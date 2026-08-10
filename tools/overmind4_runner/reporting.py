from __future__ import annotations

from dataclasses import asdict
import json

from .parsing import Outcome


def report_document(
    outcome: Outcome,
    run_id: str,
    *,
    completed_at: str | None = None,
    artifacts_present: dict[str, bool] | None = None,
) -> dict[str, object]:
    document = asdict(outcome)
    document.pop("json_stats", None)
    report = {
        "schema_version": 1,
        "run_id": run_id,
        **document,
        "json_stats": outcome.json_stats,
    }
    if completed_at is not None:
        report["completed_at"] = completed_at
    if artifacts_present is not None:
        report["artifacts_present"] = artifacts_present
    return report


def render_json(
    outcome: Outcome,
    run_id: str,
    *,
    completed_at: str | None = None,
    artifacts_present: dict[str, bool] | None = None,
) -> str:
    return json.dumps(
        report_document(
            outcome,
            run_id,
            completed_at=completed_at,
            artifacts_present=artifacts_present,
        ),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"


def _display(value: object, suffix: str = "") -> str:
    return "unknown" if value is None else f"{value}{suffix}"


def render_markdown(outcome: Outcome, run_id: str) -> str:
    achieved = (
        "unknown"
        if outcome.achieved_sim_speed is None
        else f"{outcome.achieved_sim_speed:.2f}x"
    )
    return "\n".join(
        (
            f"# Overmind4 run {run_id}",
            "",
            f"- Outcome: **{outcome.state.upper()}**",
            f"- Official result: {_display(outcome.official_result)}",
            f"- Simulation seconds: {_display(outcome.sim_seconds)}",
            f"- Wall seconds: {outcome.wall_seconds:.3f}",
            f"- Achieved simulation speed: {achieved}",
            f"- Exit code: {_display(outcome.exit_code)}",
            f"- Failure reason: {_display(outcome.failure_reason)}",
            "",
        )
    )
