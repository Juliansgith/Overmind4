from __future__ import annotations

import random
from typing import Any

import pytest

from test_controller import execute_intents, make_harness
from test_field_campaign import reconcile, start_campaign
from test_policy import (
    base_snapshot,
    decide,
    intents_of,
    lua_value,
    plain,
    post_opening_snapshot,
    role_counts,
)
from test_secured_frontier_doctrine import mass_site


ECONOMIC_INTENTS = {"build_structure", "factory_build", "factory_upgrade", "reclaim"}


def _set_economy(
    harness: Any,
    *,
    mass_income: float,
    mass_requested: float,
    energy_income: float = 30,
    energy_requested: float = 15,
    mass_stored_ratio: float = 0.5,
    energy_stored_ratio: float = 0.8,
    mass_trend: float | None = None,
    energy_trend: float | None = None,
    mass_usage: float | None = None,
    energy_usage: float | None = None,
) -> None:
    harness.brain.massIncome = mass_income
    harness.brain.massRequested = mass_requested
    harness.brain.massUsage = (
        min(mass_income, mass_requested) if mass_usage is None else mass_usage
    )
    harness.brain.massTrend = (
        mass_income - mass_requested if mass_trend is None else mass_trend
    )
    harness.brain.massStoredRatio = mass_stored_ratio
    harness.brain.energyIncome = energy_income
    harness.brain.energyRequested = energy_requested
    harness.brain.energyUsage = (
        min(energy_income, energy_requested) if energy_usage is None else energy_usage
    )
    harness.brain.energyTrend = (
        energy_income - energy_requested if energy_trend is None else energy_trend
    )
    harness.brain.energyStoredRatio = energy_stored_ratio


def _sample(harness: Any, count: int, *, start: int = 0, stride: int = 10) -> Any:
    observation = None
    for index in range(count):
        next_tick = start + index * stride
        delta = max(0, next_tick - int(harness.brain.tick))
        harness.brain.armyStats.Economy_TotalProduced_Mass = (
            harness.brain.armyStats.Economy_TotalProduced_Mass
            + harness.brain.massIncome * delta
        )
        harness.brain.armyStats.Economy_TotalProduced_Energy = (
            harness.brain.armyStats.Economy_TotalProduced_Energy
            + harness.brain.energyIncome * delta
        )
        harness.brain.tick = next_tick
        observation = harness.observe()
    assert observation is not None
    return observation


def _live_factory(harness: Any, entity_id: int, *, domain: str = "land", idle: bool = True) -> Any:
    blueprint = {"land": "ueb0101", "air": "ueb0102", "t2": "ueb0201"}[domain]
    can_build = {
        "land": {"uel0101": True, "uel0103": True, "uel0104": True, "uel0105": True, "uel0106": True, "uel0201": True, "ueb0201": True},
        "air": {"uea0102": True},
        "t2": {"uel0202": True, "uel0205": True},
    }[domain]
    return harness.unit(
        entityId=entity_id,
        blueprintId=blueprint,
        position=[10 + entity_id / 1000, 2, 20],
        idleState=idle,
        states={} if idle else {"Building": True},
        canBuild=can_build,
    )


def _engineer(harness: Any, entity_id: int, x: float, z: float = 20) -> Any:
    return harness.unit(
        entityId=entity_id,
        blueprintId="uel0105",
        position=[x, 2, z],
        canBuild={
            "ueb1103": True,
            "ueb1101": True,
            "ueb1102": True,
            "ueb0101": True,
            "ueb0102": True,
        },
    )


def _policy_allocator_snapshot(*roles: str) -> dict[str, Any]:
    snapshot = post_opening_snapshot("engineer", "scout", *roles)
    snapshot["economy"] = {
        "massIncome": 1.2,
        "massRequested": 0.4,
        "massUsage": 0.4,
        "massTrend": 0.8,
        "massStoredRatio": 0.8,
        "energyIncome": 30,
        "energyRequested": 10,
        "energyUsage": 10,
        "energyTrend": 20,
        "energyStoredRatio": 0.8,
    }
    snapshot["macro"] = {
        "allocatorEnabled": True,
        "economyLedgerValid": True,
        "recurringMassIncome": 1.2,
        "recurringEnergyIncome": 30,
        "rollingMassRequested": 0.4,
        "rollingEnergyRequested": 10,
        "availableRecurringMass": 0.8,
        "availableRecurringEnergy": 20,
        "oneTimeMassReserve": 300,
        "oneTimeEnergyReserve": 3000,
        "activeCommittedMassDrain": 0,
        "activeCommittedEnergyDrain": 0,
        "factoryTarget": 2,
        "factoryDemand": 2,
        "factoryFundedCount": 2,
        "factoryIdleCount": 0,
        "engineerTarget": 1,
        "engineerDemand": 1,
        "expansionOpportunityCount": 0,
        "activeRebuildJobs": 0,
        "activeFrontierJobs": 0,
        "activeReclaimJobs": 0,
        "campaignEnabled": False,
        "campaignState": "idle",
        "campaignIntentMode": "none",
        "techAdmission": "deferred",
    }
    snapshot["reclaim"] = []
    for unit in snapshot["units"]:
        if unit["role"] == "engineer":
            unit["buildRate"] = 5
            unit["canBuild"].update(
                mass_extractor=True,
                power_generator=True,
                hydrocarbon=True,
                land_factory=True,
                air_factory=True,
            )
        elif unit["role"] == "land_factory":
            unit["needsRally"] = False
            unit["canBuild"].update(
                engineer=True,
                scout=True,
                tank=True,
                artillery=True,
                anti_air=True,
                land_factory_t2=True,
            )
        elif unit["role"] == "air_factory":
            unit["canBuild"].update(interceptor=True)
        elif unit["role"] == "land_factory_t2":
            unit["canBuild"].update(t2_direct_fire=True, t2_anti_air=True)
    return snapshot


def _economic(result: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [intent for intent in result if intent["kind"] in ECONOMIC_INTENTS]


def _strategic_expansion_snapshot(
    *,
    engineers: int = 5,
    hydro: bool = True,
    air: bool = False,
    slots: int = 4,
    seed: int = 0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    roles = ["engineer"] * (engineers - 1) + ["mass_extractor"] * 5
    if hydro:
        roles.append("hydrocarbon")
    if air:
        roles.append("air_factory")
    snapshot = _policy_allocator_snapshot(*roles)
    snapshot["placements"]["air_factory"] = [[26, 2, 18]]
    snapshot["sites"]["hydro"] = [] if hydro else [
        mass_site("home-hydro", 26, 18)
    ]
    builders = sorted(
        (unit for unit in snapshot["units"] if unit["role"] == "engineer"),
        key=lambda unit: unit["token"],
    )
    positions = [24, 60, 100, 140, 180, 220]
    for index, builder in enumerate(builders):
        builder["position"] = [positions[index], 2, 18]
        builder["canBuild"].update(
            mass_extractor=True,
            hydrocarbon=False,
            air_factory=False,
        )
    builders[0]["canBuild"].update(hydrocarbon=True, air_factory=True)
    snapshot["sites"]["mass"] = [
        mass_site(f"expansion-{index}", x, 20, frontier=True)
        for index, x in enumerate([24, 60, 100, 140], start=1)
    ]
    snapshot["macro"].update(
        expansionRecurringMassBudget=slots * 0.3,
        expansionRecurringEnergyBudget=slots * 3,
        availableRecurringMass=5,
        availableRecurringEnergy=50,
        oneTimeMassReserve=10000,
        oneTimeEnergyReserve=10000,
        expansionOpportunityCount=4,
    )
    random.Random(seed).shuffle(snapshot["units"])
    random.Random(seed + 17).shuffle(snapshot["sites"]["mass"])
    return snapshot, builders


@pytest.mark.parametrize("seed", range(5))
def test_artifact_five_engineers_reserve_air_builder_before_four_expansions(seed: int) -> None:
    snapshot, builders = _strategic_expansion_snapshot(seed=seed)

    builds = intents_of(decide(snapshot), "build_structure")
    air = [intent for intent in builds if intent.get("buildRole") == "air_factory"]
    mex = [intent for intent in builds if intent.get("reason") == "frontier_expansion"]

    assert [(intent["actorToken"], intent["reason"]) for intent in air] == [
        (builders[0]["token"], "first_air_factory")
    ]
    assert 1 <= len(mex) <= 4
    assert len({intent["actorToken"] for intent in [*air, *mex]}) == len(air) + len(mex)


def test_four_engineers_reserve_one_air_builder_and_schedule_at_most_three_expansions() -> None:
    snapshot, builders = _strategic_expansion_snapshot(engineers=4)

    builds = intents_of(decide(snapshot), "build_structure")
    air = [intent for intent in builds if intent.get("buildRole") == "air_factory"]
    mex = [intent for intent in builds if intent.get("reason") == "frontier_expansion"]

    assert [intent["actorToken"] for intent in air] == [builders[0]["token"]]
    assert len(mex) == 3
    assert len({intent["actorToken"] for intent in [*air, *mex]}) == 4


def test_missing_hydro_reserves_its_home_builder_before_expansion() -> None:
    snapshot, builders = _strategic_expansion_snapshot(hydro=False)

    builds = intents_of(decide(snapshot), "build_structure")
    hydro = [intent for intent in builds if intent.get("buildRole") == "hydrocarbon"]
    mex = [intent for intent in builds if intent.get("reason") == "frontier_expansion"]

    assert [(intent["actorToken"], intent.get("siteKey")) for intent in hydro] == [
        (builders[0]["token"], "home-hydro")
    ]
    assert 1 <= len(mex) <= 4
    assert len({intent["actorToken"] for intent in [*hydro, *mex]}) == len(hydro) + len(mex)


def test_first_air_factory_reserves_before_optional_third_land_factory() -> None:
    snapshot, builders = _strategic_expansion_snapshot()
    snapshot["macro"].update(factoryTarget=3, factoryDemand=3)
    snapshot["economy"]["massStalled"] = False

    builds = intents_of(decide(snapshot), "build_structure")
    air = [intent for intent in builds if intent.get("buildRole") == "air_factory"]

    assert [intent["actorToken"] for intent in air] == [builders[0]["token"]]


@pytest.mark.parametrize("seed", range(6))
def test_strategic_builder_is_nearest_capable_noncampaign_engineer_under_permutation(
    seed: int,
) -> None:
    snapshot, builders = _strategic_expansion_snapshot(seed=seed)
    builders[0]["campaignEngineer"] = True
    builders[1]["canBuild"]["air_factory"] = True

    air = [
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "air_factory"
    ]

    assert [intent["actorToken"] for intent in air] == [builders[1]["token"]]


def test_lost_mex_keeps_priority_then_remaining_builder_takes_air_factory() -> None:
    snapshot, builders = _strategic_expansion_snapshot(engineers=2, slots=2)
    builders[1]["canBuild"]["air_factory"] = True
    snapshot["sites"]["mass"] = [
        dict(mass_site("lost-home", 20, 20, lost=True), engineerReachable=True),
        mass_site("new-forward", 60, 20, frontier=True),
    ]
    snapshot["macro"]["lostMexCount"] = 1

    builds = intents_of(decide(snapshot), "build_structure")
    lost = [intent for intent in builds if intent.get("reason") == "rebuild_mex"]
    air = [intent for intent in builds if intent.get("buildRole") == "air_factory"]

    assert [(intent["actorToken"], intent["siteKey"]) for intent in lost] == [
        (builders[0]["token"], "lost-home")
    ]
    assert [intent["actorToken"] for intent in air] == [builders[1]["token"]]


@pytest.mark.parametrize(
    ("blocked", "expected_mex"),
    [
        ("low_energy", 4),
        ("incomplete_mex", 4),
        ("incomplete_land", 4),
        ("existing_air", 4),
        ("contact", 0),
    ],
)
def test_false_air_milestones_do_not_reserve_an_expansion_builder(
    blocked: str,
    expected_mex: int,
) -> None:
    snapshot, _ = _strategic_expansion_snapshot(engineers=4, air=blocked == "existing_air")
    if blocked == "low_energy":
        snapshot["economy"]["energyTrend"] = -0.01
    elif blocked == "incomplete_mex":
        removed = 4
        snapshot["units"] = [
            unit for unit in snapshot["units"]
            if not (unit["role"] == "mass_extractor" and (removed := removed - 1) >= 0)
        ]
    elif blocked == "incomplete_land":
        removed = 1
        snapshot["units"] = [
            unit for unit in snapshot["units"]
            if not (unit["role"] == "land_factory" and (removed := removed - 1) >= 0)
        ]
    elif blocked == "contact":
        snapshot["enemyContact"] = {"position": [12, 2, 12], "immediate": True}

    builds = intents_of(decide(snapshot), "build_structure")

    assert not [intent for intent in builds if intent.get("buildRole") == "air_factory"]
    assert len([intent for intent in builds if intent.get("reason") == "frontier_expansion"]) == expected_mex


def test_transient_reclaim_income_is_one_time_not_recurring_factory_capacity() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    _set_economy(harness, mass_income=1.0, mass_requested=0.4, mass_stored_ratio=1.0)
    low = _sample(harness, 20)
    harness.brain.armyStats.Economy_TotalProduced_Mass = (
        harness.brain.armyStats.Economy_TotalProduced_Mass + 1020
    )
    harness.brain.armyStats.Economy_Reclaimed_Mass = 1000
    harness.brain.massStored = 1000
    harness.brain.tick = 210
    windfall = harness.observe()

    assert windfall.macro.economyLedgerValid is True
    assert windfall.macro.recurringMassIncome == pytest.approx(low.macro.recurringMassIncome)
    assert windfall.macro.oneTimeMassReserve >= 1000
    assert windfall.macro.factoryTarget <= 2


def test_first_observation_reclaim_windfall_is_baseline_only_and_never_capacity() -> None:
    harness = make_harness()
    harness.brain.armyStats.Economy_TotalProduced_Mass = 1000
    harness.brain.armyStats.Economy_Reclaimed_Mass = 1000
    harness.brain.massStored = 1000
    _set_economy(harness, mass_income=100, mass_requested=0.1, mass_stored_ratio=1)
    first = harness.observe()
    assert first.macro.economyLedgerValid is False
    assert first.macro.recurringMassIncome == 0
    assert first.macro.factoryTarget == 2


def test_positive_dt_raw_income_spike_without_generated_stat_delta_is_not_capacity() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    _set_economy(harness, mass_income=1, mass_requested=0.1)
    harness.observe()
    harness.brain.tick = 10
    harness.brain.massIncome = 100
    harness.brain.massUsage = 0.1
    harness.brain.massRequested = 0.1
    observation = harness.observe()

    assert observation.macro.economyLedgerValid is True
    assert observation.macro.recurringMassIncome == 0
    assert observation.macro.factoryTarget == 2


def test_same_tick_second_observation_cannot_replace_cumulative_ledger_sample() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    _set_economy(harness, mass_income=1, mass_requested=0.4)
    _sample(harness, 2)
    harness.brain.tick = 20
    harness.brain.armyStats.Economy_TotalProduced_Mass += 20
    harness.brain.armyStats.Economy_Reclaimed_Mass += 10
    harness.brain.armyStats.Economy_TotalProduced_Energy += 300
    sampled = harness.observe()
    ledger_before = plain(harness.controller.economyLedger)
    recurring_before = sampled.macro.recurringMassIncome
    assert sampled.macro.reclaimedMassDelta == 10

    harness.brain.massIncome = 100
    repeated = harness.observe()

    assert repeated.macro.recurringMassIncome == recurring_before
    assert repeated.macro.reclaimedMassDelta == 10
    assert plain(harness.controller.economyLedger) == ledger_before


def test_army_stat_counter_reset_rebases_once_then_recovers_without_phantom_income() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    _set_economy(harness, mass_income=1, mass_requested=0.4)
    assert _sample(harness, 3).macro.economyLedgerValid is True

    harness.brain.tick = 30
    harness.brain.armyStats.Economy_TotalProduced_Mass = 1
    reset = harness.observe()
    assert reset.macro.economyLedgerValid is False
    assert reset.macro.recurringMassIncome == 0
    assert reset.macro.reclaimedMassDelta == 0

    harness.brain.tick = 40
    harness.brain.armyStats.Economy_TotalProduced_Mass += 10
    harness.brain.armyStats.Economy_TotalProduced_Energy += 300
    recovered = harness.observe()
    assert recovered.macro.economyLedgerValid is True
    assert recovered.macro.recurringMassIncome == pytest.approx(1)
    assert recovered.macro.reclaimedMassDelta == 0


def test_cumulative_excess_is_diagnostic_and_never_added_to_spendable_reserve() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    _set_economy(harness, mass_income=1, mass_requested=0.4)
    harness.brain.massStored = 25
    _sample(harness, 2)
    harness.brain.armyStats.Economy_AccumExcess_Mass += 1000
    harness.brain.tick = 20
    harness.brain.armyStats.Economy_TotalProduced_Mass += 10
    harness.brain.armyStats.Economy_TotalProduced_Energy += 300
    observation = harness.observe()

    assert observation.macro.oneTimeMassReserve == 25
    assert observation.macro.recurringMassIncome == pytest.approx(1)


def test_demand_satisfaction_uses_usage_over_requested_not_income_or_trend() -> None:
    funded = make_harness()
    funded.controller.fieldCampaignEnabled = False
    _set_economy(
        funded,
        mass_income=0.1,
        mass_requested=0.8,
        mass_usage=0.8,
        mass_trend=-0.7,
    )
    funded_observation = _sample(funded, 2)
    assert funded_observation.macro.massDemandSatisfaction == pytest.approx(1)

    stalled = make_harness()
    stalled.controller.fieldCampaignEnabled = False
    _set_economy(
        stalled,
        mass_income=1.900000214,
        mass_requested=3.846666813,
        mass_usage=1.900000214,
        mass_trend=0,
    )
    stalled_observation = _sample(stalled, 2)
    assert stalled_observation.macro.massDemandSatisfaction == pytest.approx(
        1.900000214 / 3.846666813
    )


def test_rolling_ledger_exposes_usage_storage_and_trend_in_engine_tick_units() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    _set_economy(
        harness,
        mass_income=1.2,
        mass_requested=0.8,
        mass_usage=0.7,
        mass_stored_ratio=0.4,
        mass_trend=-0.1,
        energy_income=30,
        energy_requested=20,
        energy_usage=18,
        energy_stored_ratio=0.6,
        energy_trend=12,
    )
    observation = _sample(harness, 2)
    assert observation.macro.rollingMassUsage == pytest.approx(0.7)
    assert observation.macro.rollingEnergyUsage == pytest.approx(18)
    assert observation.macro.rollingMassStoredRatio == pytest.approx(0.4)
    assert observation.macro.rollingEnergyStoredRatio == pytest.approx(0.6)
    assert observation.macro.rollingMassTrend == pytest.approx(-0.1)
    assert observation.macro.rollingEnergyTrend == pytest.approx(12)


def test_startup_full_storage_sample_does_not_jump_factory_target_two_to_eight() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    _set_economy(harness, mass_income=0.1, mass_requested=0.8, mass_stored_ratio=0.91)
    harness.brain.massUsage = 0.8
    harness.brain.massTrend = -0.7
    _sample(harness, 30)
    harness.brain.tick = 307
    harness.brain.massIncome = 4
    harness.brain.massRequested = 0.1
    harness.brain.massUsage = 0.1
    harness.brain.massStoredRatio = 1
    observation = harness.observe()

    assert observation.macro.recurringMassIncome < 1
    assert observation.macro.factoryTarget == 2


def test_supported_factory_target_rises_only_after_window_and_can_fall_again() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    _set_economy(harness, mass_income=2.5, mass_requested=0.2, mass_stored_ratio=1)
    high = _sample(harness, 40)
    assert high.macro.factoryTarget >= 4

    _set_economy(harness, mass_income=0.7, mass_requested=0.6, mass_stored_ratio=0.2)
    low = _sample(harness, 40, start=500)
    assert low.macro.factoryTarget < high.macro.factoryTarget
    assert low.macro.factoryTarget == 2


def test_factory_completion_and_pending_are_counted_once_after_reconcile() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    engineer = _engineer(harness, 70, 14)
    factories = [_live_factory(harness, 80), _live_factory(harness, 81)]
    harness.brain.units = harness.lua.table_from([engineer, *factories])
    _set_economy(harness, mass_income=1.5, mass_requested=0.3, mass_stored_ratio=1)
    observation = harness.observe()
    position = plain(observation.placements.land_factory[1])
    execute_intents(harness, [{
        "kind": "build_structure",
        "actorToken": "70:1",
        "buildRole": "land_factory",
        "position": position,
        "priority": 21,
        "reason": "production_saturation",
    }], observation)
    assert harness.controller.pending["70:1"] is not None

    completed = _live_factory(harness, 82)
    completed.options.position = lua_value(harness.lua, position)
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from([engineer, *factories, completed])
    harness.brain.tick = 20
    refreshed = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, refreshed)

    assert harness.controller.pending["70:1"] is None
    assert refreshed.macro.completedFactories == 3
    assert refreshed.macro.buildingFactories == 0
    assert refreshed.macro.factoryPhysicalCount == 3
    assert refreshed.macro.factoryTarget <= 3


@pytest.mark.parametrize("seed", range(5))
def test_budget_admits_only_funded_factory_queues_deterministically(seed: int) -> None:
    snapshot = _policy_allocator_snapshot("land_factory", "land_factory", "land_factory")
    factories = [unit for unit in snapshot["units"] if unit["role"] == "land_factory"]
    for unit in factories:
        unit["needsRally"] = False
    random.Random(seed).shuffle(snapshot["units"])
    snapshot["macro"].update(
        availableRecurringMass=0.5,
        availableRecurringEnergy=2.5,
        factoryFundedCount=1,
    )
    builds = intents_of(decide(snapshot), "factory_build")
    assert len(builds) == 1
    assert builds[0]["actorToken"] == sorted(unit["token"] for unit in factories)[0]
    assert builds[0]["buildRole"] in {"tank", "artillery", "anti_air"}


@pytest.mark.parametrize(
    ("mass_budget", "energy_budget", "expected"),
    [(0.799, 7, 0), (0.8, 6.999, 0), (0.8, 7, 1)],
)
def test_acu_structure_admission_uses_its_exact_double_engineer_build_rate(
    mass_budget: float,
    energy_budget: float,
    expected: int,
) -> None:
    snapshot = base_snapshot()
    snapshot["units"][0]["buildRate"] = 10
    snapshot["economy"].update(
        massIncome=mass_budget,
        massRequested=0,
        energyIncome=energy_budget,
        energyRequested=0,
    )
    snapshot["macro"] = dict(_policy_allocator_snapshot()["macro"])
    snapshot["macro"].update(
        availableRecurringMass=mass_budget,
        availableRecurringEnergy=energy_budget,
        oneTimeMassReserve=0,
        oneTimeEnergyReserve=0,
    )

    opening = [
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("reason") == "opening_factory"
    ]

    assert len(opening) == expected


def test_engineer_structure_admission_keeps_exact_engineer_rate_boundary() -> None:
    snapshot = _policy_allocator_snapshot("engineer")
    engineer = next(unit for unit in snapshot["units"] if unit["role"] == "engineer")
    engineer["buildRate"] = 5
    snapshot["macro"].update(
        availableRecurringMass=0.4,
        availableRecurringEnergy=3.5,
        oneTimeMassReserve=0,
        oneTimeEnergyReserve=0,
        factoryTarget=3,
        factoryDemand=3,
    )

    factories = [
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "land_factory"
    ]

    assert [(intent["actorToken"], intent["reason"]) for intent in factories] == [
        (engineer["token"], "production_saturation")
    ]


@pytest.mark.parametrize("build_rate", [0, -1, float("nan"), float("inf"), "bad"])
def test_structure_admission_fails_closed_on_malformed_actor_build_rate(
    build_rate: Any,
) -> None:
    snapshot = base_snapshot()
    snapshot["units"][0]["buildRate"] = build_rate
    snapshot["macro"] = dict(_policy_allocator_snapshot()["macro"])
    snapshot["macro"].update(
        availableRecurringMass=100,
        availableRecurringEnergy=100,
        oneTimeMassReserve=10000,
        oneTimeEnergyReserve=10000,
    )

    opening = [
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("reason") == "opening_factory"
    ]

    assert opening == []


def _air_screen_allocator_snapshot(
    *,
    interceptors: int = 0,
    air_factories: int = 1,
) -> dict[str, Any]:
    snapshot = _policy_allocator_snapshot(
        *(["air_factory"] * air_factories),
        *(["interceptor"] * interceptors),
    )
    snapshot["sites"]["mass"] = []
    snapshot["sites"]["hydro"] = []
    snapshot["macro"].update(
        factoryFundedCount=0,
        availableRecurringMass=0,
        availableRecurringEnergy=0,
        oneTimeMassReserve=0,
        oneTimeEnergyReserve=0,
    )
    return snapshot


@pytest.mark.parametrize("available_energy, expected", [(8.999, 0), (9.0, 1)])
def test_interceptor_admission_uses_exact_nine_energy_per_tick(
    available_energy: float,
    expected: int,
) -> None:
    snapshot = _air_screen_allocator_snapshot()
    snapshot["macro"].update(
        availableRecurringMass=0.2,
        availableRecurringEnergy=available_energy,
    )
    builds = [
        intent for intent in intents_of(decide(snapshot), "factory_build")
        if intent.get("buildRole") == "interceptor"
    ]
    assert len(builds) == expected


def test_artifact_air_screen_is_bank_funded_when_generic_factory_slots_are_zero() -> None:
    snapshot = _air_screen_allocator_snapshot()
    snapshot["macro"].update(
        availableRecurringMass=1.700 - 1.273,
        availableRecurringEnergy=16 - 10.773,
        oneTimeMassReserve=696,
        oneTimeEnergyReserve=2654,
    )

    builds = [
        intent for intent in intents_of(decide(snapshot), "factory_build")
        if intent.get("reason") == "persistent_air_screen"
    ]

    assert [(intent["buildRole"], intent["reason"]) for intent in builds] == [
        ("interceptor", "persistent_air_screen")
    ]


@pytest.mark.parametrize(
    ("mass", "energy", "bank_mass", "bank_energy", "expected"),
    [
        (0.2, 9, 0, 0, 1),
        (0.199, 9, 0, 0, 0),
        (0.2, 8.999, 0, 0, 0),
        (0, 0, 50, 2250, 1),
        (0, 0, 49.999, 2250, 0),
        (0, 0, 50, 2249.999, 0),
    ],
)
def test_air_screen_protected_lane_requires_exact_recurring_or_full_unit_bank(
    mass: float,
    energy: float,
    bank_mass: float,
    bank_energy: float,
    expected: int,
) -> None:
    snapshot = _air_screen_allocator_snapshot()
    snapshot["macro"].update(
        availableRecurringMass=mass,
        availableRecurringEnergy=energy,
        oneTimeMassReserve=bank_mass,
        oneTimeEnergyReserve=bank_energy,
    )

    builds = [
        intent for intent in intents_of(decide(snapshot), "factory_build")
        if intent.get("reason") == "persistent_air_screen"
    ]

    assert len(builds) == expected


def test_pending_interceptor_occupies_the_single_air_screen_lane() -> None:
    snapshot = _air_screen_allocator_snapshot(air_factories=2)
    factories = sorted(
        (unit for unit in snapshot["units"] if unit["role"] == "air_factory"),
        key=lambda unit: unit["token"],
    )
    snapshot["pending"].append({
        "kind": "factory_build",
        "actorToken": factories[0]["token"],
        "buildRole": "interceptor",
        "phase": "accepted",
    })
    snapshot["macro"].update(
        oneTimeMassReserve=100,
        oneTimeEnergyReserve=4500,
    )

    builds = [
        intent for intent in intents_of(decide(snapshot), "factory_build")
        if intent.get("reason") == "persistent_air_screen"
    ]

    assert builds == []


@pytest.mark.parametrize(
    ("completed", "expected"),
    [(0, 1), (1, 1), (3, 1), (4, 0)],
)
def test_completed_interceptor_cycles_repeat_one_at_a_time_until_four(
    completed: int,
    expected: int,
) -> None:
    snapshot = _air_screen_allocator_snapshot(
        interceptors=completed,
        air_factories=2,
    )
    snapshot["macro"].update(
        oneTimeMassReserve=50,
        oneTimeEnergyReserve=2250,
    )

    builds = [
        intent for intent in intents_of(decide(snapshot), "factory_build")
        if intent.get("reason") == "persistent_air_screen"
    ]

    assert len(builds) == expected


def test_air_screen_bank_is_reserved_before_speculative_mex() -> None:
    snapshot = _air_screen_allocator_snapshot()
    engineer = next(unit for unit in snapshot["units"] if unit["role"] == "engineer")
    engineer["canBuild"]["mass_extractor"] = True
    snapshot["sites"]["mass"] = [mass_site("speculative", 25, 20, frontier=True)]
    snapshot["macro"].update(
        expansionOpportunityCount=1,
        expansionRecurringMassBudget=0,
        expansionRecurringEnergyBudget=0,
        oneTimeMassReserve=50,
        oneTimeEnergyReserve=2250,
    )

    result = decide(snapshot)

    assert [
        intent["buildRole"] for intent in intents_of(result, "factory_build")
        if intent.get("reason") == "persistent_air_screen"
    ] == ["interceptor"]
    assert not [
        intent for intent in intents_of(result, "build_structure")
        if intent.get("reason") == "frontier_expansion"
    ]


def test_funded_air_land_and_expansion_lanes_use_distinct_actors() -> None:
    snapshot = _policy_allocator_snapshot(
        "air_factory", "land_factory", "land_factory", "engineer",
    )
    snapshot["sites"]["hydro"] = []
    snapshot["sites"]["mass"] = [mass_site("funded", 25, 20, frontier=True)]
    snapshot["macro"].update(
        factoryFundedCount=0,
        expansionOpportunityCount=1,
        expansionRecurringMassBudget=0,
        expansionRecurringEnergyBudget=0,
        availableRecurringMass=0,
        availableRecurringEnergy=0,
        oneTimeMassReserve=150,
        oneTimeEnergyReserve=3000,
    )

    result = decide(snapshot)
    air = [
        intent for intent in intents_of(result, "factory_build")
        if intent.get("reason") == "persistent_air_screen"
    ]
    land = [
        intent for intent in intents_of(result, "factory_build")
        if intent.get("buildRole") in {"tank", "artillery", "anti_air", "lab"}
    ]
    mex = [
        intent for intent in intents_of(result, "build_structure")
        if intent.get("reason") == "frontier_expansion"
    ]

    assert len(air) == len(land) == len(mex) == 1
    assert len({air[0]["actorToken"], land[0]["actorToken"], mex[0]["actorToken"]}) == 3


@pytest.mark.parametrize("contact", [False, True])
def test_contact_does_not_disable_a_funded_air_screen_lane(contact: bool) -> None:
    snapshot = _air_screen_allocator_snapshot()
    snapshot["macro"].update(
        oneTimeMassReserve=50,
        oneTimeEnergyReserve=2250,
    )
    if contact:
        snapshot["enemyContact"] = {"position": [12, 2, 12], "immediate": True}

    builds = [
        intent for intent in intents_of(decide(snapshot), "factory_build")
        if intent.get("reason") == "persistent_air_screen"
    ]

    assert len(builds) == 1


def test_air_screen_protected_lane_fails_closed_without_a_valid_economy_sample() -> None:
    snapshot = _air_screen_allocator_snapshot()
    snapshot["macro"].update(
        economyLedgerValid=False,
        economyInputValid=False,
        oneTimeMassReserve=5000,
        oneTimeEnergyReserve=50000,
    )

    builds = [
        intent for intent in intents_of(decide(snapshot), "factory_build")
        if intent.get("reason") == "persistent_air_screen"
    ]

    assert builds == []


def test_positive_payback_mex_preempts_unfunded_combat_queue() -> None:
    snapshot = _policy_allocator_snapshot("land_factory")
    snapshot["sites"]["mass"].append(mass_site("payback", 25, 20, frontier=True))
    snapshot["macro"].update(
        availableRecurringMass=0.35,
        availableRecurringEnergy=3.1,
        oneTimeMassReserve=0,
        oneTimeEnergyReserve=0,
        expansionOpportunityCount=1,
        factoryFundedCount=1,
    )
    result = decide(snapshot)
    builds = [i for i in intents_of(result, "build_structure") if i.get("buildRole") == "mass_extractor"]
    assert [(intent["siteKey"], intent["reason"]) for intent in builds] == [("payback", "frontier_expansion")]
    assert intents_of(result, "factory_build") == []


@pytest.mark.parametrize(
    ("mass_headroom", "energy_headroom", "expected"),
    [(0.299, 3, 0), (0.3, 2.999, 0), (0.3, 3, 1)],
)
def test_expansion_lane_can_spend_its_exact_reserved_headroom_once(
    mass_headroom: float,
    energy_headroom: float,
    expected: int,
) -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    harness.brain.massStored = 0
    harness.brain.energyStored = 0
    harness.brain.units = harness.lua.table_from([_engineer(harness, 70, 20)])
    harness.controller.markers.hydro = harness.lua.table_from([])
    harness.controller.markers.mass = lua_value(harness.lua, [{
        "key": "funded", "name": "funded", "kind": "mass",
        "position": [30, 2, 20], "distance": 20,
        "reachable": True, "engineerReachable": True,
        "landReachable": True, "localSite": False,
    }])
    _set_economy(
        harness,
        mass_income=1,
        mass_requested=1 - mass_headroom,
        energy_income=20,
        energy_requested=20 - energy_headroom,
        mass_usage=1 - mass_headroom,
        energy_usage=20 - energy_headroom,
    )
    observation = _sample(harness, 2)
    assert observation.macro.availableRecurringMass == pytest.approx(0)
    assert observation.macro.availableRecurringEnergy == pytest.approx(0)

    mex = [
        intent for intent in intents_of(
            plain(harness.lua.globals().Policy.Decide(observation)),
            "build_structure",
        )
        if intent.get("buildRole") == "mass_extractor"
    ]

    assert [(intent["actorToken"], intent["siteKey"]) for intent in mex] == (
        [("70:1", "funded")] if expected else []
    )


@pytest.mark.parametrize("seed", range(5))
def test_multiple_disjoint_expansions_continue_despite_active_campaign(seed: int) -> None:
    snapshot = _policy_allocator_snapshot("engineer", "engineer", "engineer")
    engineers = [unit for unit in snapshot["units"] if unit["role"] == "engineer"]
    for index, engineer in enumerate(sorted(engineers, key=lambda unit: unit["token"])):
        engineer["position"] = [20 + index * 100, 2, 20]
    sites = [
        mass_site("campaign-a", 22, 20, frontier=True),
        mass_site("independent-b", 122, 20),
        mass_site("independent-c", 222, 20),
    ]
    for site in sites:
        site.update(engineerReachable=True, landReachable=True)
    random.Random(seed).shuffle(sites)
    random.Random(seed + 11).shuffle(snapshot["units"])
    snapshot["sites"]["mass"] = sites
    snapshot["macro"].update(
        campaignEnabled=True,
        campaignState="active",
        campaignCluster="cluster-a",
        campaignMemberKeys=["campaign-a"],
        availableRecurringMass=1.2,
        availableRecurringEnergy=12,
        expansionOpportunityCount=3,
        engineerTarget=6,
        engineerDemand=6,
    )
    builds = [
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "mass_extractor"
    ]
    assert sorted(intent["siteKey"] for intent in builds) == [
        "campaign-a", "independent-b", "independent-c"
    ]
    assert len({intent["actorToken"] for intent in builds}) == 3
    assert sum(intent.get("clusterKey") == "cluster-a" for intent in builds) == 1


def test_expansion_request_carries_bounded_travel_build_and_payback_units() -> None:
    snapshot = _policy_allocator_snapshot()
    engineer = next(unit for unit in snapshot["units"] if unit["role"] == "engineer")
    engineer["position"] = [20, 2, 20]
    engineer["moveSpeed"] = 1.9
    snapshot["sites"]["mass"] = [mass_site("roi", 217, 20, frontier=True)]
    snapshot["macro"].update(
        expansionOpportunityCount=1,
        availableRecurringMass=0.3,
        availableRecurringEnergy=3,
    )
    intent = next(
        item for item in intents_of(decide(snapshot), "build_structure")
        if item.get("buildRole") == "mass_extractor"
    )
    assert intent["estimatedTravelTicks"] == pytest.approx(197 / 1.9 * 10)
    assert intent["estimatedBuildTicks"] == 120
    assert intent["estimatedPaybackTicks"] == 180
    assert intent["estimatedRoiTicks"] == pytest.approx(197 / 1.9 * 10 + 300)


def test_40km_corner_opportunity_remains_backlog_but_exceeds_funded_roi_horizon() -> None:
    snapshot = _policy_allocator_snapshot("engineer")
    engineers = [unit for unit in snapshot["units"] if unit["role"] == "engineer"]
    for engineer in engineers:
        engineer["position"] = [20, 2, 20]
        engineer["moveSpeed"] = 1.9
    snapshot["sites"]["mass"] = [
        mass_site("edge", 2000, 20),
        mass_site("corner", 2040, 2040),
    ]
    snapshot["macro"].update(
        expansionOpportunityCount=2,
        availableRecurringMass=0.6,
        availableRecurringEnergy=6,
    )
    builds = [
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "mass_extractor"
    ]
    assert [intent["siteKey"] for intent in builds] == ["edge"]
    assert builds[0]["estimatedRoiTicks"] < 12000


def test_zero_bank_stall_denies_remote_mex_but_bank_funds_exactly_one_recovery_lane() -> None:
    snapshot = _policy_allocator_snapshot("engineer", "engineer")
    snapshot["sites"]["mass"].extend([
        mass_site("near", 30, 20, frontier=True),
        mass_site("remote", 1000, 20, frontier=True),
    ])
    snapshot["macro"].update(
        expansionOpportunityCount=2,
        availableRecurringMass=0,
        availableRecurringEnergy=0,
        oneTimeMassReserve=0,
        oneTimeEnergyReserve=0,
    )
    assert [
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "mass_extractor"
    ] == []

    snapshot["macro"].update(oneTimeMassReserve=36, oneTimeEnergyReserve=360)
    funded = [
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "mass_extractor"
    ]
    assert [(intent["siteKey"], intent["reason"]) for intent in funded] == [
        ("near", "frontier_expansion")
    ]


def test_travelling_mex_reserves_its_one_time_bank_before_next_policy_cycle() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    harness.brain.massStored = 36
    harness.brain.energyStored = 360
    harness.controller.markers.mass = lua_value(harness.lua, [
        {
            "key": "near", "name": "near", "kind": "mass",
            "position": [40, 2, 20], "distance": 30,
            "reachable": True, "engineerReachable": True,
            "landReachable": True, "localSite": False,
        },
        {
            "key": "far", "name": "far", "kind": "mass",
            "position": [80, 2, 20], "distance": 70,
            "reachable": True, "engineerReachable": True,
            "landReachable": True, "localSite": False,
        },
    ])
    engineers = [_engineer(harness, 70, 20), _engineer(harness, 71, 22)]
    harness.brain.units = harness.lua.table_from(engineers)
    observation = harness.observe()
    first = [
        intent for intent in plain(harness.lua.globals().Policy.Decide(observation))
        if intent.get("kind") == "build_structure"
        and intent.get("buildRole") == "mass_extractor"
    ]
    assert len(first) == 1
    execute_intents(harness, first, observation)

    refreshed = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, refreshed)
    assert refreshed.macro.oneTimeMassReserve == 0
    assert refreshed.macro.oneTimeEnergyReserve == 0
    second = [
        intent for intent in plain(harness.lua.globals().Policy.Decide(refreshed))
        if intent.get("kind") == "build_structure"
        and intent.get("buildRole") == "mass_extractor"
    ]
    assert second == []


def _accepted_mex_commitment(
    *, fraction: float = 0.5, second_engineer: bool = False
) -> tuple[Any, Any, Any, Any, str]:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    harness.brain.massStored = 36
    harness.brain.energyStored = 360
    engineer = _engineer(harness, 70, 20)
    units = [engineer]
    if second_engineer:
        units.append(_engineer(harness, 71, 22))
    harness.brain.units = harness.lua.table_from(units)
    observation = harness.observe()
    site = plain(observation.sites.mass)[0]
    execute_intents(harness, [{
        "kind": "build_structure",
        "actorToken": "70:1",
        "buildRole": "mass_extractor",
        "siteKey": site["key"],
        "position": site["position"],
        "priority": 22,
        "reason": "frontier_expansion",
    }], observation)

    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Building": True})
    foundation = harness.unit(
        entityId=90,
        blueprintId="ueb1103",
        position=site["position"],
        fraction=fraction,
    )
    harness.brain.units = harness.lua.table_from([*units, foundation])
    harness.brain.tick = 10
    refreshed = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, refreshed)
    return harness, engineer, foundation, refreshed, site["key"]


def test_accepted_half_built_mex_reserves_only_its_remaining_one_time_cost() -> None:
    harness, _, _, refreshed, _ = _accepted_mex_commitment()

    assert refreshed.macro.oneTimeMassReserve == pytest.approx(18)
    assert refreshed.macro.oneTimeEnergyReserve == pytest.approx(180)


def test_real_policy_shaped_assistant_shares_builders_target_local_cost_lease() -> None:
    harness, _, _, observation, site_key = _accepted_mex_commitment(
        second_engineer=True,
    )
    site = next(
        candidate for candidate in plain(observation.sites.mass)
        if candidate.get("targetToken") == "90:1"
    )
    position = site["position"]
    placement_key = (
        f"Placement:{round(position[0] * 1000)}:{round(position[2] * 1000)}"
    )
    assist = {
        "kind": "assist_structure",
        "actorToken": "71:1",
        "buildRole": "mass_extractor",
        "targetToken": site["targetToken"],
        "placementKey": placement_key,
        "position": position,
        "priority": 18,
        "reason": "finish_orphan",
    }
    assert "siteKey" not in assist

    execute_intents(harness, [assist], observation)
    assert len(harness.calls.guard) == 1
    assert harness.controller.pending["71:1"].siteKey is None
    assert harness.controller.pending["71:1"].placementKey == placement_key

    shared = harness.observe()

    assert shared.macro.oneTimeMassReserve == pytest.approx(18)
    assert shared.macro.oneTimeEnergyReserve == pytest.approx(180)
    assert len(plain(harness.controller.economyCommitmentLeases)) == 1
    assert harness.controller.reservations[site_key].actorToken == "70:1"

    # Removing either worker cannot release a target lease still owned by the
    # other operation; removing the final owner releases it exactly once.
    harness.controller.pending["70:1"] = None
    assistant_only = harness.observe()
    assert assistant_only.macro.oneTimeMassReserve == pytest.approx(18)
    harness.controller.pending["71:1"] = None
    released = harness.observe()
    assert released.macro.oneTimeMassReserve == pytest.approx(36)


@pytest.mark.parametrize("bad_fraction", [0.25, -0.1, 1.5, "malformed"])
def test_target_commitment_progress_is_monotonic_and_bad_fraction_fails_closed(
    bad_fraction: Any,
) -> None:
    harness, _, _, _, _ = _accepted_mex_commitment()
    operation = harness.controller.pending["70:1"]
    assert operation.lastFraction == pytest.approx(0.5)

    operation.lastFraction = bad_fraction
    malformed = harness.observe()

    assert malformed.macro.oneTimeMassReserve == pytest.approx(18)
    assert malformed.macro.oneTimeEnergyReserve == pytest.approx(180)


def test_completed_target_releases_its_commitment_lease_after_reconcile() -> None:
    harness, engineer, foundation, _, _ = _accepted_mex_commitment()
    foundation.options.fraction = 1
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.tick = 20

    completed = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, completed)

    assert harness.controller.pending["70:1"] is None
    assert completed.macro.oneTimeMassReserve == pytest.approx(36)
    assert completed.macro.oneTimeEnergyReserve == pytest.approx(360)


def test_cancelling_target_retains_bank_lease_through_clear_retry_until_idle_release() -> None:
    harness, engineer, _, _, site_key = _accepted_mex_commitment(fraction=0)
    operation = harness.controller.pending["70:1"]
    operation.deadlineTick = 20
    harness.calls.failClear = True
    harness.brain.tick = 20

    timed_out = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, timed_out)

    assert harness.controller.pending["70:1"].phase == "cancelling"
    assert harness.controller.reservations[site_key].actorToken == "70:1"
    assert timed_out.macro.oneTimeMassReserve == 0

    harness.calls.failClear = False
    harness.brain.tick = 21
    retry = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, retry)
    assert harness.controller.pending["70:1"] is not None
    assert retry.macro.oneTimeMassReserve == 0

    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.tick = 22
    released = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, released)
    assert harness.controller.pending["70:1"] is None
    assert harness.controller.reservations[site_key] is None
    assert released.macro.oneTimeMassReserve == pytest.approx(36)


@pytest.mark.parametrize("extent", [256, 512, 1024, 2048])
def test_reachable_unowned_large_map_sites_are_allocator_opportunities(extent: int) -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    harness.controller.markers.mass = lua_value(harness.lua, [
        {
            "key": f"m-{extent}", "name": f"m-{extent}", "kind": "mass",
            "position": [extent - 20, 2, 20], "distance": extent - 30,
            "reachable": True, "engineerReachable": True, "landReachable": True,
            "localSite": False,
        }
    ])
    observation = harness.observe()
    assert observation.macro.expansionOpportunityCount == 1
    assert observation.macro.engineerTarget >= 2


def test_hundred_markers_do_not_create_fifty_engineer_requests() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    harness.controller.markers.mass = lua_value(harness.lua, [
        {
            "key": f"m-{index}", "name": f"m-{index}", "kind": "mass",
            "position": [20 + index * 2, 2, 20], "distance": 10 + index * 2,
            "reachable": True, "engineerReachable": True, "landReachable": True,
            "localSite": False,
        }
        for index in range(100)
    ])
    _set_economy(harness, mass_income=1.9, mass_requested=1.0)
    observation = _sample(harness, 4)
    assert observation.macro.expansionOpportunityCount == 100
    assert observation.macro.engineerTarget == 2


def test_stalled_backlog_does_not_displace_a_funded_combat_queue_after_engineer_floor() -> None:
    snapshot = _policy_allocator_snapshot("engineer", "land_factory")
    snapshot["sites"]["mass"].append(mass_site("remote", 300, 20, frontier=True))
    snapshot["economy"].update(
        massIncome=0.4,
        massRequested=0.8,
        massUsage=0.4,
        massTrend=-0.4,
        massStoredRatio=0,
    )
    snapshot["macro"].update(
        recurringMassIncome=0.4,
        rollingMassRequested=0.8,
        availableRecurringMass=0.4,
        expansionOpportunityCount=1,
        engineerTarget=3,
        engineerDemand=3,
        unlockingEngineerNeeded=True,
        factoryFundedCount=1,
    )
    result = decide(snapshot)
    factory = intents_of(result, "factory_build")
    assert [(intent["buildRole"], intent["reason"]) for intent in factory] == [
        ("tank", "continuous_land_production"),
        ("engineer", "unlock_profitable_expansion"),
    ]


def test_remote_backlog_reserves_local_reclaimer_and_reclaim_windfall_is_not_recurring() -> None:
    snapshot = _policy_allocator_snapshot("engineer")
    engineers = sorted(
        [unit for unit in snapshot["units"] if unit["role"] == "engineer"],
        key=lambda unit: unit["token"],
    )
    engineers[0]["position"] = [20, 2, 20]
    engineers[1]["position"] = [300, 2, 20]
    snapshot["sites"]["mass"] = [mass_site("remote", 305, 20, frontier=True)]
    snapshot["reclaim"] = [{
        "key": "local-prop", "position": [21, 2, 20], "mass": 400,
        "reserved": False, "observerToken": engineers[0]["token"],
        "visionRadius": 10, "observedTick": 0,
    }]
    snapshot["macro"].update(
        expansionOpportunityCount=1,
        availableRecurringMass=0.6,
        availableRecurringEnergy=8,
        oneTimeMassReserve=400,
    )
    result = decide(snapshot)
    reclaim = intents_of(result, "reclaim")
    mex = [i for i in intents_of(result, "build_structure") if i.get("buildRole") == "mass_extractor"]
    assert [(i["actorToken"], i["targetKey"]) for i in reclaim] == [(engineers[0]["token"], "local-prop")]
    assert [(i["actorToken"], i["siteKey"]) for i in mex] == [(engineers[1]["token"], "remote")]


@pytest.mark.parametrize("seed", range(4))
def test_blocked_route_uses_next_roi_site_without_duplicate(seed: int) -> None:
    snapshot = _policy_allocator_snapshot("engineer", "engineer")
    sites = [
        mass_site("near-blocked", 22, 20, frontier=True, buildable=False),
        mass_site("near-unreachable", 23, 20, frontier=True, reachable=False),
        mass_site("next", 40, 20),
        mass_site("far", 80, 20),
    ]
    for site in sites:
        site.update(engineerReachable=site["reachable"], landReachable=site["reachable"])
    random.Random(seed).shuffle(sites)
    snapshot["sites"]["mass"] = sites
    snapshot["macro"].update(
        expansionOpportunityCount=2,
        availableRecurringMass=0.6,
        availableRecurringEnergy=6,
    )
    builds = [
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "mass_extractor"
    ]
    assert sorted(intent["siteKey"] for intent in builds) == ["far", "next"]
    assert len({intent["actorToken"] for intent in builds}) == 2


def test_reconcile_blocked_site_is_visible_before_same_step_policy_and_selects_alternate() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    harness.controller.markers.hydro = harness.lua.table_from([])
    _set_economy(
        harness,
        mass_income=2,
        mass_requested=0.5,
        energy_income=30,
        energy_requested=10,
    )
    harness.brain.massStored = 100
    harness.brain.energyStored = 1000
    local_positions = [[12, 2, 20], [14, 2, 20], [16, 2, 20], [18, 2, 20]]
    markers = [
        {"Name": f"local-{i}", "key": f"local-{i}", "name": f"local-{i}", "kind": "mass", "Position": pos, "position": pos, "distance": pos[0] - 10, "reachable": True, "engineerReachable": True, "landReachable": True, "localSite": True}
        for i, pos in enumerate(local_positions)
    ] + [
        {"Name": "near", "key": "near", "name": "near", "kind": "mass", "Position": [80, 2, 20], "position": [80, 2, 20], "distance": 70, "reachable": True, "engineerReachable": True, "landReachable": True, "localSite": False},
        {"Name": "far", "key": "far", "name": "far", "kind": "mass", "Position": [100, 2, 20], "position": [100, 2, 20], "distance": 90, "reachable": True, "engineerReachable": True, "landReachable": True, "localSite": False},
    ]
    harness.controller.markers.mass = lua_value(harness.lua, markers)
    engineer = _engineer(harness, 70, 30)
    structures = [
        harness.unit(entityId=100 + i, blueprintId="ueb1103", position=position)
        for i, position in enumerate(local_positions)
    ] + [_live_factory(harness, 200, idle=False), _live_factory(harness, 201, idle=False)]
    harness.brain.units = harness.lua.table_from([engineer, *structures])
    first = harness.observe()
    near = next(site for site in plain(first.sites.mass) if site["key"] == "near")
    execute_intents(harness, [{
        "kind": "build_structure", "actorToken": "70:1", "buildRole": "mass_extractor",
        "siteKey": "near", "position": near["position"], "priority": 22,
        "reason": "frontier_expansion",
    }], first)
    assert len(harness.calls.buildMobile) == 1
    harness.brain.tick = 20
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.own) == 2
    assert len(harness.calls.enemy) == 2
    assert len(harness.calls.buildMobile) == 2
    assert plain(harness.calls.buildMobile[2].position)[0] == 100


def test_energy_recovery_is_budgeted_before_factory_queue_and_tech() -> None:
    snapshot = _policy_allocator_snapshot("land_factory", "air_factory", "hydrocarbon")
    snapshot["economy"].update(
        energyIncome=10,
        energyRequested=12,
        energyUsage=10,
        energyTrend=-2,
        energyStoredRatio=0.1,
    )
    snapshot["macro"].update(
        recurringEnergyIncome=10,
        rollingEnergyRequested=12,
        availableRecurringEnergy=3,
        oneTimeMassReserve=0,
        oneTimeEnergyReserve=0,
        techAdmission="admitted",
        factoryFundedCount=2,
    )
    result = decide(snapshot)
    structures = intents_of(result, "build_structure")
    assert any(intent.get("buildRole") == "power_generator" for intent in structures)
    assert intents_of(result, "factory_upgrade") == []
    assert intents_of(result, "factory_build") == []


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("site_x", [30, 2000])
def test_required_energy_recovery_reserves_the_only_engineer_before_expansion(
    seed: int,
    site_x: float,
) -> None:
    snapshot = _policy_allocator_snapshot()
    engineer = next(unit for unit in snapshot["units"] if unit["role"] == "engineer")
    engineer["position"] = [20, 2, 20]
    engineer["moveSpeed"] = 1.9
    snapshot["sites"]["mass"].append(mass_site("opportunity", site_x, 20))
    snapshot["economy"].update(
        energyIncome=10,
        energyRequested=12,
        energyUsage=10,
        energyTrend=-2,
        energyStoredRatio=0.1,
    )
    snapshot["macro"].update(
        recurringMassIncome=1,
        recurringEnergyIncome=10,
        rollingMassRequested=0.7,
        rollingEnergyRequested=7,
        availableRecurringMass=0.3,
        availableRecurringEnergy=3,
        expansionRecurringMassBudget=0.3,
        expansionRecurringEnergyBudget=3,
        oneTimeMassReserve=0,
        oneTimeEnergyReserve=0,
        expansionOpportunityCount=1,
    )
    random.Random(seed).shuffle(snapshot["units"])

    economic = _economic(decide(snapshot))
    structures = intents_of(economic, "build_structure")

    assert [
        (intent["actorToken"], intent["buildRole"], intent["reason"])
        for intent in structures
    ] == [(engineer["token"], "power_generator", "energy_recovery")]
    assert not any(
        intent.get("buildRole") == "mass_extractor" for intent in economic
    )


def test_t2_admission_uses_forecast_fit_not_exact_mex_count() -> None:
    fit = _policy_allocator_snapshot(
        "mass_extractor", "mass_extractor", "mass_extractor", "mass_extractor",
        "land_factory", "air_factory", "hydrocarbon",
    )
    fit["macro"].update(
        ownedMexCount=8,
        recurringMassIncome=2.2,
        recurringEnergyIncome=35,
        availableRecurringMass=1.2,
        availableRecurringEnergy=10,
        oneTimeMassReserve=1200,
        oneTimeEnergyReserve=10000,
        techAdmission="admitted",
        techEtaTicks=300,
    )
    assert len(intents_of(decide(fit), "factory_upgrade")) == 1

    committed = _policy_allocator_snapshot(
        *("mass_extractor",) * 12,
        "land_factory", "air_factory", "hydrocarbon",
    )
    committed["macro"].update(
        ownedMexCount=12,
        recurringMassIncome=2.5,
        recurringEnergyIncome=35,
        availableRecurringMass=0.1,
        availableRecurringEnergy=1,
        activeCommittedMassDrain=2.4,
        activeCommittedEnergyDrain=34,
        oneTimeMassReserve=1200,
        oneTimeEnergyReserve=10000,
        techAdmission="deferred",
        techEtaTicks=-1,
    )
    assert intents_of(decide(committed), "factory_upgrade") == []


def test_t2_forecast_fit_does_not_require_a_hydro_marker_or_storage_ratio_capacity() -> None:
    snapshot = _policy_allocator_snapshot(
        "mass_extractor", "mass_extractor", "mass_extractor", "mass_extractor",
        "land_factory", "air_factory",
    )
    snapshot["economy"].update(massStoredRatio=0.1, energyStoredRatio=0.1)
    snapshot["macro"].update(
        ownedMexCount=8,
        availableRecurringMass=1.2,
        availableRecurringEnergy=10,
        oneTimeMassReserve=1200,
        oneTimeEnergyReserve=10000,
        techAdmission="admitted",
        techEtaTicks=300,
    )
    assert len(intents_of(decide(snapshot), "factory_upgrade")) == 1


@pytest.mark.parametrize("stored_ratio", [0.1, 0.9])
def test_t2_admission_uses_absolute_bank_not_factory_inflated_storage_ratio(
    stored_ratio: float,
) -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    harness.brain.units = harness.lua.table_from([
        _live_factory(harness, 10),
        _live_factory(harness, 11),
        _live_factory(harness, 12, domain="air"),
    ])
    harness.brain.massStored = 1200
    harness.brain.energyStored = 10000
    _set_economy(
        harness,
        mass_income=3,
        mass_requested=0.2,
        energy_income=40,
        energy_requested=5,
        mass_stored_ratio=stored_ratio,
        energy_stored_ratio=stored_ratio,
    )
    observation = _sample(harness, 2)
    assert observation.macro.techAdmission == "admitted"


@pytest.mark.parametrize("field", ["massIncome", "massRequested", "energyIncome", "energyRequested"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_malformed_rolling_economy_fails_closed(field: str, value: float) -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    _set_economy(harness, mass_income=1.5, mass_requested=0.5)
    setattr(harness.brain, field, value)
    observation = harness.observe()
    assert observation.macro.economyLedgerValid is False
    assert observation.macro.factoryFundedCount == 0
    assert observation.macro.techAdmission == "invalid_economy"


def test_campaign_rebuilding_does_not_absorb_unordered_new_combat() -> None:
    harness, _, _, combat, observation = start_campaign(total=24, aa=2)
    intent = next(intent for intent in plain(harness.lua.globals().Policy.Decide(observation)) if intent["kind"] == "field_campaign")
    execute_intents(harness, [intent], observation)
    harness.controller.fieldCampaign.state = "rebuilding"
    newcomer = harness.unit(entityId=9999, blueprintId="uel0201", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from([*list(harness.brain.units.values()), newcomer])
    refreshed = reconcile(harness)
    record = next(unit for unit in plain(refreshed.units) if unit["token"] == "9999:1")
    assert record["fieldCohort"] is False
    assert record["assignedToWave"] is False
    assert record["availableForWave"] is True


@pytest.mark.parametrize("seed", range(3))
def test_partial_roster_rebuilding_never_refills_field_from_unordered_production(
    seed: int,
) -> None:
    harness, _, _, _, observation = start_campaign(total=25, aa=2, seed=seed)
    intent = next(
        intent for intent in plain(harness.lua.globals().Policy.Decide(observation))
        if intent["kind"] == "field_campaign"
    )
    execute_intents(harness, [intent], observation)
    campaign = harness.controller.fieldCampaign
    campaign.state = "rebuilding"
    campaign.fullCohorts = False
    before_field = plain(campaign.fieldTokens)
    before_home = plain(campaign.homeTokens)
    newcomer = harness.unit(
        entityId=9999,
        blueprintId="uel0201",
        position=[10, 2, 20],
    )
    current_units = list(harness.brain.units.values())
    random.Random(seed).shuffle(current_units)
    harness.brain.units = harness.lua.table_from([newcomer, *current_units])

    refreshed = reconcile(harness)
    record = next(unit for unit in plain(refreshed.units) if unit["token"] == "9999:1")

    assert plain(campaign.fieldTokens) == before_field
    assert plain(campaign.homeTokens) == sorted([*before_home, "9999:1"])
    assert campaign.fullCohorts is False
    assert record["fieldCohort"] is False
    assert record["assignedToWave"] is False
    assert record["availableForWave"] is True


@pytest.mark.parametrize("lifecycle", ["dead", "captured", "recycled"])
def test_partial_roster_rebuilding_new_actor_lifecycle_never_mutates_field(
    lifecycle: str,
) -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=25, aa=2)
    intent = next(
        intent for intent in plain(harness.lua.globals().Policy.Decide(observation))
        if intent["kind"] == "field_campaign"
    )
    execute_intents(harness, [intent], observation)
    campaign = harness.controller.fieldCampaign
    campaign.state = "rebuilding"
    campaign.fullCohorts = False
    before_field = plain(campaign.fieldTokens)
    before_home = plain(campaign.homeTokens)
    newcomer = harness.unit(
        entityId=9999,
        blueprintId="uel0201",
        position=[10, 2, 20],
    )
    expected_new_token = None
    if lifecycle == "dead":
        newcomer.Dead = True
    elif lifecycle == "captured":
        newcomer.options.army = 2
    else:
        harness.brain.units = harness.lua.table_from([
            acu,
            engineer,
            *combat,
            newcomer,
        ])
        harness.observe()
        newcomer = harness.unit(
            entityId=9999,
            blueprintId="uel0201",
            position=[10, 2, 20],
        )
        expected_new_token = "9999:2"
    harness.brain.units = harness.lua.table_from([
        newcomer,
        acu,
        engineer,
        *combat,
    ])

    refreshed = reconcile(harness)
    records = {record["token"]: record for record in plain(refreshed.units)}

    assert plain(campaign.fieldTokens) == before_field
    if expected_new_token:
        assert plain(campaign.homeTokens) == sorted([*before_home, expected_new_token])
        assert records[expected_new_token]["fieldCohort"] is False
    else:
        assert plain(campaign.homeTokens) == before_home
    assert campaign.fullCohorts is False


def test_artifact_tick8569_state_idles_excess_factories_without_marker_driven_engineers() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    units = [
        *[harness.unit(entityId=100 + i, blueprintId="ueb1103", position=[5 + i, 2, 5]) for i in range(9)],
        *[_live_factory(harness, 200 + i) for i in range(10)],
        _live_factory(harness, 300, domain="air"),
        *[_engineer(harness, 400 + i, 20 + i) for i in range(5)],
    ]
    harness.brain.units = harness.lua.table_from(units)
    harness.controller.markers.mass = lua_value(harness.lua, [
        {
            "key": f"op-{i}", "name": f"op-{i}", "kind": "mass",
            "position": [200 + i * 50, 2, 20], "distance": 190 + i * 50,
            "reachable": True, "engineerReachable": True, "landReachable": True,
            "localSite": False,
        }
        for i in range(12)
    ])
    _set_economy(
        harness,
        mass_income=1.900000214,
        mass_requested=3.846666813,
        energy_income=40,
        energy_requested=35,
        mass_stored_ratio=1.886e-11,
        mass_trend=0,
    )
    observation = _sample(harness, 40, start=8200)
    assert observation.macro.factoryTarget <= 4
    assert observation.macro.factoryFundedCount == 0
    assert observation.macro.factoryIdleCount == 11
    assert observation.macro.expansionOpportunityCount == 12
    assert observation.macro.engineerTarget == 5
    assert observation.macro.techAdmission != "admitted"


def test_snapshot_reports_every_committed_budget_lane_with_exact_per_tick_units() -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    engineer = _engineer(harness, 70, 20)
    factory = _live_factory(harness, 80)
    harness.brain.units = harness.lua.table_from([engineer, factory])
    harness.brain.tick = 290
    observation = harness.observe()
    execute_intents(harness, [
        {
            "kind": "build_structure",
            "actorToken": "70:1",
            "buildRole": "power_generator",
            "placementKey": "Placement:30000:40000",
            "position": [30, 2, 40],
            "priority": 19,
            "reason": "energy_recovery",
        },
        {
            "kind": "factory_build",
            "actorToken": "80:1",
            "buildRole": "engineer",
            "priority": 30,
            "reason": "construction_capacity",
        },
    ], observation)
    assert sorted(plain(harness.controller.pending)) == ["70:1", "80:1"]
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Building": True})
    factory.options.idleState = False
    factory.options.states = lua_value(harness.lua, {"Building": True})

    harness.brain.tick = 300
    active = harness.observe()
    assert active.macro.committedMassEnergy == pytest.approx(0.3)
    assert active.macro.committedEnergyEnergy == pytest.approx(3)
    assert active.macro.committedMassEngineer == pytest.approx(0.4)
    assert active.macro.committedEnergyEngineer == pytest.approx(2)
    assert active.macro.committedMassConstruction == 0
    assert active.macro.committedEnergyConstruction == 0

    harness.lua.globals().Controller.Step(harness.controller)
    line = next(line for line in harness.logs if "event=snapshot" in line)
    for field, value in {
        "committed_mass_energy_per_tick": 0.3,
        "committed_energy_energy_per_tick": 3,
        "committed_mass_engineer_per_tick": 0.4,
        "committed_energy_engineer_per_tick": 2,
        "committed_mass_construction_per_tick": 0,
        "committed_energy_construction_per_tick": 0,
    }.items():
        assert f"{field}={value}" in line


def test_allocator_snapshot_telemetry_is_low_volume_and_contains_exact_scalar_budget_fields() -> None:
    harness = make_harness()
    _set_economy(harness, mass_income=1.2, mass_requested=0.6)
    harness.brain.tick = 300
    harness.lua.globals().Controller.Step(harness.controller)
    snapshots = [line for line in harness.logs if "event=snapshot" in line]
    assert len(snapshots) == 1
    line = snapshots[0]
    expected = {
        "recurring_mass_income_per_tick=",
        "recurring_energy_income_per_tick=",
        "rolling_mass_requested_per_tick=",
        "rolling_energy_requested_per_tick=",
        "rolling_mass_usage_per_tick=",
        "rolling_energy_usage_per_tick=",
        "rolling_mass_stored_ratio=",
        "rolling_energy_stored_ratio=",
        "rolling_mass_trend_per_tick=",
        "rolling_energy_trend_per_tick=",
        "mass_demand_satisfaction=",
        "energy_demand_satisfaction=",
        "active_committed_mass_per_tick=",
        "active_committed_energy_per_tick=",
        "committed_mass_expansion_per_tick=",
        "committed_energy_expansion_per_tick=",
        "committed_mass_energy_per_tick=",
        "committed_energy_energy_per_tick=",
        "committed_mass_engineer_per_tick=",
        "committed_energy_engineer_per_tick=",
        "committed_mass_factory_per_tick=",
        "committed_energy_factory_per_tick=",
        "committed_mass_air_per_tick=",
        "committed_energy_air_per_tick=",
        "committed_mass_tech_per_tick=",
        "committed_energy_tech_per_tick=",
        "committed_mass_construction_per_tick=",
        "committed_energy_construction_per_tick=",
        "one_time_mass_reserve=",
        "allocator_denied_request=",
        "allocator_denied_reason=",
        "expansion_opportunities=",
        "expansion_scheduled=",
        "engineer_target=",
        "factory_funded=",
        "factory_idle=",
        "tech_eta_ticks=",
        "tech_admission=",
    }
    assert all(field in line for field in expected)


def test_runtime_modules_remain_exact_and_allocator_does_not_import_stock_managers() -> None:
    controller = open("lua/AI/Overmind4/Controller.lua", encoding="utf-8").read()
    policy = open("lua/AI/Overmind4/Policy.lua", encoding="utf-8").read()
    assert "Allocator.lua" not in controller + policy
    assert "BuilderManager" not in controller + policy
    assert "EngineerManager" not in controller + policy
    assert "EconomyManager" not in controller + policy
