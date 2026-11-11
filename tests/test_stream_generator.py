from __future__ import annotations

from collections import Counter

import pytest

from src.stream_generator import UINT64_MAX, Distribution, StreamConfig, generate_stream


def config_for(
    distribution: Distribution,
    *,
    seed: int = 42,
    m: int | None = None,
    n: int | None = None,
    f0: int | None = None,
) -> StreamConfig:
    if distribution is Distribution.ALL_DUPLICATE:
        defaults = (64, 20, 1)
    elif distribution is Distribution.ALL_DISTINCT:
        defaults = (64, 80, 64)
    else:
        defaults = (512, 20, 5)
    return StreamConfig(
        m=defaults[0] if m is None else m,
        n=defaults[1] if n is None else n,
        f0=defaults[2] if f0 is None else f0,
        distribution=distribution,
        seed=seed,
    )


@pytest.mark.parametrize("distribution", list(Distribution))
def test_each_distribution_has_exact_length_f0_and_valid_ids(
    distribution: Distribution,
) -> None:
    config = config_for(distribution)

    stream = list(generate_stream(config))

    assert len(stream) == config.m
    assert len(set(stream)) == config.f0
    assert all(0 <= value < config.n for value in stream)


@pytest.mark.parametrize("distribution", list(Distribution))
def test_same_config_and_seed_reproduce_the_stream(distribution: Distribution) -> None:
    config = config_for(distribution, seed=2026)

    assert list(generate_stream(config)) == list(generate_stream(config))


def test_all_duplicate_repeats_one_id() -> None:
    stream = list(generate_stream(config_for(Distribution.ALL_DUPLICATE, m=100)))

    assert len(set(stream)) == 1
    assert len(stream) == 100


def test_all_distinct_has_one_id_per_stream_position() -> None:
    stream = list(generate_stream(config_for(Distribution.ALL_DISTINCT, m=100, n=100, f0=100)))

    assert len(stream) == 100
    assert len(set(stream)) == 100


def test_uniform_counts_are_balanced_for_a_fixed_seed() -> None:
    config = config_for(Distribution.UNIFORM, m=50_000, n=5, f0=5, seed=171)
    counts = Counter(generate_stream(config)).values()

    assert max(counts) - min(counts) < config.m * 0.02


def test_skewed_distribution_favors_its_head_for_a_fixed_seed() -> None:
    config = config_for(Distribution.SKEWED, m=50_000, n=5, f0=5, seed=172)
    counts = Counter(generate_stream(config))

    assert 0.76 < counts[0] / config.m < 0.84


def test_zipf_counts_decrease_by_rank_for_a_fixed_seed() -> None:
    config = config_for(Distribution.ZIPF, m=50_000, n=5, f0=5, seed=173)
    counts = Counter(generate_stream(config))

    assert all(counts[rank] > counts[rank + 1] for rank in range(config.f0 - 1))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"m": 0}, "m must"),
        ({"n": 0}, "n must"),
        ({"f0": 0}, "f0 must"),
        ({"m": 4, "n": 10, "f0": 5}, "f0 must"),
        ({"m": 10, "n": 4, "f0": 5}, "f0 must"),
        ({"seed": -1}, "seed must"),
        ({"seed": UINT64_MAX + 1}, "seed must"),
        ({"m": UINT64_MAX + 1}, "m must"),
        ({"n": UINT64_MAX + 2}, "n must"),
        ({"m": 2.5}, "m must be an integer"),
        ({"seed": True}, "seed must be an integer"),
    ],
)
def test_invalid_config_values_are_rejected(overrides: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "m": 20,
        "n": 10,
        "f0": 5,
        "distribution": Distribution.UNIFORM,
        "seed": 42,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        StreamConfig(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("distribution", "m", "n", "f0"),
    [
        (Distribution.ALL_DUPLICATE, 10, 10, 2),
        (Distribution.ALL_DISTINCT, 10, 10, 9),
    ],
)
def test_distribution_specific_constraints_are_rejected(
    distribution: Distribution, m: int, n: int, f0: int
) -> None:
    with pytest.raises(ValueError):
        StreamConfig(m=m, n=n, f0=f0, distribution=distribution, seed=42)


@pytest.mark.parametrize("distribution", ["normal", None, 7])
def test_unknown_distribution_is_rejected(distribution: object) -> None:
    with pytest.raises(ValueError, match="distribution must be one of"):
        StreamConfig(m=10, n=10, f0=5, distribution=distribution, seed=42)  # type: ignore[arg-type]


def test_ids_are_representable_as_unsigned_64_bit_values() -> None:
    config = StreamConfig(
        m=4,
        n=UINT64_MAX + 1,
        f0=1,
        distribution=Distribution.ALL_DUPLICATE,
        seed=42,
    )

    assert all(0 <= value <= UINT64_MAX for value in generate_stream(config))


def test_f0_one_degenerates_to_one_id_for_weighted_distributions() -> None:
    for distribution in (Distribution.UNIFORM, Distribution.SKEWED, Distribution.ZIPF):
        stream = list(
            generate_stream(
                StreamConfig(
                    m=20,
                    n=20,
                    f0=1,
                    distribution=distribution,
                    seed=42,
                )
            )
        )
        assert len(set(stream)) == 1
