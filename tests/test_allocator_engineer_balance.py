from __future__ import annotations

import copy
import itertools
from typing import Any

import pytest

from test_controller import execute_intents, make_harness
from test_feedback_allocator import (
    _engineer,
    _live_factory,
    _policy_allocator_snapshot,
    _sample,
    _set_economy,
)
from test_policy import decide, intents_of, lua_value, plain
from test_secured_frontier_doctrine import mass_site


TANK_MASS_DRAIN = 0.373333
TANK_ENERGY_DRAIN = 1.773333
TANK_MASS_COST = 56
TANK_ENERGY_COST = 266


def _marker(index: int, *, reachable: bool = True) -> dict[str, Any]:
    return {
        "key": f"raw-{index}",
        "name": f"raw-{index}",
        "kind": "mass",
        "position": [30 + index % 20 * 4, 2, 30 + index // 20 * 4],
        "distance": 20 + index,
        "reachable": reachable,
        "engineerReachable": reachable,
        "landReachable": reachable,
        "localSite": False,
    }


def _observe_marker_backlog(count: int) -> Any:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    harness.controller.markers.mass = lua_value(
        harness.lua, [_marker(index) for index in range(count)]
    )
    _set_economy(
        harness,
        mass_income=0.5,
        mass_requested=0.5,
        energy_income=10,
        energy_requested=10,
        mass_stored_ratio=0,
        energy_stored_ratio=0,
    )
    return harness, _sample(harness, 4)


def _factory_snapshot(
    *,
    available_mass: float,
    available_energy: float,
    bank_mass: float,
    bank_energy: float,
    factory_slots: int = 1,
) -> dict[str, Any]:
    # Two completed land factories, the bounded two-engineer target, and a
    # scout isolate ordinary protected combat funding.
    snapshot = _policy_allocator_snapshot("engineer")
    snapshot["macro"].update(
        engineerTarget=2,
        engineerDemand=2,
        unlockingEngineerNeeded=False,
        expansionOpportunityCount=56,
        factoryFundedCount=factory_slots,
        availableRecurringMass=available_mass,
        availableRecurringEnergy=available_energy,
        expansionRecurringMassBudget=available_mass,
        expansionRecurringEnergyBudget=available_energy,
        oneTimeMassReserve=bank_mass,
        oneTimeEnergyReserve=bank_energy,
    )
    return snapshot


def _factory_orders(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (intent["buildRole"], intent["reason"])
        for intent in intents_of(decide(snapshot), "factory_build")
    ]


def _pair_snapshot(
    *,
    lost: bool,
    slots: int,
    reverse_units: bool = False,
    reverse_sites: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    snapshot = _policy_allocator_snapshot("engineer")
    snapshot["units"][0]["idle"] = False  # keep the ACU out of lost-mex work
    engineers = sorted(
        [unit for unit in snapshot["units"] if unit["role"] == "engineer"],
        key=lambda unit: unit["token"],
    )
    assert len(engineers) == 2
    engineers[0]["position"] = [0, 2, 20]
    engineers[1]["position"] = [100, 2, 20]
    for engineer in engineers:
        engineer["canBuild"] = {"mass_extractor": True}

    # The base-distance order deliberately presents a-middle first. A
    # site-major allocator gives it to the low-token engineer and strands that
    # actor 99 units from z-near. A global pair list first takes the true
    # one-unit pair, then the only remaining feasible pair.
    sites = [
        {
            **mass_site("a-middle", 49, 20, lost=lost),
            "distance": 1,
        },
        {
            **mass_site("z-near", 1, 20, lost=lost),
            "distance": 2,
        },
    ]
    if reverse_sites:
        sites.reverse()
    snapshot["sites"]["mass"].extend(sites)
    if reverse_units:
        snapshot["units"].reverse()
    snapshot["macro"].update(
        engineerTarget=2,
        engineerDemand=2,
        unlockingEngineerNeeded=False,
        factoryFundedCount=0,
        expansionOpportunityCount=2,
        availableRecurringMass=slots * 0.3,
        availableRecurringEnergy=slots * 3,
        expansionRecurringMassBudget=slots * 0.3,
        expansionRecurringEnergyBudget=slots * 3,
        oneTimeMassReserve=0,
        oneTimeEnergyReserve=0,
    )
    return snapshot, [engineer["token"] for engineer in engineers]


def _mex_pairs(snapshot: dict[str, Any]) -> list[tuple[str, str, str]]:
    return sorted(
        (
            intent["actorToken"],
            intent["siteKey"],
            intent["reason"],
        )
        for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "mass_extractor"
        and intent.get("actorToken") != "1:1"
    )


@pytest.mark.parametrize("marker_count", [0, 56, 560])
def test_raw_marker_count_cannot_raise_an_unfunded_engineer_target(
    marker_count: int,
) -> None:
    _, observation = _observe_marker_backlog(marker_count)

    assert observation.macro.engineerTarget == 2
    assert observation.macro.unlockingEngineerNeeded is False


@pytest.mark.parametrize("jobs", [0, 1, 3])
def test_engineer_target_is_bounded_by_distinct_funded_builder_jobs_plus_one(
    jobs: int,
) -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    engineers = [_engineer(harness, 70 + index, 20 + index * 10) for index in range(max(1, jobs))]
    harness.brain.units = harness.lua.table_from(engineers)
    harness.controller.markers.mass = lua_value(
        harness.lua, [_marker(index) for index in range(jobs + 4)]
    )
    _set_economy(
        harness,
        mass_income=5,
        mass_requested=0,
        energy_income=50,
        energy_requested=0,
        mass_stored_ratio=1,
        energy_stored_ratio=1,
        mass_usage=0,
        energy_usage=0,
    )
    observation = _sample(harness, 4)
    if jobs:
        execute_intents(
            harness,
            [
                {
                    "kind": "build_structure",
                    "actorToken": f"{70 + index}:1",
                    "buildRole": "mass_extractor",
                    "siteKey": f"raw-{index}",
                    "position": _marker(index)["position"],
                    "priority": 22,
                    "reason": "frontier_expansion",
                }
                for index in range(jobs)
            ],
            observation,
        )
        observation = harness.observe()

    assert max(2, jobs) <= observation.macro.engineerTarget <= max(2, jobs + 1)


@pytest.mark.parametrize("bad_kind", ["unreachable", "reserved", "blocked", "malformed"])
def test_unfunded_or_infeasible_marker_backlog_does_not_create_engineer_demand(
    bad_kind: str,
) -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    markers = []
    for index in range(56):
        marker = _marker(index)
        marker.update(lost=True, frontierSelected=True)
        if bad_kind == "unreachable":
            marker.update(reachable=False, engineerReachable=False, landReachable=False)
        elif bad_kind == "malformed":
            marker.pop("position")
        markers.append(marker)
    harness.controller.markers.mass = lua_value(harness.lua, markers)
    if bad_kind == "reserved":
        for index in range(56):
            harness.controller.reservations[f"raw-{index}"] = lua_value(
                harness.lua,
                {"actorToken": "lease:1", "siteKey": f"raw-{index}"},
            )
    elif bad_kind == "blocked":
        for index in range(56):
            harness.controller.blockedSites[f"raw-{index}"] = 10000
    _set_economy(
        harness,
        mass_income=0.5,
        mass_requested=0.5,
        energy_income=10,
        energy_requested=10,
        mass_stored_ratio=0,
        energy_stored_ratio=0,
    )

    observation = _sample(harness, 4)

    assert observation.macro.engineerTarget == 2
    assert observation.macro.unlockingEngineerNeeded is False


@pytest.mark.parametrize("tick", [847, 2755])
def test_artifact_two_factory_choice_keeps_the_bounded_combat_lane_funded(
    tick: int,
) -> None:
    snapshot = _factory_snapshot(
        available_mass=TANK_MASS_DRAIN,
        available_energy=TANK_ENERGY_DRAIN,
        bank_mass=52,
        bank_energy=260,
    )
    snapshot["tick"] = tick

    orders = _factory_orders(snapshot)

    assert orders == [("tank", "continuous_land_production")]


@pytest.mark.parametrize(
    ("bank_mass", "bank_energy", "expected"),
    [
        (TANK_MASS_COST, TANK_ENERGY_COST, [("tank", "continuous_land_production")]),
        (TANK_MASS_COST - 0.001, TANK_ENERGY_COST, []),
        (TANK_MASS_COST, TANK_ENERGY_COST - 0.001, []),
        (0, 0, []),
    ],
)
def test_combat_forecast_uses_exact_bank_boundary_and_never_fabricates_capacity(
    bank_mass: float,
    bank_energy: float,
    expected: list[tuple[str, str]],
) -> None:
    snapshot = _factory_snapshot(
        available_mass=0,
        available_energy=0,
        bank_mass=bank_mass,
        bank_energy=bank_energy,
    )

    assert _factory_orders(snapshot) == expected


def test_capacity_return_admits_combat_before_engineer_or_expansion() -> None:
    denied = _factory_snapshot(
        available_mass=0,
        available_energy=0,
        bank_mass=0,
        bank_energy=0,
    )
    restored = copy.deepcopy(denied)
    restored["macro"].update(
        availableRecurringMass=TANK_MASS_DRAIN,
        availableRecurringEnergy=TANK_ENERGY_DRAIN,
        expansionRecurringMassBudget=TANK_MASS_DRAIN,
        expansionRecurringEnergyBudget=TANK_ENERGY_DRAIN,
        oneTimeMassReserve=52,
        oneTimeEnergyReserve=260,
    )

    assert _factory_orders(denied) == []
    assert _factory_orders(restored) == [("tank", "continuous_land_production")]


def test_one_funded_mex_lane_preempts_combat_but_second_mex_cannot_spend_combat_reserve() -> None:
    snapshot = _policy_allocator_snapshot("engineer")
    snapshot["sites"]["mass"].extend(
        [
            mass_site("mex-a", 30, 20, frontier=True),
            mass_site("mex-b", 40, 20, frontier=True),
        ]
    )
    snapshot["macro"].update(
        engineerTarget=2,
        engineerDemand=2,
        unlockingEngineerNeeded=False,
        expansionOpportunityCount=2,
        expansionRecurringMassBudget=0.8,
        expansionRecurringEnergyBudget=8,
        availableRecurringMass=0.5,
        availableRecurringEnergy=5,
        oneTimeMassReserve=0,
        oneTimeEnergyReserve=0,
        factoryFundedCount=1,
    )

    result = decide(snapshot)
    mex = [
        intent
        for intent in intents_of(result, "build_structure")
        if intent.get("buildRole") == "mass_extractor"
    ]

    assert [(intent["siteKey"], intent["reason"]) for intent in mex] == [
        ("mex-a", "frontier_expansion")
    ]
    assert _factory_orders(snapshot) == [("tank", "continuous_land_production")]


@pytest.mark.parametrize(
    ("mass_headroom", "energy_headroom", "expected_slots"),
    [
        (TANK_MASS_DRAIN, TANK_ENERGY_DRAIN, 1),
        (TANK_MASS_DRAIN - 0.00011, TANK_ENERGY_DRAIN, 0),
        (TANK_MASS_DRAIN, TANK_ENERGY_DRAIN - 0.00011, 0),
    ],
)
def test_controller_factory_slot_uses_exact_land_combat_drain_boundary(
    mass_headroom: float,
    energy_headroom: float,
    expected_slots: int,
) -> None:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = False
    first_engineer = _engineer(harness, 90, 20)
    second_engineer = _engineer(harness, 91, 22)
    for engineer in (first_engineer, second_engineer):
        engineer.options.idleState = False
        engineer.options.states = lua_value(harness.lua, {"Building": True})
    harness.brain.units = harness.lua.table_from(
        [
            _live_factory(harness, 80),
            _live_factory(harness, 81),
            first_engineer,
            second_engineer,
            harness.unit(entityId=92, blueprintId="uel0101", position=[15, 2, 20]),
        ]
    )
    harness.controller.rallied["80:1"] = True
    harness.controller.rallied["81:1"] = True
    harness.controller.markers.mass = lua_value(harness.lua, [_marker(0)])
    _set_economy(
        harness,
        mass_income=0.3 + mass_headroom,
        mass_requested=0,
        energy_income=3 + energy_headroom,
        energy_requested=0,
        mass_stored_ratio=0,
        energy_stored_ratio=0,
        mass_usage=0,
        energy_usage=0,
    )
    harness.brain.massStored = 0
    harness.brain.energyStored = 0

    observation = _sample(harness, 4)

    assert observation.macro.availableRecurringMass == pytest.approx(mass_headroom)
    assert observation.macro.availableRecurringEnergy == pytest.approx(energy_headroom)
    assert observation.macro.factoryFundedCount == expected_slots
    orders = [
        (intent["buildRole"], intent["reason"])
        for intent in plain(harness.lua.globals().Policy.Decide(observation))
        if intent["kind"] == "factory_build"
    ]
    assert orders == (
        [("tank", "continuous_land_production")] if expected_slots else []
    )


def test_allocator_accepts_the_controller_published_six_decimal_combat_boundary() -> None:
    snapshot = _factory_snapshot(
        available_mass=TANK_MASS_DRAIN,
        available_energy=TANK_ENERGY_DRAIN,
        bank_mass=0,
        bank_energy=0,
    )

    assert _factory_orders(snapshot) == [
        ("tank", "continuous_land_production")
    ]


def test_single_factory_after_opening_floor_protects_combat_before_extra_engineer() -> None:
    snapshot = _policy_allocator_snapshot()
    factories = [unit for unit in snapshot["units"] if unit["role"] == "land_factory"]
    snapshot["units"].remove(factories[-1])
    snapshot["macro"].update(
        engineerTarget=2,
        engineerDemand=2,
        unlockingEngineerNeeded=True,
        expansionOpportunityCount=1,
        availableRecurringMass=0.4,
        availableRecurringEnergy=2,
        expansionRecurringMassBudget=0.4,
        expansionRecurringEnergyBudget=2,
        oneTimeMassReserve=0,
        oneTimeEnergyReserve=0,
        factoryFundedCount=1,
    )

    assert _factory_orders(snapshot) == [("tank", "continuous_land_production")]


def test_protected_land_combat_lane_reissues_after_each_completed_unit() -> None:
    first = _factory_snapshot(
        available_mass=0.5,
        available_energy=2.5,
        bank_mass=0,
        bank_energy=0,
        factory_slots=0,
    )
    first["macro"].update(
        engineerTarget=2,
        engineerDemand=2,
        unlockingEngineerNeeded=False,
        expansionOpportunityCount=0,
    )

    second = copy.deepcopy(first)
    second["units"].append(
        {
            "token": "500:1",
            "role": "tank",
            "complete": True,
            "idle": True,
            "healthRatio": 1,
            "position": [20, 2, 20],
            "canBuild": {},
            "availableForWave": True,
            "assignedToWave": False,
            "nearStaging": True,
        }
    )

    assert _factory_orders(first) == [("tank", "continuous_land_production")]
    assert _factory_orders(second) == [("artillery", "continuous_land_production")]


def test_tick5815_bank_and_forecast_fund_combat_when_generic_factory_slots_are_zero() -> None:
    snapshot = _policy_allocator_snapshot()
    snapshot["tick"] = 5815
    snapshot["economy"].update(
        massIncome=1.9,
        massRequested=0,
        massUsage=0,
        massTrend=1.9,
        energyIncome=6,
        energyRequested=0,
        energyUsage=0,
        energyTrend=6,
        massStoredRatio=1,
        energyStoredRatio=1,
    )
    snapshot["macro"].update(
        engineerTarget=2,
        engineerDemand=2,
        unlockingEngineerNeeded=True,
        expansionOpportunityCount=0,
        factoryFundedCount=0,
        availableRecurringMass=1.9,
        availableRecurringEnergy=6,
        expansionRecurringMassBudget=1.9,
        expansionRecurringEnergyBudget=6,
        oneTimeMassReserve=820,
        oneTimeEnergyReserve=4000,
    )

    assert ("tank", "continuous_land_production") in _factory_orders(snapshot)


def test_two_factories_with_one_engineer_keep_combat_and_recovery_actors_disjoint() -> None:
    snapshot = _policy_allocator_snapshot()
    snapshot["macro"].update(
        engineerTarget=2,
        engineerDemand=2,
        unlockingEngineerNeeded=True,
        expansionOpportunityCount=0,
        factoryFundedCount=0,
        availableRecurringMass=0,
        availableRecurringEnergy=0,
        expansionRecurringMassBudget=0,
        expansionRecurringEnergyBudget=0,
        oneTimeMassReserve=TANK_MASS_COST + 52,
        oneTimeEnergyReserve=TANK_ENERGY_COST + 260,
    )

    orders = intents_of(decide(snapshot), "factory_build")

    assert sorted((intent["buildRole"], intent["reason"]) for intent in orders) == [
        ("engineer", "unlock_profitable_expansion"),
        ("tank", "continuous_land_production"),
    ]
    assert len({intent["actorToken"] for intent in orders}) == 2


def test_live_two_factory_lane_builds_one_missing_engineer_then_returns_both_to_combat() -> None:
    initial = _policy_allocator_snapshot()
    initial["tick"] = 5815
    initial["macro"].update(
        engineerTarget=2,
        engineerDemand=2,
        unlockingEngineerNeeded=False,
        expansionOpportunityCount=0,
        factoryFundedCount=0,
        availableRecurringMass=1.9,
        availableRecurringEnergy=6,
        expansionRecurringMassBudget=1.9,
        expansionRecurringEnergyBudget=6,
        oneTimeMassReserve=820,
        oneTimeEnergyReserve=4000,
    )

    initial_orders = intents_of(decide(initial), "factory_build")
    assert sorted((intent["buildRole"], intent["reason"]) for intent in initial_orders) == [
        ("engineer", "unlock_profitable_expansion"),
        ("tank", "continuous_land_production"),
    ]
    assert len({intent["actorToken"] for intent in initial_orders}) == 2

    pending = copy.deepcopy(initial)
    pending["pending"] = [
        {
            "kind": "factory_build",
            "actorToken": "11:1",
            "buildRole": "engineer",
            "phase": "accepted",
        }
    ]
    pending_orders = intents_of(decide(pending), "factory_build")
    assert [(intent["buildRole"], intent["reason"]) for intent in pending_orders] == [
        ("tank", "continuous_land_production")
    ]

    completed = copy.deepcopy(initial)
    completed["macro"]["factoryFundedCount"] = 2
    completed["units"].append(
        {
            "token": "99:1",
            "role": "engineer",
            "complete": True,
            "idle": True,
            "healthRatio": 1,
            "position": [24, 2, 20],
            "buildRate": 5,
            "canBuild": {},
        }
    )
    completed_orders = intents_of(decide(completed), "factory_build")
    assert all(intent["buildRole"] != "engineer" for intent in completed_orders)
    assert sorted(intent["actorToken"] for intent in completed_orders) == ["10:1", "11:1"]

    starved = copy.deepcopy(initial)
    starved["macro"].update(
        availableRecurringMass=0,
        availableRecurringEnergy=0,
        expansionRecurringMassBudget=0,
        expansionRecurringEnergyBudget=0,
        oneTimeMassReserve=TANK_MASS_COST - 0.001,
        oneTimeEnergyReserve=TANK_ENERGY_COST,
    )
    assert intents_of(decide(starved), "factory_build") == []


@pytest.mark.parametrize(
    ("available_mass", "available_energy", "bank_mass", "bank_energy"),
    [
        (TANK_MASS_DRAIN - 0.00011, TANK_ENERGY_DRAIN, 0, 0),
        (TANK_MASS_DRAIN, TANK_ENERGY_DRAIN - 0.00011, 0, 0),
        (0, 0, TANK_MASS_COST - 0.001, TANK_ENERGY_COST),
        (0, 0, TANK_MASS_COST, TANK_ENERGY_COST - 0.001),
    ],
)
def test_protected_combat_lane_fails_closed_without_recurring_or_full_unit_bank(
    available_mass: float,
    available_energy: float,
    bank_mass: float,
    bank_energy: float,
) -> None:
    snapshot = _factory_snapshot(
        available_mass=available_mass,
        available_energy=available_energy,
        bank_mass=bank_mass,
        bank_energy=bank_energy,
        factory_slots=0,
    )
    snapshot["macro"].update(
        engineerTarget=2,
        engineerDemand=2,
        unlockingEngineerNeeded=False,
        expansionOpportunityCount=0,
    )

    assert _factory_orders(snapshot) == []


def test_immediate_contact_does_not_suppress_the_protected_combat_lane() -> None:
    snapshot = _factory_snapshot(
        available_mass=TANK_MASS_DRAIN,
        available_energy=TANK_ENERGY_DRAIN,
        bank_mass=0,
        bank_energy=0,
        factory_slots=0,
    )
    snapshot["macro"].update(
        engineerTarget=2,
        engineerDemand=2,
        unlockingEngineerNeeded=False,
        expansionOpportunityCount=0,
    )
    snapshot["enemyContact"] = {"position": [11, 2, 10], "immediate": True}

    assert _factory_orders(snapshot) == [("tank", "continuous_land_production")]


@pytest.mark.parametrize("lost", [False, True])
@pytest.mark.parametrize("reverse_units,reverse_sites", itertools.product([False, True], repeat=2))
def test_global_mex_pairs_choose_shortest_feasible_cross_trap_deterministically(
    lost: bool,
    reverse_units: bool,
    reverse_sites: bool,
) -> None:
    snapshot, engineers = _pair_snapshot(
        lost=lost,
        slots=2,
        reverse_units=reverse_units,
        reverse_sites=reverse_sites,
    )

    assert _mex_pairs(snapshot) == [
        (engineers[0], "z-near", "rebuild_mex" if lost else "frontier_expansion"),
        (engineers[1], "a-middle", "rebuild_mex" if lost else "frontier_expansion"),
    ]


@pytest.mark.parametrize("slots,expected_count", [(0, 0), (1, 1), (2, 2)])
def test_mex_pair_allocator_respects_funded_slot_boundaries_for_lost_and_normal(
    slots: int,
    expected_count: int,
) -> None:
    for lost in (False, True):
        snapshot, _ = _pair_snapshot(lost=lost, slots=slots)
        pairs = _mex_pairs(snapshot)
        assert len(pairs) == expected_count
        if pairs:
            assert pairs[0][1] == "z-near"


def test_lost_pair_preempts_nearer_normal_site_without_duplicate_actor_or_site() -> None:
    snapshot, engineers = _pair_snapshot(lost=True, slots=1)
    lost_sites = [site for site in snapshot["sites"]["mass"] if site.get("lost")]
    lost_sites[0]["position"] = [90, 2, 20]
    lost_sites[0]["distance"] = 90
    lost_sites[1]["lost"] = False
    lost_sites[1]["position"] = [1, 2, 20]
    lost_sites[1]["distance"] = 1

    pairs = _mex_pairs(snapshot)

    assert len(pairs) == 1
    assert pairs[0][1] == "a-middle"
    assert pairs[0][2] == "rebuild_mex"
    assert pairs[0][0] in engineers


def test_mex_pair_filters_reserved_unreachable_blocked_malformed_and_incapable() -> None:
    snapshot, engineers = _pair_snapshot(lost=False, slots=1)
    snapshot["sites"]["mass"] = snapshot["sites"]["mass"][:4]
    invalid = [
        {**mass_site("reserved", 1, 20, reserved=True), "distance": 1},
        {**mass_site("unreachable", 2, 20, reachable=False), "distance": 2},
        {**mass_site("blocked", 3, 20, buildable=False), "distance": 3},
        {"key": "malformed", "name": "malformed", "reachable": True},
    ]
    valid = {**mass_site("valid", 95, 20), "distance": 95}
    snapshot["sites"]["mass"].extend([*invalid, valid])
    first = next(unit for unit in snapshot["units"] if unit.get("token") == engineers[0])
    first["canBuild"] = {"mass_extractor": False}

    assert _mex_pairs(snapshot) == [
        (engineers[1], "valid", "frontier_expansion")
    ]


def test_engineer_target_telemetry_reports_funded_target_not_raw_opportunity_count() -> None:
    harness, _ = _observe_marker_backlog(56)
    harness.brain.tick = 300

    harness.lua.globals().Controller.Step(harness.controller)

    snapshot_lines = [line for line in harness.logs if "event=snapshot" in line]
    assert len(snapshot_lines) == 1
    assert "expansion_opportunities=56" in snapshot_lines[0]
    assert "engineer_target=2" in snapshot_lines[0]
