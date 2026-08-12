from __future__ import annotations

import itertools
import random
import re
from typing import Any

import pytest

from conftest import source
from test_controller import execute_intents
from test_field_campaign import (
    actor_tokens_from_call,
    assert_campaign_cohort_indexes,
    campaign_intents,
    expected_initial_cohorts,
    layered_marker,
    policy_intents,
    reconcile,
    start_campaign,
)
from test_policy import lua_value, plain
from test_secured_frontier_doctrine import marker


def campaign_state(harness: Any) -> dict[str, Any]:
    return plain(harness.controller.fieldCampaign)


def activate_pressure_front(harness: Any, observation: Any) -> dict[str, Any]:
    intents = campaign_intents(harness, observation)
    assert len(intents) == 1
    assert intents[0].get("mode") == "activate"
    execute_intents(harness, intents, observation)
    return intents[0]


def aggressive_position(harness: Any, index: int = -1) -> list[float]:
    calls = list(harness.calls.aggressive.values())
    assert calls
    return plain(calls[index].position)


def test_live_director_regional_expansion_starts_pressure_front() -> None:
    harness, _, _, _, observation = start_campaign(
        reason="regional_expansion",
        site_key="front-a",
        cluster_key="front-a",
        position=[70, 2, 40],
        extra_markers=[layered_marker("front-b", 80, 50)],
    )

    assert harness.controller.fieldCampaign is not None
    assert campaign_state(harness)["kind"] == "pressure_front"
    assert len(campaign_intents(harness, observation)) == 1


def test_pressure_front_executes_when_force_director_owns_home_reserve() -> None:
    harness, _, _, _, _ = start_campaign(
        reason="regional_expansion",
        site_key="front-a",
        cluster_key="front-a",
        position=[70, 2, 40],
        extra_markers=[layered_marker("front-b", 80, 50)],
    )
    home = campaign_state(harness)["homeTokens"]
    harness.lua.globals().directorResults.macroPlan = lua_value(
        harness.lua,
        {
            "valid": True,
            "epoch": 1,
            "lanes": {},
            "regions": [
                {
                    "key": "front-a",
                    "state": "secured",
                    "position": [70, 2, 40],
                    "productionAnchor": True,
                }
            ],
            "intents": [],
        },
    )
    harness.lua.globals().directorResults.forcePlan = lua_value(
        harness.lua,
        {
            "epoch": 1,
            "assignments": {
                "home": [],
                "garrison": [],
                "field": home,
                "response": [],
                "raider": [],
                "unassigned": [],
            },
            "ownershipByToken": {token: "field" for token in home},
            "regionAssignments": {},
            "ratios": {},
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    force_input = plain(harness.calls.forceAssign[1])
    assert sorted(unit["token"] for unit in force_input["units"]) == home
    assert plain(harness.controller.forcePlan)["ownershipByToken"]
    assert campaign_state(harness)["state"] == "active"
    assert len(harness.calls.aggressive) == 1

    harness.brain.tick += 1
    harness.lua.globals().Controller.Step(harness.controller)

    assert campaign_state(harness)["state"] == "active"
    assert len(harness.calls.aggressive) == 1


def put_units(harness: Any, units: list[Any], seed: int = 0) -> None:
    shuffled = list(units)
    random.Random(seed).shuffle(shuffled)
    harness.brain.units = harness.lua.table_from(shuffled)


def complete_mex(harness: Any, entity_id: int, position: list[float]) -> Any:
    return harness.unit(
        entityId=entity_id,
        blueprintId="ueb1103",
        position=position,
    )


def position_field_at(harness: Any, combat: list[Any], position: list[float]) -> None:
    field = set(campaign_state(harness)["fieldTokens"])
    for actor in combat:
        token = f"{int(actor.options.entityId)}:1"
        if token in field:
            actor.options.position = lua_value(harness.lua, position)


def hold_cluster(
    harness: Any,
    acu: Any,
    engineer: Any,
    combat: list[Any],
    mexes: list[Any],
    *,
    start_tick: int = 10,
) -> Any:
    position_field_at(harness, combat, campaign_state(harness)["anchorPosition"])
    put_units(harness, [acu, engineer, *combat, *mexes])
    harness.brain.tick = start_tick
    return reconcile(harness)


def complete_staged_route(harness: Any, observation: Any) -> Any:
    """Physically prove a staged route, then execute its bulk commit."""
    probe = campaign_intents(harness, observation)
    assert len(probe) == 1 and probe[0]["mode"] == "route_probe"
    execute_intents(harness, probe, observation)
    route = campaign_state(harness)["routeAttempt"]
    for token in route["probeTokens"][: route["probeQuorum"]]:
        harness.controller.unitRefs[token].options.position = lua_value(
            harness.lua, route["destination"]
        )
    harness.brain.tick += 1
    proven = reconcile(harness)
    commit = campaign_intents(harness, proven)
    assert len(commit) == 1 and commit[0]["mode"] == "route_commit"
    execute_intents(harness, commit, proven)
    return proven


@pytest.mark.parametrize("seed", range(4))
def test_activation_snapshots_targetward_cluster_anchor_and_aggressive_moves_exact_field(seed: int) -> None:
    harness, _, engineer, _, observation = start_campaign(
        seed=seed,
        site_key="front-a",
        cluster_key="front-a",
        position=[70, 2, 40],
        extra_markers=[
            layered_marker("front-b", 80, 50),
            layered_marker("front-c", 76, 46),
        ],
    )
    expected_field, expected_home = expected_initial_cohorts(24, 2)

    intent = activate_pressure_front(harness, observation)
    state = campaign_state(harness)

    assert state["kind"] == "pressure_front"
    assert state["anchorKey"] == "front-b"
    assert state["anchorPosition"] == [80, 2, 50]
    assert state["memberKeys"] == ["front-a", "front-b", "front-c"]
    assert intent["actorTokens"] == expected_field
    assert intent.get("engineerToken") is None
    assert plain(harness.calls.sequence) == ["clear", "aggressive"]
    assert actor_tokens_from_call(harness.calls.clear[1]) == expected_field
    assert actor_tokens_from_call(harness.calls.aggressive[1]) == expected_field
    assert aggressive_position(harness) == [80, 80.5, 50]
    assert len(harness.calls.guard) == 0
    assert "1:1" not in expected_field
    assert "2:1" not in expected_field
    assert set(expected_field).isdisjoint(expected_home)
    assert engineer.options.entityId == 2


def test_anchor_tie_is_permutation_stable_by_site_key() -> None:
    anchors = []
    for seed, members in enumerate(
        itertools.permutations(
            [
                layered_marker("front-b", 80, 100),
                layered_marker("front-c", 90, 90),
            ]
        )
    ):
        harness, _, _, _, observation = start_campaign(
            seed=seed,
            site_key="front-a",
            cluster_key="front-a",
            position=[80, 2, 85],
            extra_markers=list(members),
        )
        activate_pressure_front(harness, observation)
        anchors.append((campaign_state(harness)["anchorKey"], aggressive_position(harness)))

    assert anchors == [("front-b", [80, 81, 100])] * len(anchors)


@pytest.mark.parametrize("seed", range(4))
def test_unrelated_lost_home_mex_rebuild_never_mutates_live_pressure_front(seed: int) -> None:
    harness, acu, engineer, combat, observation = start_campaign(seed=seed)
    activate_pressure_front(harness, observation)
    initial = campaign_state(harness)
    serial = initial["serial"]
    full_orders = initial["fullFieldOrders"]
    clear_count = len(harness.calls.clear)
    aggressive_count = len(harness.calls.aggressive)
    second_engineer = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[12, 2, 21],
        canBuild={"ueb1103": True},
    )
    home_mex = complete_mex(harness, 500, [20, 2, 20])
    harness.controller.markers.mass[2] = lua_value(
        harness.lua,
        marker("lost-home", 20, 20),
    )
    put_units(harness, [acu, engineer, second_engineer, *combat, home_mex], seed)
    harness.brain.tick = 10
    reconcile(harness)
    put_units(harness, [acu, engineer, second_engineer, *combat], seed + 10)
    harness.brain.tick = 20
    lost = reconcile(harness)
    rebuild = [
        intent
        for intent in policy_intents(harness, lost)
        if intent.get("kind") == "build_structure"
        and intent.get("reason") == "rebuild_mex"
        and intent.get("siteKey") == "lost-home"
    ]
    assert len(rebuild) == 1
    execute_intents(harness, rebuild, lost)
    second_engineer.options.idleState = False
    second_engineer.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.tick = 30
    reconcile(harness)

    after = campaign_state(harness)
    assert after["serial"] == serial
    assert after["clusterKey"] == initial["clusterKey"]
    assert after["anchorKey"] == initial["anchorKey"]
    assert after["anchorPosition"] == initial["anchorPosition"]
    assert after["fullFieldOrders"] == full_orders
    campaign_field = set(initial["fieldTokens"])
    for call in list(harness.calls.clear.values())[clear_count:]:
        assert campaign_field.isdisjoint(actor_tokens_from_call(call))
    assert len(harness.calls.aggressive) == aggressive_count
    assert len(harness.calls.guard) == 0


@pytest.mark.parametrize("mutation", ["replacement", "cancel", "loss", "rebuild"])
def test_current_cluster_engineer_and_member_churn_cannot_retarget_area_mission(mutation: str) -> None:
    harness, acu, engineer, combat, observation = start_campaign(
        site_key="front-a",
        cluster_key="front-a",
        position=[70, 2, 40],
        extra_markers=[layered_marker("front-b", 80, 50)],
    )
    activate_pressure_front(harness, observation)
    before = campaign_state(harness)
    clear_count = len(harness.calls.clear)
    aggressive_count = len(harness.calls.aggressive)
    replacement = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[15, 2, 20],
        canBuild={"ueb1103": True},
    )
    put_units(harness, [acu, engineer, replacement, *combat])

    if mutation == "replacement":
        engineer.Dead = True
        current = reconcile(harness)
        execute_intents(
            harness,
            [
                {
                    "kind": "build_structure",
                    "actorToken": "3:1",
                    "buildRole": "mass_extractor",
                    "siteKey": "front-b",
                    "clusterKey": "front-a",
                    "position": [80, 2, 50],
                    "priority": 22,
                    "reason": "frontier_expansion",
                }
            ],
            current,
        )
    elif mutation == "cancel":
        harness.controller.pending["2:1"].phase = "cancelling"
        harness.controller.pending["2:1"].cancelReason = "timeout"
    elif mutation == "loss":
        owned = complete_mex(harness, 510, [80, 2, 50])
        put_units(harness, [acu, engineer, replacement, *combat, owned])
        reconcile(harness)
        put_units(harness, [acu, engineer, replacement, *combat])
    else:
        owned = complete_mex(harness, 511, [80, 2, 50])
        put_units(harness, [acu, engineer, replacement, *combat, owned])
        reconcile(harness)
        put_units(harness, [acu, engineer, replacement, *combat])
        lost = reconcile(harness)
        rebuild = [
            intent
            for intent in policy_intents(harness, lost)
            if intent.get("kind") == "build_structure"
            and intent.get("siteKey") == "front-b"
        ]
        if rebuild:
            execute_intents(harness, rebuild[:1], lost)

    harness.brain.tick = 40
    reconcile(harness)
    after = campaign_state(harness)
    assert after["serial"] == before["serial"]
    assert after["clusterKey"] == before["clusterKey"]
    assert after["anchorKey"] == before["anchorKey"]
    assert after["anchorPosition"] == before["anchorPosition"]
    assert after["fullFieldOrders"] == before["fullFieldOrders"]
    campaign_field = set(before["fieldTokens"])
    for call in list(harness.calls.clear.values())[clear_count:]:
        assert campaign_field.isdisjoint(actor_tokens_from_call(call))
    assert len(harness.calls.aggressive) == aggressive_count
    assert len(harness.calls.guard) == 0


def test_reinforcement_orders_only_new_field_actor_without_clearing_survivors() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_pressure_front(harness, observation)
    original_field, _ = expected_initial_cohorts(24, 2)
    home_fill = harness.unit(entityId=9000, blueprintId="uel0201", position=[10, 2, 20])
    field_fill = harness.unit(entityId=9001, blueprintId="uel0201", position=[10, 2, 20])
    put_units(harness, [acu, engineer, *combat, home_fill])
    harness.brain.tick = 10
    reconcile(harness)
    put_units(harness, [acu, engineer, *combat, home_fill, field_fill])
    harness.brain.tick = 20
    current = reconcile(harness)
    intents = campaign_intents(harness, current)
    assert len(intents) == 1
    assert intents[0]["mode"] == "reinforce"
    assert intents[0]["actorTokens"] == ["9001:1"]
    clear_count = len(harness.calls.clear)
    aggressive_count = len(harness.calls.aggressive)
    execute_intents(harness, intents, current)

    assert len(harness.calls.clear) == clear_count
    assert len(harness.calls.aggressive) == aggressive_count + 1
    assert actor_tokens_from_call(harness.calls.aggressive[aggressive_count + 1]) == ["9001:1"]
    assert aggressive_position(harness) == [80, 80.2, 20]
    assert set(original_field).isdisjoint({"9001:1"})
    assert len(harness.calls.guard) == 0


def test_holding_front_reinforces_new_field_actor_without_reordering_survivors() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_pressure_front(harness, observation)
    mex = complete_mex(harness, 705, [80, 2, 20])
    hold_cluster(harness, acu, engineer, combat, [mex])
    assert campaign_state(harness)["state"] == "holding"
    home_fill = harness.unit(entityId=9710, blueprintId="uel0201")
    field_fill = harness.unit(entityId=9711, blueprintId="uel0201")
    put_units(harness, [acu, engineer, *combat, mex, home_fill, field_fill])
    harness.brain.tick = 20

    current = reconcile(harness)
    reinforcement = campaign_intents(harness, current)

    assert len(reinforcement) == 1
    assert reinforcement[0]["mode"] == "reinforce"
    assert reinforcement[0]["actorTokens"] == ["9711:1"]
    clear_before = len(harness.calls.clear)
    aggressive_before = len(harness.calls.aggressive)
    execute_intents(harness, reinforcement, current)
    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.aggressive) == aggressive_before + 1
    assert actor_tokens_from_call(harness.calls.aggressive[aggressive_before + 1]) == [
        "9711:1"
    ]


@pytest.mark.parametrize("seed", range(4))
def test_sub_readiness_growth_does_not_create_an_early_campaign(seed: int) -> None:
    harness, acu, engineer, combat, observation = start_campaign(
        total=4,
        aa=1,
        seed=seed,
    )
    assert campaign_intents(harness, observation) == []
    assert harness.controller.fieldCampaign is None
    first_field = harness.unit(entityId=9720, blueprintId="uel0201")
    put_units(harness, [acu, engineer, *combat, first_field], seed=seed + 10)
    harness.brain.tick = 10

    current = reconcile(harness)
    assert campaign_intents(harness, current) == []
    assert harness.controller.fieldCampaign is None
    assert plain(current)["macro"]["campaignReady"] is False


def test_delayed_sub_readiness_growth_stays_macro_only_past_300_ticks() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=4, aa=1)
    assert campaign_intents(harness, observation) == []
    first_field = harness.unit(entityId=9721, blueprintId="uel0201")
    put_units(harness, [acu, engineer, *combat, first_field])
    harness.brain.tick = 500
    ready = reconcile(harness)
    assert campaign_intents(harness, ready) == []
    assert harness.controller.fieldCampaign is None
    harness.brain.tick = 800
    assert campaign_intents(harness, reconcile(harness)) == []


@pytest.mark.parametrize("failure", ["clear", "aggressive"])
def test_activation_clear_or_aggressive_failure_is_atomic_and_immediately_retryable(failure: str) -> None:
    harness, _, _, _, observation = start_campaign()
    before = campaign_state(harness)
    if failure == "clear":
        harness.calls.failClear = True
    else:
        harness.calls.failAggressive = True
    execute_intents(harness, campaign_intents(harness, observation), observation)

    assert campaign_state(harness) == before
    assert len(harness.calls.guard) == 0
    if failure == "clear":
        harness.calls.failClear = False
    else:
        harness.calls.failAggressive = False
    execute_intents(harness, campaign_intents(harness, observation), observation)
    assert campaign_state(harness)["state"] == "active"
    assert campaign_state(harness)["fullFieldOrders"] == 1
    assert plain(harness.calls.sequence)[-2:] == ["clear", "aggressive"]


@pytest.mark.parametrize("terrain_failure", ["error", "malformed"])
def test_activation_terrain_preflight_failure_issues_no_clear_or_aggressive_order(
    terrain_failure: str,
) -> None:
    harness, _, _, _, observation = start_campaign()
    intent = campaign_intents(harness, observation)[0]
    before = campaign_state(harness)
    if terrain_failure == "error":
        harness.lua.execute("function GetTerrainHeight(x, z) error('terrain failed') end")
    else:
        harness.lua.execute("function GetTerrainHeight(x, z) return 'bad-height' end")

    execute_intents(harness, [intent], observation)

    after = campaign_state(harness)
    assert len(harness.calls.clear) == 0
    assert len(harness.calls.aggressive) == 0
    assert after["state"] == before["state"] == "awaiting_order"
    assert after["pendingMode"] == before["pendingMode"] == "activate"
    assert after["fullFieldOrders"] == before["fullFieldOrders"] == 0


@pytest.mark.parametrize("failure", [True, False])
def test_reinforcement_aggressive_failure_retains_unordered_token_and_retry_has_no_clear(failure: bool) -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_pressure_front(harness, observation)
    home_fill = harness.unit(entityId=9000, blueprintId="uel0201")
    field_fill = harness.unit(entityId=9001, blueprintId="uel0201")
    put_units(harness, [acu, engineer, *combat, home_fill])
    reconcile(harness)
    put_units(harness, [acu, engineer, *combat, home_fill, field_fill])
    harness.brain.tick = 20
    current = reconcile(harness)
    clear_count = len(harness.calls.clear)
    if failure:
        harness.calls.failAggressive = True
    execute_intents(harness, campaign_intents(harness, current), current)
    if failure:
        assert campaign_state(harness)["orderedTokens"].get("9001:1") is not True
        harness.calls.failAggressive = False
        execute_intents(harness, campaign_intents(harness, current), current)
    assert campaign_state(harness)["orderedTokens"]["9001:1"] is True
    assert len(harness.calls.clear) == clear_count


def forward_graph_campaign(seed: int = 0) -> tuple[Any, Any, Any, list[Any], Any]:
    return start_campaign(
        seed=seed,
        site_key="current-a",
        cluster_key="current-a",
        position=[45, 2, 35],
        extra_markers=[
            layered_marker("current-b", 55, 45),
            layered_marker("back-a", 20, 30),
            layered_marker("lateral-a", 25, 70),
            layered_marker("forward-far", 95, 85),
            layered_marker("forward-near", 75, 65),
            layered_marker("forward-near-b", 80, 70),
            layered_marker("unreachable-a", 65, 58, land_reachable=False),
        ],
    )


@pytest.mark.parametrize("seed", range(4))
def test_cluster_hold_requires_complete_150_continuous_ticks_and_half_field_quorum(seed: int) -> None:
    harness, acu, engineer, combat, observation = forward_graph_campaign(seed)
    activate_pressure_front(harness, observation)
    current_mexes = [
        complete_mex(harness, 600, [45, 2, 35]),
        complete_mex(harness, 601, [55, 2, 45]),
    ]
    anchor = campaign_state(harness)["anchorPosition"]
    field = set(campaign_state(harness)["fieldTokens"])
    field_actors = [actor for actor in combat if f"{int(actor.options.entityId)}:1" in field]
    for index, actor in enumerate(field_actors):
        actor.options.position = lua_value(
            harness.lua,
            anchor if index < 8 else [10, 2, 20],
        )
    put_units(harness, [acu, engineer, *combat, *current_mexes], seed)
    harness.brain.tick = 10
    reconcile(harness)
    harness.brain.tick = 160
    below = reconcile(harness)
    assert campaign_intents(harness, below) == []
    assert campaign_state(harness).get("heldSinceTick") == 10

    field_actors[8].options.position = lua_value(harness.lua, anchor)
    harness.brain.tick = 160
    at_150 = reconcile(harness)
    transition = campaign_intents(harness, at_150)
    assert len(transition) == 1
    assert transition[0]["mode"] == "route_probe"
    assert transition[0]["clusterKey"] == "forward-near"
    assert transition[0]["objectiveKey"] == "forward-near-b"


def test_one_tick_cluster_loss_resets_both_ownership_hold_and_transition() -> None:
    harness, acu, engineer, combat, observation = forward_graph_campaign()
    activate_pressure_front(harness, observation)
    mex_a = complete_mex(harness, 610, [45, 2, 35])
    mex_b = complete_mex(harness, 611, [55, 2, 45])
    position_field_at(harness, combat, campaign_state(harness)["anchorPosition"])
    put_units(harness, [acu, engineer, *combat, mex_a, mex_b])
    harness.brain.tick = 10
    reconcile(harness)
    harness.brain.tick = 159
    reconcile(harness)
    mex_b.Dead = True
    harness.brain.tick = 160
    lost = reconcile(harness)
    assert campaign_intents(harness, lost) == []
    assert campaign_state(harness).get("heldSinceTick") is None
    mex_b.Dead = False
    harness.brain.tick = 161
    reconcile(harness)
    harness.brain.tick = 310
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 311
    assert campaign_intents(harness, reconcile(harness))[0]["mode"] == "route_probe"


def test_forward_graph_rejects_backward_lateral_and_unreachable_then_chooses_nearest_forward_cluster() -> None:
    harness, acu, engineer, combat, observation = forward_graph_campaign()
    activate_pressure_front(harness, observation)
    mexes = [
        complete_mex(harness, 620, [45, 2, 35]),
        complete_mex(harness, 621, [55, 2, 45]),
    ]
    hold_cluster(harness, acu, engineer, combat, mexes)
    harness.brain.tick = 160
    current = reconcile(harness)
    intent = campaign_intents(harness, current)[0]

    assert intent["mode"] == "route_probe"
    assert intent["clusterKey"] == "forward-near"
    assert intent["objectiveKey"] == "forward-near-b"
    assert intent["position"] == [80, 2, 70]
    assert "back" not in intent["clusterKey"]
    assert "lateral" not in intent["clusterKey"]
    assert "unreachable" not in intent["clusterKey"]


def test_forward_cluster_has_no_euclidean_terminal_cutoff() -> None:
    harness, acu, engineer, combat, observation = start_campaign(
        site_key="current",
        cluster_key="current",
        position=[20, 2, 25],
        extra_markers=[layered_marker("forward-remote", 100, 100)],
    )
    activate_pressure_front(harness, observation)
    mex = complete_mex(harness, 630, [20, 2, 25])
    hold_cluster(harness, acu, engineer, combat, [mex])
    harness.brain.tick = 160
    transition = campaign_intents(harness, reconcile(harness))

    assert len(transition) == 1
    assert transition[0]["mode"] == "route_probe"
    assert transition[0]["clusterKey"] == "forward-remote"


@pytest.mark.parametrize("missing_layer", ["engineerReachable", "landReachable"])
def test_permanent_graph_rejects_markers_without_explicit_layer_reachability(
    missing_layer: str,
) -> None:
    malformed = layered_marker("malformed-near", 40, 30)
    del malformed[missing_layer]
    harness, acu, engineer, combat, observation = start_campaign(
        site_key="current",
        cluster_key="current",
        position=[20, 2, 25],
        extra_markers=[
            malformed,
            layered_marker("forward-valid", 100, 100),
        ],
    )
    activate_pressure_front(harness, observation)
    mex = complete_mex(harness, 631, [20, 2, 25])
    hold_cluster(harness, acu, engineer, combat, [mex])
    harness.brain.tick = 160

    transition = campaign_intents(harness, reconcile(harness))

    assert len(transition) == 1
    assert transition[0]["mode"] == "route_probe"
    assert transition[0]["clusterKey"] == "forward-valid"


@pytest.mark.parametrize(
    "target_path,target_position,team_spawn_mode,assault",
    [
        (True, [110, 3, 120], "fixed", True),
        (False, [110, 3, 120], "fixed", False),
        (True, None, "fixed", False),
        (True, [110, 3, 120], "random", False),
        (True, [110, 3, 120], None, False),
    ],
)
def test_terminal_assault_requires_public_fixed_pathable_non_hidden_target(
    target_path: bool,
    target_position: list[float] | None,
    team_spawn_mode: Any,
    assault: bool,
) -> None:
    harness, acu, engineer, combat, observation = start_campaign(
        site_key="last-front",
        cluster_key="last-front",
        position=[100, 2, 100],
        team_spawn_mode=team_spawn_mode,
    )
    harness.controller.targetPath = target_path
    harness.controller.targetPosition = lua_value(harness.lua, target_position) if target_position else None
    activate_pressure_front(harness, observation)
    mex = complete_mex(harness, 640, [100, 2, 100])
    hold_cluster(harness, acu, engineer, combat, [mex])
    harness.brain.tick = 160
    current = reconcile(harness)
    intents = campaign_intents(harness, current)

    if not assault:
        assert intents == []
        assert campaign_state(harness)["kind"] == "pressure_front"
        return
    assert len(intents) == 1
    assert intents[0]["mode"] == "route_probe"
    assert campaign_state(harness)["kind"] == "pressure_front"
    complete_staged_route(harness, current)
    state = campaign_state(harness)
    assert state["kind"] == "strategic_assault"
    assert state["anchorKey"] == "target:ARMY_2"
    assert state["anchorPosition"] == [110, 3, 120]
    assert plain(harness.calls.sequence)[-2:] == ["clear", "aggressive"]
    assert len(harness.calls.guard) == 0
    after = reconcile(harness)
    assert campaign_intents(harness, after) == []


@pytest.mark.parametrize("tick,expected_recoveries", [(299, 0), (300, 1), (599, 1), (600, 1)])
def test_stationary_field_recovery_has_300_tick_lower_bound_and_cadence(
    tick: int,
    expected_recoveries: int,
) -> None:
    harness, _, _, _, observation = start_campaign()
    activate_pressure_front(harness, observation)
    for boundary in [299, 300, 599, 600]:
        if boundary > tick:
            break
        harness.brain.tick = boundary
        current = reconcile(harness)
        execute_intents(harness, campaign_intents(harness, current), current)
    state = campaign_state(harness)
    assert state["recoveryOrders"] == expected_recoveries
    assert state["fullFieldOrders"] == 1 + expected_recoveries
    if tick == 600:
        assert state["rollbackOrders"] == 1
        assert state["state"] == "rebuilding"
    assert len(harness.calls.guard) == 0


def test_meaningful_field_progress_and_arrival_prevent_recovery_for_600_ticks() -> None:
    harness, _, _, combat, observation = start_campaign()
    activate_pressure_front(harness, observation)
    field = set(campaign_state(harness)["fieldTokens"])
    for tick, x in [(100, 25), (200, 40), (300, 55), (400, 70), (600, 80)]:
        for actor in combat:
            if f"{int(actor.options.entityId)}:1" in field:
                actor.options.position = lua_value(harness.lua, [x, 2, 20])
        harness.brain.tick = tick
        current = reconcile(harness)
        execute_intents(harness, campaign_intents(harness, current), current)

    assert campaign_state(harness)["fullFieldOrders"] == 1
    assert campaign_state(harness)["recoveryOrders"] == 0
    assert len(harness.calls.clear) == 1
    assert len(harness.calls.aggressive) == 1


def test_stationary_cohort_growth_rebaselines_distance_without_delaying_stuck_recovery() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_pressure_front(harness, observation)
    home_fill = harness.unit(entityId=9700, blueprintId="uel0201")
    field_fill = harness.unit(entityId=9701, blueprintId="uel0201")
    put_units(harness, [acu, engineer, *combat, home_fill, field_fill])
    harness.brain.tick = 299
    grown = reconcile(harness)
    reinforcement = campaign_intents(harness, grown)
    assert len(reinforcement) == 1
    assert reinforcement[0]["mode"] == "reinforce"
    assert reinforcement[0]["actorTokens"] == ["9701:1"]
    execute_intents(harness, reinforcement, grown)

    harness.brain.tick = 300
    stuck = reconcile(harness)
    recovery = campaign_intents(harness, stuck)

    assert len(recovery) == 1
    assert recovery[0]["mode"] == "recover"
    assert campaign_state(harness)["lastProgressTick"] == 0


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_stale_field_actor_fails_before_clear_and_reconciles_exact_live_generation(mutation: str) -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    intent = campaign_intents(harness, observation)[0]
    victim = next(actor for actor in combat if f"{int(actor.options.entityId)}:1" in intent["actorTokens"])
    units = [acu, engineer, *combat]
    if mutation == "dead":
        victim.Dead = True
    elif mutation == "captured":
        victim.options.army = 2
    else:
        replacement = harness.unit(
            entityId=int(victim.options.entityId),
            blueprintId=str(victim.options.blueprintId),
            position=[10, 2, 20],
        )
        units = [replacement if actor is victim else actor for actor in units]
        harness.controller.unitRefs[intent["actorTokens"][0]] = replacement
    put_units(harness, units)
    execute_intents(harness, [intent], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.aggressive) == 0
    current = reconcile(harness)
    retry = campaign_intents(harness, current)
    if mutation == "recycled":
        assert len(retry) == 1 and retry[0]["mode"] == "activate"
        assert intent["actorTokens"] != retry[0]["actorTokens"]
        assert any(token.endswith(":2") for token in retry[0]["actorTokens"])
    else:
        assert retry == []
        assert plain(current)["macro"]["campaignReady"] is False


def test_malicious_home_and_acu_injection_cannot_mutate_or_order_campaign() -> None:
    harness, _, _, _, observation = start_campaign()
    valid = campaign_intents(harness, observation)[0]
    before = campaign_state(harness)
    for injected in ["1:1", before["homeTokens"][0]]:
        malicious = dict(valid)
        malicious["actorTokens"] = sorted([*valid["actorTokens"], injected])
        execute_intents(harness, [malicious], observation)
    assert campaign_state(harness) == before
    assert len(harness.calls.clear) == 0
    assert len(harness.calls.aggressive) == 0


def test_ian_mass490_churn_stays_on_one_anchor_then_advances_forward_once() -> None:
    harness, acu, engineer, combat, observation = start_campaign(
        site_key="Mass490",
        cluster_key="Mass490",
        position=[490.5, 53.543, 263.5],
        extra_markers=[
            layered_marker("Mass492", 492.5, 248.5),
            layered_marker("Mass279", 279.5, 311.5),
            layered_marker("Mass277", 277.5, 295.5),
            layered_marker("Mass292", 292.5, 298.5),
            layered_marker("home-loss", 20, 20),
        ],
        target_position=[915.5, 30.3613, 935.5],
        target_name="ARMY_2",
    )
    activate_pressure_front(harness, observation)
    initial = campaign_state(harness)
    assert initial["anchorKey"] == "Mass490"
    initial_serial = initial["serial"]
    for tick, key in enumerate(["Mass492", "Mass279", "Mass277", "home-loss"] * 20, 1):
        harness.brain.tick = tick
        harness.controller.selectedFrontierCluster = key
        harness.controller.selectedFrontierSite = key
        current = reconcile(harness)
        execute_intents(harness, campaign_intents(harness, current), current)
    stable = campaign_state(harness)
    assert stable["serial"] == initial_serial
    assert stable["clusterKey"] == "Mass490"
    assert stable["anchorKey"] == "Mass490"
    assert stable["anchorPosition"] == initial["anchorPosition"]
    assert stable["fullFieldOrders"] == 1

    mexes = [
        complete_mex(harness, 700, [490.5, 53.543, 263.5]),
        complete_mex(harness, 701, [492.5, 53.8945, 248.5]),
    ]
    hold_cluster(harness, acu, engineer, combat, mexes, start_tick=100)
    harness.brain.tick = 250
    transition = campaign_intents(harness, reconcile(harness))
    assert len(transition) == 1
    assert transition[0]["mode"] == "route_probe"
    complete_staged_route(harness, reconcile(harness))
    assert campaign_state(harness)["fullFieldOrders"] == 2
    assert campaign_state(harness)["anchorKey"] == "target:ARMY_2"


def test_pressure_front_telemetry_exposes_stable_scalar_area_and_quorum_fields() -> None:
    harness, _, _, _, observation = start_campaign()
    activate_pressure_front(harness, observation)
    macro = plain(reconcile(harness))["macro"]

    assert macro["campaignKind"] == "pressure_front"
    assert macro["campaignAnchorKey"] == "cluster-a"
    assert isinstance(macro["campaignAnchorX"], (int, float))
    assert isinstance(macro["campaignAnchorZ"], (int, float))
    assert isinstance(macro["campaignFieldAtAnchor"], int)
    assert macro["campaignArrivalQuorum"] == 9
    assert isinstance(macro["campaignForwardDistance"], (int, float))
    assert isinstance(macro["campaignFullFieldOrders"], int)
    assert isinstance(macro["campaignReinforcementOrders"], int)
    assert isinstance(macro["campaignRecoveryOrders"], int)


def test_static_field_campaign_has_no_guard_or_site_level_retarget_runtime() -> None:
    controller = source("lua/AI/Overmind4/Controller.lua")
    executor = controller.split("local function ExecuteFieldCampaign", 1)[1].split("Controller = {}", 1)[0]
    update = controller.split("local function UpdateFieldCampaign", 1)[1].split(
        "local function CampaignExpectedPosition", 1
    )[0]

    assert "IssueGuard" not in executor
    assert "retarget" not in update
    assert "RelevantCampaignOperation" not in update
    assert "selectedFrontierCluster" not in update
    assert "selectedFrontierSite" not in update
    assert "IssueAggressiveMove" in executor


def test_controller_keeps_luaplus_top_level_local_headroom() -> None:
    controller = source("lua/AI/Overmind4/Controller.lua")
    top_level_locals = re.findall(
        r"^local (?:function )?([A-Za-z_][A-Za-z0-9_]*)",
        controller,
        re.MULTILINE,
    )

    assert len(top_level_locals) <= 195


def test_pressure_front_adds_no_enemy_query_or_enemy_blueprint_intelligence() -> None:
    harness, _, _, _, observation = start_campaign()
    own_before = len(harness.calls.own)
    enemy_before = len(harness.calls.enemy)
    activate_pressure_front(harness, observation)
    harness.brain.tick = 10
    reconcile(harness)

    assert len(harness.calls.own) == own_before + 1
    assert len(harness.calls.enemy) == enemy_before + 1
    controller = source("lua/AI/Overmind4/Controller.lua")
    campaign_source = controller.split("local function CampaignCombatRecords", 1)[1].split(
        "Controller = {}", 1
    )[0]
    assert "GetBlueprint" not in campaign_source
    assert "GetArmy" not in campaign_source
    assert "GetUnitsAroundPoint" not in campaign_source


def setup_pressure_mode(mode: str) -> tuple[Any, Any, dict[str, Any]]:
    if mode == "activate":
        harness, _, _, _, observation = start_campaign()
        return harness, observation, campaign_intents(harness, observation)[0]
    if mode == "recover":
        harness, _, _, _, observation = start_campaign()
        activate_pressure_front(harness, observation)
        harness.brain.tick = 300
        current = reconcile(harness)
        return harness, current, campaign_intents(harness, current)[0]
    if mode == "resume":
        harness, acu, _, _, observation = start_campaign()
        activate_pressure_front(harness, observation)
        harness.controller.pending["2:1"] = None
        acu.options.health = 69
        harness.brain.tick = 10
        low = reconcile(harness)
        execute_intents(harness, campaign_intents(harness, low), low)
        acu.options.health = 75
        harness.brain.tick = 20
        reconcile(harness)
        harness.brain.tick = 320
        ready = reconcile(harness)
        return harness, ready, campaign_intents(harness, ready)[0]
    if mode == "transition":
        harness, acu, engineer, combat, observation = forward_graph_campaign()
        activate_pressure_front(harness, observation)
        mexes = [
            complete_mex(harness, 810, [45, 2, 35]),
            complete_mex(harness, 811, [55, 2, 45]),
        ]
        hold_cluster(harness, acu, engineer, combat, mexes)
        harness.brain.tick = 160
        ready = reconcile(harness)
        return harness, ready, campaign_intents(harness, ready)[0]
    if mode == "assault":
        harness, acu, engineer, combat, observation = start_campaign(
            site_key="last-front",
            cluster_key="last-front",
            position=[100, 2, 100],
        )
        activate_pressure_front(harness, observation)
        hold_cluster(
            harness,
            acu,
            engineer,
            combat,
            [complete_mex(harness, 812, [100, 2, 100])],
        )
        harness.brain.tick = 160
        ready = reconcile(harness)
        return harness, ready, campaign_intents(harness, ready)[0]
    raise AssertionError(mode)


@pytest.mark.parametrize("mode", ["recover", "resume"])
@pytest.mark.parametrize("failure", ["clear", "aggressive"])
def test_every_full_aggressive_mode_failure_is_atomic_and_immediately_retryable(
    mode: str,
    failure: str,
) -> None:
    harness, observation, intent = setup_pressure_mode(mode)
    before = campaign_state(harness)
    if failure == "clear":
        harness.calls.failClear = True
    else:
        harness.calls.failAggressive = True
    execute_intents(harness, [intent], observation)
    assert campaign_state(harness) == before
    if failure == "clear":
        harness.calls.failClear = False
    else:
        harness.calls.failAggressive = False
    execute_intents(harness, [intent], observation)
    after = campaign_state(harness)
    assert after.get("pendingMode") is None
    assert after["fullFieldOrders"] == before["fullFieldOrders"] + 1
    assert len(harness.calls.guard) == 0


@pytest.mark.parametrize("mutation", ["target_path", "target_position", "anchor_position"])
def test_assault_and_pressure_anchor_toctou_mutations_fail_before_clear_and_retry(mutation: str) -> None:
    if mutation == "anchor_position":
        harness, observation, intent = setup_pressure_mode("recover")
        anchor = harness.controller.markers.mass[1]
        original = plain(anchor.position)
        anchor.position = lua_value(harness.lua, [original[0] + 1, original[1], original[2]])
        restore = lambda: setattr(anchor, "position", lua_value(harness.lua, original))
    else:
        harness, observation, intent = setup_pressure_mode("assault")
        if mutation == "target_path":
            harness.controller.targetPath = False
            restore = lambda: setattr(harness.controller, "targetPath", True)
        else:
            original = plain(harness.controller.targetPosition)
            harness.controller.targetPosition = lua_value(harness.lua, [111, 3, 120])
            restore = lambda: setattr(
                harness.controller,
                "targetPosition",
                lua_value(harness.lua, original),
            )
    harness.observe()
    before = campaign_state(harness)
    clear_count = len(harness.calls.clear)
    execute_intents(harness, [intent], observation)
    assert len(harness.calls.clear) == clear_count
    assert campaign_state(harness) == before
    restore()
    harness.observe()
    execute_intents(harness, [intent], observation)
    assert campaign_state(harness).get("pendingMode") is None


@pytest.mark.parametrize("missing_layer", ["engineerReachable", "landReachable"])
def test_pressure_execution_rejects_missing_live_anchor_reachability_before_clear(
    missing_layer: str,
) -> None:
    harness, observation, intent = setup_pressure_mode("activate")
    anchor = harness.controller.markers.mass[1]
    setattr(anchor, missing_layer, None)
    harness.observe()
    before = campaign_state(harness)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.aggressive) == 0
    assert campaign_state(harness) == before
    setattr(anchor, missing_layer, True)
    harness.observe()
    execute_intents(harness, [intent], observation)
    assert campaign_state(harness)["state"] == "active"


def test_persistently_invalid_staged_route_blocks_cluster_and_replans_to_next_forward_cluster() -> None:
    harness, observation, intent = setup_pressure_mode("transition")
    anchor = next(
        harness.controller.markers.mass[index]
        for index in range(1, len(harness.controller.markers.mass) + 1)
        if harness.controller.markers.mass[index].key == intent["objectiveKey"]
    )
    anchor.landReachable = False
    harness.observe()
    clear_before = len(harness.calls.clear)
    execute_intents(harness, [intent], observation)
    assert len(harness.calls.clear) == clear_before

    replanned_observation = reconcile(harness)
    replanned = campaign_intents(harness, replanned_observation)

    assert len(replanned) == 1
    assert replanned[0]["mode"] == "route_probe"
    assert replanned[0]["clusterKey"] == "forward-far"
    assert replanned[0]["objectiveKey"] == "forward-far"


def test_persistently_invalid_assault_route_is_blocked_instead_of_immediately_retried() -> None:
    harness, observation, intent = setup_pressure_mode("assault")
    harness.controller.targetPath = False
    harness.observe()
    clear_before = len(harness.calls.clear)
    execute_intents(harness, [intent], observation)
    assert len(harness.calls.clear) == clear_before

    invalid = reconcile(harness)
    assert campaign_intents(harness, invalid) == []
    state = campaign_state(harness)
    assert state.get("pendingMode") is None
    assert state.get("desiredKind") is None
    assert state["kind"] == "pressure_front"

    harness.controller.targetPath = True
    harness.brain.tick += 1
    restored = reconcile(harness)
    assert campaign_intents(harness, restored) == []
    assert campaign_state(harness).get("routeBlockedCount", 0) >= 1


def test_health_recall_without_mex_operation_resumes_same_pressure_anchor_once() -> None:
    harness, acu, _, _, observation = start_campaign()
    activate_pressure_front(harness, observation)
    before = campaign_state(harness)
    harness.controller.pending["2:1"] = None
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    assert campaign_state(harness)["state"] == "recalled"
    acu.options.health = 75
    harness.brain.tick = 20
    reconcile(harness)
    harness.brain.tick = 320
    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)
    assert len(resume) == 1 and resume[0]["mode"] == "resume"
    execute_intents(harness, resume, ready)
    after = campaign_state(harness)
    assert after["anchorKey"] == before["anchorKey"]
    assert after["anchorPosition"] == before["anchorPosition"]
    assert after["clusterKey"] == before["clusterKey"]
    assert after["kind"] == "pressure_front"
    assert len(harness.calls.guard) == 0


def test_committed_assault_recall_and_resume_needs_no_structure_operation() -> None:
    harness, ready, assault = setup_pressure_mode("assault")
    assert assault["mode"] == "route_probe"
    complete_staged_route(harness, ready)
    state = campaign_state(harness)
    assert state["kind"] == "strategic_assault"
    for token in state["fieldTokens"]:
        harness.controller.unitRefs[token].options.position = lua_value(
            harness.lua,
            state["anchorPosition"],
        )
    harness.brain.tick += 1
    reconcile(harness)
    assert campaign_state(harness).get("routeRollback") is None
    harness.controller.pending = harness.lua.table_from({})
    acu = next(
        actor
        for actor in harness.brain.units.values()
        if int(actor.options.entityId) == 1
    )
    acu.options.health = 69
    harness.brain.tick = 200
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    acu.options.health = 75
    harness.brain.tick = 210
    reconcile(harness)
    harness.brain.tick = 510
    resume_observation = reconcile(harness)
    resume = campaign_intents(harness, resume_observation)
    assert len(resume) == 1 and resume[0]["mode"] == "resume"
    execute_intents(harness, resume, resume_observation)
    after = campaign_state(harness)
    assert after["kind"] == "strategic_assault"
    assert after["anchorKey"] == "target:ARMY_2"
    assert aggressive_position(harness)[0::2] == [110, 120]


@pytest.mark.parametrize("staged_mode", ["transition", "assault"])
def test_recall_preempts_uncommitted_destination_and_resume_keeps_committed_anchor(staged_mode: str) -> None:
    harness, ready, staged = setup_pressure_mode(staged_mode)
    before = campaign_state(harness)
    acu = next(
        actor
        for actor in harness.brain.units.values()
        if int(actor.options.entityId) == 1
    )
    acu.options.health = 69
    harness.brain.tick += 1
    low = reconcile(harness)
    recall = campaign_intents(harness, low)
    assert len(recall) == 1 and recall[0]["mode"] == "recall"
    assert recall[0]["clusterKey"] == before["clusterKey"]
    execute_intents(harness, recall, low)
    recalled = campaign_state(harness)
    assert recalled.get("desiredAnchorKey") is None
    assert recalled["anchorKey"] == before["anchorKey"]
    assert recalled["kind"] == before["kind"]
    execute_intents(harness, [staged], ready)
    assert campaign_state(harness)["state"] == "recalled"


@pytest.mark.parametrize("staged_mode", ["transition", "assault"])
def test_home_reserve_recall_preempts_staged_destination_before_safe_resume(
    staged_mode: str,
) -> None:
    harness, ready, staged = setup_pressure_mode(staged_mode)
    before = campaign_state(harness)
    for token in before["homeTokens"]:
        harness.controller.unitRefs[token].Dead = True
    enemy = harness.unit(
        entityId=99100,
        blueprintId="uel0201",
        army=2,
        position=[15, 2, 20],
    )
    harness.brain.enemies = harness.lua.table_from([enemy])
    harness.brain.tick += 1
    contact = reconcile(harness)
    recall = campaign_intents(harness, contact)

    assert len(recall) == 1 and recall[0]["mode"] == "recall"
    assert recall[0]["clusterKey"] == before["clusterKey"]
    assert recall[0]["objectiveKey"] == before["anchorKey"]
    execute_intents(harness, recall, contact)
    recalled = campaign_state(harness)
    assert recalled.get("desiredKind") is None
    assert recalled.get("desiredClusterKey") is None
    assert recalled.get("desiredAnchorKey") is None
    assert recalled["kind"] == before["kind"]
    assert recalled["clusterKey"] == before["clusterKey"]
    assert recalled["anchorKey"] == before["anchorKey"]

    live = [actor for actor in harness.brain.units.values() if not actor.Dead]
    replacements = [
        harness.unit(
            entityId=99500 + index,
            blueprintId="uel0104" if index == 0 else "uel0201",
        )
        for index in range(6)
    ]
    harness.brain.units = harness.lua.table_from([*live, *replacements])
    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick += 10
    reconcile(harness)
    harness.brain.tick += 300
    safe = reconcile(harness)
    resume = campaign_intents(harness, safe)

    assert len(resume) == 1 and resume[0]["mode"] == "resume"
    assert resume[0]["clusterKey"] == before["clusterKey"]
    assert resume[0]["objectiveKey"] == before["anchorKey"]
    assert resume[0]["position"] == before["anchorPosition"]
    execute_intents(harness, resume, safe)
    after = campaign_state(harness)
    assert after["kind"] == before["kind"]
    assert after["clusterKey"] == before["clusterKey"]
    assert after["anchorKey"] == before["anchorKey"]
    execute_intents(harness, [staged], ready)
    assert campaign_state(harness)["anchorKey"] == before["anchorKey"]


def test_readiness_gate_activates_full_cohort_without_an_early_survivor_order() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=23, aa=2)
    assert campaign_intents(harness, observation) == []
    assert harness.controller.fieldCampaign is None
    promoted = harness.unit(entityId=9999, blueprintId="uel0201", position=[10, 2, 20])
    put_units(harness, [acu, engineer, *combat, promoted])
    harness.brain.tick = 10
    current = reconcile(harness)
    activation = campaign_intents(harness, current)
    assert len(activation) == 1 and activation[0]["mode"] == "activate"
    assert len(activation[0]["actorTokens"]) == 18
    execute_intents(harness, activation, current)
    assert len(harness.calls.clear) == 1
    assert len(harness.calls.aggressive) == 1


def quorum_boundary_campaign(*, delta: float, total: int = 26) -> tuple[Any, Any]:
    harness, acu, engineer, combat, observation = start_campaign(total=total, aa=2)
    activate_pressure_front(harness, observation)
    anchor = campaign_state(harness)["anchorPosition"]
    field = set(campaign_state(harness)["fieldTokens"])
    field_actors = [actor for actor in combat if f"{int(actor.options.entityId)}:1" in field]
    quorum = (len(field_actors) + 1) // 2
    for index, actor in enumerate(field_actors):
        actor.options.position = lua_value(
            harness.lua,
            [anchor[0] - (20 + delta), 2, anchor[2]] if index < quorum else [10, 2, 20],
        )
    mex = complete_mex(harness, 830, anchor)
    put_units(harness, [acu, engineer, *combat, mex])
    harness.brain.tick = 10
    reconcile(harness)
    harness.brain.tick = 160
    return harness, reconcile(harness)


@pytest.mark.parametrize("delta,transition", [(0, True), (0.01, False)])
def test_arrival_radius_is_inclusive_at_20_and_odd_live_field_uses_ceil_half(
    delta: float,
    transition: bool,
) -> None:
    harness, current = quorum_boundary_campaign(delta=delta)
    state = campaign_state(harness)
    assert state["arrivalQuorum"] == 10
    intents = campaign_intents(harness, current)
    assert bool(intents) is transition
    if transition:
        assert intents[0]["mode"] == "route_probe"


def test_zero_live_field_never_vacuously_transitions_or_recovers() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_pressure_front(harness, observation)
    field = set(campaign_state(harness)["fieldTokens"])
    survivors = [
        actor
        for actor in combat
        if f"{int(actor.options.entityId)}:1" not in field
    ]
    mex = complete_mex(harness, 831, [80, 2, 20])
    put_units(harness, [acu, engineer, *survivors, mex])
    harness.brain.tick = 10
    reconcile(harness)
    harness.brain.tick = 1000
    current = reconcile(harness)
    assert campaign_state(harness)["arrivalQuorum"] == 0
    assert not campaign_state(harness)["fieldTokens"]
    assert campaign_state(harness)["state"] == "rebuilding"
    assert campaign_state(harness)["rollbackReason"] == "field_attrition"
    assert campaign_intents(harness, current) == []


@pytest.mark.parametrize("majority_progress,recover", [(1.99, True), (2.01, False)])
def test_quorum_actor_progress_boundary_is_strictly_more_than_two(
    majority_progress: float,
    recover: bool,
) -> None:
    harness, _, _, combat, observation = start_campaign()
    activate_pressure_front(harness, observation)
    state = campaign_state(harness)
    field = set(state["fieldTokens"])
    field_actors = [actor for actor in combat if f"{int(actor.options.entityId)}:1" in field]
    baseline = state["bestDistance"]
    for actor in field_actors[:9]:
        actor.options.position = lua_value(
            harness.lua,
            [80 - (baseline - majority_progress), 2, 20],
        )
    field_actors[-1].options.position = lua_value(harness.lua, [79, 2, 20])
    harness.brain.tick = 299
    reconcile(harness)
    harness.brain.tick = 300
    intents = campaign_intents(harness, reconcile(harness))
    assert bool([intent for intent in intents if intent["mode"] == "recover"]) is recover


def test_complete_holding_below_quorum_still_recovers_at_300() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_pressure_front(harness, observation)
    mex = complete_mex(harness, 832, [80, 2, 20])
    put_units(harness, [acu, engineer, *combat, mex])
    harness.brain.tick = 10
    reconcile(harness)
    harness.brain.tick = 300
    current = reconcile(harness)
    intents = campaign_intents(harness, current)
    assert len(intents) == 1 and intents[0]["mode"] == "recover"


def pending_reinforcement_before_campaign_progress(
    next_mode: str,
    seed: int,
) -> tuple[Any, Any, dict[str, Any]]:
    if next_mode == "recover":
        harness, acu, engineer, combat, observation = start_campaign(seed=seed)
        activate_pressure_front(harness, observation)
        fixed_units = [acu, engineer, *combat]
        next_tick = 299
    elif next_mode == "transition":
        harness, acu, engineer, combat, observation = forward_graph_campaign(seed)
        activate_pressure_front(harness, observation)
        mexes = [
            complete_mex(harness, 860, [45, 2, 35]),
            complete_mex(harness, 861, [55, 2, 45]),
        ]
        hold_cluster(harness, acu, engineer, combat, mexes, start_tick=10)
        fixed_units = [acu, engineer, *combat, *mexes]
        next_tick = 159
    elif next_mode == "assault":
        harness, acu, engineer, combat, observation = start_campaign(
            seed=seed,
            site_key="last-front",
            cluster_key="last-front",
            position=[100, 2, 100],
        )
        activate_pressure_front(harness, observation)
        mex = complete_mex(harness, 862, [100, 2, 100])
        hold_cluster(harness, acu, engineer, combat, [mex], start_tick=10)
        fixed_units = [acu, engineer, *combat, mex]
        next_tick = 159
    else:
        raise AssertionError(next_mode)

    home_fill = harness.unit(entityId=9730, blueprintId="uel0201")
    pending_actor = harness.unit(entityId=9731, blueprintId="uel0201")
    put_units(
        harness,
        [*fixed_units, home_fill, pending_actor],
        seed=seed + 100,
    )
    harness.brain.tick = next_tick
    current = reconcile(harness)
    reinforcement = campaign_intents(harness, current)
    assert len(reinforcement) == 1
    assert reinforcement[0]["mode"] == "reinforce"
    assert reinforcement[0]["actorTokens"] == ["9731:1"]
    return harness, current, reinforcement[0]


def invalidate_pending_reinforcement_actor(
    harness: Any,
    intent: dict[str, Any],
    mutation: str,
    seed: int,
) -> tuple[str, str | None]:
    old_token = intent["actorTokens"][0]
    entity_id = int(old_token.split(":", 1)[0])
    actor = harness.controller.unitRefs[old_token]
    units = list(harness.brain.units.values())
    new_token = None
    if mutation == "dead":
        actor.Dead = True
    elif mutation == "captured":
        actor.options.army = 2
    elif mutation == "recycled":
        replacement = harness.unit(
            entityId=entity_id,
            blueprintId="uel0201",
            position=[10, 2, 20],
        )
        units = [
            replacement
            if int(candidate.options.entityId) == entity_id
            else candidate
            for candidate in units
        ]
        harness.controller.unitRefs[old_token] = replacement
        new_token = f"{entity_id}:2"
    else:
        raise AssertionError(mutation)
    random.Random(seed + 200).shuffle(units)
    harness.brain.units = harness.lua.table_from(units)
    return old_token, new_token


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
@pytest.mark.parametrize("next_mode", ["recover", "transition", "assault"])
def test_stale_pending_reinforcement_cannot_freeze_campaign_progress(
    seed: int,
    mutation: str,
    next_mode: str,
) -> None:
    harness, stale_observation, stale_intent = pending_reinforcement_before_campaign_progress(
        next_mode,
        seed,
    )
    before = campaign_state(harness)
    old_token, new_token = invalidate_pending_reinforcement_actor(
        harness,
        stale_intent,
        mutation,
        seed,
    )
    aggressive_before = len(harness.calls.aggressive)

    execute_intents(harness, [stale_intent], stale_observation)

    assert len(harness.calls.aggressive) == aggressive_before
    assert campaign_state(harness) == before
    harness.brain.tick += 1
    current = reconcile(harness)
    state = campaign_state(harness)
    assert_campaign_cohort_indexes(harness.controller.fieldCampaign)
    assert old_token not in (state.get("fieldTokens") or [])
    assert old_token not in (state.get("homeTokens") or [])
    assert state.get("orderedTokens", {}).get(old_token) is not True
    assert state["state"] == before["state"]
    assert state["serial"] == before["serial"]
    assert state["anchorKey"] == before["anchorKey"]
    intents = campaign_intents(harness, current)

    if mutation == "recycled":
        assert new_token is not None
        assert len(intents) == 1
        assert intents[0]["mode"] == "reinforce"
        assert intents[0]["actorTokens"] == [new_token]
        assert new_token in state["fieldTokens"]
        assert state.get("orderedTokens", {}).get(new_token) is not True
        execute_intents(harness, intents, current)
        assert campaign_state(harness)["orderedTokens"][new_token] is True
        harness.brain.tick += 1
        current = reconcile(harness)
        intents = campaign_intents(harness, current)

    expected_mode = "route_probe" if next_mode in {"transition", "assault"} else next_mode
    assert len(intents) == 1
    assert intents[0]["mode"] == expected_mode
    assert campaign_state(harness).get("pendingMode") == expected_mode


@pytest.mark.parametrize("seed", range(3))
def test_pruning_one_stale_reinforcement_retains_exact_live_unordered_survivors(
    seed: int,
) -> None:
    harness, acu, engineer, combat, observation = start_campaign(seed=seed)
    activate_pressure_front(harness, observation)
    additions = [
        harness.unit(entityId=9740 + index, blueprintId="uel0201")
        for index in range(4)
    ]
    put_units(harness, [acu, engineer, *combat, *additions], seed=seed + 300)
    harness.brain.tick = 10
    staged_observation = reconcile(harness)
    staged = campaign_intents(harness, staged_observation)
    assert len(staged) == 1 and staged[0]["mode"] == "reinforce"
    assert len(staged[0]["actorTokens"]) == 3
    victim = staged[0]["actorTokens"][0]
    survivors = staged[0]["actorTokens"][1:]
    harness.controller.unitRefs[victim].Dead = True
    aggressive_before = len(harness.calls.aggressive)
    execute_intents(harness, staged, staged_observation)
    assert len(harness.calls.aggressive) == aggressive_before

    harness.brain.tick = 11
    current = reconcile(harness)
    retry = campaign_intents(harness, current)
    state = campaign_state(harness)

    assert len(retry) == 1
    assert retry[0]["mode"] == "reinforce"
    assert retry[0]["actorTokens"] == survivors
    assert state["pendingTokens"] == survivors
    assert victim not in state["fieldTokens"]
    assert state.get("orderedTokens", {}).get(victim) is not True
    assert_campaign_cohort_indexes(harness.controller.fieldCampaign)
    execute_intents(harness, retry, current)
    after = campaign_state(harness)
    assert all(after["orderedTokens"][token] is True for token in survivors)


def test_permanent_pressure_graph_ignores_selected_frontier_and_ownership_churn() -> None:
    harness, acu, engineer, combat, observation = start_campaign(
        site_key="current-a",
        cluster_key="current-a",
        position=[45, 2, 35],
        extra_markers=[
            layered_marker("current-b", 55, 45),
            layered_marker("next-a", 80, 70),
        ],
    )
    activate_pressure_front(harness, observation)
    before = campaign_state(harness)
    harness.controller.selectedFrontierCluster = "next-a"
    harness.controller.selectedFrontierSite = "next-a"
    owned_next = complete_mex(harness, 840, [80, 2, 70])
    put_units(harness, [acu, engineer, *combat, owned_next])
    harness.brain.tick = 20
    reconcile(harness)
    after = campaign_state(harness)
    assert after["clusterKey"] == before["clusterKey"]
    assert after["memberKeys"] == before["memberKeys"]
    assert after["anchorKey"] == before["anchorKey"]
    assert after["anchorPosition"] == before["anchorPosition"]


def test_audited_ian_five_marker_subset_advances_mass279_to_mass490_then_assaults() -> None:
    target = [915.5, 30.3613, 935.5]
    m277 = "Mass:277500:295500"
    m279 = "Mass:279500:311500"
    m292 = "Mass:292500:298500"
    m490 = "Mass:490500:263500"
    m492 = "Mass:492500:248500"
    harness, acu, engineer, combat, observation = start_campaign(
        site_key=m277,
        cluster_key=m277,
        position=[277.5, 2, 295.5],
        extra_markers=[
            layered_marker(m279, 279.5, 311.5),
            layered_marker(m292, 292.5, 298.5),
            layered_marker(m490, 490.5, 263.5),
            layered_marker(m492, 492.5, 248.5),
        ],
        target_position=target,
        target_name="ARMY_2",
    )
    activate_pressure_front(harness, observation)
    assert campaign_state(harness)["anchorKey"] == m279
    first_mexes = [
        complete_mex(harness, 850, [277.5, 2, 295.5]),
        complete_mex(harness, 851, [279.5, 2, 311.5]),
        complete_mex(harness, 852, [292.5, 2, 298.5]),
    ]
    hold_cluster(harness, acu, engineer, combat, first_mexes, start_tick=10)
    harness.brain.tick = 160
    first = reconcile(harness)
    transition = campaign_intents(harness, first)
    assert transition[0]["mode"] == "route_probe"
    assert transition[0]["clusterKey"] == m490
    assert transition[0]["objectiveKey"] == m490
    complete_staged_route(harness, first)
    assert campaign_state(harness)["anchorKey"] == m490
    position_field_at(harness, combat, campaign_state(harness)["anchorPosition"])
    second_mexes = [
        complete_mex(harness, 853, [490.5, 2, 263.5]),
        complete_mex(harness, 854, [492.5, 2, 248.5]),
    ]
    put_units(harness, [acu, engineer, *combat, *first_mexes, *second_mexes])
    harness.brain.tick = 170
    reconcile(harness)
    harness.brain.tick = 320
    last = reconcile(harness)
    assault = campaign_intents(harness, last)
    assert len(assault) == 1 and assault[0]["mode"] == "route_probe"
