"""Unit tests for CVM-A1 C++ binary auto-build and execution adapter."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.cvm.build import build_cvm_core, detect_compiler_info, get_cvm_core_path
from src.cvm.executor import run_cvm_a1_core
from src.stream_generator import Distribution, StreamConfig, generate_stream
from src.types import ExperimentConfig, ExperimentStatus


class TestCVMCoreAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Ensure cvm_core executable is compiled once before adapter tests."""
        cls.binary_path = build_cvm_core()

    def test_get_cvm_core_path(self) -> None:
        path = get_cvm_core_path()
        self.assertIsInstance(path, Path)
        self.assertTrue(path.name.startswith("cvm_core"))

    def test_detect_compiler_info(self) -> None:
        compiler, flags = detect_compiler_info()
        self.assertIsInstance(compiler, str)
        self.assertIsInstance(flags, str)
        self.assertTrue(len(compiler) > 0)
        self.assertTrue(len(flags) > 0)

    def test_build_cvm_core_exists_and_runs(self) -> None:
        self.assertTrue(self.binary_path.exists())
        self.assertTrue(self.binary_path.is_file())

    def test_run_cvm_a1_core_success(self) -> None:
        config = ExperimentConfig(
            m=4,
            n=10,
            f0=3,
            epsilon=0.05,
            delta=0.01,
            seed_generator=42,
            seed_algorithm=42,
        )
        stream = [10, 20, 10, 30]
        result = run_cvm_a1_core(config, stream, self.binary_path)

        self.assertEqual(result.status, ExperimentStatus.SUCCESS)
        self.assertEqual(result.estimate, 3.0)
        self.assertEqual(result.peak_sample_size, 3)
        self.assertEqual(result.halving_count, 0)
        self.assertIsNotNone(result.algorithm_runtime_ms)
        self.assertGreater(result.algorithm_runtime_ms, 0.0)
        self.assertIsNotNone(result.end_to_end_runtime_ms)
        self.assertGreaterEqual(result.end_to_end_runtime_ms, result.algorithm_runtime_ms)

    def test_run_cvm_a1_core_stream_ends_early(self) -> None:
        config = ExperimentConfig(
            m=5,
            n=10,
            f0=3,
            epsilon=0.05,
            delta=0.01,
            seed_generator=42,
            seed_algorithm=42,
        )
        # Stream has only 3 tokens instead of m=5
        stream = [10, 20, 30]
        result = run_cvm_a1_core(config, stream, self.binary_path)

        self.assertEqual(result.status, ExperimentStatus.EXECUTION_ERROR)
        self.assertIsNone(result.estimate)
        self.assertIsNotNone(result.error_msg)
        self.assertIn("input ended after 3 IDs; expected 5", result.error_msg)

    def test_run_cvm_a1_core_with_stream_generator(self) -> None:
        stream_cfg = StreamConfig(
            m=1000,
            n=500,
            f0=200,
            distribution=Distribution.UNIFORM,
            seed=42,
        )
        stream = generate_stream(stream_cfg)

        exp_cfg = ExperimentConfig(
            m=1000,
            n=500,
            f0=200,
            epsilon=0.1,
            delta=0.05,
            seed_generator=42,
            seed_algorithm=42,
            workload="uniform",
        )
        result = run_cvm_a1_core(exp_cfg, stream, self.binary_path)

        self.assertEqual(result.status, ExperimentStatus.SUCCESS)
        self.assertIsNotNone(result.estimate)
        self.assertGreater(result.estimate, 0.0)
        self.assertIsNotNone(result.algorithm_runtime_ms)
        self.assertGreater(result.algorithm_runtime_ms, 0.0)

    def test_run_cvm_a1_core_broken_stream_generator(self) -> None:
        def broken_gen():
            yield 10
            yield 20
            raise RuntimeError("Generator stream broken")

        config = ExperimentConfig(
            m=5,
            n=10,
            f0=3,
            epsilon=0.05,
            delta=0.01,
            seed_generator=42,
            seed_algorithm=42,
        )
        result = run_cvm_a1_core(config, broken_gen(), self.binary_path)

        self.assertEqual(result.status, ExperimentStatus.EXECUTION_ERROR)
        self.assertIsNone(result.estimate)
        self.assertIn("Generator stream broken", str(result.error_msg))


if __name__ == "__main__":
    unittest.main()
