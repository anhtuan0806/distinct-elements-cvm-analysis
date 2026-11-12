"""OS-specific regression tests for TV3 build and measurement."""

import os
import shutil
import subprocess
import sys

import pytest

from src.cvm import build
from src.cvm.process_memory import peak_memory


def test_build_with_unicode_and_spaces(tmp_path, monkeypatch):
    project = tmp_path / "đường dẫn có dấu"
    shutil.copytree(build.PROJECT_ROOT / "src", project / "src")
    monkeypatch.setattr(build, "PROJECT_ROOT", project)
    core = build.build_cvm_core()
    assert core.is_file()
    identity = build.binary_identity(core)
    assert identity["compiler"] != "unknown" and len(identity["binary_sha256"]) == 64
    result = subprocess.run(
        [str(core), "--m", "1", "--eps", "0.2", "--delta", "0.1", "--seed", "42"],
        input="1\n",
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "1,FALSE,1,0\n"


@pytest.mark.skipif(sys.platform not in {"linux", "win32"}, reason="no supported RSS backend")
def test_large_then_small_process_peak_bytes(tmp_path):
    fixture = tmp_path / "allocate.cpp"
    fixture.write_text(
        """
#include <cstdlib>
#include <vector>
int main(int argc, char** argv) {
    if (argc != 2) return 1;
    std::vector<unsigned char> memory(std::strtoull(argv[1], nullptr, 10));
    volatile auto* touched = memory.data();
    for (std::size_t i = 0; i < memory.size(); i += 4096) touched[i] = 42;
    return touched[0] != 42;
}
""",
        encoding="utf-8",
    )
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("GCC or Clang required for RSS allocation fixture")
    sources = ["allocate.cpp"]
    shutil.copy(build.PROJECT_ROOT / "src/cvm/peak_rss.cpp", tmp_path)
    sources.append("peak_rss.cpp")
    executable = tmp_path / ("allocate.exe" if sys.platform == "win32" else "allocate")
    subprocess.run(
        [compiler, "-std=c++17", *sources, "-o", executable.name],
        cwd=tmp_path,
        check=True,
    )

    def measure(size, enabled=True):
        with subprocess.Popen(
            [str(executable), str(size)],
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "CVM_TV3_PEAK_RSS": "1" if enabled else "0"},
        ) as child:
            _, stderr = child.communicate(timeout=15)
            assert child.returncode == 0
            rss, diagnostics = peak_memory(stderr)
        assert not diagnostics
        return rss

    large = measure(48 * 1024**2)
    parent_memory = bytearray(b"x") * (64 * 1024**2)
    small = measure(1024**2)
    assert parent_memory[-1] == ord("x")
    assert large is not None and large >= 48 * 1024**2
    assert small is not None and 0 < small < large - 32 * 1024**2
    assert measure(1024**2, enabled=False) is None


def test_unavailable_process_measurement_returns_null():
    assert peak_memory("core error\n") == (None, "core error\n")
    assert peak_memory("cvm-tv3-peak-rss-v1:0\n") == (None, "")
    assert peak_memory("cvm-tv3-peak-rss-v1:4096\ncore error\n") == (4096, "core error\n")
