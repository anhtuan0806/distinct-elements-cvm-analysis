"""Command Line Interface (CLI) parser for CVM-A1 benchmark runner."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from src.types import ExperimentConfig


def build_parser() -> argparse.ArgumentParser:
    """Construct the command line argument parser with strict typing and defaults."""
    parser = argparse.ArgumentParser(
        prog="cvm_benchmark",
        description="Benchmark and verification runner for CVM-A1 distinct elements algorithm.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--m",
        type=int,
        default=100000,
        help="Total stream length (token count).",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=50000,
        help="Universe size (cardinality of domain items).",
    )
    parser.add_argument(
        "--f0",
        type=int,
        default=10000,
        help="Ground truth number of distinct elements (F0).",
    )
    parser.add_argument(
        "--eps",
        type=float,
        default=0.05,
        dest="eps",
        help="Target epsilon relative error bound (0 < eps < 1).",
    )
    parser.add_argument(
        "--delta",
        type=float,
        default=0.01,
        help="Target delta error probability (0 < delta < 1).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic stream generation.",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="results/raw_benchmark.csv",
        help="Output CSV file path to store benchmark metrics.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run in mock mode to validate schema and CSV pipeline without executing stream.",
    )

    return parser


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = build_parser()
    return parser.parse_args(args)


def args_to_config(args: argparse.Namespace) -> ExperimentConfig:
    """Convert parsed CLI arguments into a validated ExperimentConfig object."""
    return ExperimentConfig(
        m=args.m,
        n=args.n,
        f0=args.f0,
        epsilon=args.eps,
        delta=args.delta,
        seed=args.seed,
    )
