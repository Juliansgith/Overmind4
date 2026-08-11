from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

from .parsing import LogTelemetry, OperationEvent, Outcome


_ABSOLUTE_FLOORS: dict[int, dict[str, float]] = {
    5: {
        "engineers_alive": 6,
        "mex_alive": 8,
        "mass_reclaim": 250,
        "factories": 3,
        "combat_units": 12,
        "mex_survival": 0.90,
        "mass_income": 6,
        "mass_spent": 1000,
        "air_total": 3,
        "air_factory_t1": 1,
    },
    10: {
        "engineers_alive": 10,
        "mex_alive": 14,
        "mass_reclaim": 1000,
        "factories": 5,
        "combat_units": 35,
        "mex_survival": 0.85,
        "mass_income": 12,
        "mass_spent": 4000,
        "air_total": 5,
        "air_interceptor": 4,
        "mass_utilization": 0.75,
    },
    15: {
        "engineers_alive": 16,
        "mex_alive": 18,
        "mass_reclaim": 3000,
        "factories": 7,
        "combat_units": 75,
        "mex_survival": 0.80,
        "mass_income": 20,
        "mass_spent": 9000,
        "air_total": 18,
        "mobile_t2": 12,
        "mex_t2": 4,
        "mass_utilization": 0.85,
    },
    20: {
        "engineers_alive": 22,
        "mex_alive": 22,
        "mass_reclaim": 6000,
        "factories": 9,
        "combat_units": 120,
        "mex_survival": 0.75,
        "mass_income": 28,
        "mass_spent": 16000,
        "air_total": 30,
        "land_factory_t2": 2,
        "air_factory_t1": 2,
        "mass_utilization": 0.85,
    },
}

_RELATIVE_RATIOS: dict[int, dict[str, float]] = {
    5: {
        "mass_income": 0.60,
        "mass_spent": 0.55,
        "engineers_alive": 0.65,
        "factories": 0.65,
        "mex_alive": 0.75,
        "mass_reclaim": 0.40,
    },
    10: {
        "mass_income": 0.70,
        "mass_spent": 0.65,
        "engineers_alive": 0.70,
        "factories": 0.70,
        "mex_alive": 0.80,
        "mass_reclaim": 0.50,
    },
    15: {
        "mass_income": 0.80,
        "mass_spent": 0.75,
        "engineers_alive": 0.75,
        "factories": 0.75,
        "mex_alive": 0.85,
        "mass_reclaim": 0.65,
    },
    20: {
        "mass_income": 0.85,
        "mass_spent": 0.80,
        "engineers_alive": 0.80,
        "factories": 0.80,
        "mex_alive": 0.85,
        "mass_reclaim": 0.70,
    },
}

_FACTORY_FIELDS = (
    "land_factory_t1",
    "land_factory_t2",
    "land_factory_t3",
    "air_factory_t1",
    "air_factory_t2",
    "air_factory_t3",
)
_COMBAT_FIELDS = (
    "army_count_home",
    "army_count_garrison",
    "army_count_field",
    "army_count_response",
    "army_count_raider",
    "army_count_unassigned",
)
_AIR_FIELDS = (
    "air_scout",
    "air_interceptor",
    "air_bomber",
    "air_transport",
    "air_other",
)


def _first_operation_tick(
    events: tuple[OperationEvent, ...], operation: str, phase: str
) -> int | None:
    ticks = [
        event.tick
        for event in events
        if event.operation == operation and event.phase == phase
    ]
    return min(ticks) if ticks else None


def _derived_metrics(metrics: dict[str, int | float]) -> dict[str, float | int]:
    derived: dict[str, float | int] = dict(metrics)
    derived["mex_alive"] = sum(
        float(metrics[name]) for name in ("mex_t1", "mex_t2", "mex_t3")
    )
    derived["factories"] = sum(float(metrics[name]) for name in _FACTORY_FIELDS)
    derived["combat_units"] = sum(float(metrics[name]) for name in _COMBAT_FIELDS)
    derived["air_total"] = sum(float(metrics[name]) for name in _AIR_FIELDS)
    mass_accounted = float(metrics["mass_spent"]) + float(metrics["mass_excess"])
    derived["mass_utilization"] = (
        float(metrics["mass_spent"]) / mass_accounted if mass_accounted > 0 else 0
    )
    built = float(metrics["engineers_built"])
    derived["engineer_attrition"] = (
        float(metrics["engineers_lost"]) / built if built > 0 else 0
    )
    for integral in ("mex_alive", "factories", "combat_units", "air_total"):
        value = float(derived[integral])
        if value.is_integer():
            derived[integral] = int(value)
    return derived


def evaluate_parity(
    telemetry: LogTelemetry,
    *,
    our_army: int,
    opponent_army: int,
    map_size_km: int | float,
    official_result: str | None,
    operational_failure: str | None = None,
    seed: int | None = None,
    spawn: str | None = None,
    benchmark_config: str | None = None,
) -> dict[str, Any]:
    """Evaluate one observer-only match against the fixed parity contract."""

    integrity_failure = (
        operational_failure
        or telemetry.benchmark_integrity_reason
        or telemetry.operation_integrity_reason
        or (None if telemetry.benchmark_checkpoints else "missing-benchmark-stream")
    )
    result_kind = (official_result or "").strip().lower().split(" ", 1)[0]
    result: dict[str, Any] = {
        "classification": "operational-reject" if integrity_failure else "pending",
        "keep": False,
        "matchEligible": False,
        "promotable": False,
        "failures": [integrity_failure] if integrity_failure else [],
        "derived": {},
        "mapSizeKm": map_size_km,
        "seed": seed,
        "spawn": spawn,
        "benchmarkConfig": benchmark_config,
        "officialResult": official_result,
    }
    if integrity_failure:
        return result

    by_key = {
        (checkpoint.tick, checkpoint.army): checkpoint.metrics
        for checkpoint in telemetry.benchmark_checkpoints
    }
    failures: list[str] = []
    for minutes in sorted(_ABSOLUTE_FLOORS):
        tick = minutes * 600
        ours_raw = by_key.get((tick, our_army))
        opponent_raw = by_key.get((tick, opponent_army))
        if ours_raw is None and opponent_raw is None:
            failures.append(f"{minutes}m:checkpoint:missing")
            continue
        if ours_raw is None or opponent_raw is None:
            failures.append(f"{minutes}m:checkpoint:missing")
            continue
        ours = _derived_metrics(ours_raw)
        opponent = _derived_metrics(opponent_raw)
        ours["t2_hq_started_tick"] = _first_operation_tick(
            telemetry.operation_events, "tech:t2_hq", "ordered"
        )
        ours["t3_admitted"] = (
            _first_operation_tick(telemetry.operation_events, "tech:t3", "admitted")
            is not None
        )
        result["derived"][f"{minutes}m"] = ours

        for metric, floor in _ABSOLUTE_FLOORS[minutes].items():
            if float(ours.get(metric, 0)) < floor:
                failures.append(f"{minutes}m:{metric}:absolute")
        for metric, ratio in _RELATIVE_RATIOS[minutes].items():
            if float(ours[metric]) < float(opponent[metric]) * ratio:
                failures.append(f"{minutes}m:{metric}:relative")

        if minutes == 10:
            t2_tick = ours["t2_hq_started_tick"]
            if t2_tick is None or int(t2_tick) > 5700:
                failures.append("10m:t2_hq_started_tick:absolute")
        if minutes == 20:
            if not ours["t3_admitted"]:
                failures.append("20m:t3_admitted:absolute")
            if float(ours["factory_full_bank_idle_ticks"]) > 600:
                failures.append("20m:factory_full_bank_idle_ticks:absolute")
            if float(ours["engineer_attrition"]) > 0.40:
                failures.append("20m:engineer_attrition:absolute")

    result["failures"] = list(dict.fromkeys(failures))
    macro_pass = not result["failures"]
    if macro_pass and result_kind == "victory":
        result.update(
            classification="macro-parity-win", keep=True, matchEligible=True
        )
    elif macro_pass:
        result.update(classification="combat-loss-macro-parity", keep=True)
    elif result_kind == "victory":
        result["classification"] = "tactical-win-macro-fail"
    else:
        result["classification"] = "macro-fail"
    return result


def evaluate_promotion(matches: list[dict[str, Any]]) -> dict[str, Any]:
    required_keys = {
        (size, spawn, seed)
        for size in (5, 10, 20, 40)
        for spawn, seed in (("normal", 7777), ("swapped", 7778))
    }
    seen: set[tuple[object, object, object]] = set()
    failures: list[str] = []
    passed = 0
    benchmark_configs = {match.get("benchmarkConfig") for match in matches}
    if len(benchmark_configs) > 1:
        failures.append("mixed-benchmark-config")
    for match in matches:
        key = (match.get("mapSizeKm"), match.get("spawn"), match.get("seed"))
        if key in seen:
            failures.append(f"duplicate-match:{key[0]}:{key[1]}:{key[2]}")
        seen.add(key)
        if key not in required_keys:
            failures.append(f"unexpected-match:{key[0]}:{key[1]}:{key[2]}")
        elif match.get("matchEligible") is True:
            passed += 1
        else:
            failures.append(f"ineligible-match:{key[0]}:{key[1]}:{key[2]}")
    for size, spawn, seed in sorted(required_keys - seen):
        failures.append(f"missing-match:{size}:{spawn}:{seed}")
    promotable = not failures and len(matches) == len(required_keys) and passed == 8
    return {
        "promotable": promotable,
        "passed": passed,
        "required": 8,
        "maps": [5, 10, 20, 40],
        "failures": failures,
    }


def report_document(
    outcome: Outcome,
    run_id: str,
    *,
    completed_at: str | None = None,
    artifacts_present: dict[str, bool] | None = None,
    parity_result: dict[str, Any] | None = None,
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
    if parity_result is not None:
        report["parity"] = parity_result
    return report


def render_json(
    outcome: Outcome,
    run_id: str,
    *,
    completed_at: str | None = None,
    artifacts_present: dict[str, bool] | None = None,
    parity_result: dict[str, Any] | None = None,
) -> str:
    return json.dumps(
        report_document(
            outcome,
            run_id,
            completed_at=completed_at,
            artifacts_present=artifacts_present,
            parity_result=parity_result,
        ),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"


def _display(value: object, suffix: str = "") -> str:
    return "unknown" if value is None else f"{value}{suffix}"


def render_markdown(
    outcome: Outcome,
    run_id: str,
    *,
    parity_result: dict[str, Any] | None = None,
) -> str:
    achieved = (
        "unknown"
        if outcome.achieved_sim_speed is None
        else f"{outcome.achieved_sim_speed:.2f}x"
    )
    lines = [
            f"# Overmind4 run {run_id}",
            "",
            f"- Outcome: **{outcome.state.upper()}**",
            f"- Official result: {_display(outcome.official_result)}",
            f"- Simulation seconds: {_display(outcome.sim_seconds)}",
            f"- Wall seconds: {outcome.wall_seconds:.3f}",
            f"- Achieved simulation speed: {achieved}",
            f"- Exit code: {_display(outcome.exit_code)}",
            f"- Failure reason: {_display(outcome.failure_reason)}",
            f"- Warnings: {', '.join(outcome.warnings) if outcome.warnings else 'none'}",
    ]
    if parity_result is not None:
        lines.extend(
            (
                f"- Parity: **{parity_result.get('classification', 'unknown')}**",
                f"- Parity failures: {', '.join(parity_result.get('failures', [])) or 'none'}",
            )
        )
    lines.append("")
    return "\n".join(lines)
