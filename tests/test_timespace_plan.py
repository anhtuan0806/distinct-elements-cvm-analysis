import json
import os
import subprocess
import sys

from scripts.generate_timespace_plan import DEFAULT_PLAN, generate_plan, runner_args, write_plan
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
