"""Unit tests for CSV schema integrity, formatting rules, and CLI arguments."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from runner import main
from src.cli import args_to_config, build_parser, parse_args
from src.csv_writer import CSVReportWriter, compute_rel_error, compute_relative_errors
from src.types import (
    CSV_COLUMNS,
    CSV_HEADER,
    CVMResult,
    ExperimentConfig,
    ExperimentStatus,
)


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
        """Verify the new file contains the standardized 24 columns in strict order."""
        csv_path = self.test_dir / "test_header.csv"
        CSVReportWriter(csv_path)

        self.assertTrue(csv_path.exists())

        with open(csv_path, mode="r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], CSV_HEADER)

        cols = lines[0].split(",")
        self.assertEqual(len(cols), 24)
        expected_cols = [
            "run_id",
            "algorithm",
            "workload",
            "trial",
            "m",
            "n",
            "F0",
            "epsilon",
            "delta",
            "s",
            "seed_generator",
            "seed_algorithm",
            "status",
            "estimate",
            "algorithm_runtime_ms",
            "end_to_end_runtime_ms",
            "peak_sample_size",
            "halving_count",
            "process_peak_memory_bytes",
            "signed_rel_error",
            "abs_rel_error",
            "env_os",
            "compiler",
            "build_flags",
        ]
        self.assertEqual(cols, expected_cols)
        self.assertEqual(tuple(cols), CSV_COLUMNS)

    def test_write_success_record(self) -> None:
        """Verify precision, success status, and signed/absolute relative errors."""
        csv_path = self.test_dir / "test_success.csv"
        writer = CSVReportWriter(csv_path)

        config = ExperimentConfig(
            m=100000,
            n=50000,
            f0=10000,
            epsilon=0.05,
            delta=0.01,
            seed_generator=42,
            seed_algorithm=42,
            s=23067,
            workload="uniform",
            trial=1,
            algorithm="CVM-A1",
            run_id="run-101",
            env_os="Linux-6.6",
            compiler="g++ 11.4.0",
            build_flags="-O3;-std=c++20",
        )
        result = CVMResult(
            status=ExperimentStatus.SUCCESS,
            estimate=9980.50,
            peak_sample_size=1200,
            halving_count=4,
            algorithm_runtime_ms=10.2346,
            end_to_end_runtime_ms=12.3456,
            process_peak_memory_bytes=1048576,
            error_msg=None,
        )

        writer.write_record(config, result)

        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = list(csv.reader(f))

        self.assertEqual(len(reader), 2)  # Header + 1 record
        row = reader[1]

        self.assertEqual(len(row), 24)
        self.assertEqual(row[0], "run-101")
        self.assertEqual(row[1], "CVM-A1")
        self.assertEqual(row[2], "uniform")
        self.assertEqual(row[3], "1")
        self.assertEqual(row[4], "100000")  # m
        self.assertEqual(row[5], "50000")  # n
        self.assertEqual(row[6], "10000")  # F0
        self.assertEqual(row[7], "0.05")  # epsilon
        self.assertEqual(row[8], "0.01")  # delta
        self.assertEqual(row[9], "23067")  # s
        self.assertEqual(row[10], "42")  # seed_generator
        self.assertEqual(row[11], "42")  # seed_algorithm
        self.assertEqual(row[12], "success")  # status
        self.assertEqual(row[13], "9980.50")  # estimate (.2f)
        self.assertEqual(row[14], "10.235")  # algorithm_runtime_ms (.3f rounded)
        self.assertEqual(row[15], "12.346")  # end_to_end_runtime_ms (.3f rounded)
        self.assertEqual(row[16], "1200")  # peak_sample_size
        self.assertEqual(row[17], "4")  # halving_count
        self.assertEqual(row[18], "1048576")  # process_peak_memory_bytes

        # Signed relative error: (9980.50 - 10000) / 10000 = -19.5 / 10000 = -0.001950
        self.assertEqual(row[19], "-0.001950")
        # Absolute relative error: |9980.50 - 10000| / 10000 = 0.001950
        self.assertEqual(row[20], "0.001950")

        self.assertEqual(row[21], "Linux-6.6")
        self.assertEqual(row[22], "g++ 11.4.0")
        self.assertEqual(row[23], "-O3;-std=c++20")

    def test_write_aborted_record(self) -> None:
        """Verify aborted record: status=algorithm_abort, estimate/errors must be empty."""
        csv_path = self.test_dir / "test_abort.csv"
        writer = CSVReportWriter(csv_path)

        config = ExperimentConfig(
            m=50000,
            n=20000,
            f0=5000,
            epsilon=0.02,
            delta=0.05,
            seed_generator=123,
            seed_algorithm=123,
            run_id="run-abort-1",
        )
        result = CVMResult(
            status=ExperimentStatus.ALGORITHM_ABORT,
            estimate=None,
            peak_sample_size=500,
            halving_count=1,
            algorithm_runtime_ms=1.123,
            end_to_end_runtime_ms=1.234,
            process_peak_memory_bytes=524288,
            error_msg="Buffer capacity underflow",
        )

        writer.write_record(config, result)

        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = list(csv.reader(f))

        self.assertEqual(len(reader), 2)
        row = reader[1]

        self.assertEqual(row[12], "algorithm_abort")
        self.assertEqual(row[13], "")  # estimate is empty/null, NOT 0.0!
        self.assertEqual(row[19], "")  # signed_rel_error is empty
        self.assertEqual(row[20], "")  # abs_rel_error is empty

    def test_all_status_enums_and_null_rules(self) -> None:
        """Verify that all non-success status values yield empty estimate and errors."""
        for status in [
            ExperimentStatus.ALGORITHM_ABORT,
            ExperimentStatus.EXECUTION_ERROR,
            ExperimentStatus.RESOURCE_FAILURE,
        ]:
            with self.subTest(status=status):
                signed_err, abs_err = compute_relative_errors(
                    f0=1000, estimate=900.0, status=status
                )
                self.assertEqual(signed_err, "")
                self.assertEqual(abs_err, "")

    def test_zero_f0_relative_error_is_empty(self) -> None:
        """Verify that when f0 is 0, relative error calculation avoids ZeroDivisionError."""
        signed_err, abs_err = compute_relative_errors(
            f0=0, estimate=0.0, status=ExperimentStatus.SUCCESS
        )
        self.assertEqual(signed_err, "")
        self.assertEqual(abs_err, "")

        # Backward compatibility check
        self.assertEqual(compute_rel_error(f0=0, estimate=0.0, abort=False), "NA")

    def test_append_mode(self) -> None:
        """Verify appending preserves every row and does not duplicate the header."""
        csv_path = self.test_dir / "test_append.csv"

        config = ExperimentConfig(
            m=1000,
            n=500,
            f0=200,
            epsilon=0.05,
            delta=0.01,
            seed_generator=7,
            seed_algorithm=7,
            run_id="run-append",
        )
        result = CVMResult(
            status=ExperimentStatus.SUCCESS,
            estimate=199.00,
            peak_sample_size=50,
            halving_count=2,
            algorithm_runtime_ms=4.5,
            end_to_end_runtime_ms=5.0,
            process_peak_memory_bytes=100000,
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
        for line in lines[1:]:
            self.assertNotEqual(line, CSV_HEADER)

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
        self.assertEqual(args.workload, "uniform")
        self.assertEqual(args.trial, 1)
        self.assertEqual(args.trials, 1)
        self.assertEqual(args.out, "results/raw_benchmark.csv")
        self.assertFalse(args.dry_run)

        config = args_to_config(args)
        self.assertIsInstance(config, ExperimentConfig)
        self.assertEqual(config.m, 100000)
        self.assertEqual(config.epsilon, 0.05)
        self.assertEqual(config.seed_generator, 42)
        self.assertEqual(config.seed_algorithm, 42)

    def test_cli_parser_custom_args(self) -> None:
        """Verify CLI parses customized arguments properly."""
        custom_argv = [
            "--m",
            "5000",
            "--n",
            "2000",
            "--f0",
            "800",
            "--eps",
            "0.02",
            "--delta",
            "0.005",
            "--seed-gen",
            "111",
            "--seed-algo",
            "222",
            "--workload",
            "zipf",
            "--trial",
            "3",
            "--out",
            str(self.test_dir / "custom.csv"),
            "--dry-run",
        ]
        args = parse_args(custom_argv)
        self.assertEqual(args.m, 5000)
        self.assertEqual(args.n, 2000)
        self.assertEqual(args.f0, 800)
        self.assertEqual(args.eps, 0.02)
        self.assertEqual(args.delta, 0.005)
        self.assertEqual(args.seed_gen, 111)
        self.assertEqual(args.seed_algo, 222)
        self.assertEqual(args.workload, "zipf")
        self.assertEqual(args.trial, 3)
        self.assertTrue(args.dry_run)

        config = args_to_config(args)
        self.assertEqual(config.seed_generator, 111)
        self.assertEqual(config.seed_algorithm, 222)
        self.assertEqual(config.workload, "zipf")
        self.assertEqual(config.trial, 3)

    def test_runner_dry_run_main_execution(self) -> None:
        """Verify --dry-run generates valid 24-column CSV with both success and abort rows."""
        target_csv = self.test_dir / "dry_run_output.csv"
        argv = [
            "--f0",
            "500",
            "--m",
            "2000",
            "--n",
            "1000",
            "--out",
            str(target_csv),
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
        self.assertEqual(len(rows[1]), 24)
        self.assertEqual(len(rows[2]), 24)

        # Success row checks
        self.assertEqual(rows[1][12], "success")
        self.assertNotEqual(rows[1][13], "")

        # Abort row checks
        self.assertEqual(rows[2][12], "algorithm_abort")
        self.assertEqual(rows[2][13], "")  # null estimate
        self.assertEqual(rows[2][19], "")  # null signed_rel_error
        self.assertEqual(rows[2][20], "")  # null abs_rel_error


if __name__ == "__main__":
    unittest.main()
