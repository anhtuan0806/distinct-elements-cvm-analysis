"""Jupyter Notebook Adapter for CVM-A1 Real Benchmark Execution.

This module provides a clean, safe, and reproducible Python function API
enabling Jupyter Notebooks (TV2) to run real CVM-A1 benchmarks without shell
escapes or toy mock data, producing valid RAW CSV and companion provenance sidecars
that pass TV4's automated analysis validator (`verified_real`).
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner import _batch, run_single_trial
from src.benchmark_report import BenchmarkReport, resolve_output
from src.cvm.build import PROJECT_ROOT, binary_identity
from src.cvm.executor import resolve_core_binary
from src.stream_generator import Distribution
from src.types import CVMResult, ExperimentConfig, compute_cvm_threshold

logger = logging.getLogger("cvm_jupyter_adapter")

U64_MAX = (1 << 64) - 1

SMOKE_PRESET: dict[str, Any] = {
    "m": 256,
    "n": 256,
    "f0": 256,
    "epsilon": 0.9,
    "delta": 0.9,
    "workload": "all_distinct",
    "trials": 2,
}


@dataclass(frozen=True)
class JupyterBenchmarkResult:
    """Summary and handles for artifacts produced during a Jupyter benchmark session."""

    csv_path: Path
    sidecar_path: Path
    records_count: int
    configs_count: int
    results: list[dict[str, Any]]

    @property
    def to_dataframe(self) -> Any:
        """Load the resulting RAW CSV into a pandas DataFrame if pandas is installed."""
        try:
            import pandas as pd  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "pandas is required to load results into a DataFrame. "
                "Install it via `pip install pandas`."
            ) from exc
        return pd.read_csv(self.csv_path)


def _validate_and_infer_config(
    m_val: int,
    n_val: int | None,
    f0_val: int | None,
    workload_val: str,
    epsilon: float,
    delta: float,
    trials: int,
    base_gen: int,
    base_algo: int,
) -> tuple[int, int, int]:
    """Validate numeric ranges and infer domain/cardinality defaults if omitted."""
    if not isinstance(m_val, int) or isinstance(m_val, bool) or not 1 <= m_val <= U64_MAX:
        raise ValueError(f"m must be an integer in [1, {U64_MAX}] (got {m_val!r})")

    # Validate workload
    try:
        dist = Distribution(workload_val)
    except (ValueError, TypeError) as exc:
        choices = ", ".join(d.value for d in Distribution)
        raise ValueError(f"Invalid workload {workload_val!r}. Choices: {choices}") from exc

    # Infer n if not explicitly provided
    if n_val is None:
        if dist is Distribution.ALL_DISTINCT:
            inferred_n = max(m_val, 1000)
        else:
            inferred_n = max(m_val * 2, 1000)
    else:
        if not isinstance(n_val, int) or isinstance(n_val, bool) or not 1 <= n_val <= U64_MAX + 1:
            raise ValueError(f"n must be an integer in [1, {U64_MAX + 1}] (got {n_val!r})")
        inferred_n = n_val

    # Infer f0 if not explicitly provided
    if f0_val is None:
        if dist is Distribution.ALL_DISTINCT:
            inferred_f0 = m_val
        elif dist is Distribution.ALL_DUPLICATE:
            inferred_f0 = 1
        else:
            inferred_f0 = max(1, m_val // 2)
    else:
        if not isinstance(f0_val, int) or isinstance(f0_val, bool) or not 1 <= f0_val <= U64_MAX:
            raise ValueError(f"f0 must be an integer in [1, {U64_MAX}] (got {f0_val!r})")
        inferred_f0 = f0_val

    # Mathematical consistency checks
    if dist is Distribution.ALL_DISTINCT:
        if inferred_n < m_val:
            raise ValueError(
                f"all_distinct requires n >= m to draw unique IDs (got n={inferred_n}, m={m_val})"
            )
        if inferred_f0 != m_val:
            raise ValueError(f"all_distinct requires f0=m (got f0={inferred_f0}, m={m_val})")

    if dist is Distribution.ALL_DUPLICATE and inferred_f0 != 1:
        raise ValueError(f"all_duplicate requires f0=1 (got f0={inferred_f0})")

    if inferred_f0 > min(m_val, inferred_n):
        raise ValueError(
            f"f0={inferred_f0} exceeds min(m={m_val}, n={inferred_n}) for workload '{dist.value}'"
        )

    if not (0.0 < epsilon < 1.0):
        raise ValueError(f"epsilon must be in (0, 1) (got {epsilon!r})")
    if not (0.0 < delta < 1.0):
        raise ValueError(f"delta must be in (0, 1) (got {delta!r})")
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
        raise ValueError(f"trials must be a positive integer (got {trials!r})")

    for seed_name, seed_val in (("seed_generator", base_gen), ("seed_algorithm", base_algo)):
        if (
            not isinstance(seed_val, int)
            or isinstance(seed_val, bool)
            or not 0 <= seed_val <= U64_MAX
        ):
            raise ValueError(f"{seed_name} must be in [0, {U64_MAX}] (got {seed_val!r})")

    if max(base_gen, base_algo) + trials - 1 > U64_MAX:
        raise ValueError(f"Seed sequence exceeds 64-bit uint64 boundary with trials={trials}")

    return m_val, inferred_n, inferred_f0


def run_jupyter_benchmark(
    m: int | Sequence[int] | None = None,
    n: int | None = None,
    f0: int | None = None,
    epsilon: float | None = None,
    delta: float | None = None,
    workload: str | Sequence[str] | None = None,
    trials: int | None = None,
    seed: int = 42,
    seed_generator: int | None = None,
    seed_algorithm: int | None = None,
    preset: str | None = None,
    output_dir: str | Path = "results/real/jupyter",
    output_path: str | Path | None = None,
    tag: str | None = None,
    verbose: bool = True,
) -> JupyterBenchmarkResult:
    """Execute real CVM-A1 benchmark sessions with reproducible RAW CSV output and provenance.

    Parameters
    ----------
    m : int | Sequence[int] | None
        Stream length (total items). Can be a single integer or a sequence for parameter sweeps.
        Defaults to preset="smoke" if both `m` and `preset` are omitted.
    n : int | None
        Domain cardinality [0, n). If None, automatically inferred from m and workload.
    f0 : int | None
        Ground-truth distinct elements count F0. If None, automatically inferred.
    epsilon : float, default=0.05
        CVM relative error tolerance in (0, 1).
    delta : float, default=0.01
        CVM failure probability bound in (0, 1).
    workload : str | Sequence[str], default="uniform"
        Distribution name or sequence of distributions ("uniform", "skewed", "zipf",
        "all_distinct", "all_duplicate").
    trials : int, default=3
        Number of independent runs per configuration with deterministic seed stepping.
    seed : int, default=42
        Default random seed applied when specific seeds are None.
    seed_generator : int | None
        Specific seed for the synthetic stream generator.
    seed_algorithm : int | None
        Specific seed for CVM-A1 sampling decisions.
    preset : str | None
        Configuration preset name. Supported: 'smoke'.
        When 'smoke', executes a lightweight verification run (m=256, ~50 ms).
        Explicit arguments override preset values.
    output_dir : str | Path, default="results/real/jupyter"
        Target directory for session-specific RAW CSV and sidecars.
    output_path : str | Path | None
        Explicit file destination. If None, dynamically generates a unique filename
        `run_<timestamp>_<uuid>_<tag>.csv` preventing Resume locks.
    tag : str | None
        Optional identifier appended to the dynamic session filename.
    verbose : bool, default=True
        Whether to log progress to stdout/notebook display.

    Returns
    -------
    JupyterBenchmarkResult
        Dataclass containing paths to the generated RAW CSV, sidecar metadata,
        and structured records.
    """
    # 1. Parameter Precedence Resolution
    if m is None and preset is None:
        preset = "smoke"

    if preset is not None:
        if preset != "smoke":
            raise ValueError(f"Unsupported preset: {preset!r}. Supported presets: 'smoke'")
        # Baseline from preset, overridden by explicit non-None args
        effective_m = m if m is not None else SMOKE_PRESET["m"]
        effective_n = n if n is not None else SMOKE_PRESET["n"]
        effective_f0 = f0 if f0 is not None else SMOKE_PRESET["f0"]
        effective_eps = epsilon if epsilon is not None else SMOKE_PRESET["epsilon"]
        effective_delta = delta if delta is not None else SMOKE_PRESET["delta"]
        effective_workload = workload if workload is not None else SMOKE_PRESET["workload"]
        effective_trials = trials if trials is not None else SMOKE_PRESET["trials"]
    else:
        assert m is not None
        effective_m = m
        effective_n = n
        effective_f0 = f0
        effective_eps = epsilon if epsilon is not None else 0.05
        effective_delta = delta if delta is not None else 0.01
        effective_workload = workload if workload is not None else "uniform"
        effective_trials = trials if trials is not None else 3

    # 2. Normalize sweep inputs
    m_list: list[int] = [effective_m] if isinstance(effective_m, int) else list(effective_m)
    workload_list: list[str] = (
        [effective_workload] if isinstance(effective_workload, str) else list(effective_workload)
    )

    base_gen = seed_generator if seed_generator is not None else seed
    base_algo = seed_algorithm if seed_algorithm is not None else seed

    # 3. Pre-flight validation across all sweep permutations
    plan: list[tuple[int, int, int, str]] = []
    for wl in workload_list:
        for m_item in m_list:
            validated_m, validated_n, validated_f0 = _validate_and_infer_config(
                m_item,
                effective_n,
                effective_f0,
                wl,
                effective_eps,
                effective_delta,
                effective_trials,
                base_gen,
                base_algo,
            )
            plan.append((validated_m, validated_n, validated_f0, wl))

    # 4. Resolve session destination path (Rule 2.4: Dynamic per-session naming)
    if output_path is not None:
        target_csv = Path(output_path)
    else:
        out_folder = Path(output_dir)
        out_folder.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        session_id = uuid.uuid4().hex[:8]
        tag_suffix = f"_{tag}" if tag else ""
        target_csv = out_folder / f"run_{timestamp}_{session_id}{tag_suffix}.csv"

    resolved_csv = resolve_output(str(target_csv), mode="real", project_root=PROJECT_ROOT)

    # 5. Core execution setup (Rule 2.1: Subprocess per trial via run_single_trial)
    binary = resolve_core_binary()
    binary_info = binary_identity(binary)

    if verbose:
        logger.info(
            "Starting Jupyter CVM session: %d configuration(s), %d trial(s) each -> %s",
            len(plan),
            effective_trials,
            resolved_csv.name,
        )

    records: list[dict[str, Any]] = []
    total_written = 0

    # Build primary initial batch
    initial_m, initial_n, initial_f0, initial_wl = plan[0]
    initial_s = compute_cvm_threshold(initial_m, effective_eps, effective_delta)
    initial_config = ExperimentConfig(
        run_id=str(uuid.uuid4()),
        algorithm="CVM-A1",
        workload=initial_wl,
        trial=1,
        m=initial_m,
        n=initial_n,
        f0=initial_f0,
        epsilon=effective_eps,
        delta=effective_delta,
        s=initial_s,
        seed_generator=base_gen,
        seed_algorithm=base_algo,
        compiler=str(binary_info["compiler"]),
        build_flags=str(binary_info["build_flags"]),
    )
    initial_batch = _batch(initial_config, effective_trials, "real", binary_info)

    with BenchmarkReport.open(resolved_csv, mode="real", batch=initial_batch) as writer:
        for m_item, n_item, f0_item, wl_item in plan:
            threshold_s = compute_cvm_threshold(m_item, effective_eps, effective_delta)
            base_cfg = ExperimentConfig(
                run_id=str(uuid.uuid4()),
                algorithm="CVM-A1",
                workload=wl_item,
                trial=1,
                m=m_item,
                n=n_item,
                f0=f0_item,
                epsilon=effective_eps,
                delta=effective_delta,
                s=threshold_s,
                seed_generator=base_gen,
                seed_algorithm=base_algo,
                compiler=str(binary_info["compiler"]),
                build_flags=str(binary_info["build_flags"]),
            )

            # Advance batch context in BenchmarkReport for contiguous provenance
            current_batch = _batch(base_cfg, effective_trials, "real", binary_info)
            writer.batch = current_batch

            for offset in range(effective_trials):
                trial_cfg = dataclasses.replace(
                    base_cfg,
                    trial=1 + offset,
                    run_id=str(uuid.uuid4()),
                    seed_generator=base_gen + offset,
                    seed_algorithm=base_algo + offset,
                )

                # Subprocess per-trial execution capturing true C++ VmHWM
                result: CVMResult = run_single_trial(
                    trial_cfg,
                    writer,
                    compiler=str(binary_info["compiler"]),
                    build_flags=str(binary_info["build_flags"]),
                    binary=binary,
                    binary_sha256=str(binary_info["binary_sha256"]),
                )
                total_written += 1
                records.append(
                    {
                        "run_id": trial_cfg.run_id,
                        "workload": trial_cfg.workload,
                        "trial": trial_cfg.trial,
                        "m": trial_cfg.m,
                        "n": trial_cfg.n,
                        "f0": trial_cfg.f0,
                        "status": result.status.value,
                        "estimate": result.estimate,
                        "effective_s": result.effective_s,
                        "algorithm_runtime_ms": result.algorithm_runtime_ms,
                        "end_to_end_runtime_ms": result.end_to_end_runtime_ms,
                        "peak_sample_size": result.peak_sample_size,
                        "halving_count": result.halving_count,
                        "process_peak_memory_bytes": result.process_peak_memory_bytes,
                        "error_msg": result.error_msg,
                    }
                )

    sidecar_path = resolved_csv.with_suffix(".metadata.json")
    if verbose:
        logger.info(
            "Session complete: %d trial record(s) written to %s (sidecar: %s)",
            total_written,
            resolved_csv,
            sidecar_path.name,
        )

    return JupyterBenchmarkResult(
        csv_path=resolved_csv,
        sidecar_path=sidecar_path,
        records_count=total_written,
        configs_count=len(plan),
        results=records,
    )
