import json
import os
import subprocess
import sys

import pytest

from scripts.generate_timespace_plan import (
    DEFAULT_PLAN,
    SCALE_PLAN,
    generate_plan,
    main,
    runner_args,
    validate_scale_rows,
    write_plan,
)
from src.cli import args_to_config, parse_args
from src.stream_generator import Distribution, StreamConfig


def test_plan_is_reproducible(tmp_path):
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    write_plan(first)
    write_plan(second)
    assert first.read_bytes() == second.read_bytes() == DEFAULT_PLAN.read_bytes()


def test_all_p0_configurations_match_real_runner_cli(tmp_path):
    p0 = [row for row in generate_plan() if row.priority == "P0"]
    assert len({row.m for row in p0}) >= 5
    assert len({row.workload for row in p0}) >= 3
    assert len({(row.n, row.epsilon, row.delta) for row in p0}) == 1
    for row in p0:
        args = parse_args(runner_args(row, tmp_path / "raw.csv"))
        cfg = args_to_config(args)
        StreamConfig(cfg.m, cfg.n, cfg.f0, Distribution(cfg.workload), cfg.seed_generator)
        assert not args.dry_run and args.trials >= 3
        assert cfg.s == row.s_reference
    assert any(row.f0 >= row.s_reference for row in p0)
    assert any(row.f0 < row.s_reference for row in p0)


def test_preview_round_trips_unicode_paths_on_ascii_stdout(tmp_path):
    raw = tmp_path / "kết quả.csv"
    preview = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.generate_timespace_plan",
            "--preview",
            "smoke",
            "--raw",
            str(raw),
        ],
        capture_output=True,
        encoding="ascii",
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
        check=False,
    )
    assert preview.returncode == 0, preview.stderr
    commands = [json.loads(line) for line in preview.stdout.splitlines()[1:]]
    assert len(commands) == 3
    assert all(command[command.index("--out") + 1] == str(raw.resolve()) for command in commands)


def test_scale_plan_is_reproducible_and_fits_runner_and_core_types(tmp_path):
    output = tmp_path / "scale.csv"
    write_plan(output, scale=True)
    assert output.read_bytes() == SCALE_PLAN.read_bytes()
    rows = list(generate_plan(scale=True))
    assert sorted({row.m for row in rows}) == [
        100_000,
        200_000,
        500_000,
        1_000_000,
        2_000_000,
        5_000_000,
        10_000_000,
        20_000_000,
        50_000_000,
        100_000_000,
    ]
    assert len(rows) == 30 and sum(row.trials for row in rows) == 270
    assert {(row.n, row.epsilon, row.delta) for row in rows} == {(100_000_000, 0.5, 0.05)}
    assert {(row.first_trial, row.seed_generator, row.seed_algorithm) for row in rows} == {
        (1, 44000, 84000)
    }
    for row in rows:
        config = args_to_config(parse_args(runner_args(row, tmp_path / "raw.csv")))
        StreamConfig(
            config.m, config.n, config.f0, Distribution(config.workload), config.seed_generator
        )
        assert config.s == row.s_reference
        assert (
            config.f0
            == {"all_duplicate": 1, "uniform": row.m // 4, "all_distinct": row.m}[row.workload]
        )
    assert max(row.s_reference for row in rows) == 1628


def test_scale_preview_selects_subset_and_real_run_requires_explicit_m(tmp_path, capsys):
    raw = tmp_path / "raw.csv"
    assert (
        main(["--preview", "SCALE", "--m", "200000", "--workload", "uniform", "--raw", str(raw)])
        == 0
    )
    heading, command = capsys.readouterr().out.splitlines()
    assert heading == "1 configurations, 9 real trials"
    args = json.loads(command)
    assert args[args.index("--m") + 1] == "200000"
    assert args[args.index("--workload") + 1] == "uniform"
    assert not raw.exists()
    with pytest.raises(SystemExit) as result:
        main(["--run", "SCALE", "--raw", str(raw)])
    assert result.value.code == 2 and "explicit --m" in capsys.readouterr().err
    assert not raw.exists()


def test_scale_resume_validates_configuration_and_seed():
    row = {
        "m": 100_000,
        "F0": 25_000,
        "workload": "uniform",
        "n": 100_000_000,
        "epsilon": 0.5,
        "delta": 0.05,
        "trial": 9,
        "seed_generator": 44008,
        "seed_algorithm": 84008,
    }
    validate_scale_rows([row])
    with pytest.raises(ValueError, match="seed schedule"):
        validate_scale_rows([dict(row, seed_generator=44009)])
    with pytest.raises(ValueError, match="outside the SCALE plan"):
        validate_scale_rows([dict(row, m=256)])
