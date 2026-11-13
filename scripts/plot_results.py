"""Render Time/Space PNG figures from validated CVM-A1 RAW."""

import argparse
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import StrMethodFormatter

from scripts.analyze_results import GROUP_FIELDS, summarize
from scripts.validate_results import verified_rows

METRICS = (
    ("runtime", "Algorithm runtime", "Algorithm runtime (ms)", 1),
    ("ram", "C++ process peak memory", "Peak RSS (MiB)", 1024**2),
    ("sample", "Peak sample size", "Peak |X| (elements)", 1),
)
MARKERS = ("o", "s", "^", "D", "v")
LINE_STYLES = ("-", "--", "-.", ":")
ENV_FIELDS = tuple(
    key
    for key in GROUP_FIELDS
    if key
    not in {
        "workload",
        "m",
        "F0",
        "s",
        "n",
        "epsilon",
        "delta",
    }
)


def plot_summary(groups, out_dir, *, label=""):
    panels = defaultdict(lambda: defaultdict(dict))
    for group in groups:
        if not group["success_count"]:
            continue
        panel = tuple(group[key] for key in ("n", "epsilon", "delta", *ENV_FIELDS))
        workload = group["workload"]
        ratio = Fraction(group["F0"], group["m"])
        if workload == "all_duplicate":
            series = "all_duplicate · F₀ = 1"
        else:
            series = f"{workload} · F₀/m = {ratio}"
        points = panels[panel][series]
        if group["m"] in points:
            raise ValueError(f"ambiguous s values for {series}, m={group['m']}; use a single slice")
        points[group["m"]] = group

    paths = []
    for index, (panel, series) in enumerate(sorted(panels.items()), start=1):
        n, epsilon, delta = panel[:3]
        env = dict(zip(ENV_FIELDS, panel[3:], strict=True))
        for metric, title, ylabel, divisor in METRICS:
            figure = Figure(figsize=(9, 5.5), layout="constrained")
            FigureCanvasAgg(figure)
            ax = figure.subplots()
            ticks = set()
            for series_index, (name, points) in enumerate(sorted(series.items())):
                lengths = sorted(points)
                values = [points[m][f"{metric}_median"] for m in lengths]
                if all(value is None for value in values):
                    continue
                ax.plot(
                    lengths,
                    [float("nan") if value is None else value / divisor for value in values],
                    marker=MARKERS[series_index % len(MARKERS)],
                    linestyle=LINE_STYLES[series_index % len(LINE_STYLES)],
                    markerfacecolor="none",
                    linewidth=1.8,
                    markersize=5,
                    label=name,
                )
                ticks.update(lengths)
            if not ticks:
                continue
            ax.set_xscale("log", base=2)
            if len(ticks) <= 8:
                ax.set_xticks(sorted(ticks))
            ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
            ax.set_xlabel("Stream length m (elements)")
            ax.set_ylabel(ylabel)
            ax.set_ylim(bottom=0, top=ax.get_ylim()[1] * 1.04)
            ax.grid(alpha=0.25)
            ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9)
            figure.suptitle(f"{title} vs stream length" + (f"\n{label}" if label else ""))
            ax.set_title(
                f"Success medians · n={n:,} · ε={epsilon:g} · δ={delta:g}\n"
                f"{env['env_os']} · Python {env['python']} · Core {env['binary_sha256'][:12]}",
                fontsize=10,
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            suffix = f"_{index:02d}" if len(panels) > 1 else ""
            path = out_dir / f"timespace_{metric}{suffix}.png"
            figure.savefig(path, dpi=200)
            paths.append(path)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("results/figures"))
    args = parser.parse_args(argv)
    try:
        groups = summarize(verified_rows(args.raw, args.metadata))
        paths = plot_summary(groups, args.out_dir)
        if not paths:
            raise ValueError("no measurements on successful runs")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    for path in paths:
        print(path)
    if not any(path.stem.startswith("timespace_ram") for path in paths):
        print("No C++ peak RSS measurements on successful runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
