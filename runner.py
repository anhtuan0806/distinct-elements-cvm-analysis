from __future__ import annotations

import logging
import sys
from pathlib import Path

from src.cli import args_to_config, parse_args
from src.csv_writer import CSVReportWriter, compute_relative_errors
from src.types import CVMResult, ExperimentConfig, ExperimentStatus

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

    # Case 2: Mock aborted execution (buffer overflow / underflow)
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
        logger.info("Vui lòng sử dụng cờ --dry-run để chạy kiểm thử schema CSV.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
