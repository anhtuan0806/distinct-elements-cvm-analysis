"""Build utility for compiling the CVM-A1 C++ executable across platforms."""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_cvm_core_path() -> Path:
    """Return the platform-specific path to the compiled cvm_core executable."""
    ext = ".exe" if platform.system() == "Windows" else ""
    return PROJECT_ROOT / "build" / "a1" / f"cvm_core{ext}"


def detect_compiler_info() -> tuple[str, str]:
    """Detect the available C++ compiler and return (compiler_version_string, build_flags)."""
    flags = "-O3;-std=c++17"

    for compiler in ("g++", "clang++"):
        comp_path = shutil.which(compiler)
        if comp_path:
            try:
                out = subprocess.run(
                    [comp_path, "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                first_line = out.stdout.splitlines()[0].strip()
                return first_line, flags
            except (subprocess.SubprocessError, OSError):
                return compiler, flags

    if platform.system() == "Windows":
        cl_path = shutil.which("cl") or shutil.which("cl.exe")
        if cl_path:
            return "MSVC", "/O2;/std:c++17"

    return "unknown", "none"


def build_cvm_core(force: bool = False) -> Path:
    """Compile cvm_core from C++ sources if binary is missing or force=True.

    Returns:
        Path to the compiled executable.
    """
    out_binary = get_cvm_core_path()
    if out_binary.exists() and not force:
        return out_binary

    out_binary.parent.mkdir(parents=True, exist_ok=True)

    src_core = PROJECT_ROOT / "src" / "cvm_core.cpp"
    src_a1 = PROJECT_ROOT / "src" / "cvm" / "a1.cpp"

    for compiler in ("g++", "clang++"):
        comp_path = shutil.which(compiler)
        if comp_path:
            cmd = [
                comp_path,
                "-std=c++17",
                "-O3",
                "-Isrc",
                str(src_a1),
                str(src_core),
                "-o",
                str(out_binary),
            ]
            subprocess.run(cmd, check=True, cwd=PROJECT_ROOT, capture_output=True, text=True)
            return out_binary

    if platform.system() == "Windows":
        cl_path = shutil.which("cl") or shutil.which("cl.exe")
        if cl_path:
            cmd = [
                cl_path,
                "/std:c++17",
                "/O2",
                "/EHsc",
                "/Isrc",
                str(src_a1),
                str(src_core),
                f"/Fe:{out_binary}",
            ]
            subprocess.run(cmd, check=True, cwd=PROJECT_ROOT, capture_output=True, text=True)
            return out_binary

    raise RuntimeError(
        "No suitable C++ compiler (g++, clang++, cl.exe) found in PATH to build cvm_core."
    )
