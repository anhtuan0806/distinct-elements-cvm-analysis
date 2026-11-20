import csv
import hashlib
import json
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

from runner import _batch
from scripts.analyze_results import aggregate_by_length, benchmark_rows, summarize
from scripts.generate_timespace_plan import SCALE_LENGTHS, generate_plan
from scripts.plot_results import plot_aggregate, plot_summary
from scripts.validate_results import validate
from src.benchmark_report import PROTOCOL_VERSION
from src.types import CSV_COLUMNS, ExperimentConfig, compute_cvm_threshold


@pytest.fixture
def raw_fixture(tmp_path):
    """SYNTHETIC TEST DATA. The protocol envelope is simulated only inside tests."""
    path = tmp_path / "fixture.csv"
    config = ExperimentConfig(100, 200, 20, 0.5, 0.05, 100, 200, workload="uniform")
    row = dict.fromkeys(CSV_COLUMNS, "")
    row.update(
        run_id=str(uuid4()),
        algorithm="CVM-A1",
        workload=config.workload,
        trial=1,
        m=config.m,
        n=config.n,
        F0=config.f0,
        epsilon=config.epsilon,
        delta=config.delta,
        s=config.s,
        seed_generator=100,
        seed_algorithm=200,
        status="success",
        estimate=20,
        algorithm_runtime_ms=2,
        end_to_end_runtime_ms=5,
        peak_sample_size=20,
        halving_count=0,
        process_peak_memory_bytes=1048576,
        signed_rel_error=0,
        abs_rel_error=0,
        env_os=config.env_os,
        compiler="test gcc",
        build_flags="-O3",
    )
    return path, config, row


def write_fixture(path, config, rows, *, columns=CSV_COLUMNS, changes=None):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    content = path.read_bytes()
    batch = _batch(
        config,
        len(rows),
        "real",
        {
            "binary_sha256": "b" * 64,
            "compiler": "test gcc",
            "build_flags": "-O3",
        },
    )
    batch.update(first_record=1, last_record=len(rows), git_commit="a" * 40)
    metadata = dict(
        schema_version="P0",
        protocol_version=PROTOCOL_VERSION,
        data_source="real",
        execution_mode="real",
        target_csv=path.name,
        records_count=len(rows),
        byte_length=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        batches=[batch],
    )
    metadata.update(changes or {})
    path.with_suffix(".metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def test_valid_raw_and_missing_ram(raw_fixture):
    path, config, row = raw_fixture
    row["process_peak_memory_bytes"] = ""
    write_fixture(path, config, [row])
    report = validate(path)
    assert report.verified, report.errors
    [summary] = summarize(report.rows)
    assert summary["ram_count"] == 0
    assert summary["ram_mean"] is None


def test_missing_column(raw_fixture):
    path, config, row = raw_fixture
    write_fixture(path, config, [row], columns=CSV_COLUMNS[:-1])
    assert any("build_flags" in error for error in validate(path).errors)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("m", "1.5"),
        ("seed_algorithm", -1),
        ("trial", 0),
        ("epsilon", "nan"),
        ("delta", 1),
        ("F0", 101),
        ("algorithm_runtime_ms", -1),
        ("status", "bad"),
        ("peak_sample_size", 25),
        ("process_peak_memory_bytes", 0),
        ("seed_generator", 999),
    ],
)
def test_invalid_fields(raw_fixture, field, value):
    path, config, row = raw_fixture
    write_fixture(path, config, [{**row, field: value}])
    assert any(field in error for error in validate(path).errors)


def test_duplicate_run_and_logical_trial(raw_fixture):
    path, config, row = raw_fixture
    write_fixture(path, config, [row, row])
    sidecar = path.with_suffix(".metadata.json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    [batch] = metadata["batches"]
    batch.update(last_record=1, requested_trials=1)
    metadata["batches"].append(
        {
            **batch,
            "batch_id": str(uuid4()),
            "first_record": 2,
            "last_record": 2,
        }
    )
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    errors = validate(path).errors
    assert any("duplicate run_id" in error for error in errors)
    assert any("duplicate completed trial" in error for error in errors)


@pytest.mark.parametrize("estimate", ["", 0])
def test_abort(raw_fixture, estimate):
    path, _, row = raw_fixture
    config = ExperimentConfig(
        4096, 4096, 4096, 0.5, 0.05, 100, 200, workload="all_distinct", env_os=row["env_os"]
    )
    row.update(
        workload=config.workload,
        m=config.m,
        n=config.n,
        F0=config.f0,
        s=config.s,
        status="algorithm_abort",
        estimate=estimate,
        signed_rel_error="",
        abs_rel_error="",
        peak_sample_size=config.s,
        halving_count=1,
    )
    write_fixture(path, config, [row])
    report = validate(path)
    assert report.verified == (estimate == ""), report.errors
    if report.verified:
        [group] = summarize(report.rows)
        assert group["abort_count"] == group["abort_runtime_count"] == 1
        assert group["runtime_count"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"records_count": 10},
        {"sha256": "0" * 64},
        {"byte_length": 100},
        {"pending": {}},
        {"data_source": "synthetic_mock", "execution_mode": "synthetic_mock"},
    ],
)
def test_invalid_metadata(raw_fixture, changes):
    path, config, row = raw_fixture
    write_fixture(path, config, [row], changes=changes)
    assert not validate(path).verified


def test_dryrun_marker_and_historical_provenance(raw_fixture):
    path, config, row = raw_fixture
    write_fixture(path, config, [{**row, "algorithm": "CVM-A1-dryrun"}])
    assert validate(path).classification == "synthetic"
    write_fixture(path, config, [row])
    path.with_suffix(".metadata.json").unlink()
    assert validate(path).classification == "unverified"


def test_empty_sidecar_cannot_verify_raw(raw_fixture):
    path, config, row = raw_fixture
    write_fixture(path, config, [row])
    path.with_suffix(".metadata.json").write_text("{}", encoding="utf-8")
    assert not validate(path).verified


def test_zero_f0_and_cpp_threshold_warning(raw_fixture):
    path, config, row = raw_fixture
    from dataclasses import replace

    config = replace(config, f0=0)
    row.update(
        F0=0, estimate=0, peak_sample_size=0, s=config.s + 1, signed_rel_error="", abs_rel_error=""
    )
    write_fixture(path, config, [row])
    report = validate(path)
    assert report.verified and any("s=" in message for message in report.warnings)
    [group] = summarize(report.rows, include_trials=True)
    assert group["f0_over_m"] == 0
    assert group["signed_rel_error_mean"] is None
    assert group["s"] == config.s + 1
    [point] = benchmark_rows([group])
    assert point["estimate_median"] == 0
    assert point["relative_error_median_pct"] is None


def test_benchmark_uses_medians_of_individual_errors_and_traceable_runs(raw_fixture):
    path, config, row = raw_fixture
    rows = [
        dict(
            row,
            trial=index + 1,
            seed_generator=config.seed_generator + index,
            seed_algorithm=config.seed_algorithm + index,
            run_id=str(uuid4()),
            estimate=estimate,
            signed_rel_error=(estimate - config.f0) / config.f0,
            abs_rel_error=abs(estimate - config.f0) / config.f0,
            algorithm_runtime_ms=runtime,
            process_peak_memory_bytes=rss,
        )
        for index, (estimate, runtime, rss) in enumerate(
            ((0, 1, 1048576), (20, 2, ""), (21, 4, 3145728))
        )
    ]
    write_fixture(path, config, rows)
    report = validate(path)
    assert report.verified, report.errors
    [point] = benchmark_rows(summarize(report.rows, include_trials=True))
    assert point["estimate_median"] == 20
    assert point["relative_error_median_pct"] == pytest.approx(5)
    assert point["runtime_median_ms"] == 2
    assert point["peak_rss_median_mib"] == 2
    assert point["success_count"] == point["run_count"] == 3
    assert point["run_ids"].split() == [row["run_id"] for row in rows]


def test_relative_error_is_recomputed_from_each_verified_raw_estimate(raw_fixture):
    path, config, row = raw_fixture
    row.update(estimate=20.01, signed_rel_error=0.0004995, abs_rel_error=0.0004995)
    write_fixture(path, config, [row])
    report = validate(path)
    assert report.verified, report.errors
    [group] = summarize(report.rows, include_trials=True)
    [point] = aggregate_by_length([group])
    assert group["abs_rel_error_median"] == 0.0004995
    assert point["relative_error_pct"] == pytest.approx(0.05)
    assert point["relative_error_pct_workloads"] == 1
    assert point["relative_error_pct_status"] == "partial"


def test_aggregate_averages_workload_medians_with_per_metric_coverage(raw_fixture):
    path, config, row = raw_fixture
    write_fixture(path, config, [row])
    [verified] = validate(path).rows
    trials = [
        dict(
            verified,
            workload=workload,
            F0=f0,
            estimate=estimate,
            algorithm_runtime_ms=runtime,
            process_peak_memory_bytes=ram,
        )
        for workload, f0, estimate, runtime, ram in (
            ("all_duplicate", 1, 1, 1, None),
            ("uniform", 20, 0, 2, 1 * 2**20),
            ("uniform", 20, 20, 4, None),
            ("uniform", 20, 21, 100, 5 * 2**20),
            ("all_distinct", 100, 104, 24, 9 * 2**20),
            ("skewed", 20, 5, 1000, 99 * 2**20),
        )
    ]
    groups = summarize(trials, include_trials=True)
    [point] = aggregate_by_length(groups)
    assert point["runtime_ms"] == pytest.approx((1 + 4 + 24) / 3)
    assert (point["runtime_ms_workloads"], point["runtime_ms_trials"]) == (3, 5)
    assert point["peak_ram_mib"] == pytest.approx((3 + 9) / 2)
    assert (point["peak_ram_mib_workloads"], point["peak_ram_mib_trials"]) == (2, 3)
    assert point["peak_ram_mib_status"] == "partial"
    assert point["relative_error_pct"] == pytest.approx((0 + 5 + 4) / 3)
    assert (point["relative_error_pct_workloads"], point["relative_error_pct_trials"]) == (3, 5)
    assert {group["workload"] for group in groups} == {
        "all_duplicate",
        "uniform",
        "all_distinct",
        "skewed",
    }


def test_aggregate_does_not_pool_incompatible_settings(raw_fixture):
    path, config, row = raw_fixture
    write_fixture(path, config, [row])
    [base] = summarize(validate(path).rows, include_trials=True)
    for alternative in (
        dict(base, workload="all_duplicate", F0=1, cpu="different CPU"),
        dict(base, workload="all_distinct", F0=100, s=base["s"] + 1),
        dict(base, F0=25),
    ):
        [point] = aggregate_by_length([base, alternative])
        assert point["runtime_ms"] is None
        assert point["runtime_ms_status"] == "mixed_configuration"
        assert point["runtime_ms_workloads"] == point["runtime_ms_trials"] == 0


def test_aggregate_figure_is_one_series_per_panel_with_unmeasured_gaps(
    raw_fixture,
    tmp_path,
    monkeypatch,
):
    from matplotlib.figure import Figure

    path, config, row = raw_fixture
    write_fixture(path, config, [row])
    [base] = summarize(validate(path).rows, include_trials=True)
    table = aggregate_by_length(
        [
            dict(base, m=500_000, ram_median=None),
            dict(base, m=100_000, relative_error_median_pct=None),
        ]
    )
    figures = []
    monkeypatch.setattr(Figure, "savefig", lambda figure, *args, **kwargs: figures.append(figure))
    assert plot_aggregate(table, tmp_path).name == "timespace_combined.png"
    [figure] = figures
    figure.canvas.draw()
    for ax, expected in zip(figure.axes, [[100_000, 500_000], [100_000], [500_000]], strict=True):
        assert list(ax.get_xticks()) == list(SCALE_LENGTHS)
        assert ax.xaxis.get_transform().base == 10
        assert ax.get_xlabel() == "Kích thước dữ liệu m (phần tử)"
        labels = ax.get_xticklabels()
        assert [text.get_text() for text in labels] == [
            "100k",
            "200k",
            "500k",
            "1M",
            "2M",
            "5M",
            "10M",
            "20M",
            "50M",
            "100M",
        ]
        bounds = [text.get_window_extent() for text in labels]
        assert all(a.x1 < b.x0 for a, b in zip(bounds, bounds[1:]))
        assert 0 <= bounds[0].x0 < bounds[-1].x1 <= figure.bbox.width
        [line] = ax.lines
        xy = list(zip(line.get_xdata(), line.get_ydata(), strict=True))
        assert [m for m, value in xy if isfinite(value)] == expected
        assert not isfinite(dict(xy)[200_000])
        assert ax.texts[0].get_text() == "1/3"
    assert not figure.legends


@pytest.mark.parametrize(
    ("errors", "upper", "step"),
    [
        ((0, 0), 1.2, 0.2),
        ((0.3, 1), 1.2, 0.2),
        ((0, 2), 2, 0.5),
        ((0, 2.4), 3, 0.5),
        ((2, 4.9), 5, 1),
        ((5.1, 9), 10, 2),
        ((0, 14), 20, 5),
        ((18, 34), 50, 10),
        ((20, 80), 100, 20),
        ((0, 100), 100, 20),
        ((25, 143), None, None),
    ],
)
def test_aggregate_percent_axis_scales_without_inset(
    errors, upper, step, raw_fixture, tmp_path, monkeypatch
):
    from matplotlib.figure import Figure

    path, config, row = raw_fixture
    write_fixture(path, config, [row])
    [base] = summarize(validate(path).rows, include_trials=True)
    table = aggregate_by_length(
        [
            dict(base, m=m, relative_error_median_pct=error)
            for m, error in zip((256, 1024), errors, strict=True)
        ]
    )
    figures = []
    monkeypatch.setattr(Figure, "savefig", lambda figure, *args, **kwargs: figures.append(figure))
    plot_aggregate(table, tmp_path)
    [figure] = figures
    _, ram, error = figure.axes
    assert ram.get_ylim()[0] == 0
    low, high = error.get_ylim()
    assert low == 0
    ticks = error.get_yticks()
    if upper is not None:
        assert high == upper
        assert list(ticks) == pytest.approx([i * step for i in range(round(upper / step) + 1)])
    else:
        assert high > max(errors)
    assert ticks[0] == 0 and ticks[-1] == high
    assert [tick.get_text() for tick in error.get_yticklabels()] == [
        f"{value:g}%" for value in ticks
    ]
    assert list(error.lines[0].get_ydata()) == list(errors)
    assert not error.child_axes


def test_aggregate_p0_png_has_three_labeled_panels_and_word_resolution(tmp_path, monkeypatch):
    from matplotlib.figure import Figure

    dataset = Path(__file__).resolve().parents[1] / "notebooks" / "data" / "linux_p0"
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for item in manifest["inputs"]:
        report = validate(dataset / item["raw"], dataset / item["sidecar"])
        assert report.verified, report.errors
        rows.extend(report.rows)
    table = aggregate_by_length(summarize(rows, include_trials=True))

    figures = []
    savefig = Figure.savefig

    def capture(figure, *args, **kwargs):
        figures.append(figure)
        return savefig(figure, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", capture)
    path = plot_aggregate(table, tmp_path, label="P0 Linux đã lưu")
    with Image.open(path) as png:
        assert png.size == (2040, 2340)
        assert png.info["dpi"] == pytest.approx((300, 300), abs=0.01)
        png.verify()

    [figure] = figures
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    error = figure.axes[-1]
    assert error.get_ylim() == (0, 2)
    assert not error.child_axes
    ram = figure.axes[1]
    assert ram.get_ylim()[1] > max(ram.lines[0].get_ydata()) * 1.1
    titles = (
        "A. Thời gian chạy theo kích thước dữ liệu",
        "B. Bộ nhớ RAM theo kích thước dữ liệu",
        "C. Sai số tương đối theo kích thước dữ liệu",
    )
    ylabels = ("Thời gian chạy (ms)", "Peak RAM (MiB)", "Sai số tương đối (%)")
    bounds = []
    for ax, title, ylabel in zip(figure.axes, titles, ylabels, strict=True):
        assert ax.get_title(loc="left") == title
        assert ax.get_ylabel() == ylabel
        assert ax.get_xlabel() == "Kích thước dữ liệu m (phần tử)"
        assert ax.xaxis.get_transform().base == 10
        assert list(ax.get_xticks()) == [256, 1024, 4096, 16384, 65536]
        assert [tick.get_text() for tick in ax.get_xticklabels()] == [
            "256",
            "1,024",
            "4,096",
            "16,384",
            "65,536",
        ]
        bounds.append(ax.get_tightbbox(renderer))
    assert all(bounds[i].y0 > bounds[i + 1].y1 for i in range(2))
    for bound in bounds:
        assert 0 <= bound.x0 < bound.x1 <= figure.bbox.width
        assert 0 <= bound.y0 < bound.y1 <= figure.bbox.height


def test_missing_estimate_is_empty_for_failed_trials_and_invalid_for_success(raw_fixture):
    path, config, row = raw_fixture
    row.update(estimate="", signed_rel_error="", abs_rel_error="")
    write_fixture(path, config, [row])
    assert any("estimate must exist" in error for error in validate(path).errors)

    row.update(status="execution_error")
    write_fixture(path, config, [row])
    report = validate(path)
    assert report.verified, report.errors
    [point] = benchmark_rows(summarize(report.rows, include_trials=True))
    assert point["estimate_median"] is None
    assert point["relative_error_median_pct"] is None
    assert point["success_count"] == 0 and point["run_count"] == 1


def test_summary_grouping_and_synthetic_plot(tmp_path):
    common = dict(
        algorithm="CVM-A1",
        n=200,
        epsilon=0.5,
        delta=0.05,
        s=700,
        env_os="test",
        compiler="test",
        build_flags="test",
        python="3.14",
        cpu="test",
        platform_os="test",
        binary_sha256="test",
        source_tree_sha256="test",
        generator_sha256="test",
        git_commit="test",
        status="success",
        end_to_end_runtime_ms=10,
        peak_sample_size=20,
        halving_count=0,
        signed_rel_error=-0.1,
        abs_rel_error=0.1,
    )
    rows = [
        dict(
            common,
            workload=w,
            m=m,
            F0=m // 4,
            algorithm_runtime_ms=t,
            process_peak_memory_bytes=ram,
        )
        for w in ("uniform", "skewed")
        for m in (40, 80)
        for t, ram in ((1, 1048576), (2, None), (9, 3145728))
    ]
    rows.append(
        dict(rows[0], status="execution_error", algorithm_runtime_ms=None, peak_sample_size=0)
    )
    groups = summarize(rows)
    assert len(groups) == 4
    group = next(g for g in groups if g["m"] == 40 and g["workload"] == "uniform")
    assert group["run_count"] == 4 and group["execution_error_count"] == 1
    assert group["runtime_count"] == group["sample_count"] == 3
    assert group["runtime_mean"] == 4 and group["runtime_median"] == 2
    assert group["ram_count"] == 2 and group["ram_median"] == 2097152
    assert group["signed_rel_error_mean"] == -0.1
    paths = plot_summary(groups, tmp_path / "synthetic", label="SYNTHETIC TEST DATA")
    assert len(paths) == 3
    for path in paths:
        with Image.open(path) as png:
            assert png.format == "PNG" and png.width >= 1200
            png.verify()


def test_plot_omits_unmeasured_ram(tmp_path):
    assert plot_summary([], tmp_path, label="SYNTHETIC TEST DATA") == []
    assert list(Path(tmp_path).iterdir()) == []


def test_word_figure_uses_shared_numeric_ticks_and_workload_styles(
    raw_fixture, tmp_path, monkeypatch
):
    from matplotlib.figure import Figure

    path, config, row = raw_fixture
    write_fixture(path, config, [row])
    [group] = summarize(validate(path).rows)
    groups = []
    for m, f0, workload, runtime_ms, rss, error in (
        (100_000_000, 25_000_000, "uniform", 2, 2**20, 0.02),
        (100_000, 1, "all_duplicate", 1, None, 0),
        (200_000, 50_000, "uniform", 1, 3 * 2**20, 0.03),
        (200_000, 200_000, "all_distinct", 1, 2**20, 0.05),
    ):
        groups.append(
            dict(
                group,
                m=m,
                n=100_000_000,
                F0=f0,
                workload=workload,
                s=compute_cvm_threshold(m, config.epsilon, config.delta),
                runtime_median=runtime_ms,
                ram_median=rss,
                abs_rel_error_median=error,
            )
        )
    figures = {}
    monkeypatch.setattr(
        Figure, "savefig", lambda figure, path, **kw: figures.update({path: figure})
    )

    individual = plot_summary(groups, tmp_path)
    [combined] = plot_summary(groups, tmp_path, combined=True)
    assert combined.name == "timespace_combined.png"
    assert len(individual) == 3
    figure = figures[combined]
    runtime, rss, error = figure.axes
    assert len(figure.legends) == 1
    assert len(figure.legends[0].texts) == 3
    for index, (axis, name, unit) in enumerate(
        zip(figure.axes, ("runtime", "ram", "relative_error"), ("ms", "MiB", "%"), strict=True)
    ):
        [separate] = [figures[path].axes[0] for path in individual if name in path.stem]
        assert axis.get_shared_x_axes().joined(runtime, axis)
        assert list(axis.get_xticks()) == list(SCALE_LENGTHS)
        assert axis.get_xscale() == "log"
        assert axis.xaxis.get_transform().base == 10
        assert axis.get_title(loc="left").startswith("ABC"[index])
        assert unit in axis.get_ylabel()
        assert [line.get_color() for line in axis.lines] == [
            line.get_color() for line in separate.lines
        ]
    assert {line.get_label().split()[0]: line.get_marker() for line in runtime.lines} == {
        "all_duplicate": "o",
        "all_distinct": "^",
        "uniform": "s",
    }
    assert [line.get_marker() for line in rss.lines] == ["^", "s"]
    assert list(runtime.lines[-1].get_xdata()) == [200_000, 100_000_000]
    assert list(runtime.lines[-1].get_ydata()) == [1, 2]
    assert list(rss.lines[-1].get_ydata()) == [3, 1]
    assert list(error.lines[-1].get_ydata()) == [3, 2]
    assert all(line.get_markersize() > 0 for axis in figure.axes for line in axis.lines)
    assert "log₁₀" in error.get_xlabel()


def test_plot_keeps_alternative_thresholds_and_distinct_ratios_separate(
    raw_fixture, tmp_path, monkeypatch
):
    from matplotlib.figure import Figure

    path, config, row = raw_fixture
    write_fixture(path, config, [row])
    [group] = summarize(validate(path).rows)
    groups = [
        group,
        dict(group, s=group["s"] + 1),
        dict(group, F0=30),
    ]
    figures = []
    monkeypatch.setattr(Figure, "savefig", lambda figure, *args, **kwargs: figures.append(figure))
    plot_summary(groups, tmp_path, combined=True)
    [figure] = figures
    assert {line.get_label() for line in figure.axes[0].lines} == {
        "uniform · F₀/m = 1/5",
        f"uniform · F₀/m = 1/5 · s = {group['s'] + 1}",
        "uniform · F₀/m = 3/10",
    }


def test_word_figure_exports_with_missing_rss(raw_fixture, tmp_path, monkeypatch):
    from matplotlib.figure import Figure

    path, config, row = raw_fixture
    write_fixture(path, config, [{**row, "process_peak_memory_bytes": ""}])
    groups = summarize(validate(path).rows)
    figures = []
    savefig = Figure.savefig

    def capture_figure(figure, *args, **kwargs):
        figures.append(figure)
        savefig(figure, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", capture_figure)
    assert {p.name for p in plot_summary(groups, tmp_path)} == {
        "timespace_runtime.png",
        "timespace_relative_error.png",
    }
    [path] = plot_summary(groups, tmp_path, combined=True)
    with Image.open(path) as png:
        png.verify()
    runtime, rss, error = figures[-1].axes
    assert list(runtime.lines[0].get_xdata()) == list(error.lines[0].get_xdata()) == [100]
    assert runtime.lines[0].get_marker() == error.lines[0].get_marker() == "s"
    assert not rss.lines and [text.get_text() for text in rss.texts] == ["Không có số đo RSS"]
    groups[0]["abs_rel_error_median"] = None
    plot_summary(groups, tmp_path, combined=True)
    error = figures[-1].axes[-1]
    assert not error.lines
    assert [item.get_text() for item in error.texts] == ["Không có sai số tương đối hợp lệ"]


def test_jupyter_linux_p0_representative_matches_summary_cli(tmp_path):
    from scripts.analyze_results import main as analyze_cli
    from scripts.jupyter_analysis import analyze_jupyter_results

    root = Path(__file__).resolve().parents[1]
    dataset_root = root / "notebooks/data/linux_p0"
    manifest = json.loads((dataset_root / "manifest.json").read_text(encoding="utf-8"))
    item = next(
        value
        for value in manifest["inputs"]
        if value["workload"] == "all_distinct" and value["m"] == 256
    )
    raw = dataset_root / item["raw"]
    sidecar = dataset_root / item["sidecar"]

    result = analyze_jupyter_results(raw, tmp_path / "api", metadata_path=sidecar)
    assert result.raw.shape == (9, 24)
    assert tuple(result.raw.columns) == CSV_COLUMNS
    assert len(result.summary) == 1
    assert result.summary["success_count"].sum() == 9
    assert {path.name for path in result.png_paths} == {
        "timespace_runtime.png",
        "timespace_ram.png",
        "timespace_relative_error.png",
    }
    assert all(path.is_file() for path in result.png_paths)
    assert result.provenance.classification == "verified_real"
    assert result.provenance.raw_sha256 == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert result.provenance.metadata_sha256 == hashlib.sha256(sidecar.read_bytes()).hexdigest()
    report = result.markdown_path.read_text(encoding="utf-8")
    for expected in ("verified_real", "44000", "MiB", "Big-O"):
        assert expected in report

    cli_csv = tmp_path / "cli.csv"
    cli_benchmark = tmp_path / "benchmark.csv"
    assert (
        analyze_cli([str(raw), "--out", str(cli_csv), "--benchmark-out", str(cli_benchmark)]) == 0
    )
    assert result.summary_path.read_bytes() == cli_csv.read_bytes()
    assert result.benchmark_summary_path.read_bytes() == cli_benchmark.read_bytes()
    assert set(result.benchmark_summary.loc[0, "run_ids"].split()) == set(result.raw["run_id"])
    assert "benchmark_summary.csv" in report
    assert "estimate_median" not in result.summary.columns
    without_details = analyze_jupyter_results(raw, tmp_path / "api", plot_workloads=False)
    assert without_details.png_paths == ()
    assert not list(without_details.summary_path.parent.glob("*.png"))


@pytest.mark.parametrize("condition", ["missing", "invalid", "synthetic", "errors_only"])
def test_jupyter_rejects_unusable_raw_before_export(raw_fixture, tmp_path, condition):
    from scripts.jupyter_analysis import analyze_jupyter_results

    path, config, row = raw_fixture
    if condition == "invalid":
        write_fixture(path, config, [{**row, "m": "bad"}])
    elif condition == "synthetic":
        write_fixture(path, config, [row], changes={"data_source": "synthetic_mock"})
    elif condition == "errors_only":
        row.update(
            status="resource_failure", s="", estimate="", signed_rel_error="", abs_rel_error=""
        )
        write_fixture(path, config, [row])

    expected = {
        "missing": "RAW",
        "invalid": "invalid",
        "synthetic": "synthetic",
        "errors_only": "success|algorithm_abort",
    }
    out = tmp_path / "exports"
    with pytest.raises(ValueError, match=expected[condition]):
        analyze_jupyter_results(path, out)
    assert not out.exists()


def test_jupyter_single_configuration_and_rss_disappears(raw_fixture, tmp_path):
    from scripts.jupyter_analysis import analyze_jupyter_results

    path, config, row = raw_fixture
    out = tmp_path / "exports"
    write_fixture(path, config, [row])
    first = analyze_jupyter_results(path, out)
    [old_ram] = (p for p in first.png_paths if p.name == "timespace_ram.png")
    old_bytes = old_ram.read_bytes()
    row.update(process_peak_memory_bytes="")
    write_fixture(path, config, [row])
    sidecar = path.with_suffix(".metadata.json").rename(tmp_path / "explicit.json")
    second = analyze_jupyter_results(path, out, metadata_path=sidecar)

    assert second.summary_path.parent != first.summary_path.parent
    assert second.provenance.metadata_path == sidecar
    assert {p.name for p in second.png_paths} == {
        "timespace_runtime.png",
        "timespace_relative_error.png",
    }
    assert not list(second.summary_path.parent.glob("*ram*.png"))
    assert old_ram.read_bytes() == old_bytes
    assert second.summary.loc[0, "sample_median"] == 20
    with second.benchmark_summary_path.open(newline="", encoding="utf-8") as stream:
        [point] = csv.DictReader(stream)
    assert point["peak_rss_median_mib"] == ""
    assert any("m = 100" in note and "xu hướng" in note for note in second.notes)
    assert any("RSS" in note for note in second.notes)
    report = second.markdown_path.read_text(encoding="utf-8")
    assert "explicit.json" in report and "timespace_ram.png" not in report


@pytest.fixture
def scale_full_manifest(tmp_path, monkeypatch):
    from scripts.jupyter_analysis import REPORT_ENV_FIELDS

    raw = tmp_path / "dataset" / "full.csv"
    raw.parent.mkdir()
    raw.touch()
    sidecar = raw.with_suffix(".metadata.json")
    sidecar.touch()
    manifest_path = tmp_path / "notebooks" / "manifest.json"
    manifest_path.parent.mkdir()
    identity = {name: "a" * 64 for name in REPORT_ENV_FIELDS}
    manifest = {
        "schema_version": 1,
        "dataset_id": "timespace_scale_full",
        "name": "SCALE full fixture",
        "raw": "../dataset/full.csv",
        "raw_sha256": "b" * 64,
        "sidecar_sha256": "c" * 64,
        **{
            field: identity[field]
            for field in ("source_tree_sha256", "generator_sha256", "binary_sha256")
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        {
            **identity,
            "m": spec.m,
            "n": spec.n,
            "F0": spec.f0,
            "epsilon": spec.epsilon,
            "delta": spec.delta,
            "workload": spec.workload,
            "trial": spec.first_trial + offset,
            "run_id": str(uuid4()),
            "seed_generator": spec.seed_generator + offset,
            "seed_algorithm": spec.seed_algorithm + offset,
            "s": spec.s_reference,
            "status": "success",
            "process_peak_memory_bytes": 1024,
        }
        for spec in generate_plan(scale=True)
        for offset in range(spec.trials)
    ]

    def read_pair(csv_path, metadata_path):
        assert (csv_path, metadata_path) == (raw, sidecar)
        return SimpleNamespace(
            rows=rows,
            verified=True,
            metadata={"sha256": manifest["raw_sha256"]},
            metadata_sha256=manifest["sidecar_sha256"],
        )

    monkeypatch.setattr("scripts.jupyter_analysis.validate", read_pair)
    return manifest_path, raw, manifest, rows


def test_jupyter_resolves_relative_scale_full_manifest(scale_full_manifest):
    from scripts.jupyter_analysis import load_scale_full_manifest

    path, raw, expected, _ = scale_full_manifest
    manifest, dataset = load_scale_full_manifest(path)
    assert manifest == expected
    assert dataset["raw"] == raw
    assert dataset["metadata"] == raw.with_suffix(".metadata.json")
    assert dataset["expected_hashes"] == (expected["raw_sha256"], expected["sidecar_sha256"])


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        ("missing_trial", "270 trial"),
        ("duplicate_trial", "270 trial"),
        ("wrong_threshold", "thiếu kết quả"),
        ("wrong_seed", "seed schedule"),
        ("missing_rss", "thiếu kết quả"),
        ("mixed_sources", "một định danh"),
        ("wrong_pipeline", "Định danh"),
        ("checksum", "Checksum"),
    ],
)
def test_jupyter_rejects_ineligible_scale_full_dataset(scale_full_manifest, condition, message):
    from scripts.jupyter_analysis import load_scale_full_manifest

    path, _, manifest, rows = scale_full_manifest
    if condition == "missing_trial":
        rows.pop()
    elif condition == "duplicate_trial":
        rows[-1] = rows[0].copy()
    elif condition == "wrong_threshold":
        rows[-1]["s"] += 1
    elif condition == "wrong_seed":
        rows[-1]["seed_generator"] += 1
    elif condition == "missing_rss":
        rows[-1]["process_peak_memory_bytes"] = None
    elif condition == "mixed_sources":
        rows[-1]["source_tree_sha256"] = "d" * 64
    elif condition == "wrong_pipeline":
        manifest = {**manifest, "source_tree_sha256": "e" * 64}
    elif condition == "checksum":
        manifest = {**manifest, "raw_sha256": "f" * 64}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_scale_full_manifest(path)


def test_jupyter_reports_missing_scale_full_manifest(tmp_path):
    from scripts.jupyter_analysis import load_scale_full_manifest

    with pytest.raises(FileNotFoundError, match="BIG_O_SCALE_FULL_MANIFEST"):
        load_scale_full_manifest(tmp_path / "missing.json")


def test_summary_counts_failed_attempt_with_its_successful_retry(raw_fixture):
    path, config, row = raw_fixture
    failed = dict(
        row, status="execution_error", estimate="", signed_rel_error="", abs_rel_error="", s=""
    )
    success = dict(row, run_id=str(uuid4()))
    write_fixture(path, config, [failed, success])
    sidecar = path.with_suffix(".metadata.json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    [batch] = metadata["batches"]
    batch.update(last_record=1, requested_trials=1)
    metadata["batches"].append(
        {**batch, "batch_id": str(uuid4()), "first_record": 2, "last_record": 2}
    )
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    validated = validate(path)
    assert validated.verified, validated.errors
    assert validated.rows[0]["s"] is None
    [group] = summarize(validated.rows)
    assert group["s"] == config.s
    assert group["execution_error_count"] == group["success_count"] == 1
    assert group["run_count"] == 2 and group["success_rate"] == 0.5


def test_summary_keeps_missing_threshold_when_assignment_is_ambiguous(raw_fixture):
    path, config, row = raw_fixture
    write_fixture(path, config, [row])
    [success] = validate(path).rows
    groups = summarize(
        [
            success,
            {**success, "s": config.s + 1},
            {**success, "s": None, "status": "resource_failure"},
        ]
    )
    assert len(groups) == 3
    assert groups[0]["s"] is None
    assert groups[0]["resource_failure_count"] == 1
    assert all(group["success_count"] == 1 for group in groups[1:])


def test_jupyter_report_labels_groups_measured_on_different_cpus(raw_fixture, tmp_path):
    from scripts.jupyter_analysis import analyze_jupyter_results

    path, config, row = raw_fixture
    write_fixture(path, config, [row, {**row, "run_id": str(uuid4())}])
    sidecar = path.with_suffix(".metadata.json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    [batch] = metadata["batches"]
    batch.update(last_record=1, requested_trials=1)
    batch["environment"]["cpu"] = "CPU alpha"
    metadata["batches"].append(
        {
            **batch,
            "batch_id": str(uuid4()),
            "first_record": 2,
            "last_record": 2,
            "environment": {**batch["environment"], "cpu": "CPU beta"},
        }
    )
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    result = analyze_jupyter_results(path, tmp_path / "exports")
    report = result.markdown_path.read_text(encoding="utf-8")
    assert len(result.summary) == 2 and len(result.png_paths) == 6
    assert any(line.startswith("| E1 |") and "CPU alpha" in line for line in report.splitlines())
    assert any(line.startswith("| E2 |") and "CPU beta" in line for line in report.splitlines())
    assert "| 1 | E1 | uniform |" in report and "| 2 | E2 | uniform |" in report
    summary_rows = [line for line in report.splitlines() if line.startswith("| uniform |")]
    assert len(summary_rows) == 2
    assert "| E1 |" in summary_rows[0] and "| E2 |" in summary_rows[1]
