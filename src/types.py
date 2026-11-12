"""Data contracts and schemas for the CVM-A1 benchmark pipeline.

This module defines the typed configurations, results, status enums, and CSV headers
ensuring strict schema conformance across the entire benchmark workflow according
to the P0 specification (24 standardized columns).
"""

from __future__ import annotations

import math
import platform
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Final

# Immutable CSV header definition: exactly 24 columns strictly ordered.
CSV_HEADER: Final[str] = (
    "run_id,algorithm,workload,trial,m,n,F0,epsilon,delta,s,"
    "seed_generator,seed_algorithm,status,estimate,algorithm_runtime_ms,"
    "end_to_end_runtime_ms,peak_sample_size,halving_count,"
    "process_peak_memory_bytes,signed_rel_error,abs_rel_error,"
    "env_os,compiler,build_flags"
)

CSV_COLUMNS: Final[tuple[str, ...]] = tuple(CSV_HEADER.split(","))


class ExperimentStatus(str, Enum):
    """Execution status codes for a CVM benchmark run."""

    SUCCESS = "success"
    ALGORITHM_ABORT = "algorithm_abort"
    EXECUTION_ERROR = "execution_error"
    RESOURCE_FAILURE = "resource_failure"


def compute_cvm_threshold(m: int, epsilon: float, delta: float) -> int:
    """Compute theoretical buffer threshold s = ceil((12 / eps^2) * log2(8m / delta)).

    Matches exactly the formula in Chakraborty, Vinodchandran, Meel (2022)
    and the C++ implementation in cvm/a1.cpp.
    """
    if m <= 0 or not (0.0 < epsilon < 1.0) or not (0.0 < delta < 1.0):
        return 0
    # log2(8m / delta) = 3 + log2(m) - log2(delta)
    log_term = 3.0 + math.log2(m) - math.log2(delta)
    return math.ceil((12.0 / (epsilon * epsilon)) * log_term)


@dataclass(frozen=True)
class ExperimentConfig:
    """Configuration parameters for a single CVM experiment run.

    Attributes:
        m: Total length of the data stream (total token count).
        n: Universe size (cardinality of the domain of items).
        f0: Ground truth number of distinct elements (F0) in the stream.
        epsilon: Target accuracy parameter (relative error tolerance, 0 < eps < 1).
        delta: Failure probability bound (0 < delta < 1).
        seed_generator: Random seed for deterministic stream generation.
        seed_algorithm: Random seed for CVM algorithm sampling decisions.
        s: Buffer capacity threshold (computed if None).
        workload: Workload distribution name (e.g. uniform, skewed, zipf, all_distinct, all_duplicate).
        trial: Trial iteration index (1-based integer).
        algorithm: Algorithm identifier (default 'CVM-A1').
        run_id: Unique identifier for the benchmark run.
        env_os: Operating system descriptor.
        compiler: C++ compiler and version.
        build_flags: C++ compiler optimization flags.
    """

    m: int
    n: int
    f0: int
    epsilon: float
    delta: float
    seed_generator: int
    seed_algorithm: int
    s: int | None = None
    workload: str = "uniform"
    trial: int = 1
    algorithm: str = "CVM-A1"
    run_id: str = ""
    env_os: str = ""
    compiler: str = ""
    build_flags: str = ""

    def __post_init__(self) -> None:
        """Validate parameter domain integrity and initialize computed defaults."""
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
        if self.trial < 1:
            raise ValueError(f"Trial must be >= 1, got {self.trial}")
        if self.seed_generator < 0:
            raise ValueError(f"seed_generator must be non-negative, got {self.seed_generator}")
        if self.seed_algorithm < 0:
            raise ValueError(f"seed_algorithm must be non-negative, got {self.seed_algorithm}")

        # Compute threshold s if not explicitly provided
        if self.s is None:
            computed_s = compute_cvm_threshold(self.m, self.epsilon, self.delta)
            object.__setattr__(self, "s", computed_s)

        # Generate run_id if empty
        if not self.run_id:
            object.__setattr__(self, "run_id", str(uuid.uuid4()))

        # Auto-detect OS if empty
        if not self.env_os:
            object.__setattr__(self, "env_os", f"{platform.system()}-{platform.release()}")

        # Default compiler and build flags if empty
        if not self.compiler:
            object.__setattr__(self, "compiler", "unknown")
        if not self.build_flags:
            object.__setattr__(self, "build_flags", "none")

    @property
    def seed(self) -> int:
        """Alias returning seed_algorithm for backward compatibility."""
        return self.seed_algorithm


@dataclass(frozen=True)
class CVMResult:
    """Execution output and performance metrics from the CVM-A1 algorithm.

    Attributes:
        status: Execution status enum (success, algorithm_abort, execution_error, resource_failure).
        estimate: Estimated number of distinct elements (F0), or None if not successful.
        peak_sample_size: Maximum buffer capacity |X| reached during stream processing.
        halving_count: Total number of times sampling probability p was halved.
        algorithm_runtime_ms: Execution time of the C++ algorithm loop (excluding IPC/IO).
        end_to_end_runtime_ms: Total wall-clock time from stream start to C++ completion.
        process_peak_memory_bytes: Peak resident set size (RSS) in bytes of the C++ process.
        error_msg: Optional error description or diagnostic message when aborted or failed.
    """

    status: ExperimentStatus
    estimate: float | None = None
    peak_sample_size: int = 0
    halving_count: int = 0
    algorithm_runtime_ms: float | None = None
    end_to_end_runtime_ms: float | None = None
    process_peak_memory_bytes: int | None = None
    error_msg: str | None = None

    @property
    def abort(self) -> bool:
        """Boolean flag indicating whether execution did not succeed."""
        return self.status != ExperimentStatus.SUCCESS
