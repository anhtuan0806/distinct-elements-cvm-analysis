"""Unit tests for CSV schema integrity, formatting rules, and CLI arguments."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from runner import main
from src.cli import args_to_config, build_parser, parse_args
from src.csv_writer import CSVReportWriter, compute_rel_error, format_csv_record
from src.types import CSV_COLUMNS, CSV_HEADER, CVMResult, ExperimentConfig


class TestSchemaIO(unittest.TestCase):
    """Test suite verifying CSV schema specification, formatting, and file I/O operations."""

    def setUp(self) -> None:
        """Create a temporary directory for isolated test runs."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        """Clean up the temporary directory after tests."""
        self.temp_dir.cleanup()

    def test_csv_header_and_columns_count(self) -> None:
        """Verify new CSV file contains exactly 13 columns matching the exact header specification."""
        csv_path = self.test_dir / "test_header.csv"
        writer = CSVReportWriter(csv_path)

        # File must exist
        self.assertTrue(csv_path.exists())

        # Read the raw first line
        with open(csv_path, mode="r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], CSV_HEADER)

        # Verify parsed columns
        cols = lines[0].split(",")
        self.assertEqual(len(cols), 13)
        expected_cols = [
            "m",
            "n",
            "F0",
            "epsilon",
            "delta",
            "seed",
            "estimate",
            "abort",
            "runtime_ms",
            "peak_memory_kb",
            "max_buffer_size",
            "halving_count",
            "rel_error",
        ]
        self.assertEqual(cols, expected_cols)
        self.assertEqual(tuple(cols), CSV_COLUMNS)

    def test_write_success_record(self) -> None:
        """Verify successful record formatting: numeric precision, FALSE abort flag, and exact rel_error."""
        csv_path = self.test_dir / "test_success.csv"
        writer = CSVReportWriter(csv_path)

        config = ExperimentConfig(
            m=100000,
            n=50000,
            f0=10000,
            epsilon=0.05,
            delta=0.01,
            seed=42,
        )
        result = CVMResult(
            estimate=9980.50,
            abort=False,
            runtime_ms=12.3456,
            peak_memory_kb=1024.789,
            max_buffer_size=1200,
            halving_count=4,
            error_msg=None,
        )

        writer.write_record(config, result)

        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = list(csv.reader(f))

        self.assertEqual(len(reader), 2)  # Header + 1 record
        header, row = reader[0], reader[1]

        self.assertEqual(len(row), 13)
        self.assertEqual(row[0], "100000")  # m
        self.assertEqual(row[1], "50000")   # n
        self.assertEqual(row[2], "10000")   # F0
        self.assertEqual(row[3], "0.05")    # epsilon
        self.assertEqual(row[4], "0.01")    # delta
        self.assertEqual(row[5], "42")      # seed
        self.assertEqual(row[6], "9980.50") # estimate (.2f)
        self.assertEqual(row[7], "FALSE")   # abort
        self.assertEqual(row[8], "12.346")  # runtime_ms (.3f rounded)
        self.assertEqual(row[9], "1024.79") # peak_memory_kb (.2f rounded)
        self.assertEqual(row[10], "1200")   # max_buffer_size
        self.assertEqual(row[11], "4")      # halving_count

        # Relative error: |9980.50 - 10000| / 10000 = 19.5 / 10000 = 0.001950
        expected_rel_error = f"{abs(9980.50 - 10000) / 10000:.6f}"
        self.assertEqual(row[12], expected_rel_error)
        self.assertEqual(row[12], "0.001950")

    def test_write_aborted_record(self) -> None:
        """Verify aborted record formatting: TRUE abort flag and rel_error MUST be 'NA'."""
        csv_path = self.test_dir / "test_abort.csv"
        writer = CSVReportWriter(csv_path)

        config = ExperimentConfig(
            m=50000,
            n=20000,
            f0=5000,
            epsilon=0.02,
            delta=0.05,
            seed=123,
        )
        result = CVMResult(
            estimate=0.0,
            abort=True,
            runtime_ms=1.123,
            peak_memory_kb=512.45,
            max_buffer_size=500,
            halving_count=1,
            error_msg="Buffer capacity underflow",
        )

        writer.write_record(config, result)

        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = list(csv.reader(f))

        self.assertEqual(len(reader), 2)
        row = reader[1]

        self.assertEqual(row[7], "TRUE")
        self.assertEqual(row[12], "NA")

    def test_append_mode(self) -> None:
        """Verify consecutive writes in append mode do not duplicate header and increment rows correctly."""
        csv_path = self.test_dir / "test_append.csv"

        config = ExperimentConfig(
            m=1000,
            n=500,
            f0=200,
            epsilon=0.05,
            delta=0.01,
            seed=7,
        )
        result = CVMResult(
            estimate=199.00,
            abort=False,
            runtime_ms=5.000,
            peak_memory_kb=100.00,
            max_buffer_size=50,
            halving_count=2,
        )

        # First session: write 3 records
        writer1 = CSVReportWriter(csv_path)
        for _ in range(3):
            writer1.write_record(config, result)

        with open(csv_path, mode="r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        self.assertEqual(len(lines), 4)  # 1 header + 3 records

        # Second session: new writer instance on existing file, write 2 more records
        writer2 = CSVReportWriter(csv_path)
        writer2.write_record(config, result)
        writer2.write_record(config, result)

        with open(csv_path, mode="r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        # Must have exactly 1 header + 5 records = 6 lines
        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[0], CSV_HEADER)
        # Ensure header is not repeated in subsequent lines
        for line in lines[1:]:
            self.assertNotEqual(line, CSV_HEADER)

    def test_zero_f0_relative_error_is_na(self) -> None:
        """Verify that when f0 is 0, relative error is strictly 'NA' avoiding division by zero."""
        rel_error = compute_rel_error(f0=0, estimate=0.0, abort=False)
        self.assertEqual(rel_error, "NA")

    def test_cli_parser_defaults(self) -> None:
        """Verify CLI parser has required options and default values."""
        parser = build_parser()
        args = parser.parse_args([])

        self.assertEqual(args.m, 100000)
        self.assertEqual(args.n, 50000)
        self.assertEqual(args.f0, 10000)
        self.assertEqual(args.eps, 0.05)
        self.assertEqual(args.delta, 0.01)
        self.assertEqual(args.seed, 42)
        self.assertEqual(args.out, "results/raw_benchmark.csv")
        self.assertFalse(args.dry_run)

        config = args_to_config(args)
        self.assertIsInstance(config, ExperimentConfig)
        self.assertEqual(config.m, 100000)
        self.assertEqual(config.epsilon, 0.05)

    def test_cli_parser_custom_args(self) -> None:
        """Verify CLI parses customized arguments properly."""
        custom_argv = [
            "--m", "5000",
            "--n", "2000",
            "--f0", "800",
            "--eps", "0.02",
            "--delta", "0.005",
            "--seed", "999",
            "--out", str(self.test_dir / "custom.csv"),
            "--dry-run",
        ]
        args = parse_args(custom_argv)
        self.assertEqual(args.m, 5000)
        self.assertEqual(args.n, 2000)
        self.assertEqual(args.f0, 800)
        self.assertEqual(args.eps, 0.02)
        self.assertEqual(args.delta, 0.005)
        self.assertEqual(args.seed, 999)
        self.assertTrue(args.dry_run)

    def test_runner_dry_run_main_execution(self) -> None:
        """Verify running main() with --dry-run generates valid CSV with both success and abort rows."""
        target_csv = self.test_dir / "dry_run_output.csv"
        argv = [
            "--f0", "500",
            "--m", "2000",
            "--n", "1000",
            "--out", str(target_csv),
            "--dry-run",
        ]
        exit_code = main(argv)
        self.assertEqual(exit_code, 0)
        self.assertTrue(target_csv.exists())

        with open(target_csv, mode="r", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        # Expected: Header + Mock Success + Mock Abort = 3 rows
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], list(CSV_COLUMNS))
        self.assertEqual(rows[1][7], "FALSE")  # Mock success
        self.assertEqual(rows[2][7], "TRUE")   # Mock abort
        self.assertEqual(rows[2][12], "NA")    # Mock abort rel_error


if __name__ == "__main__":
    unittest.main()

