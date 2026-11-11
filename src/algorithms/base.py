"""Interface and Subprocess implementation for CVM-A1 algorithm."""

from __future__ import annotations

import subprocess
import time
import tracemalloc
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from src.cvm.build import build_cvm_core
from src.types import CVMResult, ExperimentConfig


class BaseDistinctElementsAlgorithm(ABC):
    """Abstract base class defining the contract for distinct element estimators."""

    def __init__(self, config: ExperimentConfig) -> None:
        self.config: ExperimentConfig = config

    @abstractmethod
    def process_stream(self, stream: Iterable[int]) -> CVMResult:
        """Process an input stream and return distinct elements estimation telemetry."""
        raise NotImplementedError


class CVMA1Algorithm(BaseDistinctElementsAlgorithm):
    """CVM-A1 Algorithm adapter delegating execution to the compiled cvm_core binary."""

    def __init__(
        self,
        config: ExperimentConfig,
        executable_path: Path | str | None = None,
    ) -> None:
        super().__init__(config)
        if executable_path is not None:
            self.executable_path = Path(executable_path).resolve()
        else:
            self.executable_path = build_cvm_core()

        if not self.executable_path.exists():
            raise FileNotFoundError(f"cvm_core executable not found at: {self.executable_path}")

    def process_stream(self, stream: Iterable[int]) -> CVMResult:
        """Execute CVM-A1 over the provided stream and return structured metrics."""
        tracemalloc.start()
        start_time = time.perf_counter()

        cmd = [
            str(self.executable_path),
            "--m",
            str(self.config.m),
            "--eps",
            str(self.config.epsilon),
            "--delta",
            str(self.config.delta),
            "--seed",
            str(self.config.seed),
        ]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=65536,
        )

        try:
            if proc.stdin is not None:
                for token in stream:
                    try:
                        proc.stdin.write(f"{token}\n")
                    except (BrokenPipeError, OSError):
                        # Process might have aborted early and closed stdin
                        break
                try:
                    proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

            stdout_data, stderr_data = proc.communicate()
        except Exception as exc:
            proc.kill()
            raise RuntimeError(f"Error communicating with cvm_core: {exc}") from exc

        end_time = time.perf_counter()
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        runtime_ms = (end_time - start_time) * 1000.0
        peak_memory_kb = peak_mem / 1024.0

        if proc.returncode != 0:
            raise RuntimeError(
                f"cvm_core failed with exit code {proc.returncode}:\n{stderr_data.strip()}"
            )

        line = stdout_data.strip()
        if not line:
            raise ValueError("cvm_core returned empty stdout")

        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 4:
            raise ValueError(
                f"Expected 4 comma-separated values from cvm_core, got: '{line}'"
            )

        estimate = float(parts[0])
        abort = parts[1].upper() == "TRUE"
        max_buffer_size = int(parts[2])
        halving_count = int(parts[3])

        return CVMResult(
            estimate=estimate,
            abort=abort,
            runtime_ms=runtime_ms,
            peak_memory_kb=peak_memory_kb,
            max_buffer_size=max_buffer_size,
            halving_count=halving_count,
            error_msg=stderr_data.strip() if abort and stderr_data.strip() else None,
        )

