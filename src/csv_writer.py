"""Schema-first CSV Report Writer for the CVM-A1 benchmark suite.

Cooperating writers use cross-platform file locks (POSIX flock on Unix/Linux/WSL,
msvcrt on Windows) to serialize initialization and append. Completed records are
flushed and fsynced; incompatible headers and malformed final records are rejected
before the report is changed.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from typing import BinaryIO

try:
    import fcntl

    _HAS_FCNTL = True
except ImportError:
    fcntl = None  # type: ignore[assignment]
    _HAS_FCNTL = False

try:
    import msvcrt

    _HAS_MSVCRT = True
except ImportError:
    msvcrt = None  # type: ignore[assignment]
    _HAS_MSVCRT = False

from src.types import (
    CSV_COLUMNS,
    CSV_HEADER,
    CVMResult,
    ExperimentConfig,
    ExperimentStatus,
)


def compute_relative_errors(
    f0: int,
    estimate: float | None,
    status: ExperimentStatus,
) -> tuple[str, str]:
    """Calculate signed and absolute relative errors formatted as strings.

    Rules:
        - If status is not SUCCESS or estimate is None, returns ('', '').
        - If ground-truth f0 is 0, returns ('', '') to avoid division by zero.
        - Otherwise returns (signed_rel_error, abs_rel_error) formatted to 6 decimal places:
          signed = (estimate - f0) / f0
          abs = |estimate - f0| / f0
    """
    if status != ExperimentStatus.SUCCESS or estimate is None or f0 == 0:
        return "", ""

    signed_error = (estimate - f0) / f0
    abs_error = abs(estimate - f0) / f0
    return f"{signed_error:.6f}", f"{abs_error:.6f}"


def compute_rel_error(f0: int, estimate: float | None, abort: bool) -> str:
    """Backward-compatible helper returning absolute relative error or 'NA'."""
    if abort or estimate is None or f0 == 0:
        return "NA"
    return f"{abs(estimate - f0) / f0:.6f}"


def format_csv_record(config: ExperimentConfig, result: CVMResult) -> list[str]:
    """Convert an ExperimentConfig and CVMResult into a standardized 24-column CSV row.

    Ensures strict formatting according to P0 specification:
        - Status is mapped to its enum string value.
        - estimate: 2 decimal places if success, else empty string.
        - algorithm_runtime_ms / end_to_end_runtime_ms: 3 decimal places if present, else empty.
        - signed_rel_error / abs_rel_error: 6 decimal places if success and f0 > 0, else empty.
        - Environment and compiler flags are recorded without delimiter conflicts.
    """
    signed_rel, abs_rel = compute_relative_errors(config.f0, result.estimate, result.status)

    estimate_str = (
        f"{result.estimate:.2f}"
        if result.status == ExperimentStatus.SUCCESS and result.estimate is not None
        else ""
    )
    alg_runtime_str = (
        f"{result.algorithm_runtime_ms:.3f}" if result.algorithm_runtime_ms is not None else ""
    )
    e2e_runtime_str = (
        f"{result.end_to_end_runtime_ms:.3f}" if result.end_to_end_runtime_ms is not None else ""
    )
    peak_mem_str = (
        str(result.process_peak_memory_bytes)
        if result.process_peak_memory_bytes is not None
        else ""
    )

    return [
        str(config.run_id),
        str(config.algorithm),
        str(config.workload),
        str(config.trial),
        str(config.m),
        str(config.n),
        str(config.f0),
        str(config.epsilon),
        str(config.delta),
        str(config.s),
        str(config.seed_generator),
        str(config.seed_algorithm),
        result.status.value,
        estimate_str,
        alg_runtime_str,
        e2e_runtime_str,
        str(result.peak_sample_size),
        str(result.halving_count),
        peak_mem_str,
        signed_rel,
        abs_rel,
        str(config.env_os),
        str(config.compiler),
        str(config.build_flags),
    ]


class CSVReportWriter:
    """CSV reporter with schema checks, cross-platform locking, and durable completed writes.

    Existing files are never truncated. A complete final record without a newline
    is separated before append; a malformed tail is left untouched for inspection.
    """

    def __init__(self, filepath: Path | str) -> None:
        self.filepath: Path = Path(filepath).resolve()
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def _ensure_header(self) -> None:
        """Initialize or validate the report while holding its exclusive lock."""
        with self._locked_report() as report:
            if self._prepare_report(report):
                report.flush()
                os.fsync(report.fileno())

    @contextmanager
    def _locked_report(self) -> Iterator[BinaryIO]:
        # a+b creates missing files without truncating another writer's records.
        with open(self.filepath, mode="a+b") as report:
            fileno = report.fileno()
            if _HAS_FCNTL:
                fcntl.flock(fileno, fcntl.LOCK_EX)
                try:
                    yield report
                finally:
                    fcntl.flock(fileno, fcntl.LOCK_UN)
            elif _HAS_MSVCRT:
                cur_pos = report.tell()
                report.seek(0)
                msvcrt.locking(fileno, msvcrt.LK_LOCK, 1)
                report.seek(cur_pos)
                try:
                    yield report
                finally:
                    cur_pos = report.tell()
                    report.seek(0)
                    msvcrt.locking(fileno, msvcrt.LK_UNLCK, 1)
                    report.seek(cur_pos)
            else:
                yield report

    def _parse_line(self, raw: bytes) -> list[str]:
        try:
            return next(csv.reader([raw.decode("utf-8")], strict=True))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ValueError(f"Invalid CSV record in {self.filepath}: {exc}") from exc

    @staticmethod
    def _last_record(report: BinaryIO, header_size: int, size: int) -> bytes:
        """Read backwards in chunks, stopping at the last record's separator."""
        report.seek(max(0, size - 2))
        ending = report.read(2)
        cursor = size
        if ending.endswith(b"\r\n"):
            cursor -= 2
        elif ending.endswith((b"\r", b"\n")):
            cursor -= 1

        chunks: list[bytes] = []
        while cursor > header_size:
            start = max(header_size, cursor - 4096)
            report.seek(start)
            chunk = report.read(cursor - start)
            separator = max(chunk.rfind(b"\n"), chunk.rfind(b"\r"))
            if separator >= 0:
                chunks.append(chunk[separator + 1 :])
                break
            chunks.append(chunk)
            cursor = start
        return b"".join(reversed(chunks))

    def _prepare_report(self, report: BinaryIO) -> bool:
        """Validate before changing bytes; return whether a separator was written."""
        report.seek(0)
        header = report.readline()
        if not header:
            report.write((CSV_HEADER + "\n").encode("utf-8"))
            return True
        if self._parse_line(header) != list(CSV_COLUMNS):
            raise ValueError(f"CSV header mismatch in {self.filepath}; expected {CSV_HEADER}")

        size = report.seek(0, os.SEEK_END)
        if size > len(header):
            last_row = self._parse_line(self._last_record(report, len(header), size))
            if len(last_row) != len(CSV_COLUMNS):
                raise ValueError(f"Incomplete or invalid final CSV record in {self.filepath}")
            # Ensure mandatory identifier and parameter fields are not empty
            mandatory_indices = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 16, 17, 21, 22, 23)
            if any(last_row[idx] == "" for idx in mandatory_indices):
                raise ValueError(f"Missing mandatory fields in final CSV record in {self.filepath}")

        report.seek(size - 1)
        if report.read(1) not in (b"\r", b"\n"):
            report.write(b"\n")
            return True
        return False

    def write_record(self, config: ExperimentConfig, result: CVMResult) -> None:
        """Append a single benchmark record to the CSV file.

        Immediately flushes user-space buffers and issues os.fsync() to commit
        bytes directly to physical storage.
        """
        row = format_csv_record(config, result)
        if len(row) != len(CSV_COLUMNS):
            raise ValueError(
                f"Row column mismatch: expected {len(CSV_COLUMNS)} values, got {len(row)}"
            )

        buffer = StringIO(newline="")
        csv.writer(buffer).writerow(row)
        with self._locked_report() as report:
            self._prepare_report(report)
            report.write(buffer.getvalue().encode("utf-8"))
            report.flush()
            os.fsync(report.fileno())
