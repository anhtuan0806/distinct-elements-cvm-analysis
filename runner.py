"""Run reproducible CVM-A1 trials and record their RAW data and provenance."""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import logging
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.benchmark_report import BenchmarkReport, resolve_output
from src.cli import args_to_config, parse_args
from src.csv_writer import CSVReportWriter
from src.cvm.build import PROJECT_ROOT, binary_identity
from src.cvm.executor import resolve_core_binary, run_cvm_a1_core
from src.stream_generator import Distribution, StreamConfig, generate_stream
from src.types import CVMResult, ExperimentConfig, ExperimentStatus

logger = logging.getLogger("cvm_runner")


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _batch(config: ExperimentConfig, count: int, mode: str, binary_info: dict) -> dict:
    generator_sha = hashlib.sha256(
        (PROJECT_ROOT / "src/stream_generator.py").read_bytes()
    ).hexdigest()
    source = hashlib.sha256()
    paths = sorted(
        [
            PROJECT_ROOT / "runner.py",
            *(PROJECT_ROOT / "src").rglob("*.py"),
            *(PROJECT_ROOT / "src").rglob("*.cpp"),
            *(PROJECT_ROOT / "src").rglob("*.hpp"),
        ]
    )
    for path in paths:
        source.update(path.relative_to(PROJECT_ROOT).as_posix().encode("utf-8") + b"\0")
        source.update(hashlib.sha256(path.read_bytes()).digest())

    python = platform.python_version()
    configuration = dataclasses.asdict(config)
    configuration.pop("run_id")
    return {
        "batch_id": str(uuid.uuid4()),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "source_tree_sha256": source.hexdigest(),
        "generator_sha256": generator_sha,
        "configuration": configuration,
        "requested_trials": count,
        "environment": {
            "os": platform.platform(),
            "python": python,
            "cpu": platform.processor() or platform.machine(),
            "memory_metric": "core_peak_resident_bytes" if mode == "real" else None,
            **binary_info,
        },
        "version": [binary_info["binary_sha256"] or mode, generator_sha, python],
    }


def run_dry_run(config: ExperimentConfig, writer: BenchmarkReport) -> None:
    for status, estimate in (
        (ExperimentStatus.SUCCESS, float(round(config.f0 * 0.995, 2))),
        (ExperimentStatus.ALGORITHM_ABORT, None),
    ):
        if not writer.is_complete(config, status):
            writer.write_record(
                dataclasses.replace(config, run_id=str(uuid.uuid4())),
                CVMResult(status=status, estimate=estimate),
            )


def run_single_trial(
    config: ExperimentConfig,
    writer: CSVReportWriter | BenchmarkReport,
    compiler: str,
    build_flags: str,
    *,
    binary: Path | None = None,
    binary_sha256: str | None = None,
) -> CVMResult:
    config = dataclasses.replace(config, compiler=compiler, build_flags=build_flags)
    stream = generate_stream(
        StreamConfig(
            config.m,
            config.n,
            config.f0,
            Distribution(config.workload),
            config.seed_generator,
        )
    )
    result = run_cvm_a1_core(config, stream, binary)
    if binary is not None and binary_sha256 is not None:
        if hashlib.sha256(binary.read_bytes()).hexdigest() != binary_sha256:
            raise ValueError("Core binary changed during the batch; trial was not recorded")
    writer.write_record(config, result)

    if result.error_msg:
        logger.error("Trial %d, status=%s: %s", config.trial, result.status.value, result.error_msg)
    else:
        logger.info(
            "Trial %d, status=%s, estimate=%s, effective_s=%s, algorithm_ms=%s",
            config.trial,
            result.status.value,
            result.estimate,
            result.effective_s,
            result.algorithm_runtime_ms,
        )
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    mode = "synthetic_mock" if args.dry_run else "real"

    try:
        base = args_to_config(args)
        if args.trials < 1:
            raise ValueError("--trials must be positive")
        if not args.dry_run:
            last_seed = max(base.seed_generator, base.seed_algorithm) + args.trials - 1
            if last_seed >= 2**64:
                raise ValueError("Batch seeds must fit in uint64")
            StreamConfig(
                base.m,
                base.n,
                base.f0,
                Distribution(base.workload),
                base.seed_generator,
            )

        output = resolve_output(args.out, mode, PROJECT_ROOT)
        binary = None if args.dry_run else resolve_core_binary()
        info = (
            {"binary_sha256": None, "compiler": "synthetic", "build_flags": "none"}
            if binary is None
            else binary_identity(binary)
        )
        if args.dry_run:
            base = dataclasses.replace(
                base,
                algorithm="CVM-A1-dryrun",
                compiler="synthetic",
                build_flags="none",
            )

        batch = _batch(base, 2 if args.dry_run else args.trials, mode, info)
        failed = False
        with BenchmarkReport.open(output, mode, batch) as writer:
            if args.dry_run:
                run_dry_run(base, writer)
                return 0
            for offset in range(args.trials):
                config = dataclasses.replace(
                    base,
                    trial=base.trial + offset,
                    run_id=str(uuid.uuid4()),
                    seed_generator=base.seed_generator + offset,
                    seed_algorithm=base.seed_algorithm + offset,
                )
                if writer.is_complete(config):
                    logger.info("Skipping completed trial %d", config.trial)
                    continue
                result = run_single_trial(
                    config,
                    writer,
                    info["compiler"],
                    info["build_flags"],
                    binary=binary,
                    binary_sha256=info["binary_sha256"],
                )
                failed |= result.status in (
                    ExperimentStatus.EXECUTION_ERROR,
                    ExperimentStatus.RESOURCE_FAILURE,
                )
        return 1 if failed else 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        ArithmeticError,
        RuntimeError,
        csv.Error,
        subprocess.SubprocessError,
    ) as exc:
        stderr = getattr(exc, "stderr", None)
        logger.error("Benchmark failed: %s%s", exc, f"\n{stderr.strip()}" if stderr else "")
        return 1


if __name__ == "__main__":
    sys.exit(main())
