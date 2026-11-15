"""Aggregate validated CVM-A1 RAW measurements by configuration and environment."""

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev

from scripts.validate_results import ENVIRONMENT, IDENTITY, verified_rows

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


def metric_stats(result, label, rows, field, *, spread=False):
    values = [row[field] for row in rows if row[field] is not None]
    result[f"{label}_count"] = len(values)
    result[f"{label}_mean"] = mean(values) if values else None
    result[f"{label}_median"] = median(values) if values else None
    if spread:
        result[f"{label}_min"] = min(values) if values else None
        result[f"{label}_max"] = max(values) if values else None
        result[f"{label}_stdev"] = stdev(values) if len(values) >= 2 else None


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in GROUP_FIELDS)].append(row)
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
        summary.append(group)
    return sorted(
        summary,
        key=lambda row: tuple(-1 if row[key] is None else row[key] for key in GROUP_FIELDS),
    )


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
    args = parser.parse_args(argv)
    try:
        metadata = args.metadata or args.raw.with_suffix(".metadata.json")
        if args.out.resolve() in {args.raw.resolve(), metadata.resolve()} or (
            args.out.exists()
            and any(
                source.exists() and args.out.samefile(source) for source in (args.raw, metadata)
            )
        ):
            raise ValueError("summary output must differ from RAW and sidecar")
        summary = summarize(verified_rows(args.raw, args.metadata))
        write_summary(args.out, summary)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(f"Wrote {len(summary)} groups to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
