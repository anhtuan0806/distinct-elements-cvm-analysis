"""End-to-End integration tests for CVM-A1 benchmark runner pipeline."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from runner import main
from src.csv_writer import CSVReportWriter
from src.cvm.build import build_cvm_core, detect_compiler_info
from src.cvm.executor import run_cvm_a1_core
from src.stream_generator import Distribution, StreamConfig, generate_stream
from src.types import CSV_COLUMNS, CSV_HEADER, CVMResult, ExperimentConfig, ExperimentStatus


class TestE2EPipeline(unittest.TestCase):
    """Test suite verifying end-to-end execution from generator to C++ and CSV report."""

    @classmethod
    def setUpClass(cls) -> None:
        """Compile cvm_core executable once before running integration tests."""
        cls.binary_path = build_cvm_core()
        cls.compiler, cls.build_flags = detect_compiler_info()

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_e2e_all_five_workloads(self) -> None:
        """Verify the pipeline executes successfully across all 5 workload distributions."""
        workloads = [
            ("all_duplicate", 200, 50, 1),
            ("all_distinct", 200, 200, 200),
            ("uniform", 500, 200, 100),
            ("skewed", 500, 200, 100),
            ("zipf", 500, 200, 100),
        ]

        csv_file = self.test_dir / "all_workloads.csv"
        writer = CSVReportWriter(csv_file)

        for workload, m, n, f0 in workloads:
            with self.subTest(workload=workload):
                cfg = ExperimentConfig(
                    m=m,
                    n=n,
                    f0=f0,
                    epsilon=0.1,
                    delta=0.05,
                    seed_generator=42,
                    seed_algorithm=42,
                    workload=workload,
                    compiler=self.compiler,
                    build_flags=self.build_flags,
                )
                dist_enum = Distribution(workload)
                stream_cfg = StreamConfig(
                    m=m,
                    n=n,
                    f0=f0,
                    distribution=dist_enum,
                    seed=42,
                )
                stream = generate_stream(stream_cfg)
                result = run_cvm_a1_core(cfg, stream, self.binary_path)

                self.assertEqual(result.status, ExperimentStatus.SUCCESS)
                self.assertIsNotNone(result.estimate)
                self.assertGreater(result.estimate, 0.0)
                self.assertIsNotNone(result.algorithm_runtime_ms)
                self.assertGreater(result.algorithm_runtime_ms, 0.0)
                self.assertIsNotNone(result.end_to_end_runtime_ms)
                self.assertGreaterEqual(result.end_to_end_runtime_ms, result.algorithm_runtime_ms)

                writer.write_record(cfg, result)

        with open(csv_file, mode="r", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        # Expected: 1 header + 5 data rows
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0], list(CSV_COLUMNS))
        for row in rows[1:]:
            self.assertEqual(len(row), 24)
            self.assertEqual(row[12], "success")

    def test_seed_reproducibility(self) -> None:
        """Verify identical seeds produce 100% identical mathematical algorithm outputs."""
        cfg = ExperimentConfig(
            m=1000,
            n=500,
            f0=250,
            epsilon=0.1,
            delta=0.05,
            seed_generator=999,
            seed_algorithm=999,
            workload="uniform",
        )
        stream_cfg = StreamConfig(
            m=1000,
            n=500,
            f0=250,
            distribution=Distribution.UNIFORM,
            seed=999,
        )

        res1 = run_cvm_a1_core(cfg, generate_stream(stream_cfg), self.binary_path)
        res2 = run_cvm_a1_core(cfg, generate_stream(stream_cfg), self.binary_path)

        # Mathematical outputs must be bit-identical
        self.assertEqual(res1.status, res2.status)
        self.assertEqual(res1.estimate, res2.estimate)
        self.assertEqual(res1.peak_sample_size, res2.peak_sample_size)
        self.assertEqual(res1.halving_count, res2.halving_count)

    def test_multi_trial_batch_execution(self) -> None:
        """Verify runner executes batch mode and writes distinct records per trial."""
        out_csv = self.test_dir / "batch_report.csv"
        argv = [
            "--m",
            "300",
            "--n",
            "150",
            "--f0",
            "80",
            "--eps",
            "0.1",
            "--delta",
            "0.05",
            "--workload",
            "skewed",
            "--trials",
            "3",
            "--out",
            str(out_csv),
        ]
        exit_code = main(argv)
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_csv.exists())

        with open(out_csv, mode="r", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        # Expected: Header + 3 trials = 4 rows
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], list(CSV_COLUMNS))

        trial_indices = [row[3] for row in rows[1:]]
        self.assertEqual(trial_indices, ["1", "2", "3"])

        # Check that run_ids are unique UUIDs
        run_ids = [row[0] for row in rows[1:]]
        self.assertEqual(len(set(run_ids)), 3)

    def test_controlled_abort_record_written_to_csv(self) -> None:
        """Verify aborted execution writes algorithm_abort with null estimate to CSV."""
        out_csv = self.test_dir / "abort_e2e.csv"
        writer = CSVReportWriter(out_csv)

        cfg = ExperimentConfig(
            m=100,
            n=50,
            f0=20,
            epsilon=0.05,
            delta=0.01,
            seed_generator=42,
            seed_algorithm=42,
        )
        abort_result = CVMResult(
            status=ExperimentStatus.ALGORITHM_ABORT,
            estimate=None,
            algorithm_runtime_ms=0.5,
            end_to_end_runtime_ms=1.0,
            peak_sample_size=20,
            halving_count=1,
            process_peak_memory_bytes=1048576,
            error_msg="Buffer capacity underflow during test",
        )
        writer.write_record(cfg, abort_result)

        with open(out_csv, mode="r", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        self.assertEqual(len(rows), 2)
        row = rows[1]
        self.assertEqual(row[12], "algorithm_abort")
        self.assertEqual(row[13], "")  # null estimate
        self.assertEqual(row[19], "")  # null signed_rel_error
        self.assertEqual(row[20], "")  # null abs_rel_error

    def test_append_preserves_previous_records(self) -> None:
        """Verify consecutive benchmark executions append records without data loss."""
        out_csv = self.test_dir / "append_e2e.csv"

        argv1 = [
            "--m",
            "200",
            "--n",
            "100",
            "--f0",
            "50",
            "--trials",
            "2",
            "--out",
            str(out_csv),
        ]
        exit_code1 = main(argv1)
        self.assertEqual(exit_code1, 0)

        argv2 = [
            "--m",
            "200",
            "--n",
            "100",
            "--f0",
            "50",
            "--trials",
            "2",
            "--out",
            str(out_csv),
        ]
        exit_code2 = main(argv2)
        self.assertEqual(exit_code2, 0)

        with open(out_csv, mode="r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        # 1 header + 2 records (session 1) + 2 records (session 2) = 5 lines
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[0], CSV_HEADER)


if __name__ == "__main__":
    unittest.main()
