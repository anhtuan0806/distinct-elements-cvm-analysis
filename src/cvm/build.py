"""Automated cross-platform compilation utility for cvm_core executable."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("cvm_build")


def get_project_root() -> Path:
    """Get root directory of the repository."""
    return Path(__file__).resolve().parent.parent.parent


def get_cvm_core_path() -> Path:
    """Return the standard path to cvm_core executable."""
    root = get_project_root()
    binary_name = "cvm_core.exe" if os.name == "nt" else "cvm_core"
    candidates = [
        root / "build" / "a1" / binary_name,
        root / "build" / binary_name,
        root / "bin" / binary_name,
    ]
    for p in candidates:
        if p.exists() and os.access(p, os.X_OK if os.name != "nt" else os.R_OK):
            return p
    return root / "build" / "a1" / binary_name


def should_recompile(executable: Path, source_files: list[Path]) -> bool:
    """Check if executable is missing or any source file has newer mtime."""
    if not executable.exists():
        return True
    exe_mtime = executable.stat().st_mtime
    return any(src.stat().st_mtime > exe_mtime for src in source_files)


def build_cvm_core(force: bool = False) -> Path:
    """Compile cvm_core from C++ sources using available compiler."""
    root = get_project_root()
    out_binary = get_cvm_core_path()
    out_binary.parent.mkdir(parents=True, exist_ok=True)

    src_files = [
        root / "src" / "cvm" / "a1.hpp",
        root / "src" / "cvm" / "a1.cpp",
        root / "src" / "cvm_core.cpp",
    ]
    for src in src_files:
        if not src.exists():
            raise FileNotFoundError(f"Source file not found: {src}")

    if not force and not should_recompile(out_binary, src_files):
        return out_binary

    logger.info("Compiling cvm_core to %s...", out_binary)

    # Detect compiler
    cxx = os.environ.get("CXX")
    if not cxx:
        if shutil.which("g++"):
            cxx = "g++"
        elif shutil.which("clang++"):
            cxx = "clang++"
        elif os.name == "nt" and shutil.which("cl"):
            cxx = "cl"
        else:
            raise RuntimeError(
                "No C++ compiler found (g++, clang++, or cl). Please install a C++ compiler."
            )

    if cxx == "cl" or (os.name == "nt" and "cl" in cxx.lower()):
        # MSVC compilation
        cmd = [
            cxx,
            "/nologo",
            "/std:c++17",
            "/EHsc",
            "/W4",
            "/O2",
            "/permissive-",
            "/utf-8",
            f"/I{root / 'src'}",
            str(src_files[1]),  # a1.cpp
            str(src_files[2]),  # cvm_core.cpp
            f"/Fo:{out_binary.parent}\\",
            f"/Fe:{out_binary}",
        ]
    else:
        # GCC / Clang compilation
        cmd = [
            cxx,
            "-O3",
            "-std=c++17",
            f"-I{root / 'src'}",
            str(src_files[1]),  # a1.cpp
            str(src_files[2]),  # cvm_core.cpp
            "-o",
            str(out_binary),
        ]

    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to compile cvm_core:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    if not out_binary.exists():
        raise RuntimeError(f"Compilation reported success but binary not found at {out_binary}")

    logger.info("Successfully compiled %s", out_binary)
    return out_binary

