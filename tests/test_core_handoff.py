"""Failure and preservation checks for the handoff driver, without compiling a Core."""

import argparse
import json
import subprocess
import sys

import pytest

from scripts import verify_core_checkout as handoff
from src.cvm import build

SHA = "a" * 40


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(handoff, "ROOT", root)
    monkeypatch.setattr(sys, "path", sys.path.copy())

    def git(*args):
        if args[:2] == ("rev-parse", "HEAD"):
            return SHA
        if args[:2] == ("branch", "--show-current"):
            return "feat/linux-core-smoke"
        return ""

    monkeypatch.setattr(handoff, "git", git)
    return argparse.Namespace(
        expected_commit=SHA,
        output_dir=root / "build/run",
        environment="windows-preparation",
        allow_dirty=False,
        native_note=None,
        python_regressions=False,
    )


def test_rejects_different_commit_before_creating_output(checkout):
    checkout.expected_commit = "b" * 40
    with pytest.raises(ValueError, match="Expected"):
        handoff.verify(checkout)
    assert not checkout.output_dir.exists()


def test_does_not_overwrite_existing_evidence(checkout):
    checkout.output_dir.mkdir(parents=True)
    marker = checkout.output_dir / "report.json"
    marker.write_text("old evidence", encoding="utf-8")
    with pytest.raises(FileExistsError):
        handoff.verify(checkout)
    assert marker.read_text(encoding="utf-8") == "old evidence"


def test_rejects_output_in_results(checkout):
    checkout.output_dir = handoff.ROOT / "results/real/new-run"
    with pytest.raises(ValueError, match="under build/"):
        handoff.verify(checkout)
    assert not checkout.output_dir.exists()


def test_build_failure_is_nonzero_and_later_steps_are_not_pass(checkout, monkeypatch):
    monkeypatch.setattr(
        handoff, "environment", lambda: {"os": "Windows", "virtualization_indicators": []}
    )
    monkeypatch.setattr(build, "_compiler", lambda: ("fixture-compiler", (), True))

    def failing_build(command, **kwargs):
        code = 17 if "-c" in command else 0
        return subprocess.CompletedProcess(command, code, b"fixture stdout", b"fixture stderr")

    monkeypatch.setattr(handoff.subprocess, "run", failing_build)
    assert handoff.verify(checkout) == 1
    report = json.loads((checkout.output_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert report["native_acceptance"] == "CHƯA CHẠY"
    assert report["steps"]["build_core"]["exit_code"] == 17
    assert report["steps"]["unit"]["status"] == "CHƯA CHẠY"
    assert (checkout.output_dir / "build_core.stderr.log").read_bytes() == b"fixture stderr"
