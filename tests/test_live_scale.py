"""Regression checks for the live notebook's plan and stopping behavior."""

import json
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from scripts import live_scale
from scripts.generate_timespace_plan import SCALE_LENGTHS, generate_plan
from src.cvm.executor import _run_core


def test_live_profiles_preserve_the_published_scale_schedule():
    plan = list(generate_plan(scale=True))
    assert live_scale.live_plan(live_scale.FULL_MODE) == plan
    assert sum(row.trials for row in plan) == 270
    quick = live_scale.live_plan(live_scale.QUICK_MODE)
    assert quick == [replace(row, trials=2) for row in plan if row.m in SCALE_LENGTHS[:2]]
    assert sum(row.trials for row in quick) == 12


def test_core_observer_reports_actual_process_and_exit():
    events = []
    result = _run_core(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        (),
        timeout=10,
        on_process=lambda event, **fields: events.append((event, fields)),
    )
    pid = int(result.stdout)
    assert events == [
        ("core_started", {"pid": pid, "executable": sys.executable}),
        ("core_finished", {"pid": pid, "returncode": 0}),
    ]


def test_live_preflight_failure_records_zero_and_does_not_create_raw(tmp_path, monkeypatch):
    def fail():
        raise RuntimeError("fixture: native check failed")

    monkeypatch.setattr(live_scale, "require_native_ubuntu", fail)
    monkeypatch.setattr(live_scale.signal, "signal", lambda *_: None)
    assert live_scale.supervise(tmp_path, live_scale.QUICK_MODE, 1234) == 1
    state = json.loads((tmp_path / live_scale.STATUS_NAME).read_text())
    assert (state["status"], state["successful_trials"], state["planned_trials"]) == (
        "failed",
        0,
        12,
    )
    assert state["reason"] == "fixture: native check failed"
    assert not (tmp_path / live_scale.RAW_NAME).exists()


def test_supervisor_rejects_existing_raw_before_work(tmp_path):
    raw = tmp_path / live_scale.RAW_NAME
    raw.write_text("retained", encoding="utf-8")
    with pytest.raises(FileExistsError):
        live_scale.supervise(tmp_path, live_scale.FULL_MODE, 1234)
    assert raw.read_text(encoding="utf-8") == "retained"


def test_live_memory_gate_rejects_batch_before_popen(tmp_path, monkeypatch):
    monkeypatch.setattr(live_scale, "_check_other_benchmarks", lambda: None)
    monkeypatch.setattr(
        live_scale,
        "psutil",
        SimpleNamespace(
            virtual_memory=lambda: SimpleNamespace(available=live_scale.MEMORY_RESERVE),
            swap_memory=lambda: SimpleNamespace(used=0),
        ),
    )
    row = live_scale.live_plan(live_scale.QUICK_MODE)[0]
    with pytest.raises(RuntimeError, match="Không đủ RAM"):
        live_scale._run_batch(row, tmp_path, None, lambda: None)
    assert not list(tmp_path.iterdir())
