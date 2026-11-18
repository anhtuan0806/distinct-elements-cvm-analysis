"""Build and smoke an isolated copy using the existing TV3 build helper and tests."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = (
    "compiler_version",
    "build_core",
    "build_unit",
    "unit",
    "build_abort_fixture",
    "cli_smoke",
    "runner_fixture_smoke",
    "runner_cli",
    "runner_record",
    "python_regressions",
)
BUILD_CODE = r"""
import json
import subprocess
import sys
from src.cvm import build
original_run = subprocess.run
def logged_run(command, **kwargs):
    entry = {"argv": [str(item) for item in command], "cwd": str(kwargs.get("cwd"))}
    print(json.dumps(entry), flush=True)
    try:
        return original_run(command, **kwargs)
    except subprocess.CalledProcessError as error:
        print(error.stdout or "", file=sys.stderr)
        print(error.stderr or "", file=sys.stderr)
        raise
build.subprocess.run = logged_run
binary = build.build_cvm_core(force=True)
print(json.dumps(build.binary_identity(binary, require_receipt=True)))
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-optional-locks", *args], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def environment() -> dict:
    info = {
        "os": platform.system(),
        "architecture": platform.machine(),
        "kernel": platform.release(),
        "cpu": platform.processor(),
        "cpu_count": os.cpu_count(),
        "python": sys.version,
        "python_executable": sys.executable,
        "virtualization_indicators": [],
    }
    if sys.platform == "linux":
        info["distribution"] = Path("/etc/os-release").read_text(encoding="utf-8")
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8")
        info["cpu"] = next(
            (
                s.split(":", 1)[1].strip()
                for s in cpuinfo.splitlines()
                if s.startswith("model name")
            ),
            info["cpu"],
        )
        if "microsoft" in platform.release().lower() or os.environ.get("WSL_INTEROP"):
            info["virtualization_indicators"].append("WSL")
        for marker in ("/.dockerenv", "/run/.containerenv"):
            if Path(marker).exists():
                info["virtualization_indicators"].append(marker)
        if shutil.which("systemd-detect-virt"):
            result = subprocess.run(["systemd-detect-virt"], capture_output=True, text=True)
            info["systemd_detect_virt"] = {"exit_code": result.returncode, "stdout": result.stdout}
            if result.returncode == 0:
                info["virtualization_indicators"].append(result.stdout.strip())
    return info


def verify(args: argparse.Namespace) -> int:
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_commit):
        raise ValueError("--expected-commit must be a full 40-character commit SHA")
    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    if commit != args.expected_commit:
        raise ValueError(f"Expected {args.expected_commit}, found {commit}")
    if status and (args.environment == "linux-native" or not args.allow_dirty):
        raise ValueError("Clean checkout required; --allow-dirty is only for Windows preparation")
    output = args.output_dir.resolve()
    if output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / "build"):
        raise ValueError("Use a new directory under build/ or outside the repository")
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite an earlier run.
    report = {
        "started_at": now(),
        "checkout": str(ROOT),
        "commit": commit,
        "branch": git("branch", "--show-current"),
        "working_tree": status,
        "environment_kind": args.environment,
        "native_note": args.native_note,
        "native_acceptance": "CHƯA CHẠY"
        if args.environment == "windows-preparation"
        else "REQUIRES_GROUP_REVIEW_OF_MACHINE_AND_LOGS",
        "environment": environment(),
        "status": "FAIL",
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "steps": {name: {"status": "CHƯA CHẠY"} for name in STEPS},
    }

    def run(name: str, command: list[str], cwd: Path) -> None:
        step = {"status": "FAIL", "started_at": now(), "command": command, "cwd": str(cwd)}
        report["steps"][name] = step
        try:
            result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=300)
            (output / f"{name}.stdout.log").write_bytes(result.stdout)
            (output / f"{name}.stderr.log").write_bytes(result.stderr)
            step.update(exit_code=result.returncode, finished_at=now())
            if result.returncode:
                raise RuntimeError(f"{name}: exit {result.returncode}; see {output}")
            step["status"] = "PASS"
            print(f"PASS {name} (exit 0)", flush=True)
        except BaseException:
            step.setdefault("exit_code", None)
            step["finished_at"] = now()
            raise

    try:
        env = report["environment"]
        if args.environment == "linux-native":
            if env["os"] != "Linux" or env["architecture"] not in {"x86_64", "AMD64"}:
                raise ValueError("Linux native x86_64 target required")
            if not args.native_note or env["virtualization_indicators"]:
                raise ValueError(
                    "Describe the installed physical target in --native-note; "
                    "VM/WSL/container is ineligible"
                )
        elif env["os"] != "Windows":
            raise ValueError("windows-preparation must run on Windows")

        # Copy only versioned source/test inputs. The build helper and Runner see
        # their usual paths inside this isolated workspace, leaving old binaries,
        # RAW files and build receipts in the original checkout untouched.
        workspace = output / "workspace"
        workspace.mkdir()
        paths = git("ls-files", "--", "src", "tests", "runner.py", "pyproject.toml").splitlines()
        manifest = {}
        for relative in paths:
            source = ROOT / relative
            destination = workspace / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            manifest[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
        report["source_sha256"] = manifest
        sys.path.insert(0, str(workspace))
        from src.cvm.build import _compiler, binary_identity

        compiler, flags, msvc = _compiler()
        report["compiler_path"] = compiler
        # The current TV3 receipt can contain the heading of cl /? rather than
        # its version. Keep the actual compiler banner as independent evidence.
        run("compiler_version", [compiler] if msvc else [compiler, "--version"], workspace)
        run("build_core", [sys.executable, "-c", BUILD_CODE], workspace)
        core = workspace / "build/a1" / ("cvm_core.exe" if env["os"] == "Windows" else "cvm_core")
        report["binary"] = {"path": str(core), **binary_identity(core, require_receipt=True)}
        binaries = output / "binaries"
        binaries.mkdir()
        ext = ".exe" if env["os"] == "Windows" else ""

        def compile_test(name: str, source: str, executable: str) -> Path:
            target = binaries / (executable + ext)
            options = (
                ["/W4", "/WX", "/permissive-", "/utf-8"]
                if msvc
                else [
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pedantic",
                ]
            )
            targets = [f"/Fe:{target}", f"/Fo:{binaries}{os.sep}"] if msvc else ["-o", str(target)]
            run(name, [compiler, *flags, *options, "src/cvm/a1.cpp", source, *targets], workspace)
            return target

        unit = compile_test("build_unit", "tests/cpp/test_a1.cpp", "test_a1")
        run("unit", [str(unit)], workspace)
        fixture = compile_test(
            "build_abort_fixture", "tests/cpp/cvm_abort_fixture.cpp", "cvm_abort_fixture"
        )
        run(
            "cli_smoke",
            [
                sys.executable,
                "-m",
                "tests.cpp.check_cvm_core",
                str(core),
                "--log",
                str(output / "cli-smoke.json"),
            ],
            workspace,
        )
        run(
            "runner_fixture_smoke",
            [sys.executable, "-m", "tests.cpp.check_tv1_runner", str(core), str(fixture)],
            workspace,
        )
        raw = output / "real/runner-smoke.csv"
        run(
            "runner_cli",
            [
                sys.executable,
                "runner.py",
                "--m",
                "4096",
                "--n",
                "4096",
                "--f0",
                "4096",
                "--workload",
                "all_distinct",
                "--eps",
                "0.9",
                "--delta",
                "0.9",
                "--seed",
                "42",
                "--out",
                str(raw),
            ],
            workspace,
        )
        report["steps"]["runner_record"] = {"status": "FAIL"}
        with raw.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            if len(reader.fieldnames or []) != 24 or len(rows) != 1:
                raise ValueError("Runner smoke must produce exactly one 24-field record")
        row = rows[0]
        if row["status"] != "success" or int(row["halving_count"]) < 1:
            raise ValueError("Runner smoke did not execute a successful halving workload")
        if row["peak_sample_size"] != row["s"]:
            raise ValueError("Runner peak sample size must reach the reported threshold")
        report["steps"]["runner_record"] = {"status": "PASS", "record": row}
        if args.python_regressions:
            run(
                "python_regressions",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/test_core_threshold.py",
                    "tests/test_cvm_core_adapter.py",
                    "tests/test_e2e_pipeline.py",
                    "--basetemp",
                    str(output / "pytest-tmp"),
                ],
                workspace,
            )
        else:
            report["steps"]["python_regressions"] = {
                "status": "SKIP",
                "reason": "optional; add --python-regressions",
            }
        if git("status", "--porcelain=v1", "--untracked-files=all") != status:
            raise RuntimeError("Source checkout changed during verification")
        report["status"] = "PASS"
        return 0
    except Exception as error:
        report["error"] = str(error)
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    finally:
        report["finished_at"] = now()
        (output / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Report: {output / 'report.json'}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--environment", required=True, choices=["windows-preparation", "linux-native"]
    )
    parser.add_argument(
        "--native-note", help="Operator's description of the installed physical Linux target"
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Windows preparation only; all source hashes are logged",
    )
    parser.add_argument("--python-regressions", action="store_true")
    args = parser.parse_args()
    try:
        return verify(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
