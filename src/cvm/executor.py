"""Execution adapter invoking the CVM-A1 C++ binary with stream input and parsing csv-v2 output."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from src.cvm.build import build_cvm_core, get_cvm_core_path
from src.types import CVMResult, ExperimentConfig, ExperimentStatus


def get_windows_peak_memory(handle: int) -> int | None:
    """Query Win32 GetProcessMemoryInfo for peak working set size (RSS) in bytes.

    Uses standard library ctypes to access K32GetProcessMemoryInfo (kernel32.dll)
    or GetProcessMemoryInfo (psapi.dll) on Windows systems.
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)

        kernel32 = getattr(ctypes, "windll", None) and getattr(ctypes.windll, "kernel32", None)
        fn = getattr(kernel32, "K32GetProcessMemoryInfo", None) if kernel32 else None
        if fn is None and hasattr(ctypes, "windll") and hasattr(ctypes.windll, "psapi"):
            fn = getattr(ctypes.windll.psapi, "GetProcessMemoryInfo", None)

        if fn and fn(handle, ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize)
        return None
    except Exception:
        return None


class MeasuredPopen(subprocess.Popen):
    """Subprocess Popen recording exact per-PID peak resident memory upon process exit.

    On POSIX (Linux/macOS), overrides _try_wait to capture per-child rusage via os.wait4.
    This guarantees memory measurements reflect only this specific child process, avoiding
    the cumulative inheritance defect of resource.RUSAGE_CHILDREN.
    On Windows, queries GetProcessMemoryInfo before closing the Win32 process handle.
    """

    def __init__(self, *args, **kwargs) -> None:
        self.peak_memory_bytes: int | None = None
        self._rusage = None
        super().__init__(*args, **kwargs)

    def _try_wait(self, wait_flags: int) -> tuple[int, int]:
        """Capture per-child rusage via os.wait4 on POSIX."""
        if hasattr(os, "wait4"):
            try:
                pid, sts, ru = os.wait4(self.pid, wait_flags)
                if pid == self.pid and ru is not None:
                    self._rusage = ru
                    multiplier = 1024 if sys.platform.startswith("linux") else 1
                    self.peak_memory_bytes = int(ru.ru_maxrss * multiplier)
                return (pid, sts)
            except ChildProcessError:
                return (self.pid, 0)
        return super()._try_wait(wait_flags)

    def wait(self, timeout: float | None = None) -> int:
        sts = super().wait(timeout=timeout)
        if sys.platform.startswith("win") and self.peak_memory_bytes is None:
            handle = getattr(self, "_handle", None)
            if handle:
                self.peak_memory_bytes = get_windows_peak_memory(int(handle))
        return sts


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
        proc = MeasuredPopen(
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

    # Collect peak resident set size (RSS) per PID
    peak_mem_bytes = proc.peak_memory_bytes
    if peak_mem_bytes is None and sys.platform.startswith("win"):
        handle = getattr(proc, "_handle", None)
        if handle:
            peak_mem_bytes = get_windows_peak_memory(int(handle))

    if peak_mem_bytes is None:
        try:
            import resource

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
