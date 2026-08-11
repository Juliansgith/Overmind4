from __future__ import annotations

import copy
from dataclasses import asdict, fields, is_dataclass, replace
import json
import math
from pathlib import Path
import re
from typing import Any

import pytest

from adaptive_parity_helpers import lua_value, plain
from conftest import ROOT, runtime
from test_lua_hooks import _runtime as hook_runtime
from test_lua_hooks import _valid_args as hook_valid_args
from tools.overmind4_runner import parsing, reporting
from tools.overmind4_runner import runner as runner_module
from tools.overmind4_runner.model import RunConfig
from tools.overmind4_runner.runner import Runner
from test_process_and_runner import _deps as runner_dependencies


RUN_ID = "parity-run"
OBSERVER_PATH = (
    ROOT / "tools" / "autorun" / "schook" / "lua" / "Overmind4Benchmark.lua"
)
SIM_HOOK_PATH = ROOT / "tools" / "autorun" / "schook" / "lua" / "simInit.lua"
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
    "factory_full_bank_idle_ticks",
    "air_scout",
    "air_interceptor",
    "air_bomber",
    "air_transport",
    "air_other",
    "mobile_t2",
    "mobile_t3",
    "army_count_home",
    "army_count_garrison",
    "army_count_field",
    "army_count_response",
    "army_count_raider",
    "army_count_unassigned",
    "army_mass_home",
    "army_mass_garrison",
    "army_mass_field",
    "army_mass_response",
    "army_mass_raider",
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
            "factory_full_bank_idle_ticks": 0,
            "air_scout": 1,
            "air_interceptor": 4,
            "air_other": 1,
            "army_count_home": 10,
            "army_count_garrison": 4,
            "army_count_field": 15,
            "army_count_response": 5,
            "army_count_raider": 2,
            "army_mass_home": 500,
            "army_mass_garrison": 200,
            "army_mass_field": 900,
            "army_mass_response": 300,
            "army_mass_raider": 120,
            "mass_killed": 2500,
            "mass_lost": 1800,
        }
    )
    values.update(updates)
    return values


def benchmark_line(
    tick: int,
    army: int,
    *,
    run_id: str = RUN_ID,
    **updates: float | int,
) -> str:
    values = metric_values(**updates)
    fields_text = "|".join(f"{key}={values[key]}" for key in sorted(values))
    return (
        f"OM4BENCH|v=1|kind=checkpoint|run={run_id}|tick={tick}|army={army}|"
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
PROMOTION_API_READY = callable(getattr(reporting, "evaluate_promotion", None))


def test_log_telemetry_has_observer_checkpoint_and_causal_operation_contract() -> None:
    assert {
        "benchmark_checkpoints",
        "benchmark_integrity_reason",
        "operation_events",
        "operation_integrity_reason",
    } <= TELEMETRY_FIELDS


def test_autorun_installs_separate_observer_only_300_tick_benchmark_stream() -> None:
    launch_path = ROOT / "tools" / "autorun" / "schook" / "lua" / "SinglePlayerLaunch.lua"
    launch = launch_path.read_text(encoding="utf-8")

    assert OBSERVER_PATH.is_file()
    assert SIM_HOOK_PATH.is_file()
    sim_hook = SIM_HOOK_PATH.read_text(encoding="utf-8")
    assert "Overmind4Benchmark.lua" in sim_hook
    assert "Overmind4Benchmark.lua" not in launch
    assert "GetGameTick" not in launch
    assert "GetArmyBrain" not in launch
    observer = OBSERVER_PATH.read_text(encoding="utf-8")
    assert "OM4BENCH" in observer
    assert "CHECKPOINT_TICKS = 300" in observer
    assert "Overmind4Benchmark.SampleArmy" in observer
    assert "GetArmyBrain" in observer
    assert "Controller" not in observer
    assert "Policy" not in observer
    assert "OM4BenchmarkLatest" not in observer
    assert "Overmind4Benchmark.Create" in sim_hook
    assert "PreviousBeginSession" in sim_hook
    assert "Overmind4BenchmarkArmyOne" in launch
    assert "Overmind4BenchmarkArmyTwo" in launch
    for forbidden in (
        r"\bIssue[A-Za-z0-9_]*\b",
        r"\bCreateUnit\b",
        r"\bDestroyUnit\b",
        r"\bGiveResource\b",
        r"\bTakeResource\b",
        r"\bSetGameSpeed\b",
        r"\bSessionEndGame\b",
        r"\bWarp\b",
    ):
        assert re.search(forbidden, observer) is None, forbidden


def test_launch_hook_only_plumbs_nondefault_observer_slots_into_session_options() -> None:
    lua, _, launched = hook_runtime(
        hook_valid_args(**{"/aitest": "4:overmind4:1:1,2:adaptive:1:2"})
    )
    lua.execute(
        (ROOT / "tools" / "autorun" / "schook" / "lua" / "SinglePlayerLaunch.lua").read_text(
            encoding="utf-8"
        )
    )

    lua.globals().StartCommandLineSession("SCMP_007", False)

    options = launched[0].scenarioInfo.Options
    assert options.Overmind4BenchmarkRunId == "run-1"
    assert options.Overmind4BenchmarkArmyOne == 4
    assert options.Overmind4BenchmarkArmyTwo == 2


def _benchmark_lua_fixture(lua: Any) -> None:
    lua.execute(
        """
        categories = {
            ALLUNITS = 'ALLUNITS', ENGINEER = 'ENGINEER', COMMAND = 'COMMAND',
            MASSEXTRACTION = 'MASSEXTRACTION',
        }

        function MakeBenchmarkUnit(options)
            local unit = {
                options = options,
                Dead = options.dead == true,
                Overmind4Token = options.token,
            }
            function unit:BeenDestroyed() return self.options.destroyed == true end
            function unit:GetArmy() return self.options.army end
            function unit:GetEntityId() return self.options.entityId end
            function unit:GetFractionComplete() return self.options.fraction or 1 end
            function unit:GetPosition() return self.options.position end
            function unit:IsIdleState() return self.options.idle == true end
            function unit:GetBlueprint()
                return {
                    BlueprintId = self.options.blueprintId,
                    CategoriesHash = self.options.categories,
                    Economy = { BuildCostMass = self.options.mass or 0 },
                }
            end
            return unit
        end

        function MakeBenchmarkBrain(army)
            local brain = {
                Army = army,
                units = {},
                economy = {},
                armyStats = {},
                blueprintStats = {},
                Overmind4ForcePlan = { assignments = {} },
                Overmind4EntityGenerations = {},
                calls = {},
            }
            function brain:GetListOfUnits(category, incomplete, dead)
                table.insert(self.calls, { method = 'GetListOfUnits', category = category })
                return self.units
            end
            function brain:GetEconomyIncome(resource)
                return self.economy[string.lower(resource) .. 'Income'] or 0
            end
            function brain:GetEconomyStored(resource)
                return self.economy[string.lower(resource) .. 'Stored'] or 0
            end
            function brain:GetEconomyStoredRatio(resource)
                return self.economy[string.lower(resource) .. 'StoredRatio'] or 0
            end
            function brain:GetArmyStat(name, default)
                return { Value = self.armyStats[name] or default or 0 }
            end
            function brain:GetBlueprintStat(name, category)
                return self.blueprintStats[name .. ':' .. tostring(category)] or 0
            end
            return brain
        end
        """
    )


def _benchmark_unit(lua: Any, **options: Any) -> Any:
    options.setdefault("army", 1)
    options.setdefault("fraction", 1)
    options.setdefault("position", [0, 0, 0])
    options.setdefault("categories", {})
    return lua.globals().MakeBenchmarkUnit(lua_value(lua, options))


@pytest.mark.skipif(not OBSERVER_PATH.is_file(), reason="benchmark observer RED module missing")
def test_sample_army_computes_complete_stateful_metrics_from_mock_engine_brain() -> None:
    lua = runtime()
    _benchmark_lua_fixture(lua)
    lua.execute(OBSERVER_PATH.read_text(encoding="utf-8"))
    assert lua.globals().Overmind4Benchmark is not None

    emitted: list[str] = []
    lua.globals().observer_logger = emitted.append
    observer = lua.globals().Overmind4Benchmark.Create(
        RUN_ID, lua.table_from([1]), lua.globals().observer_logger
    )
    brain = lua.globals().MakeBenchmarkBrain(1)

    engineer = _benchmark_unit(
        lua,
        entityId=1,
        token="1:1",
        blueprintId="uel0105",
        categories={"ENGINEER": True, "MOBILE": True, "LAND": True, "TECH1": True},
        mass=52,
    )
    commander = _benchmark_unit(
        lua,
        entityId=2,
        token="2:1",
        blueprintId="uel0001",
        categories={"ENGINEER": True, "COMMAND": True, "MOBILE": True, "LAND": True},
        mass=1000,
    )
    mex_a = _benchmark_unit(
        lua,
        entityId=10,
        token="10:1",
        blueprintId="ueb1103",
        position=[20, 0, 20],
        categories={"MASSEXTRACTION": True, "STRUCTURE": True, "TECH1": True},
        mass=36,
    )
    mex_b_t1 = _benchmark_unit(
        lua,
        entityId=11,
        token="11:1",
        blueprintId="ueb1103",
        position=[40, 0, 40],
        categories={"MASSEXTRACTION": True, "STRUCTURE": True, "TECH1": True},
        mass=36,
    )
    land_factory = _benchmark_unit(
        lua,
        entityId=20,
        token="20:1",
        blueprintId="ueb0101",
        categories={"FACTORY": True, "STRUCTURE": True, "LAND": True, "TECH1": True},
        idle=True,
        mass=210,
    )
    air_factory = _benchmark_unit(
        lua,
        entityId=21,
        token="21:1",
        blueprintId="ueb0102",
        categories={"FACTORY": True, "STRUCTURE": True, "AIR": True, "TECH1": True},
        idle=False,
        mass=210,
    )
    air_units = [
        _benchmark_unit(
            lua,
            entityId=30 + index,
            token=f"{30 + index}:1",
            blueprintId=blueprint,
            categories={"AIR": True, "MOBILE": True, category: True, "TECH1": True},
            mass=mass,
        )
        for index, (blueprint, category, mass) in enumerate(
            (
                ("uea0101", "SCOUT", 40),
                ("uea0102", "ANTIAIR", 50),
                ("uea0103", "BOMBER", 60),
                ("uea0107", "TRANSPORTATION", 100),
                ("uea0203", "GROUNDATTACK", 240),
            )
        )
    ]
    bucket_units = []
    buckets = ("home", "garrison", "field", "response", "raider", "unassigned")
    for index, bucket in enumerate(buckets):
        entity_id = 100 + index
        tier = "TECH3" if bucket == "field" else "TECH2"
        unit = _benchmark_unit(
            lua,
            entityId=entity_id,
            token=f"{entity_id}:1",
            blueprintId=f"uel9{index:03d}",
            categories={"MOBILE": True, "LAND": True, tier: True},
            mass=100 + index * 10,
        )
        bucket_units.append(unit)
        brain.Overmind4EntityGenerations[entity_id] = lua_value(
            lua, {"generation": 1}
        )
        brain.Overmind4EntityGenerations[entity_id].reference = unit
        if bucket != "unassigned":
            brain.Overmind4ForcePlan.assignments[bucket] = lua.table_from(
                [f"{entity_id}:1"]
            )

    brain.units = lua.table_from(
        [
            engineer,
            commander,
            mex_a,
            mex_b_t1,
            land_factory,
            air_factory,
            *air_units,
            *bucket_units,
        ]
    )
    brain.economy = lua_value(
        lua,
        {
            "massIncome": 1.2,
            "energyIncome": 20,
            "massStored": 500,
            "energyStored": 5000,
            "massStoredRatio": 1,
            "energyStoredRatio": 1,
        },
    )
    brain.armyStats = lua_value(
        lua,
        {
            "Economy_TotalConsumed_Mass": 1000,
            "Economy_TotalConsumed_Energy": 5000,
            "Economy_Reclaimed_Mass": 200,
            "Economy_Reclaimed_Energy": 300,
            "Economy_AccumExcess_Mass": 10,
            "Economy_AccumExcess_Energy": 20,
            "Enemies_MassValue_Destroyed": 400,
            "Units_MassValue_Lost": 250,
        },
    )
    brain.blueprintStats = lua_value(
        lua,
        {
            "Units_History:ENGINEER": 3,
            "Units_History:COMMAND": 1,
            "Units_Killed:ENGINEER": 0,
            "Units_Killed:COMMAND": 0,
            "Units_History:MASSEXTRACTION": 2,
            "Units_Killed:MASSEXTRACTION": 0,
        },
    )

    first = plain(
        lua.globals().Overmind4Benchmark.SampleArmy(observer, brain, 1, 300)
    )
    assert first["factory_full_bank_idle_ticks"] == 0
    assert first["mex_rebuilt"] == 0

    mex_b_t2 = _benchmark_unit(
        lua,
        entityId=12,
        token="12:1",
        blueprintId="ueb1202",
        position=[40, 0, 40],
        categories={"MASSEXTRACTION": True, "STRUCTURE": True, "TECH2": True},
        mass=900,
    )
    brain.units = lua.table_from(
        [engineer, commander, mex_b_t2, land_factory, air_factory, *air_units, *bucket_units]
    )
    brain.blueprintStats["Units_Killed:MASSEXTRACTION"] = 1
    second = plain(
        lua.globals().Overmind4Benchmark.SampleArmy(observer, brain, 1, 600)
    )
    assert second["mex_lost"] == 1
    assert second["mex_rebuilt"] == 0
    assert second["factory_full_bank_idle_ticks"] == 300

    rebuilt_mex_a = _benchmark_unit(
        lua,
        entityId=13,
        token="13:1",
        blueprintId="ueb1103",
        position=[20, 0, 20],
        categories={"MASSEXTRACTION": True, "STRUCTURE": True, "TECH1": True},
        mass=36,
    )
    land_factory.options.idle = False
    brain.units = lua.table_from(
        [engineer, commander, rebuilt_mex_a, mex_b_t2, land_factory, air_factory, *air_units, *bucket_units]
    )
    brain.economy.massIncome = 2.5
    brain.economy.energyIncome = 30
    brain.armyStats.Economy_TotalConsumed_Mass = 5000
    brain.armyStats.Economy_TotalConsumed_Energy = 25000
    brain.armyStats.Economy_Reclaimed_Mass = 600
    brain.armyStats.Economy_Reclaimed_Energy = 900
    brain.armyStats.Economy_AccumExcess_Mass = 50
    brain.armyStats.Economy_AccumExcess_Energy = 80
    brain.armyStats.Enemies_MassValue_Destroyed = 1200
    brain.armyStats.Units_MassValue_Lost = 700
    brain.blueprintStats["Units_History:ENGINEER"] = 4
    brain.blueprintStats["Units_Killed:ENGINEER"] = 1
    brain.blueprintStats["Units_History:MASSEXTRACTION"] = 3
    final = plain(
        lua.globals().Overmind4Benchmark.SampleArmy(observer, brain, 1, 900)
    )

    assert final == {
        **metric_values(),
        "mass_income": 25,
        "energy_income": 300,
        "mass_spent": 5000,
        "energy_spent": 25000,
        "mass_reclaim": 600,
        "energy_reclaim": 900,
        "mass_stored": 500,
        "energy_stored": 5000,
        "mass_excess": 50,
        "energy_excess": 80,
        "engineers_alive": 1,
        "engineers_built": 3,
        "engineers_lost": 1,
        "mex_t1": 1,
        "mex_t2": 1,
        "mex_t3": 0,
        "mex_built": 3,
        "mex_lost": 1,
        "mex_rebuilt": 1,
        "mex_survival": pytest.approx(2 / 3),
        "land_factory_t1": 1,
        "land_factory_t2": 0,
        "land_factory_t3": 0,
        "air_factory_t1": 1,
        "air_factory_t2": 0,
        "air_factory_t3": 0,
        "factory_idle": 0,
        "factory_utilization": 1,
        "factory_full_bank_idle_ticks": 300,
        "air_scout": 1,
        "air_interceptor": 1,
        "air_bomber": 1,
        "air_transport": 1,
        "air_other": 1,
        "mobile_t2": 5,
        "mobile_t3": 1,
        "army_count_home": 1,
        "army_count_garrison": 1,
        "army_count_field": 1,
        "army_count_response": 1,
        "army_count_raider": 1,
        "army_count_unassigned": 1,
        "army_mass_home": 100,
        "army_mass_garrison": 110,
        "army_mass_field": 120,
        "army_mass_response": 130,
        "army_mass_raider": 140,
        "army_mass_unassigned": 150,
        "mass_killed": 1200,
        "mass_lost": 700,
    }


@pytest.mark.skipif(not OBSERVER_PATH.is_file(), reason="benchmark observer RED module missing")
def test_step_resolves_both_actual_army_brains_samples_and_never_duplicates_tick() -> None:
    lua = runtime()
    _benchmark_lua_fixture(lua)
    lua.execute(OBSERVER_PATH.read_text(encoding="utf-8"))
    emitted: list[str] = []
    reads: list[int] = []
    brains = {}
    for army, income in ((4, 1.5), (2, 2.5)):
        brain = lua.globals().MakeBenchmarkBrain(army)
        brain.economy = lua_value(
            lua,
            {
                "massIncome": income,
                "energyIncome": 10,
                "massStored": 0,
                "energyStored": 0,
                "massStoredRatio": 0,
                "energyStoredRatio": 0,
            },
        )
        brains[army] = brain

    def get_army_brain(army: int) -> Any:
        reads.append(army)
        return brains[army]

    lua.globals().GetArmyBrain = get_army_brain
    lua.globals().observer_logger = emitted.append
    observer = lua.globals().Overmind4Benchmark.Create(
        RUN_ID, lua.table_from([4, 2]), lua.globals().observer_logger
    )

    lua.globals().Overmind4Benchmark.Step(observer, 299)
    assert emitted == []
    assert reads == []
    lua.globals().Overmind4Benchmark.Step(observer, 300)
    lua.globals().Overmind4Benchmark.Step(observer, 300)

    assert reads == [4, 2]
    assert len(emitted) == 2
    assert "|tick=300|army=4|" in emitted[0]
    assert "|mass_income=15" in emitted[0]
    assert "|tick=300|army=2|" in emitted[1]
    assert "|mass_income=25" in emitted[1]


@pytest.mark.skipif(not OBSERVER_PATH.is_file(), reason="benchmark observer RED module missing")
def test_step_normalizes_late_scheduler_wakeups_to_the_due_300_tick_checkpoint() -> None:
    lua = runtime()
    _benchmark_lua_fixture(lua)
    lua.execute(OBSERVER_PATH.read_text(encoding="utf-8"))
    emitted: list[str] = []
    brain = lua.globals().MakeBenchmarkBrain(1)
    lua.globals().GetArmyBrain = lambda _: brain
    lua.globals().observer_logger = emitted.append
    observer = lua.globals().Overmind4Benchmark.Create(
        RUN_ID, lua.table_from([1]), lua.globals().observer_logger
    )

    lua.globals().Overmind4Benchmark.Step(observer, 329)
    lua.globals().Overmind4Benchmark.Step(observer, 359)
    lua.globals().Overmind4Benchmark.Step(observer, 601)

    assert [line.split("|tick=", 1)[1].split("|", 1)[0] for line in emitted] == [
        "300",
        "600",
    ]


@pytest.mark.skipif(not OBSERVER_PATH.is_file(), reason="benchmark observer RED module missing")
def test_overmind_force_metrics_fail_closed_when_public_snapshot_is_unavailable() -> None:
    lua = runtime()
    _benchmark_lua_fixture(lua)
    lua.execute(OBSERVER_PATH.read_text(encoding="utf-8"))
    emitted: list[str] = []
    observer = lua.globals().Overmind4Benchmark.Create(
        RUN_ID, lua.table_from([1]), emitted.append
    )
    brain = lua.globals().MakeBenchmarkBrain(1)
    brain.Overmind4 = True
    brain.Overmind4ForcePlan = None
    brain.Overmind4EntityGenerations = None

    lua.globals().Overmind4Benchmark.SampleArmy(observer, brain, 1, 300)

    assert any(
        "|kind=integrity|" in line
        and "|reason=force-plan-unavailable|" in line
        for line in emitted
    )


@pytest.mark.skipif(not OBSERVER_PATH.is_file(), reason="benchmark observer RED module missing")
@pytest.mark.parametrize(
    ("method", "replacement", "reason"),
    (
        ("GetEconomyIncome", "function() error('economy unavailable') end", "economy-api-failed"),
        ("GetEconomyStored", "function() return 'not-a-number' end", "economy-api-failed"),
        ("GetArmyStat", "function() error('stats unavailable') end", "army-stat-api-failed"),
        (
            "GetBlueprintStat",
            "function() error('blueprint stats unavailable') end",
            "blueprint-stat-api-failed",
        ),
        ("GetListOfUnits", "function() error('units unavailable') end", "unit-list-api-failed"),
        ("GetListOfUnits", "function() return nil end", "unit-list-api-failed"),
    ),
)
def test_required_observer_api_errors_emit_one_integrity_marker_and_keep_checkpoint_framing(
    method: str,
    replacement: str,
    reason: str,
) -> None:
    lua = runtime()
    _benchmark_lua_fixture(lua)
    lua.execute(OBSERVER_PATH.read_text(encoding="utf-8"))
    emitted: list[str] = []
    observer = lua.globals().Overmind4Benchmark.Create(
        RUN_ID, lua.table_from([1]), emitted.append
    )
    brain = lua.globals().MakeBenchmarkBrain(1)
    brain[method] = lua.eval(replacement)

    lua.globals().Overmind4Benchmark.SampleArmy(observer, brain, 1, 300)

    integrity = [line for line in emitted if "|kind=integrity|" in line]
    checkpoints = [line for line in emitted if "|kind=checkpoint|" in line]
    assert integrity == [
        f"OM4BENCH|v=1|kind=integrity|run={RUN_ID}|tick=300|army=1|"
        f"reason={reason}|source=observer"
    ]
    assert len(checkpoints) == 1


@pytest.mark.skipif(not OBSERVER_PATH.is_file(), reason="benchmark observer RED module missing")
def test_either_army_brain_lookup_failure_is_integrity_rejected_without_stopping_other_sample() -> None:
    lua = runtime()
    _benchmark_lua_fixture(lua)
    lua.execute(OBSERVER_PATH.read_text(encoding="utf-8"))
    emitted: list[str] = []
    valid = lua.globals().MakeBenchmarkBrain(1)

    def brain_lookup(army: int) -> Any:
        if army == 2:
            raise RuntimeError("opponent brain unavailable")
        return valid

    lua.globals().GetArmyBrain = brain_lookup
    observer = lua.globals().Overmind4Benchmark.Create(
        RUN_ID, lua.table_from([1, 2]), emitted.append
    )

    assert lua.globals().Overmind4Benchmark.Step(observer, 300) is True

    assert any("|kind=checkpoint|" in line and "|army=1|" in line for line in emitted)
    assert any(
        "|kind=integrity|" in line
        and "|army=2|" in line
        and "|reason=army-brain-unavailable|" in line
        for line in emitted
    )


@pytest.mark.skipif(not BENCHMARK_SCHEMA_READY, reason="benchmark parser RED schema missing")
class TestBenchmarkParsing:
    def test_parser_collects_both_armies_at_each_checkpoint_in_tick_army_order(self) -> None:
        text = "\n".join(
            [
                benchmark_line(300, 2, mass_income=16),
                benchmark_line(300, 1, mass_income=10),
                benchmark_line(
                    600,
                    2,
                    mass_income=20,
                    army_count_raider=7,
                    army_mass_raider=420,
                ),
                benchmark_line(600, 1, mass_income=12),
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
        assert checkpoints[-1]["metrics"]["army_count_raider"] == 7
        assert checkpoints[-1]["metrics"]["army_mass_raider"] == 420
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

    def test_crlf_checkpoint_chunks_parse_without_leaking_carriage_returns(self) -> None:
        chunks = (
            benchmark_line(300, 2) + "\r",
            "\n" + benchmark_line(300, 1) + "\r\n",
        )

        telemetry = parsing.parse_log("".join(chunks), RUN_ID, our_slot=1)

        assert telemetry.benchmark_integrity_reason is None
        assert [(item.tick, item.army) for item in telemetry.benchmark_checkpoints] == [
            (300, 1),
            (300, 2),
        ]

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
            benchmark_line(300, 1) + "|mass_income=999",
            benchmark_line(300, 1) + "|unframed-token",
            benchmark_line(300, 1).replace(f"run={RUN_ID}", "run=other"),
        )

        for malformed in malformed_lines:
            telemetry = parsing.parse_log(
                malformed + "\n" + valid_army_two, RUN_ID, our_slot=1
            )
            assert len(telemetry.benchmark_checkpoints) < 2
            assert telemetry.benchmark_integrity_reason is not None

    def test_explicit_observer_integrity_failure_is_preserved_as_hard_reject_reason(self) -> None:
        text = "\n".join(
            (
                benchmark_line(300, 1),
                benchmark_line(300, 2),
                f"OM4BENCH|v=1|kind=integrity|run={RUN_ID}|tick=300|army=1|"
                "reason=force-plan-unavailable",
            )
        )

        telemetry = parsing.parse_log(text, RUN_ID, our_slot=1)

        assert telemetry.benchmark_integrity_reason == "force-plan-unavailable"

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

    def test_selection_before_its_seen_opportunity_tick_fails_closed(self) -> None:
        text = "\n".join(
            (
                operation_line(100, "mex-1", "opportunity"),
                operation_line(50, "mex-1", "selected"),
            )
        )

        telemetry = parsing.parse_log(text, RUN_ID, our_slot=1)

        assert telemetry.operation_integrity_reason == "out-of-order-operation:mex-1"
        assert [event.tick for event in telemetry.operation_events] == [100, 50]

    @pytest.mark.parametrize(
        "malformed",
        (
            operation_line(100, "mex-1", "opportunity").replace("v=1", "v=2"),
            operation_line(100, "mex-1", "opportunity").replace("|tick=100", ""),
            operation_line(100, "mex-1", "opportunity").replace("|phase=opportunity", ""),
            operation_line(100, "mex-1", "opportunity") + "|army=2",
        ),
    )
    def test_own_wrong_version_or_malformed_operation_records_fail_closed(
        self, malformed: str
    ) -> None:
        telemetry = parsing.parse_log(malformed, RUN_ID, our_slot=1)

        assert telemetry.operation_integrity_reason is not None

    def test_crlf_operation_records_preserve_causal_order_and_typed_fields(self) -> None:
        text = "\r\n".join(
            (
                operation_line(100, "mex-1", "opportunity"),
                operation_line(110, "mex-1", "selected", attempt=0),
                operation_line(120, "mex-1", "admitted", response_ticks=10),
            )
        ) + "\r\n"

        telemetry = parsing.parse_log(text, RUN_ID, our_slot=1)

        assert telemetry.operation_integrity_reason is None
        assert [event.phase for event in telemetry.operation_events] == [
            "opportunity",
            "selected",
            "admitted",
        ]
        assert telemetry.operation_events[-1].fields["response_ticks"] == 10

    @pytest.mark.parametrize(
        "malformed",
        (
            operation_line(100, "mex-1", "opportunity")
            + "|operation=mex-2",
            operation_line(100, "mex-1", "opportunity") + "|unframed-token",
            operation_line(100, "mex-1", "opportunity", response_ticks=-1),
            operation_line(100, "mex-1", "opportunity", scout_coverage_age="nan"),
        ),
    )
    def test_duplicate_fields_or_invalid_causal_timings_fail_closed(
        self, malformed: str
    ) -> None:
        telemetry = parsing.parse_log(malformed, RUN_ID, our_slot=1)

        assert telemetry.operation_integrity_reason is not None

    def test_malformed_records_for_another_run_or_army_do_not_poison_our_stream(self) -> None:
        other_run_duplicate = (
            benchmark_line(300, 1, run_id="other") + "|mass_income=999"
        )
        opponent_duplicate = (
            operation_line(100, "opponent-op", "opportunity")
            .replace("army=1", "army=2")
            + "|operation=duplicate"
        )
        opponent_wrong_version = (
            operation_line(100, "opponent-v2", "opportunity")
            .replace("army=1", "army=2")
            .replace("v=1", "v=2")
        )
        text = "\n".join(
            (
                other_run_duplicate,
                opponent_duplicate,
                opponent_wrong_version,
                benchmark_line(300, 1),
                benchmark_line(300, 2),
                operation_line(100, "our-op", "opportunity"),
                operation_line(110, "our-op", "selected"),
            )
        )

        telemetry = parsing.parse_log(text, RUN_ID, our_slot=1)

        assert telemetry.benchmark_integrity_reason is None
        assert telemetry.operation_integrity_reason is None


def test_reporting_exposes_a_public_parity_gate_api() -> None:
    assert callable(getattr(reporting, "evaluate_parity", None))
    assert callable(getattr(reporting, "evaluate_promotion", None))


def test_benchmark_provenance_digest_covers_parser_reporting_and_changes_combined_config() -> None:
    contract = runner_module._evaluation_contract_hash()

    assert {path.name for path in runner_module.EVALUATION_CONTRACT_FILES} == {
        "parsing.py",
        "reporting.py",
    }
    assert contract == runner_module._evaluation_contract_hash()
    assert re.fullmatch(r"[0-9A-F]{64}", contract)
    assert runner_module._benchmark_config_hash("content-a", contract) != (
        runner_module._benchmark_config_hash("content-b", contract)
    )
    assert runner_module._benchmark_config_hash("content-a", contract) != (
        runner_module._benchmark_config_hash("content-a", "F" * 64)
    )


IAN_FLOORS = {
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
    },
}

RELATIVE_RATIOS = {
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

RELATIVE_OPPONENT_PROBES = {
    5: {
        "mass_income": 20,
        "mass_spent": 2000,
        "engineers_alive": 13,
        "factories": 7,
        "mex_alive": 17,
        "mass_reclaim": 1000,
    },
    10: {
        "mass_income": 40,
        "mass_spent": 8000,
        "engineers_alive": 21,
        "factories": 11,
        "mex_alive": 29,
        "mass_reclaim": 3000,
    },
    15: {
        "mass_income": 40,
        "mass_spent": 16000,
        "engineers_alive": 33,
        "factories": 15,
        "mex_alive": 37,
        "mass_reclaim": 6000,
    },
    20: {
        "mass_income": 40,
        "mass_spent": 24000,
        "engineers_alive": 46,
        "factories": 19,
        "mex_alive": 45,
        "mass_reclaim": 10000,
    },
}


def parity_raw_metrics(minutes: int, *, scale: float = 1) -> dict[str, float | int]:
    floor = IAN_FLOORS[minutes]
    values = metric_values()
    scaled_count = lambda value: int(math.ceil(float(value) * scale - 1e-9))
    engineers_alive = scaled_count(floor["engineers_alive"])
    engineers_built = max(engineers_alive, math.floor(engineers_alive / 0.95))
    mex_t2 = scaled_count(8 if minutes >= 20 else (4 if minutes >= 15 else 0))
    mex_t3 = 0
    mex_t1 = scaled_count(floor["mex_alive"]) - mex_t2 - mex_t3
    if minutes == 5:
        base_land_t1, base_land_t2, base_air_t1 = 2, 0, 1
    elif minutes == 10:
        base_land_t1, base_land_t2, base_air_t1 = 4, 0, 1
    elif minutes == 15:
        base_land_t1, base_land_t2, base_air_t1 = 3, 1, 3
    else:
        base_land_t1, base_land_t2, base_air_t1 = 3, 2, 4
    base_factory_total = base_land_t1 + base_land_t2 + base_air_t1
    scaled_factory_total = scaled_count(base_factory_total)
    land_t1 = base_land_t1 + (scaled_factory_total - base_factory_total)
    land_t2 = base_land_t2
    air_t1 = base_air_t1
    air_scout = scaled_count(1)
    air_interceptor = scaled_count(4 if minutes >= 10 else 2)
    air_bomber = scaled_count(1 if minutes >= 15 else 0)
    air_transport = scaled_count(1 if minutes >= 15 else 0)
    air_other = max(
        0,
        scaled_count(floor["air_total"])
        - air_scout
        - air_interceptor
        - air_bomber
        - air_transport,
    )
    combat = scaled_count(floor["combat_units"])
    home = math.ceil(combat * 0.25)
    garrison = math.ceil(combat * 0.15)
    response = math.ceil(combat * 0.10)
    raider = math.floor(combat * 0.05)
    field = combat - home - garrison - response - raider
    utilization_floor = 0.85 if minutes >= 15 else 0.75
    mass_spent = floor["mass_spent"] * scale
    mass_excess = mass_spent / utilization_floor - mass_spent
    values.update(
        {
            "mass_income": floor["mass_income"] * scale,
            "mass_spent": mass_spent,
            "mass_excess": mass_excess,
            "mass_reclaim": floor["mass_reclaim"] * scale,
            "engineers_alive": engineers_alive,
            "engineers_built": engineers_built,
            "engineers_lost": engineers_built - engineers_alive,
            "mex_t1": mex_t1,
            "mex_t2": mex_t2,
            "mex_t3": mex_t3,
            "mex_survival": floor["mex_survival"],
            "land_factory_t1": land_t1,
            "land_factory_t2": land_t2,
            "land_factory_t3": 0,
            "air_factory_t1": air_t1,
            "air_factory_t2": 0,
            "air_factory_t3": 0,
            "factory_utilization": utilization_floor,
            "factory_full_bank_idle_ticks": 0,
            "air_scout": air_scout,
            "air_interceptor": air_interceptor,
            "air_bomber": air_bomber,
            "air_transport": air_transport,
            "air_other": air_other,
            "mobile_t2": scaled_count(
                35 if minutes >= 20 else (12 if minutes >= 15 else 0)
            ),
            "army_count_home": home,
            "army_count_garrison": garrison,
            "army_count_field": field,
            "army_count_response": response,
            "army_count_raider": raider,
            "army_count_unassigned": 0,
        }
    )
    return values


def passing_parity_log(
    *,
    max_minutes: int = 20,
    raw_overrides: dict[tuple[int, int, str], float | int] | None = None,
    t2_start_tick: int = 5700,
    include_t3_admission: bool = True,
    official_result: str | None = None,
    run_id: str = RUN_ID,
) -> str:
    overrides = raw_overrides or {}
    records: list[tuple[int, int, int, str]] = []
    for tick in range(300, max_minutes * 600 + 1, 300):
        stage = 5 if tick <= 3000 else (10 if tick <= 6000 else (15 if tick <= 9000 else 20))
        for army, scale in ((1, 1.0), (2, 1.05)):
            values = parity_raw_metrics(stage, scale=scale)
            if tick == stage * 600:
                for (minute, override_army, field), value in overrides.items():
                    if minute == stage and override_army == army:
                        values[field] = value
            records.append(
                (
                    tick,
                    0,
                    army,
                    benchmark_line(tick, army, run_id=run_id, **values),
                )
            )
    t2_phases = (
        (5500, "opportunity"),
        (5600, "selected"),
        (5650, "admitted"),
        (t2_start_tick, "ordered"),
    )
    records.extend(
        (tick, 1, index, operation_line(tick, "tech:t2_hq", phase))
        for index, (tick, phase) in enumerate(t2_phases)
        if tick <= max_minutes * 600
    )
    if include_t3_admission and max_minutes >= 20:
        records.extend(
            (
                (11700, 1, 10, operation_line(11700, "tech:t3", "opportunity")),
                (11800, 1, 11, operation_line(11800, "tech:t3", "selected")),
                (11900, 1, 12, operation_line(11900, "tech:t3", "admitted")),
            )
        )
    lines = [record[3] for record in sorted(records)]
    if official_result is not None:
        lines.append(
            "OM4HARNESS|v=1|kind=result|"
            f"run={run_id}|army=1|result={official_result}|"
            f"sim={max_minutes * 60}"
        )
    return "\n".join(lines)


def passing_parity_telemetry(
    *,
    max_minutes: int = 20,
    raw_overrides: dict[tuple[int, int, str], float | int] | None = None,
    t2_start_tick: int = 5700,
    include_t3_admission: bool = True,
    official_result: str | None = None,
    run_id: str = RUN_ID,
) -> parsing.LogTelemetry:
    telemetry = parsing.parse_log(
        passing_parity_log(
            max_minutes=max_minutes,
            raw_overrides=raw_overrides,
            t2_start_tick=t2_start_tick,
            include_t3_admission=include_t3_admission,
            official_result=official_result,
            run_id=run_id,
        ),
        run_id,
        our_slot=1,
    )
    assert telemetry.benchmark_integrity_reason is None
    assert telemetry.operation_integrity_reason is None
    return telemetry


def derived_metric_overrides(
    minutes: int,
    army: int,
    metric: str,
    value: float | int,
) -> dict[tuple[int, int, str], float | int]:
    raw = parity_raw_metrics(minutes, scale=1 if army == 1 else 1.05)
    overrides: dict[tuple[int, int, str], float | int] = {}

    def override(field: str, updated: float | int) -> None:
        overrides[(minutes, army, field)] = updated

    if metric == "factories":
        fields_ = (
            "land_factory_t1",
            "land_factory_t2",
            "land_factory_t3",
            "air_factory_t1",
            "air_factory_t2",
            "air_factory_t3",
        )
        for field in fields_:
            override(field, 0)
        override("land_factory_t1", value)
    elif metric == "mex_alive":
        for field in ("mex_t1", "mex_t2", "mex_t3"):
            override(field, 0)
        override("mex_t1", value)
    elif metric == "engineers_alive":
        override("engineers_alive", value)
        override("engineers_built", value)
        override("engineers_lost", 0)
    elif metric == "combat_units":
        fields_ = (
            "army_count_home",
            "army_count_garrison",
            "army_count_field",
            "army_count_response",
            "army_count_raider",
            "army_count_unassigned",
        )
        for field in fields_:
            override(field, 0)
        override("army_count_raider", value)
    elif metric == "air_total":
        fields_ = (
            "air_scout",
            "air_interceptor",
            "air_bomber",
            "air_transport",
            "air_other",
        )
        for field in fields_:
            override(field, 0)
        override("air_other", value)
    elif metric == "mass_utilization":
        spent = float(raw["mass_spent"])
        override("mass_excess", spent / float(value) - spent)
    elif metric == "engineer_attrition":
        built = float(raw["engineers_built"])
        override("engineers_lost", built * float(value))
    else:
        override(metric, value)
    return overrides


def derived_failure_telemetry(
    minutes: int, metric: str, value: float | int
) -> parsing.LogTelemetry:
    if metric == "t2_hq_started_tick":
        return passing_parity_telemetry(t2_start_tick=int(value))
    if metric == "t3_admitted":
        return passing_parity_telemetry(include_t3_admission=bool(value))
    return passing_parity_telemetry(
        raw_overrides=derived_metric_overrides(minutes, 1, metric, value)
    )


def test_real_runner_automatically_parses_evaluates_and_writes_live_parity_artifacts(
    tmp_path: Path,
) -> None:
    lifecycle = "\n".join(
        (
            "OM4HARNESS|v=1|kind=start|run=run-fixed|map=SCMP_007",
            "OM4|v=1|kind=lifecycle|army=1|event=created|plan=none",
            "OM4|v=1|kind=lifecycle|army=1|event=begin_session",
            "OM4HARNESS|v=1|kind=speed|run=run-fixed|requested=25|sim=1",
        )
    )
    live_log = "\n".join(
        (
            lifecycle,
            passing_parity_log(run_id="run-fixed"),
            "OM4|v=1|kind=lifecycle|army=1|event=terminal|result=victory",
            "OM4HARNESS|v=1|kind=result|run=run-fixed|army=1|"
            "result=victory 10|sim=1200",
        )
    )

    class CompletedBenchmarkMonitor:
        def wait(
            self,
            process: Any,
            log_path: Path,
            wall_limit: float,
            **_: Any,
        ) -> parsing.ProcessObservation:
            del process, wall_limit
            log_path.write_text(live_log, encoding="utf-8")
            return parsing.ProcessObservation(exit_code=0, wall_seconds=2)

        def stop_owned(self, process: Any) -> tuple[int | None, bool]:
            del process
            return 0, False

    deps, _, _, _ = runner_dependencies(tmp_path)
    deps = replace(
        deps,
        monitor=CompletedBenchmarkMonitor(),
        map_fingerprint=lambda _: {
            "version": 3,
            "sha256": "map123",
            "size_km": 20,
        },
    )
    result = Runner(tmp_path / "repo", deps).run(
        RunConfig(
            opponent_ai="adaptive",
            seed=7777,
            sim_time_limit=1200,
        ),
        tmp_path / "artifacts",
        dry_run=False,
    )

    assert result.outcome is not None
    assert result.outcome.state == "win"
    report = json.loads(result.paths.report_json_path.read_text(encoding="utf-8"))
    assert report["official_result"] == "victory 10"
    assert len(report["benchmark_checkpoints"]) == 80
    assert len(report["operation_events"]) == 7
    assert report["parity"]["classification"] == "macro-parity-win"
    assert report["parity"]["matchEligible"] is True
    assert report["parity"]["benchmarkConfig"]
    assert report["parity"]["benchmarkConfig"] != "content123"
    assert report["parity"]["evaluationContractDigest"]
    manifest = json.loads(result.paths.manifest_path.read_text(encoding="utf-8"))
    assert manifest["benchmark"]["config_sha256"] == report["parity"]["benchmarkConfig"]
    assert (
        manifest["benchmark"]["evaluation_contract_sha256"]
        == report["parity"]["evaluationContractDigest"]
    )
    markdown = result.paths.report_markdown_path.read_text(encoding="utf-8")
    assert "macro-parity-win" in markdown


@pytest.mark.parametrize(
    ("expected_state", "observation", "log_suffix"),
    (
        (
            "crash",
            parsing.ProcessObservation(exit_code=1, wall_seconds=2),
            "",
        ),
        (
            "wall-timeout",
            parsing.ProcessObservation(
                exit_code=None, wall_seconds=300, wall_timeout=True
            ),
            "",
        ),
        (
            "malformed",
            parsing.ProcessObservation(exit_code=0, wall_seconds=2),
            '\nJsonStats {"stats":[',
        ),
    ),
)
def test_runner_rejects_nonterminal_outcome_even_when_benchmark_stream_is_complete(
    tmp_path: Path,
    expected_state: str,
    observation: parsing.ProcessObservation,
    log_suffix: str,
) -> None:
    live_log = "\n".join(
        (
            "OM4HARNESS|v=1|kind=start|run=run-fixed|map=SCMP_007",
            "OM4|v=1|kind=lifecycle|army=1|event=created|plan=none",
            "OM4|v=1|kind=lifecycle|army=1|event=begin_session",
            "OM4HARNESS|v=1|kind=speed|run=run-fixed|requested=25|sim=1",
            passing_parity_log(run_id="run-fixed"),
            "OM4|v=1|kind=lifecycle|army=1|event=terminal|result=victory",
            "OM4HARNESS|v=1|kind=result|run=run-fixed|army=1|"
            "result=victory 10|sim=1200",
        )
    ) + log_suffix

    class InvalidOutcomeMonitor:
        def wait(
            self,
            process: Any,
            log_path: Path,
            wall_limit: float,
            **_: Any,
        ) -> parsing.ProcessObservation:
            del process, wall_limit
            log_path.write_text(live_log, encoding="utf-8")
            return observation

        def stop_owned(self, process: Any) -> tuple[int | None, bool]:
            del process
            return 0, False

    deps, _, _, _ = runner_dependencies(tmp_path)
    deps = replace(
        deps,
        monitor=InvalidOutcomeMonitor(),
        map_fingerprint=lambda _: {
            "version": 3,
            "sha256": "map123",
            "size_km": 20,
        },
    )

    result = Runner(tmp_path / "repo", deps).run(
        RunConfig(opponent_ai="adaptive", seed=7777, sim_time_limit=1200),
        tmp_path / "artifacts",
        dry_run=False,
    )

    assert result.outcome is not None
    assert result.outcome.state == expected_state
    report = json.loads(result.paths.report_json_path.read_text(encoding="utf-8"))
    assert report["parity"]["classification"] == "operational-reject"
    assert report["parity"]["matchEligible"] is False
    assert report["parity"]["failures"] == [
        f"invalid-outcome-state:{expected_state}"
    ]


@pytest.mark.skipif(
    not (PARITY_API_READY and BENCHMARK_SCHEMA_READY),
    reason="parity reporting or parser RED API missing",
)
class TestParityReporting:
    def test_ian_5_10_15_20_absolute_and_relative_floors_pass_together(self) -> None:
        result = reporting.evaluate_parity(
            passing_parity_telemetry(),
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="victory",
            operational_failure=None,
            seed=7777,
            spawn="normal",
        )

        assert result["failures"] == []
        assert result["classification"] == "macro-parity-win"
        assert result["keep"] is True
        assert result["matchEligible"] is True
        assert result["promotable"] is False
        assert result["derived"]["20m"]["mex_alive"] == 22
        assert result["derived"]["20m"]["factories"] == 9
        assert result["derived"]["20m"]["combat_units"] == 120
        assert result["derived"]["20m"]["air_total"] == 30
        assert result["derived"]["10m"]["t2_hq_started_tick"] == 5700
        assert result["derived"]["20m"]["mass_utilization"] == pytest.approx(0.85)
        assert result["derived"]["20m"]["factory_full_bank_idle_ticks"] == 0
        assert result["derived"]["20m"]["engineer_attrition"] <= 0.05

    @pytest.mark.parametrize(
        ("official_result", "classification", "eligible"),
        (
            ("victory 10", "macro-parity-win", True),
            ("defeat -10", "combat-loss-macro-parity", False),
        ),
    )
    def test_parity_uses_the_real_parsed_official_result_with_score_suffix(
        self,
        official_result: str,
        classification: str,
        eligible: bool,
    ) -> None:
        telemetry = passing_parity_telemetry(official_result=official_result)

        assert telemetry.official_result == official_result
        result = reporting.evaluate_parity(
            telemetry,
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result=telemetry.official_result,
            seed=7777,
            spawn="normal",
        )

        assert result["classification"] == classification
        assert result["matchEligible"] is eligible

    @pytest.mark.parametrize(
        ("minutes", "metric"),
        [
            (minutes, metric)
            for minutes in (5, 10, 15, 20)
            for metric in (
                "mass_income",
                "mass_spent",
                "engineers_alive",
                "factories",
                "mex_alive",
                "mass_reclaim",
            )
        ],
    )
    def test_every_opponent_relative_gate_fails_immediately_below_and_passes_at_boundary(
        self,
        minutes: int,
        metric: str,
    ) -> None:
        opponent = RELATIVE_OPPONENT_PROBES[minutes][metric]
        ratio = RELATIVE_RATIOS[minutes][metric]
        raw_required = max(float(IAN_FLOORS[minutes][metric]), opponent * ratio)
        if metric in {"engineers_alive", "factories", "mex_alive"}:
            at_boundary: float | int = int(math.ceil(raw_required - 1e-9))
            below_boundary: float | int = at_boundary - 1
        else:
            at_boundary = raw_required
            below_boundary = math.nextafter(raw_required, -math.inf)
        expected = f"{minutes}m:{metric}:relative"
        common_overrides = derived_metric_overrides(
            minutes, 2, metric, opponent
        )

        below = reporting.evaluate_parity(
            passing_parity_telemetry(
                raw_overrides={
                    **common_overrides,
                    **derived_metric_overrides(
                        minutes, 1, metric, below_boundary
                    ),
                }
            ),
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="defeat -10",
        )
        at = reporting.evaluate_parity(
            passing_parity_telemetry(
                raw_overrides={
                    **common_overrides,
                    **derived_metric_overrides(
                        minutes, 1, metric, at_boundary
                    ),
                }
            ),
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="defeat -10",
        )

        assert [
            failure
            for failure in below["failures"]
            if failure.endswith(":relative")
        ] == [expected]
        assert not [
            failure
            for failure in at["failures"]
            if failure.endswith(":relative")
        ]

    @pytest.mark.parametrize(
        ("minutes", "metric", "floor"),
        (
            (5, "mex_survival", 0.90),
            (10, "mex_survival", 0.85),
            (15, "mex_survival", 0.80),
            (20, "mex_survival", 0.75),
            (10, "mass_utilization", 0.75),
            (15, "mass_utilization", 0.85),
            (20, "mass_utilization", 0.85),
        ),
    )
    def test_every_nonintegral_absolute_floor_fails_immediately_below_and_passes_exactly_at_boundary(
        self,
        minutes: int,
        metric: str,
        floor: float,
    ) -> None:
        expected = f"{minutes}m:{metric}:absolute"
        below = reporting.evaluate_parity(
            derived_failure_telemetry(
                minutes, metric, math.nextafter(floor, -math.inf)
            ),
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="defeat -10",
        )
        at = reporting.evaluate_parity(
            derived_failure_telemetry(minutes, metric, floor),
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="defeat -10",
        )

        assert [
            failure
            for failure in below["failures"]
            if failure.endswith(":absolute")
        ] == [expected]
        assert not [
            failure
            for failure in at["failures"]
            if failure.endswith(":absolute")
        ]

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
            telemetry = derived_failure_telemetry(minutes, metric, value)
            result = reporting.evaluate_parity(
                telemetry,
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
            telemetry = derived_failure_telemetry(15, metric, 0)
            result = reporting.evaluate_parity(
                telemetry,
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
        overrides = {}
        for minutes in (5, 10):
            for field in REQUIRED_METRICS:
                base = parity_raw_metrics(minutes)[field]
                overrides[(minutes, 1, field)] = float(base) * 0.2
        telemetry = passing_parity_telemetry(
            max_minutes=10, raw_overrides=overrides
        )

        result = reporting.evaluate_parity(
            telemetry,
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="victory",
        )

        assert result["classification"] == "tactical-win-macro-fail"
        assert result["keep"] is False
        assert result["matchEligible"] is False
        assert result["promotable"] is False

    def test_early_win_cannot_skip_unobserved_15_and_20_minute_macro_gates(self) -> None:
        result = reporting.evaluate_parity(
            passing_parity_telemetry(max_minutes=10),
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="victory 10",
        )

        assert result["classification"] == "tactical-win-macro-fail"
        assert result["matchEligible"] is False
        assert "15m:checkpoint:missing" in result["failures"]
        assert "20m:checkpoint:missing" in result["failures"]

    def test_macro_parity_loss_is_kept_and_classified_as_combat_not_macro_failure(self) -> None:
        result = reporting.evaluate_parity(
            passing_parity_telemetry(),
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="defeat",
        )

        assert result["classification"] == "combat-loss-macro-parity"
        assert result["keep"] is True
        assert result["matchEligible"] is False
        assert result["promotable"] is False

    def test_operational_failure_or_missing_benchmark_integrity_is_a_hard_reject(self) -> None:
        for failure in ("lua-error", "desync", "missing-benchmark-tick:600"):
            result = reporting.evaluate_parity(
                passing_parity_telemetry(),
                our_army=1,
                opponent_army=2,
                map_size_km=20,
                official_result="victory",
                operational_failure=failure,
            )
            assert result["classification"] == "operational-reject", failure
            assert result["keep"] is False, failure
            assert result["matchEligible"] is False, failure
            assert result["promotable"] is False, failure

        missing_checkpoint = parsing.parse_log(
            "\n".join(
                (
                    benchmark_line(300, 1),
                    benchmark_line(300, 2),
                    benchmark_line(900, 1),
                    benchmark_line(900, 2),
                )
            ),
            RUN_ID,
            our_slot=1,
        )
        assert missing_checkpoint.benchmark_integrity_reason == (
            "missing-benchmark-tick:600"
        )
        rejected = reporting.evaluate_parity(
            missing_checkpoint,
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="victory",
            operational_failure=None,
        )
        assert rejected["classification"] == "operational-reject"
        assert rejected["matchEligible"] is False
        assert rejected["promotable"] is False

    @pytest.mark.parametrize(
        "outcome_state",
        (
            "crash",
            "wall-timeout",
            "sim-timeout",
            "malformed",
            "load-error",
            "desync",
            "missing-result",
        ),
    )
    def test_every_nonterminal_outcome_state_rejects_even_complete_passing_telemetry(
        self, outcome_state: str
    ) -> None:
        result = reporting.evaluate_parity(
            passing_parity_telemetry(),
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="victory",
            operational_failure=None,
            outcome_state=outcome_state,
        )

        assert result["classification"] == "operational-reject"
        assert result["matchEligible"] is False
        assert result["failures"] == [f"invalid-outcome-state:{outcome_state}"]

    @pytest.mark.parametrize("outcome_state", ("win", "loss", "draw"))
    def test_only_valid_terminal_outcome_states_enter_macro_evaluation(
        self, outcome_state: str
    ) -> None:
        official = {"win": "victory", "loss": "defeat", "draw": "draw"}[
            outcome_state
        ]
        result = reporting.evaluate_parity(
            passing_parity_telemetry(),
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result=official,
            outcome_state=outcome_state,
        )

        assert result["classification"] != "operational-reject"

    def test_json_report_contains_checkpoints_operations_and_parity_without_feeding_ai(self) -> None:
        telemetry = passing_parity_telemetry()
        parity = reporting.evaluate_parity(
            telemetry,
            our_army=1,
            opponent_army=2,
            map_size_km=20,
            official_result="victory",
            seed=7777,
            spawn="normal",
        )
        outcome = parsing.classify_outcome(
            telemetry,
            parsing.ProcessObservation(exit_code=0, wall_seconds=2),
        )
        document = json.loads(
            reporting.render_json(outcome, RUN_ID, parity_result=parity)
        )

        assert len(document["benchmark_checkpoints"]) == 80
        assert len(document["operation_events"]) == 7
        assert document["parity"] == parity
        assert document["parity"]["classification"] == "macro-parity-win"
        own_20m = next(
            checkpoint
            for checkpoint in document["benchmark_checkpoints"]
            if checkpoint["tick"] == 12000 and checkpoint["army"] == 1
        )
        assert own_20m["metrics"]["army_count_raider"] == 6
        assert "army_mass_raider" in own_20m["metrics"]

    @pytest.mark.skipif(
        not PROMOTION_API_READY, reason="promotion aggregation RED API missing"
    )
    def test_all_size_promotion_requires_unique_normal_and_swapped_8_of_8(self) -> None:
        matches = []
        for map_size in (5, 10, 20, 40):
            for spawn, seed in (("normal", 7777), ("swapped", 7778)):
                result = reporting.evaluate_parity(
                    passing_parity_telemetry(),
                    our_army=1,
                    opponent_army=2,
                    map_size_km=map_size,
                    official_result="victory",
                    seed=seed,
                    spawn=spawn,
                    benchmark_config="benchmark-a",
                    evaluation_contract_digest="contract-a",
                )
                assert result["matchEligible"] is True
                assert result["promotable"] is False
                matches.append(result)

        promoted = reporting.evaluate_promotion(matches)

        assert promoted["promotable"] is True
        assert promoted["passed"] == 8
        assert promoted["required"] == 8
        assert promoted["maps"] == [5, 10, 20, 40]

        parity_loss = reporting.evaluate_parity(
            passing_parity_telemetry(),
            our_army=1,
            opponent_army=2,
            map_size_km=10,
            official_result="defeat",
            seed=7777,
            spawn="normal",
            benchmark_config="benchmark-a",
            evaluation_contract_digest="contract-a",
        )
        wrong_spawn = reporting.evaluate_parity(
            passing_parity_telemetry(),
            our_army=1,
            opponent_army=2,
            map_size_km=5,
            official_result="victory",
            seed=7779,
            spawn="third",
            benchmark_config="benchmark-a",
            evaluation_contract_digest="contract-a",
        )
        assert parity_loss["matchEligible"] is False
        invalid_matrices = (
            matches[:-1],
            matches[:-1] + [copy.deepcopy(matches[0])],
            [
                ({**match, "matchEligible": False} if index == 3 else match)
                for index, match in enumerate(matches)
            ],
            [wrong_spawn, *matches[1:]],
            [*matches[:2], parity_loss, *matches[3:]],
            [
                ({**match, "benchmarkConfig": "different-build"} if index == 4 else match)
                for index, match in enumerate(matches)
            ],
            [
                (
                    {**match, "evaluationContractDigest": "different-contract"}
                    if index == 4
                    else match
                )
                for index, match in enumerate(matches)
            ],
            [{**match, "benchmarkConfig": None} for match in matches],
            [{**match, "benchmarkConfig": ""} for match in matches],
            [{**match, "evaluationContractDigest": None} for match in matches],
            [{**match, "evaluationContractDigest": ""} for match in matches],
        )
        for invalid in invalid_matrices:
            rejected = reporting.evaluate_promotion(invalid)
            assert rejected["promotable"] is False
            assert rejected["failures"]

        reversed_order = reporting.evaluate_promotion(list(reversed(matches)))
        assert reversed_order["promotable"] is True
        assert reversed_order["passed"] == 8
