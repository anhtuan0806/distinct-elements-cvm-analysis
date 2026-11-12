"""Run the C++ core and validate its six-field csv-v2 response."""

from __future__ import annotations

import math
import os
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path

from src.cvm.build import build_cvm_core, get_cvm_core_path
from src.cvm.process_memory import peak_memory
from src.types import CVMResult, ExperimentConfig, ExperimentStatus


def resolve_core_binary() -> Path:
    binary = get_cvm_core_path()
    return binary if binary.is_file() else build_cvm_core()


def run_cvm_a1_core(
    config: ExperimentConfig,
    stream: Iterable[int],
    binary_path: Path | str | None = None,
) -> CVMResult:
    start = time.perf_counter()
    peak_bytes = None
    effective_s = None
    try:
        binary = Path(binary_path) if binary_path is not None else resolve_core_binary()
        input_data = "".join(f"{item}\n" for item in stream)
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
        with subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "CVM_TV3_PEAK_RSS": "1"},
        ) as proc:
            try:
                stdout, stderr = proc.communicate(input=input_data)
            except BaseException:
                proc.kill()
                raise
            elapsed_ms = (time.perf_counter() - start) * 1000
            peak_bytes, stderr = peak_memory(stderr)

        if proc.returncode != 0:
            raise ValueError(f"Core exit {proc.returncode}: {stderr.strip() or 'empty stderr'}")

        fields = stdout.strip().split(",")
        if len(fields) != 6 or "\n" in stdout.strip():
            raise ValueError(f"Invalid csv-v2 output: {stdout.strip()!r}")
        status, estimate_text, runtime_text, peak_text, halving_text, threshold_text = fields
        if status not in ("success", "algorithm_abort"):
            raise ValueError(f"Unknown Core status: {status!r}")

        threshold = int(threshold_text)
        runtime = float(runtime_text)
        peak = int(peak_text)
        halvings = int(halving_text)
        if threshold <= 0 or not math.isfinite(runtime) or runtime < 0:
            raise ValueError("Core returned invalid threshold or algorithm runtime")
        effective_s = threshold
        if not 0 <= peak <= min(threshold, config.m) or not 0 <= halvings <= config.m:
            raise ValueError("Core returned invalid peak sample size or halving count")
        if effective_s != config.s:
            raise ValueError(f"Configured s={config.s} differs from Core s={effective_s}")

        if status == "algorithm_abort":
            if estimate_text or peak != threshold or halvings < 1:
                raise ValueError("Core returned inconsistent algorithm_abort metrics")
            estimate = None
        else:
            estimate = float(estimate_text)
            if not math.isfinite(estimate) or estimate < 0:
                raise ValueError("Core returned an invalid estimate")

        return CVMResult(
            status=ExperimentStatus(status),
            estimate=estimate,
            peak_sample_size=peak,
            halving_count=halvings,
            algorithm_runtime_ms=runtime,
            end_to_end_runtime_ms=elapsed_ms,
            process_peak_memory_bytes=peak_bytes,
            effective_s=effective_s,
        )
    except MemoryError as exc:
        status = ExperimentStatus.RESOURCE_FAILURE
        reason = str(exc) or "Python raised MemoryError while preparing the Core invocation"
    except Exception as exc:
        status = ExperimentStatus.EXECUTION_ERROR
        reason = str(exc)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            reason += f": {exc.stderr.strip()}"
    return CVMResult(
        status=status,
        end_to_end_runtime_ms=(time.perf_counter() - start) * 1000,
        process_peak_memory_bytes=peak_bytes,
        effective_s=effective_s,
        error_msg=reason,
    )
