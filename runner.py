from __future__ import annotations

import logging
import sys
from pathlib import Path

from src.algorithms.base import CVMA1Algorithm
from src.cli import args_to_config, parse_args
from src.csv_writer import CSVReportWriter, compute_rel_error
from src.generators.base import SyntheticStreamGenerator
from src.types import CVMResult, ExperimentConfig

logger = logging.getLogger("cvm_runner")


def configure_logging(verbose: bool = True) -> None:
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_dry_run(config: ExperimentConfig, writer: CSVReportWriter) -> None:
    logger.info("Executing DRY-RUN verification mode...")

    # Case 1: Mock successful estimation
    mock_estimate = float(round(config.f0 * 0.995, 2)) if config.f0 > 0 else 0.0
    mock_success = CVMResult(
        estimate=mock_estimate,
        abort=False,
        runtime_ms=12.345,
        peak_memory_kb=1024.50,
        max_buffer_size=min(config.f0, 1200) if config.f0 > 0 else 64,
        halving_count=4,
        error_msg=None,
    )
    writer.write_record(config, mock_success)
    rel_err_str = compute_rel_error(config.f0, mock_success.estimate, mock_success.abort)
    logger.info(
        "Successfully wrote mock SUCCESS record: F0=%d, estimate=%.2f, rel_error=%s",
        config.f0,
        mock_success.estimate,
        rel_err_str,
    )

    # Case 2: Mock aborted execution (buffer overflow / underflow)
    mock_abort = CVMResult(
        estimate=0.0,
        abort=True,
        runtime_ms=1.234,
        peak_memory_kb=512.00,
        max_buffer_size=min(config.f0, 500) if config.f0 > 0 else 32,
        halving_count=1,
        error_msg="Simulated buffer overflow/underflow abort",
    )
    writer.write_record(config, mock_abort)
    logger.info(
        "Successfully wrote mock ABORT record: abort=TRUE, rel_error=NA, reason=%s",
        mock_abort.error_msg,
    )

    logger.info("Dry-run complete. Verified schema integrity on: %s", writer.filepath)


def run_benchmark(config: ExperimentConfig, writer: CSVReportWriter) -> CVMResult:
    logger.info(
        "Starting benchmark execution: m=%d, n=%d, F0=%d, eps=%.4f, delta=%.4f, seed=%d",
        config.m,
        config.n,
        config.f0,
        config.epsilon,
        config.delta,
        config.seed,
    )

    generator = SyntheticStreamGenerator(config)
    algorithm = CVMA1Algorithm(config)

    logger.info("Streaming tokens to CVM-A1 core engine...")
    result = algorithm.process_stream(generator.generate())

    writer.write_record(config, result)
    rel_err_str = compute_rel_error(config.f0, result.estimate, result.abort)
    logger.info(
        "Benchmark completed - Estimate: %.2f (F0: %d), Abort: %s, RelError: %s, "
        "Runtime: %.3f ms, PeakMem: %.2f KB, MaxBuffer: %d, Halvings: %d",
        result.estimate,
        config.f0,
        result.abort,
        rel_err_str,
        result.runtime_ms,
        result.peak_memory_kb,
        result.max_buffer_size,
        result.halving_count,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)

    try:
        config = args_to_config(args)
    except ValueError as exc:
        logger.error("Configuration validation error: %s", exc)
        return 1

    out_path = Path(args.out)
    writer = CSVReportWriter(out_path)

    if args.dry_run:
        run_dry_run(config, writer)
    else:
        run_benchmark(config, writer)

    return 0


if __name__ == "__main__":
    sys.exit(main())
