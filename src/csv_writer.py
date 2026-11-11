"""Schema-first CSV Report Writer for the CVM-A1 benchmark suite.

Cooperating writers use POSIX file locks to serialize initialization and append.
Completed records are flushed and fsynced; incompatible headers and malformed
final records are rejected before the report is changed.
"""

from __future__ import annotations

import csv
import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from typing import BinaryIO

from src.types import CSV_COLUMNS, CSV_HEADER, CVMResult, ExperimentConfig


def compute_rel_error(f0: int, estimate: float, abort: bool) -> str:
    """Calculate relative error formatted as a string.

    Rules:
        - If 'abort' is True or ground-truth 'f0' is 0, returns 'NA'.
        - Otherwise returns absolute relative error |estimate - f0| / f0
          rounded to 6 decimal places.
    """
    if abort or f0 == 0:
        return "NA"
    rel_error = abs(estimate - f0) / f0
    return f"{rel_error:.6f}"


def format_csv_record(config: ExperimentConfig, result: CVMResult) -> list[str]:
    """Convert an ExperimentConfig and CVMResult into a standardized CSV row.

    Ensures strict formatting:
        - abort: 'TRUE' or 'FALSE' uppercase.
        - estimate: 2 decimal places.
        - runtime_ms: 3 decimal places.
        - peak_memory_kb: 2 decimal places.
        - rel_error: 'NA' if aborted/f0==0, else 6 decimal places.
    """
    return [
        str(config.m),
        str(config.n),
        str(config.f0),
        str(config.epsilon),
        str(config.delta),
        str(config.seed),
        f"{result.estimate:.2f}",
        "TRUE" if result.abort else "FALSE",
        f"{result.runtime_ms:.3f}",
        f"{result.peak_memory_kb:.2f}",
        str(result.max_buffer_size),
        str(result.halving_count),
        compute_rel_error(config.f0, result.estimate, result.abort),
    ]


class CSVReportWriter:
    """CSV reporter with schema checks, POSIX locking and durable completed writes.

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
            fcntl.flock(report.fileno(), fcntl.LOCK_EX)
            try:
                yield report
            finally:
                fcntl.flock(report.fileno(), fcntl.LOCK_UN)

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
            if len(last_row) != len(CSV_COLUMNS) or any(value == "" for value in last_row):
                raise ValueError(f"Incomplete or invalid final CSV record in {self.filepath}")

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
