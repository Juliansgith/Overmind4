from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Sequence

from .model import RunConfig, ValidationError
from .runner import Runner


@dataclass(frozen=True)
class CliOptions:
    config: RunConfig
    output_dir: Path
    dry_run: bool


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one pinned FAF 3836 Overmind4 AI match"
    )
    parser.add_argument("--map", default="SCMP_007")
    parser.add_argument("--seed", type=int, default=7777)
    parser.add_argument("--speed", type=int, default=25)
    parser.add_argument("--sim-time", type=int, default=1800)
    parser.add_argument("--wall-time", type=int, default=300)
    parser.add_argument("--our-ai", default="overmind4")
    parser.add_argument("--opponent-ai", default="easy")
    parser.add_argument("--our-faction", type=int, default=1)
    parser.add_argument("--opponent-faction", type=int, default=1)
    parser.add_argument("--our-slot", type=int, default=1)
    parser.add_argument("--opponent-slot", type=int, default=2)
    parser.add_argument("--our-team", type=int, default=1)
    parser.add_argument("--opponent-team", type=int, default=2)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/runs"))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def parse_cli(argv: Sequence[str]) -> CliOptions:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        config = RunConfig(
            map_id=args.map,
            seed=args.seed,
            speed=args.speed,
            sim_time_limit=args.sim_time,
            wall_time_limit=args.wall_time,
            our_ai=args.our_ai,
            opponent_ai=args.opponent_ai,
            our_faction=args.our_faction,
            opponent_faction=args.opponent_faction,
            our_slot=args.our_slot,
            opponent_slot=args.opponent_slot,
            our_team=args.our_team,
            opponent_team=args.opponent_team,
        )
    except ValidationError as error:
        parser.error(str(error))
    return CliOptions(config=config, output_dir=args.output_dir, dry_run=args.dry_run)


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_cli(sys.argv[1:] if argv is None else argv)
    repository = Path(__file__).resolve().parents[2]
    try:
        result = Runner(repository).run(
            options.config,
            options.output_dir,
            dry_run=options.dry_run,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Overmind4 runner refused to launch: {error}", file=sys.stderr)
        return 2
    if result.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "run_id": result.run_id,
                    "argv": result.argv,
                    "artifact_directory": str(result.paths.run_dir),
                },
                indent=2,
            )
        )
        return 0
    assert result.outcome is not None
    print(f"{result.outcome.state}: {result.paths.report_markdown_path}")
    return 0 if result.outcome.state in {"win", "loss", "draw", "sim-timeout"} else 1

