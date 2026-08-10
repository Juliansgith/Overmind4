from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import RunConfig, validate_identifier


@dataclass(frozen=True)
class ArtifactPaths:
    run_dir: Path
    log_path: Path
    replay_path: Path
    manifest_path: Path
    report_json_path: Path
    report_markdown_path: Path

    @classmethod
    def for_run(cls, output_root: Path, run_id: str) -> "ArtifactPaths":
        validate_identifier(run_id, "run ID")
        run_dir = output_root / run_id
        return cls(
            run_dir=run_dir,
            log_path=run_dir / "game.log",
            replay_path=run_dir / "game.scfareplay",
            manifest_path=run_dir / "manifest.json",
            report_json_path=run_dir / "report.json",
            report_markdown_path=run_dir / "report.md",
        )


def build_argv(
    executable: Path,
    generated_init: Path,
    config: RunConfig,
    artifacts: ArtifactPaths,
    run_id: str,
) -> list[str]:
    validate_identifier(run_id, "run ID")
    ai_wire = ",".join(spec.wire for spec in config.ai_specs)
    return [
        str(executable),
        "/nobugreport",
        "/nosound",
        "/exitongameover",
        "/init",
        str(generated_init),
        "/map",
        config.map_id,
        "/log",
        str(artifacts.log_path),
        "/savereplay",
        str(artifacts.replay_path),
        "/seed",
        str(config.seed),
        "/speed",
        str(config.speed),
        "/maxtime",
        str(config.sim_time_limit),
        "/aitest",
        ai_wire,
        "/om4runid",
        run_id,
    ]

