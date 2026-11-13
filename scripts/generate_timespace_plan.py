"""Generate and execute the TV4 Giai đoạn 1 Time/Space benchmark matrix."""

import argparse
import csv
import json
import random
import subprocess
import sys
from dataclasses import asdict, dataclass, fields
from fractions import Fraction
from pathlib import Path

from src.cli import args_to_config, parse_args
from src.stream_generator import Distribution, StreamConfig
from src.types import compute_cvm_threshold

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "experiments" / "benchmark_plan_timespace.csv"
ORDER_SEED = 4404
LENGTHS = (256, 1024, 4096, 16384, 65536)


@dataclass(frozen=True)
class PlanRow:
    priority: str
    workload: str
    m: int
    n: int
    f0: int
    f0_over_m: str
    epsilon: float
    delta: float
    s_reference: int
    first_trial: int
    trials: int
    seed_generator: int
    seed_algorithm: int


def generate_plan():
    for priority, lengths, workloads, n, epsilon, trials in (
        ("P0", LENGTHS, ("all_duplicate", "uniform", "all_distinct"), 65536, 0.5, 9),
        ("P1", LENGTHS, ("uniform", "skewed"), 65536, 0.5, 5),
        ("P2", (65536, 262144), ("all_distinct",), 262144, 0.2, 5),
    ):
        for m in lengths:
            for workload in workloads:
                f0 = {"all_duplicate": 1, "all_distinct": m}.get(workload, m // 4)
                yield PlanRow(
                    priority,
                    workload,
                    m,
                    n,
                    f0,
                    str(Fraction(f0, m)),
                    epsilon,
                    0.05,
                    compute_cvm_threshold(m, epsilon, 0.05),
                    1,
                    trials,
                    44000,
                    84000,
                )


def write_plan(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, [item.name for item in fields(PlanRow)], lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(row) for row in generate_plan())


def runner_args(row, output):
    return [
        "--workload",
        row.workload,
        "--m",
        str(row.m),
        "--n",
        str(row.n),
        "--f0",
        str(row.f0),
        "--eps",
        str(row.epsilon),
        "--delta",
        str(row.delta),
        "--trial",
        str(row.first_trial),
        "--trials",
        str(row.trials),
        "--seed-gen",
        str(row.seed_generator),
        "--seed-algo",
        str(row.seed_algorithm),
        "--out",
        str(output),
    ]


def select_rows(priority):
    rows = list(generate_plan())
    if priority == "smoke":
        return [
            PlanRow(**(asdict(row) | {"trials": 2}))
            for row in rows
            if row.priority == "P0" and row.m == LENGTHS[0]
        ]
    selected = [row for row in rows if row.priority == priority]
    random.Random(ORDER_SEED).shuffle(selected)
    return selected


def run_plan(rows, output, *, preview):
    commands = []
    for row in rows:
        args = runner_args(row, output)
        parsed = parse_args(args)
        config = args_to_config(parsed)
        StreamConfig(
            config.m, config.n, config.f0, Distribution(config.workload), config.seed_generator
        )
        commands.append([sys.executable, str(ROOT / "runner.py"), *args])
    print(f"{len(rows)} configurations, {sum(row.trials for row in rows)} real trials", flush=True)
    if preview:
        for command in commands:
            print(json.dumps(command))
        return 0
    if output.exists() or output.with_suffix(".metadata.json").exists():
        raise ValueError("choose a new RAW path; output or sidecar already exists")
    failures = 0
    for command in commands:
        failures += subprocess.run(command, cwd=ROOT, check=False).returncode != 0
    if failures:
        print(f"{failures} Runner commands failed; inspect RAW status and stderr", file=sys.stderr)
    return int(failures > 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-out", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--preview", choices=("smoke", "P0", "P1", "P2"))
    modes.add_argument("--run", choices=("smoke", "P0", "P1", "P2"))
    parser.add_argument("--raw", type=Path)
    args = parser.parse_args(argv)
    try:
        priority = args.preview or args.run
        if priority:
            if args.raw is None or args.raw.suffix.lower() != ".csv" or args.plan_out:
                parser.error("--preview/--run requires --raw <new.csv> and excludes --plan-out")
            return run_plan(select_rows(priority), args.raw.resolve(), preview=bool(args.preview))
        if args.raw:
            parser.error("--raw requires --preview or --run")
        path = args.plan_out or DEFAULT_PLAN
        if path.resolve() == (ROOT / "experiments/benchmark_plan.csv").resolve():
            raise ValueError("choose a Time/Space plan path distinct from the existing RQ1 plan")
        write_plan(path)
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
