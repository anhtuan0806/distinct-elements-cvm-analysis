"""Stream generator interfaces and synthetic data stream generators."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator

from src.types import ExperimentConfig


class BaseStreamGenerator(ABC):
    """Abstract base class for streaming input token generators."""

    def __init__(self, config: ExperimentConfig) -> None:
        self.config: ExperimentConfig = config

    @abstractmethod
    def generate(self) -> Iterator[int]:
        """Yield a stream of token identifiers."""
        raise NotImplementedError


class SyntheticStreamGenerator(BaseStreamGenerator):
    """Memory-efficient synthetic stream generator with exact ground truth F0.

    Guarantees:
        - Exactly config.f0 distinct items from universe [1, config.n] appear in stream.
        - Stream length is exactly config.m.
        - First occurrences of distinct tokens are interleaved across the stream.
        - Memory consumption is strictly O(f0), yielding elements on the fly.
    """

    def __init__(self, config: ExperimentConfig) -> None:
        super().__init__(config)
        self._rng: random.Random = random.Random(config.seed)

    def generate(self) -> Iterator[int]:
        """Generate and yield token IDs one by one."""
        f0 = self.config.f0
        m = self.config.m
        n = self.config.n

        if f0 == 0 or m == 0:
            return

        # Sample distinct items from universe 1..n
        distinct_items: list[int] = self._rng.sample(range(1, n + 1), k=f0)
        self._rng.shuffle(distinct_items)

        unseen_idx = 0
        for t in range(m):
            remaining_slots = m - t
            remaining_unseen = f0 - unseen_idx

            # Interleave unseen distinct items so they are distributed across the stream
            if remaining_unseen > 0 and (
                remaining_unseen == remaining_slots
                or self._rng.random() < remaining_unseen / remaining_slots
            ):
                yield distinct_items[unseen_idx]
                unseen_idx += 1
            else:
                yield self._rng.choice(distinct_items)


class CustomStreamGenerator(BaseStreamGenerator):
    """Stream generator yielding from a predefined iterable, validating length m."""

    def __init__(self, config: ExperimentConfig, tokens: Iterable[int]) -> None:
        super().__init__(config)
        self.tokens: list[int] = list(tokens)
        if len(self.tokens) != config.m:
            raise ValueError(
                f"Custom stream length mismatch: expected {config.m}, got {len(self.tokens)}"
            )

    def generate(self) -> Iterator[int]:
        """Yield the custom tokens."""
        yield from self.tokens

