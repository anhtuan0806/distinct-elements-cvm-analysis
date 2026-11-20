"""Generate, preview, and run the TV4 Time/Space benchmark plans."""

import argparse
import csv
import json
import random
import subprocess
import sys
from dataclasses import asdict, dataclass, fields
from fractions import Fraction
from pathlib import Path

from scripts.validate_results import validate
from src.cli import args_to_config, parse_args
from src.stream_generator import Distribution, StreamConfig
from src.types import compute_cvm_threshold

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "experiments" / "benchmark_plan_timespace.csv"
SCALE_PLAN = ROOT / "experiments" / "benchmark_plan_timespace_scale.csv"
ORDER_SEED = 4404
LENGTHS = (256, 1024, 4096, 16384, 65536)
SCALE_LENGTHS = tuple(factor * 10**power for power in range(5, 8) for factor in (1, 2, 5)) + (
    100_000_000,
)
BASE_WORKLOADS = ("all_duplicate", "uniform", "all_distinct")


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


def generate_plan(*, scale=False):
    profiles = (
        ("P0", LENGTHS, BASE_WORKLOADS, 65536, 0.5, 9),
        ("P1", LENGTHS, ("uniform", "skewed"), 65536, 0.5, 5),
        ("P2", (65536, 262144), ("all_distinct",), 262144, 0.2, 5),
    )
    if scale:
        profiles = (("SCALE", SCALE_LENGTHS, BASE_WORKLOADS, SCALE_LENGTHS[-1], 0.5, 9),)
    for priority, lengths, workloads, n, epsilon, trials in profiles:
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


def write_plan(path, *, scale=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, [item.name for item in fields(PlanRow)], lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(row) for row in generate_plan(scale=scale))


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


def select_rows(priority, *, lengths=(), workloads=()):
    rows = list(generate_plan(scale=priority == "SCALE"))
    if priority == "smoke":
        return [
            PlanRow(**(asdict(row) | {"trials": 2}))
            for row in rows
            if row.priority == "P0" and row.m == LENGTHS[0]
        ]
    selected = [
        row
        for row in rows
        if row.priority == priority
        and (not lengths or row.m in lengths)
        and (not workloads or row.workload in workloads)
    ]
    random.Random(ORDER_SEED).shuffle(selected)
    return selected


def validate_scale_rows(records):
    plan = {(row.m, row.workload): row for row in generate_plan(scale=True)}
    for record in records:
        row = plan.get((record["m"], record["workload"]))
        if row is None:
            raise ValueError("RAW contains configurations outside the SCALE plan")
        offset = record["trial"] - row.first_trial
        if (
            (record["n"], record["F0"], record["epsilon"], record["delta"])
            != (row.n, row.f0, row.epsilon, row.delta)
            or not 0 <= offset < row.trials
            or (record["seed_generator"], record["seed_algorithm"])
            != (row.seed_generator + offset, row.seed_algorithm + offset)
        ):
            raise ValueError("RAW contains trials outside the SCALE plan or its seed schedule")


def run_plan(rows, output, *, preview, resume=False):
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
    if resume:
        report = validate(output)
        if not report.verified or not report.rows:
            raise ValueError("SCALE resume needs a verified real RAW/sidecar pair")
        validate_scale_rows(report.rows)
    elif output.exists() or output.with_suffix(".metadata.json").exists():
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
    parser.add_argument("--scale-plan", action="store_true", help="write the separate SCALE CSV")
    modes = parser.add_mutually_exclusive_group()
    profiles = ("smoke", "P0", "P1", "P2", "SCALE")
    modes.add_argument("--preview", choices=profiles)
    modes.add_argument("--run", choices=profiles)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--m", type=int, action="append", choices=SCALE_LENGTHS)
    parser.add_argument("--workload", action="append", choices=BASE_WORKLOADS)
    parser.add_argument("--resume", action="store_true", help="resume a verified SCALE RAW pair")
    args = parser.parse_args(argv)
    try:
        priority = args.preview or args.run
        if (args.m or args.workload) and priority != "SCALE":
            parser.error("--m and --workload selectors require the SCALE profile")
        if args.resume and args.run != "SCALE":
            parser.error("--resume requires --run SCALE")
        if priority:
            if (
                args.raw is None
                or args.raw.suffix.lower() != ".csv"
                or args.plan_out
                or args.scale_plan
            ):
                parser.error("--preview/--run requires --raw <file.csv> and excludes plan export")
            if args.run == "SCALE" and not args.m:
                parser.error("--run SCALE requires at least one explicit --m selection")
            rows = select_rows(priority, lengths=args.m or (), workloads=args.workload or ())
            return run_plan(
                rows, args.raw.resolve(), preview=bool(args.preview), resume=args.resume
            )
        if args.raw:
            parser.error("--raw requires --preview or --run")
        path = args.plan_out or (SCALE_PLAN if args.scale_plan else DEFAULT_PLAN)
        protected = (
            ROOT / "experiments/benchmark_plan.csv",
            DEFAULT_PLAN if args.scale_plan else SCALE_PLAN,
        )
        if any(
            path.resolve() == target.resolve()
            or (path.exists() and target.exists() and path.samefile(target))
            for target in protected
        ):
            raise ValueError("choose a plan path distinct from the other benchmark plans")
        write_plan(path, scale=args.scale_plan)
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
