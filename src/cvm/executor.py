"""Run the C++ core and validate its six-field csv-v2 response."""

from __future__ import annotations

import errno
import io
import math
import os
import subprocess
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from pathlib import Path
from threading import Event, Timer
from typing import BinaryIO

from src.cvm.build import build_cvm_core, get_cvm_core_path
from src.cvm.process_memory import peak_memory
from src.types import CVMResult, ExperimentConfig, ExperimentStatus, compute_cvm_threshold

MAX_WIRE_THRESHOLD = (1 << 64) - 1
_CHUNK_ITEMS = 8192
_OUTPUT_LIMIT = 64 * 1024
_TRIAL_TIMEOUT_SECONDS = 600


def _parse_threshold(text: str) -> int:
    if not text.isascii() or not text.isdecimal() or len(text) > 20:
        raise ValueError(f"Invalid csv-v2 threshold: expected a uint64 decimal, got {text!r}")
    threshold = int(text)
    if not 1 <= threshold <= MAX_WIRE_THRESHOLD:
        raise ValueError(f"Invalid csv-v2 threshold: s={threshold} is outside [1, 2^64 - 1]")
    return threshold


def _core_command(binary: Path, config: ExperimentConfig, output_format: str) -> list[str]:
    return [
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
        output_format,
    ]


def _read_output(pipe: BinaryIO, proc: subprocess.Popen) -> bytes:
    with io.BufferedReader(pipe) as reader:
        data = reader.read(_OUTPUT_LIMIT + 1)
    if len(data) > _OUTPUT_LIMIT:
        proc.kill()
    return data


def _write_input(pipe: BinaryIO, proc: subprocess.Popen, stream: Iterable[int]) -> None:
    items = iter(stream)
    try:
        while proc.poll() is None:
            chunk = "".join(f"{item}\n" for item in islice(items, _CHUNK_ITEMS))
            if not chunk:
                return
            # Unbuffered pipe writes can accept only part of a chunk.
            remaining = memoryview(chunk.encode("utf-8"))
            while remaining:
                try:
                    written = pipe.write(remaining)
                except OSError as exc:
                    if not (
                        isinstance(exc, BrokenPipeError)
                        or (os.name == "nt" and exc.errno == errno.EINVAL)
                    ):
                        raise
                    # Core can close stdin early on an abort or input error.
                    # The exit code and csv-v2 response determine the result.
                    return
                remaining = remaining[written:]
    finally:
        pipe.close()


def _run_core(
    cmd: list[str],
    stream: Iterable[int],
    timeout: float,
    *,
    on_process: Callable[..., None] | None = None,
) -> subprocess.CompletedProcess[str]:
    with subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        env={**os.environ, "CVM_TV3_PEAK_RSS": "1"},
    ) as proc, ThreadPoolExecutor(max_workers=2) as readers:
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
        expired = Event()

        def on_timeout() -> None:
            expired.set()
            proc.kill()

        timer = Timer(timeout, on_timeout)
        timer.start()
        try:
            if on_process is not None:
                on_process("core_started", pid=proc.pid, executable=cmd[0])
            # Drain both pipes while stdin is being sent to avoid pipe backpressure.
            stdout_read = readers.submit(_read_output, proc.stdout, proc)
            stderr_read = readers.submit(_read_output, proc.stderr, proc)
            _write_input(proc.stdin, proc, stream)
            proc.wait()
            stdout, stderr = stdout_read.result(), stderr_read.result()
        except BaseException:
            proc.kill()
            raise
        finally:
            timer.cancel()
            timer.join()
            if on_process is not None:
                proc.wait()
                on_process("core_finished", pid=proc.pid, returncode=proc.returncode)

    diagnostic = stderr[:_OUTPUT_LIMIT].decode("utf-8", "replace")
    if expired.is_set():
        raise subprocess.TimeoutExpired(cmd, timeout, stderr=diagnostic)
    if max(len(stdout), len(stderr)) > _OUTPUT_LIMIT:
        raise ValueError(f"Core stdout/stderr exceeded {_OUTPUT_LIMIT} bytes: {diagnostic.strip()}")
    return subprocess.CompletedProcess(
        cmd, proc.returncode, stdout.decode("utf-8", "replace"), diagnostic
    )


def query_core_threshold(binary: Path, config: ExperimentConfig) -> int:
    result = _run_core(_core_command(binary, config, "threshold-v1"), (), timeout=15)
    if result.returncode != 0:
        raise ValueError(
            f"Core threshold-v1 query failed (exit {result.returncode}); "
            f"check the input or rebuild an older Core: {result.stderr.strip()}"
        )
    prefix, _, value = result.stdout.removesuffix("\n").removesuffix("\r").partition(",")
    if prefix != "threshold-v1":
        raise ValueError("Invalid threshold-v1 Core response")
    return _parse_threshold(value)


def resolve_core_binary() -> Path:
    binary = get_cvm_core_path()
    return binary if binary.is_file() else build_cvm_core()


def run_cvm_a1_core(
    config: ExperimentConfig,
    stream: Iterable[int],
    binary_path: Path | str | None = None,
    *,
    on_process: Callable[..., None] | None = None,
) -> CVMResult:
    start = time.perf_counter()
    peak_bytes = None
    effective_s = None
    try:
        binary = Path(binary_path) if binary_path is not None else resolve_core_binary()
        expected_s = query_core_threshold(binary, config)
        # Keep the independent query outside the measured trial.
        start = time.perf_counter()
        cmd = _core_command(binary, config, "csv-v2")
        options = {"on_process": on_process} if on_process is not None else {}
        process = _run_core(cmd, stream, timeout=_TRIAL_TIMEOUT_SECONDS, **options)
        elapsed_ms = (time.perf_counter() - start) * 1000
        peak_bytes, stderr = peak_memory(process.stderr)
        if process.returncode != 0:
            raise ValueError(f"Core exit {process.returncode}: {stderr.strip() or 'empty stderr'}")

        record = process.stdout.removesuffix("\n").removesuffix("\r")
        fields = record.split(",")
        if len(fields) != 6 or "\n" in record or "\r" in record:
            raise ValueError(f"Invalid csv-v2 output: {record!r}")
        status, estimate_text, runtime_text, peak_text, halving_text, threshold_text = fields
        if status not in ("success", "algorithm_abort"):
            raise ValueError(f"Unknown Core status: {status!r}")

        threshold = _parse_threshold(threshold_text)
        runtime = float(runtime_text)
        peak = int(peak_text)
        halvings = int(halving_text)
        if not math.isfinite(runtime) or runtime < 0:
            raise ValueError("Core returned invalid algorithm runtime")
        effective_s = threshold
        if not 0 <= peak <= min(threshold, config.m) or not 0 <= halvings <= config.m:
            raise ValueError("Core returned invalid peak sample size or halving count")
        if threshold != expected_s:
            effective_s = None
            raise ValueError(f"Core s={threshold} differs from its threshold-v1 s={expected_s}")
        if config.s != threshold:
            reference = compute_cvm_threshold(config.m, config.epsilon, config.delta)
            if config.s != reference:
                raise ValueError(f"Configured s={config.s} differs from Core s={threshold}")
        if (halvings > 0) != (peak == threshold):
            raise ValueError("Core returned inconsistent peak sample size and halving count")

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
        if isinstance(exc, (subprocess.CalledProcessError, subprocess.TimeoutExpired)) and exc.stderr:
            reason += f": {exc.stderr.strip()}"
    return CVMResult(
        status=status,
        end_to_end_runtime_ms=(time.perf_counter() - start) * 1000,
        process_peak_memory_bytes=peak_bytes,
        effective_s=effective_s,
        error_msg=reason,
    )
