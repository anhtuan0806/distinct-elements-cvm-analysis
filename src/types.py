"""Data contracts and schemas for the CVM-A1 benchmark pipeline.

This module defines the typed configurations, results, and CSV headers
ensuring strict schema conformance across the entire benchmark workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Immutable CSV header definition: 13 columns strictly ordered.
CSV_HEADER: Final[str] = (
    "m,n,F0,epsilon,delta,seed,estimate,abort,runtime_ms,peak_memory_kb,"
    "max_buffer_size,halving_count,rel_error"
)

CSV_COLUMNS: Final[tuple[str, ...]] = tuple(CSV_HEADER.split(","))


@dataclass(frozen=True)
class ExperimentConfig:
    """Configuration parameters for a single CVM experiment run.

    Attributes:
        m: Total length of the data stream (total token count).
        n: Universe size (cardinality of the domain of items).
        f0: Ground truth number of distinct elements (F0) in the stream.
        epsilon: Target accuracy parameter (relative error tolerance, 0 < eps < 1).
        delta: Failure probability bound (0 < delta < 1).
        seed: Random seed for deterministic stream generation and algorithm execution.
    """

    m: int
    n: int
    f0: int
    epsilon: float
    delta: float
    seed: int

    def __post_init__(self) -> None:
        """Validate parameter domain integrity."""
        if self.m <= 0:
            raise ValueError(f"Stream length 'm' must be positive, got {self.m}")
        if self.n <= 0:
            raise ValueError(f"Universe size 'n' must be positive, got {self.n}")
        if self.f0 < 0:
            raise ValueError(f"Distinct elements 'f0' must be non-negative, got {self.f0}")
        if self.f0 > self.n:
            raise ValueError(
                f"Distinct elements 'f0' ({self.f0}) cannot exceed universe size 'n' ({self.n})"
            )
        if self.f0 > self.m:
            raise ValueError(
                f"Distinct elements 'f0' ({self.f0}) cannot exceed stream length 'm' ({self.m})"
            )
        if not (0.0 < self.epsilon < 1.0):
            raise ValueError(f"Epsilon must be in (0, 1), got {self.epsilon}")
        if not (0.0 < self.delta < 1.0):
            raise ValueError(f"Delta must be in (0, 1), got {self.delta}")


@dataclass(frozen=True)
class CVMResult:
    """Execution output and performance metrics from the CVM-A1 algorithm.

    Attributes:
        estimate: Estimated number of distinct elements (F0).
        abort: Flag indicating early termination (e.g. buffer exhaustion or underflow).
        runtime_ms: Wall-clock execution time in milliseconds.
        peak_memory_kb: Peak memory allocation in kilobytes (KB).
        max_buffer_size: Maximum buffer capacity |X| reached during the stream processing.
        halving_count: Total number of times sampling probability p was halved.
        error_msg: Optional error description or diagnostic message when aborted.
    """

    estimate: float
    abort: bool
    runtime_ms: float
    peak_memory_kb: float
    max_buffer_size: int
    halving_count: int
    error_msg: str | None = None

