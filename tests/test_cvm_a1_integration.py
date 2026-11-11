"""Integration test suite for CVM-A1 algorithm, stream generators, and runner.

Covers:
    - Sampling: element deduplication, retention, small stream exactness.
    - Halving: threshold detection, probability halving, multiple halving accumulation.
    - Abort: abort parsing, CSV serialization, NA relative error enforcement.
    - Stream Generator: exact F0 guarantees, stream length, interleaving.
    - End-to-End: full CLI pipeline from stream generation to CSV output.
"""

from __future__ import annotations

import csv
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from runner import main
from src.algorithms.base import CVMA1Algorithm
from src.csv_writer import CSVReportWriter
from src.generators.base import CustomStreamGenerator, SyntheticStreamGenerator
from src.types import CSV_COLUMNS, CSV_HEADER, CVMResult, ExperimentConfig


class TestCVMA1Integration(unittest.TestCase):
    """Integration test suite for CVM-A1 engine and stream generation."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # =========================================================================
    # 1. SAMPLING TESTS
    # =========================================================================

    def test_sampling_exact_duplicates_no_thinning(self) -> None:
        """Verify stream with F0 < threshold yields exact count with zero halvings."""
        # Threshold for m=256, eps=0.9, delta=0.9 is 166.
        # Stream has only 5 distinct IDs repeated across 20 tokens.
        config = ExperimentConfig(m=20, n=50, f0=5, epsilon=0.9, delta=0.9, seed=42)
        tokens = [1, 2, 3, 4, 5] * 4  # exactly 5 unique tokens
        gen = CustomStreamGenerator(config, tokens)
        algo = CVMA1Algorithm(config)

        result = algo.process_stream(gen.generate())

        self.assertFalse(result.abort)
        self.assertEqual(result.estimate, 5.0)
        self.assertEqual(result.max_buffer_size, 5)
        self.assertEqual(result.halving_count, 0)

    def test_sampling_deduplication_integrity(self) -> None:
        """Verify duplicate tokens in stream do not inflate max buffer size."""
        config = ExperimentConfig(m=50, n=100, f0=10, epsilon=0.5, delta=0.1, seed=99)
        tokens = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100] * 5
        gen = CustomStreamGenerator(config, tokens)
        algo = CVMA1Algorithm(config)

        result = algo.process_stream(gen.generate())

        self.assertFalse(result.abort)
        self.assertEqual(result.estimate, 10.0)
        self.assertEqual(result.max_buffer_size, 10)
        self.assertEqual(result.halving_count, 0)

    # =========================================================================
    # 2. HALVING TESTS
    # =========================================================================

    def test_halving_triggers_when_threshold_reached(self) -> None:
        """Verify that reaching threshold s = 166 triggers probability halving and thinning."""
        # Paper parameters: m=256, eps=0.9, delta=0.9 -> threshold = 166.
        # Feed 200 distinct IDs, which forces buffer to reach 166 and halve.
        config = ExperimentConfig(m=256, n=300, f0=200, epsilon=0.9, delta=0.9, seed=42)
        tokens = list(range(1, 201)) + [1] * 56
        self.assertEqual(len(tokens), 256)
        gen = CustomStreamGenerator(config, tokens)
        algo = CVMA1Algorithm(config)

        result = algo.process_stream(gen.generate())

        self.assertFalse(result.abort)
        self.assertEqual(result.max_buffer_size, 166)
        self.assertGreaterEqual(result.halving_count, 1)
        # With p = 0.5, estimate should approximate 200
        self.assertGreater(result.estimate, 100.0)
        self.assertLess(result.estimate, 350.0)

    def test_multiple_halvings_accumulate(self) -> None:
        """Verify that distinct elements exceeding threshold trigger multiple halvings."""
        # m=1000, eps=0.9, delta=0.9 -> threshold = 195
        # Feed 800 distinct IDs to trigger multiple rounds of halving
        config = ExperimentConfig(m=1000, n=1000, f0=800, epsilon=0.9, delta=0.9, seed=42)
        tokens = list(range(1, 801)) + [1] * 200
        gen = CustomStreamGenerator(config, tokens)
        algo = CVMA1Algorithm(config)

        result = algo.process_stream(gen.generate())

        self.assertFalse(result.abort)
        self.assertEqual(result.max_buffer_size, 195)
        self.assertGreaterEqual(result.halving_count, 2)
        # Estimate should reasonably approximate 800
        self.assertGreater(result.estimate, 400.0)
        self.assertLess(result.estimate, 1200.0)

    # =========================================================================
    # 3. ABORT TESTS
    # =========================================================================

    def test_abort_output_parsing_and_csv_serialization(self) -> None:
        """Verify that an abort output translates to abort=TRUE and rel_error=NA in CSV."""
        config = ExperimentConfig(m=256, n=256, f0=200, epsilon=0.9, delta=0.9, seed=42)
        algo = CVMA1Algorithm(config)

        # Mock subprocess.Popen returning cvm_core abort line
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdin = MagicMock()
        mock_proc.communicate.return_value = ("0.0,TRUE,166,1\n", "")

        with patch("subprocess.Popen", return_value=mock_proc):
            result = algo.process_stream(range(256))

        self.assertTrue(result.abort)
        self.assertEqual(result.estimate, 0.0)
        self.assertEqual(result.max_buffer_size, 166)
        self.assertEqual(result.halving_count, 1)

        # Verify CSV writing of the aborted result
        out_csv = self.test_dir / "abort_test.csv"
        writer = CSVReportWriter(out_csv)
        writer.write_record(config, result)

        with open(out_csv, mode="r", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        self.assertEqual(len(rows), 2)  # Header + row
        row = rows[1]
        self.assertEqual(row[7], "TRUE")   # abort column
        self.assertEqual(row[12], "NA")    # rel_error column

    def test_incomplete_stream_raises_error(self) -> None:
        """Verify cvm_core raises RuntimeError when stream ends prematurely."""
        config = ExperimentConfig(m=100, n=50, f0=20, epsilon=0.5, delta=0.1, seed=42)
        algo = CVMA1Algorithm(config)
        # Provide only 10 tokens instead of required 100
        short_stream = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

        with self.assertRaises(RuntimeError) as ctx:
            algo.process_stream(short_stream)
        self.assertIn("cvm_core failed with exit code", str(ctx.exception))

    # =========================================================================
    # 4. DETERMINISM & GENERATOR TESTS
    # =========================================================================

    def test_determinism_with_same_seed(self) -> None:
        """Verify two runs with identical parameters and seed produce identical results."""
        config = ExperimentConfig(m=500, n=300, f0=150, epsilon=0.8, delta=0.5, seed=12345)
        tokens = list(SyntheticStreamGenerator(config).generate())
        self.assertEqual(len(tokens), 500)

        algo1 = CVMA1Algorithm(config)
        result1 = algo1.process_stream(tokens)

        algo2 = CVMA1Algorithm(config)
        result2 = algo2.process_stream(tokens)

        self.assertEqual(result1.estimate, result2.estimate)
        self.assertEqual(result1.abort, result2.abort)
        self.assertEqual(result1.max_buffer_size, result2.max_buffer_size)
        self.assertEqual(result1.halving_count, result2.halving_count)

    def test_synthetic_stream_generator_properties(self) -> None:
        """Verify SyntheticStreamGenerator produces exact stream length m and ground truth F0."""
        config = ExperimentConfig(m=2000, n=1000, f0=350, epsilon=0.05, delta=0.01, seed=777)
        gen = SyntheticStreamGenerator(config)

        tokens = list(gen.generate())
        self.assertEqual(len(tokens), 2000)

        distinct_set = set(tokens)
        self.assertEqual(len(distinct_set), 350)
        # All items must be within universe 1..n
        self.assertTrue(all(1 <= token <= 1000 for token in tokens))

    # =========================================================================
    # 5. END-TO-END PIPELINE TESTS
    # =========================================================================

    def test_full_e2e_runner_pipeline(self) -> None:
        """Verify full execution through runner.main() from CLI args to verified CSV output."""
        out_csv = self.test_dir / "e2e_benchmark.csv"
        argv = [
            "--m", "1000",
            "--n", "500",
            "--f0", "200",
            "--eps", "0.2",
            "--delta", "0.1",
            "--seed", "42",
            "--out", str(out_csv),
        ]
        exit_code = main(argv)
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_csv.exists())

        with open(out_csv, mode="r", encoding="utf-8") as f:
            reader = list(csv.reader(f))

        self.assertEqual(len(reader), 2)  # Header + 1 record
        header, row = reader[0], reader[1]

        self.assertEqual(header, list(CSV_COLUMNS))
        self.assertEqual(row[0], "1000")  # m
        self.assertEqual(row[1], "500")   # n
        self.assertEqual(row[2], "200")   # F0
        self.assertEqual(row[3], "0.2")   # epsilon
        self.assertEqual(row[4], "0.1")   # delta
        self.assertEqual(row[5], "42")    # seed
        self.assertEqual(row[7], "FALSE") # abort

        # rel_error must be a valid float string
        rel_error = float(row[12])
        self.assertGreaterEqual(rel_error, 0.0)


if __name__ == "__main__":
    unittest.main()

