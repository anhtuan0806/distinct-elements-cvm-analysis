import csv
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from runner import _batch
from scripts.analyze_results import summarize
from scripts.plot_results import plot_summary
from scripts.validate_results import validate
from src.benchmark_report import PROTOCOL_VERSION
from src.types import CSV_COLUMNS, ExperimentConfig


@pytest.fixture
def raw_fixture(tmp_path):
    """SYNTHETIC TEST DATA. The protocol envelope is simulated only inside tests."""
    path = tmp_path / "fixture.csv"
    config = ExperimentConfig(100, 200, 20, 0.5, 0.05, 100, 200, workload="uniform")
    row = dict.fromkeys(CSV_COLUMNS, "")
    row.update(
        run_id=str(uuid4()),
        algorithm="CVM-A1",
        workload=config.workload,
        trial=1,
        m=config.m,
        n=config.n,
        F0=config.f0,
        epsilon=config.epsilon,
        delta=config.delta,
        s=config.s,
        seed_generator=100,
        seed_algorithm=200,
        status="success",
        estimate=20,
        algorithm_runtime_ms=2,
        end_to_end_runtime_ms=5,
        peak_sample_size=20,
        halving_count=0,
        process_peak_memory_bytes=1048576,
        signed_rel_error=0,
        abs_rel_error=0,
        env_os=config.env_os,
        compiler="test gcc",
        build_flags="-O3",
    )
    return path, config, row


def write_fixture(path, config, rows, *, columns=CSV_COLUMNS, changes=None):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    content = path.read_bytes()
    batch = _batch(
        config,
        len(rows),
        "real",
        {
            "binary_sha256": "b" * 64,
            "compiler": "test gcc",
            "build_flags": "-O3",
        },
    )
    batch.update(first_record=1, last_record=len(rows), git_commit="a" * 40)
    metadata = dict(
        schema_version="P0",
        protocol_version=PROTOCOL_VERSION,
        data_source="real",
        execution_mode="real",
        target_csv=path.name,
        records_count=len(rows),
        byte_length=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        batches=[batch],
    )
    metadata.update(changes or {})
    path.with_suffix(".metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def test_valid_raw_and_missing_ram(raw_fixture):
    path, config, row = raw_fixture
    row["process_peak_memory_bytes"] = ""
    write_fixture(path, config, [row])
    report = validate(path)
    assert report.verified, report.errors
    [summary] = summarize(report.rows)
    assert summary["ram_count"] == 0
    assert summary["ram_mean"] is None


def test_missing_column(raw_fixture):
    path, config, row = raw_fixture
    write_fixture(path, config, [row], columns=CSV_COLUMNS[:-1])
    assert any("build_flags" in error for error in validate(path).errors)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("m", "1.5"),
        ("seed_algorithm", -1),
        ("trial", 0),
        ("epsilon", "nan"),
        ("delta", 1),
        ("F0", 101),
        ("algorithm_runtime_ms", -1),
        ("status", "bad"),
        ("peak_sample_size", 25),
        ("process_peak_memory_bytes", 0),
        ("seed_generator", 999),
    ],
)
def test_invalid_fields(raw_fixture, field, value):
    path, config, row = raw_fixture
    write_fixture(path, config, [{**row, field: value}])
    assert any(field in error for error in validate(path).errors)


def test_duplicate_run_and_logical_trial(raw_fixture):
    path, config, row = raw_fixture
    write_fixture(path, config, [row, row])
    sidecar = path.with_suffix(".metadata.json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    [batch] = metadata["batches"]
    batch.update(last_record=1, requested_trials=1)
    metadata["batches"].append(
        {
            **batch,
            "batch_id": str(uuid4()),
            "first_record": 2,
            "last_record": 2,
        }
    )
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    errors = validate(path).errors
    assert any("duplicate run_id" in error for error in errors)
    assert any("duplicate completed trial" in error for error in errors)


@pytest.mark.parametrize("estimate", ["", 0])
def test_abort(raw_fixture, estimate):
    path, _, row = raw_fixture
    config = ExperimentConfig(
        4096, 4096, 4096, 0.5, 0.05, 100, 200, workload="all_distinct", env_os=row["env_os"]
    )
    row.update(
        workload=config.workload,
        m=config.m,
        n=config.n,
        F0=config.f0,
        s=config.s,
        status="algorithm_abort",
        estimate=estimate,
        signed_rel_error="",
        abs_rel_error="",
        peak_sample_size=config.s,
        halving_count=1,
    )
    write_fixture(path, config, [row])
    report = validate(path)
    assert report.verified == (estimate == ""), report.errors
    if report.verified:
        [group] = summarize(report.rows)
        assert group["abort_count"] == group["abort_runtime_count"] == 1
        assert group["runtime_count"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"records_count": 10},
        {"sha256": "0" * 64},
        {"byte_length": 100},
        {"pending": {}},
        {"data_source": "synthetic_mock", "execution_mode": "synthetic_mock"},
    ],
)
def test_invalid_metadata(raw_fixture, changes):
    path, config, row = raw_fixture
    write_fixture(path, config, [row], changes=changes)
    assert not validate(path).verified


def test_dryrun_marker_and_historical_provenance(raw_fixture):
    path, config, row = raw_fixture
    write_fixture(path, config, [{**row, "algorithm": "CVM-A1-dryrun"}])
    assert validate(path).classification == "synthetic"
    write_fixture(path, config, [row])
    path.with_suffix(".metadata.json").unlink()
    assert validate(path).classification == "unverified"


def test_empty_sidecar_cannot_verify_raw(raw_fixture):
    path, config, row = raw_fixture
    write_fixture(path, config, [row])
    path.with_suffix(".metadata.json").write_text("{}", encoding="utf-8")
    assert not validate(path).verified


def test_zero_f0_and_cpp_threshold_warning(raw_fixture):
    path, config, row = raw_fixture
    from dataclasses import replace

    config = replace(config, f0=0)
    row.update(
        F0=0, estimate=0, peak_sample_size=0, s=config.s + 1, signed_rel_error="", abs_rel_error=""
    )
    write_fixture(path, config, [row])
    report = validate(path)
    assert report.verified and any("s=" in message for message in report.warnings)
    [group] = summarize(report.rows)
    assert group["f0_over_m"] == 0
    assert group["signed_rel_error_mean"] is None
    assert group["s"] == config.s + 1


def test_summary_grouping_and_synthetic_plot(tmp_path):
    common = dict(
        algorithm="CVM-A1",
        n=200,
        epsilon=0.5,
        delta=0.05,
        s=700,
        env_os="test",
        compiler="test",
        build_flags="test",
        python="3.14",
        cpu="test",
        platform_os="test",
        binary_sha256="test",
        source_tree_sha256="test",
        generator_sha256="test",
        git_commit="test",
        status="success",
        end_to_end_runtime_ms=10,
        peak_sample_size=20,
        halving_count=0,
        signed_rel_error=-0.1,
        abs_rel_error=0.1,
    )
    rows = [
        dict(
            common,
            workload=w,
            m=m,
            F0=m // 4,
            algorithm_runtime_ms=t,
            process_peak_memory_bytes=ram,
        )
        for w in ("uniform", "skewed")
        for m in (40, 80)
        for t, ram in ((1, 1048576), (2, None), (9, 3145728))
    ]
    rows.append(
        dict(rows[0], status="execution_error", algorithm_runtime_ms=None, peak_sample_size=0)
    )
    groups = summarize(rows)
    assert len(groups) == 4
    group = next(g for g in groups if g["m"] == 40 and g["workload"] == "uniform")
    assert group["run_count"] == 4 and group["execution_error_count"] == 1
    assert group["runtime_count"] == group["sample_count"] == 3
    assert group["runtime_mean"] == 4 and group["runtime_median"] == 2
    assert group["ram_count"] == 2 and group["ram_median"] == 2097152
    assert group["signed_rel_error_mean"] == -0.1
    paths = plot_summary(groups, tmp_path / "synthetic", label="SYNTHETIC TEST DATA")
    assert len(paths) == 3
    for path in paths:
        with Image.open(path) as png:
            assert png.format == "PNG" and png.width >= 1200
            png.verify()


def test_plot_omits_unmeasured_ram(tmp_path):
    assert plot_summary([], tmp_path, label="SYNTHETIC TEST DATA") == []
    assert list(Path(tmp_path).iterdir()) == []
