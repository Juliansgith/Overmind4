from __future__ import annotations

import itertools
import random
import re
from typing import Any

import pytest

from conftest import source
from test_controller import execute_intents, make_harness
from test_field_campaign import (
    campaign_intents,
    policy_intents,
    reconcile,
    start_campaign,
)
from test_pressure_front_campaign import setup_pressure_mode
from test_policy import decide, intents_of, lua_value, plain, post_opening_snapshot, role_counts
from test_secured_frontier_doctrine import macro_snapshot, mass_site


def support_units(harness: Any, *, mex: int, land: int, air: int = 0, hydro: int = 0) -> list[Any]:
    units = [
        harness.unit(entityId=5000 + index, blueprintId="ueb1103", position=[3 + index, 2, 4])
        for index in range(mex)
    ]
    units.extend(
        harness.unit(
            entityId=5100 + index,
            blueprintId="ueb0101",
            position=[4 + index, 2, 8],
            idleState=False,
            states={"Building": True},
        )
        for index in range(land)
    )
    units.extend(
        harness.unit(
            entityId=5200 + index,
            blueprintId="ueb0102",
            position=[4 + index, 2, 12],
            idleState=False,
            states={"Building": True},
        )
        for index in range(air)
    )
    units.extend(
        harness.unit(entityId=5300 + index, blueprintId="ueb1102", position=[6 + index, 2, 14])
        for index in range(hydro)
    )
    return units


def campaign_state(harness: Any) -> dict[str, Any]:
    value = harness.controller.fieldCampaign
    return plain(value) if value is not None else {}


def set_support(harness: Any, **counts: int) -> None:
    harness.brain.supportUnits = harness.lua.table_from(support_units(harness, **counts))


def engineer_record(token: str, position: list[float]) -> dict[str, Any]:
    return {
        "token": token,
        "role": "engineer",
        "complete": True,
        "idle": True,
        "position": position,
        "canBuild": {
            "mass_extractor": True,
            "power_generator": True,
            "land_factory": True,
            "air_factory": True,
        },
    }


def ready_economy() -> dict[str, float]:
    return {
        "energyTrend": 1,
        "energyStoredRatio": 0.8,
        "energyIncome": 30,
        "energyUsage": 20,
        "energyRequested": 20,
        "massTrend": 0.5,
        "massStoredRatio": 0.8,
        "massIncome": 1.5,
        "massUsage": 0.5,
        "massRequested": 0.5,
        "unusedMass": 1.0,
    }


def economy_policy_snapshot(*extra_roles: str) -> dict[str, Any]:
    snapshot = post_opening_snapshot(
        "engineer",
        "mass_extractor",
        "mass_extractor",
        *extra_roles,
    )
    snapshot["economy"] = ready_economy()
    snapshot["macro"] = {
        "ownedMexCount": 6,
        "lostMexCount": 0,
        "activeRebuildJobs": 0,
        "activeFrontierJobs": 0,
        "activeReclaimJobs": 0,
        "constructionBacklog": 0,
        "engineerDemand": 2,
        "factoryDemand": 2,
        "factoryTarget": 2,
        "massSurplusTicks": 300,
        "campaignEnabled": True,
        "campaignState": "idle",
        "campaignIntentMode": "none",
        "reclaimTarget": "none",
        "reclaimValue": -1,
    }
    snapshot["placements"]["air_factory"] = [[26, 2, 18], [30, 2, 18]]
    for unit in snapshot["units"]:
        if unit["role"] == "engineer":
            unit["canBuild"].update(air_factory=True)
        if unit["role"] == "land_factory":
            unit["needsRally"] = False
            unit["canBuild"].update(
                t2_direct_fire=True,
                t2_anti_air=True,
                engineer=True,
                tank=True,
                anti_air=True,
            )
    return snapshot


def only(result: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = intents_of(result, kind)
    assert len(matches) == 1
    return matches[0]


def test_catalog_contains_pinned_uef_air_and_t2_vertical_slice() -> None:
    lua = make_harness().lua
    catalog = lua.globals().Catalog
    expected = {
        "air_factory": "ueb0102",
        "air_scout": "uea0101",
        "interceptor": "uea0102",
        "land_factory_t2": "ueb0201",
        "t2_direct_fire": "uel0202",
        "t2_anti_air": "uel0205",
    }
    assert {role: catalog.IdFor(role) for role in expected} == expected
    assert {blueprint: catalog.RoleFor(blueprint) for role, blueprint in expected.items()} == {
        blueprint: role for role, blueprint in expected.items()
    }


@pytest.mark.parametrize(
    ("kwargs", "blocker"),
    [
        ({"macro_ready": False}, "mex"),
        ({"readiness_mex": 7}, "mex"),
        ({"readiness_land_factories": 2}, "production_factory"),
        ({"total": 23}, "combat"),
        ({"aa": 1}, "anti_air"),
        ({"economy_updates": {"massIncome": None}}, "economy_invalid"),
    ],
)
def test_campaign_start_fails_closed_at_each_macro_readiness_boundary(
    kwargs: dict[str, Any], blocker: str
) -> None:
    harness, _, _, _, observation = start_campaign(**kwargs)
    assert harness.controller.fieldCampaign is None
    assert campaign_intents(harness, observation) == []
    blockers = plain(observation.macro.campaignReadinessBlockers)
    assert blocker in blockers
    assert observation.macro.campaignReady is False


def test_tick784_zero_force_never_starts_campaign_but_macro_policy_keeps_building() -> None:
    harness, _, _, _, _ = start_campaign(total=0, aa=0, macro_ready=False)
    harness.brain.tick = 784
    observation = reconcile(harness)
    intents = policy_intents(harness, observation)
    assert harness.controller.fieldCampaign is None
    assert not [intent for intent in intents if intent["kind"] == "field_campaign"]
    assert plain(observation.pending)[0]["kind"] == "build_structure"


def test_exact_readiness_threshold_starts_pressure_campaign() -> None:
    harness, _, _, _, observation = start_campaign(total=24, aa=2)
    assert observation.macro.campaignReady is True
    assert plain(observation.macro.campaignReadinessBlockers) in ([], {})
    assert campaign_state(harness)["state"] == "awaiting_order"
    assert only(campaign_intents(harness, observation), "field_campaign")["mode"] == "activate"


@pytest.mark.parametrize("seed", range(4))
def test_t2_mobile_aa_satisfies_readiness_and_is_split_between_campaign_cohorts(
    seed: int,
) -> None:
    harness, acu, engineer, combat, _ = start_campaign(total=24, aa=0, seed=seed)
    t2_aa = [
        harness.unit(
            entityId=1000 + index,
            blueprintId="uel0205",
            position=[10 + index * 0.01, 2, 20],
        )
        for index in range(2)
    ]
    live_combat = [*t2_aa, *combat[2:]]
    shuffled = [acu, engineer, *live_combat]
    random.Random(seed + 50).shuffle(shuffled)
    harness.brain.units = harness.lua.table_from(shuffled)
    harness.brain.tick = 10

    observation = reconcile(harness)

    assert observation.macro.campaignReady is True
    assert "anti_air" not in plain(observation.macro.campaignReadinessBlockers)
    activation = only(campaign_intents(harness, observation), "field_campaign")
    execute_intents(harness, [activation], observation)
    campaign = campaign_state(harness)
    field = set(campaign["fieldTokens"])
    home = set(campaign["homeTokens"])
    aa_tokens = {"1000:1", "1001:1"}
    assert len(field & aa_tokens) == 1
    assert len(home & aa_tokens) == 1


@pytest.mark.parametrize(
    ("land", "air", "ready", "blocker"),
    [
        (2, 1, True, None),
        (1, 2, False, "land_factory"),
        (2, 0, False, "production_factory"),
    ],
)
def test_campaign_readiness_counts_total_production_but_requires_two_land_factories(
    land: int,
    air: int,
    ready: bool,
    blocker: str | None,
) -> None:
    harness, _, _, _, observation = start_campaign(
        readiness_land_factories=land,
        readiness_air_factories=air,
    )
    assert observation.macro.campaignReady is ready
    assert (harness.controller.fieldCampaign is not None) is ready
    blockers = plain(observation.macro.campaignReadinessBlockers)
    if blocker:
        assert blocker in blockers


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("massIncome", float("nan")),
        ("massIncome", float("inf")),
        ("massRequested", -0.01),
        ("massStoredRatio", 1.01),
        ("massTrend", float("-inf")),
        ("energyIncome", -0.01),
        ("energyStoredRatio", float("nan")),
        ("energyTrend", float("inf")),
    ],
)
def test_campaign_readiness_rejects_nonfinite_or_out_of_contract_economy(
    field: str,
    value: float,
) -> None:
    harness, _, _, _, observation = start_campaign(economy_updates={field: value})
    assert observation.macro.campaignReady is False
    assert "economy_invalid" in plain(observation.macro.campaignReadinessBlockers)
    assert harness.controller.fieldCampaign is None
    assert campaign_intents(harness, observation) == []


def test_economy_getter_exception_blocks_campaign_and_capacity_escalation() -> None:
    harness, _, _, _, _ = start_campaign(macro_ready=False)
    set_support(harness, mex=8, land=3)
    harness.lua.execute(
        """
        brain.GetEconomyIncome = function(self, resource)
            if resource == 'MASS' then error('economy unavailable') end
            return self.energyIncome
        end
        """
    )
    harness.brain.massStoredRatio = 1
    harness.brain.tick = 300
    observation = reconcile(harness)
    assert observation.macro.campaignReady is False
    assert "economy_invalid" in plain(observation.macro.campaignReadinessBlockers)
    assert harness.controller.fieldCampaign is None
    assert observation.macro.factoryTarget == 2


def test_campaign_allows_one_connected_job_without_suppressing_other_idle_engineers() -> None:
    snapshot = macro_snapshot("engineer", "engineer")
    snapshot["macro"].update(
        campaignEnabled=True,
        campaignState="active",
        campaignCluster="front",
        campaignMemberKeys=["front-a"],
        campaignReady=True,
        constructionBacklog=3,
    )
    snapshot["sites"]["mass"] = [
        mass_site("front-a", 80, 20, frontier=True),
        mass_site("lost-home", 18, 20, lost=True),
        mass_site("safe-next", 30, 20, frontier=True),
    ]
    for site in snapshot["sites"]["mass"]:
        site["engineerReachable"] = True
        site["landReachable"] = True
    builds = intents_of(decide(snapshot), "build_structure")
    mex = [intent for intent in builds if intent.get("buildRole") == "mass_extractor"]
    assert len({intent["actorToken"] for intent in mex}) >= 2
    assert sum(intent.get("clusterKey") == "front" for intent in mex) <= 1
    assert mex[0]["siteKey"] == "lost-home"
    assert len({intent["siteKey"] for intent in mex}) == len(mex)


def test_remote_backlog_still_reserves_one_local_engineer_for_best_visible_reclaim() -> None:
    snapshot = macro_snapshot("engineer")
    engineers = [unit for unit in snapshot["units"] if unit["role"] == "engineer"]
    assert len(engineers) == 2
    engineers[0]["position"] = [80, 2, 20]
    engineers[1]["position"] = [12, 2, 10]
    snapshot["macro"].update(
        campaignEnabled=True,
        campaignState="active",
        campaignCluster="front",
        campaignMemberKeys=["front"],
        constructionBacklog=5,
        activeFrontierJobs=1,
    )
    snapshot["sites"]["mass"] = [mass_site("front", 82, 20, frontier=True)]
    snapshot["reclaim"] = [
        {
            "key": "small",
            "position": [13, 2, 10],
            "mass": 20,
            "reserved": False,
            "observerToken": engineers[1]["token"],
            "visionRadius": 10,
            "observedTick": 0,
        },
        {
            "key": "large",
            "position": [14, 2, 10],
            "mass": 200,
            "reserved": False,
            "observerToken": engineers[1]["token"],
            "visionRadius": 10,
            "observedTick": 0,
        },
    ]
    reclaim = only(decide(snapshot), "reclaim")
    assert reclaim["actorToken"] == engineers[1]["token"]
    assert reclaim["targetKey"] == "large"


def test_lost_mex_preempts_reclaim_per_actor_but_spare_engineer_still_reclaims() -> None:
    snapshot = macro_snapshot("engineer")
    snapshot["sites"]["mass"].append(mass_site("lost", 20, 10, lost=True))
    snapshot["macro"].update(lostMexCount=1, constructionBacklog=9)
    engineer = next(unit for unit in snapshot["units"] if unit["role"] == "engineer")
    snapshot["reclaim"] = [{
        "key": "valuable",
        "position": engineer["position"],
        "mass": 500,
        "reserved": False,
        "observerToken": engineer["token"],
        "visionRadius": 10,
        "observedTick": 0,
    }]
    result = decide(snapshot)
    rebuild = next(
        intent for intent in intents_of(result, "build_structure")
        if intent.get("siteKey") == "lost"
    )
    reclaim = only(result, "reclaim")
    assert rebuild["actorToken"] != reclaim["actorToken"]
    assert reclaim["targetKey"] == "valuable"


def test_dynamic_placement_probes_beyond_legacy_thirteen_seeds_and_is_bounded() -> None:
    harness = make_harness()
    harness.lua.execute(
        """
        brain.canBuildAt = function(blueprintId, position)
            local dx = position[1] - brain.startX
            local dz = position[3] - brain.startZ
            return dx * dx + dz * dz >= 42 * 42
        end
        """
    )
    observation = harness.observe()
    placements = plain(observation.placements)
    assert placements["land_factory"]
    assert placements["power_generator"]
    assert observation.macro.placementProbeCount <= 96
    assert observation.macro.placementCapacity >= 2
    assert len(harness.calls.canBuild) <= 96


def test_power_generator_candidates_start_flush_against_factory_sides() -> None:
    harness = make_harness()
    factory = harness.unit(
        entityId=20,
        blueprintId="ueb0101",
        position=[30, 2, 30],
    )
    harness.brain.units = harness.lua.table_from([factory])

    placements = plain(harness.observe().placements)["power_generator"]

    assert [(position[0], position[2]) for position in placements[:4]] == [
        (25, 27),
        (35, 27),
        (27, 25),
        (27, 35),
    ]


def test_dynamic_placement_probe_budget_is_global_not_multiplied_by_engineer_count() -> None:
    baseline = make_harness()
    baseline.brain.canBuildAt = False
    baseline.observe()
    expected = len(baseline.calls.canBuild)

    crowded = make_harness()
    crowded.brain.canBuildAt = False
    crowded.brain.units = crowded.lua.table_from([
        crowded.unit(entityId=100 + index, blueprintId="uel0105")
        for index in range(40)
    ])
    crowded.observe()
    assert len(crowded.calls.canBuild) == expected
    assert len(crowded.calls.canBuild) <= 96
    for call in crowded.calls.canBuild.values():
        dx = float(call[2][1]) - float(crowded.brain.startX)
        dz = float(call[2][3]) - float(crowded.brain.startZ)
        assert dx * dx + dz * dz <= 64 * 64


@pytest.mark.parametrize("seed", range(5))
def test_dynamic_placement_is_deterministic_and_has_no_duplicate_footprints(seed: int) -> None:
    baseline = make_harness()
    baseline.lua.execute("brain.canBuildAt = function(id, position) return position[1] >= 30 end")
    expected = plain(baseline.observe().placements)
    harness = make_harness()
    harness.lua.execute("brain.canBuildAt = function(id, position) return position[1] >= 30 end")
    permuted = plain(harness.controller.placementSeeds)
    random.Random(seed).shuffle(permuted)
    harness.controller.placementSeeds = lua_value(harness.lua, permuted)
    observation = harness.observe()
    actual = plain(observation.placements)
    all_positions = [tuple(position) for values in actual.values() for position in values]
    assert len(all_positions) == len(set(all_positions))
    assert actual == expected
    assert len(harness.calls.canBuild) <= 96


def test_no_buildable_dynamic_placement_stops_at_fixed_probe_budget() -> None:
    harness = make_harness()
    harness.brain.canBuildAt = False
    observation = harness.observe()
    assert all(not values for values in plain(observation.placements).values())
    assert 13 < len(harness.calls.canBuild) <= 96
    assert observation.macro.placementCapacity == 0


def test_factory_builder_is_nearest_live_engineer_not_lowest_token_remote_actor() -> None:
    snapshot = economy_policy_snapshot()
    engineers = [unit for unit in snapshot["units"] if unit["role"] == "engineer"]
    engineers[0].update(token="10:1", position=[200, 2, 200])
    near = engineer_record("99:1", [25, 2, 18])
    snapshot["units"].append(near)
    snapshot["macro"].update(factoryTarget=3, factoryDemand=3, massSurplusTicks=300)
    build = next(
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "land_factory"
    )
    assert build["actorToken"] == "99:1"


def test_jobs_first_matching_sends_each_builder_to_its_nearest_priority_job() -> None:
    snapshot = economy_policy_snapshot()
    first = next(unit for unit in snapshot["units"] if unit["role"] == "engineer")
    first.update(token="10:1", position=[99, 2, 20])
    second = engineer_record("99:1", [21, 2, 20])
    snapshot["units"].append(second)
    snapshot["sites"]["mass"] = [mass_site("lost", 20, 20, lost=True)]
    snapshot["placements"]["land_factory"] = [[100, 2, 20]]
    snapshot["macro"].update(
        lostMexCount=1,
        factoryTarget=3,
        factoryDemand=3,
        massSurplusTicks=300,
    )
    builds = intents_of(decide(snapshot), "build_structure")
    assignments = {
        intent.get("buildRole"): intent.get("actorToken")
        for intent in builds
        if intent.get("buildRole") in {"mass_extractor", "land_factory"}
    }
    assert assignments == {"mass_extractor": "99:1", "land_factory": "10:1"}


def test_lost_mex_uses_nearest_builder_while_two_spares_reclaim_unique_props() -> None:
    snapshot = macro_snapshot("engineer", "engineer")
    engineers = [unit for unit in snapshot["units"] if unit["role"] == "engineer"]
    engineers.sort(key=lambda unit: unit["token"])
    engineers[0].update(token="10:1", position=[100, 2, 20])
    engineers[1].update(token="20:1", position=[50, 2, 20])
    engineers[2].update(token="99:1", position=[21, 2, 20])
    snapshot["sites"]["mass"] = [mass_site("lost", 20, 20, lost=True)]
    snapshot["macro"].update(lostMexCount=1, constructionBacklog=1)
    snapshot["reclaim"] = [
        {
            "key": "prop-a",
            "position": [51, 2, 20],
            "mass": 200,
            "reserved": False,
            "observerToken": "20:1",
            "visionRadius": 10,
            "observedTick": 0,
        },
        {
            "key": "prop-b",
            "position": [101, 2, 20],
            "mass": 100,
            "reserved": False,
            "observerToken": "10:1",
            "visionRadius": 10,
            "observedTick": 0,
        },
    ]
    result = decide(snapshot)
    builds = [
        intent for intent in intents_of(result, "build_structure")
        if intent.get("buildRole") == "mass_extractor"
    ]
    reclaim = intents_of(result, "reclaim")
    assert [(intent["actorToken"], intent["siteKey"]) for intent in builds] == [
        ("99:1", "lost")
    ]
    assert {
        (intent["actorToken"], intent["targetKey"])
        for intent in reclaim
    } == {("20:1", "prop-a"), ("10:1", "prop-b")}


def test_income_capacity_target_is_rolling_and_falls_after_sustained_normalization() -> None:
    harness = make_harness()
    harness.controller.markers.mass = lua_value(harness.lua, [])
    set_support(harness, mex=8, land=2)
    harness.brain.massIncome = 1.5
    harness.brain.massRequested = 0.5
    harness.brain.massUsage = 0.5
    harness.brain.massStoredRatio = 1.0
    first = harness.observe()
    harness.brain.armyStats.Economy_TotalProduced_Mass = 1.5 * 300
    harness.brain.armyStats.Economy_TotalProduced_Energy = (
        harness.brain.energyIncome * 300
    )
    harness.brain.tick = 300
    high = harness.observe()
    assert high.macro.factoryTarget >= 3
    assert high.macro.factoryDemand >= 3
    harness.brain.massRequested = 0.6
    harness.brain.massUsage = 0.6
    harness.brain.massIncome = 0.7
    harness.brain.massStoredRatio = 0.2
    busy = None
    for tick in range(310, 711, 10):
        harness.brain.armyStats.Economy_TotalProduced_Mass += 0.7 * 10
        harness.brain.armyStats.Economy_TotalProduced_Energy += (
            harness.brain.energyIncome * 10
        )
        harness.brain.tick = tick
        busy = harness.observe()
    assert busy is not None
    assert busy.macro.factoryTarget < high.macro.factoryTarget
    assert busy.macro.factoryTarget == 2
    assert first.macro.factoryTarget <= high.macro.factoryTarget


@pytest.mark.parametrize(
    ("income", "stored", "expected_after_window"),
    [
        (1.49, 1.0, 2),
        (1.5, 0.1, 3),
        (1.5, 0.95, 3),
        (float("inf"), 1.0, 2),
        (float("nan"), 1.0, 2),
    ],
)
def test_factory_capacity_ignores_storage_ratio_and_requires_recurring_window(
    income: float,
    stored: float,
    expected_after_window: int,
) -> None:
    harness = make_harness()
    harness.controller.markers.mass = lua_value(harness.lua, [])
    set_support(harness, mex=8, land=2)
    harness.brain.massIncome = income
    harness.brain.massRequested = 0.0
    harness.brain.massUsage = 0.0
    harness.brain.massStoredRatio = stored
    harness.brain.massTrend = 0.0
    first = harness.observe()
    assert first.macro.factoryTarget == 2
    if income == income and income != float("inf"):
        harness.brain.armyStats.Economy_TotalProduced_Mass = income * 10
        harness.brain.armyStats.Economy_TotalProduced_Energy = 200
    harness.brain.tick = 10
    observation = harness.observe()
    assert observation.macro.factoryTarget == expected_after_window


def test_remote_lost_mex_does_not_prohibit_safe_base_factory_capacity_intent() -> None:
    snapshot = economy_policy_snapshot()
    snapshot["units"].append(engineer_record("99:1", [25, 2, 18]))
    snapshot["macro"].update(factoryTarget=3, factoryDemand=3, massSurplusTicks=300, lostMexCount=1)
    snapshot["sites"]["mass"].append(mass_site("lost-remote", 300, 300, lost=True))
    result = decide(snapshot)
    assert any(intent.get("siteKey") == "lost-remote" for intent in intents_of(result, "build_structure"))
    assert any(intent.get("buildRole") == "land_factory" for intent in intents_of(result, "build_structure"))


@pytest.mark.parametrize(
    ("mex", "land", "hydro", "energy_trend", "energy_stored", "expected"),
    [
        (5, 2, 1, 0, 0.5, False),
        (6, 1, 1, 0, 0.5, False),
        (6, 2, 0, 0, 0.5, False),
        (6, 2, 1, -0.01, 0.5, False),
        (6, 2, 1, 0, 0.49, False),
        (6, 2, 1, 0, 0.5, True),
    ],
)
def test_air_factory_exact_milestone_gate(
    mex: int, land: int, hydro: int, energy_trend: float, energy_stored: float, expected: bool
) -> None:
    roles = ["mass_extractor"] * max(0, mex - 6)
    roles += ["hydrocarbon"] * hydro
    snapshot = economy_policy_snapshot(*roles)
    # The base fixture already has six mex and two land factories.
    if mex < 6:
        removed = 6 - mex
        snapshot["units"] = [
            unit for unit in snapshot["units"]
            if not (unit["role"] == "mass_extractor" and (removed := removed - 1) >= 0)
        ]
    if land < 2:
        removed_land = 2 - land
        retained = []
        for unit in snapshot["units"]:
            if unit["role"] == "land_factory" and removed_land:
                removed_land -= 1
            else:
                retained.append(unit)
        snapshot["units"] = retained
    snapshot["economy"].update(energyTrend=energy_trend, energyStoredRatio=energy_stored)
    builds = [
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "air_factory"
    ]
    assert bool(builds) is expected
    if expected:
        assert len(builds) == 1
        assert builds[0]["reason"] == "first_air_factory"


def test_air_factory_produces_interceptor_and_assigns_fair_defensive_patrol() -> None:
    snapshot = economy_policy_snapshot("hydrocarbon", "air_factory")
    air = next(unit for unit in snapshot["units"] if unit["role"] == "air_factory")
    air.update(idle=True, needsRally=False, canBuild={"air_scout": True, "interceptor": True})
    snapshot["units"].append({
        "token": "899:1",
        "role": "air_scout",
        "complete": True,
        "idle": False,
        "position": [20, 2, 20],
        "canBuild": {},
    })
    interceptor = {
        "token": "900:1",
        "role": "interceptor",
        "complete": True,
        "idle": True,
        "position": [10, 2, 10],
        "canBuild": {},
    }
    snapshot["units"].append(interceptor)
    result = decide(snapshot)
    production = next(
        intent for intent in intents_of(result, "factory_build")
        if intent["actorToken"] == air["token"]
    )
    assert production["actorToken"] == air["token"]
    assert production["buildRole"] == "interceptor"
    patrol = only(result, "air_screen")
    assert patrol["actorTokens"] == ["900:1"]
    assert patrol["position"] in (snapshot["basePosition"], snapshot.get("rallyPosition"))


def test_air_factory_builds_one_scout_before_any_interceptor() -> None:
    snapshot = economy_policy_snapshot("hydrocarbon", "air_factory", "air_factory")
    for unit in snapshot["units"]:
        if unit["role"] == "air_factory":
            unit.update(idle=True, needsRally=False)
            unit["canBuild"].update(air_scout=True, interceptor=True)

    builds = [
        intent for intent in intents_of(decide(snapshot), "factory_build")
        if intent.get("buildRole") in {"air_scout", "interceptor"}
    ]

    assert len(builds) == 1
    assert builds[0]["buildRole"] == "air_scout"
    assert builds[0]["reason"] == "initial_frontier_air_scout"


def test_pending_air_scout_suppresses_duplicate_and_interceptor_until_complete() -> None:
    snapshot = economy_policy_snapshot("hydrocarbon", "air_factory", "air_factory")
    factories = sorted(
        (unit for unit in snapshot["units"] if unit["role"] == "air_factory"),
        key=lambda unit: unit["token"],
    )
    for factory in factories:
        factory["canBuild"].update(air_scout=True, interceptor=True)
    snapshot["pending"].append({
        "kind": "factory_build",
        "actorToken": factories[0]["token"],
        "buildRole": "air_scout",
        "phase": "accepted",
    })

    builds = [
        intent for intent in intents_of(decide(snapshot), "factory_build")
        if intent.get("buildRole") in {"air_scout", "interceptor"}
    ]

    assert builds == []


def test_air_screen_executor_rejects_enemy_target_and_accepts_exact_own_base() -> None:
    harness = make_harness()
    interceptor = harness.unit(entityId=90, blueprintId="uea0102")
    harness.brain.units = harness.lua.table_from([interceptor])
    observation = harness.observe()
    malicious = {
        "kind": "air_screen",
        "actorTokens": ["90:1"],
        "position": plain(observation.targetPosition),
        "priority": 32,
    }

    execute_intents(harness, [malicious], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.patrol) == 0
    assert harness.controller.airAssignments["90:1"] is None

    valid = {**malicious, "position": plain(observation.basePosition)}
    execute_intents(harness, [valid], observation)
    assert plain(harness.calls.sequence) == ["clear", "patrol"]
    assert harness.controller.airAssignments["90:1"] is True


def test_active_campaign_sends_new_interceptors_to_the_secured_anchor() -> None:
    snapshot = economy_policy_snapshot("interceptor", "interceptor")
    for unit in snapshot["units"]:
        if unit["role"] == "interceptor":
            unit.update(idle=True, airAssigned=False)
    snapshot["macro"].update(
        campaignEnabled=True,
        campaignState="active",
        campaignAnchorX=279.5,
        campaignAnchorZ=311.5,
    )

    intent = only(decide(snapshot), "air_screen")

    assert intent["actorTokens"] == sorted(intent["actorTokens"])
    assert intent["position"] == [279.5, 0, 311.5]


@pytest.mark.parametrize("failure", ["clear", "patrol"])
def test_air_screen_command_failure_is_atomic_and_immediately_retryable(
    failure: str,
) -> None:
    harness = make_harness()
    interceptor = harness.unit(entityId=90, blueprintId="uea0102")
    harness.brain.units = harness.lua.table_from([interceptor])
    observation = harness.observe()
    intent = {
        "kind": "air_screen",
        "actorTokens": ["90:1"],
        "position": plain(observation.basePosition),
        "priority": 32,
    }
    setattr(harness.calls, f"fail{failure.title()}", True)

    execute_intents(harness, [intent], observation)

    assert harness.controller.airAssignments["90:1"] is None
    assert harness.controller.airScreenCount == 0
    setattr(harness.calls, f"fail{failure.title()}", False)
    execute_intents(harness, [intent], observation)
    assert harness.controller.airAssignments["90:1"] is True
    assert harness.controller.airScreenCount == 1


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_air_screen_execution_revalidates_exact_live_interceptor_generation(
    mutation: str,
) -> None:
    harness = make_harness()
    interceptor = harness.unit(entityId=90, blueprintId="uea0102")
    harness.brain.units = harness.lua.table_from([interceptor])
    observation = harness.observe()
    if mutation == "dead":
        interceptor.Dead = True
    elif mutation == "captured":
        interceptor.options.army = 2
    else:
        replacement = harness.unit(entityId=90, blueprintId="uea0102")
        harness.brain.units = harness.lua.table_from([replacement])
        harness.controller.unitRefs["90:1"] = replacement

    execute_intents(harness, [{
        "kind": "air_screen",
        "actorTokens": ["90:1"],
        "position": plain(observation.basePosition),
        "priority": 32,
    }], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.patrol) == 0
    assert harness.controller.airAssignments["90:1"] is None


def test_completed_idle_air_scout_targets_exact_public_selected_frontier_site() -> None:
    snapshot = economy_policy_snapshot("hydrocarbon", "air_factory", "air_scout")
    scout = next(unit for unit in snapshot["units"] if unit["role"] == "air_scout")
    scout.update(idle=True, airScoutAssigned=False)
    snapshot["sites"]["mass"] = [mass_site("public-frontier", 70, 40, frontier=True)]
    snapshot["macro"]["selectedFrontierSite"] = "public-frontier"

    intent = only(decide(snapshot), "air_scout")

    assert intent["actorToken"] == scout["token"]
    assert intent["siteKey"] == "public-frontier"
    assert intent["position"] == [70, 2, 40]


def _live_frontier_air_scout() -> tuple[Any, Any, Any, dict[str, Any]]:
    harness = make_harness()
    scout = harness.unit(entityId=91, blueprintId="uea0101", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from([scout])
    first = harness.observe()
    site = next(
        value for value in plain(first.sites.mass)
        if value["key"] == first.macro.selectedFrontierSite
    )
    observation = first
    intent = {
        "kind": "air_scout",
        "actorToken": "91:1",
        "siteKey": site["key"],
        "position": site["position"],
        "priority": 32,
        "reason": "public_frontier_recon",
    }
    return harness, scout, observation, intent


def test_air_factory_executor_accepts_exact_uef_air_scout_product() -> None:
    harness = make_harness()
    factory = harness.unit(
        entityId=80,
        blueprintId="ueb0102",
        canBuild={"uea0101": True},
    )
    harness.brain.units = harness.lua.table_from([factory])
    observation = harness.observe()

    execute_intents(harness, [{
        "kind": "factory_build",
        "actorToken": "80:1",
        "buildRole": "air_scout",
        "priority": 24,
        "reason": "initial_frontier_air_scout",
    }], observation)

    assert len(harness.calls.buildFactory) == 1
    assert harness.calls.buildFactory[1].blueprintId == "uea0101"


def test_frontier_air_scout_orders_once_and_emits_exact_site_telemetry() -> None:
    harness, _, observation, intent = _live_frontier_air_scout()

    execute_intents(harness, [intent], observation)
    execute_intents(harness, [intent], observation)

    assert plain(harness.calls.sequence) == ["clear", "patrol"]
    target = plain(harness.calls.patrol[1].position)
    base = plain(observation.basePosition)
    assert (target[0], target[2]) != (base[0], base[2])
    assert harness.controller.airScoutAssignments["91:1"] is True
    assert any(
        "command=patrol" in line
        and "role=air_scout" in line
        and f"site={intent['siteKey']}" in line
        for line in harness.logs
    )


@pytest.mark.parametrize("invalid", ["missing", "wrong_position", "nan"])
def test_frontier_air_scout_rejects_missing_or_malformed_selected_site(invalid: str) -> None:
    harness, _, observation, intent = _live_frontier_air_scout()
    if invalid == "missing":
        intent["siteKey"] = "missing"
    elif invalid == "wrong_position":
        intent["position"] = [intent["position"][0] + 1, 2, intent["position"][2]]
    else:
        intent["position"] = [intent["position"][0], float("nan"), intent["position"][2]]

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.patrol) == 0


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled", "busy"])
def test_frontier_air_scout_revalidates_exact_live_idle_generation(mutation: str) -> None:
    harness, scout, observation, intent = _live_frontier_air_scout()
    if mutation == "dead":
        scout.Dead = True
    elif mutation == "captured":
        scout.options.army = 2
    elif mutation == "busy":
        scout.options.idleState = False
    else:
        replacement = harness.unit(entityId=91, blueprintId="uea0101")
        harness.brain.units = harness.lua.table_from([replacement])
        harness.controller.unitRefs["91:1"] = replacement

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.patrol) == 0


@pytest.mark.parametrize(
    ("mex", "land", "air", "mass_stored", "expected"),
    [(9, 3, 1, 0.8, False), (10, 2, 1, 0.8, False), (10, 3, 0, 0.8, False), (10, 3, 1, 0.49, False), (10, 3, 1, 0.5, True)],
)
def test_t2_upgrade_exact_milestone_gate(mex: int, land: int, air: int, mass_stored: float, expected: bool) -> None:
    snapshot = economy_policy_snapshot(
        *(["mass_extractor"] * 4),
        *(["land_factory"] * max(0, land - 2)),
        *(["air_factory"] * air),
        "hydrocarbon",
    )
    # Normalize requested boundary counts.
    for role, desired in (("mass_extractor", mex), ("land_factory", land), ("air_factory", air)):
        seen = 0
        retained = []
        for unit in snapshot["units"]:
            if unit["role"] == role:
                seen += 1
                if seen > desired:
                    continue
            retained.append(unit)
        snapshot["units"] = retained
    snapshot["economy"].update(massStoredRatio=mass_stored, massTrend=0)
    for unit in snapshot["units"]:
        if unit["role"] == "land_factory":
            unit["idle"] = True
            unit["canBuild"]["land_factory_t2"] = True
    upgrades = intents_of(decide(snapshot), "factory_upgrade")
    assert bool(upgrades) is expected
    if expected:
        assert len(upgrades) == 1
        assert upgrades[0]["upgradeRole"] == "land_factory_t2"


@pytest.mark.parametrize(
    ("mass_trend", "energy_trend", "energy_stored", "expected"),
    [
        (-0.01, 0, 0.5, False),
        (0, -0.01, 0.5, False),
        (0, 0, 0.49, False),
        (0, 0, 0.5, True),
    ],
)
def test_t2_upgrade_requires_exact_healthy_mass_and_energy_boundaries(
    mass_trend: float,
    energy_trend: float,
    energy_stored: float,
    expected: bool,
) -> None:
    snapshot = economy_policy_snapshot(
        *(["mass_extractor"] * 4),
        "land_factory",
        "air_factory",
        "hydrocarbon",
    )
    snapshot["economy"].update(
        massStoredRatio=0.5,
        energyStoredRatio=energy_stored,
        massTrend=mass_trend,
        energyTrend=energy_trend,
    )
    for unit in snapshot["units"]:
        if unit["role"] == "land_factory":
            unit["idle"] = True
            unit["canBuild"]["land_factory_t2"] = True
    assert bool(intents_of(decide(snapshot), "factory_upgrade")) is expected


@pytest.mark.parametrize(
    ("field", "value", "forbidden_kind"),
    [
        ("energyTrend", float("inf"), "air_factory"),
        ("massTrend", float("inf"), "factory_upgrade"),
        ("energyStoredRatio", float("nan"), "factory_upgrade"),
    ],
)
def test_nonfinite_economy_never_satisfies_air_or_t2_gate(
    field: str,
    value: float,
    forbidden_kind: str,
) -> None:
    if forbidden_kind == "air_factory":
        snapshot = economy_policy_snapshot("hydrocarbon")
    else:
        snapshot = economy_policy_snapshot(
            *(["mass_extractor"] * 4),
            "land_factory",
            "air_factory",
            "hydrocarbon",
        )
    snapshot["economy"][field] = value
    for unit in snapshot["units"]:
        if unit["role"] == "land_factory":
            unit["idle"] = True
            unit["canBuild"]["land_factory_t2"] = True
    result = decide(snapshot)
    if forbidden_kind == "air_factory":
        assert not [
            intent for intent in intents_of(result, "build_structure")
            if intent.get("buildRole") == "air_factory"
        ]
    else:
        assert intents_of(result, "factory_upgrade") == []


def test_upgrade_executor_is_persistent_exact_and_completes_on_exact_t2_blueprint() -> None:
    harness = make_harness()
    factory = harness.unit(
        entityId=70,
        blueprintId="ueb0101",
        position=[12, 2, 20],
        canBuild={"ueb0201": True},
    )
    harness.brain.units = harness.lua.table_from([factory])
    observation = harness.observe()
    intent = {
        "kind": "factory_upgrade",
        "actorToken": "70:1",
        "upgradeRole": "land_factory_t2",
        "priority": 23,
        "reason": "first_t2_land_hq",
    }
    execute_intents(harness, [intent], observation)
    assert len(harness.calls.upgrade) == 1
    assert harness.calls.upgrade[1].blueprintId == "ueb0201"
    assert plain(harness.controller.pending["70:1"])["kind"] == "factory_upgrade"
    factory.options.blueprintId = "ueb0201"
    factory.options.states = lua_value(harness.lua, {})
    factory.options.idleState = True
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None


def test_upgrade_rebinds_to_incomplete_replacement_entity_then_completes_once() -> None:
    harness = make_harness()
    old = harness.unit(
        entityId=70,
        blueprintId="ueb0101",
        position=[12, 2, 20],
        canBuild={"ueb0201": True},
    )
    harness.brain.units = harness.lua.table_from([old])
    observation = harness.observe()
    execute_intents(harness, [{
        "kind": "factory_upgrade",
        "actorToken": "70:1",
        "upgradeRole": "land_factory_t2",
        "priority": 23,
    }], observation)
    target = harness.unit(
        entityId=71,
        blueprintId="ueb0201",
        position=[12.5, 2, 20],
        fraction=0.4,
        idleState=False,
        states={"BeingBuilt": True},
    )
    old.options.focusUnit = target
    harness.brain.units = harness.lua.table_from([old, target])
    harness.brain.tick = 3
    reconcile(harness)
    pending = plain(harness.controller.pending["70:1"])
    assert pending["kind"] == "factory_upgrade"
    assert pending["upgradeTargetToken"] == "71:1"

    old.Dead = True
    harness.brain.units = harness.lua.table_from([target])
    harness.brain.tick = 10
    reconcile(harness)
    assert harness.controller.pending["70:1"] is not None

    target.options.fraction = 1
    target.options.idleState = True
    target.options.states = lua_value(harness.lua, {})
    harness.brain.tick = 20
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None
    assert harness.controller.upgradeState == "completed"


def test_upgrade_binds_exact_focus_target_and_ignores_completed_nearby_decoy() -> None:
    harness = make_harness()
    old = harness.unit(
        entityId=70,
        blueprintId="ueb0101",
        position=[12, 2, 20],
        canBuild={"ueb0201": True},
    )
    target = harness.unit(
        entityId=71,
        blueprintId="ueb0201",
        position=[12.2, 2, 20],
        fraction=0.4,
        idleState=False,
        states={"BeingBuilt": True},
    )
    decoy = harness.unit(
        entityId=72,
        blueprintId="ueb0201",
        position=[12.4, 2, 20],
    )
    harness.brain.units = harness.lua.table_from([old])
    observation = harness.observe()
    execute_intents(harness, [{
        "kind": "factory_upgrade",
        "actorToken": "70:1",
        "upgradeRole": "land_factory_t2",
        "priority": 23,
    }], observation)
    old.options.focusUnit = target
    harness.brain.units = harness.lua.table_from([old, target, decoy])
    harness.brain.tick = 3
    reconcile(harness)
    pending = plain(harness.controller.pending["70:1"])
    assert pending["upgradeTargetToken"] == "71:1"
    assert pending.get("completedToken") is None

    target.options.fraction = 1
    target.options.idleState = True
    target.options.states = lua_value(harness.lua, {})
    harness.brain.tick = 10
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None


def test_live_upgrading_source_without_focus_does_not_bind_unrelated_t2_foundation() -> None:
    harness = make_harness()
    old = harness.unit(
        entityId=70,
        blueprintId="ueb0101",
        position=[12, 2, 20],
        canBuild={"ueb0201": True},
    )
    unrelated = harness.unit(
        entityId=71,
        blueprintId="ueb0201",
        position=[12.2, 2, 20],
        fraction=0.4,
        idleState=False,
        states={"BeingBuilt": True},
    )
    harness.brain.units = harness.lua.table_from([old])
    observation = harness.observe()
    execute_intents(harness, [{
        "kind": "factory_upgrade",
        "actorToken": "70:1",
        "upgradeRole": "land_factory_t2",
        "priority": 23,
    }], observation)
    harness.brain.units = harness.lua.table_from([old, unrelated])
    harness.brain.tick = 3
    reconcile(harness)
    pending = plain(harness.controller.pending["70:1"])
    assert pending.get("upgradeTargetToken") is None
    assert pending["accepted"] is False


def test_lost_upgrade_source_without_bound_focus_does_not_claim_nearby_t2() -> None:
    harness = make_harness()
    old = harness.unit(
        entityId=70,
        blueprintId="ueb0101",
        position=[12, 2, 20],
        canBuild={"ueb0201": True},
    )
    unrelated = harness.unit(
        entityId=71,
        blueprintId="ueb0201",
        position=[12.2, 2, 20],
        fraction=0.4,
        idleState=False,
        states={"BeingBuilt": True},
    )
    harness.brain.units = harness.lua.table_from([old])
    observation = harness.observe()
    execute_intents(harness, [{
        "kind": "factory_upgrade",
        "actorToken": "70:1",
        "upgradeRole": "land_factory_t2",
        "priority": 23,
    }], observation)
    old.Dead = True
    harness.brain.units = harness.lua.table_from([unrelated])
    harness.brain.tick = 3

    reconcile(harness)

    assert harness.controller.pending["70:1"] is None
    assert str(harness.controller.upgradeState).startswith("failed:actor_missing")


def test_upgrade_accepted_then_old_factory_idle_releases_for_immediate_retry() -> None:
    harness = make_harness()
    factory = harness.unit(
        entityId=70,
        blueprintId="ueb0101",
        canBuild={"ueb0201": True},
    )
    target = harness.unit(
        entityId=71,
        blueprintId="ueb0201",
        fraction=0.2,
        idleState=False,
        states={"BeingBuilt": True},
    )
    harness.brain.units = harness.lua.table_from([factory])
    observation = harness.observe()
    intent = {
        "kind": "factory_upgrade",
        "actorToken": "70:1",
        "upgradeRole": "land_factory_t2",
        "priority": 23,
    }
    execute_intents(harness, [intent], observation)
    factory.options.focusUnit = target
    harness.brain.units = harness.lua.table_from([factory, target])
    harness.brain.tick = 3
    reconcile(harness)
    assert harness.controller.pending["70:1"].accepted is True
    factory.options.states = lua_value(harness.lua, {})
    factory.options.queue = lua_value(harness.lua, {})
    factory.options.idleState = True
    harness.brain.tick = 13
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None
    assert str(harness.controller.upgradeState).startswith("failed:rejected")
    retry_observation = harness.observe()
    execute_intents(harness, [intent], retry_observation)
    assert harness.controller.pending["70:1"] is not None


def test_pending_upgrade_replaces_capacity_instead_of_ratcheting_factory_target() -> None:
    harness = make_harness()
    harness.controller.markers.mass = lua_value(harness.lua, [])
    factories = [
        harness.unit(
            entityId=70 + index,
            blueprintId="ueb0101",
            position=[12 + index * 4, 2, 20],
            canBuild={"ueb0201": True},
        )
        for index in range(3)
    ]
    air = harness.unit(entityId=80, blueprintId="ueb0102", position=[30, 2, 20])
    harness.brain.units = harness.lua.table_from([*factories, air])
    harness.brain.massIncome = 2
    harness.brain.massRequested = 0
    harness.brain.massUsage = 0
    harness.brain.energyIncome = 30
    harness.brain.energyRequested = 10
    harness.brain.energyUsage = 10
    harness.observe()
    harness.brain.armyStats.Economy_TotalProduced_Mass = 20
    harness.brain.armyStats.Economy_TotalProduced_Energy = 300
    harness.brain.tick = 10
    first = harness.observe()
    assert first.macro.factoryTarget == 4
    execute_intents(harness, [{
        "kind": "factory_upgrade",
        "actorToken": "70:1",
        "upgradeRole": "land_factory_t2",
        "priority": 23,
    }], first)
    target = harness.unit(
        entityId=90,
        blueprintId="ueb0201",
        position=[12.5, 2, 20],
        fraction=0.3,
        idleState=False,
        states={"BeingBuilt": True},
    )
    factories[0].options.focusUnit = target
    harness.brain.units = harness.lua.table_from([*factories, air, target])
    harness.brain.armyStats.Economy_TotalProduced_Mass = 40
    harness.brain.armyStats.Economy_TotalProduced_Energy = 600
    harness.brain.tick = 20
    second = harness.observe()
    assert second.macro.buildingLandT2Factories == 1
    assert second.macro.factoryTarget == 4


def test_pending_upgrade_replaces_source_capacity_when_planning_next_factory() -> None:
    snapshot = economy_policy_snapshot("land_factory", "air_factory")
    source_factory = next(
        unit for unit in snapshot["units"] if unit["role"] == "land_factory"
    )
    snapshot["pending"] = [{
        "kind": "factory_upgrade",
        "actorToken": source_factory["token"],
        "buildRole": "land_factory_t2",
        "upgradeRole": "land_factory_t2",
        "position": source_factory["position"],
    }]
    snapshot["macro"].update(
        factoryTarget=5,
        factoryDemand=5,
        massSurplusTicks=300,
    )
    snapshot["placements"]["land_factory"].append([40, 2, 20])

    land_builds = [
        intent
        for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "land_factory"
    ]

    assert len(land_builds) == 1
    assert land_builds[0]["actorToken"] != source_factory["token"]


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_upgrade_preflight_rejects_dead_captured_or_recycled_factory(mutation: str) -> None:
    harness = make_harness()
    factory = harness.unit(entityId=70, blueprintId="ueb0101", canBuild={"ueb0201": True})
    harness.brain.units = harness.lua.table_from([factory])
    observation = harness.observe()
    if mutation == "dead":
        factory.Dead = True
    elif mutation == "captured":
        factory.options.army = 2
    else:
        replacement = harness.unit(entityId=70, blueprintId="ueb0101", canBuild={"ueb0201": True})
        harness.brain.units = harness.lua.table_from([replacement])
        harness.controller.unitRefs["70:1"] = replacement
    execute_intents(harness, [{
        "kind": "factory_upgrade",
        "actorToken": "70:1",
        "upgradeRole": "land_factory_t2",
        "priority": 23,
    }], observation)
    assert len(harness.calls.upgrade) == 0
    assert harness.controller.pending["70:1"] is None


def test_upgrade_issue_failure_is_atomic_and_immediately_retryable() -> None:
    harness = make_harness()
    factory = harness.unit(entityId=70, blueprintId="ueb0101", canBuild={"ueb0201": True})
    harness.brain.units = harness.lua.table_from([factory])
    intent = {"kind": "factory_upgrade", "actorToken": "70:1", "upgradeRole": "land_factory_t2", "priority": 23}
    observation = harness.observe()
    harness.calls.failUpgrade = True
    execute_intents(harness, [intent], observation)
    assert harness.controller.pending["70:1"] is None
    harness.calls.failUpgrade = False
    execute_intents(harness, [intent], observation)
    assert len(harness.calls.upgrade) == 2
    assert harness.controller.pending["70:1"] is not None


@pytest.mark.parametrize(
    ("producer", "product"),
    [("ueb0102", "tank"), ("ueb0101", "interceptor"), ("ueb0101", "t2_direct_fire")],
)
def test_factory_executor_rejects_illegal_domain_or_tier_pair(producer: str, product: str) -> None:
    harness = make_harness()
    factory = harness.unit(entityId=80, blueprintId=producer, canBuild={
        "uel0201": True, "uea0102": True, "uel0202": True,
    })
    harness.brain.units = harness.lua.table_from([factory])
    observation = harness.observe()
    execute_intents(harness, [{
        "kind": "factory_build", "actorToken": "80:1", "buildRole": product, "priority": 31,
    }], observation)
    assert len(harness.calls.buildFactory) == 0
    assert harness.controller.pending["80:1"] is None


def test_t2_land_factory_accepts_only_t2_ground_mix() -> None:
    harness = make_harness()
    factory = harness.unit(
        entityId=81,
        blueprintId="ueb0201",
        canBuild={"uel0202": True, "uel0205": True},
    )
    harness.brain.units = harness.lua.table_from([factory])
    observation = harness.observe()
    execute_intents(harness, [{
        "kind": "factory_build", "actorToken": "81:1", "buildRole": "t2_direct_fire", "priority": 31,
    }], observation)
    assert len(harness.calls.buildFactory) == 1
    assert harness.calls.buildFactory[1].blueprintId == "uel0202"


def activate_campaign(harness: Any, observation: Any) -> None:
    execute_intents(harness, campaign_intents(harness, observation), observation)
    assert campaign_state(harness)["state"] == "active"


def test_readiness_loss_blocks_advancement_without_inventing_a_rollback() -> None:
    harness, _, _, _, observation = start_campaign(total=24, aa=2)
    activate_campaign(harness, observation)
    harness.brain.supportUnits = harness.lua.table_from([])
    harness.brain.tick = 10
    observation = reconcile(harness)
    assert observation.macro.campaignReady is False
    assert campaign_intents(harness, observation) == []
    assert campaign_state(harness)["state"] == "active"
    assert campaign_state(harness)["rollbackOrders"] == 0


@pytest.mark.parametrize("seed", range(3))
def test_immediate_contact_preempts_not_ready_awaiting_activation(seed: int) -> None:
    harness, acu, engineer, combat, _ = start_campaign(seed=seed)
    state = campaign_state(harness)
    field = set(state["fieldTokens"])
    home = sorted(state["homeTokens"])
    live = [
        actor
        for actor in combat
        if f"{int(actor.options.entityId)}:1" in field | set(home[:3])
    ]
    harness.brain.units = harness.lua.table_from([acu, engineer, *live])
    harness.brain.supportUnits = harness.lua.table_from([])
    harness.brain.enemies = harness.lua.table_from([
        harness.unit(entityId=99000, blueprintId="uel0201", army=2, position=[15, 2, 20])
    ])
    harness.brain.tick = 10

    current = reconcile(harness)

    recall = only(campaign_intents(harness, current), "field_campaign")
    assert current.macro.campaignReady is False
    assert recall["mode"] == "recall"


@pytest.mark.parametrize("emergency", ["contact", "acu_health"])
def test_emergency_recall_preempts_same_tick_attrition_rollback(emergency: str) -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    state = campaign_state(harness)
    field = sorted(state["fieldTokens"])
    home = sorted(state["homeTokens"])
    removed = set(field[:5])
    if emergency == "contact":
        removed.update(home[:3])
        harness.brain.enemies = harness.lua.table_from([
            harness.unit(entityId=99000, blueprintId="uel0201", army=2, position=[15, 2, 20])
        ])
    else:
        acu.options.health = 69
    live = [
        actor
        for actor in combat
        if f"{int(actor.options.entityId)}:1" not in removed
    ]
    harness.brain.units = harness.lua.table_from([acu, engineer, *live])
    harness.brain.tick = 10

    current = reconcile(harness)

    recall = only(campaign_intents(harness, current), "field_campaign")
    assert recall["mode"] == "recall"
    assert campaign_state(harness).get("pendingRollbackReason") is None


def test_rebuilding_campaign_still_rebalances_for_immediate_home_contact() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    state = campaign_state(harness)
    field = sorted(state["fieldTokens"])
    home = sorted(state["homeTokens"])
    by_token = {
        f"{int(actor.options.entityId)}:1": actor
        for actor in combat
    }
    survivors = [
        actor for token, actor in by_token.items()
        if token not in set(field[:5])
    ]
    harness.brain.units = harness.lua.table_from([acu, engineer, *survivors])
    harness.brain.tick = 10
    rollback_observation = reconcile(harness)
    rollback = only(campaign_intents(harness, rollback_observation), "field_campaign")
    assert rollback["mode"] == "rollback"
    execute_intents(harness, [rollback], rollback_observation)
    assert campaign_state(harness)["state"] == "rebuilding"

    removed_home = set(home[:3])
    survivors = [
        actor
        for actor in survivors
        if f"{int(actor.options.entityId)}:1" not in removed_home
    ]
    harness.brain.units = harness.lua.table_from([acu, engineer, *survivors])
    harness.brain.enemies = harness.lua.table_from([
        harness.unit(entityId=99000, blueprintId="uel0201", army=2, position=[15, 2, 20])
    ])
    harness.brain.tick = 20

    current = reconcile(harness)

    recall = only(campaign_intents(harness, current), "field_campaign")
    assert recall["mode"] == "recall"


@pytest.mark.parametrize("mode", ["transition", "assault"])
def test_readiness_loss_cancels_staged_forward_advancement_until_restored(mode: str) -> None:
    harness, _, _ = setup_pressure_mode(mode)
    before = campaign_state(harness)
    harness.brain.supportUnits = harness.lua.table_from([])
    harness.brain.tick += 1
    blocked = reconcile(harness)
    assert blocked.macro.campaignReady is False
    assert campaign_intents(harness, blocked) == []
    assert campaign_state(harness)["clusterKey"] == before["clusterKey"]
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert campaign_state(harness)["rollbackOrders"] == 0

    set_support(harness, mex=8, land=3)
    harness.brain.tick += 1
    restored = reconcile(harness)
    forward = campaign_intents(harness, restored)
    assert len(forward) == 1 and forward[0]["mode"] == "route_probe"


@pytest.mark.parametrize(("lost", "should_rollback"), [(24, False), (25, True)])
def test_field_attrition_exact_24_9_and_25_percent_boundaries(lost: int, should_rollback: bool) -> None:
    # 134 total -> floor(3N/4) == 100 field units, making the percentage exact.
    harness, acu, engineer, combat, observation = start_campaign(total=134, aa=14)
    activate_campaign(harness, observation)
    field = set(campaign_state(harness)["fieldTokens"])
    survivors = [actor for actor in combat if f"{int(actor.options.entityId)}:1" not in set(sorted(field)[:lost])]
    harness.brain.units = harness.lua.table_from([acu, engineer, *survivors])
    harness.brain.tick = 599
    observation = reconcile(harness)
    modes = [intent["mode"] for intent in campaign_intents(harness, observation)]
    assert ("rollback" in modes) is should_rollback


def test_field_attrition_is_captured_before_same_tick_new_units_refill_the_cohort() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=24, aa=2)
    activate_campaign(harness, observation)
    state = campaign_state(harness)
    field = set(state["fieldTokens"])
    killed = set(
        token for token in sorted(field) if token.startswith("2")
    )
    killed = set(sorted(killed)[:5])  # 5 / 18 exceeds the exact 25% boundary.
    survivors = [
        actor for actor in combat
        if f"{int(actor.options.entityId)}:1" not in killed
    ]
    replacements = [
        harness.unit(entityId=9000 + index, blueprintId="uel0201")
        for index in range(8)
    ]
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, *survivors, *replacements]
    )
    harness.brain.tick = 100
    current = reconcile(harness)
    rollback = only(campaign_intents(harness, current), "field_campaign")
    assert rollback["mode"] == "rollback"
    assert rollback["reason"] == "field_attrition"


def test_successful_reinforcement_raises_attrition_high_water_before_same_tick_refill() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=24, aa=2)
    activate_campaign(harness, observation)
    additions = [
        harness.unit(entityId=9700 + index, blueprintId="uel0201")
        for index in range(8)
    ]
    harness.brain.units = harness.lua.table_from([acu, engineer, *combat, *additions])
    harness.brain.tick = 10
    reinforced_observation = reconcile(harness)
    reinforce = only(campaign_intents(harness, reinforced_observation), "field_campaign")
    assert reinforce["mode"] == "reinforce"
    execute_intents(harness, [reinforce], reinforced_observation)
    assert harness.controller.fieldCampaign.attritionBaseline == 24

    field = set(campaign_state(harness)["fieldTokens"])
    killed = set(
        token for token in sorted(field)
        if token.startswith("2") or token.startswith("97")
    )
    killed = set(sorted(killed)[:6])
    all_combat = [*combat, *additions]
    survivors = [
        actor for actor in all_combat
        if f"{int(actor.options.entityId)}:1" not in killed
    ]
    replacements = [
        harness.unit(entityId=9900 + index, blueprintId="uel0201")
        for index in range(6)
    ]
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, *survivors, *replacements]
    )
    harness.brain.tick = 100
    current = reconcile(harness)
    rollback = only(campaign_intents(harness, current), "field_campaign")
    assert rollback["mode"] == "rollback"
    assert rollback["reason"] == "field_attrition"


@pytest.mark.parametrize(("tick", "rollback"), [(600, True), (601, False)])
def test_field_attrition_window_is_inclusive_at_600_and_expires_at_601(
    tick: int,
    rollback: bool,
) -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=24, aa=2)
    activate_campaign(harness, observation)
    field = set(campaign_state(harness)["fieldTokens"])
    killed = set(
        token for token in sorted(field)
        if token.startswith("2")
    )
    killed = set(sorted(killed)[:5])
    survivors = [
        actor for actor in combat
        if f"{int(actor.options.entityId)}:1" not in killed
    ]
    replacements = [
        harness.unit(entityId=9800 + index, blueprintId="uel0201")
        for index in range(5)
    ]
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, *survivors, *replacements]
    )
    harness.brain.tick = tick
    current = reconcile(harness)
    modes = [intent["mode"] for intent in campaign_intents(harness, current)]
    assert ("rollback" in modes) is rollback


def test_second_no_progress_window_rolls_back_instead_of_same_anchor_recovery_spam() -> None:
    harness, _, _, _, observation = start_campaign(total=24, aa=2)
    activate_campaign(harness, observation)
    harness.brain.tick = 300
    first = reconcile(harness)
    assert only(campaign_intents(harness, first), "field_campaign")["mode"] == "recover"
    execute_intents(harness, campaign_intents(harness, first), first)
    harness.brain.tick = 600
    second = reconcile(harness)
    intent = only(campaign_intents(harness, second), "field_campaign")
    assert intent["mode"] == "rollback"
    execute_intents(harness, [intent], second)
    assert campaign_state(harness)["rollbackReason"] == "repeated_no_progress"


def test_rollback_clear_or_move_failure_preserves_exact_state_and_retries() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=24, aa=2)
    activate_campaign(harness, observation)
    field = set(campaign_state(harness)["fieldTokens"])
    killed = set(token for token in sorted(field) if token.startswith("2"))
    killed = set(sorted(killed)[:5])
    survivors = [
        actor for actor in combat
        if f"{int(actor.options.entityId)}:1" not in killed
    ]
    replacements = [
        harness.unit(entityId=9850 + index, blueprintId="uel0201")
        for index in range(5)
    ]
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, *survivors, *replacements]
    )
    harness.brain.tick = 100
    observation = reconcile(harness)
    intent = only(campaign_intents(harness, observation), "field_campaign")
    assert intent["mode"] == "rollback"
    before = campaign_state(harness)
    for flag in ("failClear", "failMove"):
        setattr(harness.calls, flag, True)
        execute_intents(harness, [intent], observation)
        assert campaign_state(harness) == before
        setattr(harness.calls, flag, False)
    execute_intents(harness, [intent], observation)
    assert campaign_state(harness)["rollbackOrders"] == 1


def test_rebuilding_campaign_resumes_only_after_full_readiness_returns() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=24, aa=2)
    activate_campaign(harness, observation)
    field = set(campaign_state(harness)["fieldTokens"])
    killed = set(token for token in sorted(field) if token.startswith("2"))
    killed = set(sorted(killed)[:5])
    survivors = [
        actor for actor in combat
        if f"{int(actor.options.entityId)}:1" not in killed
    ]
    replacements = [
        harness.unit(entityId=9860 + index, blueprintId="uel0201")
        for index in range(5)
    ]
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, *survivors, *replacements]
    )
    harness.brain.tick = 100
    rollback = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, rollback), rollback)
    harness.brain.supportUnits = harness.lua.table_from([])
    harness.brain.tick = 400
    blocked = reconcile(harness)
    assert campaign_intents(harness, blocked) == []
    set_support(harness, mex=8, land=3)
    harness.brain.tick = 699
    cooling_down = reconcile(harness)
    assert campaign_intents(harness, cooling_down) == []
    harness.brain.tick = 700
    ready = reconcile(harness)
    assert only(campaign_intents(harness, ready), "field_campaign")["mode"] == "resume"


def test_escalation_telemetry_fields_are_scalar_and_rate_limited() -> None:
    harness = make_harness()
    set_support(harness, mex=10, land=3, air=1, hydro=1)
    harness.brain.tick = 0
    harness.lua.globals().Controller.Step(harness.controller)
    harness.brain.tick = 100
    harness.lua.globals().Controller.Step(harness.controller)
    harness.brain.tick = 300
    harness.lua.globals().Controller.Step(harness.controller)
    snapshots = [line for line in harness.logs if "event=snapshot" in line]
    assert len(snapshots) == 2
    required = {
        "economy_stage",
        "factory_target",
        "land_t1_completed",
        "land_t1_building",
        "air_t1_completed",
        "air_t1_building",
        "land_t2_completed",
        "land_t2_building",
        "placement_capacity",
        "placement_probes",
        "upgrade_state",
        "air_screen",
        "reclaim_candidate_value",
        "campaign_ready",
        "campaign_readiness_blockers",
        "rollback_reason",
        "field_attrition_lost",
        "field_attrition_window",
    }
    fields = {match.group(1) for match in re.finditer(r"(?:^|\|)([a-z0-9_]+)=", snapshots[-1])}
    assert required <= fields
    assert "table:" not in snapshots[-1]


def test_escalation_telemetry_reports_real_completed_and_building_factory_domains() -> None:
    harness = make_harness()
    harness.brain.units = harness.lua.table_from([
        harness.unit(entityId=10, blueprintId="ueb0101"),
        harness.unit(entityId=11, blueprintId="ueb0101", fraction=0.4),
        harness.unit(entityId=12, blueprintId="ueb0102", fraction=0.3),
        harness.unit(entityId=13, blueprintId="ueb0201", fraction=0.8),
    ])
    observation = harness.observe()
    assert observation.macro.completedLandT1Factories == 1
    assert observation.macro.buildingLandT1Factories == 1
    assert observation.macro.completedAirT1Factories == 0
    assert observation.macro.buildingAirT1Factories == 1
    assert observation.macro.completedLandT2Factories == 0
    assert observation.macro.buildingLandT2Factories == 1
    harness.lua.globals().Controller.Step(harness.controller)
    snapshot = next(line for line in harness.logs if "event=snapshot" in line)
    for fragment in (
        "land_t1_completed=1",
        "land_t1_building=1",
        "air_t1_completed=0",
        "air_t1_building=1",
        "land_t2_completed=0",
        "land_t2_building=1",
    ):
        assert fragment in snapshot


def test_runtime_keeps_bounded_probe_and_luaplus_local_headroom_contracts() -> None:
    controller = source("lua/AI/Overmind4/Controller.lua")
    assert "MAX_PLACEMENT_PROBES" in controller
    assert "MAX_PLACEMENT_RADIUS" in controller
    top_level_locals = re.findall(
        r"^local\s+(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)",
        controller,
        re.MULTILINE,
    )
    assert len(top_level_locals) <= 195
    assert "GetUnitsInRect" not in controller
    assert "GetEntitiesInRect" not in controller
