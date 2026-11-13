"""Smoke checks against a built executable; run explicitly, independently of pytest."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import subprocess
import time
from pathlib import Path


def run_checks(executable: Path) -> dict:
    executable = executable.resolve()
    base = [str(executable), "--m", "4", "--eps", "0.05", "--delta", "0.01", "--seed", "42"]
    v2 = [*base, "--output-format", "csv-v2"]
    records = []

    def invoke(name: str, command: list[str], data: str, expected_error: str | None = None):
        result = subprocess.run(command, input=data, text=True, capture_output=True, timeout=15)
        record = {
            "name": name,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        records.append(record)
        if expected_error is not None:
            assert result.returncode != 0 and result.stdout == "", record
            assert "execution_error" in result.stderr and expected_error in result.stderr, record
            return None
        assert result.returncode == 0 and result.stderr == "", record
        rows = list(csv.reader(io.StringIO(result.stdout)))
        assert len(rows) == 1, record
        return rows[0]

    def validate_v2(row: list[str]):
        assert len(row) == 6 and row[0] == "success", row
        assert math.isfinite(float(row[2])) and float(row[2]) >= 0, row

    data = "10\n20\n10\n30\n"
    row = invoke("smoke_v2", v2, data)
    validate_v2(row)
    expected_s = math.ceil(12 / 0.05**2 * math.log2(8 * 4 / 0.01))
    assert float(row[1]) == 3 and row[3:] == ["3", "0", str(expected_s)], row
    assert invoke("legacy_compatibility", base, data) == ["3", "FALSE", "3", "0"]
    for m, eps, delta in [
        (8, "0.3", "0.125"),
        (4096, "0.3", "0.125"),
        (8, str(2**-26), "0.125"),
        (8, "0.5", "0.49999999999999994"),
        *((m, "0.5", "0.05") for m in (256, 1024, 4096, 16384, 65536)),
    ]:
        args = [str(executable), "--m", str(m), "--eps", eps, "--delta", delta, "--seed", "42"]
        query = invoke(
            f"threshold_{m}_{eps}_{delta}", [*args, "--output-format", "threshold-v1"], ""
        )
        measured = invoke(
            f"stream_{m}_{eps}_{delta}", [*args, "--output-format", "csv-v2"], "0\n" * m
        )
        validate_v2(measured)
        assert query == ["threshold-v1", measured[-1]], (query, measured)
    threshold_command = [*base, "--output-format", "threshold-v1"]
    invoke(
        "threshold_malformed_m",
        [*threshold_command[:2], "8x", *threshold_command[3:]],
        "",
        "invalid --m",
    )
    invoke(
        "threshold_invalid_epsilon",
        [*threshold_command[:4], "nan", *threshold_command[5:]],
        "",
        "epsilon",
    )
    invoke(
        "threshold_invalid_delta",
        [*threshold_command[:6], "1", *threshold_command[7:]],
        "",
        "delta",
    )
    invoke(
        "threshold_overflow",
        [*threshold_command[:4], "1e-30", *threshold_command[5:]],
        "",
        "does not fit in size_t",
    )
    invoke("early_eof", v2, "10\n20\n10\n", "input ended after 3 IDs; expected 4")
    invoke("missing_seed", [*base[:-2], "--output-format", "csv-v2"], "", "--seed")
    invoke("negative_m", [str(executable), "--m", "-1", *v2[3:]], "", "invalid --m")
    invoke("invalid_epsilon", [*v2[:4], "0", *v2[5:]], "", "epsilon")
    invoke("invalid_delta", [*v2[:6], "1", *v2[7:]], "", "delta")
    invoke("overflow_seed", [*v2[:8], str(2**64), *v2[9:]], "", "invalid --seed")
    invoke("bad_output_format", [*base, "--output-format", "json"], "", "--output-format")
    invoke("duplicate_output_format", [*v2, "--output-format", "csv-v2"], "", "duplicate")
    for name, bad_id in [
        ("malformed_id", "10x"),
        ("negative_id", "-1"),
        ("overflow_id", str(2**64)),
        ("blank_id", ""),
        ("multiple_ids_on_line", "10 20"),
    ]:
        invoke(name, v2, f"{bad_id}\n", "uint64 ID at line 1")
    empty = invoke("empty_stream", [str(executable), "--m", "0", *v2[3:]], "")
    validate_v2(empty)
    assert empty[1] == "0" and empty[3:] == ["0", "0", "0"], empty
    boundary = invoke("uint64_boundary", v2, f"0\n{2**64 - 1}\n0\n30\n")
    validate_v2(boundary)
    assert float(boundary[1]) == 3 and boundary[3:] == row[3:], boundary
    trailing = invoke("stops_at_m", v2, data + "invalid-unread\n")
    assert trailing[:2] == row[:2] and trailing[3:] == row[3:], trailing

    random_input = "".join(f"{i if i < 2048 else (i * 37) % 2048}\n" for i in range(4096))
    random_command = [str(executable), "--m", "4096", "--eps", "0.9", *v2[5:]]
    first = invoke("repeat_seed_first", random_command, random_input)
    second = invoke("repeat_seed_second", random_command, random_input)
    validate_v2(first)
    validate_v2(second)
    assert first[:2] == second[:2] and first[3:] == second[3:], (first, second)
    assert int(first[4]) > 0, first

    # The intentional input wait is logged, not enforced by a tight absolute
    # timing assertion: process startup and scheduling vary across machines.
    started = time.perf_counter()
    with subprocess.Popen(
        v2, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as process:
        process.stdin.write("10\n")
        process.stdin.flush()
        wait_started = time.perf_counter()
        time.sleep(0.4)
        wait_ms = (time.perf_counter() - wait_started) * 1000
        stdout, stderr = process.communicate("20\n10\n30\n", timeout=15)
        exit_code = process.returncode
    wall_ms = (time.perf_counter() - started) * 1000
    delayed = list(csv.reader(io.StringIO(stdout)))
    assert exit_code == 0 and stderr == "" and len(delayed) == 1, (exit_code, stdout, stderr)
    validate_v2(delayed[0])
    assert delayed[0][:2] == row[:2] and delayed[0][3:] == row[3:], delayed
    return {
        "executable": str(executable),
        "checks": records,
        "delayed_input": {
            "stdout": stdout,
            "exit_code": exit_code,
            "input_wait_ms": wait_ms,
            "wall_runtime_ms": wall_ms,
            "algorithm_runtime_ms": float(delayed[0][2]),
            "wall_minus_algorithm_ms": wall_ms - float(delayed[0][2]),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    report = run_checks(args.executable)
    text = json.dumps(report, indent=2)
    print(text)
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.log.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
