"""Aggregate validated CVM-A1 RAW measurements by configuration and environment."""

import argparse
import csv
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from statistics import mean, median, stdev

from scripts.generate_timespace_plan import BASE_WORKLOADS
from scripts.validate_results import COMPLETED, ENVIRONMENT, IDENTITY, verified_rows

GROUP_FIELDS = (
    "algorithm",
    "workload",
    "m",
    "n",
    "F0",
    "epsilon",
    "delta",
    "s",
    "env_os",
    "platform_os",
    "compiler",
    "build_flags",
    *ENVIRONMENT,
    *IDENTITY,
)
DEFAULT_OUTPUT = Path("results/summary/timespace_summary.csv")
BYTES_PER_MIB = 1024**2
PERCENT_PER_UNIT = 100
TRIAL_DETAILS = ("estimate_median", "relative_error_median_pct", "relative_error_count", "run_ids")
COMPARISON_FIELDS = tuple(key for key in GROUP_FIELDS if key not in {"workload", "m", "F0"})
AGGREGATE_METRICS = (
    ("runtime_ms", "runtime_median", "runtime_count", 1),
    ("peak_ram_mib", "ram_median", "ram_count", 1 / BYTES_PER_MIB),
    ("relative_error_pct", "relative_error_median_pct", "relative_error_count", 1),
)


def metric_stats(result, label, rows, field, *, spread=False):
    values = [row[field] for row in rows if row[field] is not None]
    result[f"{label}_count"] = len(values)
    result[f"{label}_mean"] = mean(values) if values else None
    result[f"{label}_median"] = median(values) if values else None
    if spread:
        result[f"{label}_min"] = min(values) if values else None
        result[f"{label}_max"] = max(values) if values else None
        result[f"{label}_stdev"] = stdev(values) if len(values) >= 2 else None


def summarize(rows, *, include_trials=False):
    groups = defaultdict(list)
    known_thresholds = defaultdict(set)
    s_index = GROUP_FIELDS.index("s")
    for row in rows:
        key = tuple(row[field] for field in GROUP_FIELDS)
        groups[key].append(row)
        if row["s"] is not None and row["status"] in COMPLETED:
            known_thresholds[key[:s_index] + key[s_index + 1 :]].add(key)
    # Attribute unmeasured attempts only when the same configuration and
    # environment identify a single completed threshold. RAW stays untouched.
    for key in list(groups):
        if key[s_index] is None:
            candidates = known_thresholds.get(key[:s_index] + key[s_index + 1 :], ())
            if len(candidates) == 1:
                groups[next(iter(candidates))].extend(groups.pop(key))

    summary = []
    for key, records in groups.items():
        group = dict(zip(GROUP_FIELDS, key, strict=True))
        statuses = defaultdict(list)
        for row in records:
            statuses[row["status"]].append(row)
        success = statuses["success"]
        abort = statuses["algorithm_abort"]
        count = len(records)
        group.update(
            f0_over_m=group["F0"] / group["m"],
            run_count=count,
            success_count=len(success),
            abort_count=len(abort),
            execution_error_count=len(statuses["execution_error"]),
            resource_failure_count=len(statuses["resource_failure"]),
            success_rate=len(success) / count,
            abort_rate=len(abort) / count,
            halving_run_count=sum(row["halving_count"] > 0 for row in success),
            halving_total=sum(row["halving_count"] for row in success),
        )
        for label, field in (
            ("runtime", "algorithm_runtime_ms"),
            ("end_to_end", "end_to_end_runtime_ms"),
            ("ram", "process_peak_memory_bytes"),
            ("sample", "peak_sample_size"),
            ("halving", "halving_count"),
            ("signed_rel_error", "signed_rel_error"),
            ("abs_rel_error", "abs_rel_error"),
        ):
            metric_stats(
                group,
                label,
                success,
                field,
                spread=label
                in {
                    "runtime",
                    "end_to_end",
                    "sample",
                    "halving",
                },
            )
        metric_stats(group, "abort_runtime", abort, "algorithm_runtime_ms", spread=True)
        if include_trials:
            estimates = [row["estimate"] for row in success if row["estimate"] is not None]
            f0 = group["F0"]
            errors = (
                [abs(estimate - f0) / f0 * PERCENT_PER_UNIT for estimate in estimates] if f0 else []
            )
            group["estimate_median"] = median(estimates) if estimates else None
            group["relative_error_median_pct"] = median(errors) if errors else None
            group["relative_error_count"] = len(errors)
            group["run_ids"] = " ".join(row["run_id"] for row in records)
        summary.append(group)
    return sorted(
        summary,
        key=lambda row: tuple(-1 if row[key] is None else row[key] for key in GROUP_FIELDS),
    )


def summary_rows(groups):
    """Keep the historical summary.csv schema even when collecting trial details."""
    return [
        {key: value for key, value in group.items() if key not in TRIAL_DETAILS} for group in groups
    ]


def benchmark_rows(groups):
    """Project the plotted groups to a numeric-m-ordered table with RAW identifiers."""
    table = []
    for group in sorted(groups, key=lambda row: row["m"]):
        ram = group["ram_median"]
        table.append(
            {
                "m": group["m"],
                "workload": group["workload"],
                "F0": group["F0"],
                "estimate_median": group["estimate_median"],
                "runtime_median_ms": group["runtime_median"],
                "peak_rss_median_mib": None if ram is None else ram / BYTES_PER_MIB,
                "relative_error_median_pct": group["relative_error_median_pct"],
                "success_count": group["success_count"],
                "run_count": group["run_count"],
                "s": group["s"],
                "f0_over_m": group["f0_over_m"],
                "ram_count": group["ram_count"],
                "abs_rel_error_count": group["abs_rel_error_count"],
                **{
                    key: group[key]
                    for key in GROUP_FIELDS
                    if key not in {"m", "workload", "F0", "s"}
                },
                "run_ids": group["run_ids"],
            }
        )
    return table


def aggregate_by_length(groups):
    """Average comparable workload medians with equal weight, separately for each metric."""
    by_length = defaultdict(list)
    for group in groups:
        by_length[group["m"]].append(group)

    table = []
    for length, candidates in sorted(by_length.items()):
        row = {"m": length}
        for field, median_field, count_field, scale in AGGREGATE_METRICS:
            measured = [
                group
                for group in candidates
                if group["workload"] in BASE_WORKLOADS and group[median_field] is not None
            ]
            workloads = {group["workload"] for group in measured}
            settings = {tuple(group[key] for key in COMPARISON_FIELDS) for group in measured}
            if len(measured) != len(workloads) or len(settings) > 1:
                row.update(
                    {
                        field: None,
                        f"{field}_workloads": 0,
                        f"{field}_trials": 0,
                        f"{field}_status": "mixed_configuration",
                    }
                )
                continue
            row.update(
                {
                    field: mean(group[median_field] for group in measured) * scale
                    if measured
                    else None,
                    f"{field}_workloads": len(workloads),
                    f"{field}_trials": sum(group[count_field] for group in measured),
                    f"{field}_status": (
                        "complete"
                        if len(workloads) == len(BASE_WORKLOADS)
                        else "partial"
                        if measured
                        else "no_data"
                    ),
                }
            )
        table.append(row)
    return table


def write_summary(path, summary):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--benchmark-out", type=Path, help="also write chart data with RAW run IDs")
    parser.add_argument("--aggregate-out", type=Path, help="also write the overall table by m")
    args = parser.parse_args(argv)
    try:
        metadata = args.metadata or args.raw.with_suffix(".metadata.json")
        outputs = [path for path in (args.out, args.benchmark_out, args.aggregate_out) if path]
        pairs = [(output, source) for output in outputs for source in (args.raw, metadata)]
        pairs.extend(combinations(outputs, 2))
        if any(
            left.resolve() == right.resolve()
            or (left.exists() and right.exists() and left.samefile(right))
            for left, right in pairs
        ):
            raise ValueError("summary outputs must differ from one another, RAW and sidecar")
        summary = summarize(verified_rows(args.raw, args.metadata), include_trials=len(outputs) > 1)
        write_summary(args.out, summary_rows(summary))
        if args.benchmark_out is not None:
            write_summary(args.benchmark_out, benchmark_rows(summary))
        if args.aggregate_out is not None:
            write_summary(args.aggregate_out, aggregate_by_length(summary))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(f"Wrote {len(summary)} groups to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
