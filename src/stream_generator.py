"""Deterministic generators for synthetic distinct-element data streams."""

from __future__ import annotations

import bisect
import random
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

UINT64_MAX = (1 << 64) - 1


class Distribution(str, Enum):
    """Supported shapes for a generated stream."""

    ALL_DUPLICATE = "all_duplicate"
    ALL_DISTINCT = "all_distinct"
    UNIFORM = "uniform"
    SKEWED = "skewed"
    ZIPF = "zipf"


@dataclass(frozen=True)
class StreamConfig:
    """Parameters for generating one reproducible stream.

    IDs are selected from ``[0, n)`` and are therefore compatible with the
    unsigned 64-bit IDs accepted by ``cvm_core``.
    """

    m: int
    n: int
    f0: int
    distribution: Distribution
    seed: int

    def __post_init__(self) -> None:
        for name, value in (
            ("m", self.m),
            ("n", self.n),
            ("f0", self.f0),
            ("seed", self.seed),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")

        try:
            distribution = Distribution(self.distribution)
        except (TypeError, ValueError) as exc:
            choices = ", ".join(item.value for item in Distribution)
            raise ValueError(f"distribution must be one of: {choices}") from exc
        object.__setattr__(self, "distribution", distribution)

        if not 1 <= self.m <= UINT64_MAX:
            raise ValueError(f"m must be in [1, {UINT64_MAX}]")
        if not 1 <= self.n <= UINT64_MAX + 1:
            raise ValueError(f"n must be in [1, {UINT64_MAX + 1}]")
        if not 0 <= self.seed <= UINT64_MAX:
            raise ValueError(f"seed must be in [0, {UINT64_MAX}]")
        if not 1 <= self.f0 <= min(self.m, self.n):
            raise ValueError("f0 must be in [1, min(m, n)]")
        if distribution is Distribution.ALL_DUPLICATE and self.f0 != 1:
            raise ValueError("all_duplicate requires f0=1")
        if distribution is Distribution.ALL_DISTINCT and self.f0 != self.m:
            raise ValueError("all_distinct requires f0=m")


def _sample_unique_values(rng: random.Random, population_size: int, sample_size: int) -> list[int]:
    """Sample without replacement without materializing the full population."""
    selected: list[int] = []
    selected_set: set[int] = set()

    # Floyd's algorithm uses O(sample_size) space and supports large integer
    # populations such as the full uint64 ID domain.
    for upper_bound in range(population_size - sample_size, population_size):
        candidate = rng.randrange(upper_bound + 1)
        value = upper_bound if candidate in selected_set else candidate
        selected.append(value)
        selected_set.add(value)

    rng.shuffle(selected)
    return selected


def _weights(distribution: Distribution, count: int) -> list[float]:
    if distribution is Distribution.UNIFORM:
        return [1.0] * count

    if distribution is Distribution.SKEWED:
        if count == 1:
            return [1.0]
        head_count = (count + 4) // 5
        tail_count = count - head_count
        return [
            *([0.8 / head_count] * head_count),
            *([0.2 / tail_count] * tail_count),
        ]

    if distribution is Distribution.ZIPF:
        if count == 1:
            return [1.0]
        return [rank**-1.2 for rank in range(1, count + 1)]

    raise ValueError(f"{distribution.value} does not use weighted sampling")


def _iter_stream(config: StreamConfig, rng: random.Random) -> Iterator[int]:
    if config.distribution is Distribution.ALL_DUPLICATE:
        value = rng.randrange(config.n)
        for _ in range(config.m):
            yield value
        return

    values = _sample_unique_values(rng, config.n, config.f0)
    if config.distribution is Distribution.ALL_DISTINCT:
        yield from values
        return

    # Numeric ID order defines rank for the weighted distributions.
    values.sort()

    positions = _sample_unique_values(rng, config.m, config.f0)
    rng.shuffle(positions)
    forced_values = dict(zip(positions, values, strict=True))

    cumulative_weights: list[float] = []
    total_weight = 0.0
    for weight in _weights(config.distribution, config.f0):
        total_weight += weight
        cumulative_weights.append(total_weight)

    for position in range(config.m):
        forced_value = forced_values.get(position)
        if forced_value is not None:
            yield forced_value
            continue

        target = rng.random() * total_weight
        selected_index = min(bisect.bisect_right(cumulative_weights, target), config.f0 - 1)
        yield values[selected_index]


def generate_stream(config: StreamConfig) -> Iterator[int]:
    """Return a lazy stream with exactly ``config.m`` values and ``config.f0`` IDs.

    Every ID in the selected distinct-value pool is placed at one seeded
    position first. Remaining positions are sampled according to the selected
    distribution. The complete stream is not materialized in memory; auxiliary
    state is O(F0). Repeating the call with the same config in the same Python
    environment produces the same sequence.
    """
    if not isinstance(config, StreamConfig):
        raise ValueError("config must be a StreamConfig")
    return _iter_stream(config, random.Random(config.seed))
