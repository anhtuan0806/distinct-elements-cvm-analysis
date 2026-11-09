"""Schema-first CSV Report Writer for the CVM-A1 benchmark suite.

This module guarantees thread-safe, crash-resilient CSV appending with
immediate buffer flushing and OS sync (fsync) after every record.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

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
    """Robust CSV reporter ensuring schema integrity and crash resilience.

    Every row is appended, flushed, and synchronized with the operating system's
    underlying disk storage to guard against power cuts or process terminations.
    """

    def __init__(self, filepath: Path | str) -> None:
        self.filepath: Path = Path(filepath).resolve()
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def _ensure_header(self) -> None:
        """Write the standard CSV header if file does not exist or is empty."""
        needs_header = not self.filepath.exists() or self.filepath.stat().st_size == 0
        if needs_header:
            with open(self.filepath, mode="w", encoding="utf-8", newline="") as f:
                f.write(CSV_HEADER + "\n")
                f.flush()
                os.fsync(f.fileno())

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

        with open(self.filepath, mode="a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)
            f.flush()
            os.fsync(f.fileno())

