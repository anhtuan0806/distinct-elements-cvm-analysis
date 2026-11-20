"""Run real SCALE batches for Jupyter under an Ubuntu process supervisor."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil
except ModuleNotFoundError:
    psutil = None

import runner
from scripts.generate_timespace_plan import (
    SCALE_LENGTHS,
    PlanRow,
    generate_plan,
    runner_args,
    validate_scale_rows,
)
from scripts.validate_results import validate
from src.benchmark_report import BenchmarkReport
from src.cli import args_to_config, parse_args
from src.cvm.build import PROJECT_ROOT, binary_identity
from src.cvm.executor import resolve_core_binary

FULL_MODE = "RUN_LIVE_SCALE"
QUICK_MODE = "QUICK_LIVE"
LIVE_MODES = (FULL_MODE, QUICK_MODE)
MIB = 2**20
GIB = 2**30
MEMORY_RESERVE = 4 * GIB
SWAP_GROWTH_LIMIT = 512 * MIB
RAW_NAME = "scale-live.csv"
EVENTS_NAME = "events.jsonl"
STATUS_NAME = "run-provenance.json"
COMPETING_PROGRAMS = {
    "runner.py",
    "cvm_core",
    "cvm_core.exe",
    "run_scale.py",
    "run_optimized.py",
    "run_full_scale.py",
}


def live_plan(mode: str) -> list[PlanRow]:
    """Select the published SCALE plan or a prefix of two trials at two sizes."""
    if mode not in LIVE_MODES:
        raise ValueError(f"Chế độ LIVE không hợp lệ: {mode}")
    rows = list(generate_plan(scale=True))
    if mode == QUICK_MODE:
        return [replace(row, trials=2) for row in rows if row.m in SCALE_LENGTHS[:2]]
    return rows


def require_native_ubuntu() -> list[str]:
    if platform.system() != "Linux" or platform.freedesktop_os_release().get("ID") != "ubuntu":
        raise RuntimeError("Benchmark LIVE yêu cầu Ubuntu native.")
    if (
        any(os.environ.get(name) for name in ("WSL_DISTRO_NAME", "WSL_INTEROP"))
        or "microsoft" in platform.version().lower()
        or "microsoft" in platform.release().lower()
    ):
        raise RuntimeError("Phát hiện WSL. Benchmark yêu cầu Ubuntu native.")
    release = platform.freedesktop_os_release()
    evidence = [f"Ubuntu: {release['PRETTY_NAME']}", f"Kernel: {platform.release()}"]
    for option in ("--vm", "--container"):
        check = subprocess.run(
            ["systemd-detect-virt", option], capture_output=True, text=True, timeout=5
        )
        detected = check.stdout.strip()
        if check.returncode != 1 or detected != "none":
            raise RuntimeError(f"Không xác nhận được Ubuntu native: {option} {detected!r}.")
        evidence.append(f"{option}: {detected}")
    return evidence


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(path: Path, event: str, **fields) -> None:
    entry = {
        "event": event,
        "time": _now(),
        "monotonic": time.monotonic(),
        "emitter_pid": os.getpid(),
        **fields,
    }
    # Each short JSON line uses one append write, including writes by the Runner.
    with path.open("ab", buffering=0) as stream:
        line = (json.dumps(entry, ensure_ascii=False) + "\n").encode()
        if stream.write(line) != len(line):
            raise OSError(f"Không thể ghi đầy đủ một sự kiện LIVE: {path}")


def _save_status(directory: Path, state: dict) -> None:
    stage = directory / f".status-{os.getpid()}.tmp"
    with stage.open("w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    stage.replace(directory / STATUS_NAME)


@contextmanager
def _host_lock():
    import fcntl

    path = Path("/tmp") / f"cvm-a1-live-{os.getuid()}.lock"
    with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), "r+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Một lượt LIVE CVM-A1 khác đang chạy trên máy này.") from exc
        yield


def _check_other_benchmarks() -> None:
    own = {os.getpid(), *(proc.pid for proc in psutil.Process().parents())}
    running = []
    for proc in psutil.process_iter(("name", "cmdline", "status"), ad_value=None):
        if proc.pid in own or proc.info["status"] == psutil.STATUS_ZOMBIE:
            continue
        args = proc.info["cmdline"] or []
        if (
            proc.info["name"] in COMPETING_PROGRAMS
            or any(Path(arg).name in COMPETING_PROGRAMS for arg in args[:3])
            or ("scripts.generate_timespace_plan" in args and "--run" in args)
        ):
            running.append(proc.pid)
    if running:
        raise RuntimeError(f"Phát hiện benchmark CVM-A1 khác đang chạy, PID {running}.")


def _forecast(row: PlanRow, previous: dict | None) -> tuple[int, int]:
    compact = {"all_duplicate": 0, "all_distinct": 8 * row.m, "uniform": 72 * row.f0 + 6 * row.m}
    analytic = 128 * MIB + compact[row.workload]
    empirical = 0
    seconds = 0
    if previous is not None:
        ratio = row.m / previous["m"]
        if previous["m"] >= 1_000_000:
            empirical = previous["peak_pipeline_bytes"] * ratio * 1.5
        seconds = ratio * previous["elapsed_seconds"]
    return int(max(analytic, empirical)), max(120, int(3 * seconds + 60))


def _rss_tree(pid: int) -> int:
    try:
        parent = psutil.Process(pid)
        processes = [parent, *parent.children(recursive=True)]
    except psutil.NoSuchProcess:
        return 0
    rss = 0
    for proc in processes:
        try:
            rss += proc.memory_info().rss
        except psutil.NoSuchProcess:
            pass
    return rss


def _stop_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # The wrapper can exit before one of its descendants has stopped.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _time_peak(path: Path) -> int:
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "Maximum resident set size (kbytes):" in line:
                return int(line.rsplit(":", 1)[1]) * 1024
    return 0


def _run_batch(
    row: PlanRow, directory: Path, previous: dict | None, check_kernel: Callable[[], None]
) -> dict:
    check_kernel()
    _check_other_benchmarks()
    forecast, timeout = _forecast(row, previous)
    available = psutil.virtual_memory().available
    swap_start = psutil.swap_memory().used
    if available - MEMORY_RESERVE < forecast or shutil.disk_usage(directory).free < GIB:
        raise RuntimeError(
            f"Không đủ RAM hoặc đĩa tại m={row.m}, {row.workload}. "
            f"RAM khả dụng {available / GIB:.2f} GiB, dự báo peak {forecast / GIB:.2f} GiB."
        )
    address_limit = int(min(available - MEMORY_RESERVE, max(2 * GIB, 1.8 * forecast + 512 * MIB)))
    events = directory / EVENTS_NAME
    stem = f"{row.m}-{row.workload}"
    time_log = directory / "logs" / f"{stem}.time"
    batch_log = directory / "logs" / f"{stem}.log"
    raw = directory / RAW_NAME
    command = [
        "/usr/bin/time",
        "-v",
        "-o",
        str(time_log),
        "prlimit",
        f"--as={address_limit}",
        "--",
        sys.executable,
        "-m",
        "scripts.live_scale",
        "worker",
        str(events),
        *runner_args(row, raw),
    ]
    start = time.monotonic()
    peak = 0
    min_available = available
    max_swap_growth = 0
    context = {"m": row.m, "workload": row.workload}
    _emit(
        events,
        "batch_started",
        **context,
        trials=row.trials,
        available_bytes=available,
        forecast_bytes=forecast,
        address_space_limit_bytes=address_limit,
        timeout_seconds=timeout,
    )
    with batch_log.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(command, ensure_ascii=False) + "\n")
        stream.flush()
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            env={**os.environ, "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        try:
            _emit(events, "batch_process_started", **context, monitor_pid=process.pid)
            while process.poll() is None:
                check_kernel()
                elapsed = time.monotonic() - start
                rss = _rss_tree(process.pid)
                available = psutil.virtual_memory().available
                swap_growth = max(0, psutil.swap_memory().used - swap_start)
                peak = max(peak, rss)
                min_available = min(min_available, available)
                max_swap_growth = max(max_swap_growth, swap_growth)
                _emit(
                    events,
                    "resource_sample",
                    **context,
                    pipeline_rss_bytes=rss,
                    available_bytes=available,
                    swap_growth_bytes=swap_growth,
                )
                if available < MEMORY_RESERVE or swap_growth > SWAP_GROWTH_LIMIT:
                    raise RuntimeError(f"Đã chạm giới hạn RAM/swap tại m={row.m}, {row.workload}.")
                if elapsed > timeout:
                    raise TimeoutError(
                        f"Quá deadline batch ở m={row.m}, {row.workload}: {timeout} s."
                    )
                time.sleep(0.25 if row.m < 2_000_000 else 0.5)
            if process.returncode != 0:
                raise RuntimeError(
                    f"Runner exit {process.returncode} ở m={row.m}, {row.workload}. "
                    f"Xem {batch_log}."
                )
        finally:
            if process.returncode != 0:
                _stop_group(process)
            outcome = {
                **context,
                "peak_pipeline_bytes": max(peak, _time_peak(time_log)),
                "min_available_bytes": min_available,
                "max_swap_growth_bytes": max_swap_growth,
                "elapsed_seconds": time.monotonic() - start,
                "returncode": process.returncode,
            }
            _emit(events, "batch_finished", **outcome)
    return outcome


def _recover_pending(raw: Path) -> None:
    sidecar = raw.with_suffix(".metadata.json")
    if raw.is_file() and sidecar.is_file():
        pending = json.loads(sidecar.read_text(encoding="utf-8")).get("pending")
        if pending:
            with BenchmarkReport.open(raw, "real", pending["batch"]):
                pass


def _checkpoint(raw: Path, expected: dict, fingerprint: dict) -> dict:
    if not raw.is_file():
        return {"successful_trials": 0, "recorded_trials": 0, "raw_verified": False}
    report = validate(raw)
    validate_scale_rows(report.rows)
    if not report.verified and report.rows:
        raise ValueError("RAW LIVE không hợp lệ: " + "; ".join(report.errors))
    seen = set()
    for row in report.rows:
        key = row["m"], row["workload"], row["trial"]
        spec = expected.get(key)
        if key in seen or spec is None:
            raise ValueError(f"Trial ngoài kế hoạch LIVE hoặc bị trùng: {key}.")
        seen.add(key)
        if (
            row["binary_sha256"] != fingerprint["environment"]["binary_sha256"]
            or row["source_tree_sha256"] != fingerprint["source_tree_sha256"]
            or row["generator_sha256"] != fingerprint["generator_sha256"]
            or row["git_commit"] != fingerprint["git_commit"]
            or row["python"] != fingerprint["environment"]["python"]
            or row["platform_os"] != fingerprint["environment"]["os"]
            or row["cpu"] != fingerprint["environment"]["cpu"]
            or row["compiler"] != fingerprint["environment"]["compiler"]
            or row["build_flags"] != fingerprint["environment"]["build_flags"]
        ):
            raise ValueError("Provenance thay đổi giữa các trial LIVE.")
        if row["status"] == "success" and (
            row["s"] != spec.s_reference or row["process_peak_memory_bytes"] is None
        ):
            raise ValueError(f"Trial LIVE thiếu Peak RSS hoặc sai ngưỡng s: {key}.")
    statuses = Counter(row["status"] for row in report.rows)
    return {
        "successful_trials": statuses["success"],
        "recorded_trials": len(report.rows),
        "raw_verified": report.verified,
        "statuses": dict(statuses),
        "raw_sha256": report.metadata.get("sha256") if report.verified else None,
        "sidecar_sha256": report.metadata_sha256 if report.verified else None,
    }


class KernelStopped(RuntimeError):
    """Stop the benchmark when the notebook no longer owns the run."""


def supervise(directory: Path, mode: str, kernel_pid: int) -> int:
    raw = directory / RAW_NAME
    events = directory / EVENTS_NAME
    sidecar = raw.with_suffix(".metadata.json")
    if any(path.exists() for path in (raw, sidecar, events, directory / STATUS_NAME)):
        raise FileExistsError("Một lượt LIVE cần thư mục mới và RAW chưa tồn tại.")
    events.touch(exist_ok=False)
    stop_signal = None

    def request_stop(signum, _frame):
        nonlocal stop_signal
        stop_signal = signum

    def check_kernel():
        if stop_signal is not None:
            raise KernelStopped(f"Notebook yêu cầu dừng (signal {stop_signal}).")
        if os.getppid() != kernel_pid:
            raise KernelStopped(f"Kernel PID {kernel_pid} đã kết thúc.")

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, request_stop)
    rows = live_plan(mode)
    expected = {
        (row.m, row.workload, row.first_trial + i): row for row in rows for i in range(row.trials)
    }
    state = {
        "mode": mode,
        "live_run_id": directory.name,
        "started_at": _now(),
        "kernel_pid": kernel_pid,
        "supervisor_pid": os.getpid(),
        "status": "running",
        "planned_trials": len(expected),
        "requested_plan": [asdict(row) for row in rows],
        "raw": RAW_NAME,
        "sidecar": sidecar.name,
        "events": EVENTS_NAME,
        "successful_trials": 0,
        "recorded_trials": 0,
        "raw_verified": False,
    }
    _save_status(directory, state)
    _emit(events, "run_started", mode=mode, total_trials=len(expected), kernel_pid=kernel_pid)
    directory.joinpath("logs").mkdir()
    fingerprint = None
    observed = {}
    try:
        state["native_linux_check"] = require_native_ubuntu()
        if psutil is None:
            raise RuntimeError("Thiếu psutil. Cài các dependency trong requirements-jupyter.txt.")
        with _host_lock():
            check_kernel()
            _check_other_benchmarks()
            binary = resolve_core_binary()
            core = binary_identity(binary, require_receipt=True)
            if not core["peak_rss_hook"]:
                raise RuntimeError("Binary Core thiếu hook Peak RSS.")
            configuration = args_to_config(parse_args(runner_args(rows[0], raw)))
            fingerprint = runner._batch(configuration, rows[0].trials, "real", core)
            state["pipeline"] = {
                name: fingerprint[name]
                for name in ("git_commit", "source_tree_sha256", "generator_sha256", "environment")
            }
            state["resource_limits"] = {
                "reserve_bytes": MEMORY_RESERVE,
                "max_swap_growth_bytes": SWAP_GROWTH_LIMIT,
                "initial_available_bytes": psutil.virtual_memory().available,
                "initial_disk_free_bytes": shutil.disk_usage(directory).free,
                "cpu": platform.processor() or platform.machine(),
            }
            _save_status(directory, state)
            for row in rows:
                observed[row.workload] = _run_batch(
                    row, directory, observed.get(row.workload), check_kernel
                )
                state.update(_checkpoint(raw, expected, fingerprint))
                _save_status(directory, state)
            if state["successful_trials"] != len(expected):
                raise RuntimeError("Một số trial LIVE không hoàn tất thành công. Xem RAW và log.")
            state["status"] = "complete"
    except KernelStopped as exc:
        state.update(status="interrupted", reason=str(exc))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        state.update(status="failed", reason=str(exc))
    finally:
        if fingerprint is not None:
            try:
                _recover_pending(raw)
                state.update(_checkpoint(raw, expected, fingerprint))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                state.update(status="failed", raw_verified=False, validation_error=str(exc))
        state["finished_at"] = _now()
        _save_status(directory, state)
        _emit(
            events,
            "run_finished",
            status=state["status"],
            reason=state.get("reason"),
            successful_trials=state["successful_trials"],
            recorded_trials=state["recorded_trials"],
        )
    return 0 if state["status"] == "complete" else 1


def run_live_scale(directory: Path, mode: str, on_event: Callable[[dict], None]) -> dict:
    """From Jupyter, launch a fresh supervisor and relay its durable events."""
    directory = directory.resolve()
    events = directory / EVENTS_NAME
    position = 0
    interrupted = False

    def drain_events():
        nonlocal position
        if not events.is_file():
            return
        with events.open("rb") as stream:
            stream.seek(position)
            for line in stream:
                if not line.endswith(b"\n"):
                    break
                position += len(line)
                on_event(json.loads(line))

    with (directory / "supervisor.log").open("x", encoding="utf-8") as stream:
        worker = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "scripts.live_scale",
                "supervise",
                str(directory),
                mode,
                str(os.getpid()),
            ],
            cwd=PROJECT_ROOT,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        try:
            while worker.poll() is None:
                drain_events()
                time.sleep(0.2)
        except KeyboardInterrupt:
            # Interrupt the supervisor; it stops the Runner process group and saves state.
            interrupted = True
            worker.terminate()
            worker.wait(timeout=15)
        finally:
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=15)
        drain_events()
    status_path = directory / STATUS_NAME
    if not status_path.is_file():
        if interrupted:
            state = {
                "status": "interrupted",
                "reason": "Đã dừng trước khi supervisor khởi tạo.",
                "live_run_id": directory.name,
                "mode": mode,
                "finished_at": _now(),
                "planned_trials": sum(row.trials for row in live_plan(mode)),
                "successful_trials": 0,
                "recorded_trials": 0,
                "raw_verified": False,
            }
            _save_status(directory, state)
            return state
        raise RuntimeError(
            f"Supervisor LIVE không ghi kết quả. Xem {directory / 'supervisor.log'}."
        )
    state = json.loads(status_path.read_text(encoding="utf-8"))
    if state["status"] == "running":
        raise RuntimeError(f"Supervisor LIVE kết thúc bất thường. Xem {status_path} và log.")
    return state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    supervisor = commands.add_parser("supervise")
    supervisor.add_argument("directory", type=Path)
    supervisor.add_argument("mode", choices=LIVE_MODES)
    supervisor.add_argument("kernel_pid", type=int)
    worker = commands.add_parser("worker")
    worker.add_argument("events", type=Path)
    worker.add_argument("runner_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "supervise":
        return supervise(args.directory, args.mode, args.kernel_pid)

    def on_event(event, **fields):
        _emit(args.events, event, **fields)

    _emit(args.events, "runner_started")
    try:
        result = runner.main(args.runner_args, on_event=on_event)
    except BaseException:
        _emit(args.events, "runner_failed")
        raise
    _emit(args.events, "runner_finished", returncode=result)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
