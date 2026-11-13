"""Regression checks for threshold validation and replay with the actual Core threshold."""

import csv
import hashlib
import json
import subprocess
from unittest.mock import MagicMock

import pytest

from runner import main
from src.cvm.build import build_cvm_core
from src.cvm.executor import query_core_threshold, run_cvm_a1_core
from src.types import CSV_COLUMNS, ExperimentConfig, ExperimentStatus


def fake_core(monkeypatch, stdout, threshold=1201):
    process = MagicMock()
    process.__enter__.return_value = process
    process.communicate.return_value = (stdout, "")
    process.returncode = 0
    monkeypatch.setattr("src.cvm.executor.subprocess.Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr("src.cvm.executor.query_core_threshold", lambda *_: threshold)


@pytest.mark.parametrize(
    ("m", "epsilon", "expected", "reported"),
    [
        (8, 0.3, 1201, 1200),
        (4096, 0.3, 2401, 2400),
        (8, 2**-26, 486388759756013568, 486388759756014068),
    ],
)
def test_stream_output_must_match_core_threshold_query(monkeypatch, m, epsilon, expected, reported):
    cfg = ExperimentConfig(m, 1, 1, epsilon, 0.125, 42, 42)
    fake_core(monkeypatch, f"success,1,0.01,1,0,{reported}\n", expected)
    result = run_cvm_a1_core(cfg, [1] * m, "fixture-core")
    assert result.status is ExperimentStatus.EXECUTION_ERROR
    assert result.effective_s is None
    assert str(expected) in result.error_msg


@pytest.mark.parametrize(
    ("code", "stdout"),
    [(1, ""), (0, "csv-v2,1201\n"), (0, "threshold-v1,1201\n1200\n")],
)
def test_rejects_unsupported_or_invalid_threshold_query(monkeypatch, tmp_path, code, stdout):
    response = subprocess.CompletedProcess([], code, stdout, "unsupported format" if code else "")
    monkeypatch.setattr("src.cvm.executor.subprocess.run", lambda *args, **kwargs: response)
    cfg = ExperimentConfig(8, 1, 1, 0.3, 0.125, 42, 42)
    with pytest.raises(ValueError, match="threshold"):
        query_core_threshold(tmp_path / "core", cfg)


def test_boundary_output_is_accepted(monkeypatch):
    cfg = ExperimentConfig(8, 1, 1, 0.3, 0.125, 42, 42)
    assert cfg.s == 1200
    fake_core(monkeypatch, "success,1,0.01,1,0,1201\n")
    result = run_cvm_a1_core(cfg, [1] * 8, "fixture-core")
    assert result.status is ExperimentStatus.SUCCESS, result.error_msg
    assert result.effective_s == 1201


@pytest.mark.parametrize(
    ("m", "epsilon", "delta", "reported"),
    [
        (8, 0.3, 0.125, 1199),  # Wrong side of the integer boundary.
        (8, 0.3, 0.125, 9999),  # Large mismatch.
        (256, 0.5, 0.05, 735),  # Python reference 736, far from either boundary.
        (256, 0.5, 0.05, 737),
    ],
)
def test_incompatible_threshold_is_rejected(monkeypatch, m, epsilon, delta, reported):
    cfg = ExperimentConfig(m, 1, 1, epsilon, delta, 42, 42)
    fake_core(monkeypatch, f"success,1,0.01,1,0,{reported}\n", 1201 if m == 8 else 736)
    result = run_cvm_a1_core(cfg, [1] * cfg.m, "fixture-core")
    assert result.status is ExperimentStatus.EXECUTION_ERROR
    assert result.estimate is None
    assert f"Core s={reported}" in result.error_msg


@pytest.mark.parametrize(
    ("stdout", "diagnostic"),
    [
        ("success,1,0.01,1,0", "csv-v2"),
        *[
            (f"success,1,0.01,1,0,{s}", "threshold")
            for s in (
                "",
                "1.5",
                "-1",
                "0",
                "1_200",
                "１２00",
                "1200 ",
                str(1 << 64),
            )
        ],
    ],
)
def test_malformed_threshold_is_rejected(monkeypatch, stdout, diagnostic):
    fake_core(monkeypatch, stdout)
    cfg = ExperimentConfig(8, 1, 1, 0.3, 0.125, 42, 42)
    result = run_cvm_a1_core(cfg, [1] * 8, "fixture-core")
    assert result.status is ExperimentStatus.EXECUTION_ERROR
    assert result.effective_s is None
    assert diagnostic in result.error_msg


def test_boundary_abort_keeps_empty_estimate(monkeypatch):
    cfg = ExperimentConfig(4096, 4096, 4096, 0.3, 0.125, 42, 42)
    assert cfg.s == 2400
    fake_core(monkeypatch, "algorithm_abort,,0.01,2401,1,2401", 2401)
    result = run_cvm_a1_core(cfg, range(cfg.m), "fixture-core")
    assert result.status is ExperimentStatus.ALGORITHM_ABORT, result.error_msg
    assert result.effective_s == 2401
    assert result.estimate is None


@pytest.mark.parametrize(
    ("m", "eps", "delta", "workload", "s"),
    [
        (8, "0.3", "0.125", "all_duplicate", None),
        (4096, "0.3", "0.125", "all_distinct", None),
        (8, str(2**-26), "0.125", "all_duplicate", 486388759756013568),
        (256, "0.5", "0.05", "all_distinct", 736),
        (1024, "0.5", "0.05", "all_distinct", 832),
        (4096, "0.5", "0.05", "all_distinct", 928),
    ],
)
def test_real_core_threshold_and_resume(tmp_path, m, eps, delta, workload, s):
    core = build_cvm_core()
    out = tmp_path / "real.csv"
    f0 = 1 if workload == "all_duplicate" else m
    args = [
        "--m",
        str(m),
        "--n",
        str(f0),
        "--f0",
        str(f0),
        "--workload",
        workload,
        "--eps",
        eps,
        "--delta",
        delta,
        "--seed-gen",
        "44000",
        "--seed-algo",
        "84000",
    ]
    proc = subprocess.run(
        [
            str(core),
            "--m",
            str(m),
            "--eps",
            eps,
            "--delta",
            delta,
            "--seed",
            "84000",
            "--output-format",
            "csv-v2",
        ],
        input="0\n" * m if f0 == 1 else "".join(f"{i}\n" for i in range(m)),
        text=True,
        capture_output=True,
        check=True,
    )
    assert proc.stdout.split(",")[0] == "success"
    actual_s = int(proc.stdout.split(",")[-1])
    config = ExperimentConfig(m, f0, f0, float(eps), float(delta), 44000, 84000)
    assert query_core_threshold(core, config) == actual_s
    if s is None:
        reference = 1200 if m == 8 else 2400
        assert actual_s in (reference, reference + 1)
    else:
        assert actual_s == s

    assert main([*args, "--out", str(out)]) == 0
    sidecar = out.with_suffix(".metadata.json")
    snapshot = out.read_bytes(), sidecar.read_bytes()
    assert main([*args, "--out", str(out)]) == 0
    assert main([*args, "--out", str(out), "--dry-run"]) == 1
    assert (out.read_bytes(), sidecar.read_bytes()) == snapshot
    metadata = json.loads(snapshot[1])
    assert metadata["records_count"] == 1
    assert metadata["byte_length"] == len(snapshot[0])
    assert metadata["sha256"] == hashlib.sha256(snapshot[0]).hexdigest()
    replay = tmp_path / "replay.csv"
    assert main([*args, "--out", str(replay)]) == 0
    with (
        out.open(newline="", encoding="utf-8") as first,
        replay.open(newline="", encoding="utf-8") as second,
    ):
        reader = csv.DictReader(first)
        [record] = reader
        [repeated] = csv.DictReader(second)
        assert tuple(reader.fieldnames) == CSV_COLUMNS
    assert record["status"] == repeated["status"] == "success"
    assert int(record["s"]) == actual_s
    for column in ("estimate", "halving_count", "peak_sample_size", "s"):
        assert record[column] == repeated[column]
