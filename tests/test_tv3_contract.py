"""Regression tests for the managed TV3 runner."""

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from runner import main, run_single_trial
from src.benchmark_report import HEADER, BenchmarkReport
from src.cvm.build import build_cvm_core
from src.cvm.executor import run_cvm_a1_core
from src.types import CVMResult, ExperimentConfig, ExperimentStatus


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_resume_and_mode_isolation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "sample.csv"
    sidecar = output.with_suffix(".metadata.json")
    args = ["--m", "8", "--n", "8", "--f0", "8", "--workload", "all_distinct"]
    assert main([*args, "--out", "sample.csv", "--trials", "2"]) == 0
    raw = output.read_bytes()
    metadata = sidecar.read_bytes()
    assert json.loads(metadata)["records_count"] == 2
    assert main([*args, "--out", str(output), "--trials", "2"]) == 0
    assert output.read_bytes() == raw
    assert sidecar.read_bytes() == metadata
    assert main([*args, "--out", str(output), "--dry-run"]) != 0
    assert output.read_bytes() == raw
    assert sidecar.read_bytes() == metadata


@pytest.mark.parametrize("requested", [2, 4])
def test_requested_s_mismatch_is_an_error(requested):
    core = build_cvm_core()
    cfg = ExperimentConfig(8, 8, 8, 0.2, 0.1, 42, 42)
    result = run_cvm_a1_core(replace(cfg, s=requested), range(8), core)
    assert result.status == ExperimentStatus.EXECUTION_ERROR
    assert result.estimate is None
    assert result.effective_s == 2797
    assert "2797" in result.error_msg


def _args(path):
    return ["--m", "8", "--n", "8", "--f0", "8", "--workload", "all_distinct", "--out", str(path)]


def test_append_seed_and_resume_missing_trial(tmp_path):
    output = tmp_path / "resume.csv"
    args = _args(output)
    assert main(args) == 0
    first = rows(output)[0]
    assert main([*args, "--trials", "2"]) == 0
    assert main([*args, "--trials", "2", "--seed", "99"]) == 0
    result = rows(output)
    assert len(result) == 4 and result[0] == first
    assert [row["seed_algorithm"] for row in result] == ["42", "43", "99", "100"]
    assert {row["s"] for row in result} == {"60691"}
    meta = json.loads(output.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    assert meta["records_count"] == len(result)
    assert meta["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert [(b["first_record"], b["last_record"]) for b in meta["batches"]] == [
        (1, 1),
        (2, 2),
        (3, 4),
    ]
    assert all(b["environment"]["binary_sha256"] for b in meta["batches"])
    assert meta["batches"][-1]["configuration"]["seed_algorithm"] == 99


def test_synthetic_replay_and_reverse_mode_isolation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "mock.csv"
    assert main([*_args("mock.csv"), "--dry-run"]) == 0
    meta = output.with_suffix(".metadata.json")
    snapshot = (output.read_bytes(), meta.read_bytes())
    assert main([*_args(output), "--dry-run"]) == 0
    assert main(_args("mock.csv")) == 1
    assert (output.read_bytes(), meta.read_bytes()) == snapshot
    result = rows(output)
    assert len(result) == len({r["run_id"] for r in result}) == 2
    assert {r["algorithm"] for r in result} == {"CVM-A1-dryrun"}
    assert {r["status"] for r in result} == {"success", "algorithm_abort"}
    assert json.loads(snapshot[1])["data_source"] == "synthetic_mock"


@pytest.mark.parametrize("partial", [True, False])
def test_resume_after_interrupted_record(tmp_path, monkeypatch, partial):
    output = tmp_path / "interrupted.csv"
    args = _args(output)
    original_write = BenchmarkReport._write_bytes
    original_save = BenchmarkReport._save

    if partial:

        def interrupted_write(report, data):
            if data == HEADER:
                return original_write(report, data)
            original_write(report, data[: len(data) // 2])
            raise OSError("interrupted during CSV append")

        monkeypatch.setattr(BenchmarkReport, "_write_bytes", interrupted_write)
    else:

        def interrupted_save(report, state):
            if state["records_count"] == 1 and "pending" not in state:
                raise OSError("interrupted after CSV append")
            original_save(report, state)

        monkeypatch.setattr(BenchmarkReport, "_save", interrupted_save)

    assert main(args) == 1
    sidecar = output.with_suffix(".metadata.json")
    pending = json.loads(sidecar.read_text(encoding="utf-8"))["pending"]
    monkeypatch.undo()
    assert main([*args, "--trials", "2"]) == 0
    result = rows(output)
    assert [row["trial"] for row in result] == ["1", "2"]
    assert result[0]["run_id"] == next(csv.reader([pending["record"]]))[0]
    final = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "pending" not in final and final["records_count"] == 2


def test_managed_output_rejects_metadata_mismatch_and_duplicate(tmp_path):
    output = tmp_path / "tampered.csv"
    args = _args(output)
    assert main(args) == 0
    sidecar = output.with_suffix(".metadata.json")
    raw = output.read_bytes()
    original = sidecar.read_bytes()
    damaged = raw.replace(b"60691", b"60690")
    assert damaged != raw and len(damaged) == len(raw)
    output.write_bytes(damaged)
    assert main(args) == 1
    assert (output.read_bytes(), sidecar.read_bytes()) == (damaged, original)
    output.write_bytes(raw)
    sidecar.write_bytes(original.replace(b'"records_count": 1', b'"records_count": 5'))
    mismatch = sidecar.read_bytes()
    assert main(args) == 1
    assert output.read_bytes() == raw and sidecar.read_bytes() == mismatch

    # Forge consistent lengths/hash and a new UUID to exercise the logical-key check.
    first, tail = raw.split(b"\n", 1)
    duplicate = b"another-id," + tail.split(b",", 1)[1]
    forged = first + b"\n" + tail + duplicate
    output.write_bytes(forged)
    meta = json.loads(original)
    meta.update(records_count=2, byte_length=len(forged), sha256=hashlib.sha256(forged).hexdigest())
    meta["batches"][0]["last_record"] = 2
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    assert main(args) == 1
    assert output.read_bytes() == forged


def test_legacy_output_is_preserved(tmp_path):
    output = tmp_path / "legacy.csv"
    output.write_bytes(HEADER)
    sidecar = output.with_suffix(".metadata.json")
    sidecar.write_text('{"data_source": "real", "records_count": 3}', encoding="utf-8")
    snapshot = output.read_bytes(), sidecar.read_bytes()
    assert main(_args(output)) == 1
    assert (output.read_bytes(), sidecar.read_bytes()) == snapshot


@pytest.mark.parametrize("field", ["binary", "generator", "python", "missing", "config", "flags"])
def test_resume_rejects_inconsistent_batch_provenance(tmp_path, field, caplog):
    output = tmp_path / "contradiction.csv"
    assert main(_args(output)) == 0
    sidecar = output.with_suffix(".metadata.json")
    metadata = json.loads(sidecar.read_bytes())
    [batch] = metadata["batches"]
    if field == "binary":
        batch["environment"]["binary_sha256"] = "0" * 64
    elif field == "generator":
        batch["generator_sha256"] = "0" * 64
    elif field == "python":
        batch["environment"]["python"] = "0.0.0"
    elif field == "missing":
        del batch["environment"]
    elif field == "flags":
        batch["environment"]["build_flags"] = "other-flags"
    else:
        batch["configuration"]["epsilon"] = 0.3
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    snapshot = (output.read_bytes(), sidecar.read_bytes())
    assert main(_args(output)) == 1
    assert "metadata" in caplog.text
    assert (output.read_bytes(), sidecar.read_bytes()) == snapshot


def test_pending_batch_mismatch_preserves_partial_record(tmp_path, monkeypatch):
    output = tmp_path / "pending.csv"
    original_write = BenchmarkReport._write_bytes

    def interrupted_write(report, data):
        if data == HEADER:
            return original_write(report, data)
        original_write(report, data[: len(data) // 2])
        raise OSError("interrupted during CSV append")

    with monkeypatch.context() as patch:
        patch.setattr(BenchmarkReport, "_write_bytes", interrupted_write)
        assert main(_args(output)) == 1
    sidecar = output.with_suffix(".metadata.json")
    metadata = json.loads(sidecar.read_bytes())
    metadata["pending"]["batch"]["environment"]["binary_sha256"] = "0" * 64
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    snapshot = output.read_bytes(), sidecar.read_bytes()
    assert main(_args(output)) == 1
    assert (output.read_bytes(), sidecar.read_bytes()) == snapshot


def test_resume_core_fingerprint_and_receipt(tmp_path, monkeypatch):
    original = build_cvm_core()
    binary = tmp_path / original.name
    shutil.copyfile(original, binary)
    receipt = binary.with_suffix(".build.json")
    shutil.copyfile(original.with_suffix(".build.json"), receipt)
    monkeypatch.setattr("runner.resolve_core_binary", lambda: binary)
    output = tmp_path / "binary.csv"
    args = _args(output)
    assert main(args) == 0
    sidecar = output.with_suffix(".metadata.json")
    snapshot = output.read_bytes(), sidecar.read_bytes()
    info = json.loads(receipt.read_bytes())
    info["build_flags"] = "different receipt claim"
    receipt.write_text(json.dumps(info), encoding="utf-8")
    assert main(args) == 0
    assert (output.read_bytes(), sidecar.read_bytes()) == snapshot

    # Appended fixture bytes change the executable hash without changing its path.
    with binary.open("ab") as executable:
        executable.write(b"distinct binary identity fixture")
    assert main(args) == 1
    assert (output.read_bytes(), sidecar.read_bytes()) == snapshot
    info["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(info), encoding="utf-8")
    assert main(args) == 0
    assert len(rows(output)) == 2
    batches = json.loads(sidecar.read_bytes())["batches"]
    assert batches[0]["version"][0] != batches[1]["version"][0]


def test_trial_uses_verified_binary_snapshot_even_if_original_is_replaced(tmp_path, monkeypatch):
    original = tmp_path / "core"
    original.write_bytes(b"verified executable")
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    config = ExperimentConfig(8, 1, 1, 0.3, 0.125, 42, 42, workload="all_duplicate")
    recorded = []

    class Writer:
        def write_record(self, config, result):
            recorded.append(result)

    def run(config, stream, binary):
        assert binary.read_bytes() == b"verified executable"
        original.write_bytes(b"replacement between query and execution")
        try:
            assert binary.read_bytes() == b"verified executable"
        finally:
            original.write_bytes(b"verified executable")
        return CVMResult(ExperimentStatus.SUCCESS, estimate=1, effective_s=1201)

    monkeypatch.setattr("runner.run_cvm_a1_core", run)
    result = run_single_trial(config, Writer(), "gcc", "-O3", binary=original, binary_sha256=sha)
    assert recorded == [result]


def test_resume_distinguishes_generator_and_input(tmp_path, monkeypatch):
    core = build_cvm_core()
    root = Path(__file__).resolve().parents[1]
    local = tmp_path / "source"
    generator = local / "src/stream_generator.py"
    generator.parent.mkdir(parents=True)
    shutil.copyfile(root / "src/stream_generator.py", generator)
    shutil.copyfile(root / "runner.py", local / "runner.py")
    monkeypatch.setattr("runner.PROJECT_ROOT", local)
    monkeypatch.setattr("runner.resolve_core_binary", lambda: core)
    output = tmp_path / "inputs.csv"
    args = _args(output)
    assert main(args) == 0
    generator.write_bytes(generator.read_bytes() + b"\n# distinct generator identity fixture\n")
    assert main(args) == 0
    sidecar = output.with_suffix(".metadata.json")
    batches = json.loads(sidecar.read_bytes())["batches"]
    assert batches[0]["version"][1] != batches[1]["version"][1]
    for option in (
        ["--eps", "0.3"],
        ["--delta", "0.125"],
        ["--workload", "uniform"],
        ["--seed-gen", "43"],
        ["--seed-algo", "44"],
        ["--trial", "2"],
    ):
        count = len(rows(output))
        assert main([*args, *option]) == 0
        assert len(rows(output)) == count + 1


def test_concurrent_runner_processes_commit_each_trial_once(tmp_path):
    build_cvm_core()
    output = tmp_path / "concurrent.csv"
    runner = Path(__file__).resolve().parents[1] / "runner.py"
    command = [sys.executable, "-B", str(runner), *_args(output), "--trials", "2"]
    with (
        subprocess.Popen(command, env=os.environ, stderr=subprocess.PIPE, text=True) as first,
        subprocess.Popen(command, env=os.environ, stderr=subprocess.PIPE, text=True) as second,
    ):
        for process in (first, second):
            _, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
    assert [row["trial"] for row in rows(output)] == ["1", "2"]


def test_failed_trial_is_logged_and_retry_preserves_history(tmp_path, monkeypatch, caplog):
    output = tmp_path / "retry.csv"
    with monkeypatch.context() as patch:
        patch.setattr(
            "runner.run_cvm_a1_core",
            lambda *_: CVMResult(
                ExperimentStatus.EXECUTION_ERROR, error_msg="Core exit 1: deliberate fixture"
            ),
        )
        assert main(_args(output)) == 1
    assert "Core exit 1: deliberate fixture" in caplog.text
    assert main(_args(output)) == 0
    assert main(_args(output)) == 0
    failure, success = rows(output)
    assert failure["status"] == "execution_error"
    assert all(failure[key] == "" for key in ("s", "estimate", "signed_rel_error", "abs_rel_error"))
    assert success["status"] == "success"
    assert failure["run_id"] != success["run_id"]


def test_bad_seed_and_invalid_workload_fail_before_creating_raw(tmp_path):
    output = tmp_path / "invalid.csv"
    assert main([*_args(output), "--seed-algo", str(2**64)]) == 1
    assert main([*_args(output), "--f0", "7"]) == 1
    assert not output.exists()
