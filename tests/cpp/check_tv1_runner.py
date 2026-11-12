"""Check the real Runner and RAW writer against production and fixture C++ binaries."""

import argparse
import csv
import io
import math
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runner import main as run_benchmark


def run_and_read(binary: Path, output: Path, m: int, epsilon: str, delta: str) -> dict[str, str]:
    args = [
        "--m",
        str(m),
        "--n",
        str(m),
        "--f0",
        str(m),
        "--workload",
        "all_distinct",
        "--eps",
        epsilon,
        "--delta",
        delta,
        "--seed",
        "42",
        "--out",
        str(output),
    ]
    with patch("src.cvm.executor.get_cvm_core_path", return_value=binary):
        assert run_benchmark(args) == 0
    with output.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        assert reader.fieldnames is not None and len(reader.fieldnames) == 24
        (row,) = list(reader)
    assert row["m"] == row["n"] == row["F0"] == str(m), row
    assert row["seed_generator"] == row["seed_algorithm"] == "42", row
    runtime = float(row["algorithm_runtime_ms"])
    assert math.isfinite(runtime) and runtime >= 0, row
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("core", type=Path)
    parser.add_argument("abort_fixture", type=Path)
    args = parser.parse_args()
    core = args.core.resolve(strict=True)
    fixture = args.abort_fixture.resolve(strict=True)
    process = subprocess.run(
        [
            str(fixture),
            "--m",
            "256",
            "--eps",
            "0.9",
            "--delta",
            "0.9",
            "--seed",
            "42",
            "--output-format",
            "csv-v2",
        ],
        input="".join(f"{item}\n" for item in range(256)),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 0 and process.stderr == "", process
    (csv_row,) = list(csv.reader(io.StringIO(process.stdout)))
    status, estimate, runtime, peak, halvings, threshold = csv_row
    assert (status, estimate, peak, halvings, threshold) == (
        "algorithm_abort",
        "",
        "166",
        "1",
        "166",
    )
    assert math.isfinite(float(runtime)) and float(runtime) >= 0, csv_row

    with TemporaryDirectory() as tmp:
        folder = Path(tmp)
        success = run_and_read(core, folder / "success.csv", 4, "0.05", "0.01")
        assert success["status"] == "success" and success["estimate"] == "4.00", success
        assert (success["s"], success["peak_sample_size"], success["halving_count"]) == (
            "55891",
            "4",
            "0",
        ), success
        first = run_and_read(fixture, folder / "abort.csv", 256, "0.9", "0.9")
        replay = run_and_read(fixture, folder / "abort_replay.csv", 256, "0.9", "0.9")

    for row in (first, replay):
        assert row["status"] == "algorithm_abort", row
        assert row["estimate"] == row["signed_rel_error"] == row["abs_rel_error"] == "", row
        assert (row["s"], row["peak_sample_size"], row["halving_count"]) == ("166", "166", "1"), row
    print("PASS production Core -> Runner -> RAW success (estimate=4, s=55891, peak=4)")
    print(f"PASS C++ abort fixture stdout (exit=0): {process.stdout.strip()}")
    print("PASS C++ abort fixture -> Runner -> RAW and replay (empty estimate, s=166, peak=166)")


if __name__ == "__main__":
    main()
