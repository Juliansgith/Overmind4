from __future__ import annotations

import itertools
import math
import random
import re
from typing import Any

import pytest

from conftest import source
from test_controller import execute_intents
from test_field_campaign import (
    actor_tokens_from_call,
    campaign_intents,
    layered_marker,
    reconcile,
    start_campaign,
)
from test_policy import lua_value, plain
from test_pressure_front_campaign import (
    activate_pressure_front,
    campaign_state,
    complete_mex,
    forward_graph_campaign,
    position_field_at,
    put_units,
)


SOURCE_ANCHOR = [55, 2, 45]
DESTINATION = [80, 2, 70]
TERRAIN_DESTINATION = [80, 80.7, 70]
NORMAL_ROUTE = [
    [62, 62.55, 55],
    [70, 70.62, 62],
    TERRAIN_DESTINATION,
]


def configure_route(
    harness: Any,
    waypoints: Any = NORMAL_ROUTE,
    *,
    count: Any = 3,
    length: Any = 48,
) -> None:
    harness.calls.pathReturnNil = waypoints is None
    harness.calls.pathWaypoints = (
        waypoints
        if hasattr(waypoints, "items")
        else lua_value(harness.lua, waypoints)
    )
    harness.calls.pathCount = count
    harness.calls.pathLength = length


def path_probe_state(harness: Any) -> dict[str, Any]:
    state = campaign_state(harness)
    return state.get("routeAttempt") or {}


def route_events(harness: Any, name: str) -> list[str]:
    needle = f"event={name}"
    return [line for line in harness.logs if needle in line]


def telemetry_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in line.split("|"):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key] = value
    return fields


def calls(values: Any) -> list[Any]:
    return list(values.values())


def stage_transition_probe(
    seed: int = 0,
    *,
    waypoints: Any = NORMAL_ROUTE,
    count: Any = 3,
    length: Any = 48,
) -> tuple[Any, Any, Any, list[Any], Any, dict[str, Any]]:
    harness, acu, engineer, combat, observation = forward_graph_campaign(seed)
    activate_pressure_front(harness, observation)
    mexes = [
        complete_mex(harness, 70000, [45, 2, 35]),
        complete_mex(harness, 70001, [55, 2, 45]),
    ]
    position_field_at(harness, combat, campaign_state(harness)["anchorPosition"])
    put_units(harness, [acu, engineer, *combat, *mexes], seed)
    harness.brain.tick = 10
    reconcile(harness)
    configure_route(harness, waypoints, count=count, length=length)
    before = campaign_state(harness)
    harness.brain.tick = 160
    ready = reconcile(harness)
    return harness, acu, engineer, combat, ready, before


def stage_assault_probe(
    seed: int = 0,
    *,
    waypoints: Any | None = None,
    count: Any = 2,
    length: Any = 60,
) -> tuple[Any, Any, Any, list[Any], Any, dict[str, Any]]:
    harness, acu, engineer, combat, observation = start_campaign(
        seed=seed,
        site_key="last-front",
        cluster_key="last-front",
        position=[100, 2, 100],
    )
    activate_pressure_front(harness, observation)
    mex = complete_mex(harness, 70100, [100, 2, 100])
    position_field_at(harness, combat, [100, 2, 100])
    put_units(harness, [acu, engineer, *combat, mex], seed)
    harness.brain.tick = 10
    reconcile(harness)
    target = [110, 111.2, 120]
    configure_route(
        harness,
        waypoints or [[105, 106.1, 110], target],
        count=count,
        length=length,
    )
    before = campaign_state(harness)
    harness.brain.tick = 160
    ready = reconcile(harness)
    return harness, acu, engineer, combat, ready, before


def only_campaign_intent(harness: Any, observation: Any, mode: str) -> dict[str, Any]:
    intents = campaign_intents(harness, observation)
    assert len(intents) == 1
    assert intents[0]["mode"] == mode
    return intents[0]


def execute_probe(harness: Any, observation: Any) -> dict[str, Any]:
    intent = only_campaign_intent(harness, observation, "route_probe")
    execute_intents(harness, [intent], observation)
    return intent


def move_probe_to_destination(harness: Any, *, distance: float = 0) -> list[str]:
    route = path_probe_state(harness)
    tokens = list(route["probeTokens"])
    destination = route["destination"]
    for index, token in enumerate(tokens):
        actor = harness.controller.unitRefs[token]
        actor.options.position = lua_value(
            harness.lua,
            [destination[0] + (distance if index == 0 else 0), destination[1], destination[2]],
        )
    return tokens


def prove_transition(
    harness: Any,
    observation: Any,
    *,
    arrived: int | None = None,
) -> tuple[Any, dict[str, Any], list[str]]:
    probe = execute_probe(harness, observation)
    tokens = list(probe["actorTokens"])
    route = path_probe_state(harness)
    destination = route["destination"]
    count = len(tokens) if arrived is None else arrived
    for token in tokens[:count]:
        harness.controller.unitRefs[token].options.position = lua_value(
            harness.lua, destination
        )
    harness.brain.tick += 1
    proven_observation = reconcile(harness)
    commit = only_campaign_intent(harness, proven_observation, "route_commit")
    return proven_observation, commit, tokens


def test_proven_bulk_route_dispatches_small_disjoint_groups_instead_of_one_large_formation() -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    proven, commit, _ = prove_transition(harness, ready)
    bulk = sorted(commit["actorTokens"])
    assert len(bulk) > 8
    clear_before = len(harness.calls.clear)
    move_before = len(harness.calls.move)
    aggressive_before = len(harness.calls.aggressive)

    execute_intents(harness, [commit], proven)

    clear_calls = calls(harness.calls.clear)[clear_before:]
    move_calls = calls(harness.calls.move)[move_before:]
    aggressive_calls = calls(harness.calls.aggressive)[aggressive_before:]
    assert len(clear_calls) == 1
    assert actor_tokens_from_call(clear_calls[0]) == bulk
    assert len(aggressive_calls) == len(bulk)
    groups = [actor_tokens_from_call(call) for call in aggressive_calls]
    assert all(len(group) == 1 for group in groups)
    assert sorted(token for group in groups for token in group) == bulk
    assert len({token for group in groups for token in group}) == len(bulk)
    assert groups == [[token] for token in bulk]
    assert len(move_calls) == len(aggressive_calls) * (len(NORMAL_ROUTE) - 1)
    for group_index, group in enumerate(groups):
        group_moves = move_calls[
            group_index * (len(NORMAL_ROUTE) - 1) :
            (group_index + 1) * (len(NORMAL_ROUTE) - 1)
        ]
        assert all(actor_tokens_from_call(call) == group for call in group_moves)


@pytest.mark.parametrize("seed", range(6))
def test_secured_transition_stages_bounded_frozen_probe_before_any_full_field_order(
    seed: int,
) -> None:
    harness, _, _, _, ready, before = stage_transition_probe(seed)
    intent = only_campaign_intent(harness, ready, "route_probe")
    route = path_probe_state(harness)

    assert campaign_state(harness)["kind"] == before["kind"] == "pressure_front"
    assert campaign_state(harness)["clusterKey"] == before["clusterKey"] == "current-a"
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"] == "current-b"
    assert campaign_state(harness)["anchorPosition"] == before["anchorPosition"] == SOURCE_ANCHOR
    assert route["state"] == "staged"
    assert route["candidateKind"] == "pressure_front"
    assert route["candidateClusterKey"] == "forward-near"
    assert route["candidateAnchorKey"] == "forward-near-b"
    assert route["probeQuorum"] == 2
    assert 1 <= len(route["probeTokens"]) <= 4
    assert intent["actorTokens"] == route["probeTokens"]
    assert "1000:1" in route["probeTokens"]
    assert len(harness.calls.navPath) == 1
    assert plain(harness.calls.navPath[1][1]) == "Land"
    assert len(harness.calls.clear) == 1  # activation only
    assert len(harness.calls.aggressive) == 1


def test_probe_orders_exact_cached_route_and_never_orders_non_probe_field_before_proof() -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    intent = execute_probe(harness, ready)
    route = path_probe_state(harness)
    probe = sorted(intent["actorTokens"])

    assert route["state"] == "probing"
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert plain(harness.calls.sequence)[-4:] == ["clear", "move", "move", "aggressive"]
    assert actor_tokens_from_call(calls(harness.calls.clear)[-1]) == probe
    assert actor_tokens_from_call(calls(harness.calls.move)[-2]) == probe
    assert actor_tokens_from_call(calls(harness.calls.move)[-1]) == probe
    assert actor_tokens_from_call(calls(harness.calls.aggressive)[-1]) == probe
    assert plain(calls(harness.calls.move)[-2].position) == NORMAL_ROUTE[0]
    assert plain(calls(harness.calls.move)[-1].position) == NORMAL_ROUTE[1]
    assert plain(calls(harness.calls.aggressive)[-1].position) == TERRAIN_DESTINATION
    assert set(probe).isdisjoint(set(campaign_state(harness)["homeTokens"]))
    assert len(probe) < len(campaign_state(harness)["fieldTokens"])


def test_same_section_zero_index_route_is_valid_and_still_orders_exact_destination() -> None:
    harness, acu, engineer, combat, observation = forward_graph_campaign()
    activate_pressure_front(harness, observation)
    mexes = [
        complete_mex(harness, 70200, [45, 2, 35]),
        complete_mex(harness, 70201, [55, 2, 45]),
    ]
    position_field_at(harness, combat, SOURCE_ANCHOR)
    put_units(harness, [acu, engineer, *combat, *mexes])
    harness.brain.tick = 10
    reconcile(harness)
    path = harness.lua.table()
    path[0] = lua_value(harness.lua, TERRAIN_DESTINATION)
    configure_route(harness, path, count=0, length=0)
    assert harness.calls.pathWaypoints[0] is not None
    assert harness.calls.pathWaypoints[1] is None
    harness.brain.tick = 160
    ready = reconcile(harness)

    execute_probe(harness, ready)

    assert plain(harness.calls.sequence)[-2:] == ["clear", "aggressive"]
    assert len(harness.calls.move) == 0
    assert plain(calls(harness.calls.aggressive)[-1].position) == TERRAIN_DESTINATION
    assert path_probe_state(harness)["state"] == "probing"


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("nil", "NotGenerated"),
        ("nil", "InvalidLayer"),
        ("nil", "OriginOutsideMap"),
        ("nil", "OriginUnpathable"),
        ("nil", "DestinationOutsideMap"),
        ("nil", "DestinationUnpathable"),
        ("nil", "SystemError"),
        ("false", "Unpathable"),
        ("exception", "error"),
    ],
)
def test_can_path_failures_block_candidate_without_commands_or_state_commit(
    failure: str,
    reason: str,
) -> None:
    harness, acu, engineer, combat, observation = forward_graph_campaign()
    activate_pressure_front(harness, observation)
    mexes = [complete_mex(harness, 70300, [45, 2, 35]), complete_mex(harness, 70301, [55, 2, 45])]
    position_field_at(harness, combat, SOURCE_ANCHOR)
    put_units(harness, [acu, engineer, *combat, *mexes])
    harness.brain.tick = 10
    reconcile(harness)
    if failure == "exception":
        harness.calls.failCanPath = True
    else:
        harness.calls.canPathMode = failure
        harness.calls.canPathReason = reason
    before = campaign_state(harness)
    harness.brain.tick = 160
    current = reconcile(harness)

    assert campaign_intents(harness, current) == []
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert len(harness.calls.navPath) == 0
    assert len(harness.calls.clear) == 1
    assert len(harness.calls.aggressive) == 1
    assert campaign_state(harness).get("routeBlockedCount", 0) >= 1


@pytest.mark.parametrize(
    "label_values",
    [[0, 1], [-1, 1], [None, 1], [1, 0], [1, -1], [1, None], [1, 2]],
)
def test_both_route_endpoint_labels_must_be_positive_numbers(label_values: list[Any]) -> None:
    harness, acu, engineer, combat, observation = forward_graph_campaign()
    activate_pressure_front(harness, observation)
    mexes = [complete_mex(harness, 70400, [45, 2, 35]), complete_mex(harness, 70401, [55, 2, 45])]
    position_field_at(harness, combat, SOURCE_ANCHOR)
    put_units(harness, [acu, engineer, *combat, *mexes])
    harness.brain.tick = 10
    reconcile(harness)
    harness.calls.labelValues = lua_value(harness.lua, label_values)
    configure_route(harness)
    harness.brain.tick = 160
    current = reconcile(harness)

    assert campaign_intents(harness, current) == []
    assert len(harness.calls.navPath) == 0
    assert campaign_state(harness).get("routeBlockedCount", 0) >= 1


@pytest.mark.parametrize("failure", ["exception", "NotGenerated", "SystemError", "Unpathable"])
def test_path_to_exception_or_error_tuple_blocks_only_candidate_before_commands(failure: str) -> None:
    harness, acu, engineer, combat, observation = forward_graph_campaign()
    activate_pressure_front(harness, observation)
    mexes = [complete_mex(harness, 70410, [45, 2, 35]), complete_mex(harness, 70411, [55, 2, 45])]
    position_field_at(harness, combat, SOURCE_ANCHOR)
    put_units(harness, [acu, engineer, *combat, *mexes])
    harness.brain.tick = 10
    reconcile(harness)
    if failure == "exception":
        harness.calls.failPath = True
    else:
        harness.calls.pathError = failure
    before = campaign_state(harness)
    harness.brain.tick = 160
    current = reconcile(harness)

    assert campaign_intents(harness, current) == []
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert len(harness.calls.navPath) == 1
    assert len(harness.calls.clear) == 1


def test_get_label_exception_fails_closed_without_calling_path_to() -> None:
    harness, acu, engineer, combat, observation = forward_graph_campaign()
    activate_pressure_front(harness, observation)
    mexes = [complete_mex(harness, 70420, [45, 2, 35]), complete_mex(harness, 70421, [55, 2, 45])]
    position_field_at(harness, combat, SOURCE_ANCHOR)
    put_units(harness, [acu, engineer, *combat, *mexes])
    harness.brain.tick = 10
    reconcile(harness)
    harness.calls.failGetLabel = True
    harness.brain.tick = 160
    current = reconcile(harness)

    assert campaign_intents(harness, current) == []
    assert len(harness.calls.navPath) == 0
    assert len(harness.calls.clear) == 1


@pytest.mark.parametrize(
    "waypoints,count,length",
    [
        (None, 1, 10),
        ([], 0, 0),
        ([[60, 2, 55], None, TERRAIN_DESTINATION], 3, 20),
        ([[60, 2, 55], TERRAIN_DESTINATION], -1, 20),
        ([[60, 2, 55], TERRAIN_DESTINATION], 1.5, 20),
        ([[60, 2, 55], TERRAIN_DESTINATION], "2", 20),
        ([[60, 2, 55], TERRAIN_DESTINATION], 2, -1),
        ([[60, 2, 55], TERRAIN_DESTINATION], 2, float("nan")),
        ([[60, 2, 55], TERRAIN_DESTINATION], 2, 10**12),
        ([[60, 2, 55], [float("nan"), 2, 70]], 2, 20),
        ([[60, float("nan"), 55], TERRAIN_DESTINATION], 2, 48),
        ([[60, float("inf"), 55], TERRAIN_DESTINATION], 2, 48),
        ([[60, 10**8, 55], TERRAIN_DESTINATION], 2, 48),
        ([[60, 2, 55], [80, float("nan"), 70]], 2, 48),
        ([[60, 2, 55], [80, float("inf"), 70]], 2, 48),
        ([[60, 2, 55], [80, 10**8, 70]], 2, 48),
        ([[60, 2, 55], [80, 2]], 2, 20),
        ([[60, 2, 55], [81, 81.7, 70]], 2, 20),
    ],
)
def test_malformed_path_shapes_fail_closed_before_any_probe_order(
    waypoints: Any,
    count: Any,
    length: Any,
) -> None:
    harness, _, _, _, current, before = stage_transition_probe(
        waypoints=waypoints,
        count=count,
        length=length,
    )

    assert campaign_intents(harness, current) == []
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert len(harness.calls.clear) == 1
    assert len(harness.calls.move) == 0
    assert len(harness.calls.aggressive) == 1


def test_path_waypoint_count_is_strictly_bounded() -> None:
    waypoints = [[60 + index * 0.1, 2, 55 + index * 0.1] for index in range(32)]
    waypoints.append(TERRAIN_DESTINATION)
    harness, _, _, _, current, before = stage_transition_probe(
        waypoints=waypoints,
        count=len(waypoints),
        length=48,
    )

    assert campaign_intents(harness, current) == []
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert len(harness.calls.clear) == 1


def test_cyclic_or_map_shaped_waypoint_table_is_rejected_without_recursing() -> None:
    for shape in ["cycle", "map"]:
        harness, acu, engineer, combat, observation = forward_graph_campaign()
        activate_pressure_front(harness, observation)
        mexes = [complete_mex(harness, 70430, [45, 2, 35]), complete_mex(harness, 70431, [55, 2, 45])]
        position_field_at(harness, combat, SOURCE_ANCHOR)
        put_units(harness, [acu, engineer, *combat, *mexes])
        harness.brain.tick = 10
        reconcile(harness)
        path = harness.lua.table()
        if shape == "cycle":
            path[1] = path
            path[2] = lua_value(harness.lua, TERRAIN_DESTINATION)
        else:
            path["first"] = lua_value(harness.lua, NORMAL_ROUTE[0])
            path["last"] = lua_value(harness.lua, TERRAIN_DESTINATION)
        configure_route(harness, path, count=2, length=48)
        harness.brain.tick = 160
        current = reconcile(harness)
        assert campaign_intents(harness, current) == []
        assert len(harness.calls.clear) == 1


def test_returned_count_is_authoritative_and_ignores_out_of_range_table_keys() -> None:
    harness, acu, engineer, combat, observation = forward_graph_campaign()
    activate_pressure_front(harness, observation)
    mexes = [complete_mex(harness, 70500, [45, 2, 35]), complete_mex(harness, 70501, [55, 2, 45])]
    position_field_at(harness, combat, SOURCE_ANCHOR)
    put_units(harness, [acu, engineer, *combat, *mexes])
    harness.brain.tick = 10
    reconcile(harness)
    path = lua_value(harness.lua, NORMAL_ROUTE)
    path[0] = lua_value(harness.lua, [999, 999, 999])
    path[999] = lua_value(harness.lua, [999, 999, 999])
    configure_route(harness, path, count=3, length=48)
    harness.brain.tick = 160
    ready = reconcile(harness)
    execute_probe(harness, ready)

    assert [plain(call.position) for call in harness.calls.move.values()] == NORMAL_ROUTE[:2]
    assert plain(calls(harness.calls.aggressive)[-1].position) == TERRAIN_DESTINATION


@pytest.mark.parametrize("failure", ["clear", "move_1", "move_2", "aggressive"])
def test_every_probe_command_failure_preserves_staged_attempt_and_is_retryable(
    failure: str,
) -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    intent = only_campaign_intent(harness, ready, "route_probe")
    route_before = path_probe_state(harness)
    if failure == "clear":
        harness.calls.failClear = True
    elif failure == "move_1":
        harness.calls.failMoveAt = 1
    elif failure == "move_2":
        harness.calls.failMoveAt = 2
    else:
        harness.calls.failAggressiveAt = 2  # activation is call 1

    execute_intents(harness, [intent], ready)

    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert path_probe_state(harness)["state"] == route_before["state"] == "staged"
    assert campaign_state(harness)["pendingMode"] == "route_probe"
    if failure in {"move_1", "move_2", "aggressive"}:
        assert plain(harness.calls.sequence)[-1] == "clear"
    harness.calls.failClear = False
    harness.calls.failMoveAt = None
    harness.calls.failAggressiveAt = None
    execute_intents(harness, [intent], ready)
    assert path_probe_state(harness)["state"] == "probing"
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]


def arm_route_failure(harness: Any, failure: str) -> None:
    clear = len(harness.calls.clear)
    move = len(harness.calls.move)
    aggressive = len(harness.calls.aggressive)
    if failure == "clear":
        harness.calls.failClearAt = clear + 1
    elif failure == "move_1":
        harness.calls.failMoveAt = move + 1
    elif failure == "move_2":
        harness.calls.failMoveAt = move + 2
    elif failure == "aggressive":
        harness.calls.failAggressiveAt = aggressive + 1
    else:
        harness.calls.failMoveAt = move + 1
        harness.calls.failClearAt = clear + 2


def clear_route_failures(harness: Any) -> None:
    harness.calls.failClear = False
    harness.calls.failClearAt = None
    harness.calls.failMoveAt = None
    harness.calls.failAggressiveAt = None


def fail_bulk_dispatch_after_partial_queue(
    harness: Any,
    failure: str,
) -> None:
    clear_before = len(harness.calls.clear)
    move_before = len(harness.calls.move)
    aggressive_before = len(harness.calls.aggressive)
    harness.calls.failClearAt = clear_before + 2
    if failure == "move_2_cleanup":
        harness.calls.failMoveAt = move_before + 2
    elif failure == "aggressive_cleanup":
        harness.calls.failAggressiveAt = aggressive_before + 1
    else:
        raise AssertionError(f"unknown bulk failure: {failure}")


@pytest.mark.parametrize("phase", ["probe", "commit"])
@pytest.mark.parametrize(
    "failure",
    ["clear", "move_1", "move_2", "aggressive", "compensation_clear"],
)
def test_persistent_dispatch_failure_releases_by_three_hundred_and_expires_by_six_hundred(
    phase: str,
    failure: str,
) -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    if phase == "probe":
        observation = ready
        intent = only_campaign_intent(harness, observation, "route_probe")
        failure_tick = 160
    else:
        execute_probe(harness, ready)
        move_probe_to_destination(harness)
        harness.brain.tick = 161
        observation = reconcile(harness)
        intent = only_campaign_intent(harness, observation, "route_commit")
        failure_tick = 161
    arm_route_failure(harness, failure)
    execute_intents(harness, [intent], observation)
    assert path_probe_state(harness)["state"] == (
        "staged" if phase == "probe" else "proven"
    )

    clear_route_failures(harness)
    harness.brain.tick = failure_tick + 299
    before_boundary = reconcile(harness)
    expected = "route_probe" if phase == "probe" else "route_commit"
    assert only_campaign_intent(harness, before_boundary, expected)["mode"] == expected
    harness.brain.tick = failure_tick + 300
    releasing = reconcile(harness)
    release = only_campaign_intent(harness, releasing, "route_release")
    assert path_probe_state(harness)["state"] == "releasing"
    assert campaign_state(harness).get("routeBlockedCount", 0) == 0

    harness.calls.failClear = True
    execute_intents(harness, [release], releasing)
    harness.brain.tick = 759
    assert path_probe_state(harness) != {}
    reconcile(harness)
    assert path_probe_state(harness) != {}
    harness.brain.tick = 760
    expired = reconcile(harness)
    assert path_probe_state(harness) == {}
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert campaign_state(harness)["state"] != "rebuilding"
    assert campaign_intents(harness, expired) == []


@pytest.mark.parametrize("failure", ["move_2_cleanup", "aggressive_cleanup"])
@pytest.mark.parametrize("release_result", ["success", "deadline"])
def test_partial_bulk_dispatch_cleanup_failure_retains_every_touched_generation_for_release(
    failure: str,
    release_result: str,
) -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    proven, commit, probes = prove_transition(harness, ready)
    bulk = list(commit["actorTokens"])
    expected_release = sorted(set(probes + bulk))
    assert set(probes).isdisjoint(bulk)
    assert len(bulk) > 1

    fail_bulk_dispatch_after_partial_queue(harness, failure)
    execute_intents(harness, [commit], proven)

    expected_tail = (
        ["clear", "move", "move", "clear"]
        if failure == "move_2_cleanup"
        else ["clear", "move", "move", "aggressive", "clear"]
    )
    assert plain(harness.calls.sequence)[-len(expected_tail) :] == expected_tail
    assert path_probe_state(harness)["state"] == "proven"
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]

    clear_route_failures(harness)
    harness.brain.tick = 461
    releasing = reconcile(harness)
    release = only_campaign_intent(harness, releasing, "route_release")
    assert release["actorTokens"] == expected_release
    assert path_probe_state(harness)["releaseTokens"] == expected_release

    if release_result == "success":
        execute_intents(harness, [release], releasing)
        assert actor_tokens_from_call(calls(harness.calls.clear)[-1]) == expected_release
        assert actor_tokens_from_call(calls(harness.calls.aggressive)[-1]) == expected_release
        assert path_probe_state(harness) == {}
    else:
        harness.calls.failClear = True
        execute_intents(harness, [release], releasing)
        harness.brain.tick = 760
        assert path_probe_state(harness) != {}
        harness.brain.tick = 761
        expired = reconcile(harness)
        assert path_probe_state(harness) == {}
        assert campaign_intents(harness, expired) == []

    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert campaign_state(harness)["state"] != "rebuilding"


@pytest.mark.parametrize("failure", ["move_2_cleanup", "aggressive_cleanup"])
@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_partial_bulk_release_never_adopts_replacement_or_stale_touched_actor(
    failure: str,
    mutation: str,
) -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    proven, commit, probes = prove_transition(harness, ready)
    bulk = list(commit["actorTokens"])
    stale_token = bulk[0]
    stale_actor = harness.controller.unitRefs[stale_token]
    fail_bulk_dispatch_after_partial_queue(harness, failure)
    execute_intents(harness, [commit], proven)
    clear_route_failures(harness)

    replacement_token = None
    units = list(harness.brain.units.values())
    if mutation == "dead":
        stale_actor.Dead = True
    elif mutation == "captured":
        stale_actor.options.army = 2
    else:
        replacement = harness.unit(
            entityId=int(stale_actor.options.entityId),
            blueprintId=str(stale_actor.options.blueprintId),
            position=SOURCE_ANCHOR,
        )
        units = [
            replacement
            if int(candidate.options.entityId) == int(stale_actor.options.entityId)
            else candidate
            for candidate in units
        ]
        put_units(harness, units)
        harness.observe()
        replacement_token = f"{int(stale_actor.options.entityId)}:2"

    harness.brain.tick = 461
    releasing = reconcile(harness)
    stale_release = only_campaign_intent(harness, releasing, "route_release")
    assert stale_release["actorTokens"] == sorted(set(probes + bulk))
    assert stale_token in stale_release["actorTokens"]
    if replacement_token:
        assert replacement_token not in stale_release["actorTokens"]
    clear_before = len(harness.calls.clear)
    execute_intents(harness, [stale_release], releasing)
    assert len(harness.calls.clear) == clear_before

    harness.brain.tick = 462
    current = reconcile(harness)
    fresh_release = only_campaign_intent(harness, current, "route_release")
    expected = sorted(set(probes + bulk) - {stale_token})
    assert fresh_release["actorTokens"] == expected
    assert stale_token not in fresh_release["actorTokens"]
    if replacement_token:
        assert replacement_token not in fresh_release["actorTokens"]
    execute_intents(harness, [fresh_release], current)
    assert path_probe_state(harness) == {}


@pytest.mark.parametrize("failure", ["move_2_cleanup", "aggressive_cleanup"])
@pytest.mark.parametrize(
    "mutation",
    ["drop", "add", "reorder", "malformed", "replacement_generation"],
)
def test_latched_bulk_cleanup_ownership_is_sealed_before_release_phase(
    failure: str,
    mutation: str,
) -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    proven, commit, probes = prove_transition(harness, ready)
    bulk = list(commit["actorTokens"])
    authoritative = sorted(set(probes + bulk))
    fail_bulk_dispatch_after_partial_queue(harness, failure)
    execute_intents(harness, [commit], proven)
    clear_route_failures(harness)
    route = harness.controller.fieldCampaign.routeAttempt
    replacement_token = None

    if mutation == "drop":
        route.releaseTokens = lua_value(harness.lua, probes)
    elif mutation == "add":
        route.releaseTokens = lua_value(harness.lua, sorted(authoritative + ["99999:1"]))
    elif mutation == "reorder":
        route.releaseTokens = lua_value(harness.lua, list(reversed(authoritative)))
    elif mutation == "malformed":
        route.releaseTokens = True
    else:
        stale_token = bulk[0]
        stale_actor = harness.controller.unitRefs[stale_token]
        replacement = harness.unit(
            entityId=int(stale_actor.options.entityId),
            blueprintId=str(stale_actor.options.blueprintId),
            position=SOURCE_ANCHOR,
        )
        put_units(
            harness,
            [
                replacement
                if int(candidate.options.entityId) == int(stale_actor.options.entityId)
                else candidate
                for candidate in harness.brain.units.values()
            ],
        )
        harness.observe()
        replacement_token = f"{int(stale_actor.options.entityId)}:2"
        route.releaseTokens = lua_value(
            harness.lua,
            sorted(
                replacement_token if token == stale_token else token
                for token in authoritative
            ),
        )

    harness.brain.tick = 461
    releasing = reconcile(harness)
    release = only_campaign_intent(harness, releasing, "route_release")
    assert release["actorTokens"] == authoritative
    assert path_probe_state(harness)["releaseTokens"] == authoritative
    assert campaign_state(harness).get("routeBlockedCount", 0) == 0
    if replacement_token:
        assert replacement_token not in release["actorTokens"]


@pytest.mark.parametrize("failure", ["move_2_cleanup", "aggressive_cleanup"])
@pytest.mark.parametrize(
    "mutation",
    ["drop", "add", "reorder", "malformed", "replacement_generation"],
)
def test_sealed_route_cleanup_ownership_precedes_mutated_recovery_copy(
    failure: str,
    mutation: str,
) -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    proven, commit, probes = prove_transition(harness, ready)
    bulk = list(commit["actorTokens"])
    authoritative = sorted(set(probes + bulk))
    fail_bulk_dispatch_after_partial_queue(harness, failure)
    execute_intents(harness, [commit], proven)
    clear_route_failures(harness)
    sealed_route = harness.controller.fieldCampaign.routeAttempt
    assert plain(sealed_route.cleanupTokens) == authoritative
    ownership = harness.controller.routeCleanupOwnership
    replacement_token = None

    if mutation == "drop":
        ownership.tokens = lua_value(harness.lua, probes)
    elif mutation == "add":
        ownership.tokens = lua_value(harness.lua, sorted(authoritative + ["99999:1"]))
    elif mutation == "reorder":
        ownership.tokens = lua_value(harness.lua, list(reversed(authoritative)))
    elif mutation == "malformed":
        ownership.tokens = True
    else:
        stale_token = bulk[0]
        stale_actor = harness.controller.unitRefs[stale_token]
        replacement = harness.unit(
            entityId=int(stale_actor.options.entityId),
            blueprintId=str(stale_actor.options.blueprintId),
            position=SOURCE_ANCHOR,
        )
        put_units(
            harness,
            [
                replacement
                if int(candidate.options.entityId) == int(stale_actor.options.entityId)
                else candidate
                for candidate in harness.brain.units.values()
            ],
        )
        harness.observe()
        replacement_token = f"{int(stale_actor.options.entityId)}:2"
        ownership.tokens = lua_value(
            harness.lua,
            sorted(
                replacement_token if token == stale_token else token
                for token in authoritative
            ),
        )

    harness.brain.tick = 461
    releasing = reconcile(harness)
    release = only_campaign_intent(harness, releasing, "route_release")
    assert release["actorTokens"] == authoritative
    assert path_probe_state(harness)["releaseTokens"] == authoritative
    assert campaign_state(harness).get("routeBlockedCount", 0) == 0
    if replacement_token:
        assert replacement_token not in release["actorTokens"]


@pytest.mark.parametrize("phase", ["probe", "commit"])
def test_never_executed_route_pending_uses_same_three_hundred_tick_release_bound(
    phase: str,
) -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    if phase == "probe":
        failure_tick = 160
        expected = "route_probe"
    else:
        execute_probe(harness, ready)
        move_probe_to_destination(harness)
        harness.brain.tick = 161
        ready = reconcile(harness)
        failure_tick = 161
        expected = "route_commit"
    assert only_campaign_intent(harness, ready, expected)["mode"] == expected

    harness.brain.tick = failure_tick + 299
    assert only_campaign_intent(harness, reconcile(harness), expected)["mode"] == expected
    harness.brain.tick = failure_tick + 300
    assert only_campaign_intent(
        harness,
        reconcile(harness),
        "route_release",
    )["mode"] == "route_release"


@pytest.mark.parametrize("distance,proven", [(20, True), (20.01, False)])
def test_fixed_probe_quorum_uses_inclusive_twenty_unit_arrival_boundary(
    distance: float,
    proven: bool,
) -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    intent = execute_probe(harness, ready)
    route = path_probe_state(harness)
    destination = route["destination"]
    quorum = int(route["probeQuorum"])
    for token in intent["actorTokens"][:quorum]:
        harness.controller.unitRefs[token].options.position = lua_value(
            harness.lua, [destination[0] + distance, destination[1], destination[2]]
        )
    harness.brain.tick = 161
    current = reconcile(harness)
    intents = campaign_intents(harness, current)

    assert path_probe_state(harness)["probeQuorum"] == quorum
    assert (len(intents) == 1 and intents[0]["mode"] == "route_commit") is proven


def test_probe_membership_and_quorum_never_change_when_reinforcements_arrive() -> None:
    harness, acu, engineer, combat, ready, _ = stage_transition_probe()
    intent = execute_probe(harness, ready)
    frozen = list(intent["actorTokens"])
    quorum = path_probe_state(harness)["probeQuorum"]
    additions = [harness.unit(entityId=88000 + index, blueprintId="uel0201") for index in range(8)]
    put_units(harness, [acu, engineer, *combat, *additions, *[complete_mex(harness, 70200 + i, p) for i, p in enumerate([[45, 2, 35], [55, 2, 45]])]])
    harness.brain.tick = 170
    reconcile(harness)

    route = path_probe_state(harness)
    assert route["probeTokens"] == frozen
    assert route["probeQuorum"] == quorum
    assert all(not token.startswith("880") for token in route["probeTokens"])


@pytest.mark.parametrize("seed", range(4))
def test_probe_selects_only_actors_near_secured_anchor_and_prefers_available_aa(seed: int) -> None:
    harness, acu, engineer, combat, observation = forward_graph_campaign(seed)
    activate_pressure_front(harness, observation)
    field = set(campaign_state(harness)["fieldTokens"])
    field_actors = [actor for actor in combat if f"{int(actor.options.entityId)}:1" in field]
    for actor in field_actors:
        token = f"{int(actor.options.entityId)}:1"
        actor.options.position = lua_value(
            harness.lua,
            SOURCE_ANCHOR
            if token in {
                "1000:1", "2005:1", "2006:1", "2007:1", "2008:1",
                "2009:1", "2010:1", "2011:1", "2012:1",
            }
            else [10, 2, 20],
        )
    mexes = [complete_mex(harness, 70600, [45, 2, 35]), complete_mex(harness, 70601, [55, 2, 45])]
    put_units(harness, [acu, engineer, *combat, *mexes], seed)
    harness.brain.tick = 10
    reconcile(harness)
    configure_route(harness)
    harness.brain.tick = 160
    ready = reconcile(harness)
    probe = only_campaign_intent(harness, ready, "route_probe")

    assert probe["actorTokens"] == ["1000:1", "2005:1", "2006:1", "2007:1"]
    assert path_probe_state(harness)["probeQuorum"] == 2


def test_transition_remains_deferred_when_fewer_than_field_quorum_are_near_anchor() -> None:
    for near_count in [1, 0]:
        harness, acu, engineer, combat, observation = forward_graph_campaign()
        activate_pressure_front(harness, observation)
        field = set(campaign_state(harness)["fieldTokens"])
        field_actors = [actor for actor in combat if f"{int(actor.options.entityId)}:1" in field]
        for index, actor in enumerate(field_actors):
            actor.options.position = lua_value(
                harness.lua, SOURCE_ANCHOR if index < near_count else [10, 2, 20]
            )
        mexes = [complete_mex(harness, 70610, [45, 2, 35]), complete_mex(harness, 70611, [55, 2, 45])]
        put_units(harness, [acu, engineer, *combat, *mexes])
        harness.brain.tick = 10
        reconcile(harness)
        configure_route(harness)
        harness.brain.tick = 160
        ready = reconcile(harness)
        intents = campaign_intents(harness, ready)
        assert intents == []
        assert path_probe_state(harness) == {}


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_stale_probe_actor_generation_fails_before_first_clear_and_replans_survivors(
    mutation: str,
) -> None:
    harness, acu, engineer, combat, ready, before = stage_transition_probe()
    intent = only_campaign_intent(harness, ready, "route_probe")
    token = intent["actorTokens"][0]
    victim = harness.controller.unitRefs[token]
    units = list(harness.brain.units.values())
    if mutation == "dead":
        victim.Dead = True
    elif mutation == "captured":
        victim.options.army = 2
    else:
        replacement = harness.unit(
            entityId=int(victim.options.entityId),
            blueprintId=str(victim.options.blueprintId),
            position=SOURCE_ANCHOR,
        )
        units = [
            replacement
            if int(actor.options.entityId) == int(victim.options.entityId)
            else actor
            for actor in units
        ]
        harness.controller.unitRefs[token] = replacement
    put_units(harness, units)
    clear_before = len(harness.calls.clear)
    execute_intents(harness, [intent], ready)

    assert len(harness.calls.clear) == clear_before
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    harness.brain.tick += 1
    retry_observation = reconcile(harness)
    retry = campaign_intents(harness, retry_observation)
    assert token not in path_probe_state(harness).get("probeTokens", [])
    if retry:
        assert retry[0]["mode"] in {"route_probe", "route_release"}
        assert token not in retry[0]["actorTokens"]


def test_probe_losses_do_not_lower_frozen_quorum_or_admit_replacements() -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    probe = execute_probe(harness, ready)
    route = path_probe_state(harness)
    quorum = int(route["probeQuorum"])
    destination = route["destination"]
    for token in probe["actorTokens"][: quorum - 1]:
        harness.controller.unitRefs[token].options.position = lua_value(harness.lua, destination)
    for token in probe["actorTokens"][quorum - 1 :]:
        harness.controller.unitRefs[token].Dead = True
    harness.brain.tick = 170
    current = reconcile(harness)

    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert path_probe_state(harness).get("probeQuorum") == quorum
    assert all(intent["mode"] != "route_commit" for intent in campaign_intents(harness, current))


@pytest.mark.parametrize("failure", ["clear", "move_1", "move_2", "aggressive"])
def test_bulk_commit_is_atomic_revalidates_probe_arrival_and_retries_every_command_half(
    failure: str,
) -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    proven_observation, commit, frozen = prove_transition(harness, ready)
    route = path_probe_state(harness)
    field = set(campaign_state(harness)["fieldTokens"])
    assert set(commit["actorTokens"]) == field - set(frozen)
    clear_before = len(harness.calls.clear)
    move_before = len(harness.calls.move)
    aggressive_before = len(harness.calls.aggressive)
    if failure == "clear":
        harness.calls.failClearAt = clear_before + 1
    elif failure == "move_1":
        harness.calls.failMoveAt = move_before + 1
    elif failure == "move_2":
        harness.calls.failMoveAt = move_before + 2
    else:
        harness.calls.failAggressiveAt = aggressive_before + 1
    execute_intents(harness, [commit], proven_observation)

    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert path_probe_state(harness)["state"] == "proven"
    harness.calls.failClearAt = None
    harness.calls.failMoveAt = None
    harness.calls.failAggressiveAt = None
    execute_intents(harness, [commit], proven_observation)
    state = campaign_state(harness)
    assert state["clusterKey"] == "forward-near"
    assert state["anchorKey"] == "forward-near-b"
    assert state["kind"] == "pressure_front"
    assert state.get("routeAttempt") is None


def test_quorum_moving_outside_radius_between_policy_and_execute_rejects_bulk_commit() -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    proven_observation, commit, tokens = prove_transition(harness, ready)
    for token in tokens:
        harness.controller.unitRefs[token].options.position = lua_value(harness.lua, SOURCE_ANCHOR)
    harness.observe()
    clear_before = len(harness.calls.clear)

    execute_intents(harness, [commit], proven_observation)

    assert len(harness.calls.clear) == clear_before
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert path_probe_state(harness)["state"] == "proven"


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_stale_non_probe_bulk_actor_fails_before_clear_and_fresh_commit_replans(
    mutation: str,
) -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    proven_observation, commit, frozen = prove_transition(harness, ready)
    token = commit["actorTokens"][0]
    actor = harness.controller.unitRefs[token]
    units = list(harness.brain.units.values())
    if mutation == "dead":
        actor.Dead = True
    elif mutation == "captured":
        actor.options.army = 2
    else:
        replacement = harness.unit(
            entityId=int(actor.options.entityId),
            blueprintId=str(actor.options.blueprintId),
            position=SOURCE_ANCHOR,
        )
        units = [
            replacement
            if int(candidate.options.entityId) == int(actor.options.entityId)
            else candidate
            for candidate in units
        ]
        harness.controller.unitRefs[token] = replacement
    put_units(harness, units)
    clear_before = len(harness.calls.clear)
    execute_intents(harness, [commit], proven_observation)

    assert len(harness.calls.clear) == clear_before
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    harness.brain.tick += 1
    current = reconcile(harness)
    retries = campaign_intents(harness, current)
    assert token not in path_probe_state(harness).get("bulkTokens", [])
    if retries:
        assert retries[0]["mode"] in {"route_commit", "route_release"}
        assert token not in retries[0]["actorTokens"]


@pytest.mark.parametrize("field", ["routeEpoch", "routeKey", "routeFingerprint", "routeSourceKey"])
def test_route_intent_epoch_source_and_fingerprint_tampering_fails_before_commands(field: str) -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    intent = only_campaign_intent(harness, ready, "route_probe")
    tampered = dict(intent)
    value = tampered.get(field)
    tampered[field] = value + 1 if isinstance(value, int) else f"{value}:tampered"
    clear_before = len(harness.calls.clear)

    execute_intents(harness, [tampered], ready)

    assert len(harness.calls.clear) == clear_before
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert path_probe_state(harness)["state"] == "staged"


@pytest.mark.parametrize("mode", ["route_probe", "route_commit"])
@pytest.mark.parametrize("mutation", ["waypoint", "destination", "quorum", "length"])
def test_cached_route_internal_tampering_fails_before_any_command(
    mode: str,
    mutation: str,
) -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    if mode == "route_probe":
        intent = only_campaign_intent(harness, ready, "route_probe")
    else:
        execute_probe(harness, ready)
        move_probe_to_destination(harness)
        harness.brain.tick += 1
        proven = reconcile(harness)
        intent = only_campaign_intent(harness, proven, "route_commit")

    route = harness.controller.fieldCampaign.routeAttempt
    if mutation == "waypoint":
        route.waypoints[1] = lua_value(harness.lua, [63, 63.56, 56])
    elif mutation == "destination":
        destination = plain(route.destination)
        route.destination = lua_value(
            harness.lua,
            [destination[0] + 1, destination[1], destination[2]],
        )
    elif mutation == "quorum":
        route.probeQuorum = 1
    else:
        route.routeLength = route.routeLength + 1
    clear_before = len(harness.calls.clear)
    aggressive_before = len(harness.calls.aggressive)

    execute_intents(harness, [intent], ready if mode == "route_probe" else proven)

    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.aggressive) == aggressive_before
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]


@pytest.mark.parametrize("mode", ["route_probe", "route_release"])
@pytest.mark.parametrize(
    "field",
    ["objectiveKey", "objectivePosition", "state", "lastSecuredAnchorPosition"],
)
def test_cached_secured_snapshot_tampering_fails_before_probe_or_release_command(
    mode: str,
    field: str,
) -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    if mode == "route_probe":
        observation = ready
        intent = only_campaign_intent(harness, observation, "route_probe")
    else:
        execute_probe(harness, ready)
        harness.brain.tick = 460
        observation = reconcile(harness)
        intent = only_campaign_intent(harness, observation, "route_release")
    source = harness.controller.fieldCampaign.routeAttempt.source
    if field in {"objectivePosition", "lastSecuredAnchorPosition"}:
        setattr(source, field, lua_value(harness.lua, [999, 2, 999]))
    elif field == "state":
        source.state = "rebuilding"
    else:
        source.objectiveKey = "tampered"
    clear_before = len(harness.calls.clear)
    aggressive_before = len(harness.calls.aggressive)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.aggressive) == aggressive_before
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]


def test_release_uses_sealed_source_position_when_terrain_adapter_changes_after_policy() -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    execute_probe(harness, ready)
    harness.brain.tick = 460
    observation = reconcile(harness)
    release = only_campaign_intent(harness, observation, "route_release")
    sealed = plain(harness.controller.fieldCampaign.routeAttempt.sourcePosition)
    harness.lua.execute("GetTerrainHeight = function(x, z) return 999 end")

    execute_intents(harness, [release], observation)

    assert plain(calls(harness.calls.aggressive)[-1].position) == sealed


@pytest.mark.parametrize("mode", ["transition", "assault"])
def test_route_candidate_position_or_reachability_flip_before_probe_fails_toctou(mode: str) -> None:
    if mode == "transition":
        harness, _, _, _, ready, before = stage_transition_probe()
        intent = only_campaign_intent(harness, ready, "route_probe")
        marker = next(
            site for site in harness.controller.markers.mass.values()
            if site.key == "forward-near-b"
        )
        original = plain(marker.position)
        marker.position = lua_value(harness.lua, [81, 2, 70])
    else:
        harness, _, _, _, ready, before = stage_assault_probe()
        intent = only_campaign_intent(harness, ready, "route_probe")
        original = plain(harness.controller.targetPosition)
        harness.controller.targetPath = False
    harness.observe()
    clear_before = len(harness.calls.clear)
    execute_intents(harness, [intent], ready)

    assert len(harness.calls.clear) == clear_before
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    if mode == "transition":
        marker.position = lua_value(harness.lua, original)
    else:
        harness.controller.targetPath = True


@pytest.mark.parametrize("tick,expected", [(459, "probing"), (460, "releasing")])
def test_probe_no_progress_enters_releasing_at_exact_three_hundred_ticks(
    tick: int,
    expected: str,
) -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    execute_probe(harness, ready)
    harness.brain.tick = tick
    current = reconcile(harness)

    assert path_probe_state(harness)["state"] == expected
    intents = campaign_intents(harness, current)
    if expected == "releasing":
        assert len(intents) == 1 and intents[0]["mode"] == "route_release"
    else:
        assert intents == []


def test_meaningful_probe_progress_resets_stuck_clock_without_changing_membership() -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    intent = execute_probe(harness, ready)
    frozen = list(path_probe_state(harness)["probeTokens"])
    for tick, x in [(300, 60), (500, 63), (700, 65)]:
        for token in intent["actorTokens"]:
            harness.controller.unitRefs[token].options.position = lua_value(
                harness.lua, [x, 2, x - 10]
            )
        harness.brain.tick = tick
        assert campaign_intents(harness, reconcile(harness)) == []
        assert path_probe_state(harness)["state"] == "probing"
        assert path_probe_state(harness)["probeTokens"] == frozen


def test_release_cleanup_failure_retains_attempt_then_logically_expires_by_six_hundred() -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    execute_probe(harness, ready)
    harness.brain.tick = 460
    releasing_observation = reconcile(harness)
    release = only_campaign_intent(harness, releasing_observation, "route_release")
    harness.calls.failClear = True
    execute_intents(harness, [release], releasing_observation)
    assert path_probe_state(harness)["state"] == "releasing"
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]

    harness.brain.tick = 760
    expired = reconcile(harness)
    assert path_probe_state(harness) == {}
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert campaign_state(harness)["state"] != "rebuilding"
    assert all(intent.get("mode") != "route_release" for intent in campaign_intents(harness, expired))


def test_successful_release_returns_live_probe_to_source_and_selects_deterministic_alternate() -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    execute_probe(harness, ready)
    harness.brain.tick = 460
    releasing_observation = reconcile(harness)
    release = only_campaign_intent(harness, releasing_observation, "route_release")
    execute_intents(harness, [release], releasing_observation)

    assert plain(harness.calls.sequence)[-2:] == ["clear", "aggressive"]
    assert plain(calls(harness.calls.aggressive)[-1].position)[0::2] == SOURCE_ANCHOR[0::2]
    assert path_probe_state(harness) == {}
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    harness.calls.canPathMode = "true"
    configure_route(harness, [[95, 95.85, 85]], count=1, length=90)
    harness.brain.tick = 461
    alternate = reconcile(harness)
    intent = only_campaign_intent(harness, alternate, "route_probe")
    assert intent["clusterKey"] == "forward-far"


def test_probe_attrition_blocks_failed_destination_and_selects_live_alternate() -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    probe = execute_probe(harness, ready)
    additions = [
        harness.unit(
            entityId=88100 + index,
            blueprintId="uel0104" if index < 2 else "uel0201",
            position=SOURCE_ANCHOR,
        )
        for index in range(8)
    ]
    put_units(harness, [*list(harness.brain.units.values()), *additions])
    for token in probe["actorTokens"][:3]:
        harness.controller.unitRefs[token].Dead = True

    harness.brain.tick = 161
    releasing_observation = reconcile(harness)
    release = only_campaign_intent(harness, releasing_observation, "route_release")

    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert campaign_state(harness).get("routeBlockedCount", 0) == 1
    route_blocks = campaign_state(harness)["routeBlocks"]
    block = next(iter(route_blocks.values()))
    assert block["untilTick"] == 3761
    execute_intents(harness, [release], releasing_observation)

    configure_route(harness, [[95, 95.85, 85]], count=1, length=90)
    harness.brain.tick = 461
    reconcile(harness)
    harness.brain.tick = 462
    alternate = reconcile(harness)
    intent = only_campaign_intent(harness, alternate, "route_probe")
    assert intent["clusterKey"] == "forward-far"


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_release_prunes_stale_generation_reseals_and_cleans_remaining_exact_actors(
    mutation: str,
) -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    execute_probe(harness, ready)
    harness.brain.tick = 460
    releasing = reconcile(harness)
    stale = only_campaign_intent(harness, releasing, "route_release")
    token = stale["actorTokens"][0]
    actor = harness.controller.unitRefs[token]
    replacement_token = None
    units = list(harness.brain.units.values())
    if mutation == "dead":
        actor.Dead = True
    elif mutation == "captured":
        actor.options.army = 2
    else:
        replacement = harness.unit(
            entityId=int(actor.options.entityId),
            blueprintId=str(actor.options.blueprintId),
            position=SOURCE_ANCHOR,
        )
        units = [
            replacement
            if int(candidate.options.entityId) == int(actor.options.entityId)
            else candidate
            for candidate in units
        ]
        put_units(harness, units)
        harness.observe()
        replacement_token = f"{int(actor.options.entityId)}:2"
    clear_before = len(harness.calls.clear)
    execute_intents(harness, [stale], releasing)
    assert len(harness.calls.clear) == clear_before

    harness.brain.tick = 461
    current = reconcile(harness)
    fresh = only_campaign_intent(harness, current, "route_release")
    assert token not in fresh["actorTokens"]
    if replacement_token:
        assert replacement_token not in fresh["actorTokens"]
    execute_intents(harness, [fresh], current)

    assert path_probe_state(harness) == {}
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]


def test_block_key_is_cluster_scoped_so_sibling_member_cannot_evade_and_cooldown_expires() -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    execute_probe(harness, ready)
    harness.brain.tick = 460
    release_observation = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, release_observation), release_observation)
    configure_route(harness, [[95, 95.85, 85]], count=1, length=90)
    harness.brain.tick = 1059
    blocked = reconcile(harness)
    intent = only_campaign_intent(harness, blocked, "route_probe")
    assert intent["clusterKey"] != "forward-near"
    harness.controller.fieldCampaign.routeAttempt = None
    harness.controller.fieldCampaign.pendingMode = None
    harness.controller.fieldCampaign.pendingTokens = harness.lua.table()
    configure_route(harness)
    harness.brain.tick = 1060
    retried = reconcile(harness)
    assert only_campaign_intent(harness, retried, "route_probe")["clusterKey"] == "forward-near"


@pytest.mark.parametrize("phase", ["staged", "probing", "proven", "releasing"])
@pytest.mark.parametrize("emergency", ["health", "home_reserve"])
def test_emergency_recall_cancels_uncommitted_route_phase_without_new_topology_poison(
    emergency: str,
    phase: str,
) -> None:
    harness, acu, _, _, ready, before = stage_transition_probe()
    if phase != "staged":
        probe = execute_probe(harness, ready)
        if phase == "proven":
            route = path_probe_state(harness)
            for token in probe["actorTokens"][: route["probeQuorum"]]:
                harness.controller.unitRefs[token].options.position = lua_value(
                    harness.lua, route["destination"]
                )
            harness.brain.tick = 161
            reconcile(harness)
        elif phase == "releasing":
            harness.brain.tick = 460
            reconcile(harness)
    blocked_before = campaign_state(harness).get("routeBlockedCount", 0)
    if emergency == "health":
        acu.options.health = 69
    else:
        for token in before["homeTokens"]:
            harness.controller.unitRefs[token].Dead = True
        enemy = harness.unit(entityId=99001, blueprintId="uel0201", army=2, position=[15, 2, 20])
        harness.brain.enemies = harness.lua.table_from([enemy])
    harness.brain.tick = 170
    recalled_observation = reconcile(harness)
    recall = only_campaign_intent(harness, recalled_observation, "recall")

    assert path_probe_state(harness) == {}
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    assert campaign_state(harness).get("routeBlockedCount", 0) == blocked_before
    execute_intents(harness, [recall], recalled_observation)
    assert campaign_state(harness)["state"] == "recalled"


def commit_route_before_bulk_arrival(
    kind: str,
    seed: int = 0,
) -> tuple[Any, Any, list[Any], dict[str, Any]]:
    if kind == "transition":
        harness, acu, _, combat, ready, before = stage_transition_probe(seed)
    else:
        harness, acu, _, combat, ready, before = stage_assault_probe(seed)
    proven, commit, _ = prove_transition(harness, ready)
    execute_intents(harness, [commit], proven)
    assert campaign_state(harness).get("routeRollback") is not None
    return harness, acu, combat, before


def stage_postcommit_release(
    kind: str,
    seed: int = 0,
) -> tuple[Any, Any, list[Any], dict[str, Any], dict[str, Any]]:
    harness, acu, combat, before = commit_route_before_bulk_arrival(kind, seed)
    committed = campaign_state(harness)
    harness.brain.tick += 300
    releasing = reconcile(harness)
    only_campaign_intent(harness, releasing, "route_release")
    assert path_probe_state(harness)["state"] == "releasing"
    assert path_probe_state(harness)["restoreOnRelease"] is True
    assert campaign_state(harness).get("routeRollback") is None
    return harness, acu, combat, before, committed


@pytest.mark.parametrize("seed", range(2))
@pytest.mark.parametrize("kind", ["transition", "assault"])
@pytest.mark.parametrize("emergency", ["health", "home_reserve"])
def test_full_bulk_arrival_is_committed_before_same_tick_emergency_recall(
    emergency: str,
    kind: str,
    seed: int,
) -> None:
    harness, acu, combat, before = commit_route_before_bulk_arrival(kind, seed)
    committed = campaign_state(harness)
    position_field_at(harness, combat, committed["anchorPosition"])
    if emergency == "health":
        acu.options.health = 69
    else:
        for token in before["homeTokens"]:
            harness.controller.unitRefs[token].Dead = True
        harness.brain.enemies = harness.lua.table_from(
            [harness.unit(entityId=99200 + seed, blueprintId="uel0201", army=2, position=[15, 2, 20])]
        )

    harness.brain.tick += 1
    current = reconcile(harness)
    only_campaign_intent(harness, current, "recall")
    state = campaign_state(harness)

    assert state["fieldAtAnchor"] >= state["arrivalQuorum"]
    assert state["anchorKey"] == committed["anchorKey"]
    assert state["anchorPosition"] == committed["anchorPosition"]
    assert state["anchorKey"] != before["anchorKey"]
    assert state.get("routeRollback") is None


@pytest.mark.parametrize("seed", range(2))
@pytest.mark.parametrize("kind", ["transition", "assault"])
@pytest.mark.parametrize("interruption", ["health", "home_reserve", "field_attrition"])
def test_postcommit_releasing_interruption_restores_secured_source_before_new_action(
    interruption: str,
    kind: str,
    seed: int,
) -> None:
    harness, acu, _, before, committed = stage_postcommit_release(kind, seed)
    if interruption == "health":
        acu.options.health = 69
    elif interruption == "home_reserve":
        for token in before["homeTokens"]:
            harness.controller.unitRefs[token].Dead = True
        harness.brain.enemies = harness.lua.table_from(
            [harness.unit(entityId=99300 + seed, blueprintId="uel0201", army=2, position=[15, 2, 20])]
        )
    else:
        for token in committed["fieldTokens"][:5]:
            harness.controller.unitRefs[token].Dead = True

    harness.brain.tick += 1
    current = reconcile(harness)
    mode = "rollback" if interruption == "field_attrition" else "recall"
    intent = only_campaign_intent(harness, current, mode)
    state = campaign_state(harness)

    assert path_probe_state(harness) == {}
    assert state["kind"] == before["kind"]
    assert state["clusterKey"] == before["clusterKey"]
    assert state["anchorKey"] == before["anchorKey"]
    assert state["anchorPosition"] == before["anchorPosition"]
    if mode == "rollback":
        assert intent["position"] == before["anchorPosition"]


@pytest.mark.parametrize("kind", ["transition", "assault"])
def test_postcommit_bulk_release_reuses_original_sealed_source_position(
    kind: str,
) -> None:
    if kind == "transition":
        harness, _, _, _, ready, _ = stage_transition_probe()
    else:
        harness, _, _, _, ready, _ = stage_assault_probe()
    sealed_source = plain(path_probe_state(harness)["sourcePosition"])
    proven, commit, _ = prove_transition(harness, ready)
    execute_intents(harness, [commit], proven)
    harness.lua.execute("GetTerrainHeight = function(x, z) return 999 end")
    harness.brain.tick += 300
    releasing = reconcile(harness)
    release = only_campaign_intent(harness, releasing, "route_release")
    execute_intents(harness, [release], releasing)

    assert plain(calls(harness.calls.aggressive)[-1].position) == sealed_source


@pytest.mark.parametrize("seed", range(2))
@pytest.mark.parametrize("kind", ["transition", "assault"])
@pytest.mark.parametrize("emergency", ["health", "home_reserve"])
def test_post_commit_emergency_restores_secured_source_before_recall_without_poison(
    emergency: str,
    kind: str,
    seed: int,
) -> None:
    harness, acu, _, before = commit_route_before_bulk_arrival(kind, seed)
    blocked_before = campaign_state(harness).get("routeBlockedCount", 0)
    if emergency == "health":
        acu.options.health = 69
    else:
        for token in before["homeTokens"]:
            harness.controller.unitRefs[token].Dead = True
        harness.brain.enemies = harness.lua.table_from(
            [harness.unit(entityId=99100 + seed, blueprintId="uel0201", army=2, position=[15, 2, 20])]
        )
    harness.brain.tick += 1
    current = reconcile(harness)
    recall = only_campaign_intent(harness, current, "recall")
    restored = campaign_state(harness)

    assert restored["kind"] == before["kind"]
    assert restored["clusterKey"] == before["clusterKey"]
    assert restored["anchorKey"] == before["anchorKey"]
    assert restored["anchorPosition"] == before["anchorPosition"]
    assert restored.get("routeRollback") is None
    assert restored.get("routeBlockedCount", 0) == blocked_before
    execute_intents(harness, [recall], current)
    assert campaign_state(harness)["state"] == "recalled"

    if emergency == "health":
        acu.options.health = 75
        harness.brain.tick += 1
        reconcile(harness)
        harness.brain.tick += 300
        resumed = reconcile(harness)
        resume = only_campaign_intent(harness, resumed, "resume")
        assert resume["position"] == before["anchorPosition"]


@pytest.mark.parametrize("seed", range(2))
@pytest.mark.parametrize("kind", ["transition", "assault"])
def test_post_commit_field_attrition_restores_secured_source_before_rebuilding(
    kind: str,
    seed: int,
) -> None:
    harness, _, _, before = commit_route_before_bulk_arrival(kind, seed)
    committed = campaign_state(harness)
    for token in committed["fieldTokens"][:5]:
        harness.controller.unitRefs[token].Dead = True
    harness.brain.tick += 1
    current = reconcile(harness)
    rollback = only_campaign_intent(harness, current, "rollback")
    restored = campaign_state(harness)

    assert restored["kind"] == before["kind"]
    assert restored["clusterKey"] == before["clusterKey"]
    assert restored["anchorKey"] == before["anchorKey"]
    assert restored["anchorPosition"] == before["anchorPosition"]
    assert rollback["position"] == before["anchorPosition"]
    assert restored.get("routeRollback") is None
    assert restored.get("routeBlockedCount", 0) == 0
    execute_intents(harness, [rollback], current)
    rebuilt = campaign_state(harness)
    assert rebuilt["state"] == "rebuilding"
    assert rebuilt["clusterKey"] == before["clusterKey"]
    assert rebuilt["anchorKey"] == before["anchorKey"]


def test_readiness_loss_cancels_probe_without_block_and_restoration_stages_fresh_attempt() -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    stale = only_campaign_intent(harness, ready, "route_probe")
    harness.brain.supportUnits = harness.lua.table_from([])
    harness.brain.tick = 161
    blocked = reconcile(harness)

    assert blocked.macro.campaignReady is False
    assert campaign_intents(harness, blocked) == []
    assert path_probe_state(harness) == {}
    assert campaign_state(harness).get("routeBlockedCount", 0) == 0
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]
    clear_before = len(harness.calls.clear)
    execute_intents(harness, [stale], ready)
    assert len(harness.calls.clear) == clear_before

    support = [
        harness.unit(entityId=73000 + index, blueprintId="ueb1103")
        for index in range(8)
    ] + [
        harness.unit(entityId=73100 + index, blueprintId="ueb0101", idleState=False, states={"Building": True})
        for index in range(3)
    ]
    harness.brain.supportUnits = harness.lua.table_from(support)
    configure_route(harness)
    harness.brain.tick = 162
    restored = reconcile(harness)
    fresh = only_campaign_intent(harness, restored, "route_probe")
    assert fresh["routeEpoch"] != stale["routeEpoch"]


def test_malformed_route_attempt_state_and_duplicate_probe_tokens_fail_closed() -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    intent = only_campaign_intent(harness, ready, "route_probe")
    clear_before = len(harness.calls.clear)
    for malformed in [17, True, "bad"]:
        harness.controller.fieldCampaign.routeAttempt = malformed
        execute_intents(harness, [intent], ready)
        assert len(harness.calls.clear) == clear_before
        assert campaign_state(harness)["anchorKey"] == before["anchorKey"]

    harness, _, _, _, ready, before = stage_transition_probe()
    intent = only_campaign_intent(harness, ready, "route_probe")
    duplicate = dict(intent)
    duplicate["actorTokens"] = [intent["actorTokens"][0], intent["actorTokens"][0]]
    clear_before = len(harness.calls.clear)
    execute_intents(harness, [duplicate], ready)
    assert len(harness.calls.clear) == clear_before
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]


def test_terminal_assault_uses_same_probe_before_commit_and_never_orders_home_or_acu() -> None:
    harness, _, _, _, ready, before = stage_assault_probe()
    probe = execute_probe(harness, ready)
    assert campaign_state(harness)["kind"] == before["kind"] == "pressure_front"
    assert path_probe_state(harness)["candidateKind"] == "strategic_assault"
    assert "1:1" not in probe["actorTokens"]
    assert set(probe["actorTokens"]).isdisjoint(before["homeTokens"])

    route = path_probe_state(harness)
    for token in probe["actorTokens"][: route["probeQuorum"]]:
        harness.controller.unitRefs[token].options.position = lua_value(harness.lua, route["destination"])
    harness.brain.tick = 161
    proven = reconcile(harness)
    commit = only_campaign_intent(harness, proven, "route_commit")
    execute_intents(harness, [commit], proven)
    state = campaign_state(harness)
    assert state["kind"] == "strategic_assault"
    assert state["anchorKey"] == "target:ARMY_2"
    assert state["anchorPosition"] == [110, 3, 120]


@pytest.mark.parametrize("invalid", ["path_false", "target_mutated", "spawn_random", "target_nan"])
def test_terminal_probe_fails_closed_for_hidden_or_stale_public_target(invalid: str) -> None:
    harness, _, _, _, ready, before = stage_assault_probe()
    if invalid == "path_false":
        harness.controller.targetPath = False
    elif invalid == "target_mutated":
        harness.controller.targetPosition = lua_value(harness.lua, [111, 3, 120])
    elif invalid == "spawn_random":
        harness.lua.globals().ScenarioInfo.Options.TeamSpawn = "random"
    else:
        harness.controller.targetPosition = lua_value(harness.lua, [float("nan"), 3, 120])
    harness.observe()
    clear_before = len(harness.calls.clear)
    execute_intents(harness, campaign_intents(harness, ready), ready)

    assert len(harness.calls.clear) == clear_before
    assert campaign_state(harness)["kind"] == before["kind"]
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]


def test_post_proof_bulk_stall_retires_failed_campaign_for_regional_force_fallback() -> None:
    harness, _, _, _, ready, before = stage_transition_probe()
    proven, commit, _ = prove_transition(harness, ready)
    execute_intents(harness, [commit], proven)
    assert campaign_state(harness)["anchorKey"] == "forward-near-b"
    harness.brain.tick = 461
    releasing = reconcile(harness)
    release = only_campaign_intent(harness, releasing, "route_release")
    execute_intents(harness, [release], releasing)

    assert plain(harness.controller.fieldCampaign) is None
    assert harness.controller.fieldCampaignEnabled is False
    assert route_events(harness, "campaign_retired")


def test_ian_mass277_to_mass490_stall_never_commits_or_whole_field_orders_before_probe_quorum() -> None:
    harness, acu, engineer, combat, observation = start_campaign(
        site_key="Mass:277500:295500",
        cluster_key="Mass:277500:295500",
        position=[277.5, 28.9648, 295.5],
        extra_markers=[
            layered_marker("Mass:279500:311500", 279.5, 311.5),
            layered_marker("Mass:292500:298500", 292.5, 298.5),
            layered_marker("Mass:490500:263500", 490.5, 263.5),
            layered_marker("Mass:492500:248500", 492.5, 248.5),
        ],
        target_position=[915.5, 30.3613, 935.5],
        target_name="ARMY_2",
    )
    activate_pressure_front(harness, observation)
    old = campaign_state(harness)
    mexes = [
        complete_mex(harness, 71000, [277.5, 28.9648, 295.5]),
        complete_mex(harness, 71001, [279.5, 28.8027, 311.5]),
        complete_mex(harness, 71002, [292.5, 29, 298.5]),
    ]
    position_field_at(harness, combat, old["anchorPosition"])
    put_units(harness, [acu, engineer, *combat, *mexes])
    harness.brain.tick = 5854
    reconcile(harness)
    configure_route(
        harness,
        [[380, 40, 285], [490.5, 53.543, 263.5]],
        count=2,
        length=217,
    )
    harness.brain.tick = 6004
    staged = reconcile(harness)
    probe = execute_probe(harness, staged)

    assert path_probe_state(harness)["candidateAnchorKey"] == "Mass:490500:263500"
    assert campaign_state(harness)["anchorKey"] == "Mass:279500:311500"
    assert len(probe["actorTokens"]) <= 4
    assert len(harness.calls.clear) == 2
    assert campaign_state(harness)["fullFieldOrders"] == 1
    harness.brain.tick = 6303
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 6304
    assert only_campaign_intent(harness, reconcile(harness), "route_release")
    assert campaign_state(harness)["state"] != "rebuilding"


def test_route_probe_is_deterministic_across_marker_and_unit_permutations() -> None:
    results = []
    for seed in range(8):
        harness, _, _, _, ready, _ = stage_transition_probe(seed)
        intent = only_campaign_intent(harness, ready, "route_probe")
        route = path_probe_state(harness)
        results.append(
            (
                intent["clusterKey"],
                intent["objectiveKey"],
                tuple(intent["actorTokens"]),
                route["routeFingerprint"],
            )
        )
    assert results == [results[0]] * len(results)


def test_route_probe_telemetry_is_scalar_low_volume_and_emits_semantic_events() -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    execute_probe(harness, ready)
    macro = plain(reconcile(harness).macro)
    required = {
        "campaignRouteState",
        "campaignRouteSource",
        "campaignRouteDestination",
        "campaignRouteProbeUnits",
        "campaignRouteProbeQuorum",
        "campaignRouteAtDestination",
        "campaignRouteAge",
        "campaignRouteLastProgressTick",
        "campaignRouteBlockedCount",
        "campaignRouteEpoch",
        "campaignRouteKey",
        "campaignRouteFingerprint",
        "campaignRouteWaypointCount",
        "campaignRouteLength",
        "campaignRouteProgressAge",
        "campaignRouteReleaseAge",
        "campaignRouteLastFailure",
    }
    assert required <= set(macro)
    for key in required:
        assert not isinstance(macro[key], (list, dict))
    assert route_events(harness, "campaign_route_staged")
    assert route_events(harness, "campaign_route_probe")
    serialized = "\n".join(harness.logs)
    assert "waypoints=[" not in serialized
    assert "probe_tokens=" not in serialized


def test_serialized_route_events_and_snapshot_correlate_one_cached_route_without_arrays() -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    route = path_probe_state(harness)
    expected_epoch = str(route["epoch"])
    expected_fingerprint = str(route["routeFingerprint"])
    harness.lua.globals().Controller.Step(harness.controller)
    move_probe_to_destination(harness)
    harness.brain.tick = 161
    harness.lua.globals().Controller.Step(harness.controller)

    event_names = [
        "campaign_route_staged",
        "campaign_route_probe",
        "campaign_route_proven",
        "campaign_route_committed",
    ]
    for name in event_names:
        fields = telemetry_fields(route_events(harness, name)[-1])
        assert fields["epoch"] == expected_epoch
        assert fields["fingerprint"] == expected_fingerprint
        assert int(fields["waypoints"]) == len(NORMAL_ROUTE)
        assert float(fields["route_length"]) > 0
    snapshot = telemetry_fields(
        next(line for line in harness.logs if "event=snapshot" in line)
    )
    assert snapshot["route_epoch"] == expected_epoch
    assert snapshot["route_fingerprint"] == expected_fingerprint
    assert int(snapshot["route_waypoints"]) == len(NORMAL_ROUTE)
    assert float(snapshot["route_length"]) > 0
    assert int(snapshot["route_progress_age"]) >= 0
    assert snapshot["route_release_age"] == "-1"
    assert snapshot["route_last_failure"] == "none"
    serialized = "\n".join(harness.logs)
    assert "probe_tokens=" not in serialized
    assert "waypoints=[" not in serialized


def test_serialized_release_snapshot_exposes_failure_and_bounded_release_age() -> None:
    harness, _, _, _, ready, _ = stage_transition_probe()
    intent = only_campaign_intent(harness, ready, "route_probe")
    harness.calls.failClear = True
    execute_intents(harness, [intent], ready)
    harness.brain.tick = 460
    reconcile(harness)
    harness.controller.lastSnapshotTick = 160
    harness.lua.globals().Controller.Step(harness.controller)

    snapshot = telemetry_fields(
        [line for line in harness.logs if "event=snapshot" in line][-1]
    )
    assert snapshot["route_state"] == "releasing"
    assert int(snapshot["route_release_age"]) >= 0
    assert snapshot["route_last_failure"] in {"clear", "release_clear"}
    releasing = telemetry_fields(route_events(harness, "campaign_route_releasing")[-1])
    assert releasing["reason"] == "probe_dispatch_stuck"
    assert int(releasing["release_age"]) >= 0


def test_route_planning_keeps_one_enemy_observation_query_and_one_path_query_at_scale() -> None:
    harness, acu, engineer, combat, observation = forward_graph_campaign()
    activate_pressure_front(harness, observation)
    additions = [harness.unit(entityId=72000 + index, blueprintId="uel0201") for index in range(976)]
    # Keep structure entity ids outside the 72,000..72,975 combat range so the
    # scale fixture does not accidentally manufacture recycled combat tokens.
    mexes = [complete_mex(harness, 90000, [45, 2, 35]), complete_mex(harness, 90001, [55, 2, 45])]
    position_field_at(harness, combat, SOURCE_ANCHOR)
    for actor in additions:
        actor.options.position = lua_value(harness.lua, SOURCE_ANCHOR)
    put_units(harness, [acu, engineer, *combat, *additions, *mexes], seed=11)
    harness.brain.tick = 10
    grown = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, grown), grown)
    reconcile(harness)
    configure_route(harness)
    enemy_before = len(harness.calls.enemy)
    harness.brain.tick = 160
    current = reconcile(harness)

    intent = only_campaign_intent(harness, current, "route_probe")
    assert len(intent["actorTokens"]) <= 4
    assert len(harness.calls.navPath) == 1
    assert len(harness.calls.enemy) == enemy_before + 1


def test_route_static_contract_is_land_only_bounded_and_adds_no_threat_or_enemy_intel() -> None:
    controller = source("lua/AI/Overmind4/Controller.lua")
    policy = source("lua/AI/Overmind4/Policy.lua")
    route_region = controller.split("ESCALATION.Route", 1)[1].split("Controller = {}", 1)[0]
    assert re.search(r"PathTo\s*\(\s*'Land'", route_region)
    assert "DetailedPathTo" not in route_region
    assert "GetThreat" not in route_region
    assert "GetBlueprint" not in route_region
    assert "GetArmy" not in route_region
    assert "GetUnitsAroundPoint" not in route_region
    assert "IssueGuard" not in route_region
    assert "routeWaypoints" not in policy
    top_level_locals = re.findall(r"(?m)^local\s+(?:function\s+)?[A-Za-z_]", controller)
    assert len(top_level_locals) <= 195
