"""Render Time/Space PNG figures from validated CVM-A1 RAW."""

import argparse
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import NamedTuple

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator, NullLocator

from scripts.analyze_results import (
    AGGREGATE_METRICS,
    BYTES_PER_MIB,
    GROUP_FIELDS,
    PERCENT_PER_UNIT,
    aggregate_by_length,
    summarize,
)
from scripts.generate_timespace_plan import BASE_WORKLOADS, SCALE_LENGTHS
from scripts.validate_results import verified_rows
from src.types import compute_cvm_threshold


class Metric(NamedTuple):
    field: str
    file_label: str
    title: str
    ylabel: str
    scale: float
    missing: str


RUNTIME = Metric(
    "runtime", "runtime", "Core runtime", "Core runtime (ms)", 1, "Không có số đo runtime"
)
RAM = Metric(
    "ram", "ram", "Peak RAM", "C++ process peak RSS (MiB)", 1 / BYTES_PER_MIB, "Không có số đo RSS"
)
RELATIVE_ERROR = Metric(
    "abs_rel_error",
    "relative_error",
    "Relative error",
    "Relative error (%)",
    PERCENT_PER_UNIT,
    "Không có sai số tương đối hợp lệ",
)
METRICS = (RUNTIME, RAM, RELATIVE_ERROR)
WORKLOAD_STYLES = {
    "all_duplicate": ("#a64424", "o", 5.5, 0),
    "uniform": ("#22678f", "s", 8, 1),
    "all_distinct": ("#694a8c", "^", 11, 2),
    "skewed": ("#326c51", "D", 7, 3),
    "zipf": ("#76551f", "v", 9, 0),
}
LINE_STYLES = ("-", "--", "-.", ":")
MEDIAN_NOTE = "Medians of successful runs with measurements"
ENV_FIELDS = tuple(
    key for key in GROUP_FIELDS if key not in {"workload", "m", "F0", "s", "n", "epsilon", "delta"}
)


def _plot_metric(ax, series, metric):
    workload_counts = defaultdict(int)
    for (workload, label), points in sorted(series.items()):
        color, marker, size, style_index = WORKLOAD_STYLES.get(workload, ("#525252", "x", 7, 0))
        style = LINE_STYLES[(style_index + workload_counts[workload]) % len(LINE_STYLES)]
        workload_counts[workload] += 1
        lengths = sorted(points)
        values = []
        for length in lengths:
            group = points[length]
            value = group[f"{metric.field}_median"]
            if metric == RELATIVE_ERROR and "relative_error_median_pct" in group:
                values.append(group["relative_error_median_pct"])
            else:
                values.append(None if value is None else value * metric.scale)
        if all(value is None for value in values):
            continue
        ax.plot(
            lengths,
            [float("nan") if value is None else value for value in values],
            color=color,
            marker=marker,
            linestyle=style,
            markerfacecolor="none",
            markeredgewidth=1.4,
            linewidth=1.6,
            markersize=size,
            label=label,
        )
    ax.set_ylabel(metric.ylabel)
    if ax.lines:
        upper = ax.get_ylim()[1]
        # Leave room for markers at zero, including exact estimates.
        ax.set_ylim(bottom=-upper * 0.045, top=upper * 1.06)
        ax.grid(alpha=0.25)


def _set_stream_axis(ax, lengths):
    ax.set_xscale("log", base=10)
    if set(lengths).issubset(SCALE_LENGTHS):
        ticks = SCALE_LENGTHS
        labels = [f"{m // 1000}k" if m < 10**6 else f"{m // 10**6}M" for m in ticks]
        ax.set_xlim(ticks[0] / 1.12, ticks[-1] * 1.12)
    else:
        last = len(lengths) - 1
        ticks = lengths if len(lengths) <= 10 else [lengths[round(i * last / 9)] for i in range(10)]
        labels = [f"{m:,}" for m in ticks]
    ax.set_xticks(ticks, labels, fontsize=8)
    ax.xaxis.set_minor_locator(NullLocator())
    ax.set_xlabel("Stream length m (elements, log₁₀ scale)")


def _relative_error_ticks(peak):
    """Choose a zero-based percent scale for the largest plotted aggregate error."""
    if peak <= 1:
        return [i / 5 for i in range(7)]
    for upper, intervals in ((2, 4), (3, 6), (5, 5), (10, 5), (20, 4), (50, 5), (100, 5)):
        if peak <= upper:
            return [upper * i / intervals for i in range(intervals + 1)]
    return MaxNLocator(nbins=5).tick_values(0, peak * 1.06)


def plot_aggregate(table, out_dir, *, label=""):
    """Export one three-panel figure with a single aggregate series in each panel."""
    figure = Figure(figsize=(6.8, 7.8), layout="constrained")
    figure.get_layout_engine().set(h_pad=0.08)
    FigureCanvasAgg(figure)
    axes = figure.subplots(3, 1, sharex=True)
    lengths = sorted(row["m"] for row in table)
    scale = set(lengths).issubset(SCALE_LENGTHS)
    positions = SCALE_LENGTHS if scale else lengths
    by_length = {row["m"]: row for row in table}
    captions = (
        ("Thời gian chạy theo kích thước dữ liệu", "Thời gian chạy (ms)"),
        ("Bộ nhớ RAM theo kích thước dữ liệu", "Peak RAM (MiB)"),
        ("Sai số tương đối theo kích thước dữ liệu", "Sai số tương đối (%)"),
    )
    for letter, ax, metric, spec, (title, ylabel) in zip(
        "ABC", axes, METRICS, AGGREGATE_METRICS, captions, strict=True
    ):
        field = spec[0]
        points = {m: row[field] for m, row in by_length.items() if row[field] is not None}
        ax.set_title(f"{letter}. {title}", loc="left", fontsize=10, fontweight="bold")
        ax.set_ylabel(ylabel)
        if points:
            ax.plot(
                positions,
                [points.get(m, float("nan")) for m in positions],
                color="#225b7a",
                marker="o",
                markersize=4.5,
                linewidth=1.7,
                clip_on=False,
            )
            ax.grid(alpha=0.22)
            ax.margins(y=0.22)
        else:
            ax.set_yticks([])
            mixed = any(row[f"{field}_status"] == "mixed_configuration" for row in table)
            message = "Cấu hình hoặc môi trường đo khác nhau" if mixed else metric.missing
            ax.text(0.5, 0.5, message, transform=ax.transAxes, ha="center", va="center")
        if metric is RAM:
            peak = max(points.values(), default=0)
            ax.set_ylim(0, peak * 1.12 if peak else 1)
        if metric is RELATIVE_ERROR:
            peak = max(points.values(), default=0)
            ticks = _relative_error_ticks(peak)
            ax.set_yticks(ticks, [f"{tick:g}%" for tick in ticks])
            ax.set_ylim(0, ticks[-1])
        low, high = ax.get_ylim()
        for m, value in points.items():
            coverage = by_length[m][f"{field}_workloads"]
            if coverage < len(BASE_WORKLOADS):
                near_top = value > high - 0.08 * (high - low)
                ax.annotate(
                    f"{coverage}/{len(BASE_WORKLOADS)}",
                    (m, value),
                    xytext=(0, -7 if near_top else 7),
                    textcoords="offset points",
                    ha="center",
                    va="top" if near_top else "bottom",
                    fontsize=8,
                )
    _set_stream_axis(axes[-1], lengths)
    if lengths and not scale and not any(ax.lines for ax in axes):
        axes[-1].set_xlim(lengths[0] / 1.2, lengths[-1] * 1.2)
    for ax in axes:
        ax.set_xlabel("Kích thước dữ liệu m (phần tử)")
        ax.tick_params(axis="x", labelbottom=True, labelsize=8)
    figure.suptitle(
        f"{label or 'CVM-A1'} · trục m log₁₀\n"
        "Trung bình không trọng số các trung vị theo workload\n"
        "k/3 đánh dấu điểm thiếu workload. Số lượt hợp lệ có trong CSV.",
        fontsize=10,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "timespace_combined.png"
    figure.savefig(path, dpi=300)
    return path


def _combined_figure(series, lengths, heading):
    figure = Figure(figsize=(6.8, 7.8), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(3, 1, sharex=True)
    legend = {}
    for letter, ax, metric in zip("ABC", axes, METRICS, strict=True):
        _plot_metric(ax, series, metric)
        ax.set_title(f"{letter}   {metric.title}", loc="left", fontsize=11, fontweight="bold")
        if not ax.lines:
            ax.set_yticks([])
            ax.text(0.5, 0.5, metric.missing, transform=ax.transAxes, ha="center", va="center")
        legend.update((line.get_label(), line) for line in ax.lines)
    _set_stream_axis(axes[-1], lengths)
    figure.suptitle(heading, fontsize=10)
    figure.legend(
        legend.values(),
        legend.keys(),
        loc="outside lower center",
        ncols=min(3, len(legend)),
        fontsize=8,
        title="Workload",
    )
    return figure


def _series_label(group):
    workload, length, f0 = (group[field] for field in ("workload", "m", "F0"))
    if workload == "all_duplicate":
        label = "all_duplicate · F₀ = 1"
    else:
        label = f"{workload} · F₀/m = {Fraction(f0, length)}"
    # Reference s changes with m by design. Alternative thresholds get separate lines.
    try:
        reference = compute_cvm_threshold(length, group["epsilon"], group["delta"])
    except ArithmeticError:
        reference = None
    if group["s"] != reference:
        label += f" · s = {group['s']}"
    return label


def plot_summary(groups, out_dir, *, label="", combined=False):
    """Write separate metric PNGs or, with combined=True, a Word figure per slice."""
    panels = defaultdict(lambda: defaultdict(dict))
    for group in groups:
        if not group["success_count"]:
            continue
        panel = tuple(group[key] for key in ("n", "epsilon", "delta", *ENV_FIELDS))
        workload = group["workload"]
        series = _series_label(group)
        points = panels[panel][workload, series]
        if group["m"] in points:
            raise ValueError(f"duplicate summary point for {series}, m={group['m']}")
        points[group["m"]] = group

    paths = []
    for index, (panel, series) in enumerate(sorted(panels.items()), start=1):
        lengths = sorted({m for points in series.values() for m in points})
        suffix = f"_{index:02d}" if len(panels) > 1 else ""
        n, epsilon, delta = panel[:3]
        env = dict(zip(ENV_FIELDS, panel[3:], strict=True))
        heading = (
            f"{MEDIAN_NOTE} · n={n:,} · ε={epsilon:g} · δ={delta:g}\n"
            f"{env['env_os']} · Python {env['python']} · Core {env['binary_sha256'][:12]}"
        )
        if combined:
            figure = _combined_figure(series, lengths, f"{label}\n{heading}" if label else heading)
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"timespace_combined{suffix}.png"
            figure.savefig(path, dpi=300)
            paths.append(path)
            continue
        for metric in METRICS:
            figure = Figure(figsize=(9, 5.5), layout="constrained")
            FigureCanvasAgg(figure)
            ax = figure.subplots()
            _plot_metric(ax, series, metric)
            if not ax.lines:
                continue
            _set_stream_axis(ax, lengths)
            ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9)
            figure.suptitle(f"{metric.title} vs stream length" + (f"\n{label}" if label else ""))
            ax.set_title(heading, fontsize=10)
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"timespace_{metric.file_label}{suffix}.png"
            figure.savefig(path, dpi=200)
            paths.append(path)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Export the CVM-A1 aggregate figure from verified RAW."
    )
    parser.add_argument("raw", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("results/figures"))
    parser.add_argument("--workloads", action="store_true", help="plot individual workloads")
    parser.add_argument(
        "--combined", action="store_true", help="with --workloads, combine the three metric panels"
    )
    args = parser.parse_args(argv)
    try:
        groups = summarize(verified_rows(args.raw, args.metadata), include_trials=True)
        if args.workloads:
            destination = args.out_dir / "workloads" if args.combined else args.out_dir
            paths = plot_summary(groups, destination, combined=args.combined)
            if not paths:
                raise ValueError("no measurements on successful runs")
        else:
            paths = [plot_aggregate(aggregate_by_length(groups), args.out_dir)]
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    for path in paths:
        print(path)
    if not any(group["ram_count"] for group in groups):
        print("No C++ peak RSS measurements on successful runs")
    if not any(group["abs_rel_error_count"] for group in groups):
        print("No relative error measurements on successful runs with positive F0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
