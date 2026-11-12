"""Build the C++ core without passing non-ASCII source paths to MinGW."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_cvm_core_path() -> Path:
    ext = ".exe" if platform.system() == "Windows" else ""
    return PROJECT_ROOT / "build" / "a1" / f"cvm_core{ext}"


def _compiler() -> tuple[str, tuple[str, ...], bool]:
    for name in ("g++", "clang++"):
        if path := shutil.which(name):
            return path, ("-O3", "-std=c++17", "-Isrc"), False
    if platform.system() == "Windows" and (path := shutil.which("cl.exe")):
        return path, ("/O2", "/std:c++17", "/EHsc", "/Isrc"), True
    raise RuntimeError("No C++17 compiler (g++, clang++, cl.exe) found in PATH")


def _version(exe: str, msvc: bool) -> str:
    try:
        result = subprocess.run(
            [exe, "/?" if msvc else "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=PROJECT_ROOT,
        )
        output = (result.stdout or result.stderr).splitlines()
        return next((line.strip() for line in output if line.strip()), Path(exe).name)
    except OSError:
        return Path(exe).name


def detect_compiler_info() -> tuple[str, str]:
    try:
        exe, flags, msvc = _compiler()
    except RuntimeError:
        return "unknown", "unknown"
    return _version(exe, msvc), ";".join(flags)


def binary_identity(binary: Path) -> dict[str, str | bool]:
    """Read build information only when the receipt identifies these exact bytes."""
    sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    try:
        receipt = json.loads(binary.with_suffix(".build.json").read_text(encoding="utf-8"))
        if receipt["binary_sha256"] == sha:
            return receipt
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"binary_sha256": sha, "compiler": "unknown", "build_flags": "unknown"}


def build_cvm_core(force: bool = False) -> Path:
    out = get_cvm_core_path()
    if out.is_file() and not force:
        return out

    exe, flags, msvc = _compiler()
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="compile-", dir=out.parent) as folder:
        scratch = Path(folder)
        binary = scratch / out.name
        relative = binary.relative_to(PROJECT_ROOT)
        sources = ["src/cvm/a1.cpp", "src/cvm_core.cpp"]
        if platform.system() in {"Windows", "Linux"}:
            sources.append("src/cvm/peak_rss.cpp")
        if msvc:
            targets = [f"/Fe:{relative}", f"/Fo:{relative.parent}{os.sep}"]
        else:
            targets = ["-o", str(relative)]
        subprocess.run(
            [exe, *flags, *sources, *targets],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        receipt = scratch / "build.json"
        receipt.write_text(
            json.dumps(
                {
                    "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                    "compiler": _version(exe, msvc),
                    "build_flags": ";".join(flags),
                    "peak_rss_hook": platform.system() in {"Windows", "Linux"},
                }
            ),
            encoding="utf-8",
        )
        os.replace(binary, out)
        os.replace(receipt, out.with_suffix(".build.json"))
    return out
