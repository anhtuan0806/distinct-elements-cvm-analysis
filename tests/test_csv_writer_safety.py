"""Regression tests for preserving CSV reports across restarts and concurrent writers."""

from __future__ import annotations

import csv
import multiprocessing
import tempfile
import threading
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from multiprocessing.synchronize import Barrier, Event
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

from src.csv_writer import CSVReportWriter
from src.types import CSV_HEADER, CVMResult, ExperimentConfig, ExperimentStatus

RECORD = (
    "test-run-1,CVM-A1,uniform,1,100,50,20,0.05,0.01,23067,42,42,success,"
    "20.00,1.000,1.000,10,1,1048576,0.000000,0.000000,Linux-Test,g++ 11.4,-O3"
)


def append_records(
    filepath: str,
    seed: int,
    count: int = 1,
    ready: Event | None = None,
    barrier: Barrier | None = None,
) -> None:
    """Run the real writer in a child process without inheriting file descriptors."""
    if ready is not None:
        ready.set()
    if barrier is not None:
        barrier.wait(timeout=10)
    writer = CSVReportWriter(filepath)
    config = ExperimentConfig(
        m=100,
        n=50,
        f0=20,
        epsilon=0.05,
        delta=0.01,
        seed_generator=seed,
        seed_algorithm=seed,
        s=23067,
        workload="uniform",
        trial=1,
        algorithm="CVM-A1",
        run_id="test-run-1" if seed == 42 else f"run-{seed}",
        env_os="Linux-Test",
        compiler="g++ 11.4",
        build_flags="-O3",
    )
    result = CVMResult(
        status=ExperimentStatus.SUCCESS,
        estimate=20.0,
        algorithm_runtime_ms=1.0,
        end_to_end_runtime_ms=1.0,
        peak_sample_size=10,
        halving_count=1,
        process_peak_memory_bytes=1048576,
    )
    for _ in range(count):
        writer.write_record(config, result)


class TestCSVWriterSafety(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.filepath = Path(self.temp_dir.name) / "report.csv"
        self.config = ExperimentConfig(
            m=100,
            n=50,
            f0=20,
            epsilon=0.05,
            delta=0.01,
            seed_generator=42,
            seed_algorithm=42,
            s=23067,
            workload="uniform",
            trial=1,
            algorithm="CVM-A1",
            run_id="test-run-1",
            env_os="Linux-Test",
            compiler="g++ 11.4",
            build_flags="-O3",
        )
        self.result = CVMResult(
            status=ExperimentStatus.SUCCESS,
            estimate=20.0,
            algorithm_runtime_ms=1.0,
            end_to_end_runtime_ms=1.0,
            peak_sample_size=10,
            halving_count=1,
            process_peak_memory_bytes=1048576,
        )

    def read_rows(self) -> list[list[str]]:
        with self.filepath.open(encoding="utf-8", newline="") as report:
            return list(csv.reader(report))

    def test_rejects_incompatible_headers_without_changing_file(self) -> None:
        for header in ["seed,estimate", CSV_HEADER.replace("run_id,algorithm,", "algorithm,run_id,")]:
            with self.subTest(header=header):
                original = (header + "\n42,20\n").encode()
                self.filepath.write_bytes(original)
                with self.assertRaises(ValueError):
                    CSVReportWriter(self.filepath)
                self.assertEqual(self.filepath.read_bytes(), original)

    def test_rechecks_header_before_append(self) -> None:
        writer = CSVReportWriter(self.filepath)
        original = b"seed,estimate\n42,20\n"
        self.filepath.write_bytes(original)
        with self.assertRaises(ValueError):
            writer.write_record(self.config, self.result)
        self.assertEqual(self.filepath.read_bytes(), original)

    def test_separates_complete_last_record_without_newline(self) -> None:
        self.filepath.write_text(CSV_HEADER + "\n" + RECORD, encoding="utf-8")
        CSVReportWriter(self.filepath).write_record(self.config, self.result)
        self.assertEqual(
            self.read_rows(), [CSV_HEADER.split(","), RECORD.split(","), RECORD.split(",")]
        )

    def test_separates_header_without_newline(self) -> None:
        self.filepath.write_text(CSV_HEADER, encoding="utf-8")
        CSVReportWriter(self.filepath).write_record(self.config, self.result)
        self.assertEqual(self.read_rows(), [CSV_HEADER.split(","), RECORD.split(",")])

    def test_rejects_truncated_tail_without_changing_file(self) -> None:
        for tail in ["100,50", "100,50\n", RECORD.rsplit(",", 1)[0] + ",", '"100,50']:
            with self.subTest(tail=tail):
                original = (CSV_HEADER + "\n" + RECORD + "\n" + tail).encode()
                self.filepath.write_bytes(original)
                with self.assertRaises(ValueError):
                    CSVReportWriter(self.filepath)
                self.assertEqual(self.filepath.read_bytes(), original)

    def test_rechecks_tail_before_append(self) -> None:
        writer = CSVReportWriter(self.filepath)
        original = (CSV_HEADER + "\n100,50").encode()
        self.filepath.write_bytes(original)
        with self.assertRaises(ValueError):
            writer.write_record(self.config, self.result)
        self.assertEqual(self.filepath.read_bytes(), original)

    def test_initialization_respects_another_process_file_lock(self) -> None:
        if fcntl is None:
            self.skipTest("fcntl not available on this platform")
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        process = context.Process(target=append_records, args=(str(self.filepath), 42, 1, ready))
        with self.filepath.open("a+b") as held_file:
            fcntl.flock(held_file.fileno(), fcntl.LOCK_EX)
            try:
                process.start()
                self.assertTrue(ready.wait(timeout=10), "Child writer did not start")
                process.join(timeout=0.5)
                self.assertTrue(process.is_alive(), "Writer bypassed the report lock")
                self.assertEqual(self.filepath.read_bytes(), b"")
            finally:
                fcntl.flock(held_file.fileno(), fcntl.LOCK_UN)
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(self.read_rows(), [CSV_HEADER.split(","), RECORD.split(",")])

    def test_concurrent_processes_preserve_all_records(self) -> None:
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(4)
        processes = [
            context.Process(
                target=append_records,
                args=(str(self.filepath), seed, 10, None, barrier),
            )
            for seed in range(4)
        ]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=15)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
        rows = self.read_rows()
        self.assertEqual(rows[0], CSV_HEADER.split(","))
        self.assertEqual(len(rows), 41)
        self.assertTrue(all(len(row) == 24 for row in rows))
        # row[11] is seed_algorithm
        self.assertEqual(
            Counter(row[11] for row in rows[1:]),
            {"0": 10, "1": 10, "2": 10, "3": 10},
        )

    def test_concurrent_threads_preserve_all_records(self) -> None:
        barrier = threading.Barrier(8)

        def append(seed: int) -> None:
            barrier.wait(timeout=10)
            append_records(str(self.filepath), seed, count=5)

        with ThreadPoolExecutor(max_workers=8) as workers:
            list(workers.map(append, range(8)))
        rows = self.read_rows()
        self.assertEqual(rows[0], CSV_HEADER.split(","))
        self.assertEqual(len(rows), 41)
        self.assertTrue(all(len(row) == 24 for row in rows))
        self.assertEqual(
            Counter(row[11] for row in rows[1:]),
            {str(seed): 5 for seed in range(8)},
        )
