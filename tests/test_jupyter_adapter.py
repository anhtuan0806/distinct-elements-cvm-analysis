"""Tests for the Jupyter Notebook experiment adapter module."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from src.jupyter_adapter import JupyterBenchmarkResult, run_jupyter_benchmark
from src.types import CSV_COLUMNS


def test_adapter_parameter_validation() -> None:
    """Verify input validation catches boundary and semantic violations."""
    # m must be positive uint64
    with pytest.raises(ValueError, match="m must be an integer"):
        run_jupyter_benchmark(m=-10)

    # all_distinct requires n >= m
    with pytest.raises(ValueError, match="all_distinct requires n >= m"):
        run_jupyter_benchmark(m=500, n=200, workload="all_distinct")

    # all_distinct requires f0 == m
    with pytest.raises(ValueError, match="all_distinct requires f0=m"):
        run_jupyter_benchmark(m=500, n=1000, f0=400, workload="all_distinct")

    # all_duplicate requires f0 == 1
    with pytest.raises(ValueError, match="all_duplicate requires f0=1"):
        run_jupyter_benchmark(m=500, n=1000, f0=2, workload="all_duplicate")

    # f0 cannot exceed min(m, n)
    with pytest.raises(ValueError, match="exceeds min"):
        run_jupyter_benchmark(m=500, n=300, f0=400, workload="uniform")

    # epsilon and delta must be in (0, 1)
    with pytest.raises(ValueError, match="epsilon must be in"):
        run_jupyter_benchmark(m=100, epsilon=1.5)

    with pytest.raises(ValueError, match="delta must be in"):
        run_jupyter_benchmark(m=100, delta=0.0)

    # invalid workload
    with pytest.raises(ValueError, match="Invalid workload"):
        run_jupyter_benchmark(m=100, workload="non_existent")

    # unsupported preset
    with pytest.raises(ValueError, match="Unsupported preset"):
        run_jupyter_benchmark(preset="unsupported")


def test_adapter_parameter_precedence(tmp_path: Path) -> None:
    """Verify preset defaults and explicit overrides behave predictably."""
    # When both m and preset are None, defaults to smoke preset
    out_dir = tmp_path / "real_precedence"
    res = run_jupyter_benchmark(output_dir=out_dir)
    assert isinstance(res, JupyterBenchmarkResult)
    assert res.records_count == 2
    assert res.configs_count == 1

    first_record = res.results[0]
    assert first_record["m"] == 256
    assert first_record["workload"] == "all_distinct"
    assert first_record["status"] == "success"

    # Explicit override with preset: trials=3
    res2 = run_jupyter_benchmark(preset="smoke", trials=3, output_dir=out_dir)
    assert res2.records_count == 3


def test_adapter_smoke_run_creates_valid_real_raw(tmp_path: Path) -> None:
    """Verify smoke run produces real CVM-A1 CSV records and companion sidecar."""
    clean_dir = tmp_path / "real_runs"
    result = run_jupyter_benchmark(preset="smoke", output_dir=clean_dir)

    assert result.csv_path.is_file()
    assert result.sidecar_path.is_file()
    assert result.records_count == 2
    assert result.configs_count == 1

    # Verify CSV content
    with open(result.csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == list(CSV_COLUMNS)

        rows = list(reader)
        assert len(rows) == 2
        for row in rows:
            record = dict(zip(CSV_COLUMNS, row, strict=True))
            assert record["algorithm"] == "CVM-A1"
            assert record["status"] == "success"
            assert record["workload"] == "all_distinct"
            assert float(record["estimate"]) > 0
            assert float(record["algorithm_runtime_ms"]) >= 0
            assert float(record["end_to_end_runtime_ms"]) >= float(record["algorithm_runtime_ms"])
            assert record["process_peak_memory_bytes"] != ""
            assert int(record["process_peak_memory_bytes"]) > 0

    # Verify metadata sidecar
    metadata = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert metadata["schema_version"] == "P0"
    assert metadata["protocol_version"] == "cvm-a1-tv3-v1"
    assert metadata["data_source"] == "real"
    assert metadata["execution_mode"] == "real"
    assert metadata["records_count"] == 2
    assert metadata["sha256"] == hashlib.sha256(result.csv_path.read_bytes()).hexdigest()
    assert len(metadata["batches"]) == 1

    batch = metadata["batches"][0]
    assert batch["first_record"] == 1
    assert batch["last_record"] == 2
    assert batch["environment"]["memory_metric"] == "core_peak_resident_bytes"


def test_adapter_sweep_multi_workload_and_trials(tmp_path: Path) -> None:
    """Verify sweep across multiple m values and workloads with seed stepping."""
    clean_dir = tmp_path / "real_sweep"
    result = run_jupyter_benchmark(
        m=[100, 200],
        workload=["uniform", "skewed"],
        trials=3,
        seed=100,
        output_dir=clean_dir,
    )

    # 2 workloads * 2 m values = 4 configs; 4 configs * 3 trials = 12 records
    assert result.records_count == 12
    assert result.configs_count == 4

    with open(result.csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        assert len(rows) == 12

        # Check that seed offsets are strictly stepped per trial
        trials_by_config: dict[str, list[dict]] = {}
        for r in rows:
            cfg_key = f"{r['workload']}_{r['m']}"
            trials_by_config.setdefault(cfg_key, []).append(r)

        assert len(trials_by_config) == 4
        for cfg_key, cfg_rows in trials_by_config.items():
            assert len(cfg_rows) == 3
            for idx, trial_row in enumerate(cfg_rows):
                assert int(trial_row["trial"]) == idx + 1
                assert int(trial_row["seed_generator"]) == 100 + idx
                assert int(trial_row["seed_algorithm"]) == 100 + idx

    # Check that metadata batches are contiguous
    metadata = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert metadata["records_count"] == 12
    assert len(metadata["batches"]) == 4

    expected_first = 1
    for b in metadata["batches"]:
        assert b["first_record"] == expected_first
        assert b["last_record"] == expected_first + 2
        expected_first = b["last_record"] + 1


def test_adapter_preserves_p0_legacy_files(tmp_path: Path) -> None:
    """Verify running Jupyter benchmark never overwrites existing real results."""
    # Ensure real/raw_benchmark.csv is not modified
    p0_file = Path("results/real/raw_benchmark.csv")
    original_mtime = p0_file.stat().st_mtime if p0_file.exists() else None

    # Run jupyter benchmark
    clean_dir = tmp_path / "isolated_session"
    res = run_jupyter_benchmark(preset="smoke", output_dir=clean_dir)

    assert res.csv_path.parent == clean_dir
    assert res.csv_path != p0_file

    if p0_file.exists():
        assert p0_file.stat().st_mtime == original_mtime
