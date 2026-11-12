"""Execution adapter invoking the CVM-A1 C++ binary with stream input and parsing csv-v2 output."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterable
from pathlib import Path

from src.cvm.build import build_cvm_core, get_cvm_core_path
from src.types import CVMResult, ExperimentConfig, ExperimentStatus


def run_cvm_a1_core(
    config: ExperimentConfig,
    stream: Iterable[int],
    binary_path: Path | str | None = None,
) -> CVMResult:
    """Execute the CVM-A1 C++ core binary with streaming input and collect performance metrics.

    Args:
        config: Experiment parameters (m, eps, delta, seed_algorithm, etc.).
        stream: Iterable yielding unsigned 64-bit integer item tokens.
        binary_path: Optional explicit path to cvm_core executable; auto-builds if None.

    Returns:
        Standardized CVMResult with status, estimate, runtimes, sample size, halving, and RAM.
    """
    binary = Path(binary_path) if binary_path is not None else get_cvm_core_path()
    if not binary.exists():
        binary = build_cvm_core()

    cmd = [
        str(binary),
        "--m",
        str(config.m),
        "--eps",
        str(config.epsilon),
        "--delta",
        str(config.delta),
        "--seed",
        str(config.seed_algorithm),
        "--output-format",
        "csv-v2",
    ]

    t_start = time.perf_counter()

    try:
        input_data = "".join(f"{item}\n" for item in stream)
    except Exception as exc:
        t_end = time.perf_counter()
        return CVMResult(
            status=ExperimentStatus.EXECUTION_ERROR,
            estimate=None,
            end_to_end_runtime_ms=(t_end - t_start) * 1000.0,
            error_msg=f"Pipeline stream generation failure: {exc}",
        )

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(input=input_data)
        except Exception:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            raise
    except Exception as exc:
        t_end = time.perf_counter()
        return CVMResult(
            status=ExperimentStatus.EXECUTION_ERROR,
            estimate=None,
            end_to_end_runtime_ms=(t_end - t_start) * 1000.0,
            error_msg=f"Pipeline stream I/O failure: {exc}",
        )

    t_end = time.perf_counter()
    e2e_runtime_ms = (t_end - t_start) * 1000.0

    # Collect peak resident set size (RSS) if supported by OS
    peak_mem_bytes: int | None = None
    try:
        import resource

        # On Linux ru_maxrss is in KiB; convert to bytes
        peak_mem_bytes = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024
    except (ImportError, AttributeError):
        peak_mem_bytes = None

    if proc.returncode != 0:
        return CVMResult(
            status=ExperimentStatus.EXECUTION_ERROR,
            estimate=None,
            end_to_end_runtime_ms=e2e_runtime_ms,
            process_peak_memory_bytes=peak_mem_bytes,
            error_msg=stderr.strip() or f"Process exited with non-zero code {proc.returncode}",
        )

    output_line = stdout.strip()
    parts = output_line.split(",")
    if len(parts) != 6:
        return CVMResult(
            status=ExperimentStatus.EXECUTION_ERROR,
            estimate=None,
            end_to_end_runtime_ms=e2e_runtime_ms,
            process_peak_memory_bytes=peak_mem_bytes,
            error_msg=f"Expected 6 csv-v2 output fields from cvm_core, got: '{output_line}'",
        )

    status_str, est_str, alg_rt_str, max_buf_str, halving_str, _thresh_str = parts
    status = (
        ExperimentStatus.ALGORITHM_ABORT
        if status_str == "algorithm_abort"
        else ExperimentStatus.SUCCESS
    )

    estimate = float(est_str) if (status == ExperimentStatus.SUCCESS and est_str) else None
    alg_runtime_ms = float(alg_rt_str)
    peak_sample_size = int(max_buf_str)
    halving_count = int(halving_str)

    return CVMResult(
        status=status,
        estimate=estimate,
        peak_sample_size=peak_sample_size,
        halving_count=halving_count,
        algorithm_runtime_ms=alg_runtime_ms,
        end_to_end_runtime_ms=e2e_runtime_ms,
        process_peak_memory_bytes=peak_mem_bytes,
    )
