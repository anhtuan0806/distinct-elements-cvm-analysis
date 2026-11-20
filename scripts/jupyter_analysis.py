"""Analyze validated CVM-A1 benchmark results from a Jupyter cell."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from html import escape
from pathlib import Path
from tempfile import mkdtemp

import pandas as pd

from scripts.analyze_results import benchmark_rows, summarize, summary_rows, write_summary
from scripts.generate_timespace_plan import generate_plan, validate_scale_rows
from scripts.plot_results import METRICS, plot_summary
from scripts.validate_results import COMPLETED, validate
from src.types import CSV_COLUMNS

REPORT_ENV_FIELDS = (
    "env_os",
    "platform_os",
    "python",
    "cpu",
    "compiler",
    "build_flags",
    "binary_sha256",
    "git_commit",
    "source_tree_sha256",
    "generator_sha256",
)


@dataclass(frozen=True)
class AnalysisProvenance:
    """Paths, hashes and metadata from the same validated RAW snapshot."""

    raw_path: Path
    metadata_path: Path
    raw_sha256: str
    metadata_sha256: str
    classification: str
    metadata: dict


@dataclass(frozen=True)
class JupyterAnalysisResult:
    """Tables, report artifacts, and notes for a single analysis run."""

    raw: pd.DataFrame
    summary: pd.DataFrame
    summary_path: Path
    png_paths: tuple[Path, ...]
    markdown_path: Path
    provenance: AnalysisProvenance
    notes: tuple[str, ...]
    benchmark_summary: pd.DataFrame
    benchmark_summary_path: Path
    verified_rows: tuple[dict, ...]


def load_scale_full_manifest(path: str | Path) -> tuple[dict, dict]:
    """Resolve and verify a complete SCALE dataset before notebook display."""
    path = Path(path).expanduser().resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Không tìm thấy manifest SCALE đầy đủ: {path}. "
            "Kiểm tra vị trí dữ liệu hoặc đặt BIG_O_SCALE_FULL_MANIFEST."
        ) from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Manifest SCALE đầy đủ không đọc được: {path}") from exc

    if not (
        isinstance(manifest, dict)
        and manifest.get("schema_version") == 1
        and manifest.get("dataset_id") == "timespace_scale_full"
        and isinstance(manifest.get("name"), str)
        and manifest["name"].strip()
        and isinstance(manifest.get("raw"), str)
        and manifest["raw"].strip()
    ):
        raise ValueError(f"Manifest SCALE đầy đủ không hợp lệ: {path}")

    raw = (path.parent / manifest["raw"]).resolve()
    sidecar = raw.with_suffix(".metadata.json")
    for source in (raw, sidecar):
        if not source.is_file():
            raise FileNotFoundError(f"Không tìm thấy dữ liệu SCALE đầy đủ: {source}")

    report = validate(raw, sidecar)
    if not report.verified:
        raise ValueError("RAW/sidecar SCALE không hợp lệ:\n" + "\n".join(report.errors))
    checksums = report.metadata["sha256"], report.metadata_sha256
    if checksums != (manifest.get("raw_sha256"), manifest.get("sidecar_sha256")):
        raise ValueError("Checksum RAW/sidecar SCALE không khớp manifest.")

    plan = {(row.m, row.workload): row for row in generate_plan(scale=True)}
    expected = {
        (spec.m, spec.workload, trial)
        for spec in plan.values()
        for trial in range(spec.first_trial, spec.first_trial + spec.trials)
    }
    measured = {(row["m"], row["workload"], row["trial"]) for row in report.rows}
    if len(report.rows) != len(expected) or measured != expected:
        raise ValueError(f"SCALE đầy đủ cần đúng {len(expected)} trial theo kế hoạch.")
    validate_scale_rows(report.rows)
    for row in report.rows:
        spec = plan[row["m"], row["workload"]]
        if (
            row["status"] != "success"
            or row["s"] != spec.s_reference
            or row["process_peak_memory_bytes"] is None
        ):
            raise ValueError(f"Trial SCALE thiếu kết quả hợp lệ: {row['run_id']}")

    identity = {tuple(row[field] for field in REPORT_ENV_FIELDS) for row in report.rows}
    if len(identity) != 1:
        raise ValueError("SCALE đầy đủ cần một định danh pipeline và môi trường đo duy nhất.")
    for field in ("source_tree_sha256", "generator_sha256", "binary_sha256"):
        if report.rows[0][field] != manifest.get(field):
            raise ValueError(f"Định danh SCALE không khớp manifest: {field}")
    return manifest, {
        "raw": raw,
        "metadata": sidecar,
        "configuration": "SCALE_FULL",
        "expected_hashes": checksums,
        "record_count": len(report.rows),
        "group_count": len(plan),
        "size_count": len({m for m, _ in plan}),
    }


def _notes(groups: list[dict]) -> tuple[str, ...]:
    lengths = sorted({group["m"] for group in groups if group["success_count"]})
    notes = []
    if not lengths:
        notes.append("Không có lượt success để vẽ các số đo. Bảng vẫn ghi nhận algorithm abort.")
    elif len(lengths) == 1:
        notes.append(f"Chỉ có số đo tại m = {lengths[0]:,}. Chưa đủ điểm để nhận xét xu hướng.")
    else:
        notes.append(
            f"Có số đo success ở {len(lengths)} mức m. "
            "Đọc xu hướng trong cùng workload, tỷ lệ F₀/m và môi trường đo."
        )

    success = sum(group["success_count"] for group in groups)
    rss = sum(group["ram_count"] for group in groups)
    if not rss:
        notes.append("Không có số đo peak RSS của tiến trình C++ từ các lượt success.")
    elif rss < success:
        notes.append(f"Có số đo peak RSS C++ ở {rss}/{success} lượt success.")
    errors = sum(group["relative_error_count"] for group in groups)
    if not errors:
        notes.append("Không có sai số tương đối hợp lệ. Cần lượt success có estimate và F₀ > 0.")
    elif errors < success:
        notes.append(f"Có sai số tương đối ở {errors}/{success} lượt success.")
    if any(group["s"] is None for group in groups):
        notes.append("Các lượt chưa xác định duy nhất ngưỡng s được giữ ở nhóm s trống.")
    return tuple(notes)


def _dataset_title(provenance: AnalysisProvenance) -> str:
    if provenance.raw_path.stem.startswith("tv4_timespace_p0_") and all(
        batch["environment"]["os"].lower().startswith("windows")
        for batch in provenance.metadata["batches"]
    ):
        return "Windows P0"
    return escape(provenance.raw_path.stem)


def _table_row(*cells: object) -> str:
    text = [escape(str(cell)).replace("|", r"\|").replace("\n", " ") for cell in cells]
    return "| " + " | ".join(text) + " |"


def _metric(value: float | None, divisor: int = 1) -> str:
    return "—" if value is None else f"{value / divisor:.6g}"


def _environment_key(row: dict) -> tuple:
    return tuple(row[field] for field in REPORT_ENV_FIELDS)


def _report(
    provenance: AnalysisProvenance,
    rows: list[dict],
    groups: list[dict],
    notes: tuple[str, ...],
    summary_path: Path,
    benchmark_path: Path,
    png_paths: tuple[Path, ...],
) -> str:
    batches = provenance.metadata["batches"]
    environment_keys = dict.fromkeys(_environment_key(row) for row in rows)
    environments = {key: f"E{index}" for index, key in enumerate(environment_keys, start=1)}
    statuses = {
        name: sum(row["status"] == name for row in rows)
        for name in ("success", "algorithm_abort", "execution_error", "resource_failure")
    }
    status_text = ", ".join(f"{count} {name}" for name, count in statuses.items())
    lines = [
        f"# Phân tích TV4 CVM-A1 — {_dataset_title(provenance)}",
        "",
        f"- RAW `{provenance.raw_path}`",
        f"- SHA-256 RAW `{provenance.raw_sha256}`",
        f"- Sidecar `{provenance.metadata_path}`",
        f"- SHA-256 sidecar `{provenance.metadata_sha256}`",
        f"- Validator `{provenance.classification}`",
        f"- {len(rows)} bản ghi · {len(groups)} nhóm · {len(batches)} batch · {status_text}",
        f"- [CSV tổng hợp]({summary_path.name})",
        f"- [CSV số liệu biểu đồ và run_id]({benchmark_path.name})",
        "",
        "## Môi trường đo",
        "",
        "Mã môi trường nối từng batch và nhóm với hệ đo trong sidecar. "
        "Hash của Core và mã nguồn được rút gọn trong bảng này.",
        "",
        "| Mã | OS RAW | OS sidecar | Python | CPU | Compiler | Flags | "
        "Core | Commit | Cây nguồn | Generator |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        *(
            _table_row(code, *key[:6], *(digest[:12] for digest in key[6:]))
            for key, code in environments.items()
        ),
        "",
        "## Cấu hình và lịch seed",
        "",
        "Seed trong bảng là giá trị bắt đầu theo sidecar. RAW ghi seed của từng lượt.",
        "",
        "| Batch | Môi trường | Workload | m | n | F₀ | ε | δ | Seed generator | Seed CVM | "
        "Ghi / yêu cầu |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for index, batch in enumerate(batches, start=1):
        config = batch["configuration"]
        count = batch["last_record"] - batch["first_record"] + 1
        first_row = rows[batch["first_record"] - 1]
        lines.append(
            _table_row(
                index,
                environments[_environment_key(first_row)],
                *(config[key] for key in ("workload", "m", "n", "f0", "epsilon", "delta")),
                config["seed_generator"],
                config["seed_algorithm"],
                f"{count} / {batch['requested_trials']}",
            )
        )

    halving_runs = sum(group["halving_run_count"] for group in groups)
    halving_total = sum(group["halving_total"] for group in groups)
    successful_rows = [row for row in rows if row["status"] == "success"]
    runtime_medians = [group["runtime_median"] for group in groups if group["success_count"]]
    observations = []
    if successful_rows:
        observations.append(
            "- Median runtime theo cấu hình nằm trong khoảng "
            f"{min(runtime_medians):.6g} đến {max(runtime_medians):.6g} ms. "
            f"Peak sample lớn nhất ghi nhận là "
            f"{max(row['peak_sample_size'] for row in successful_rows):,} phần tử."
        )
        rss_medians = [group["ram_median"] for group in groups if group["ram_count"]]
        if rss_medians:
            observations.append(
                f"- Median peak RSS theo cấu hình có số đo nằm trong khoảng "
                f"{min(rss_medians) / 1024**2:.6g} đến {max(rss_medians) / 1024**2:.6g} MiB."
            )
    lines.extend(
        [
            "",
            "## Thống kê theo cấu hình",
            "",
            "Nhóm theo workload, m, n, F₀, ε, δ, s và định danh nguồn, binary, môi trường. "
            "CSV ghi mean, median và độ phân tán khi đủ số đo. Runtime, RSS và sample "
            "dùng lượt success. Runtime abort có cột riêng. Tỷ lệ status dùng tổng số attempt "
            "của nhóm. Attempt thiếu s được gộp khi cấu hình và môi trường xác định duy nhất s.",
            "",
            "| Workload | m | n | F₀ | ε | δ | s | Môi trường | Lượt | Success | Abort | Lỗi | "
            "Có halving | "
            "Runtime median (ms) | RSS median (MiB) | Peak sample median (phần tử) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for group in groups:
        lines.append(
            _table_row(
                *(group[key] for key in ("workload", "m", "n", "F0", "epsilon", "delta")),
                group["s"] if group["s"] is not None else "—",
                environments[_environment_key(group)],
                *(group[key] for key in ("run_count", "success_count", "abort_count")),
                group["execution_error_count"] + group["resource_failure_count"],
                group["halving_run_count"],
                _metric(group["runtime_median"]),
                _metric(group["ram_median"], 1024**2),
                _metric(group["sample_median"]),
            )
        )

    lines.extend(
        [
            "",
            "## Biểu đồ và diễn giải",
            "",
            f"- Trong {statuses['success']} lượt success, {halving_runs} lượt có halving, "
            f"tổng cộng {halving_total} lần.",
            *observations,
            *(f"- {escape(note)}" for note in notes),
            "- Peak RSS đo bộ nhớ thường trú cực đại của tiến trình C++, gồm runtime "
            "và allocator. Chỉ số này loại bộ nhớ của Python/Jupyter.",
            "- Peak sample là số ID tối đa trong tập mẫu, tính cả kích thước trước thinning.",
            "- Sai số là trung vị của |estimate − F₀| / F₀ × 100 qua các lượt success có F₀ > 0. "
            "Công thức dùng estimate và F₀ của từng lượt trong RAW đã xác thực.",
            "- Số đo mô tả cấu hình và môi trường đã chạy. Kết luận Big-O cần phân tích "
            "chi phí cập nhật, thinning và sức chứa mẫu.",
        ]
    )
    for path in png_paths:
        label = next(
            metric.ylabel
            for metric in METRICS
            if path.stem.startswith(f"timespace_{metric.file_label}")
        )
        lines.extend(("", f"![{label}]({path.name})"))
    return "\n".join(lines) + "\n"


def analyze_jupyter_results(
    raw_path: str | Path,
    out_dir: str | Path,
    *,
    metadata_path: str | Path | None = None,
    plot_workloads: bool = True,
) -> JupyterAnalysisResult:
    """Validate a real RAW dataset and export tables, available PNGs and a Markdown report.

    Each call creates a fresh subdirectory under out_dir. Invalid data and data
    containing only execution/resource errors raise ValueError before export.
    """
    raw_path = Path(raw_path).absolute()
    sidecar = (
        Path(metadata_path).absolute() if metadata_path else raw_path.with_suffix(".metadata.json")
    )
    validation = validate(raw_path, sidecar)
    if not validation.verified:
        message = "\n".join(validation.errors)
        raise ValueError(f"RAW {raw_path} ({validation.classification}): {message}")
    rows = validation.rows
    if not any(row["status"] in COMPLETED for row in rows):
        raise ValueError(f"RAW {raw_path} cần ít nhất một lượt success hoặc algorithm_abort.")

    provenance = AnalysisProvenance(
        raw_path=raw_path,
        metadata_path=sidecar,
        raw_sha256=validation.metadata["sha256"],
        metadata_sha256=validation.metadata_sha256,
        classification=validation.classification,
        metadata=validation.metadata,
    )
    groups = summarize(rows, include_trials=True)
    historical_summary = summary_rows(groups)
    benchmark = benchmark_rows(groups)
    notes = (*_notes(groups), *validation.warnings)
    raw = pd.DataFrame.from_records(rows, columns=CSV_COLUMNS)
    summary = pd.DataFrame.from_records(historical_summary)
    benchmark_summary = pd.DataFrame.from_records(benchmark)
    # Preserve exact uint64 values in columns that can also contain nulls.
    for field in ("s", "process_peak_memory_bytes"):
        raw[field] = pd.Series([row[field] for row in rows], dtype=object)
    summary["s"] = pd.Series([group["s"] for group in groups], dtype=object)
    benchmark_summary["s"] = pd.Series([row["s"] for row in benchmark], dtype=object)

    destination = Path(out_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    run_dir = Path(mkdtemp(prefix="tv4-", dir=destination))
    summary_path = run_dir / "summary.csv"
    benchmark_path = run_dir / "benchmark_summary.csv"
    markdown_path = run_dir / "report.md"
    try:
        write_summary(summary_path, historical_summary)
        write_summary(benchmark_path, benchmark)
        png_paths = tuple(plot_summary(groups, run_dir)) if plot_workloads else ()
        markdown_path.write_text(
            _report(provenance, rows, groups, notes, summary_path, benchmark_path, png_paths),
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(run_dir)
        raise
    return JupyterAnalysisResult(
        raw,
        summary,
        summary_path,
        png_paths,
        markdown_path,
        provenance,
        notes,
        benchmark_summary,
        benchmark_path,
        tuple(rows),
    )
