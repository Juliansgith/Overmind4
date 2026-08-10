from __future__ import annotations

import random
from typing import Any

import pytest

from test_controller import execute_intents, make_harness
from test_policy import decide, intents_of, lua_value, plain
from test_secured_frontier_doctrine import (
    install_markers,
    macro_snapshot,
    make_reclaim_prop,
    marker,
)


def reconcile(harness: Any) -> Any:
    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    return observation


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


def issue_far_assist_job(harness: Any) -> tuple[Any, Any, Any]:
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
    return engineer, foundation, harness.controller.pending["1:1"]


def issue_reclaim_job(harness: Any, *, actor_id: int = 1) -> tuple[Any, Any, Any]:
    engineer = harness.unit(
        entityId=actor_id,
        blueprintId="uel0105",
        position=[40, 2, 20],
        blueprintIntel={"VisionRadius": 10},
    )
    prop = make_reclaim_prop(
        harness,
        entityId=5000,
        position=[42, 2, 20],
        mass=5000,
    )
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.reclaimables = harness.lua.table_from([prop])
    observation = harness.observe()
    execute_intents(
        harness,
        [
            {
                "kind": "reclaim",
                "actorToken": f"{actor_id}:1",
                "targetKey": "prop:5000",
                "priority": 50,
                "reason": "controlled_reclaim",
            }
        ],
        observation,
    )
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Moving": True})
    return engineer, prop, harness.controller.pending[f"{actor_id}:1"]


@pytest.mark.parametrize("kind", ["build_structure", "assist_structure", "reclaim"])
def test_hard_timeout_enters_cancelling_and_retains_exact_ownership(kind: str) -> None:
    harness = make_harness()
    if kind == "build_structure":
        actor, operation = issue_far_structure_job(harness)
        reservation = lambda: harness.controller.reservations["far"]
    elif kind == "assist_structure":
        actor, _, operation = issue_far_assist_job(harness)
        reservation = lambda: harness.controller.foundationReservations["10:1"]
    elif kind == "reclaim":
        actor, _, operation = issue_reclaim_job(harness)
        reservation = lambda: harness.controller.reclaimReservations["prop:5000"]
    deadline = int(operation.deadlineTick)
    assert deadline >= 900
    harness.brain.tick = deadline

    reconcile(harness)

    pending = harness.controller.pending["1:1"]
    assert pending is not None
    assert pending.phase == "cancelling"
    assert pending.cancelReason == "timeout"
    assert reservation() is not None
    assert len(harness.calls.clear) == 1
    assert harness.calls.clear[1].units[1].options.entityId == actor.options.entityId
    if kind == "build_structure":
        assert harness.controller.blockedSites["far"] is None


def test_progressing_moving_actor_at_derived_deadline_is_cancelled_not_released() -> None:
    harness = make_harness()
    engineer, operation = issue_far_structure_job(harness)
    deadline = int(operation.deadlineTick)
    engineer.options.position = lua_value(harness.lua, [200, 2, 100])
    harness.brain.tick = deadline

    reconcile(harness)

    assert harness.controller.pending["1:1"].phase == "cancelling"
    assert harness.controller.reservations["far"] is not None
    assert len(harness.calls.clear) == 1


def test_cancelling_job_blocks_duplicate_even_after_a_hypothetical_backoff_expires() -> None:
    harness = make_harness()
    engineer, operation = issue_far_structure_job(harness)
    deadline = int(operation.deadlineTick)
    harness.brain.tick = deadline
    reconcile(harness)
    replacement = harness.unit(
        entityId=2,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([engineer, replacement])
    harness.brain.tick = deadline + 301
    observation = reconcile(harness)

    execute_intents(
        harness,
        [
            {
                "kind": "build_structure",
                "actorToken": "2:1",
                "buildRole": "mass_extractor",
                "siteKey": "far",
                "position": [410, 2, 20],
                "priority": 22,
                "reason": "frontier_expansion",
            }
        ],
        observation,
    )

    assert len(harness.calls.buildMobile) == 1
    assert harness.controller.pending["1:1"] is not None
    assert harness.controller.pending["2:1"] is None
    assert harness.controller.reservations["far"].actorToken == "1:1"


@pytest.mark.parametrize("kind", ["build_structure", "assist_structure", "reclaim"])
@pytest.mark.parametrize("failure", ["persistent", "single_attempt"])
def test_cancel_clear_exception_retains_ownership_and_retries_immediately(
    kind: str,
    failure: str,
) -> None:
    harness = make_harness()
    if kind == "build_structure":
        engineer, operation = issue_far_structure_job(harness)
        reservation = lambda: harness.controller.reservations["far"]
    elif kind == "assist_structure":
        engineer, _, operation = issue_far_assist_job(harness)
        reservation = lambda: harness.controller.foundationReservations["10:1"]
    else:
        engineer, _, operation = issue_reclaim_job(harness)
        reservation = lambda: harness.controller.reclaimReservations["prop:5000"]
    deadline = int(operation.deadlineTick)
    if failure == "persistent":
        harness.calls.failClear = True
    else:
        harness.calls.failClearAt = 1
    harness.brain.tick = deadline

    observation = reconcile(harness)

    assert len(harness.calls.clear) == 1
    assert harness.controller.pending["1:1"].phase == "cancelling"
    assert reservation() is not None
    harness.calls.failClear = False
    harness.calls.failClearAt = None
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    assert len(harness.calls.clear) == 2
    assert harness.calls.clear[2].units[1].options.entityId == engineer.options.entityId
    assert harness.controller.pending["1:1"] is not None
    assert reservation() is not None


@pytest.mark.parametrize("kind", ["build_structure", "assist_structure", "reclaim"])
def test_successful_cancel_releases_only_after_later_idle_observation(kind: str) -> None:
    harness = make_harness()
    if kind == "build_structure":
        engineer, operation = issue_far_structure_job(harness)
        reservation = lambda: harness.controller.reservations["far"]
        blocked_key = "far"
    elif kind == "assist_structure":
        engineer, _, operation = issue_far_assist_job(harness)
        reservation = lambda: harness.controller.foundationReservations["10:1"]
        blocked_key = operation.placementKey
    else:
        engineer, _, operation = issue_reclaim_job(harness)
        reservation = lambda: harness.controller.reclaimReservations["prop:5000"]
        blocked_key = None
    deadline = int(operation.deadlineTick)
    harness.brain.tick = deadline
    busy_observation = reconcile(harness)

    harness.lua.globals().Controller.Reconcile(harness.controller, busy_observation)
    assert harness.controller.pending["1:1"] is not None
    assert reservation() is not None
    if blocked_key:
        assert harness.controller.blockedSites[blocked_key] is None
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.tick = deadline + 1

    reconcile(harness)

    assert harness.controller.pending["1:1"] is None
    assert reservation() is None
    if blocked_key:
        assert harness.controller.blockedSites[blocked_key] == deadline + 301


@pytest.mark.parametrize("kind", ["build_structure", "assist_structure", "reclaim"])
def test_completion_after_cancel_request_wins_without_failure_backoff(kind: str) -> None:
    harness = make_harness()
    if kind == "build_structure":
        engineer, operation = issue_far_structure_job(harness)
        target = harness.unit(
            entityId=11,
            blueprintId="ueb1103",
            position=[410, 2, 20],
            fraction=1,
        )
        reservation = lambda: harness.controller.reservations["far"]
        blocked_key = "far"
    elif kind == "assist_structure":
        engineer, target, operation = issue_far_assist_job(harness)
        reservation = lambda: harness.controller.foundationReservations["10:1"]
        blocked_key = operation.placementKey
    else:
        engineer, target, operation = issue_reclaim_job(harness)
        reservation = lambda: harness.controller.reclaimReservations["prop:5000"]
        blocked_key = None
    deadline = int(operation.deadlineTick)
    harness.brain.tick = deadline
    reconcile(harness)
    assert harness.controller.pending["1:1"].phase == "cancelling"
    assert len(harness.calls.clear) == 1
    if kind == "build_structure":
        harness.brain.units = harness.lua.table_from([engineer, target])
    elif kind == "assist_structure":
        target.options.fraction = 1
    else:
        target.ReclaimLeft = 0
        target.options.reclaimLeft = 0
    harness.brain.tick = deadline + 300

    reconcile(harness)

    assert harness.controller.pending["1:1"] is None
    assert reservation() is None
    assert len(harness.calls.clear) == 1
    if blocked_key:
        assert harness.controller.blockedSites[blocked_key] is None


def test_already_idle_at_hard_deadline_releases_without_clear_round_trip() -> None:
    harness = make_harness()
    engineer, operation = issue_far_structure_job(harness)
    foundation = harness.unit(
        entityId=11,
        blueprintId="ueb1103",
        position=[410, 2, 20],
        fraction=0.25,
    )
    harness.brain.units = harness.lua.table_from([engineer, foundation])
    operation.phase = "building"
    operation.accepted = True
    operation.lastFraction = 0.25
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    deadline = int(operation.deadlineTick)
    harness.brain.tick = deadline

    reconcile(harness)

    assert harness.controller.pending["1:1"] is None
    assert harness.controller.reservations["far"] is None
    assert harness.controller.blockedSites["far"] == deadline + 300
    assert len(harness.calls.clear) == 0


@pytest.mark.parametrize("kind", ["build_structure", "assist_structure"])
def test_stalled_busy_structure_enters_cancelling_and_holds_reservation(kind: str) -> None:
    harness = make_harness()
    if kind == "build_structure":
        engineer, operation = issue_far_structure_job(harness)
        foundation = harness.unit(
            entityId=11,
            blueprintId="ueb1103",
            position=[410, 2, 20],
            fraction=0.25,
        )
        harness.brain.units = harness.lua.table_from([engineer, foundation])
        reservation = lambda: harness.controller.reservations["far"]
    else:
        engineer, foundation, operation = issue_far_assist_job(harness)
        reservation = lambda: harness.controller.foundationReservations["10:1"]
    operation.phase = "building"
    operation.accepted = True
    operation.lastFraction = 0.25 if kind == "build_structure" else foundation.options.fraction
    operation.lastProgressTick = 0
    harness.brain.tick = 901

    reconcile(harness)

    assert harness.controller.pending["1:1"].phase == "cancelling"
    assert harness.controller.pending["1:1"].cancelReason == "stalled"
    assert reservation() is not None
    assert len(harness.calls.clear) == 1


@pytest.mark.parametrize("kind", ["build_structure", "assist_structure", "reclaim"])
@pytest.mark.parametrize("mutation", ["dead", "destroyed", "captured", "recycled"])
def test_timeout_revalidates_generation_before_first_clear(kind: str, mutation: str) -> None:
    harness = make_harness()
    if kind == "build_structure":
        actor, operation = issue_far_structure_job(harness)
        reservation = lambda: harness.controller.reservations["far"]
    elif kind == "assist_structure":
        actor, _, operation = issue_far_assist_job(harness)
        reservation = lambda: harness.controller.foundationReservations["10:1"]
    else:
        actor, _, operation = issue_reclaim_job(harness)
        reservation = lambda: harness.controller.reclaimReservations["prop:5000"]
    deadline = int(operation.deadlineTick)
    harness.brain.tick = deadline
    stale_observation = harness.observe()
    if mutation == "dead":
        actor.Dead = True
    elif mutation == "destroyed":
        actor.options.destroyed = True
    elif mutation == "captured":
        actor.options.army = 2
    else:
        replacement = harness.unit(
            entityId=actor.options.entityId,
            blueprintId="uel0105",
            position=[40, 2, 20],
            canBuild={"ueb1103": True, "ueb0101": True},
        )
        harness.brain.units = harness.lua.table_from([replacement])
        harness.observe()

    harness.lua.globals().Controller.Reconcile(harness.controller, stale_observation)

    assert len(harness.calls.clear) == 0
    assert harness.controller.pending["1:1"] is None
    assert reservation() is None
    if kind == "build_structure":
        assert harness.controller.blockedSites["far"] is None


def test_release_never_clears_foreign_site_reservation() -> None:
    harness = make_harness()
    engineer, _ = issue_far_structure_job(harness)
    harness.controller.reservations["far"] = lua_value(
        harness.lua,
        {"actorToken": "2:1", "issuedTick": 50},
    )
    engineer.Dead = True
    harness.brain.units = harness.lua.table_from([])

    reconcile(harness)

    assert harness.controller.pending["1:1"] is None
    assert harness.controller.reservations["far"].actorToken == "2:1"


@pytest.mark.parametrize("kind", ["build_structure", "assist_structure", "reclaim"])
@pytest.mark.parametrize("mutation", ["dead", "destroyed", "captured", "recycled"])
def test_cancelling_operation_cleans_up_without_clearing_stale_or_foreign_actor(
    kind: str,
    mutation: str,
) -> None:
    harness = make_harness()
    if kind == "build_structure":
        engineer, operation = issue_far_structure_job(harness)
        reservation = lambda: harness.controller.reservations["far"]
    elif kind == "assist_structure":
        engineer, _, operation = issue_far_assist_job(harness)
        reservation = lambda: harness.controller.foundationReservations["10:1"]
    else:
        engineer, _, operation = issue_reclaim_job(harness)
        reservation = lambda: harness.controller.reclaimReservations["prop:5000"]
    deadline = int(operation.deadlineTick)
    harness.brain.tick = deadline
    reconcile(harness)
    assert len(harness.calls.clear) == 1
    if mutation == "dead":
        engineer.Dead = True
    elif mutation == "destroyed":
        engineer.options.destroyed = True
    elif mutation == "captured":
        engineer.options.army = 2
    else:
        replacement = harness.unit(
            entityId=1,
            blueprintId="uel0105",
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([replacement])
    harness.brain.tick = deadline + 1

    reconcile(harness)

    assert harness.controller.pending["1:1"] is None
    assert reservation() is None
    assert len(harness.calls.clear) == 1


def five_engineer_reclaim_harness(seed: int = 0) -> tuple[Any, list[Any], list[Any], Any]:
    harness = make_harness()
    engineers = [
        harness.unit(
            entityId=entity_id,
            blueprintId="uel0105",
            position=[10, 2, 20],
            blueprintIntel={"VisionRadius": 10},
        )
        for entity_id in range(1, 6)
    ]
    props = [
        make_reclaim_prop(
            harness,
            entityId=100 + entity_id,
            position=[12, 2, 20],
            mass=100 + entity_id,
        )
        for entity_id in range(1, 6)
    ]
    units = list(engineers)
    random.Random(seed).shuffle(units)
    harness.brain.units = harness.lua.table_from(units)
    harness.brain.reclaimables = harness.lua.table_from(props)
    return harness, engineers, props, harness.observe()


@pytest.mark.parametrize("seed", range(8))
def test_executor_caps_reclaim_jobs_to_deterministic_active_query_budget(seed: int) -> None:
    harness, _, _, observation = five_engineer_reclaim_harness(seed)
    intents = [
        {
            "kind": "reclaim",
            "actorToken": f"{entity_id}:1",
            "targetKey": f"prop:{100 + entity_id}",
            "priority": 50,
            "reason": "controlled_reclaim",
        }
        for entity_id in range(1, 6)
    ]
    random.Random(seed + 100).shuffle(intents)

    execute_intents(harness, intents, observation)

    active = sorted(
        token
        for token in harness.controller.pending.keys()
        if harness.controller.pending[token].kind == "reclaim"
    )
    assert active == ["1:1", "2:1", "3:1", "4:1"]
    assert len(harness.calls.reclaim) == 4
    assert harness.controller.pending["5:1"] is None
    assert harness.controller.reclaimReservations["prop:105"] is None


def test_policy_does_not_admit_fifth_reclaim_job() -> None:
    snapshot = macro_snapshot("engineer", "engineer", "engineer", "engineer")
    engineers = sorted(
        (unit for unit in snapshot["units"] if unit["role"] == "engineer"),
        key=lambda unit: unit["token"],
    )
    for engineer in engineers:
        engineer.update(position=[10, 2, 20], visionRadius=10)
    snapshot["pending"] = [
        {
            "actorToken": engineer["token"],
            "kind": "reclaim",
            "targetKey": f"prop:{index}",
            "reason": "controlled_reclaim",
        }
        for index, engineer in enumerate(engineers[:4], 1)
    ]
    snapshot["macro"].update(activeReclaimJobs=4, constructionBacklog=0)
    snapshot["reclaim"] = [
        {
            "key": "prop:5000",
            "position": [12, 2, 20],
            "mass": 5000,
            "reserved": False,
            "observerToken": engineers[4]["token"],
            "observedTick": 0,
            "visionRadius": 10,
        }
    ]

    assert intents_of(decide(snapshot), "reclaim") == []


def fifth_engineer_active_reclaim(seed: int = 0) -> tuple[Any, Any, Any, list[Any]]:
    harness = make_harness()
    active, target, _ = issue_reclaim_job(harness, actor_id=5)
    discovery = [
        harness.unit(
            entityId=entity_id,
            blueprintId="uel0105",
            position=[10, 2, 20],
            blueprintIntel={"VisionRadius": 10},
        )
        for entity_id in range(1, 5)
    ]
    units = [*discovery, active]
    random.Random(seed).shuffle(units)
    harness.brain.units = harness.lua.table_from(units)
    return harness, active, target, discovery


@pytest.mark.parametrize("seed", range(12))
def test_active_fifth_engineer_is_queried_first_and_live_target_is_not_falsely_completed(
    seed: int,
) -> None:
    harness, _, target, _ = fifth_engineer_active_reclaim(seed)
    query_count = len(harness.calls.reclaimQuery)
    harness.brain.tick = 300

    observation = reconcile(harness)
    refresh_queries = plain(harness.calls.reclaimQuery)[query_count:]

    assert target.ReclaimLeft == 1
    assert refresh_queries[0] == [30, 10, 50, 30]
    assert len(refresh_queries) == 4
    assert harness.controller.pending["5:1"] is not None
    assert harness.controller.reclaimReservations["prop:5000"] == "5:1"
    assert harness.controller.reclaimRefs["prop:5000"].EntityId == target.EntityId
    assert plain(observation)["pending"][0]["actorToken"] == "5:1"


@pytest.mark.parametrize("invalidity", ["moved", "vision_disabled", "vision_error", "query_error"])
def test_unqueried_or_uncovered_active_target_is_not_treated_as_absent(invalidity: str) -> None:
    harness, active, _, _ = fifth_engineer_active_reclaim()
    harness.brain.reclaimables = harness.lua.table_from([])
    if invalidity == "moved":
        active.options.position = lua_value(harness.lua, [10, 2, 20])
    elif invalidity == "vision_disabled":
        active.options.visionEnabled = False
    elif invalidity == "vision_error":
        active.options.failVisionEnabled = True
    else:
        harness.calls.failReclaimQuery = True
    harness.brain.tick = 300

    observation = reconcile(harness)

    assert harness.controller.pending["5:1"] is not None
    assert harness.controller.reclaimReservations["prop:5000"] == "5:1"
    assert "prop:5000" not in [
        candidate["key"] for candidate in plain(observation).get("reclaim", [])
    ]


@pytest.mark.parametrize("completion", ["absent", "depleted"])
def test_only_fresh_active_query_absence_or_depletion_completes_reclaim(completion: str) -> None:
    harness, active, target, _ = fifth_engineer_active_reclaim()
    active.options.position = lua_value(harness.lua, [10, 2, 20])
    harness.brain.reclaimables = harness.lua.table_from([])
    harness.brain.tick = 300
    reconcile(harness)
    assert harness.controller.pending["5:1"] is not None
    active.options.position = lua_value(harness.lua, [40, 2, 20])
    if completion == "absent":
        harness.brain.reclaimables = harness.lua.table_from([])
    else:
        target.ReclaimLeft = 0
        target.options.reclaimLeft = 0
        harness.brain.reclaimables = harness.lua.table_from([target])
    harness.brain.tick = 600

    reconcile(harness)

    assert harness.controller.pending["5:1"] is None
    assert harness.controller.reclaimReservations["prop:5000"] is None


@pytest.mark.parametrize("field", ["ReclaimLeft", "MaxMassReclaim"])
def test_freshly_returned_malformed_active_prop_is_not_treated_as_depleted(field: str) -> None:
    harness, _, target, _ = fifth_engineer_active_reclaim()
    setattr(target, field, "malformed")
    harness.brain.tick = 300

    observation = reconcile(harness)

    assert harness.controller.pending["5:1"] is not None
    assert harness.controller.reclaimReservations["prop:5000"] == "5:1"
    assert "prop:5000" not in [
        candidate["key"] for candidate in plain(observation).get("reclaim", [])
    ]


def test_freshly_returned_prop_with_failed_liveness_probe_remains_unknown() -> None:
    harness, _, target, _ = fifth_engineer_active_reclaim()
    target.options.failDestroyed = True
    harness.brain.tick = 300

    reconcile(harness)

    assert harness.controller.pending["5:1"] is not None
    assert harness.controller.reclaimReservations["prop:5000"] == "5:1"
    assert harness.controller.reclaimFreshness["5:1"].state == "unknown"


@pytest.mark.parametrize("identity_failure", ["error", "not_prop"])
def test_freshly_returned_exact_prop_with_failed_identity_probe_remains_unknown(
    identity_failure: str,
) -> None:
    harness, _, target, _ = fifth_engineer_active_reclaim()
    if identity_failure == "error":
        harness.calls.failIsProp = True
    else:
        target.options.isUnit = True
    harness.brain.tick = 300

    reconcile(harness)

    assert harness.controller.pending["5:1"] is not None
    assert harness.controller.reclaimReservations["prop:5000"] == "5:1"
    assert harness.controller.reclaimFreshness["5:1"].state == "unknown"
    assert harness.calls.unitReclaimInspections == 0


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_active_reclaim_actor_lifecycle_cleans_up_without_querying_stale_identity(mutation: str) -> None:
    harness, active, _, discovery = fifth_engineer_active_reclaim()
    harness.brain.tick = 300
    reconcile(harness)
    assert harness.controller.pending["5:1"] is not None
    query_count = len(harness.calls.reclaimQuery)
    if mutation == "dead":
        active.Dead = True
        harness.brain.units = harness.lua.table_from(discovery)
    elif mutation == "captured":
        active.options.army = 2
    else:
        replacement = harness.unit(
            entityId=5,
            blueprintId="uel0105",
            position=[40, 2, 20],
            blueprintIntel={"VisionRadius": 10},
        )
        harness.brain.units = harness.lua.table_from([*discovery, replacement])
    harness.brain.tick = 600

    reconcile(harness)

    assert harness.controller.pending["5:1"] is None
    assert harness.controller.reclaimReservations["prop:5000"] is None
    refresh_queries = plain(harness.calls.reclaimQuery)[query_count:]
    assert [30, 10, 50, 30] not in refresh_queries
