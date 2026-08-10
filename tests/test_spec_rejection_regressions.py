from __future__ import annotations

import math
import random
from typing import Any

import pytest

from test_controller import (
    activate_commander_push,
    commander_force,
    commander_mobilize_intent,
    commander_push_intent,
    commander_reinforcement_intent,
    execute_intents,
    make_harness,
)
from test_policy import decide, intents_of, lua_value, plain
from test_secured_frontier_doctrine import (
    install_markers,
    macro_snapshot,
    make_reclaim_prop,
    marker,
    mass_site,
)


def telemetry_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in line.split("|"):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key] = value
    return fields


@pytest.mark.parametrize("permutation_seed", range(8))
def test_ian_cross_army_1_frontier_escapes_four_start_mex_without_euclidean_cutoff(
    permutation_seed: int,
) -> None:
    harness = make_harness()
    harness.controller.basePosition = lua_value(harness.lua, [99.5, 2, 86.5])
    markers = [
        marker("MASS_200", 88.5, 75.5),
        marker("MASS_201", 108.5, 69.5),
        marker("MASS_202", 110.5, 101.5),
        marker("MASS_203", 97.5, 100.5),
        marker("MASS_204", 179.5, 32.5),
        marker("MASS_206", 32.5, 141.5),
    ]
    random.Random(permutation_seed).shuffle(markers)
    install_markers(harness, markers)
    owned_positions = [
        (97.5, 100.5),
        (88.5, 75.5),
        (110.5, 101.5),
        (108.5, 69.5),
    ]
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(
                entityId=100 + index,
                blueprintId="ueb1103",
                position=[x, 2, z],
            )
            for index, (x, z) in enumerate(owned_positions)
        ]
    )

    observation = plain(harness.observe())
    macro = observation["macro"]

    nearest_206 = min(math.hypot(32.5 - x, 141.5 - z) for x, z in owned_positions)
    nearest_204 = min(math.hypot(179.5 - x, 32.5 - z) for x, z in owned_positions)
    assert math.isclose(nearest_206, 76.8505042273634)
    assert math.isclose(nearest_204, 80.06247560499239)
    assert macro["selectedFrontierCluster"] == "MASS_206"
    assert macro["selectedFrontierSite"] == "MASS_206"


def test_zero_engineer_mass_stall_builds_only_recovery_engineer() -> None:
    snapshot = macro_snapshot()
    snapshot["units"] = [unit for unit in snapshot["units"] if unit["role"] != "engineer"]
    snapshot["sites"]["mass"].append(mass_site("lost-remote", 80, 20, lost=True))
    snapshot["macro"].update(lostMexCount=1, constructionBacklog=1, engineerDemand=3)
    snapshot["economy"].update(
        massIncome=0,
        massUsage=0,
        massRequested=1,
        massTrend=-1,
        massStoredRatio=0,
    )
    for factory in (unit for unit in snapshot["units"] if unit["role"] == "land_factory"):
        factory.update(
            idle=True,
            needsRally=False,
            canBuild={
                "engineer": True,
                "scout": True,
                "tank": True,
                "artillery": True,
                "anti_air": True,
            },
        )

    production = intents_of(decide(snapshot), "factory_build")

    assert [intent["buildRole"] for intent in production] == ["engineer"]
    assert production[0]["reason"] == "recovery_engineer_floor"


def test_pending_recovery_engineer_suppresses_combat_until_one_is_completed() -> None:
    snapshot = macro_snapshot()
    snapshot["units"] = [unit for unit in snapshot["units"] if unit["role"] != "engineer"]
    snapshot["pending"] = [
        {
            "actorToken": "10:1",
            "kind": "factory_build",
            "buildRole": "engineer",
            "reason": "recovery_engineer_floor",
        }
    ]
    snapshot["economy"].update(
        massIncome=0,
        massUsage=0,
        massRequested=1,
        massTrend=-1,
        massStoredRatio=0,
    )
    for factory in (unit for unit in snapshot["units"] if unit["role"] == "land_factory"):
        factory.update(
            idle=True,
            needsRally=False,
            canBuild={"engineer": True, "scout": True, "tank": True},
        )

    assert intents_of(decide(snapshot), "factory_build") == []


def test_zero_engineer_stall_recovers_then_retries_lost_remote_mex_end_to_end() -> None:
    harness = make_harness()
    install_markers(harness, [marker("lost-remote", 100, 20)])
    owned = harness.unit(entityId=20, blueprintId="ueb1103", position=[100, 2, 20])
    harness.brain.units = harness.lua.table_from([owned])
    plain(harness.observe())

    factories = [
        harness.unit(
            entityId=1 + index,
            blueprintId="ueb0101",
            canBuild={"uel0105": True, "uel0101": True, "uel0201": True},
        )
        for index in range(2)
    ]
    harness.brain.units = harness.lua.table_from(factories)
    harness.brain.massIncome = 0
    harness.brain.massUsage = 0
    harness.brain.massRequested = 1
    harness.brain.massTrend = -1
    harness.brain.massStoredRatio = 0
    harness.brain.energyTrend = 1
    harness.brain.energyStoredRatio = 0.8
    for token in ("1:1", "2:1"):
        harness.controller.rallied[token] = True

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildFactory) == 1
    assert harness.calls.buildFactory[1].blueprintId == "uel0105"

    harness.brain.tick = 10
    moving = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, moving)
    factories[0].options.queue = lua_value(harness.lua, [])
    factories[0].options.idleState = True
    factories[0].options.states = lua_value(harness.lua, {})
    recovered = harness.unit(
        entityId=10,
        blueprintId="uel0105",
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([*factories, recovered])
    harness.brain.tick = 20
    completed = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, completed)

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb1103"
    assert math.isclose(plain(harness.calls.buildMobile[1].position)[0], 100)


def issue_far_structure_job(harness: Any) -> tuple[Any, Any]:
    install_markers(harness, [marker("far", 410, 20)])
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[10, 2, 20],
        blueprintPhysics={"MaxSpeed": 1.5},
        blueprintEconomy={"BuildRate": 5},
        canBuild={"ueb1103": True},
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
                "priority": 22,
                "reason": "frontier_expansion",
            }
        ],
        observation,
    )
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Moving": True})
    return engineer, harness.controller.pending["1:1"]


def test_detouring_moving_engineer_survives_old_900_tick_boundary_until_derived_deadline() -> None:
    harness = make_harness()
    engineer, operation = issue_far_structure_job(harness)
    assert operation.deadlineTick > 5300
    engineer.options.position = lua_value(harness.lua, [10, 2, 100])
    harness.brain.tick = 901

    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)

    assert harness.controller.pending["1:1"] is not None
    assert harness.controller.pending["1:1"].phase == "travelling"


def test_tiny_periodic_travel_progress_cannot_extend_job_past_derived_deadline_forever() -> None:
    harness = make_harness()
    engineer, operation = issue_far_structure_job(harness)
    deadline = int(operation.deadlineTick)
    x = 10
    for tick in range(800, deadline, 800):
        x += 2
        engineer.options.position = lua_value(harness.lua, [x, 2, 20])
        harness.brain.tick = tick
        observation = harness.observe()
        harness.lua.globals().Controller.Reconcile(harness.controller, observation)
        assert harness.controller.pending["1:1"] is not None

    harness.brain.tick = deadline + 1
    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)

    assert harness.controller.pending["1:1"] is None


@pytest.mark.parametrize(
    ("build_role", "blueprint_id"),
    [("land_factory", "ueb0101"), ("power_generator", "ueb1101")],
)
def test_orphan_factory_and_pgen_foundations_are_uniquely_assisted_to_completion(
    build_role: str,
    blueprint_id: str,
) -> None:
    harness = make_harness()
    install_markers(harness, [])
    builder = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        canBuild={blueprint_id: True},
    )
    harness.brain.units = harness.lua.table_from([builder])
    position = [30, 2, 40]
    execute_intents(
        harness,
        [
            {
                "kind": "build_structure",
                "actorToken": "1:1",
                "buildRole": build_role,
                "position": position,
                "priority": 20,
                "reason": "test_foundation",
            }
        ],
        harness.observe(),
    )

    foundation = harness.unit(
        entityId=10,
        blueprintId=blueprint_id,
        position=position,
        fraction=0.35,
    )
    replacements = [
        harness.unit(
            entityId=2 + index,
            blueprintId="uel0105",
            canBuild={blueprint_id: True},
        )
        for index in range(2)
    ]
    harness.brain.units = harness.lua.table_from([foundation, *replacements])
    harness.brain.energyTrend = 1
    harness.brain.energyStoredRatio = 0.8
    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    snapshot = plain(observation)

    matching = [item for item in snapshot.get("foundations", []) if item["role"] == build_role]
    assert len(matching) == 1
    assert matching[0]["targetToken"] == "10:1"
    assert snapshot["macro"]["constructionBacklog"] == 1
    assists = [
        intent
        for intent in plain(harness.lua.globals().Policy.Decide(observation))
        if intent.get("kind") == "assist_structure" and intent.get("buildRole") == build_role
    ]
    assert len(assists) == 1
    assert assists[0]["reason"] == "finish_orphan"

    execute_intents(harness, assists, observation)
    assert len(harness.calls.guard) == 1
    assert harness.controller.pending[assists[0]["actorToken"]] is not None

    foundation.options.fraction = 1
    harness.brain.tick = 20
    completed = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, completed)
    assert harness.controller.pending[assists[0]["actorToken"]] is None
    assert plain(completed)["macro"]["constructionBacklog"] == 0


def test_far_orphan_assist_remains_travelling_past_900_until_derived_deadline() -> None:
    harness = make_harness()
    install_markers(harness, [])
    foundation = harness.unit(
        entityId=10,
        blueprintId="ueb0101",
        position=[410, 2, 20],
        fraction=0.35,
    )
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[10, 2, 20],
        blueprintPhysics={"MaxSpeed": 1.5},
        canBuild={"ueb0101": True},
    )
    harness.brain.units = harness.lua.table_from([engineer, foundation])
    observation = harness.observe()
    assist = next(
        intent
        for intent in plain(harness.lua.globals().Policy.Decide(observation))
        if intent.get("reason") == "finish_orphan"
    )
    execute_intents(harness, [assist], observation)
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.tick = 1
    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())
    harness.brain.tick = 902
    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())

    operation = harness.controller.pending["1:1"]
    assert operation is not None
    assert operation.phase == "travelling"
    assert operation.deadlineTick > 5000


@pytest.mark.parametrize("mutation", ["dead", "destroyed", "captured", "recycled"])
def test_structure_order_revalidates_exact_live_actor_after_observe(mutation: str) -> None:
    harness = make_harness()
    actor = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        canBuild={"ueb1101": True},
    )
    harness.brain.units = harness.lua.table_from([actor])
    stale_observation = harness.observe()
    if mutation == "dead":
        actor.Dead = True
    elif mutation == "destroyed":
        actor.options.destroyed = True
    elif mutation == "captured":
        actor.options.army = 2
    else:
        replacement = harness.unit(
            entityId=1,
            blueprintId="uel0105",
            canBuild={"ueb1101": True},
        )
        harness.brain.units = harness.lua.table_from([replacement])
        harness.observe()

    execute_intents(
        harness,
        [
            {
                "kind": "build_structure",
                "actorToken": "1:1",
                "buildRole": "power_generator",
                "position": [30, 2, 40],
                "priority": 20,
                "reason": "live_revalidation",
            }
        ],
        stale_observation,
    )

    assert len(harness.calls.buildMobile) == 0
    assert harness.controller.pending["1:1"] is None
    assert plain(harness.controller.reservations) == {}


def test_frontier_backlog_counts_site_once_across_pending_foundation_and_completion() -> None:
    harness = make_harness()
    install_markers(harness, [marker("frontier", 40, 20)])
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    initial = harness.observe()
    initial_plain = plain(initial)
    site = initial_plain["sites"]["mass"][0]
    assert initial_plain["macro"]["constructionBacklog"] == 1
    assert initial_plain["macro"]["engineerDemand"] == 3

    execute_intents(
        harness,
        [
            {
                "kind": "build_structure",
                "actorToken": "1:1",
                "buildRole": "mass_extractor",
                "siteKey": site["key"],
                "clusterKey": site["clusterKey"],
                "position": site["position"],
                "priority": 22,
                "reason": "frontier_expansion",
            }
        ],
        initial,
    )
    pending = plain(harness.observe())
    assert pending["macro"]["constructionBacklog"] == 1
    assert pending["macro"]["engineerDemand"] == 3

    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Building": True})
    foundation = harness.unit(
        entityId=10,
        blueprintId="ueb1103",
        position=site["position"],
        fraction=0.3,
    )
    harness.brain.units = harness.lua.table_from([engineer, foundation])
    building = plain(harness.observe())
    assert building["macro"]["constructionBacklog"] == 1
    assert building["macro"]["engineerDemand"] == 3

    foundation.options.fraction = 1
    harness.brain.tick = 20
    completed = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, completed)
    completed_plain = plain(completed)
    assert completed_plain["macro"]["constructionBacklog"] == 0
    assert completed_plain["macro"]["engineerDemand"] == 2


def test_placement_foundation_with_engine_snap_offset_does_not_double_count_pending_job() -> None:
    harness = make_harness()
    install_markers(harness, [])
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        canBuild={"ueb0101": True},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    observation = harness.observe()
    execute_intents(
        harness,
        [
            {
                "kind": "build_structure",
                "actorToken": "1:1",
                "buildRole": "land_factory",
                "position": [30, 2, 40],
                "priority": 21,
                "reason": "production_saturation",
            }
        ],
        observation,
    )
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Building": True})
    foundation = harness.unit(
        entityId=10,
        blueprintId="ueb0101",
        position=[31, 2, 40],
        fraction=0.2,
    )
    replacement = harness.unit(
        entityId=2,
        blueprintId="uel0105",
        canBuild={"ueb0101": True},
    )
    harness.brain.units = harness.lua.table_from([engineer, foundation, replacement])

    building = plain(harness.observe())

    assert building["macro"]["constructionBacklog"] == 1
    assert building["macro"]["factoryDemand"] == 2
    assert building["foundations"][0]["reserved"] is True
    assert not [
        intent
        for intent in plain(harness.lua.globals().Policy.Decide(harness.observe()))
        if intent.get("reason") == "finish_orphan"
    ]


@pytest.mark.parametrize("failure", ["preflight", "issue"])
def test_frontier_screen_requires_successful_matching_frontier_build_before_guard(failure: str) -> None:
    harness = make_harness()
    install_markers(harness, [marker("frontier", 40, 20)])
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        canBuild={"ueb1103": True},
    )
    escorts = [
        harness.unit(entityId=2 + index, blueprintId="uel0201")
        for index in range(5)
    ]
    harness.brain.units = harness.lua.table_from([engineer, *escorts])
    observation = harness.observe()
    site = plain(observation)["sites"]["mass"][0]
    intents = [
        {
            "kind": "build_structure",
            "actorToken": "1:1",
            "buildRole": "mass_extractor",
            "siteKey": site["key"],
            "clusterKey": site["clusterKey"],
            "position": site["position"],
            "priority": 22,
            "reason": "frontier_expansion",
        },
        {
            "kind": "frontier_screen",
            "engineerToken": "1:1",
            "actorTokens": ["2:1"],
            "clusterKey": site["clusterKey"],
            "priority": 24,
            "reason": "secure_frontier",
        },
    ]
    if failure == "preflight":
        harness.brain.canBuildAt = False
    else:
        harness.calls.failBuildMobile = True

    execute_intents(harness, intents, observation)

    assert len(harness.calls.guard) == 0
    assert harness.controller.frontierMission is None
    assert plain(harness.controller.frontierAssignments) == {}

    harness.brain.canBuildAt = True
    harness.calls.failBuildMobile = False
    harness.brain.tick = 301
    retry_observation = harness.observe()
    execute_intents(harness, intents, retry_observation)
    assert harness.controller.pending["1:1"] is not None
    assert len(harness.calls.guard) == 1


def test_frontier_screen_rejects_cluster_that_does_not_match_pending_operation() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        canBuild={"ueb1103": True},
    )
    escort = harness.unit(entityId=2, blueprintId="uel0201")
    harness.brain.units = harness.lua.table_from([engineer, escort])
    observation = harness.observe()
    execute_intents(
        harness,
        [
            {
                "kind": "build_structure",
                "actorToken": "1:1",
                "buildRole": "mass_extractor",
                "siteKey": "frontier",
                "clusterKey": "cluster-a",
                "position": [40, 2, 20],
                "reason": "frontier_expansion",
                "priority": 22,
            }
        ],
        observation,
    )

    execute_intents(
        harness,
        [
            {
                "kind": "frontier_screen",
                "engineerToken": "1:1",
                "actorTokens": ["2:1"],
                "clusterKey": "cluster-b",
                "priority": 24,
                "reason": "secure_frontier",
            }
        ],
        harness.observe(),
    )

    assert len(harness.calls.guard) == 0
    assert harness.controller.frontierMission is None


def reclaim_observation_with_two_engineers() -> tuple[Any, Any, Any, Any]:
    harness = make_harness()
    observer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[10, 2, 20],
        blueprintIntel={"VisionRadius": 10},
    )
    remote = harness.unit(
        entityId=2,
        blueprintId="uel0105",
        position=[40, 2, 20],
        blueprintIntel={"VisionRadius": 10},
    )
    prop = make_reclaim_prop(harness, entityId=101, position=[12, 2, 20], mass=50)
    harness.brain.units = harness.lua.table_from([observer, remote])
    harness.brain.reclaimables = harness.lua.table_from([prop])
    observation = harness.observe()
    return harness, observer, remote, observation


def test_reclaim_candidate_carries_live_observer_visibility_contract() -> None:
    harness, _, _, observation = reclaim_observation_with_two_engineers()
    candidate = plain(observation)["reclaim"][0]

    assert candidate["observerToken"] == "1:1"
    assert candidate["observedTick"] == 0
    assert candidate["visionRadius"] == 10


def test_reclaim_policy_skips_remote_earlier_engineer_for_visible_observer() -> None:
    snapshot = macro_snapshot("engineer")
    engineers = [unit for unit in snapshot["units"] if unit["role"] == "engineer"]
    engineers[0].update(token="1:1", position=[25, 2, 20], visionRadius=26)
    engineers[1].update(token="2:1", position=[10, 2, 20], visionRadius=10)
    snapshot["reclaim"] = [
        {
            "key": "prop:101",
            "position": [12, 2, 20],
            "mass": 50,
            "reserved": False,
            "observerToken": "2:1",
            "observedTick": 0,
            "visionRadius": 10,
        }
    ]

    reclaim = intents_of(decide(snapshot), "reclaim")

    assert len(reclaim) == 1
    assert reclaim[0]["actorToken"] == "2:1"


@pytest.mark.parametrize(
    "invalidity",
    [
        "observer_dead",
        "observer_moved",
        "observer_vision_disabled",
        "cache_expired",
        "remote_actor",
        "missing_from_fresh_query",
    ],
)
def test_reclaim_revalidates_observer_cache_and_assigned_engineer_visibility(invalidity: str) -> None:
    harness, observer, remote, observation = reclaim_observation_with_two_engineers()
    actor_token = "1:1"
    current = observation
    if invalidity == "observer_dead":
        observer.Dead = True
        harness.brain.units = harness.lua.table_from([remote])
        actor_token = "2:1"
        harness.brain.tick = 10
        current = harness.observe()
    elif invalidity == "observer_moved":
        observer.options.position = lua_value(harness.lua, [40, 2, 20])
        harness.brain.units = harness.lua.table_from([observer])
        harness.brain.tick = 10
        current = harness.observe()
    elif invalidity == "observer_vision_disabled":
        observer.options.visionEnabled = False
    elif invalidity == "cache_expired":
        harness.brain.tick = 301
    elif invalidity == "remote_actor":
        actor_token = "2:1"
    else:
        harness.brain.reclaimables = harness.lua.table_from([])

    execute_intents(
        harness,
        [
            {
                "kind": "reclaim",
                "actorToken": actor_token,
                "targetKey": "prop:101",
                "priority": 50,
                "reason": "controlled_reclaim",
            }
        ],
        current,
    )

    assert len(harness.calls.reclaim) == 0
    assert harness.controller.pending[actor_token] is None


@pytest.mark.parametrize("seed", range(4))
def test_reclaim_top_64_selection_is_deterministic_and_value_correct(seed: int) -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[10, 2, 20],
        blueprintIntel={"VisionRadius": 10},
    )
    props = [
        make_reclaim_prop(harness, entityId=value, position=[12, 2, 20], mass=value)
        for value in range(1, 301)
    ]
    random.Random(seed).shuffle(props)
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.reclaimables = harness.lua.table_from(props)

    candidates = plain(harness.observe())["reclaim"]

    assert len(candidates) == 64
    assert [candidate["mass"] for candidate in candidates] == list(range(300, 236, -1))
    assert [candidate["key"] for candidate in candidates] == [
        f"prop:{value}" for value in range(300, 236, -1)
    ]


def test_reclaim_operation_records_target_position_observer_progress_and_deadline() -> None:
    harness, _, _, observation = reclaim_observation_with_two_engineers()
    execute_intents(
        harness,
        [
            {
                "kind": "reclaim",
                "actorToken": "1:1",
                "targetKey": "prop:101",
                "priority": 50,
                "reason": "controlled_reclaim",
            }
        ],
        observation,
    )

    operation = plain(harness.controller.pending["1:1"])
    assert operation["position"] == [12, 2, 20]
    assert operation["observerToken"] == "1:1"
    assert operation["observedTick"] == 0
    assert operation["initialDistance"] == 2
    assert operation["phase"] in {"travelling", "reclaiming"}
    assert operation["deadlineTick"] >= 900


def test_active_reclaim_reference_survives_top_64_refresh_without_unbounded_cache() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        position=[10, 2, 20],
        blueprintIntel={"VisionRadius": 10},
    )
    target = make_reclaim_prop(
        harness,
        entityId=999,
        position=[12, 2, 20],
        mass=100,
    )
    initial = [target] + [
        make_reclaim_prop(harness, entityId=value, position=[12, 2, 20], mass=value)
        for value in range(1, 64)
    ]
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.reclaimables = harness.lua.table_from(initial)
    observation = harness.observe()
    execute_intents(
        harness,
        [
            {
                "kind": "reclaim",
                "actorToken": "1:1",
                "targetKey": "prop:999",
                "priority": 50,
                "reason": "controlled_reclaim",
            }
        ],
        observation,
    )
    engineer.options.idleState = False
    target.ReclaimLeft = 0.5
    target.options.reclaimLeft = 0.5
    high = [
        make_reclaim_prop(
            harness,
            entityId=1000 + value,
            position=[12, 2, 20],
            mass=200 - value,
        )
        for value in range(70)
    ]
    harness.brain.reclaimables = harness.lua.table_from([target, *high, *initial[1:]])
    harness.brain.tick = 300

    refreshed = harness.observe()
    candidate_keys = [item["key"] for item in plain(refreshed)["reclaim"]]

    assert "prop:999" not in candidate_keys
    assert harness.controller.reclaimRefs["prop:999"] is not None
    assert len(list(harness.controller.reclaimRefs.keys())) <= 65
    harness.lua.globals().Controller.Reconcile(harness.controller, refreshed)
    assert harness.controller.pending["1:1"] is not None


@pytest.mark.parametrize(
    "kind",
    ["mobilize_commander", "commander_push", "reinforce_commander", "attack_wave"],
)
def test_controller_execute_hard_disables_all_cross_map_offense(kind: str) -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness)
    if kind == "mobilize_commander":
        intent = commander_mobilize_intent(observation)
    elif kind == "commander_push":
        intent = commander_push_intent(observation)
    elif kind == "reinforce_commander":
        activate_commander_push(harness)
        intent = commander_reinforcement_intent(observation)
    else:
        intent = {
            "kind": "attack_wave",
            "actorTokens": [
                unit["token"]
                for unit in plain(observation.units)
                if unit["role"] in {"tank", "artillery"}
            ],
            "position": plain(observation.targetPosition),
            "priority": 40,
            "reason": "injected_offense",
        }
    harness.controller.crossMapOffenseEnabled = False
    before = {
        "initial": harness.controller.initialWaveSent,
        "push": harness.controller.commanderPushActive,
        "mobilizing": harness.controller.commanderMobilizing,
        "token": harness.controller.commanderToken,
        "assignments": plain(harness.controller.waveAssignments),
    }

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.sequence) == 0
    assert harness.controller.initialWaveSent == before["initial"]
    assert harness.controller.commanderPushActive == before["push"]
    assert harness.controller.commanderMobilizing == before["mobilizing"]
    assert harness.controller.commanderToken == before["token"]
    assert plain(harness.controller.waveAssignments) == before["assignments"]


def test_realistic_per_tick_surplus_scales_fourth_factory_using_requested_not_capped_usage() -> None:
    harness = make_harness()
    units = [
        harness.unit(entityId=1 + index, blueprintId="ueb0101", idleState=False)
        for index in range(3)
    ]
    engineer = harness.unit(
        entityId=10,
        blueprintId="uel0105",
        canBuild={"ueb0101": True},
    )
    units.append(engineer)
    harness.brain.units = harness.lua.table_from(units)
    harness.brain.energyTrend = 1
    harness.brain.energyStoredRatio = 0.8
    harness.brain.massIncome = 1.2
    harness.brain.massUsage = 0.6
    harness.brain.massRequested = 0.6
    harness.brain.massTrend = 0.6
    harness.brain.massStoredRatio = 0.5
    harness.brain.tick = 0
    plain(harness.observe())
    harness.brain.tick = 300
    observation = harness.observe()
    snapshot = plain(observation)

    assert snapshot["economy"]["unusedMass"] == pytest.approx(0.6)
    assert snapshot["macro"]["factoryDemand"] == 4
    factory_growth = [
        intent
        for intent in plain(harness.lua.globals().Policy.Decide(observation))
        if intent.get("reason") == "production_saturation"
    ]
    assert len(factory_growth) == 1

    execute_intents(harness, factory_growth, observation)
    assert harness.controller.massSurplusTicks == 0
    harness.brain.massRequested = 1.3
    harness.brain.massTrend = -0.1
    harness.brain.tick = 310
    stalled = harness.observe()
    assert plain(stalled)["macro"]["massSurplusTicks"] == 0
    assert not [
        intent
        for intent in plain(harness.lua.globals().Policy.Decide(stalled))
        if intent.get("reason") == "production_saturation"
    ]


def telemetry_units(harness: Any) -> list[Any]:
    return [
        harness.unit(entityId=1, blueprintId="uel0105", position=[10, 2, 20], idleState=False, states={"Moving": True}),
        harness.unit(entityId=2, blueprintId="uel0105", position=[12, 2, 20], idleState=False, states={"Moving": True}),
        harness.unit(entityId=3, blueprintId="uel0105", fraction=0.4),
        harness.unit(entityId=10, blueprintId="ueb1103", position=[12, 2, 20]),
        harness.unit(entityId=11, blueprintId="ueb1103", position=[40, 2, 40], fraction=0.4),
        harness.unit(entityId=12, blueprintId="ueb0101", idleState=False, states={"Building": True}),
        harness.unit(entityId=13, blueprintId="ueb0101", position=[25, 2, 25], fraction=0.4),
        harness.unit(entityId=14, blueprintId="ueb1101"),
        harness.unit(entityId=15, blueprintId="ueb1101", position=[30, 2, 30], fraction=0.4),
        harness.unit(entityId=16, blueprintId="ueb1102"),
        harness.unit(entityId=17, blueprintId="ueb1102", position=[25, 2, 25], fraction=0.4),
        harness.unit(entityId=18, blueprintId="uel0201"),
        harness.unit(entityId=19, blueprintId="uel0201", fraction=0.4),
        harness.unit(entityId=20, blueprintId="uel0104"),
        harness.unit(entityId=21, blueprintId="uel0104", fraction=0.4),
    ]


def test_telemetry_semantically_reports_building_counts_oldest_job_and_cumulative_mass() -> None:
    harness = make_harness()
    units = telemetry_units(harness)
    harness.brain.units = harness.lua.table_from(units)
    harness.brain.armyStats.Economy_TotalProduced_Mass = 1234
    harness.brain.armyStats.Economy_TotalConsumed_Mass = 1000
    harness.brain.armyStats.Economy_Reclaimed_Mass = 234
    harness.brain.armyStats.Economy_AccumExcess_Mass = 12
    harness.controller.pending = lua_value(
        harness.lua,
        {
            "1:1": {
                "actorToken": "1:1",
                "kind": "build_structure",
                "buildRole": "power_generator",
                "position": [100, 2, 20],
                "issuedTick": 10,
                "deadlineTick": 5000,
                "lastProgressTick": 20,
                "lastDistance": 90,
                "lastFraction": 0,
                "phase": "travelling",
                "accepted": True,
                "reason": "energy_recovery",
            },
            "2:1": {
                "actorToken": "2:1",
                "kind": "build_structure",
                "buildRole": "land_factory",
                "position": [200, 2, 20],
                "issuedTick": 5,
                "deadlineTick": 6000,
                "lastProgressTick": 15,
                "lastDistance": 188,
                "lastFraction": 0.25,
                "phase": "travelling",
                "accepted": True,
                "reason": "production_saturation",
            },
        },
    )
    harness.brain.tick = 100
    harness.lua.globals().Controller.Step(harness.controller)
    harness.brain.units = harness.lua.table_from(list(reversed(units)))
    harness.brain.tick = 200
    harness.lua.globals().Controller.Step(harness.controller)
    harness.brain.tick = 400
    harness.lua.globals().Controller.Step(harness.controller)
    snapshots = [telemetry_fields(line) for line in harness.logs if "event=snapshot" in line]

    assert len(snapshots) == 2
    first, second = snapshots
    expected_counts = {
        "completed_mex": "1",
        "building_mex": "1",
        "completed_factories": "1",
        "building_factories": "1",
        "completed_engineers": "2",
        "building_engineers": "1",
        "completed_pgen": "1",
        "building_pgen": "1",
        "completed_hydro": "1",
        "building_hydro": "1",
        "completed_combat": "2",
        "building_combat": "2",
        "completed_aa": "1",
        "building_aa": "1",
    }
    assert {key: first.get(key) for key in expected_counts} == expected_counts
    assert first["oldest_job_actor"] == "2:1"
    assert first["oldest_job_kind"] == "build_structure"
    assert first["oldest_job_phase"] == "travelling"
    assert first["oldest_job_age"] == "95"
    assert first["oldest_job_remaining_distance"] == "188"
    assert first["oldest_job_fraction"] == "0.25"
    assert first["oldest_job_last_progress_tick"] == "15"
    assert first["oldest_job_deadline"] == "6000"
    assert first["mass_produced_total"] == "1234"
    assert first["mass_consumed_total"] == "1000"
    assert first["mass_reclaimed_total"] == "234"
    assert first["mass_excess_total"] == "12"
    for field in (
        "oldest_job_actor",
        "oldest_job_kind",
        "oldest_job_phase",
        "oldest_job_remaining_distance",
        "oldest_job_fraction",
        "oldest_job_last_progress_tick",
        "oldest_job_deadline",
    ):
        assert second[field] == first[field]


def test_job_phase_change_event_is_semantic_and_emitted_once() -> None:
    harness = make_harness()
    engineer, _ = issue_far_structure_job(harness)
    harness.brain.tick = 10
    moving = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, moving)
    engineer.options.position = lua_value(harness.lua, [410, 2, 20])
    engineer.options.states = lua_value(harness.lua, {"Building": True})
    foundation = harness.unit(
        entityId=10,
        blueprintId="ueb1103",
        position=[410, 2, 20],
        fraction=0.2,
    )
    harness.brain.units = harness.lua.table_from([engineer, foundation])
    harness.brain.tick = 20
    building = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, building)
    harness.lua.globals().Controller.Reconcile(harness.controller, building)
    events = [
        telemetry_fields(line)
        for line in harness.logs
        if "event=job_phase_changed" in line
    ]

    assert events == [
        {
            "v": "1",
            "kind": "controller",
            "actor": "1:1",
            "army": "1",
            "event": "job_phase_changed",
            "from": "travelling",
            "phase": "building",
            "tick": "20",
        }
    ]


def test_cumulative_mass_telemetry_uses_safe_sentinels_for_malformed_stats() -> None:
    harness = make_harness()
    harness.brain.armyStats = lua_value(
        harness.lua,
        {
            "Economy_TotalProduced_Mass": {"bad": 1},
            "Economy_TotalConsumed_Mass": "unknown",
        },
    )
    harness.brain.units = harness.lua.table_from([])
    harness.lua.globals().Controller.Step(harness.controller)
    snapshot = telemetry_fields(next(line for line in harness.logs if "event=snapshot" in line))

    assert snapshot["mass_produced_total"] == "-1"
    assert snapshot["mass_consumed_total"] == "-1"
    assert snapshot["mass_reclaimed_total"] == "-1"
    assert snapshot["mass_excess_total"] == "-1"


@pytest.mark.parametrize("mode", ["scalar", "throw"])
def test_cumulative_mass_telemetry_fails_closed_on_invalid_army_stat_api_shape(
    mode: str,
) -> None:
    harness = make_harness()
    if mode == "scalar":
        harness.lua.execute("function brain:GetArmyStat(name, default) return 123 end")
    else:
        harness.lua.execute("function brain:GetArmyStat(name, default) error('bad stat') end")
    harness.brain.units = harness.lua.table_from([])

    harness.lua.globals().Controller.Step(harness.controller)
    snapshot = telemetry_fields(next(line for line in harness.logs if "event=snapshot" in line))

    assert snapshot["mass_produced_total"] == "-1"
    assert snapshot["mass_consumed_total"] == "-1"
    assert snapshot["mass_reclaimed_total"] == "-1"
    assert snapshot["mass_excess_total"] == "-1"
