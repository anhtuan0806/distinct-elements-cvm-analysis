"""Benchmark runner executing CVM-A1 pipeline end-to-end and writing raw CSV reports."""

from __future__ import annotations

import dataclasses
import logging
import sys
import uuid
from pathlib import Path

from src.cli import args_to_config, parse_args
from src.csv_writer import CSVReportWriter, compute_relative_errors
from src.cvm.build import detect_compiler_info
from src.cvm.executor import run_cvm_a1_core
from src.stream_generator import Distribution, StreamConfig, generate_stream
from src.types import CVMResult, ExperimentConfig, ExperimentStatus

logger = logging.getLogger("cvm_runner")


def configure_logging(verbose: bool = True) -> None:
    """Initialize logging format and log levels."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_dry_run(config: ExperimentConfig, writer: CSVReportWriter) -> None:
    """Execute mock verification mode to validate schema integrity without calling C++."""
    logger.info("Executing DRY-RUN verification mode...")

    # Case 1: Mock successful estimation
    mock_estimate = float(round(config.f0 * 0.995, 2)) if config.f0 > 0 else 0.0
    mock_success = CVMResult(
        status=ExperimentStatus.SUCCESS,
        estimate=mock_estimate,
        algorithm_runtime_ms=10.234,
        end_to_end_runtime_ms=12.345,
        peak_sample_size=min(config.f0, 1200) if config.f0 > 0 else 64,
        halving_count=4,
        process_peak_memory_bytes=1024 * 1024,
        error_msg=None,
    )
    writer.write_record(config, mock_success)
    signed_err, abs_err = compute_relative_errors(
        config.f0, mock_success.estimate, mock_success.status
    )
    logger.info(
        "Successfully wrote mock SUCCESS record: F0=%d, estimate=%.2f, signed_err=%s, abs_err=%s",
        config.f0,
        mock_success.estimate,
        signed_err,
        abs_err,
    )

    # Case 2: Mock aborted execution (buffer capacity failure)
    mock_abort = CVMResult(
        status=ExperimentStatus.ALGORITHM_ABORT,
        estimate=None,
        algorithm_runtime_ms=1.123,
        end_to_end_runtime_ms=1.234,
        peak_sample_size=min(config.f0, 500) if config.f0 > 0 else 32,
        halving_count=1,
        process_peak_memory_bytes=512 * 1024,
        error_msg="Simulated buffer overflow/underflow abort",
    )
    writer.write_record(config, mock_abort)
    logger.info(
        "Successfully wrote mock ABORT record: status=algorithm_abort, estimate=null, reason=%s",
        mock_abort.error_msg,
    )

    logger.info("Dry-run complete. Verified schema integrity on: %s", writer.filepath)


def run_single_trial(
    config: ExperimentConfig,
    writer: CSVReportWriter,
    compiler: str,
    build_flags: str,
) -> CVMResult:
    """Generate reproducible stream, execute C++ CVM-A1 core, and commit RAW record."""
    trial_cfg = dataclasses.replace(
        config,
        compiler=compiler,
        build_flags=build_flags,
    )

    dist_enum = Distribution(trial_cfg.workload)
    stream_cfg = StreamConfig(
        m=trial_cfg.m,
        n=trial_cfg.n,
        f0=trial_cfg.f0,
        distribution=dist_enum,
        seed=trial_cfg.seed_generator,
    )

    stream = generate_stream(stream_cfg)
    result = run_cvm_a1_core(trial_cfg, stream)
    writer.write_record(trial_cfg, result)

    signed_err, abs_err = compute_relative_errors(
        trial_cfg.f0, result.estimate, result.status
    )
    logger.info(
        "Trial %d: status=%s, F0=%d, estimate=%s, signed_err=%s, abs_err=%s, "
        "alg_time=%.3f ms, e2e_time=%.3f ms, peak_sample=%d, halvings=%d",
        trial_cfg.trial,
        result.status.value,
        trial_cfg.f0,
        f"{result.estimate:.2f}" if result.estimate is not None else "null",
        signed_err or "null",
        abs_err or "null",
        result.algorithm_runtime_ms or 0.0,
        result.end_to_end_runtime_ms or 0.0,
        result.peak_sample_size,
        result.halving_count,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI Entrypoint coordinating benchmark execution."""
    configure_logging()
    args = parse_args(argv)

    try:
        base_config = args_to_config(args)
    except ValueError as exc:
        logger.error("Configuration validation error: %s", exc)
        return 1

    out_path = Path(args.out)
    writer = CSVReportWriter(out_path)

    if args.dry_run:
        run_dry_run(base_config, writer)
        return 0

    compiler, build_flags = detect_compiler_info()
    num_trials = getattr(args, "trials", 1)

    logger.info(
        "Starting CVM benchmark: workload=%s, m=%d, n=%d, F0=%d, eps=%.4f, delta=%.4f, trials=%d",
        base_config.workload,
        base_config.m,
        base_config.n,
        base_config.f0,
        base_config.epsilon,
        base_config.delta,
        num_trials,
    )

    for trial_idx in range(1, num_trials + 1):
        # Shift seeds deterministically across multi-trial batches
        seed_offset = trial_idx - 1
        trial_cfg = dataclasses.replace(
            base_config,
            trial=trial_idx,
            run_id=str(uuid.uuid4()),
            seed_generator=base_config.seed_generator + seed_offset,
            seed_algorithm=base_config.seed_algorithm + seed_offset,
        )
        run_single_trial(trial_cfg, writer, compiler, build_flags)

    logger.info(
        "Benchmark complete. Recorded %d trial(s) to: %s",
        num_trials,
        writer.filepath,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
