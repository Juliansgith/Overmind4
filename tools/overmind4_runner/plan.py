from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .model import RunConfig, ValidationError, validate_identifier


@dataclass(frozen=True)
class ArtifactPaths:
    run_dir: Path
    log_path: Path
    replay_path: Path
    prefs_path: Path
    prefs_filename: str
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
            prefs_path=run_dir / "overmind4.prefs",
            prefs_filename=f"Overmind4-{run_id}.prefs",
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
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", artifacts.prefs_filename):
        raise ValidationError("prefs filename must be a safe leaf filename")
    ai_wire = ",".join(spec.wire for spec in config.ai_specs)
    return [
        str(executable),
        "/nobugreport",
        "/nosound",
        "/exitongameover",
        "/init",
        str(generated_init),
        "/prefs",
        artifacts.prefs_filename,
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
        "/unitcap",
        str(config.unit_cap),
        "/aitest",
        ai_wire,
        "/om4runid",
        run_id,
    ]
