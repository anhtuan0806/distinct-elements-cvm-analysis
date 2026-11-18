"""Managed RAW CSV with serialized resume and recoverable provenance updates."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from src.csv_writer import CSVReportWriter, format_csv_record
from src.types import CSV_COLUMNS, CSV_HEADER, CVMResult, ExperimentConfig, ExperimentStatus

PROTOCOL_VERSION = "cvm-a1-tv3-v1"
HEADER = (CSV_HEADER + "\n").encode("utf-8")
COMPLETED = {ExperimentStatus.SUCCESS.value, ExperimentStatus.ALGORITHM_ABORT.value}
STATUSES = {status.value for status in ExperimentStatus}
ROW_CONFIG = {
    1: "algorithm",
    2: "workload",
    4: "m",
    5: "n",
    6: "f0",
    7: "epsilon",
    8: "delta",
    21: "env_os",
}


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _validate_batch(batch: dict, mode: str) -> list[str]:
    env = batch.get("environment")
    config = batch.get("configuration")
    if not isinstance(env, dict) or not isinstance(config, dict):
        raise ValueError("Invalid batch metadata environment or configuration")
    binary = env.get("binary_sha256")
    generator = batch.get("generator_sha256")
    python = env.get("python")
    if (
        not _is_sha256(generator)
        or (not _is_sha256(binary) if mode == "real" else binary is not None)
        or "binary_sha256" not in env
        or not isinstance(python, str)
        or not python.strip()
        or batch.get("version") != [binary if mode == "real" else mode, generator, python]
    ):
        raise ValueError("Invalid batch metadata version: binary, generator or Python mismatch")
    for key in ("os", "cpu", "compiler", "build_flags"):
        if not isinstance(env.get(key), str) or not env[key].strip():
            raise ValueError(f"Invalid batch metadata environment field {key}")
    if "memory_metric" not in env or env["memory_metric"] != (
        "core_peak_resident_bytes" if mode == "real" else None
    ):
        raise ValueError("Invalid batch metadata memory metric")
    if not isinstance(batch.get("batch_id"), str) or not batch["batch_id"].strip():
        raise ValueError("Invalid batch metadata ID")
    started = batch.get("started_at")
    try:
        if not isinstance(started, str) or datetime.fromisoformat(started).utcoffset() is None:
            raise ValueError
    except ValueError as exc:
        raise ValueError("Invalid batch metadata start time") from exc
    commit = batch.get("git_commit")
    if (
        not _is_sha256(batch.get("source_tree_sha256"))
        or "git_commit" not in batch
        or (
            commit is not None
            and (
                not isinstance(commit, str)
                or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit)
            )
        )
    ):
        raise ValueError("Invalid batch metadata source identity")
    count = batch.get("requested_trials")
    if type(count) is not int or count < 1:
        raise ValueError("Invalid batch metadata requested_trials")
    for key in ("m", "n", "f0", "trial", "s", "seed_generator", "seed_algorithm"):
        if type(config.get(key)) is not int:
            raise ValueError(f"Invalid batch metadata configuration field {key}")
    if (
        not 0 < config["m"] < 2**64
        or not 0 < config["n"] <= 2**64
        or not 0 <= config["f0"] <= min(config["m"], config["n"])
        or config["trial"] < 1
        or config["s"] < 1
        or any(not 0 <= config[key] < 2**64 for key in ("seed_generator", "seed_algorithm"))
    ):
        raise ValueError("Invalid batch metadata configuration range")
    for key in ("epsilon", "delta"):
        if type(config.get(key)) not in (int, float) or not 0 < config[key] < 1:
            raise ValueError(f"Invalid batch metadata configuration field {key}")
    for key in ("algorithm", "workload", "env_os", "compiler", "build_flags"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"Invalid batch metadata configuration field {key}")
    return batch["version"]


def _check_batch_row(batch: dict, row: list[str], mode: str) -> int:
    config = batch["configuration"]
    for index, key in ROW_CONFIG.items():
        if row[index] != str(config[key]):
            raise ValueError(f"Batch metadata configuration {key} differs from RAW")
    env = batch["environment"]
    if row[22:24] != [env["compiler"], env["build_flags"]]:
        raise ValueError("Batch metadata compiler or build flags differ from RAW")
    try:
        offset = int(row[3]) - config["trial"]
        seeds_match = row[10:12] == [
            str(config[key] + offset) for key in ("seed_generator", "seed_algorithm")
        ]
    except ValueError as exc:
        raise ValueError("Invalid RAW trial for batch metadata") from exc
    if (
        not 0 <= offset < batch["requested_trials"]
        or not seeds_match
        or (mode == "synthetic_mock" and (offset != 0 or row[9] != str(config["s"])))
    ):
        raise ValueError("Batch metadata trial, seeds or synthetic threshold differ from RAW")
    return offset


def resolve_output(path: str | None, mode: str, project_root: Path) -> Path:
    default = (
        "results/real/raw_benchmark.csv" if mode == "real" else "results/synthetic/dry_run.csv"
    )
    target = Path(path or default).resolve()
    if target.suffix.lower() != ".csv":
        raise ValueError("Output must have a .csv extension")
    for root in (Path.cwd(), project_root):
        results = root / "results"
        if mode == "synthetic_mock" and (
            target.is_relative_to((results / "real").resolve())
            or target == (results / "raw_benchmark.csv").resolve()
        ):
            raise ValueError("Dry-run output cannot target the real results directory")
        if mode == "real" and target.is_relative_to((results / "synthetic").resolve()):
            raise ValueError("Real output cannot target the synthetic results directory")
    return target


def _trial_key(fields: list[str], version: list[str], mode: str) -> tuple[str, ...]:
    if mode == "synthetic_mock":
        return (*version, *fields[1:13])
    # Real s is an output of this binary and these inputs. Replay only knows
    # the Python reference, which can differ at an integer rounding boundary.
    return (*version, *fields[1:9], *fields[10:12])


class BenchmarkReport:
    """One locked session owns CSV writes and matching metadata changes."""

    @classmethod
    @contextmanager
    def open(cls, path: Path, mode: str, batch: dict) -> Iterator[BenchmarkReport]:
        _validate_batch(batch, mode)
        writer = CSVReportWriter(path, initialize=False)
        with writer._locked_report() as stream:
            if os.fstat(stream.fileno()).st_nlink > 1:
                raise ValueError("Hard-linked CSV outputs are unsupported")
            yield cls(stream, writer.filepath, mode, batch)

    def __init__(self, stream: BinaryIO, path: Path, mode: str, batch: dict) -> None:
        self.stream = stream
        self.filename = path.name
        self.sidecar = path.with_suffix(".metadata.json")
        self.mode = mode
        self.batch = batch
        self.completed: set[tuple[str, ...]] = set()
        self.run_ids: set[str] = set()
        self.state, content = self._open_state()
        self.digest = hashlib.sha256(content)
        self._index(content)

    def _save(self, state: dict) -> None:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.sidecar.parent, delete=False
        ) as staged:
            temporary = Path(staged.name)
            try:
                json.dump(state, staged, ensure_ascii=False, allow_nan=False)
                staged.write("\n")
                staged.flush()
                os.fsync(staged.fileno())
            except BaseException:
                staged.close()
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, self.sidecar)
        finally:
            temporary.unlink(missing_ok=True)

    def _write_bytes(self, data: bytes) -> None:
        if self.stream.write(data) != len(data):
            raise OSError("Incomplete CSV write; run again to recover the pending record")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def _open_state(self) -> tuple[dict, bytes]:
        self.stream.seek(0)
        content = self.stream.read()
        if not self.sidecar.exists():
            if content:
                raise ValueError("Legacy/unverified CSV without metadata; choose a new --out")
            state = {
                "schema_version": "P0",
                "protocol_version": PROTOCOL_VERSION,
                "data_source": self.mode,
                "execution_mode": self.mode,
                "target_csv": self.filename,
                "records_count": 0,
                "byte_length": len(HEADER),
                "sha256": hashlib.sha256(HEADER).hexdigest(),
                "batches": [],
            }
            self._save(state)
        else:
            try:
                state = json.loads(self.sidecar.read_text(encoding="utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("Unreadable dataset metadata; CSV preserved") from exc
            if not isinstance(state, dict) or state.get("protocol_version") != PROTOCOL_VERSION:
                raise ValueError("Legacy/unverified metadata; choose a new --out")
            if state.get("execution_mode") != self.mode or state.get("data_source") != self.mode:
                raise ValueError("Output belongs to a different execution mode")

        count = state.get("records_count")
        length = state.get("byte_length")
        if (
            state.get("schema_version") != "P0"
            or state.get("target_csv") != self.filename
            or type(count) is not int
            or count < 0
            or type(length) is not int
            or length < len(HEADER)
            or not isinstance(state.get("batches"), list)
        ):
            raise ValueError("Invalid dataset metadata")

        # Stage a missing header in memory until metadata and pending are verified.
        header_tail = b""
        if count == 0 and length == len(HEADER) and HEADER.startswith(content):
            header_tail = HEADER[len(content) :]
            content = HEADER
        prefix, tail = content[:length], content[length:]
        if len(prefix) != length or hashlib.sha256(prefix).hexdigest() != state.get("sha256"):
            raise ValueError("RAW content does not match metadata; CSV preserved")

        if "pending" in state:
            pending = state["pending"]
            if (
                not isinstance(pending, dict)
                or not isinstance(pending.get("record"), str)
                or not isinstance(pending.get("batch"), dict)
            ):
                raise ValueError("Invalid pending record in dataset metadata")
            pending_batch = pending["batch"]
            _validate_batch(pending_batch, self.mode)
            self._index(prefix, state, remember=False)
            if state["batches"] and state["batches"][-1]["batch_id"] == pending_batch["batch_id"]:
                previous = state["batches"][-1]
                if pending_batch != {
                    key: value
                    for key, value in previous.items()
                    if key not in ("first_record", "last_record")
                }:
                    raise ValueError("Pending batch metadata differs from its committed batch")
            record = pending["record"].encode("utf-8")
            if not record.startswith(tail):
                raise ValueError("RAW tail differs from the pending record; CSV preserved")
            final = self._advanced(state, pending_batch, record, hashlib.sha256(prefix))
            # Validate the planned dataset before modifying the interrupted file.
            self._index(prefix + record, final, remember=False)
            if header_tail or tail != record:
                self._write_bytes(header_tail + record[len(tail) :])
            else:
                os.fsync(self.stream.fileno())
            self._save(final)
            return final, prefix + record
        if tail:
            raise ValueError("RAW has untracked bytes after its recorded end; CSV preserved")
        if header_tail:
            self._index(content, state, remember=False)
            self._write_bytes(header_tail)
        return state, content

    def _index(self, content: bytes, state: dict | None = None, *, remember: bool = True) -> None:
        state = self.state if state is None else state
        reader = csv.reader(StringIO(content.decode("utf-8"), newline=""), strict=True)
        if next(reader, None) != list(CSV_COLUMNS):
            raise ValueError("RAW CSV header mismatch")
        complete = self.completed if remember else set()
        run_ids = self.run_ids if remember else set()
        batch_ids = set()
        count = 0
        for batch in state["batches"]:
            if not isinstance(batch, dict):
                raise ValueError("Invalid batch in dataset metadata")
            last = batch["last_record"]
            if (
                type(last) is not int
                or type(batch.get("first_record")) is not int
                or batch["first_record"] != count + 1
                or not count < last <= state["records_count"]
            ):
                raise ValueError("Metadata batch ranges are not contiguous")
            version = _validate_batch(batch, self.mode)
            batch_id = batch["batch_id"]
            if batch_id in batch_ids:
                raise ValueError("Duplicate batch metadata ID")
            batch_ids.add(batch_id)
            previous_offset = -1
            for _ in range(count, last):
                row = next(reader, None)
                if row is None or len(row) != len(CSV_COLUMNS):
                    raise ValueError("RAW CSV is missing records described in metadata")
                if not row[0] or row[0] in run_ids:
                    raise ValueError("Duplicate or missing run_id in RAW")
                run_ids.add(row[0])
                expected = "CVM-A1" if self.mode == "real" else "CVM-A1-dryrun"
                if row[1] != expected or row[12] not in STATUSES:
                    raise ValueError("RAW algorithm or status does not match the dataset contract")
                offset = _check_batch_row(batch, row, self.mode)
                if self.mode == "real" and offset <= previous_offset:
                    raise ValueError("RAW trial order differs from batch metadata")
                previous_offset = offset
                if row[12] == ExperimentStatus.SUCCESS.value:
                    estimate = float(row[13])
                    if not math.isfinite(estimate) or estimate < 0:
                        raise ValueError("Invalid estimate on completed RAW trial")
                elif any(row[index] for index in (13, 19, 20)):
                    raise ValueError("Non-success RAW trial contains estimate or errors")
                if row[12] in COMPLETED:
                    if not 0 < int(row[9]) < 2**64:
                        raise ValueError("Completed RAW trial has an invalid threshold")
                    key = _trial_key(row, version, self.mode)
                    if key in complete:
                        raise ValueError("Duplicate completed logical trial in RAW")
                    complete.add(key)
                count += 1
        if count != state["records_count"] or next(reader, None) is not None:
            raise ValueError("RAW record count does not match metadata")

    @staticmethod
    def _advanced(state: dict, batch: dict, record: bytes, digest) -> dict:
        digest.update(record)
        count = state["records_count"] + 1
        batches = state["batches"].copy()
        if batches and batches[-1]["batch_id"] == batch["batch_id"]:
            batches[-1] = {**batches[-1], "last_record": count}
        else:
            batches.append({**batch, "first_record": count, "last_record": count})
        final = {key: value for key, value in state.items() if key != "pending"}
        final.update(
            records_count=count,
            byte_length=state["byte_length"] + len(record),
            sha256=digest.hexdigest(),
            batches=batches,
        )
        return final

    def is_complete(
        self, config: ExperimentConfig, status: ExperimentStatus = ExperimentStatus.SUCCESS
    ) -> bool:
        fields = format_csv_record(config, CVMResult(status=status))
        return _trial_key(fields, self.batch["version"], self.mode) in self.completed

    def write_record(self, config: ExperimentConfig, result: CVMResult) -> None:
        row = format_csv_record(config, result)
        if self.mode == "real":
            if result.status.value in COMPLETED and result.effective_s is None:
                raise ValueError("Completed Core trial lacks its effective threshold")
            if result.effective_s is None:
                row[9] = ""
            if result.algorithm_runtime_ms is not None:
                row[14] = repr(result.algorithm_runtime_ms)
            if result.end_to_end_runtime_ms is not None:
                row[15] = repr(result.end_to_end_runtime_ms)
        key = _trial_key(row, self.batch["version"], self.mode)
        _check_batch_row(self.batch, row, self.mode)
        if row[0] in self.run_ids or (row[12] in COMPLETED and key in self.completed):
            raise ValueError("Duplicate run ID or completed logical trial")
        buffer = StringIO(newline="")
        csv.writer(buffer).writerow(row)
        record = buffer.getvalue().encode("utf-8")
        pending = {"record": buffer.getvalue(), "batch": self.batch}
        self._save({**self.state, "pending": pending})
        self._write_bytes(record)
        self.state = self._advanced(self.state, self.batch, record, self.digest)
        self._save(self.state)
        self.run_ids.add(row[0])
        if row[12] in COMPLETED:
            self.completed.add(key)
