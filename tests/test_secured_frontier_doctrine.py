from __future__ import annotations

import copy
import itertools
import random
from typing import Any

import pytest

from test_controller import execute_intents, make_harness
from test_policy import (
    decide,
    intents_of,
    lua_value,
    plain,
    post_opening_snapshot,
    role_counts,
)


FORBIDDEN_OFFENSE = {
    "mobilize_commander",
    "commander_push",
    "reinforce_commander",
    "attack_wave",
}


def mass_site(
    key: str,
    x: float,
    z: float,
    *,
    occupied: bool = False,
    complete: bool | None = None,
    lost: bool = False,
    frontier: bool = False,
    reachable: bool = True,
    buildable: bool = True,
    reserved: bool = False,
    local: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "name": key,
        "position": [x, 2, z],
        "distance": ((x - 10) ** 2 + (z - 10) ** 2) ** 0.5,
        "localSite": local,
        "reachable": reachable,
        "buildable": buildable,
        "occupied": occupied,
        "complete": occupied if complete is None else complete,
        "reserved": reserved,
        "everOwned": occupied or lost,
        "lost": lost,
        "frontierSelected": frontier,
        "clusterKey": "cluster-a" if frontier else "none",
    }


def macro_snapshot(*extra_roles: str) -> dict[str, Any]:
    snapshot = post_opening_snapshot("engineer", *extra_roles)
    snapshot["economy"] = {
        "energyTrend": 2,
        "energyStoredRatio": 0.8,
        "energyIncome": 30,
        "energyUsage": 20,
        "massTrend": 1,
        "massStoredRatio": 0.5,
        "massIncome": 8,
        "massUsage": 7,
        "unusedMass": 1,
    }
    snapshot["macro"] = {
        "ownedMexCount": 4,
        "lostMexCount": 0,
        "rebuiltMexCount": 0,
        "activeRebuildJobs": 0,
        "activeFrontierJobs": 0,
        "activeReclaimJobs": 0,
        "constructionBacklog": 0,
        "frontierWork": 0,
        "engineerDemand": 2,
        "factoryDemand": 2,
        "massSurplusTicks": 0,
        "selectedFrontierCluster": "none",
        "selectedFrontierSite": "none",
        "frontierOwned": 0,
        "frontierTotal": 0,
        "frontierScreenCount": 0,
        "homeReserveCount": 0,
        "reclaimTarget": "none",
        "reclaimValue": -1,
    }
    snapshot["reclaim"] = []
    for unit in snapshot["units"]:
        if unit["role"] == "land_factory":
            unit["needsRally"] = False
            unit["canBuild"] = {
                "engineer": True,
                "scout": True,
                "tank": True,
                "artillery": True,
                "anti_air": True,
            }
    return snapshot


def engineer_tokens(snapshot: dict[str, Any]) -> list[str]:
    return sorted(unit["token"] for unit in snapshot["units"] if unit["role"] == "engineer")


def install_markers(harness: Any, markers: list[dict[str, Any]]) -> None:
    harness.controller.markers.mass = lua_value(harness.lua, markers)


def marker(key: str, x: float, z: float, *, reachable: bool = True) -> dict[str, Any]:
    return {
        "key": key,
        "name": key,
        "kind": "mass",
        "position": [x, 2, z],
        "distance": ((x - 10) ** 2 + (z - 20) ** 2) ** 0.5,
        "reachable": reachable,
        "localSite": False,
    }


def test_lost_mex_is_rebuilt_before_nearer_new_frontier_expansion() -> None:
    snapshot = macro_snapshot()
    snapshot["sites"]["mass"].extend(
        [
            mass_site("new-near", 22, 20, frontier=True),
            mass_site("lost-far", 60, 20, lost=True),
        ]
    )
    snapshot["macro"].update(lostMexCount=1, constructionBacklog=2, frontierWork=1)

    builds = [
        intent
        for intent in intents_of(decide(snapshot), "build_structure")
        if intent["actorToken"] in engineer_tokens(snapshot)
    ]

    assert builds[0]["siteKey"] == "lost-far"
    assert builds[0]["reason"] == "rebuild_mex"


def test_initially_empty_marker_is_not_mislabeled_as_a_rebuild() -> None:
    snapshot = macro_snapshot()
    snapshot["sites"]["mass"].append(mass_site("never-owned", 25, 20, frontier=True))
    snapshot["macro"].update(frontierWork=1, selectedFrontierCluster="cluster-a")

    builds = intents_of(decide(snapshot), "build_structure")

    assert not [intent for intent in builds if intent.get("reason") == "rebuild_mex"]
    frontier = [intent for intent in builds if intent.get("buildRole") == "mass_extractor"]
    assert frontier[0]["siteKey"] == "never-owned"
    assert frontier[0]["reason"] == "frontier_expansion"


def test_policy_honors_persistent_selected_frontier_site_within_cluster() -> None:
    snapshot = macro_snapshot()
    snapshot["sites"]["mass"].extend(
        [
            dict(mass_site("near-member", 22, 20, frontier=True), clusterKey="cluster-a"),
            dict(mass_site("selected-member", 40, 20, frontier=True), clusterKey="cluster-a"),
        ]
    )
    snapshot["macro"].update(
        frontierWork=2,
        constructionBacklog=2,
        selectedFrontierCluster="cluster-a",
        selectedFrontierSite="selected-member",
    )

    expansion = next(
        intent
        for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("reason") == "frontier_expansion"
    )

    assert expansion["siteKey"] == "selected-member"


def test_rebuild_and_frontier_sites_have_unique_engineer_and_site_ownership() -> None:
    snapshot = macro_snapshot("engineer", "engineer")
    snapshot["sites"]["mass"].extend(
        [
            mass_site("lost-a", 30, 20, lost=True),
            mass_site("lost-b", 35, 20, lost=True),
            mass_site("frontier", 40, 20, frontier=True),
        ]
    )
    snapshot["macro"].update(lostMexCount=2, constructionBacklog=3, frontierWork=1)

    builds = [
        intent
        for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "mass_extractor"
    ]

    assert [intent["siteKey"] for intent in builds[:2]] == ["lost-a", "lost-b"]
    assert len({intent["actorToken"] for intent in builds}) == len(builds)
    assert len({intent["siteKey"] for intent in builds}) == len(builds)


def test_owned_lost_and_rebuilt_mex_transitions_are_observed_once() -> None:
    harness = make_harness()
    mex = harness.unit(entityId=10, blueprintId="ueb1103", position=[12, 2, 20])
    harness.brain.units = harness.lua.table_from([mex])
    first = plain(harness.observe())
    assert first.get("macro", {}).get("ownedMexCount") == 1
    assert first.get("macro", {}).get("lostMexCount") == 0

    harness.brain.units = harness.lua.table_from([])
    lost = plain(harness.observe())
    again = plain(harness.observe())
    assert lost.get("macro", {}).get("lostMexCount") == 1
    assert again.get("macro", {}).get("lostMexCount") == 1
    assert len([line for line in harness.logs if "event=mex_lost" in line]) == 1

    foundation = harness.unit(
        entityId=11,
        blueprintId="ueb1103",
        position=[12, 2, 20],
        fraction=0,
        busy=True,
    )
    harness.brain.units = harness.lua.table_from([foundation])
    rebuilding = plain(harness.observe())
    assert rebuilding.get("macro", {}).get("lostMexCount") == 1
    assert rebuilding.get("macro", {}).get("rebuiltMexCount") == 0

    replacement = harness.unit(entityId=11, blueprintId="ueb1103", position=[12, 2, 20])
    harness.brain.units = harness.lua.table_from([replacement])
    rebuilt = plain(harness.observe())
    plain(harness.observe())
    assert rebuilt.get("macro", {}).get("lostMexCount") == 0
    assert rebuilt.get("macro", {}).get("rebuiltMexCount") == 1
    assert len([line for line in harness.logs if "event=mex_rebuilt" in line]) == 1


@pytest.mark.parametrize("permutation_seed", range(8))
def test_frontier_cluster_selection_is_deterministic_under_marker_permutations(
    permutation_seed: int,
) -> None:
    harness = make_harness()
    markers = [
        marker("owned", 12, 20),
        marker("a1", 40, 20),
        marker("a2", 46, 22),
        marker("b1", 75, 20),
        marker("b2", 80, 22),
    ]
    random.Random(permutation_seed).shuffle(markers)
    install_markers(harness, markers)
    owned = harness.unit(entityId=10, blueprintId="ueb1103", position=[12, 2, 20])
    harness.brain.units = harness.lua.table_from([owned])

    observation = plain(harness.observe())
    macro = observation.get("macro", {})

    assert macro.get("selectedFrontierCluster") == "a1"
    assert macro.get("selectedFrontierSite") == "a1"
    selected = [site["key"] for site in observation["sites"]["mass"] if site.get("frontierSelected")]
    assert selected == ["a1", "a2"]


def test_frontier_ignores_unreachable_malformed_and_disconnected_clusters() -> None:
    harness = make_harness()
    install_markers(
        harness,
        [
            marker("owned", 12, 20),
            marker("unreachable", 25, 20, reachable=False),
            {"key": "malformed", "name": "malformed", "kind": "mass", "reachable": True},
            marker("disconnected", 400, 400),
            marker("valid", 45, 20),
        ],
    )
    owned = harness.unit(entityId=10, blueprintId="ueb1103", position=[12, 2, 20])
    harness.brain.units = harness.lua.table_from([owned])

    macro = plain(harness.observe()).get("macro", {})

    assert macro.get("selectedFrontierCluster") == "valid"
    assert macro.get("selectedFrontierSite") == "valid"


def test_equal_distance_frontier_tie_breaks_by_stable_cluster_key() -> None:
    harness = make_harness()
    install_markers(
        harness,
        [
            marker("owned", 10, 20),
            marker("z-cluster", 40, 20),
            marker("a-cluster", -20, 20),
        ],
    )
    owned = harness.unit(entityId=10, blueprintId="ueb1103", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from([owned])

    macro = plain(harness.observe()).get("macro", {})

    assert macro.get("selectedFrontierCluster") == "a-cluster"


def test_selected_frontier_is_retained_until_secured_then_reselected() -> None:
    harness = make_harness()
    original = [marker("owned", 12, 20), marker("held-a", 45, 20), marker("held-b", 50, 22)]
    install_markers(harness, original)
    owned = harness.unit(entityId=10, blueprintId="ueb1103", position=[12, 2, 20])
    harness.brain.units = harness.lua.table_from([owned])
    first = plain(harness.observe()).get("macro", {})
    assert first.get("selectedFrontierCluster") == "held-a"

    install_markers(harness, original + [marker("new-nearer", 20, 20)])
    retained = plain(harness.observe()).get("macro", {})
    assert retained.get("selectedFrontierCluster") == "held-a"

    first_mex = harness.unit(entityId=11, blueprintId="ueb1103", position=[45, 2, 20])
    harness.brain.units = harness.lua.table_from([owned, first_mex])
    advancing = plain(harness.observe()).get("macro", {})
    assert advancing.get("selectedFrontierCluster") == "held-a"
    assert advancing.get("selectedFrontierSite") == "held-b"
    assert any(
        "event=frontier_selected" in line and "cluster=held-a" in line and "site=held-b" in line
        for line in harness.logs
    )

    second_mex = harness.unit(entityId=12, blueprintId="ueb1103", position=[50, 2, 22])
    harness.brain.units = harness.lua.table_from([owned, first_mex, second_mex])
    reselection = plain(harness.observe()).get("macro", {})
    assert reselection.get("selectedFrontierCluster") == "new-nearer"


def test_far_engineer_build_gets_speed_scaled_deadline_beyond_old_900_ticks() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
        blueprintPhysics={"MaxSpeed": 2},
        blueprintEconomy={"BuildRate": 5},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    observation = harness.observe()
    execute_intents(
        harness,
        [
            {
                "kind": "build_structure",
                "actorToken": "1:1",
                "buildRole": "mass_extractor",
                "siteKey": "far",
                "position": [410, 2, 20],
                "reason": "frontier_expansion",
            }
        ],
        observation,
    )

    operation = harness.controller.pending["1:1"]
    assert operation.deadlineTick > 900
    assert operation.lastProgressTick == 0
    assert operation.initialDistance >= 399


def test_progressing_long_trip_survives_past_900_ticks_and_refreshes_progress_clock() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
        blueprintPhysics={"MaxSpeed": 2},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    observation = harness.observe()
    execute_intents(
        harness,
        [{"kind": "build_structure", "actorToken": "1:1", "buildRole": "mass_extractor", "siteKey": "far", "position": [410, 2, 20], "reason": "frontier_expansion"}],
        observation,
    )
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Moving": True})

    for tick, x in ((700, 110), (1200, 210), (1800, 310)):
        harness.brain.tick = tick
        engineer.options.position = lua_value(harness.lua, [x, 2, 20])
        current = harness.observe()
        harness.lua.globals().Controller.Reconcile(harness.controller, current)
        assert harness.controller.pending["1:1"] is not None

    assert harness.controller.pending["1:1"].lastProgressTick == 1800


def test_true_no_progress_travel_is_bounded_by_derived_deadline_and_releases_for_retry() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
        blueprintPhysics={"MaxSpeed": 2},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    observation = harness.observe()
    execute_intents(
        harness,
        [{"kind": "build_structure", "actorToken": "1:1", "buildRole": "mass_extractor", "siteKey": "far", "position": [410, 2, 20], "reason": "frontier_expansion"}],
        observation,
    )
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Moving": True})
    deadline = int(harness.controller.pending["1:1"].deadlineTick)
    harness.brain.tick = 901
    current = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, current)

    assert harness.controller.pending["1:1"] is not None

    harness.brain.tick = deadline + 1
    current = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, current)

    assert harness.controller.pending["1:1"] is None
    assert harness.controller.reservations["far"] is None
    assert any("reason=timeout" in line for line in harness.logs)


def test_incomplete_foundation_retains_job_and_fraction_progress_refreshes_clock() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        canBuild={"ueb1103": True},
    )
    site = harness.controller.markers.mass[1]
    harness.brain.units = harness.lua.table_from([engineer])
    execute_intents(
        harness,
        [{"kind": "build_structure", "actorToken": "1:1", "buildRole": "mass_extractor", "siteKey": site.key, "position": plain(site.position), "reason": "frontier_expansion"}],
        harness.observe(),
    )
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Building": True})
    foundation = harness.unit(
        entityId=9,
        blueprintId="ueb1103",
        position=plain(site.position),
        fraction=0.2,
    )
    harness.brain.units = harness.lua.table_from([engineer, foundation])
    harness.brain.tick = 500
    current = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, current)
    assert harness.controller.pending["1:1"] is not None
    assert harness.controller.pending["1:1"].lastProgressTick == 500

    foundation.options.fraction = 0.6
    harness.brain.tick = 1200
    current = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, current)
    assert harness.controller.pending["1:1"] is not None
    assert harness.controller.pending["1:1"].lastProgressTick == 1200

    foundation.options.fraction = 1
    harness.brain.tick = 1300
    current = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, current)
    assert harness.controller.pending["1:1"] is None


@pytest.mark.parametrize("blueprint_id", ["ueb1103", "ueb1202", "ueb1302"])
def test_every_uef_mex_tier_preserves_owned_site_history(blueprint_id: str) -> None:
    harness = make_harness()
    mex = harness.unit(entityId=10, blueprintId=blueprint_id, position=[12, 2, 20])
    harness.brain.units = harness.lua.table_from([mex])

    observation = plain(harness.observe())

    near = next(site for site in observation["sites"]["mass"] if site["name"] == "Near Mass")
    assert near["complete"] is True
    assert near["everOwned"] is True
    assert observation.get("macro", {}).get("ownedMexCount") == 1


def test_incomplete_mex_upgrade_does_not_create_false_lost_or_rebuilt_transition() -> None:
    harness = make_harness()
    t1 = harness.unit(entityId=10, blueprintId="ueb1103", position=[12, 2, 20])
    harness.brain.units = harness.lua.table_from([t1])
    plain(harness.observe())

    upgrading = harness.unit(
        entityId=11,
        blueprintId="ueb1202",
        position=[12, 2, 20],
        fraction=0.4,
    )
    harness.brain.units = harness.lua.table_from([upgrading])
    observation = plain(harness.observe())

    near = next(site for site in observation["sites"]["mass"] if site["name"] == "Near Mass")
    assert near["occupied"] is True
    assert near["lost"] is False
    assert observation["macro"]["lostMexCount"] == 0
    assert not [line for line in harness.logs if "event=mex_lost" in line]


def test_abandoned_incomplete_lost_mex_is_assisted_and_retryable_after_actor_death() -> None:
    harness = make_harness()
    original = harness.unit(entityId=10, blueprintId="ueb1103", position=[12, 2, 20])
    harness.brain.units = harness.lua.table_from([original])
    plain(harness.observe())
    harness.brain.units = harness.lua.table_from([])
    plain(harness.observe())

    foundation = harness.unit(
        entityId=11,
        blueprintId="ueb1103",
        position=[12, 2, 20],
        fraction=0,
        busy=True,
    )
    first_engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([foundation, first_engineer])
    observation = harness.observe()
    first_intents = plain(harness.lua.globals().Policy.Decide(observation))
    first = next(intent for intent in first_intents if intent.get("reason") == "rebuild_mex")

    assert first["kind"] == "assist_structure"
    assert first["targetToken"] == "11:1"
    site_key = first["siteKey"]
    execute_intents(harness, first_intents, observation)
    assert len(harness.calls.guard) == 1
    assert harness.calls.guard[1].target.options.entityId == 11
    assert harness.controller.reservations[site_key].actorToken == "1:1"

    replacement_engineer = harness.unit(
        entityId=2,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([foundation, replacement_engineer])
    next_observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, next_observation)
    retry_intents = plain(harness.lua.globals().Policy.Decide(next_observation))
    retry = next(intent for intent in retry_intents if intent.get("reason") == "rebuild_mex")

    assert retry["kind"] == "assist_structure"
    assert retry["actorToken"] == "2:1"
    execute_intents(harness, retry_intents, next_observation)
    assert len(harness.calls.guard) == 2
    assert harness.controller.reservations[site_key].actorToken == "2:1"

    foundation.options.fraction = 1
    harness.brain.tick = 20
    completed = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, completed)
    assert harness.controller.pending["2:1"] is None
    assert harness.controller.reservations[site_key] is None
    assert plain(completed)["macro"]["rebuiltMexCount"] == 1


def test_destroyed_abandoned_foundation_releases_assist_for_fresh_rebuild() -> None:
    harness = make_harness()
    original = harness.unit(entityId=10, blueprintId="ueb1103", position=[12, 2, 20])
    harness.brain.units = harness.lua.table_from([original])
    plain(harness.observe())
    harness.brain.units = harness.lua.table_from([])
    plain(harness.observe())

    foundation = harness.unit(
        entityId=11,
        blueprintId="ueb1103",
        position=[12, 2, 20],
        fraction=0.3,
    )
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([foundation, engineer])
    observation = harness.observe()
    intents = plain(harness.lua.globals().Policy.Decide(observation))
    assist = next(intent for intent in intents if intent.get("reason") == "rebuild_mex")
    execute_intents(harness, [assist], observation)
    site_key = assist["siteKey"]

    foundation.Dead = True
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.tick = 10
    missing = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, missing)

    assert harness.controller.pending["1:1"] is None
    assert harness.controller.reservations[site_key] is None
    retry = next(
        intent
        for intent in plain(harness.lua.globals().Policy.Decide(missing))
        if intent.get("reason") == "rebuild_mex"
    )
    assert retry["kind"] == "build_structure"


def test_engineer_demand_scales_with_real_backlog_beyond_old_fixed_cap() -> None:
    snapshot = macro_snapshot("engineer", "engineer", "engineer", "engineer", "engineer")
    snapshot["macro"].update(constructionBacklog=12, frontierWork=8, engineerDemand=7)

    production = intents_of(decide(snapshot), "factory_build")

    assert [intent["buildRole"] for intent in production].count("engineer") == 1
    assert next(intent for intent in production if intent["buildRole"] == "engineer")["reason"] == "construction_capacity"


def test_engineer_growth_is_suppressed_during_mass_stall() -> None:
    snapshot = macro_snapshot("engineer", "engineer")
    snapshot["macro"].update(constructionBacklog=20, frontierWork=20, engineerDemand=12)
    snapshot["economy"].update(massTrend=-0.1, massStoredRatio=0.05, unusedMass=0)

    production = intents_of(decide(snapshot), "factory_build")

    assert not [intent for intent in production if intent["buildRole"] == "engineer"]


def test_multiple_idle_factories_admit_only_one_engineer_increment_per_decision() -> None:
    snapshot = macro_snapshot("engineer", "land_factory", "land_factory")
    snapshot["macro"].update(constructionBacklog=9, frontierWork=9, engineerDemand=6)
    for unit in snapshot["units"]:
        if unit["role"] == "land_factory":
            unit["needsRally"] = False
            unit["canBuild"] = {"engineer": True, "tank": True}

    production = intents_of(decide(snapshot), "factory_build")

    assert [intent["buildRole"] for intent in production].count("engineer") == 1


def test_sustained_unused_mass_admits_one_factory_above_old_fixed_ceiling() -> None:
    snapshot = macro_snapshot("land_factory", "engineer", "mass_extractor", "mass_extractor", "mass_extractor", "mass_extractor")
    snapshot["macro"].update(factoryDemand=4, massSurplusTicks=300)
    snapshot["economy"].update(massIncome=20, massUsage=10, unusedMass=10, massTrend=2, massStoredRatio=0.8)
    snapshot["placements"]["land_factory"] = [[50, 2, 20], [55, 2, 20]]

    builds = [
        intent
        for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("buildRole") == "land_factory" and intent["actorToken"] != "1:1"
    ]

    assert len(builds) == 1
    assert builds[0]["reason"] == "production_saturation"


@pytest.mark.parametrize(
    ("surplus_ticks", "mass_trend", "stored_ratio"),
    [(299, 2, 0.8), (300, -0.1, 0.8), (300, 2, 0.05)],
)
def test_factory_scale_requires_sustained_surplus_and_nonstalled_mass(
    surplus_ticks: int,
    mass_trend: float,
    stored_ratio: float,
) -> None:
    snapshot = macro_snapshot("land_factory", "engineer", "mass_extractor", "mass_extractor")
    snapshot["macro"].update(factoryDemand=4, massSurplusTicks=surplus_ticks)
    snapshot["economy"].update(
        massIncome=20,
        massUsage=10,
        unusedMass=10,
        massTrend=mass_trend,
        massStoredRatio=stored_ratio,
    )

    builds = [
        intent for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("reason") == "production_saturation"
    ]

    assert builds == []


def test_mass_surplus_duration_resets_immediately_on_stall() -> None:
    harness = make_harness()
    harness.brain.massIncome = 12
    harness.brain.massUsage = 5
    harness.brain.massTrend = 2
    harness.brain.massStoredRatio = 0.8
    harness.brain.tick = 0
    plain(harness.observe())
    harness.brain.tick = 350
    sustained = plain(harness.observe()).get("macro", {})
    assert sustained.get("massSurplusTicks", 0) >= 300

    harness.brain.massTrend = -1
    harness.brain.massStoredRatio = 0.04
    harness.brain.tick = 360
    stalled = plain(harness.observe()).get("macro", {})
    assert stalled.get("massSurplusTicks") == 0


def screen_snapshot() -> dict[str, Any]:
    snapshot = macro_snapshot("tank", "tank", "tank", "tank", "tank", "tank", "anti_air", "artillery")
    engineer = next(unit for unit in snapshot["units"] if unit["role"] == "engineer")
    snapshot["pending"] = [
        {
            "actorToken": engineer["token"],
            "kind": "build_structure",
            "buildRole": "mass_extractor",
            "siteKey": "frontier",
            "reason": "frontier_expansion",
            "clusterKey": "cluster-a",
        }
    ]
    snapshot["macro"].update(
        activeFrontierJobs=1,
        selectedFrontierCluster="cluster-a",
        selectedFrontierSite="frontier",
        frontierWork=1,
    )
    return snapshot


def test_frontier_screen_includes_available_aa_and_preserves_disjoint_home_reserve() -> None:
    snapshot = screen_snapshot()

    screen = intents_of(decide(snapshot), "frontier_screen")

    assert len(screen) == 1
    tokens = screen[0]["actorTokens"]
    by_token = {unit["token"]: unit for unit in snapshot["units"]}
    assert any(by_token[token]["role"] == "anti_air" for token in tokens)
    combat_tokens = {
        unit["token"]
        for unit in snapshot["units"]
        if unit["role"] in {"tank", "artillery", "anti_air", "lab"}
    }
    assert len(combat_tokens - set(tokens)) >= 4
    assert screen[0]["engineerToken"] == next(
        operation["actorToken"] for operation in snapshot["pending"]
    )


def test_surviving_partial_frontier_screen_is_replenished_with_new_aa() -> None:
    snapshot = screen_snapshot()
    existing = next(unit for unit in snapshot["units"] if unit["role"] == "tank")
    existing["assignedToWave"] = True
    existing["frontierEscort"] = True
    snapshot["macro"].update(frontierScreenCount=1, homeReserveCount=7)

    screen = intents_of(decide(snapshot), "frontier_screen")

    assert len(screen) == 1
    by_token = {unit["token"]: unit for unit in snapshot["units"]}
    assert existing["token"] not in screen[0]["actorTokens"]
    assert any(by_token[token]["role"] == "anti_air" for token in screen[0]["actorTokens"])
    assert len(screen[0]["actorTokens"]) == 3
    assert "displacedToken" not in screen[0]


def full_frontier_screen_snapshot() -> tuple[dict[str, Any], list[str], list[str], str]:
    snapshot = screen_snapshot()
    combat = sorted(
        (
            unit
            for unit in snapshot["units"]
            if unit["role"] in {"tank", "artillery", "anti_air", "lab"}
        ),
        key=lambda unit: unit["token"],
    )
    screen_units = [unit for unit in combat if unit["role"] == "tank"][:4]
    for unit in screen_units:
        unit["assignedToWave"] = True
        unit["frontierEscort"] = True
    home_units = [unit for unit in combat if unit not in screen_units]
    anti_air = next(unit for unit in home_units if unit["role"] == "anti_air")
    snapshot["macro"].update(frontierScreenCount=4, homeReserveCount=4)
    return (
        snapshot,
        [unit["token"] for unit in screen_units],
        [unit["token"] for unit in home_units],
        anti_air["token"],
    )


def reserve_blocked_screen_snapshot(
    screen_size: int,
) -> tuple[dict[str, Any], list[str], list[str], str]:
    snapshot = macro_snapshot(
        *(["tank"] * screen_size),
        "anti_air",
        "tank",
        "artillery",
        "lab",
    )
    engineer = next(unit for unit in snapshot["units"] if unit["role"] == "engineer")
    snapshot["pending"] = [
        {
            "actorToken": engineer["token"],
            "kind": "build_structure",
            "buildRole": "mass_extractor",
            "siteKey": "frontier",
            "reason": "frontier_expansion",
            "clusterKey": "cluster-a",
        }
    ]
    combat = sorted(
        (
            unit
            for unit in snapshot["units"]
            if unit["role"] in {"tank", "artillery", "anti_air", "lab"}
        ),
        key=lambda unit: unit["token"],
    )
    screen_units = [unit for unit in combat if unit["role"] == "tank"][:screen_size]
    for unit in screen_units:
        unit["assignedToWave"] = True
        unit["frontierEscort"] = True
    home_units = [unit for unit in combat if unit not in screen_units]
    anti_air = next(unit for unit in home_units if unit["role"] == "anti_air")
    assert len(home_units) == 4
    snapshot["macro"].update(
        activeFrontierJobs=1,
        selectedFrontierCluster="cluster-a",
        selectedFrontierSite="frontier",
        frontierWork=1,
        frontierScreenCount=screen_size,
        homeReserveCount=4,
    )
    return (
        snapshot,
        [unit["token"] for unit in screen_units],
        [unit["token"] for unit in home_units],
        anti_air["token"],
    )


@pytest.mark.parametrize("screen_size", [1, 2, 3])
@pytest.mark.parametrize("seed", range(12))
def test_reserve_blocked_partial_screen_rotates_aa_deterministically_under_permutations(
    screen_size: int,
    seed: int,
) -> None:
    snapshot, old_screen, old_home, anti_air = reserve_blocked_screen_snapshot(screen_size)
    random.Random(seed).shuffle(snapshot["units"])

    screen = intents_of(decide(snapshot), "frontier_screen")

    assert len(screen) == 1
    assert screen[0]["actorTokens"] == [anti_air]
    assert screen[0]["displacedToken"] == min(old_screen)
    new_screen = (set(old_screen) - {screen[0]["displacedToken"]}) | {anti_air}
    new_home = (set(old_home) - {anti_air}) | {screen[0]["displacedToken"]}
    assert len(new_screen) == screen_size
    assert len(new_home) == 4
    assert new_screen.isdisjoint(new_home)


@pytest.mark.parametrize("seed", range(12))
def test_full_tank_screen_rotates_home_aa_one_for_one_deterministically(seed: int) -> None:
    snapshot, old_screen, old_home, anti_air = full_frontier_screen_snapshot()
    random.Random(seed).shuffle(snapshot["units"])

    screen = intents_of(decide(snapshot), "frontier_screen")

    assert len(screen) == 1
    assert screen[0]["actorTokens"] == [anti_air]
    assert screen[0]["displacedToken"] == min(old_screen)
    new_screen = (set(old_screen) - {screen[0]["displacedToken"]}) | {anti_air}
    new_home = (set(old_home) - {anti_air}) | {screen[0]["displacedToken"]}
    assert len(new_screen) == 4
    assert len(new_home) == 4
    assert new_screen.isdisjoint(new_home)


def test_full_screen_displacement_tie_breaks_by_token_not_input_order() -> None:
    displaced = set()
    for seed in range(20):
        snapshot, old_screen, _, _ = full_frontier_screen_snapshot()
        random.Random(seed).shuffle(snapshot["units"])
        intent = intents_of(decide(snapshot), "frontier_screen")[0]
        displaced.add(intent["displacedToken"])

    assert displaced == {min(old_screen)}


def test_full_screen_with_existing_aa_does_not_rotate_another_aa() -> None:
    snapshot, old_screen, old_home, anti_air = full_frontier_screen_snapshot()
    by_token = {unit["token"]: unit for unit in snapshot["units"]}
    displaced_tank = old_screen[0]
    by_token[displaced_tank]["assignedToWave"] = False
    by_token[displaced_tank]["frontierEscort"] = False
    by_token[anti_air]["assignedToWave"] = True
    by_token[anti_air]["frontierEscort"] = True
    snapshot["macro"].update(frontierScreenCount=4, homeReserveCount=4)

    assert intents_of(decide(snapshot), "frontier_screen") == []


def _call_actor_ids(call: Any) -> list[int]:
    return [call.units[index].options.entityId for index in range(1, len(call.units) + 1)]


def full_frontier_screen_harness() -> tuple[Any, Any, dict[str, Any]]:
    harness = make_harness()
    engineer = harness.unit(entityId=1, blueprintId="uel0105")
    tanks = [harness.unit(entityId=entity_id, blueprintId="uel0201") for entity_id in range(2, 6)]
    home = [
        harness.unit(entityId=6, blueprintId="uel0104"),
        harness.unit(entityId=7, blueprintId="uel0201"),
        harness.unit(entityId=8, blueprintId="uel0103"),
        harness.unit(entityId=9, blueprintId="uel0106"),
    ]
    harness.brain.units = harness.lua.table_from([engineer, *tanks, *home])
    harness.observe()
    install_pending_frontier_operation(harness)
    harness.controller.frontierMission = lua_value(
        harness.lua,
        {
            "engineerToken": "1:1",
            "clusterKey": "cluster-a",
            "escortTokens": ["2:1", "3:1", "4:1", "5:1"],
            "issuedTick": 0,
        },
    )
    for token in ("2:1", "3:1", "4:1", "5:1"):
        harness.controller.frontierAssignments[token] = lua_value(
            harness.lua,
            {"engineerToken": "1:1", "clusterKey": "cluster-a", "issuedTick": 0},
        )
    observation = harness.observe()
    intent = {
        "kind": "frontier_screen",
        "engineerToken": "1:1",
        "actorTokens": ["6:1"],
        "displacedToken": "2:1",
        "clusterKey": "cluster-a",
        "priority": 24,
        "reason": "secure_frontier",
    }
    return harness, observation, intent


def partial_frontier_screen_harness(
    screen_size: int,
    *,
    seed: int = 0,
    contact: bool = False,
) -> tuple[Any, Any, dict[str, Any], list[str], list[str]]:
    harness = make_harness()
    engineer = harness.unit(entityId=1, blueprintId="uel0105")
    escorts = [
        harness.unit(entityId=entity_id, blueprintId="uel0201")
        for entity_id in range(2, screen_size + 2)
    ]
    home = [
        harness.unit(entityId=6, blueprintId="uel0104"),
        harness.unit(entityId=7, blueprintId="uel0201"),
        harness.unit(entityId=8, blueprintId="uel0103"),
        harness.unit(entityId=9, blueprintId="uel0106"),
    ]
    units = [engineer, *escorts, *home]
    random.Random(seed).shuffle(units)
    harness.brain.units = harness.lua.table_from(units)
    if contact:
        enemy = harness.unit(entityId=80, blueprintId="url0201", position=[40, 2, 20])
        harness.brain.enemies = harness.lua.table_from([enemy])
    harness.observe()
    install_pending_frontier_operation(harness)
    escort_tokens = [f"{entity_id}:1" for entity_id in range(2, screen_size + 2)]
    harness.controller.frontierMission = lua_value(
        harness.lua,
        {
            "engineerToken": "1:1",
            "clusterKey": "cluster-a",
            "escortTokens": escort_tokens,
            "issuedTick": 0,
        },
    )
    for token in escort_tokens:
        harness.controller.frontierAssignments[token] = lua_value(
            harness.lua,
            {"engineerToken": "1:1", "clusterKey": "cluster-a", "issuedTick": 0},
        )
    observation = harness.observe()
    intent = {
        "kind": "frontier_screen",
        "engineerToken": "1:1",
        "actorTokens": ["6:1"],
        "displacedToken": "2:1",
        "clusterKey": "cluster-a",
        "priority": 24,
        "reason": "secure_frontier",
    }
    return harness, observation, intent, escort_tokens, ["6:1", "7:1", "8:1", "9:1"]


def _controller_policy_intents(harness: Any, observation: Any) -> list[dict[str, Any]]:
    return plain(harness.lua.globals().Policy.Decide(observation))


def _screen_state(harness: Any) -> tuple[Any, Any]:
    return (
        plain(harness.controller.frontierMission),
        plain(harness.controller.frontierAssignments),
    )


def test_full_screen_aa_rotation_executes_exact_swap_and_actor_partition() -> None:
    harness, observation, intent = full_frontier_screen_harness()

    execute_intents(harness, [intent], observation)

    assert plain(harness.calls.sequence) == ["clear", "guard", "clear"]
    assert _call_actor_ids(harness.calls.clear[1]) == [6]
    assert _call_actor_ids(harness.calls.guard[1]) == [6]
    assert harness.calls.guard[1].target.options.entityId == 1
    assert _call_actor_ids(harness.calls.clear[2]) == [2]
    assert plain(harness.controller.frontierMission.escortTokens) == ["3:1", "4:1", "5:1", "6:1"]
    assert harness.controller.frontierAssignments["2:1"] is None
    assert harness.controller.frontierAssignments["6:1"] is not None
    screen = set(plain(harness.controller.frontierMission.escortTokens))
    home = {"2:1", "7:1", "8:1", "9:1"}
    assert len(screen) == len(home) == 4
    assert screen.isdisjoint(home)
    next_observation = harness.observe()
    next_macro = plain(next_observation.macro)
    assert next_macro["frontierScreenCount"] == 4
    assert next_macro["homeReserveCount"] == 4
    next_intents = plain(harness.lua.globals().Policy.Decide(next_observation))
    assert intents_of(next_intents, "frontier_screen") == []


@pytest.mark.parametrize("screen_size", [1, 2, 3])
@pytest.mark.parametrize("seed", range(8))
def test_partial_rotation_runs_observe_policy_execute_end_to_end_for_all_input_orders(
    screen_size: int,
    seed: int,
) -> None:
    harness, observation, _, old_screen, old_home = partial_frontier_screen_harness(
        screen_size,
        seed=seed,
    )
    intents = _controller_policy_intents(harness, observation)

    execute_intents(harness, intents, observation)

    assert plain(harness.calls.sequence) == ["clear", "guard", "clear"]
    assert _call_actor_ids(harness.calls.clear[1]) == [6]
    assert _call_actor_ids(harness.calls.guard[1]) == [6]
    assert harness.calls.guard[1].target.options.entityId == 1
    assert _call_actor_ids(harness.calls.clear[2]) == [2]
    expected_screen = sorted((set(old_screen) - {"2:1"}) | {"6:1"})
    expected_home = (set(old_home) - {"6:1"}) | {"2:1"}
    assert plain(harness.controller.frontierMission.escortTokens) == expected_screen
    assert harness.controller.frontierAssignments["2:1"] is None
    assert harness.controller.frontierAssignments["6:1"] is not None
    assert len(expected_screen) == screen_size
    assert len(expected_home) == 4
    assert set(expected_screen).isdisjoint(expected_home)
    next_observation = harness.observe()
    next_macro = plain(next_observation.macro)
    assert next_macro["frontierScreenCount"] == screen_size
    assert next_macro["homeReserveCount"] == 4
    assert intents_of(_controller_policy_intents(harness, next_observation), "frontier_screen") == []


@pytest.mark.parametrize("seed", range(12))
def test_non_immediate_contact_defends_with_three_disjoint_home_units_and_rotates_aa(
    seed: int,
) -> None:
    harness, observation, _, old_screen, old_home = partial_frontier_screen_harness(
        4,
        seed=seed,
        contact=True,
    )
    assert plain(observation.enemyContact)["immediate"] is False
    intents = _controller_policy_intents(harness, observation)
    defend = intents_of(intents, "defend_wave")
    screen = intents_of(intents, "frontier_screen")

    assert len(defend) == len(screen) == 1
    assert defend[0]["actorTokens"] == ["7:1", "8:1", "9:1"]
    assert screen[0]["actorTokens"] == ["6:1"]
    assert screen[0]["displacedToken"] == "2:1"
    assert set(defend[0]["actorTokens"]).isdisjoint(screen[0]["actorTokens"])
    assert set(defend[0]["actorTokens"]).isdisjoint(old_screen)

    execute_intents(harness, intents, observation)

    assert plain(harness.calls.sequence) == ["clear", "aggressive", "clear", "guard", "clear"]
    assert _call_actor_ids(harness.calls.clear[1]) == [7, 8, 9]
    assert _call_actor_ids(harness.calls.aggressive[1]) == [7, 8, 9]
    assert _call_actor_ids(harness.calls.clear[2]) == [6]
    assert _call_actor_ids(harness.calls.guard[1]) == [6]
    assert _call_actor_ids(harness.calls.clear[3]) == [2]
    screen_tokens = set(plain(harness.controller.frontierMission.escortTokens))
    home_tokens = (set(old_home) - {"6:1"}) | {"2:1"}
    assert len(screen_tokens) == len(home_tokens) == 4
    assert screen_tokens.isdisjoint(home_tokens)
    assert harness.controller.frontierAssignments["2:1"] is None
    assert harness.controller.frontierAssignments["6:1"] is not None


@pytest.mark.parametrize(
    ("failure_field", "failure_call", "expected_failure_sequence"),
    [
        ("failClearAt", 1, ["clear"]),
        ("failGuardAt", 1, ["clear", "guard", "clear"]),
        ("failClearAt", 2, ["clear", "guard", "clear", "clear"]),
    ],
)
def test_full_screen_rotation_order_failure_restores_exact_state_and_retries_immediately(
    failure_field: str,
    failure_call: int,
    expected_failure_sequence: list[str],
) -> None:
    harness, observation, intent = full_frontier_screen_harness()
    before = _screen_state(harness)
    harness.calls[failure_field] = failure_call

    execute_intents(harness, [intent], observation)

    assert plain(harness.calls.sequence) == expected_failure_sequence
    assert _screen_state(harness) == before
    assert harness.controller.frontierAssignments["6:1"] is None

    harness.calls[failure_field] = None
    sequence_count = len(harness.calls.sequence)
    execute_intents(harness, [intent], harness.observe())

    assert plain(harness.calls.sequence)[sequence_count:] == ["clear", "guard", "clear"]
    assert plain(harness.controller.frontierMission.escortTokens) == ["3:1", "4:1", "5:1", "6:1"]


@pytest.mark.parametrize("screen_size", [1, 2, 3])
@pytest.mark.parametrize(
    ("failure_field", "failure_call", "expected_failure_sequence"),
    [
        ("failClearAt", 1, ["clear"]),
        ("failGuardAt", 1, ["clear", "guard", "clear"]),
        ("failClearAt", 2, ["clear", "guard", "clear", "clear"]),
    ],
)
def test_partial_rotation_command_failure_restores_exact_state_and_retries_immediately(
    screen_size: int,
    failure_field: str,
    failure_call: int,
    expected_failure_sequence: list[str],
) -> None:
    harness, observation, intent, old_screen, _ = partial_frontier_screen_harness(screen_size)
    before = _screen_state(harness)
    harness.calls[failure_field] = failure_call

    execute_intents(harness, [intent], observation)

    assert plain(harness.calls.sequence) == expected_failure_sequence
    assert _screen_state(harness) == before
    assert harness.controller.frontierAssignments["6:1"] is None

    harness.calls[failure_field] = None
    sequence_count = len(harness.calls.sequence)
    execute_intents(harness, [intent], harness.observe())

    assert plain(harness.calls.sequence)[sequence_count:] == ["clear", "guard", "clear"]
    expected = sorted((set(old_screen) - {"2:1"}) | {"6:1"})
    assert plain(harness.controller.frontierMission.escortTokens) == expected


@pytest.mark.parametrize("actor", ["replacement", "displaced"])
@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_full_screen_rotation_fails_closed_for_invalid_exact_actor(
    actor: str,
    mutation: str,
) -> None:
    harness, observation, intent = full_frontier_screen_harness()
    entity_id = 6 if actor == "replacement" else 2
    token = f"{entity_id}:1"
    unit = harness.controller.unitRefs[token]
    if mutation == "dead":
        unit.Dead = True
    elif mutation == "captured":
        unit.options.army = 2
    else:
        replacement = harness.unit(
            entityId=entity_id,
            blueprintId="uel0104" if actor == "replacement" else "uel0201",
        )
        units = [
            replacement if item.options.entityId == entity_id else item
            for item in harness.brain.units.values()
        ]
        harness.brain.units = harness.lua.table_from(units)
        harness.observe()
    before = _screen_state(harness)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.sequence) == 0
    assert _screen_state(harness) == before


@pytest.mark.parametrize("screen_size", [1, 2, 3])
@pytest.mark.parametrize("actor", ["replacement", "displaced"])
@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_partial_rotation_fails_closed_for_dead_captured_or_recycled_exact_actor(
    screen_size: int,
    actor: str,
    mutation: str,
) -> None:
    harness, observation, _, _, _ = partial_frontier_screen_harness(screen_size)
    screen = intents_of(_controller_policy_intents(harness, observation), "frontier_screen")
    assert len(screen) == 1
    intent = screen[0]
    entity_id = 6 if actor == "replacement" else 2
    token = f"{entity_id}:1"
    unit = harness.controller.unitRefs[token]
    if mutation == "dead":
        unit.Dead = True
    elif mutation == "captured":
        unit.options.army = 2
    else:
        replacement = harness.unit(
            entityId=entity_id,
            blueprintId="uel0104" if actor == "replacement" else "uel0201",
        )
        units = [
            replacement if item.options.entityId == entity_id else item
            for item in harness.brain.units.values()
        ]
        harness.brain.units = harness.lua.table_from(units)
        harness.observe()
    before = _screen_state(harness)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.sequence) == 0
    assert _screen_state(harness) == before


@pytest.mark.parametrize("screen_size", [1, 2, 3])
@pytest.mark.parametrize("corruption", ["nonmember", "duplicate", "missing_assignment"])
def test_partial_rotation_rejects_corrupted_mission_membership_without_orders(
    screen_size: int,
    corruption: str,
) -> None:
    harness, observation, _, old_screen, _ = partial_frontier_screen_harness(screen_size)
    screen = intents_of(_controller_policy_intents(harness, observation), "frontier_screen")
    assert len(screen) == 1
    intent = screen[0]
    if corruption == "nonmember":
        intent["displacedToken"] = "7:1"
    elif corruption == "duplicate":
        duplicate = [old_screen[0], *old_screen]
        harness.controller.frontierMission.escortTokens = lua_value(harness.lua, duplicate)
    else:
        harness.controller.frontierAssignments[old_screen[0]] = None
    before = _screen_state(harness)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.sequence) == 0
    assert _screen_state(harness) == before


def test_full_screen_rotation_rejects_nonmember_displacement_without_orders() -> None:
    harness, observation, intent = full_frontier_screen_harness()
    intent["displacedToken"] = "7:1"
    before = _screen_state(harness)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.sequence) == 0
    assert _screen_state(harness) == before


def test_full_screen_rotation_fails_closed_if_home_reserve_is_no_longer_four_live_units() -> None:
    harness, observation, intent = full_frontier_screen_harness()
    harness.controller.unitRefs["7:1"].Dead = True
    before = _screen_state(harness)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.sequence) == 0
    assert _screen_state(harness) == before


def test_frontier_escorts_are_never_consumed_by_home_defense_or_regroup() -> None:
    snapshot = screen_snapshot()
    assigned = [unit for unit in snapshot["units"] if unit["role"] in {"tank", "anti_air"}][:2]
    for unit in assigned:
        unit["assignedToWave"] = True
        unit["frontierEscort"] = True
    snapshot["enemyContact"] = {"position": [12, 2, 20], "immediate": False}

    result = decide(snapshot)
    tactical_tokens = set(
        itertools.chain.from_iterable(
            intent.get("actorTokens", [])
            for intent in result
            if intent["kind"] in {"defend_wave", "regroup_wave"}
        )
    )

    assert tactical_tokens.isdisjoint({unit["token"] for unit in assigned})


def install_pending_frontier_operation(
    harness: Any,
    engineer_token: str = "1:1",
    cluster_key: str = "cluster-a",
) -> None:
    harness.controller.pending[engineer_token] = lua_value(
        harness.lua,
        {
            "actorToken": engineer_token,
            "kind": "build_structure",
            "buildRole": "mass_extractor",
            "siteKey": "frontier",
            "position": [40, 2, 20],
            "issuedTick": 0,
            "deadlineTick": 5000,
            "lastProgressTick": 0,
            "lastDistance": 30,
            "lastFraction": 0,
            "phase": "travelling",
            "accepted": True,
            "reason": "frontier_expansion",
            "clusterKey": cluster_key,
        },
    )


def test_frontier_screen_executes_exact_clear_then_guard_and_persists_ownership() -> None:
    harness = make_harness()
    engineer = harness.unit(entityId=1, blueprintId="uel0105")
    tank = harness.unit(entityId=2, blueprintId="uel0201")
    aa = harness.unit(entityId=3, blueprintId="uel0104")
    harness.brain.units = harness.lua.table_from([engineer, tank, aa])
    observation = harness.observe()
    install_pending_frontier_operation(harness)

    execute_intents(
        harness,
        [{"kind": "frontier_screen", "engineerToken": "1:1", "actorTokens": ["3:1", "2:1"], "clusterKey": "cluster-a", "priority": 24, "reason": "secure_frontier"}],
        observation,
    )

    assert plain(harness.calls.sequence) == ["clear", "guard"]
    assert plain(harness.calls.guard[1].target.options)["entityId"] == 1
    mission = harness.controller.frontierMission
    assert mission.engineerToken == "1:1"
    assert plain(mission.escortTokens) == ["2:1", "3:1"]


def test_frontier_screen_reinforcement_extends_existing_mission_atomically() -> None:
    harness = make_harness()
    engineer = harness.unit(entityId=1, blueprintId="uel0105")
    tank = harness.unit(entityId=2, blueprintId="uel0201")
    aa = harness.unit(entityId=3, blueprintId="uel0104")
    harness.brain.units = harness.lua.table_from([engineer, tank, aa])
    observation = harness.observe()
    install_pending_frontier_operation(harness)
    execute_intents(
        harness,
        [{"kind": "frontier_screen", "engineerToken": "1:1", "actorTokens": ["2:1"], "clusterKey": "cluster-a", "priority": 24, "reason": "secure_frontier"}],
        observation,
    )

    execute_intents(
        harness,
        [{"kind": "frontier_screen", "engineerToken": "1:1", "actorTokens": ["3:1"], "clusterKey": "cluster-a", "priority": 24, "reason": "secure_frontier"}],
        harness.observe(),
    )

    assert plain(harness.calls.sequence) == ["clear", "guard", "clear", "guard"]
    assert plain(harness.controller.frontierMission.escortTokens) == ["2:1", "3:1"]
    assert harness.controller.frontierAssignments["2:1"] is not None
    assert harness.controller.frontierAssignments["3:1"] is not None


@pytest.mark.parametrize("failure", ["failClear", "failGuard"])
def test_frontier_screen_order_failure_rolls_back_without_leaking_ownership(failure: str) -> None:
    harness = make_harness()
    engineer = harness.unit(entityId=1, blueprintId="uel0105")
    tank = harness.unit(entityId=2, blueprintId="uel0201")
    harness.brain.units = harness.lua.table_from([engineer, tank])
    observation = harness.observe()
    install_pending_frontier_operation(harness)
    harness.calls[failure] = True
    intent = {"kind": "frontier_screen", "engineerToken": "1:1", "actorTokens": ["2:1"], "clusterKey": "cluster-a", "priority": 24, "reason": "secure_frontier"}

    execute_intents(harness, [intent], observation)

    assert harness.controller.frontierMission is None
    assert harness.controller.waveAssignments["2:1"] is None
    harness.calls[failure] = False
    execute_intents(harness, [intent], harness.observe())
    assert harness.controller.frontierMission is not None


def test_frontier_screen_rejects_dead_captured_or_recycled_engineer_atomically() -> None:
    for mutation in ("dead", "captured", "recycled"):
        harness = make_harness()
        engineer = harness.unit(entityId=1, blueprintId="uel0105")
        tank = harness.unit(entityId=2, blueprintId="uel0201")
        harness.brain.units = harness.lua.table_from([engineer, tank])
        observation = harness.observe()
        install_pending_frontier_operation(harness)
        if mutation == "dead":
            engineer.Dead = True
        elif mutation == "captured":
            engineer.options.army = 2
        else:
            replacement = harness.unit(entityId=1, blueprintId="uel0105")
            harness.brain.units = harness.lua.table_from([replacement, tank])
            harness.observe()

        execute_intents(
            harness,
            [{"kind": "frontier_screen", "engineerToken": "1:1", "actorTokens": ["2:1"], "clusterKey": "cluster-a", "priority": 24, "reason": "secure_frontier"}],
            observation,
        )

        assert len(harness.calls.guard) == 0
        assert harness.controller.frontierMission is None


@pytest.mark.parametrize(
    "state",
    [
        {"initialWaveSent": False},
        {"initialWaveSent": True, "commanderPushActive": False},
        {"initialWaveSent": True, "commanderPushActive": True},
        {"initialWaveSent": False, "commanderMobilizing": True},
        {"initialWaveSent": True, "commanderRetreating": True},
        {},
    ],
)
def test_secured_frontier_policy_never_emits_cross_map_offense_on_any_state(
    state: dict[str, Any],
) -> None:
    snapshot = macro_snapshot("tank", "tank", "tank", "tank", "artillery")
    snapshot["state"] = state
    snapshot["tick"] = 999_999
    snapshot["targetPath"] = True
    snapshot["targetPosition"] = [999, 2, 999]

    kinds = {intent["kind"] for intent in decide(snapshot)}

    assert kinds.isdisjoint(FORBIDDEN_OFFENSE)


def test_controller_step_never_orders_any_actor_to_diagnostic_enemy_spawn() -> None:
    harness = make_harness()
    staging = plain(harness.controller.stagingPosition)
    acu = harness.unit(entityId=1, blueprintId="uel0001", position=staging)
    factory = harness.unit(entityId=100, blueprintId="ueb0101", position=[12, 2, 20])
    units = [acu, factory]
    for offset in range(24):
        units.append(
            harness.unit(
                entityId=offset + 2,
                blueprintId="uel0103" if offset < 4 else "uel0201",
                position=staging,
            )
        )
    harness.brain.units = harness.lua.table_from(units)
    harness.lua.globals().Controller.Step(harness.controller)

    target = plain(harness.controller.targetPosition)
    old_staging = plain(harness.controller.stagingPosition)
    assert not [call for call in plain(harness.calls.aggressive) if call["position"] == target]
    assert not [call for call in plain(harness.calls.move) if call["position"] == target]
    assert not [
        call for call in plain(harness.calls.rally)
        if call["position"] == target or call["position"] == old_staging
    ]


def test_factory_rally_and_regroup_use_controlled_macro_anchor_not_enemy_staging() -> None:
    snapshot = macro_snapshot("tank")
    controlled = [28, 2, 20]
    snapshot["macro"]["rallyPosition"] = controlled
    snapshot["stagingPosition"] = [80, 2, 80]
    snapshot["targetPosition"] = [200, 2, 200]
    for unit in snapshot["units"]:
        if unit["role"] == "land_factory":
            unit["needsRally"] = True
        if unit["role"] == "tank":
            unit["nearStaging"] = False

    result = decide(snapshot)
    positions = [
        intent["position"]
        for intent in result
        if intent["kind"] in {"rally", "regroup_wave"}
    ]

    assert positions
    assert all(position == controlled for position in positions)


def make_reclaim_prop(harness: Any, **options: Any) -> Any:
    return harness.lua.globals().MakeProp(lua_value(harness.lua, options))


def test_reclaim_query_is_cadenced_bounded_and_limited_to_controlled_engineer_vision() -> None:
    harness = make_harness()
    owned = harness.unit(entityId=10, blueprintId="ueb1103", position=[40, 2, 40])
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[12, 2, 20],
        blueprintIntel={"VisionRadius": 8},
    )
    inside = make_reclaim_prop(harness, entityId=101, position=[15, 2, 20], mass=40)
    outside = make_reclaim_prop(harness, entityId=102, position=[300, 2, 300], mass=999)
    corner = make_reclaim_prop(harness, entityId=103, position=[20, 2, 28], mass=800)
    harness.brain.units = harness.lua.table_from([owned, engineer])
    harness.brain.reclaimables = harness.lua.table_from([outside, corner, inside])

    first = plain(harness.observe())
    second = plain(harness.observe())

    assert 1 <= len(harness.calls.reclaimQuery) <= 4
    assert len(harness.calls.reclaimQuery) == len(plain(harness.calls.reclaimQuery))
    assert [candidate["key"] for candidate in first.get("reclaim", [])] == ["prop:101"]
    assert second.get("reclaim", []) == first.get("reclaim", [])
    assert all(rect[2] - rect[0] <= 16 and rect[3] - rect[1] <= 16 for rect in plain(harness.calls.reclaimQuery))


def test_reclaim_candidates_ignore_units_stale_malformed_noise_and_sort_deterministically() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[10, 2, 20],
        blueprintIntel={"VisionRadius": 10},
    )
    props = [
        make_reclaim_prop(harness, entityId=4, position=[12, 2, 20], mass=50),
        make_reclaim_prop(harness, entityId=2, position=[14, 2, 20], mass=50),
        make_reclaim_prop(harness, entityId=3, position=[11, 2, 20], mass=0.1),
        make_reclaim_prop(harness, entityId=5, position=None, mass=500),
        make_reclaim_prop(harness, entityId=6, position=[13, 2, 20], mass=500, destroyed=True),
        make_reclaim_prop(harness, entityId=7, position=[13, 2, 20], mass=900, isUnit=True),
    ]
    random.Random(7).shuffle(props)
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.reclaimables = harness.lua.table_from(props)

    candidates = plain(harness.observe()).get("reclaim", [])

    assert [candidate["key"] for candidate in candidates] == ["prop:2", "prop:4"]


def test_reclaim_is_lowest_priority_and_one_prop_has_one_engineer_owner() -> None:
    snapshot = macro_snapshot("engineer")
    engineers = [unit for unit in snapshot["units"] if unit["role"] == "engineer"]
    for index, engineer in enumerate(engineers):
        engineer.update(position=[10 + index, 2, 20], visionRadius=10)
    snapshot["reclaim"] = [
        {"key": "prop:2", "position": [14, 2, 20], "mass": 50, "reserved": False, "observerToken": engineers[0]["token"], "observedTick": 0, "visionRadius": 10},
        {"key": "prop:4", "position": [12, 2, 20], "mass": 40, "reserved": False, "observerToken": engineers[0]["token"], "observedTick": 0, "visionRadius": 10},
    ]

    reclaim = intents_of(decide(snapshot), "reclaim")
    assert len(reclaim) == 1
    assert reclaim[0]["targetKey"] == "prop:2"

    blocked = copy.deepcopy(snapshot)
    blocked["sites"]["mass"].append(mass_site("lost", 30, 20, lost=True))
    blocked["macro"].update(lostMexCount=1, constructionBacklog=1)
    assert intents_of(decide(blocked), "reclaim") == []


def test_reclaim_waits_when_any_power_hydro_or_factory_construction_is_planned() -> None:
    snapshot = macro_snapshot("engineer")
    snapshot["economy"].update(energyTrend=-2, energyStoredRatio=0.1)
    snapshot["reclaim"] = [
        {"key": "prop:2", "position": [14, 2, 20], "mass": 50, "reserved": False},
    ]

    result = decide(snapshot)

    assert any(
        intent.get("buildRole") == "power_generator"
        for intent in intents_of(result, "build_structure")
    )
    assert intents_of(result, "reclaim") == []


def test_reclaim_filter_never_inspects_returned_units_beyond_is_prop() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[10, 2, 20],
        blueprintIntel={"VisionRadius": 10},
    )
    returned_unit = make_reclaim_prop(
        harness,
        entityId=7,
        position=[12, 2, 20],
        mass=900,
        isUnit=True,
    )
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.reclaimables = harness.lua.table_from([returned_unit])

    candidates = plain(harness.observe()).get("reclaim", [])

    assert not candidates
    assert harness.calls.unitReclaimInspections == 0


def test_reclaim_target_itself_must_remain_inside_controlled_territory() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[54, 2, 20],
        blueprintIntel={"VisionRadius": 10},
    )
    outside_control = make_reclaim_prop(
        harness,
        entityId=101,
        position=[62, 2, 20],
        mass=50,
    )
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.reclaimables = harness.lua.table_from([outside_control])

    assert not plain(harness.observe()).get("reclaim", [])


def test_cached_reclaim_target_is_rejected_if_territory_is_lost_before_order() -> None:
    harness = make_harness()
    install_markers(harness, [marker("remote", 100, 20)])
    mex = harness.unit(entityId=10, blueprintId="ueb1103", position=[100, 2, 20])
    engineer = harness.unit(entityId=1, blueprintId="uel0105", position=[102, 2, 20])
    prop = make_reclaim_prop(harness, entityId=101, position=[104, 2, 20], mass=50)
    harness.brain.units = harness.lua.table_from([mex, engineer])
    harness.brain.reclaimables = harness.lua.table_from([prop])
    first = plain(harness.observe())
    assert first["reclaim"][0]["key"] == "prop:101"

    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.tick = 10
    uncontrolled = harness.observe()
    execute_intents(
        harness,
        [{"kind": "reclaim", "actorToken": "1:1", "targetKey": "prop:101", "priority": 50, "reason": "controlled_reclaim"}],
        uncontrolled,
    )

    assert len(harness.calls.reclaim) == 0
    assert harness.controller.pending["1:1"] is None


def test_controller_defense_cannot_consume_persistently_owned_frontier_escort() -> None:
    harness = make_harness()
    engineer = harness.unit(entityId=1, blueprintId="uel0105")
    escort = harness.unit(entityId=2, blueprintId="uel0201")
    reserve = harness.unit(entityId=3, blueprintId="uel0201")
    harness.brain.units = harness.lua.table_from([engineer, escort, reserve])
    observation = harness.observe()
    install_pending_frontier_operation(harness)
    execute_intents(
        harness,
        [{"kind": "frontier_screen", "engineerToken": "1:1", "actorTokens": ["2:1"], "clusterKey": "cluster-a", "priority": 24, "reason": "secure_frontier"}],
        observation,
    )

    execute_intents(
        harness,
        [{"kind": "defend_wave", "actorTokens": ["2:1"], "position": [12, 2, 20], "priority": 2, "reason": "base_contact"}],
        harness.observe(),
    )

    assert len(harness.calls.aggressive) == 0
    assert harness.controller.frontierAssignments["2:1"] is not None

    execute_intents(
        harness,
        [{"kind": "attack_wave", "actorTokens": ["2:1", "3:1"], "position": [12, 2, 20], "priority": 40, "reason": "injected_legacy_order"}],
        harness.observe(),
    )

    assert len(harness.calls.aggressive) == 1
    assert [unit.options.entityId for unit in harness.calls.aggressive[1].units.values()] == [3]
    assert harness.controller.waveAssignments["2:1"] is None
    assert harness.controller.waveAssignments["3:1"] is not None


def test_existing_factory_rallies_again_when_controlled_frontier_anchor_advances() -> None:
    harness = make_harness()
    install_markers(
        harness,
        [marker("anchor", 40, 20), marker("next-frontier", 70, 20)],
    )
    factory = harness.unit(entityId=1, blueprintId="ueb0101")
    harness.brain.units = harness.lua.table_from([factory])
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.rally) == 1

    anchor_mex = harness.unit(entityId=10, blueprintId="ueb1103", position=[40, 2, 20])
    harness.brain.units = harness.lua.table_from([factory, anchor_mex])
    harness.brain.tick = 10
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.rally) == 2
    assert plain(harness.calls.rally[2].position)[0] == 40


def test_reclaim_executes_exact_prop_target_and_reconciles_destroyed_completion() -> None:
    harness = make_harness()
    engineer = harness.unit(entityId=1, blueprintId="uel0105", position=[10, 2, 20])
    prop = make_reclaim_prop(harness, entityId=101, position=[12, 2, 20], mass=40)
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.reclaimables = harness.lua.table_from([prop])
    observation = harness.observe()

    execute_intents(
        harness,
        [{"kind": "reclaim", "actorToken": "1:1", "targetKey": "prop:101", "priority": 50, "reason": "controlled_reclaim"}],
        observation,
    )

    assert len(harness.calls.reclaim) == 1
    assert harness.calls.reclaim[1].target.options.entityId == prop.options.entityId
    assert harness.controller.reclaimReservations["prop:101"] == "1:1"
    prop.Dead = True
    harness.brain.tick = 10
    current = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, current)
    assert harness.controller.pending["1:1"] is None
    assert harness.controller.reclaimReservations["prop:101"] is None


@pytest.mark.parametrize("failure", ["stale", "command"])
def test_stale_or_failed_reclaim_is_retryable_without_reservation_leak(failure: str) -> None:
    harness = make_harness()
    engineer = harness.unit(entityId=1, blueprintId="uel0105", position=[10, 2, 20])
    prop = make_reclaim_prop(harness, entityId=101, position=[12, 2, 20], mass=40)
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.reclaimables = harness.lua.table_from([prop])
    observation = harness.observe()
    if failure == "stale":
        prop.Dead = True
    else:
        harness.calls.failReclaim = True

    execute_intents(
        harness,
        [{"kind": "reclaim", "actorToken": "1:1", "targetKey": "prop:101", "priority": 50, "reason": "controlled_reclaim"}],
        observation,
    )

    assert harness.controller.pending["1:1"] is None
    assert harness.controller.reclaimReservations["prop:101"] is None


def test_snapshot_contains_low_volume_economic_macro_and_mission_fields() -> None:
    harness = make_harness()
    harness.brain.massIncome = 12
    harness.brain.massUsage = 7
    harness.brain.massRequested = 7
    harness.brain.massTrend = 5
    harness.brain.massStoredRatio = 0.75
    units = [
        harness.unit(entityId=1, blueprintId="uel0001"),
        harness.unit(entityId=2, blueprintId="uel0105"),
        harness.unit(entityId=3, blueprintId="ueb0101"),
        harness.unit(entityId=4, blueprintId="ueb1101"),
        harness.unit(entityId=5, blueprintId="ueb1102"),
        harness.unit(entityId=6, blueprintId="ueb1103", position=[12, 2, 20]),
        harness.unit(entityId=7, blueprintId="uel0201"),
        harness.unit(entityId=8, blueprintId="uel0104"),
    ]
    harness.brain.units = harness.lua.table_from(units)
    harness.lua.globals().Controller.Step(harness.controller)
    snapshot = next(line for line in harness.logs if "event=snapshot" in line)

    required = {
        "completed_mex=1",
        "completed_factories=1",
        "completed_engineers=1",
        "completed_pgen=1",
        "completed_hydro=1",
        "completed_combat=2",
        "completed_aa=1",
        "mass_income_per_tick=12",
        "mass_usage_per_tick=7",
        "mass_requested_per_tick=7",
        "mass_trend_per_tick=5",
        "mass_stored_ratio=0.75",
        "unused_mass_per_tick=5",
        "rebuild_jobs=0",
        "frontier_jobs=0",
        "reclaim_jobs=0",
        "owned_mex=1",
        "lost_mex=0",
        "rebuilt_mex=0",
        "frontier_cluster=",
        "frontier_site=",
        "frontier_progress=",
        "frontier_screen=0",
        "home_reserve=2",
        "engineer_demand=",
        "factory_demand=",
        "reclaim_target=",
        "reclaim_value=",
        "first_intent_reason=",
    }
    assert all(field in snapshot for field in required)


def test_empty_macro_telemetry_uses_safe_scalar_sentinels_and_stays_rate_limited() -> None:
    harness = make_harness()
    harness.controller.markers.mass = harness.lua.table_from([])
    harness.brain.units = harness.lua.table_from([])
    for tick in (0, 10, 299, 300, 301):
        harness.brain.tick = tick
        harness.lua.globals().Controller.Step(harness.controller)
    snapshots = [line for line in harness.logs if "event=snapshot" in line]

    assert len(snapshots) == 2
    assert "frontier_cluster=none" in snapshots[0]
    assert "frontier_site=none" in snapshots[0]
    assert "frontier_progress=-1" in snapshots[0]
    assert "reclaim_target=none" in snapshots[0]
    assert "reclaim_value=-1" in snapshots[0]
    assert "first_intent_reason=none" in snapshots[0]
    assert "\n" not in snapshots[0]


def test_multiple_reclaim_jobs_choose_a_deterministic_telemetry_target() -> None:
    harness = make_harness()
    harness.controller.pending = lua_value(
        harness.lua,
        {
            "x:1": {"kind": "reclaim", "targetKey": "prop:x", "targetValue": 10},
            "z:1": {"kind": "reclaim", "targetKey": "prop:z", "targetValue": 50},
        },
    )

    macro = plain(harness.observe())["macro"]

    assert macro["reclaimTarget"] == "prop:x"
    assert macro["reclaimValue"] == 10
