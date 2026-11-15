"""Validate the current TV3 RAW contract and classify datasets for analysis."""

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID

from src.benchmark_report import COMPLETED, PROTOCOL_VERSION, STATUSES
from src.stream_generator import Distribution
from src.types import CSV_COLUMNS, compute_cvm_threshold

U64 = (1 << 64) - 1
CONFIG = dict.fromkeys(("algorithm", "workload", "m", "n", "epsilon", "delta", "env_os")) | {
    "F0": "f0"
}
SEQUENCE = ("trial", "seed_generator", "seed_algorithm")
IDENTITY = ("git_commit", "source_tree_sha256", "generator_sha256")
ENVIRONMENT = ("python", "cpu", "binary_sha256")
SYNTHETIC = re.compile(r"synthetic|dry[-_ ]?run|mock", re.I)


@dataclass
class ValidationReport:
    classification: str = "unverified"
    rows: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def verified(self):
        return self.classification == "verified_real"


def integer(value, name, low, high, *, optional=False):
    if optional and value == "":
        return None
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if not low <= result <= high:
        raise ValueError(f"{name} must be in [{low}, {high}]")
    return result


def number(value, name, *, optional=False, signed=False):
    if optional and value == "":
        return None
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or (not signed and result < 0):
        raise ValueError(f"{name} must be finite and in range")
    return result


def uuid_value(value, name):
    try:
        if str(UUID(value)) != value.lower():
            raise ValueError
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def parse_row(raw, warnings):
    row = dict(raw)
    uuid_value(row["run_id"], "run_id")
    if row["algorithm"] != "CVM-A1":
        raise ValueError("algorithm must be CVM-A1")
    if row["workload"] not in {item.value for item in Distribution}:
        raise ValueError("unsupported workload")
    status = row["status"]
    if status not in STATUSES:
        raise ValueError(f"invalid status {status!r}")
    completed = status in COMPLETED
    for name in ("env_os", "compiler", "build_flags"):
        if not row[name].strip():
            raise ValueError(f"{name} is required")
    for name, low, high in (
        ("m", 1, U64),
        ("n", 1, U64 + 1),
        ("F0", 0, U64),
        ("trial", 1, U64),
        ("seed_generator", 0, U64),
        ("seed_algorithm", 0, U64),
        ("s", 1, U64),
        ("peak_sample_size", 0, U64),
        ("halving_count", 0, U64),
        ("process_peak_memory_bytes", 1, U64),
    ):
        optional = name == "process_peak_memory_bytes" or (name == "s" and not completed)
        row[name] = integer(raw[name], name, low, high, optional=optional)
    for name in ("epsilon", "delta"):
        row[name] = number(raw[name], name)
        if not 0 < row[name] < 1:
            raise ValueError(f"{name} must be in (0, 1)")
    for name in (
        "estimate",
        "algorithm_runtime_ms",
        "end_to_end_runtime_ms",
        "signed_rel_error",
        "abs_rel_error",
    ):
        row[name] = number(raw[name], name, optional=True, signed=name == "signed_rel_error")

    m, n, f0, threshold = (row[key] for key in ("m", "n", "F0", "s"))
    if f0 > min(m, n):
        raise ValueError("F0 exceeds min(m, n)")
    if (row["workload"] == "all_distinct" and f0 != m) or (
        row["workload"] == "all_duplicate" and f0 != 1
    ):
        raise ValueError("F0 is inconsistent with workload")
    if threshold is not None:
        try:
            reference = compute_cvm_threshold(m, row["epsilon"], row["delta"])
        except ArithmeticError:
            reference = None
        if threshold != reference:
            warnings.append(f"s={threshold} from Core differs from Python reference {reference}")

    peak, halving = row["peak_sample_size"], row["halving_count"]
    if peak > min(m, f0) or (threshold is not None and peak > threshold):
        raise ValueError("peak_sample_size exceeds m, F0 or s")
    if halving > m or (completed and (halving > 0) != (peak == threshold)):
        raise ValueError("halving_count is inconsistent with m, peak_sample_size or s")
    if status == "algorithm_abort" and halving == 0:
        raise ValueError("algorithm_abort requires halving_count >= 1")
    runtime, wall = row["algorithm_runtime_ms"], row["end_to_end_runtime_ms"]
    if completed and (runtime is None or wall is None):
        raise ValueError("algorithm_runtime_ms and end_to_end_runtime_ms are required")
    if runtime is not None and wall is not None and runtime > wall + 0.001:
        raise ValueError("algorithm_runtime_ms exceeds end_to_end_runtime_ms")

    estimate, signed, absolute = (row[k] for k in ("estimate", "signed_rel_error", "abs_rel_error"))
    if (estimate is not None) != (status == "success"):
        raise ValueError("estimate must exist only on success")
    if status == "success" and f0:
        expected = (estimate - f0) / f0
        if (
            signed is None
            or absolute is None
            or abs(signed - expected) > 0.005 / f0 + 0.000001
            or abs(abs(signed) - absolute) > 0.000001
        ):
            raise ValueError("signed_rel_error or abs_rel_error is inconsistent with estimate/F0")
    elif signed is not None or absolute is not None:
        raise ValueError("relative errors must be empty on non-success or F0=0")
    return row


def digest(value, lengths):
    return isinstance(value, str) and len(value) in lengths and re.fullmatch("[0-9a-f]+", value)


def batch_rows(batch, rows, raw_config):
    start = raw_config.get("trial")
    count = batch["requested_trials"]
    if type(start) is not int or start < 1 or type(count) is not int or count < 1:
        raise ValueError("invalid trial start or requested_trials")
    previous = -1
    for index, row in rows:
        if row is None:
            continue
        for column, config_key in CONFIG.items():
            if row[column] != raw_config.get(config_key or column):
                raise ValueError(f"record {index}: {column} differs from batch configuration")
        offset = row["trial"] - start
        if not previous < offset < count:
            raise ValueError(f"record {index}: trial is outside batch range or out of order")
        previous = offset
        for name in SEQUENCE[1:]:
            seed = raw_config.get(name)
            if type(seed) is not int or not 0 <= seed <= U64 or row[name] != seed + offset:
                raise ValueError(f"record {index}: {name} differs from batch seed sequence")
        env = batch["environment"]
        for name in ("compiler", "build_flags"):
            if row[name] != env[name]:
                raise ValueError(f"record {index}: {name} differs from batch environment")
        row.update({key: batch[key] for key in IDENTITY})
        row.update({key: env[key] for key in ENVIRONMENT})
        row["platform_os"] = env["os"]


def check_metadata(metadata, content, path, rows):
    checks = {
        "schema_version": "P0",
        "target_csv": path.name,
        "records_count": len(rows),
        "byte_length": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    for key, expected in checks.items():
        actual = metadata.get(key)
        if type(actual) is not type(expected) or actual != expected:
            raise ValueError(f"metadata {key} does not match RAW (expected {expected})")
    if "pending" in metadata:
        raise ValueError("metadata contains an unfinished pending record")
    if any(metadata.get(key) != "real" for key in ("execution_mode", "data_source")):
        raise ValueError("metadata execution_mode and data_source must both be real")
    if not rows or not isinstance(metadata.get("batches"), list):
        raise ValueError("metadata must cover a nonempty dataset with batches")

    first = 1
    seen = set()
    for batch in metadata["batches"]:
        if not isinstance(batch, dict):
            raise ValueError("invalid metadata batch")
        last = batch.get("last_record")
        if (
            type(batch.get("first_record")) is not int
            or batch["first_record"] != first
            or type(last) is not int
            or not first <= last <= len(rows)
        ):
            raise ValueError("metadata batch ranges must be contiguous and cover the RAW")
        batch_id = batch.get("batch_id")
        uuid_value(batch_id, "batch_id")
        if batch_id in seen:
            raise ValueError("duplicate batch_id")
        seen.add(batch_id)
        started = datetime.fromisoformat(batch["started_at"])
        if started.utcoffset() is None:
            raise ValueError("batch started_at requires timezone")
        for key in IDENTITY:
            lengths = (40, 64) if key == "git_commit" else (64,)
            if not digest(batch.get(key), lengths):
                raise ValueError(f"missing or invalid batch {key}")
        env = batch.get("environment")
        if not isinstance(env, dict) or not digest(env.get("binary_sha256"), (64,)):
            raise ValueError("missing or invalid binary_sha256")
        for key in ("os", "python", "cpu", "compiler", "build_flags"):
            value = env.get(key)
            if not isinstance(value, str) or value.strip().lower() in {"", "unknown", "none"}:
                raise ValueError(f"missing or unknown environment {key}")
        if env.get("memory_metric") != "core_peak_resident_bytes":
            raise ValueError("unknown process memory metric")
        if batch.get("version") != [env["binary_sha256"], batch["generator_sha256"], env["python"]]:
            raise ValueError("batch version does not match binary/generator/Python identity")
        config = batch.get("configuration")
        if not isinstance(config, dict):
            raise ValueError("missing batch configuration")
        batch_rows(batch, enumerate(rows[first - 1 : last], start=first), config)
        first = last + 1
    if first != len(rows) + 1:
        raise ValueError("metadata batches do not cover all records")


def validate(path, metadata_path=None):
    path = Path(path)
    metadata_path = Path(metadata_path) if metadata_path else path.with_suffix(".metadata.json")
    report = ValidationReport()
    metadata = {}
    synthetic = bool(SYNTHETIC.search(path.stem)) or any(
        part.lower() in {"synthetic", "synthetic_mock", "dry_run"} for part in path.parts[:-1]
    )
    legacy = False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("sidecar must be a JSON object")
        if not metadata:
            raise ValueError("sidecar is empty")
    except FileNotFoundError:
        legacy = True
        report.errors.append(f"missing metadata sidecar {metadata_path}")
    except (OSError, ValueError) as exc:
        report.errors.append(f"invalid metadata: {exc}")
        metadata = {}
    synthetic |= any(
        SYNTHETIC.search(str(metadata.get(key, ""))) is not None
        for key in ("execution_mode", "data_source")
    )

    rows = []
    run_ids = set()
    try:
        content = path.read_bytes()
        reader = csv.reader(io.StringIO(content.decode("utf-8"), newline=""), strict=True)
        header = next(reader, [])
        if header != list(CSV_COLUMNS):
            missing = ", ".join(key for key in CSV_COLUMNS if key not in header) or "none"
            raise ValueError(f"RAW header differs from 24-column schema; missing: {missing}")
        for index, values in enumerate(reader, start=1):
            rows.append(None)
            if len(values) != len(CSV_COLUMNS):
                report.errors.append(f"record {index}: expected 24 columns, got {len(values)}")
                continue
            raw = dict(zip(CSV_COLUMNS, values, strict=True))
            if any(SYNTHETIC.search(raw[key]) for key in ("algorithm", "compiler", "workload")):
                synthetic = True
                continue
            run_id = raw["run_id"].lower()
            if run_id in run_ids:
                report.errors.append(f"record {index}: duplicate run_id")
            run_ids.add(run_id)
            warnings = []
            try:
                rows[-1] = parse_row(raw, warnings)
            except ValueError as exc:
                report.errors.append(f"record {index}: {exc}")
            report.warnings.extend(f"record {index}: {warning}" for warning in warnings)
    except (OSError, ValueError, csv.Error) as exc:
        report.errors.append(f"RAW: {exc}")
        content = b""

    if synthetic:
        report.classification = "synthetic"
        report.errors.append("synthetic/dry-run data is ineligible for benchmark analysis")
        return report
    if metadata and metadata.get("protocol_version") != PROTOCOL_VERSION:
        legacy = True
        report.errors.append("historical/unverified metadata protocol")
        if "records_count" in metadata and metadata["records_count"] != len(rows):
            report.errors.append(f"metadata records_count differs from RAW ({len(rows)})")
        if "sha256" in metadata and metadata["sha256"] != hashlib.sha256(content).hexdigest():
            report.errors.append("metadata sha256 differs from RAW")
    elif metadata and content:
        try:
            check_metadata(metadata, content, path, rows)
        except (ValueError, KeyError, TypeError) as exc:
            report.errors.append(f"metadata: {exc}")

    completed = set()
    report.rows = [row for row in rows if row is not None]
    for row in report.rows:
        if row["status"] in COMPLETED:
            key = tuple(
                row.get(name)
                for name in (
                    *IDENTITY,
                    *ENVIRONMENT,
                    "platform_os",
                    "compiler",
                    "build_flags",
                    *CONFIG,
                    *SEQUENCE,
                )
            )
            if key in completed:
                report.errors.append(f"duplicate completed trial: {row['run_id']}")
            completed.add(key)
    if not report.errors:
        report.classification = "verified_real"
    elif not legacy:
        report.classification = "invalid"
    return report


def verified_rows(path, metadata=None):
    report = validate(path, metadata)
    for warning in report.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if not report.verified:
        raise ValueError(f"{report.classification}: " + "\n".join(report.errors))
    return report.rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args(argv)
    report = validate(args.raw, args.metadata)
    for label, messages in (("ERROR", report.errors), ("WARNING", report.warnings)):
        for message in messages:
            print(f"{label}: {message}", file=sys.stderr)
    print(f"{report.classification}: {len(report.rows)} parsed records")
    return 0 if report.verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
