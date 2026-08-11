from __future__ import annotations

import copy
from dataclasses import asdict, fields, is_dataclass
import json
import math
from pathlib import Path
from typing import Any

import pytest

from conftest import ROOT
from tools.overmind4_runner import parsing, reporting


RUN_ID = "parity-run"
REQUIRED_METRICS = {
    "mass_income",
    "energy_income",
    "mass_spent",
    "energy_spent",
    "mass_reclaim",
    "energy_reclaim",
    "mass_stored",
    "energy_stored",
    "mass_excess",
    "energy_excess",
    "engineers_alive",
    "engineers_built",
    "engineers_lost",
    "mex_t1",
    "mex_t2",
    "mex_t3",
    "mex_built",
    "mex_lost",
    "mex_rebuilt",
    "mex_survival",
    "land_factory_t1",
    "land_factory_t2",
    "land_factory_t3",
    "air_factory_t1",
    "air_factory_t2",
    "air_factory_t3",
    "factory_idle",
    "factory_utilization",
    "air_scout",
    "air_interceptor",
    "air_bomber",
    "air_transport",
    "mobile_t2",
    "mobile_t3",
    "army_count_home",
    "army_count_garrison",
    "army_count_field",
    "army_count_response",
    "army_count_unassigned",
    "army_mass_home",
    "army_mass_garrison",
    "army_mass_field",
    "army_mass_response",
    "army_mass_unassigned",
    "mass_killed",
    "mass_lost",
}


def metric_values(**updates: float | int) -> dict[str, float | int]:
    values: dict[str, float | int] = {name: 0 for name in REQUIRED_METRICS}
    values.update(
        {
            "mass_income": 10,
            "energy_income": 200,
            "mass_spent": 1000,
            "energy_spent": 10000,
            "mass_reclaim": 500,
            "energy_reclaim": 100,
            "mass_stored": 200,
            "energy_stored": 4000,
            "engineers_alive": 10,
            "engineers_built": 12,
            "engineers_lost": 2,
            "mex_t1": 12,
            "mex_built": 14,
            "mex_lost": 2,
            "mex_rebuilt": 1,
            "mex_survival": 0.9,
            "land_factory_t1": 3,
            "air_factory_t1": 1,
            "factory_utilization": 0.85,
            "air_scout": 1,
            "air_interceptor": 4,
            "army_count_home": 10,
            "army_count_garrison": 4,
            "army_count_field": 15,
            "army_count_response": 5,
            "army_mass_home": 500,
            "army_mass_garrison": 200,
            "army_mass_field": 900,
            "army_mass_response": 300,
            "mass_killed": 2500,
            "mass_lost": 1800,
        }
    )
    values.update(updates)
    return values


def benchmark_line(tick: int, army: int, **updates: float | int) -> str:
    values = metric_values(**updates)
    fields_text = "|".join(f"{key}={values[key]}" for key in sorted(values))
    return (
        f"OM4BENCH|v=1|kind=checkpoint|run={RUN_ID}|tick={tick}|army={army}|"
        f"{fields_text}"
    )


def operation_line(
    tick: int,
    operation: str,
    phase: str,
    **fields_: str | int | float,
) -> str:
    suffix = "".join(f"|{key}={value}" for key, value in sorted(fields_.items()))
    return (
        f"OM4|v=1|kind=operation|army=1|tick={tick}|operation={operation}"
        f"|phase={phase}{suffix}"
    )


def checkpoint_plain(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return dict(value.__dict__)


def event_plain(value: Any) -> dict[str, Any]:
    return checkpoint_plain(value)


TELEMETRY_FIELDS = {field.name for field in fields(parsing.LogTelemetry)}
BENCHMARK_SCHEMA_READY = {
    "benchmark_checkpoints",
    "benchmark_integrity_reason",
    "operation_events",
    "operation_integrity_reason",
} <= TELEMETRY_FIELDS
PARITY_API_READY = callable(getattr(reporting, "evaluate_parity", None))


def test_log_telemetry_has_observer_checkpoint_and_causal_operation_contract() -> None:
    assert {
        "benchmark_checkpoints",
        "benchmark_integrity_reason",
        "operation_events",
        "operation_integrity_reason",
    } <= TELEMETRY_FIELDS


def test_autorun_installs_separate_observer_only_300_tick_benchmark_stream() -> None:
    launch_path = ROOT / "tools" / "autorun" / "schook" / "lua" / "SinglePlayerLaunch.lua"
    observer_path = ROOT / "tools" / "autorun" / "schook" / "lua" / "Overmind4Benchmark.lua"
    launch = launch_path.read_text(encoding="utf-8")

    assert observer_path.is_file()
    assert "Overmind4Benchmark.lua" in launch
    observer = observer_path.read_text(encoding="utf-8")
    assert "OM4BENCH" in observer
    assert "CHECKPOINT_TICKS = 300" in observer
    assert "Controller" not in observer
    assert "Policy" not in observer


@pytest.mark.skipif(not BENCHMARK_SCHEMA_READY, reason="benchmark parser RED schema missing")
class TestBenchmarkParsing:
    def test_parser_collects_both_armies_at_each_checkpoint_in_tick_army_order(self) -> None:
        text = "\n".join(
            [
                benchmark_line(600, 2, mass_income=20),
                benchmark_line(300, 2, mass_income=16),
                benchmark_line(600, 1, mass_income=12),
                benchmark_line(300, 1, mass_income=10),
            ]
        )

        telemetry = parsing.parse_log(text, RUN_ID, our_slot=1)
        checkpoints = [checkpoint_plain(item) for item in telemetry.benchmark_checkpoints]

        assert [(item["tick"], item["army"]) for item in checkpoints] == [
            (300, 1),
            (300, 2),
            (600, 1),
            (600, 2),
        ]
        assert checkpoints[-1]["metrics"]["mass_income"] == 20
        assert telemetry.benchmark_integrity_reason is None

    def test_checkpoint_requires_the_complete_nonnegative_metric_schema(self) -> None:
        telemetry = parsing.parse_log(
            "\n".join([benchmark_line(300, 1), benchmark_line(300, 2)]),
            RUN_ID,
            our_slot=1,
        )

        checkpoints = [checkpoint_plain(item) for item in telemetry.benchmark_checkpoints]
        assert len(checkpoints) == 2
        for checkpoint in checkpoints:
            assert set(checkpoint["metrics"]) == REQUIRED_METRICS
            assert all(
                isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
                for value in checkpoint["metrics"].values()
            )

    def test_missing_army_duplicate_and_out_of_order_checkpoints_fail_closed(self) -> None:
        cases = {
            "missing": "\n".join([benchmark_line(300, 1)]),
            "duplicate": "\n".join(
                [
                    benchmark_line(300, 1),
                    benchmark_line(300, 1),
                    benchmark_line(300, 2),
                ]
            ),
            "out_of_order": "\n".join(
                [
                    benchmark_line(600, 1),
                    benchmark_line(600, 2),
                    benchmark_line(300, 1),
                    benchmark_line(300, 2),
                ]
            ),
        }

        for expected, text in cases.items():
            telemetry = parsing.parse_log(text, RUN_ID, our_slot=1)
            assert telemetry.benchmark_integrity_reason is not None, expected
            assert expected.replace("_", "-") in telemetry.benchmark_integrity_reason

    def test_300_tick_cadence_detects_a_missing_middle_checkpoint(self) -> None:
        text = "\n".join(
            [
                benchmark_line(300, 1),
                benchmark_line(300, 2),
                benchmark_line(900, 1),
                benchmark_line(900, 2),
            ]
        )

        telemetry = parsing.parse_log(text, RUN_ID, our_slot=1)

        assert telemetry.benchmark_integrity_reason == "missing-benchmark-tick:600"

    def test_malformed_nonfinite_negative_or_wrong_run_checkpoint_is_not_accepted(self) -> None:
        valid_army_two = benchmark_line(300, 2)
        malformed_lines = (
            benchmark_line(300, 1).replace("mass_income=10", "mass_income=nan"),
            benchmark_line(300, 1).replace("mass_income=10", "mass_income=-1"),
            benchmark_line(300, 1).replace("mass_income=10", "mass_income=bad"),
            benchmark_line(300, 1).replace(f"run={RUN_ID}", "run=other"),
        )

        for malformed in malformed_lines:
            telemetry = parsing.parse_log(
                malformed + "\n" + valid_army_two, RUN_ID, our_slot=1
            )
            assert len(telemetry.benchmark_checkpoints) < 2
            assert telemetry.benchmark_integrity_reason is not None

    def test_operation_parser_retains_complete_success_lifecycle_and_timing_fields(self) -> None:
        phases = (
            "opportunity",
            "selected",
            "admitted",
            "ordered",
            "travelling",
            "progressing",
            "completed",
            "survived",
        )
        text = "\n".join(
            operation_line(
                100 + index * 10,
                "mex:region-a:site-1",
                phase,
                site="site-1",
                scout_coverage_age=300,
                radar_coverage_age=40,
                transport_pickup_ticks=80,
                transport_drop_ticks=120,
                response_ticks=25,
            )
            for index, phase in enumerate(phases)
        )

        telemetry = parsing.parse_log(text, RUN_ID, our_slot=1)
        events = [event_plain(item) for item in telemetry.operation_events]

        assert [event["phase"] for event in events] == list(phases)
        assert events[-1]["fields"]["scout_coverage_age"] == 300
        assert events[-1]["fields"]["radar_coverage_age"] == 40
        assert events[-1]["fields"]["transport_pickup_ticks"] == 80
        assert events[-1]["fields"]["transport_drop_ticks"] == 120
        assert events[-1]["fields"]["response_ticks"] == 25
        assert telemetry.operation_integrity_reason is None

    def test_denied_rejected_and_lost_are_valid_terminal_causal_branches(self) -> None:
        branches = (
            ("denied", ["opportunity", "selected", "denied"]),
            ("rejected", ["opportunity", "selected", "admitted", "rejected"]),
            ("lost", ["opportunity", "selected", "admitted", "ordered", "completed", "lost"]),
        )

        for terminal, phases in branches:
            text = "\n".join(
                operation_line(100 + index * 10, f"op-{terminal}", phase)
                for index, phase in enumerate(phases)
            )
            telemetry = parsing.parse_log(text, RUN_ID, our_slot=1)
            assert telemetry.operation_integrity_reason is None, terminal
            assert event_plain(telemetry.operation_events[-1])["phase"] == terminal

    def test_impossible_operation_transition_fails_closed_without_reordering_history(self) -> None:
        text = "\n".join(
            [
                operation_line(100, "mex-1", "opportunity"),
                operation_line(110, "mex-1", "ordered"),
                operation_line(105, "mex-1", "selected"),
            ]
        )

        telemetry = parsing.parse_log(text, RUN_ID, our_slot=1)

        assert telemetry.operation_integrity_reason is not None
        assert [event_plain(item)["tick"] for item in telemetry.operation_events] == [
            100,
            110,
            105,
        ]


def test_reporting_exposes_a_public_parity_gate_api() -> None:
    assert callable(getattr(reporting, "evaluate_parity", None))


def parity_checkpoint(
    minutes: int,
    army: int,
    *,
    scale: float = 1,
    **updates: float | int,
) -> dict[str, Any]:
    floors = {
        5: {
            "engineers_alive": 6,
            "mex_alive": 8,
            "mass_reclaim": 250,
            "factories": 3,
            "combat_units": 12,
            "mex_survival": 0.90,
            "mass_income": 6,
            "mass_spent": 1000,
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
        },
    }
    metrics = {
        key: (value * scale if key != "mex_survival" else value)
        for key, value in floors[minutes].items()
    }
    metrics.update(
        {
            "air_scout": 1,
            "air_interceptor": 4 if minutes >= 10 else 2,
            "air_total": 30 if minutes >= 20 else (18 if minutes >= 15 else 6),
            "land_factory_t1": 3,
            "land_factory_t2": 2 if minutes >= 20 else (1 if minutes >= 15 else 0),
            "air_factory_t1": 2 if minutes >= 15 else 1,
            "mobile_t2": 35 if minutes >= 20 else (12 if minutes >= 15 else 0),
            "mex_t2": 8 if minutes >= 20 else (4 if minutes >= 15 else 0),
            "t3_admitted": 1 if minutes >= 20 else 0,
            "t2_hq_started_tick": 5700,
            "mass_utilization": 0.85 if minutes >= 15 else 0.75,
            "factory_full_bank_idle_ticks": 0,
            "engineer_attrition": 0.05,
        }
    )
    metrics.update(updates)
    return {"tick": minutes * 600, "army": army, "metrics": metrics}


def passing_parity_checkpoints() -> list[dict[str, Any]]:
    checkpoints = []
    for minutes in (5, 10, 15, 20):
        checkpoints.append(parity_checkpoint(minutes, 1))
        # Adaptive remains a meaningful reference, but the own-army absolute
        # Ian floors above remain the stricter gate in this passing fixture.
        checkpoints.append(parity_checkpoint(minutes, 2, scale=1.05))
    return checkpoints


@pytest.mark.skipif(not PARITY_API_READY, reason="parity reporting RED API missing")
class TestParityReporting:
    def test_ian_5_10_15_20_absolute_and_relative_floors_pass_together(self) -> None:
        result = reporting.evaluate_parity(
            passing_parity_checkpoints(),
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="victory",
            operational_failure=None,
        )

        assert result["failures"] == []
        assert result["classification"] == "macro-parity-win"
        assert result["keep"] is True
        assert result["promotable"] is True

    def test_one_absolute_or_relative_shortfall_names_exact_checkpoint_and_metric(self) -> None:
        absolute_cases = (
            (5, "engineers_alive", 5, "5m:engineers_alive:absolute"),
            (5, "factories", 2, "5m:factories:absolute"),
            (5, "air_factory_t1", 0, "5m:air_factory_t1:absolute"),
            (10, "mex_alive", 13, "10m:mex_alive:absolute"),
            (10, "mass_reclaim", 0, "10m:mass_reclaim:absolute"),
            (10, "air_interceptor", 3, "10m:air_interceptor:absolute"),
            (10, "t2_hq_started_tick", 5701, "10m:t2_hq_started_tick:absolute"),
            (15, "mobile_t2", 11, "15m:mobile_t2:absolute"),
            (15, "mex_t2", 3, "15m:mex_t2:absolute"),
            (15, "air_total", 17, "15m:air_total:absolute"),
            (15, "mass_utilization", 0.84, "15m:mass_utilization:absolute"),
            (20, "combat_units", 119, "20m:combat_units:absolute"),
            (20, "land_factory_t2", 1, "20m:land_factory_t2:absolute"),
            (20, "air_factory_t1", 1, "20m:air_factory_t1:absolute"),
            (20, "t3_admitted", 0, "20m:t3_admitted:absolute"),
            (20, "mex_survival", 0.64, "20m:mex_survival:absolute"),
            (
                20,
                "factory_full_bank_idle_ticks",
                601,
                "20m:factory_full_bank_idle_ticks:absolute",
            ),
            (20, "engineer_attrition", 0.41, "20m:engineer_attrition:absolute"),
        )
        for minutes, metric, value, expected in absolute_cases:
            checkpoints = copy.deepcopy(passing_parity_checkpoints())
            own = next(
                item
                for item in checkpoints
                if item["army"] == 1 and item["tick"] == minutes * 600
            )
            own["metrics"][metric] = value
            result = reporting.evaluate_parity(
                checkpoints,
                our_army=1,
                opponent_army=2,
                map_size_km=20,
                official_result="defeat",
            )
            assert expected in result["failures"], (metric, result)

        for metric in (
            "mass_income",
            "mass_spent",
            "engineers_alive",
            "factories",
            "mex_alive",
            "mass_reclaim",
        ):
            checkpoints = copy.deepcopy(passing_parity_checkpoints())
            own = next(
                item
                for item in checkpoints
                if item["army"] == 1 and item["tick"] == 9000
            )
            own["metrics"][metric] = 0
            result = reporting.evaluate_parity(
                checkpoints,
                our_army=1,
                opponent_army=2,
                map_size_km=20,
                official_result="defeat",
            )
            assert f"15m:{metric}:relative" in result["failures"], (
                metric,
                result,
            )

    def test_quick_tactical_win_without_macro_gates_is_not_a_parity_promotion(self) -> None:
        checkpoints = [
            parity_checkpoint(5, 1, scale=0.2),
            parity_checkpoint(5, 2, scale=1),
            parity_checkpoint(10, 1, scale=0.2),
            parity_checkpoint(10, 2, scale=1),
        ]

        result = reporting.evaluate_parity(
            checkpoints,
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="victory",
        )

        assert result["classification"] == "tactical-win-macro-fail"
        assert result["keep"] is False
        assert result["promotable"] is False

    def test_macro_parity_loss_is_kept_and_classified_as_combat_not_macro_failure(self) -> None:
        result = reporting.evaluate_parity(
            passing_parity_checkpoints(),
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="defeat",
        )

        assert result["classification"] == "combat-loss-macro-parity"
        assert result["keep"] is True
        assert result["promotable"] is False

    def test_operational_failure_or_missing_benchmark_integrity_is_a_hard_reject(self) -> None:
        for failure in ("lua-error", "desync", "missing-benchmark-tick:600"):
            result = reporting.evaluate_parity(
                passing_parity_checkpoints(),
                our_army=1,
                opponent_army=2,
                map_size_km=20,
                official_result="victory",
                operational_failure=failure,
            )
            assert result["classification"] == "operational-reject", failure
            assert result["keep"] is False, failure
            assert result["promotable"] is False, failure

    def test_json_report_contains_checkpoints_operations_and_parity_without_feeding_ai(self) -> None:
        text = "\n".join(
            [
                benchmark_line(300, 1),
                benchmark_line(300, 2),
                operation_line(100, "mex-1", "opportunity"),
                operation_line(110, "mex-1", "denied", reason="budget"),
            ]
        )
        telemetry = parsing.parse_log(text, RUN_ID, our_slot=1)
        outcome = parsing.classify_outcome(
            telemetry,
            parsing.ProcessObservation(exit_code=0, wall_seconds=2),
        )
        document = json.loads(reporting.render_json(outcome, RUN_ID))

        assert len(document["benchmark_checkpoints"]) == 2
        assert len(document["operation_events"]) == 2
        assert document["benchmark_checkpoints"][1]["army"] == 2
