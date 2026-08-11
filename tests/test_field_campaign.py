from __future__ import annotations

import itertools
import random
from pathlib import Path
from typing import Any

import pytest

from conftest import source
from test_controller import execute_intents, make_harness
from test_policy import lua_value, plain
from test_secured_frontier_doctrine import FORBIDDEN_OFFENSE, install_markers, marker


CAMPAIGN_KIND = "field_campaign"
COMBAT_ROLES = {"tank", "artillery", "anti_air", "lab"}


def reconcile(harness: Any) -> Any:
    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    return observation


def policy_intents(harness: Any, observation: Any) -> list[dict[str, Any]]:
    return plain(harness.lua.globals().Policy.Decide(observation))


def campaign_intents(harness: Any, observation: Any) -> list[dict[str, Any]]:
    return [intent for intent in policy_intents(harness, observation) if intent.get("kind") == CAMPAIGN_KIND]


def actor_tokens_from_call(call: Any) -> list[str]:
    return sorted(
        f"{int(actor.options.entityId)}:1"
        for actor in call.units.values()
    )


def expected_initial_cohorts(total: int, aa: int) -> tuple[list[str], list[str]]:
    aa_tokens = [f"{1000 + index}:1" for index in range(aa)]
    tank_tokens = [f"{2000 + index}:1" for index in range(total - aa)]
    field_total = (3 * total) // 4
    field_aa = max(1, min((3 * aa) // 4, aa - 1))
    field = sorted(aa_tokens[:field_aa] + tank_tokens[: field_total - field_aa])
    home = sorted(set(aa_tokens + tank_tokens) - set(field))
    return field, home


def start_campaign(
    *,
    total: int = 24,
    aa: int = 2,
    seed: int = 0,
    acu_health: float = 1.0,
    reason: str = "frontier_expansion",
    site_key: str = "cluster-a",
    cluster_key: str = "cluster-a",
    position: list[float] | None = None,
    reachable: bool = True,
    extra_markers: list[dict[str, Any]] | None = None,
) -> tuple[Any, Any, Any, list[Any], Any]:
    harness = make_harness()
    harness.controller.fieldCampaignEnabled = True
    harness.controller.crossMapOffenseEnabled = False
    position = position or [80, 2, 20]
    install_markers(
        harness,
        [
            marker(site_key, position[0], position[2], reachable=reachable),
            *(extra_markers or []),
        ],
    )
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        health=acu_health * 100,
        maxHealth=100,
        position=[10, 2, 20],
    )
    engineer = harness.unit(
        entityId=2,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    combat = [
        harness.unit(
            entityId=1000 + index,
            blueprintId="uel0104",
            position=[10 + index * 0.01, 2, 20],
        )
        for index in range(aa)
    ] + [
        harness.unit(
            entityId=2000 + index,
            blueprintId="uel0201",
            position=[10 + index * 0.01, 2, 20],
        )
        for index in range(total - aa)
    ]
    shuffled = [acu, engineer, *combat]
    random.Random(seed).shuffle(shuffled)
    harness.brain.units = harness.lua.table_from(shuffled)
    observation = harness.observe()
    execute_intents(
        harness,
        [
            {
                "kind": "build_structure",
                "actorToken": "2:1",
                "buildRole": "mass_extractor",
                "siteKey": site_key,
                "clusterKey": cluster_key,
                "position": position,
                "priority": 22,
                "reason": reason,
            }
        ],
        observation,
    )
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Moving": True})
    return harness, acu, engineer, combat, reconcile(harness)


def layered_marker(
    key: str,
    x: float,
    z: float,
    *,
    engineer_reachable: bool = True,
    land_reachable: bool = True,
) -> dict[str, Any]:
    value = marker(key, x, z, reachable=engineer_reachable)
    value["engineerReachable"] = engineer_reachable
    value["landReachable"] = land_reachable
    return value


def controller_marker(harness: Any, key: str) -> Any:
    for index in range(1, len(harness.controller.markers.mass) + 1):
        candidate = harness.controller.markers.mass[index]
        if candidate.key == key:
            return candidate
    raise AssertionError(f"missing marker {key}")


def activate_campaign(harness: Any, observation: Any) -> tuple[dict[str, Any], Any]:
    intents = campaign_intents(harness, observation)
    assert len(intents) == 1
    execute_intents(harness, intents, observation)
    current = reconcile(harness)
    return intents[0], current


@pytest.mark.parametrize("total,aa", itertools.product([24, 25, 122], [2, 3, 14]))
@pytest.mark.parametrize("seed", range(4))
def test_campaign_allocates_exact_deterministic_three_quarters_cohorts(
    total: int,
    aa: int,
    seed: int,
) -> None:
    harness, _, _, _, observation = start_campaign(total=total, aa=aa, seed=seed)
    macro = plain(observation)["macro"]
    field, home = expected_initial_cohorts(total, aa)

    assert macro.get("campaignState") == "awaiting_order"
    assert macro.get("campaignCluster") == "cluster-a"
    assert macro.get("campaignObjective") == "cluster-a"
    assert macro.get("fieldTokens") == field
    assert macro.get("homeTokens") == home
    assert macro.get("fieldUnits") == (3 * total) // 4
    assert macro.get("homeUnits") == total - (3 * total) // 4
    assert macro.get("fieldAa") == max(1, min((3 * aa) // 4, aa - 1))
    assert macro.get("homeAa") == aa - macro.get("fieldAa")
    campaign = campaign_intents(harness, observation)
    assert len(campaign) == 1
    assert campaign[0].get("mode") == "activate"
    assert campaign[0].get("actorTokens") == field
    assert not [intent for intent in policy_intents(harness, observation) if intent.get("kind") == "frontier_screen"]


@pytest.mark.parametrize("total,aa", [(23, 2), (24, 1), (8, 1), (4, 0)])
def test_early_campaign_keeps_a_small_screen_until_both_field_gates_are_met(total: int, aa: int) -> None:
    harness, _, _, _, observation = start_campaign(total=total, aa=aa)
    macro = plain(observation)["macro"]
    expected_field = min(4, max(0, total - 4))

    assert macro.get("campaignState") == "early_awaiting_order"
    assert macro.get("fieldUnits") == expected_field
    assert macro.get("homeUnits") == total - expected_field
    assert len(macro.get("fieldTokens") or []) == expected_field
    assert len(macro.get("fieldTokens") or []) <= 4


def test_activation_orders_exact_full_field_once_and_stays_quiet_for_600_ticks() -> None:
    harness, _, engineer, _, observation = start_campaign()
    field, _ = expected_initial_cohorts(24, 2)
    intent, _ = activate_campaign(harness, observation)

    assert intent["actorTokens"] == field
    assert plain(harness.calls.sequence)[:2] == ["clear", "guard"]
    assert actor_tokens_from_call(harness.calls.clear[1]) == field
    assert actor_tokens_from_call(harness.calls.guard[1]) == field
    assert harness.calls.guard[1].target.options.entityId == engineer.options.entityId
    assert harness.controller.fieldCampaign.state == "active"
    assert harness.controller.fieldCampaign.fullFieldOrders == 1
    clear_count = len(harness.calls.clear)
    guard_count = len(harness.calls.guard)

    for tick, x in [(1, 20), (50, 35), (299, 55), (599, 76)]:
        harness.brain.tick = tick
        engineer.options.position = lua_value(harness.lua, [x, 2, 20])
        current = reconcile(harness)
        execute_intents(harness, campaign_intents(harness, current), current)

    assert len(harness.calls.clear) == clear_count
    assert len(harness.calls.guard) == guard_count
    assert harness.controller.fieldCampaign.fullFieldOrders == 1


def test_ian_selected_frontier_churn_cannot_recreate_the_same_live_campaign_543_times() -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    clear_count = len(harness.calls.clear)
    guard_count = len(harness.calls.guard)

    for tick in range(1, 544):
        harness.brain.tick = tick
        harness.controller.selectedFrontierCluster = "volatile-a" if tick % 2 else "volatile-b"
        harness.controller.selectedFrontierSite = f"volatile-{tick}"
        current = reconcile(harness)
        execute_intents(harness, campaign_intents(harness, current), current)

    assert harness.controller.fieldCampaign.clusterKey == "cluster-a"
    assert harness.controller.fieldCampaign.objectiveKey == "cluster-a"
    # The campaign never reacts to the volatile selection.  The sole extra
    # full-field order is the independently bounded tick-300 stuck recovery.
    assert harness.controller.fieldCampaign.fullFieldOrders == 2
    assert len(harness.calls.clear) - clear_count <= 1
    assert len(harness.calls.guard) - guard_count <= 1


def test_new_units_fill_the_more_under_target_cohort_without_moving_survivors() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    original_field, original_home = expected_initial_cohorts(24, 2)
    home_reinforcement = harness.unit(entityId=9000, blueprintId="uel0201", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from([acu, engineer, *reversed(combat), home_reinforcement])
    harness.brain.tick = 10

    at_25 = reconcile(harness)
    macro_25 = plain(at_25)["macro"]

    assert macro_25.get("fieldTokens") == original_field
    assert macro_25.get("homeTokens") == sorted([*original_home, "9000:1"])
    assert campaign_intents(harness, at_25) == []
    field_reinforcement = harness.unit(entityId=9001, blueprintId="uel0201", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from(
        [field_reinforcement, home_reinforcement, *combat, engineer, acu]
    )
    harness.brain.tick = 20

    at_26 = reconcile(harness)
    campaign = campaign_intents(harness, at_26)

    assert plain(at_26)["macro"].get("fieldTokens") == sorted([*original_field, "9001:1"])
    assert plain(at_26)["macro"].get("homeTokens") == sorted([*original_home, "9000:1"])
    assert len(campaign) == 1
    assert campaign[0].get("mode") == "reinforce"
    assert campaign[0].get("actorTokens") == ["9001:1"]
    clear_count = len(harness.calls.clear)
    execute_intents(harness, campaign, at_26)
    assert actor_tokens_from_call(harness.calls.clear[clear_count + 1]) == ["9001:1"]


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_field_actor_lifecycle_releases_only_the_exact_dead_generation(mutation: str) -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    old_field, old_home = expected_initial_cohorts(24, 2)
    victim = combat[0]
    units = [acu, engineer, *combat]
    replacement = None
    if mutation == "dead":
        victim.Dead = True
        units.remove(victim)
    elif mutation == "captured":
        victim.options.army = 2
    else:
        replacement = harness.unit(
            entityId=victim.options.entityId,
            blueprintId="uel0104",
            position=[10, 2, 20],
        )
        units[units.index(victim)] = replacement
    harness.brain.units = harness.lua.table_from(list(reversed(units)))
    harness.brain.tick = 10

    current = reconcile(harness)
    macro = plain(current)["macro"]

    assert "1000:1" not in (macro.get("fieldTokens") or [])
    assert "1000:1" not in (macro.get("homeTokens") or [])
    assert set(old_field) - {"1000:1"} <= set(macro.get("fieldTokens") or [])
    assert set(old_home) <= set(macro.get("homeTokens") or [])
    if replacement is not None:
        assert "1000:2" in (macro.get("fieldTokens") or [])
        reinforce = campaign_intents(harness, current)
        assert reinforce and reinforce[0].get("actorTokens") == ["1000:2"]


def test_ordinary_contact_and_same_tick_reinforcement_use_disjoint_home_and_field_actors() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    home_extra = harness.unit(entityId=9000, blueprintId="uel0201", position=[10, 2, 20])
    field_extra = harness.unit(entityId=9001, blueprintId="uel0201", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from([acu, engineer, *combat, home_extra, field_extra])
    enemy = harness.unit(
        entityId=99000,
        blueprintId="uel0201",
        army=2,
        position=[40, 2, 20],
    )
    harness.brain.enemies = harness.lua.table_from([enemy])
    harness.brain.tick = 20

    current = reconcile(harness)
    intents = policy_intents(harness, current)
    macro = plain(current)["macro"]
    defend = [intent for intent in intents if intent.get("kind") == "defend_wave"]
    campaign = [intent for intent in intents if intent.get("kind") == CAMPAIGN_KIND]

    assert len(defend) == 1 and len(campaign) == 1
    assert set(defend[0].get("actorTokens") or []) == set(macro.get("homeTokens") or [])
    assert campaign[0].get("actorTokens") == ["9001:1"]
    assert set(defend[0]["actorTokens"]).isdisjoint(campaign[0]["actorTokens"])
    execute_intents(harness, intents, current)
    assert harness.controller.fieldCampaign.clusterKey == "cluster-a"
    assert set(plain(harness.controller.fieldCampaign.fieldTokens)) == set(macro["fieldTokens"])


@pytest.mark.parametrize("failure", ["clear", "guard"])
def test_full_field_activation_failure_is_atomic_and_immediately_retryable(failure: str) -> None:
    harness, _, _, _, observation = start_campaign()
    field, _ = expected_initial_cohorts(24, 2)
    campaign = campaign_intents(harness, observation)
    assert campaign and campaign[0].get("actorTokens") == field
    if failure == "clear":
        harness.calls.failClear = True
    else:
        harness.calls.failGuard = True

    execute_intents(harness, campaign, observation)

    assert harness.controller.fieldCampaign.state == "awaiting_order"
    assert harness.controller.fieldCampaign.fullFieldOrders == 0
    assert plain(harness.controller.fieldCampaign.fieldTokens) == field
    if failure == "clear":
        assert len(harness.calls.guard) == 0
        harness.calls.failClear = False
    else:
        assert len(harness.calls.guard) == 1
        harness.calls.failGuard = False
    execute_intents(harness, campaign, observation)
    assert harness.controller.fieldCampaign.state == "active"
    assert harness.controller.fieldCampaign.fullFieldOrders == 1


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_campaign_preflight_rejects_stale_field_actor_before_any_command(mutation: str) -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    campaign = campaign_intents(harness, observation)
    assert campaign
    victim = combat[0]
    if mutation == "dead":
        victim.Dead = True
    elif mutation == "captured":
        victim.options.army = 2
    else:
        replacement = harness.unit(
            entityId=victim.options.entityId,
            blueprintId="uel0104",
            position=[10, 2, 20],
        )
        harness.brain.units = harness.lua.table_from([acu, engineer, replacement, *combat[1:]])
        harness.observe()

    execute_intents(harness, campaign, observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert len(harness.calls.move) == 0
    assert harness.controller.fieldCampaign.state == "awaiting_order"


@pytest.mark.parametrize(
    "malformed",
    [
        {"mode": "unknown"},
        {"mode": "activate", "actorTokens": ["1000:1", "1000:1"]},
        {"mode": "activate", "actorTokens": "1000:1"},
        {"mode": "activate", "actorTokens": 1000},
        {"mode": "activate", "actorTokens": {"token": "1000:1"}},
        {"mode": "activate", "position": ["bad", 0, 20]},
        {"mode": "activate", "campaignSerial": "bad"},
        {"mode": "activate", "campaignSerial": "1"},
        {"mode": "activate", "clusterKey": "wrong-cluster"},
        {"mode": "activate", "objectiveKey": "wrong-objective"},
    ],
)
def test_malformed_campaign_intents_fail_closed_without_mutating_live_mission(
    malformed: dict[str, Any],
) -> None:
    harness, _, _, _, observation = start_campaign()
    assert harness.controller.fieldCampaign is not None
    before = plain(harness.controller.fieldCampaign)
    injected = {
        "kind": CAMPAIGN_KIND,
        "mode": "activate",
        "actorTokens": expected_initial_cohorts(24, 2)[0],
        "engineerToken": "2:1",
        "position": [80, 2, 20],
        "campaignSerial": 1,
        "clusterKey": "cluster-a",
        "objectiveKey": "cluster-a",
        "priority": 24,
    }
    injected.update(malformed)

    execute_intents(harness, [injected], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert len(harness.calls.move) == 0
    assert plain(harness.controller.fieldCampaign) == before


@pytest.mark.parametrize("failure", ["clear", "move"])
def test_emergency_recall_failure_is_atomic_and_immediately_retryable(failure: str) -> None:
    harness, acu, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    field, home = expected_initial_cohorts(24, 2)
    acu.options.health = 69
    harness.brain.tick = 10
    current = reconcile(harness)
    recall = campaign_intents(harness, current)

    assert len(recall) == 1
    assert recall[0].get("mode") == "recall"
    assert recall[0].get("actorTokens") == field
    before = plain(harness.controller.fieldCampaign)
    if failure == "clear":
        harness.calls.failClear = True
    else:
        harness.calls.failMove = True
    execute_intents(harness, recall, current)

    assert plain(harness.controller.fieldCampaign) == before
    assert plain(harness.controller.fieldCampaign.fieldTokens) == field
    assert plain(harness.controller.fieldCampaign.homeTokens) == home
    if failure == "clear":
        assert len(harness.calls.move) == 0
        harness.calls.failClear = False
    else:
        assert len(harness.calls.move) == 1
        harness.calls.failMove = False
    execute_intents(harness, recall, current)
    assert harness.controller.fieldCampaign.state == "recalled"
    assert harness.controller.fieldCampaign.emergency is True
    assert harness.controller.fieldCampaign.modeSwitches == before["modeSwitches"] + 1


def test_emergency_hysteresis_recalls_once_then_resumes_same_valid_mission_once() -> None:
    harness, acu, engineer, _, observation = start_campaign()
    activate_campaign(harness, observation)
    field, home = expected_initial_cohorts(24, 2)
    acu.options.health = 69
    harness.brain.tick = 20
    low = reconcile(harness)
    recall = campaign_intents(harness, low)
    assert len(recall) == 1 and recall[0].get("mode") == "recall"
    execute_intents(harness, recall, low)
    recall_clear = len(harness.calls.clear)
    recall_move = len(harness.calls.move)

    for tick in [21, 100, 500]:
        harness.brain.tick = tick
        low_again = reconcile(harness)
        execute_intents(harness, campaign_intents(harness, low_again), low_again)

    assert len(harness.calls.clear) == recall_clear
    assert len(harness.calls.move) == recall_move
    assert harness.controller.fieldCampaign.state == "recalled"
    assert plain(harness.controller.fieldCampaign.fieldTokens) == field
    assert plain(harness.controller.fieldCampaign.homeTokens) == home

    acu.options.health = 75
    harness.brain.tick = 501
    first_clear_tick = reconcile(harness)
    assert campaign_intents(harness, first_clear_tick) == []
    harness.brain.tick = 800
    before_resume = reconcile(harness)
    assert campaign_intents(harness, before_resume) == []
    harness.brain.tick = 801
    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)

    assert len(resume) == 1 and resume[0].get("mode") == "resume"
    assert resume[0].get("actorTokens") == field
    execute_intents(harness, resume, ready)
    assert harness.calls.guard[len(harness.calls.guard)].target.options.entityId == engineer.options.entityId
    assert harness.controller.fieldCampaign.state == "active"
    assert harness.controller.fieldCampaign.emergency is False
    assert harness.controller.fieldCampaign.modeSwitches == 2

    harness.brain.tick = 1102
    stable = reconcile(harness)
    assert not [
        intent for intent in campaign_intents(harness, stable)
        if intent.get("mode") in {"recall", "resume"}
    ]


@pytest.mark.parametrize("tick,expected", [(299, 0), (300, 1), (599, 0), (600, 1)])
def test_stuck_recovery_has_an_exact_300_tick_lower_bound_and_rate_limit(
    tick: int,
    expected: int,
) -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    if tick >= 300:
        harness.brain.tick = 300
        first = reconcile(harness)
        first_recovery = [
            intent for intent in campaign_intents(harness, first)
            if intent.get("mode") == "recover"
        ]
        assert len(first_recovery) == 1
        execute_intents(harness, first_recovery, first)
    harness.brain.tick = tick
    current = reconcile(harness)
    recover = [
        intent for intent in campaign_intents(harness, current)
        if intent.get("mode") == "recover"
    ]

    if tick == 300:
        # The tick-300 order above is the sole recovery for this boundary.
        assert recover == []
    else:
        assert len(recover) == expected
    assert harness.controller.fieldCampaign.clusterKey == "cluster-a"
    assert harness.controller.fieldCampaign.objectiveKey == "cluster-a"


def inject_structure_operation(
    harness: Any,
    *,
    actor_token: str,
    site_key: str,
    position: list[float],
    reason: str,
    cluster_key: str | None = None,
) -> None:
    harness.controller.pending[actor_token] = lua_value(
        harness.lua,
        {
            "kind": "build_structure",
            "actorToken": actor_token,
            "actorReference": harness.controller.unitRefs[actor_token],
            "role": "engineer",
            "buildRole": "mass_extractor",
            "siteKey": site_key,
            "clusterKey": cluster_key,
            "position": position,
            "reason": reason,
            "issuedTick": harness.brain.tick,
            "deadlineTick": harness.brain.tick + 5000,
            "lastProgressTick": harness.brain.tick,
            "phase": "travelling",
            "accepted": True,
        },
    )
    harness.controller.reservations[site_key] = lua_value(
        harness.lua,
        {"actorToken": actor_token, "kind": "build_structure"},
    )


@pytest.mark.parametrize("failure", [None, "clear", "guard"])
def test_rebuild_retargets_the_existing_campaign_atomically_without_cluster_churn(
    failure: str | None,
) -> None:
    harness, acu, original_engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    install_markers(
        harness,
        [
            layered_marker("cluster-a", 80, 20),
            layered_marker("lost-home", 35, 20),
        ],
    )
    rebuild_engineer = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[20, 2, 20],
        canBuild={"ueb1103": True},
        idleState=False,
        states=lua_value(harness.lua, {"Moving": True}),
    )
    harness.brain.units = harness.lua.table_from([acu, original_engineer, rebuild_engineer, *combat])
    harness.brain.tick = 20
    harness.observe()
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="lost-home",
        position=[35, 2, 20],
        reason="rebuild_mex",
    )
    harness.controller.selectedFrontierCluster = "speculative-next"
    harness.controller.selectedFrontierSite = "speculative-site"
    current = reconcile(harness)
    retarget = campaign_intents(harness, current)

    assert len(retarget) == 1 and retarget[0].get("mode") == "retarget"
    assert retarget[0].get("engineerToken") == "3:1"
    assert retarget[0].get("position") == [35, 2, 20]
    assert harness.controller.fieldCampaign.clusterKey == "cluster-a"
    before = plain(harness.controller.fieldCampaign)
    if failure == "clear":
        harness.calls.failClear = True
    elif failure == "guard":
        harness.calls.failGuard = True
    execute_intents(harness, retarget, current)

    if failure:
        assert plain(harness.controller.fieldCampaign) == before
        if failure == "clear":
            harness.calls.failClear = False
        else:
            harness.calls.failGuard = False
        execute_intents(harness, retarget, current)
    assert harness.controller.fieldCampaign.clusterKey == "cluster-a"
    assert harness.controller.fieldCampaign.objectiveKey == "lost-home"
    assert harness.controller.fieldCampaign.engineerToken == "3:1"
    assert harness.calls.guard[len(harness.calls.guard)].target.options.entityId == rebuild_engineer.options.entityId


def test_speculative_next_cluster_does_not_preempt_unfinished_current_campaign_cluster() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    speculative_engineer = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
        idleState=False,
        states=lua_value(harness.lua, {"Moving": True}),
    )
    harness.brain.units = harness.lua.table_from([acu, engineer, speculative_engineer, *combat])
    harness.brain.tick = 30
    harness.observe()
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="cluster-b-site",
        cluster_key="cluster-b",
        position=[140, 2, 20],
        reason="frontier_expansion",
    )
    current = reconcile(harness)

    assert harness.controller.fieldCampaign.clusterKey == "cluster-a"
    assert harness.controller.fieldCampaign.objectiveKey == "cluster-a"
    assert not [
        intent for intent in campaign_intents(harness, current)
        if intent.get("mode") == "retarget"
    ]


def test_cluster_must_be_fully_owned_and_held_150_ticks_before_one_transition() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    mex = harness.unit(
        entityId=50,
        blueprintId="ueb1103",
        position=[80, 2, 20],
        fraction=1,
    )
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from([acu, engineer, mex, *combat])
    harness.brain.tick = 100
    holding = reconcile(harness)

    assert plain(holding)["macro"].get("campaignState") == "holding"
    assert harness.controller.fieldCampaign.heldSinceTick == 100
    for tick in [101, 249]:
        harness.brain.tick = tick
        still_holding = reconcile(harness)
        assert plain(still_holding)["macro"].get("campaignState") == "holding"
    harness.brain.tick = 250
    completed = reconcile(harness)

    assert plain(completed)["macro"].get("campaignState") == "awaiting_objective"
    assert harness.controller.fieldCampaign is not None
    transition_events = [line for line in harness.logs if "event=campaign_held" in line]
    assert len(transition_events) == 1
    for tick in [251, 400, 1000]:
        harness.brain.tick = tick
        reconcile(harness)
    assert len([line for line in harness.logs if "event=campaign_held" in line]) == 1


def test_unreachable_objective_never_activates_a_field_campaign() -> None:
    harness, _, _, _, observation = start_campaign(reachable=False)
    macro = plain(observation)["macro"]

    assert macro.get("campaignState") == "idle"
    assert campaign_intents(harness, observation) == []
    assert harness.controller.fieldCampaign is None


@pytest.mark.parametrize(
    "bad_position",
    [None, [], [80, 20], ["bad", 2, 20], [float("inf"), 2, 20]],
)
def test_invalid_or_malformed_objective_cannot_create_or_mutate_campaign(
    bad_position: list[Any] | None,
) -> None:
    harness, _, _, _, observation = start_campaign()
    before = plain(harness.controller.fieldCampaign)
    operation = harness.controller.pending["2:1"]
    operation.position = lua_value(harness.lua, bad_position) if bad_position is not None else None
    harness.controller.fieldCampaign = None
    harness.brain.tick = 1
    current = reconcile(harness)

    assert campaign_intents(harness, current) == []
    assert harness.controller.fieldCampaign is None
    assert before.get("clusterKey") == "cluster-a"


def test_campaign_telemetry_is_scalar_low_volume_and_emits_semantic_transitions_once() -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    harness.brain.tick = 300
    harness.lua.globals().Controller.Step(harness.controller)
    snapshots = [line for line in harness.logs if "event=snapshot" in line]
    assert len(snapshots) == 1
    latest = snapshots[-1]
    for field in {
        "campaign_state=active",
        "campaign_cluster=cluster-a",
        "campaign_objective=cluster-a",
        "field_units=18",
        "field_aa=1",
        "home_units=6",
        "home_aa=1",
        "mission_age=300",
        "last_campaign_progress_tick=0",
        "full_field_orders=1",
        "mode_switches=0",
        "campaign_emergency=false",
    }:
        assert field in latest
    harness.brain.tick = 301
    harness.lua.globals().Controller.Step(harness.controller)
    assert len([line for line in harness.logs if "event=snapshot" in line]) == 1
    starts = [line for line in harness.logs if "event=campaign_started" in line]
    assert len(starts) == 1


def test_campaign_observation_keeps_the_existing_fair_query_boundary() -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    own_before = len(harness.calls.own)
    enemy_before = len(harness.calls.enemy)
    harness.brain.tick = 10

    current = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, current), current)

    assert len(harness.calls.own) - own_before == 1
    assert len(harness.calls.enemy) - enemy_before == 1


def test_campaign_hard_disables_legacy_screen_and_every_cross_map_offense_executor() -> None:
    harness, _, _, _, observation = start_campaign()
    field, _ = expected_initial_cohorts(24, 2)
    enemy_position = plain(observation.targetPosition)
    injected = [
        {
            "kind": "frontier_screen",
            "engineerToken": "2:1",
            "actorTokens": field[:4],
            "clusterKey": "cluster-a",
            "priority": 1,
        }
    ] + [
        {
            "kind": kind,
            "acuToken": "1:1",
            "actorTokens": field,
            "position": enemy_position,
            "priority": 2,
        }
        for kind in sorted(FORBIDDEN_OFFENSE)
    ]
    harness.controller.crossMapOffenseEnabled = True

    execute_intents(harness, injected, observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert len(harness.calls.move) == 0
    assert len(harness.calls.aggressive) == 0
    assert harness.controller.frontierMission is None
    assert harness.controller.waveAssignments is not None


def test_campaign_policy_never_targets_enemy_spawn_and_static_runtime_boundary_stays_minimal() -> None:
    harness, _, _, _, observation = start_campaign()
    intents = policy_intents(harness, observation)
    enemy_position = plain(observation.targetPosition)

    assert not [intent for intent in intents if intent.get("kind") in FORBIDDEN_OFFENSE]
    assert not [intent for intent in intents if intent.get("position") == enemy_position]
    controller_source = source("lua/AI/Overmind4/Controller.lua")
    policy_source = source("lua/AI/Overmind4/Policy.lua")
    assert "BuilderManager" not in controller_source + policy_source
    assert "PlatoonFormManager" not in controller_source + policy_source
    assert controller_source.count("import(") == 5


def test_unit_list_reordering_and_economy_contact_flicker_do_not_reshuffle_cohorts() -> None:
    harness, acu, engineer, combat, observation = start_campaign(seed=1)
    activate_campaign(harness, observation)
    field, home = expected_initial_cohorts(24, 2)
    enemy = harness.unit(entityId=99000, blueprintId="uel0201", army=2, position=[40, 2, 20])

    for tick, shuffled in enumerate(
        [list(reversed(combat)), combat[::2] + combat[1::2], list(combat)],
        start=10,
    ):
        harness.brain.massIncome = 0.2 if tick % 2 else 5
        harness.brain.massRequested = 3 if tick % 2 else 1
        harness.brain.enemies = harness.lua.table_from([enemy] if tick % 2 else [])
        harness.brain.units = harness.lua.table_from([*shuffled, engineer, acu])
        harness.brain.tick = tick
        current = reconcile(harness)

        assert plain(current)["macro"].get("fieldTokens") == field
        assert plain(current)["macro"].get("homeTokens") == home


def test_cluster_hold_requires_150_continuous_ticks_and_resets_after_one_tick_loss() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[80, 2, 20])
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from([acu, engineer, mex, *combat])
    harness.brain.tick = 100
    reconcile(harness)
    harness.brain.tick = 249
    at_149 = reconcile(harness)
    assert plain(at_149)["macro"].get("campaignState") == "holding"

    harness.brain.units = harness.lua.table_from([acu, engineer, *combat])
    harness.brain.tick = 250
    lost_for_one_tick = reconcile(harness)
    assert plain(lost_for_one_tick)["macro"].get("campaignState") == "active"
    assert harness.controller.fieldCampaign.heldSinceTick is None

    harness.brain.units = harness.lua.table_from([acu, engineer, mex, *combat])
    harness.brain.tick = 251
    reconcile(harness)
    harness.brain.tick = 400
    reset_149 = reconcile(harness)
    assert plain(reset_149)["macro"].get("campaignState") == "holding"
    harness.brain.tick = 401
    held_150 = reconcile(harness)
    assert plain(held_150)["macro"].get("campaignState") == "awaiting_objective"


@pytest.mark.parametrize("health,recall", [(69.9, True), (70.0, False), (70.1, False)])
def test_emergency_recall_health_boundary_is_strictly_below_point_seven(
    health: float,
    recall: bool,
) -> None:
    harness, acu, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    acu.options.health = health
    harness.brain.tick = 10
    current = reconcile(harness)
    modes = [intent.get("mode") for intent in campaign_intents(harness, current)]
    assert ("recall" in modes) is recall


def test_resume_requires_point_seven_five_for_300_continuous_ticks_and_resets_on_dip() -> None:
    harness, acu, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)

    acu.options.health = 75
    harness.brain.tick = 20
    reconcile(harness)
    harness.brain.tick = 319
    assert campaign_intents(harness, reconcile(harness)) == []
    acu.options.health = 74.9
    harness.brain.tick = 320
    assert campaign_intents(harness, reconcile(harness)) == []
    acu.options.health = 75
    harness.brain.tick = 321
    reconcile(harness)
    harness.brain.tick = 620
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 621
    ready = campaign_intents(harness, reconcile(harness))
    assert len(ready) == 1 and ready[0].get("mode") == "resume"


@pytest.mark.parametrize("failure", ["clear", "guard"])
def test_failed_stuck_recovery_is_atomic_immediately_retryable_then_rate_limited(
    failure: str,
) -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    harness.brain.tick = 300
    current = reconcile(harness)
    recover = campaign_intents(harness, current)
    assert len(recover) == 1 and recover[0].get("mode") == "recover"
    before = plain(harness.controller.fieldCampaign)
    if failure == "clear":
        harness.calls.failClear = True
    else:
        harness.calls.failGuard = True
    execute_intents(harness, recover, current)
    assert plain(harness.controller.fieldCampaign) == before
    if failure == "clear":
        harness.calls.failClear = False
    else:
        harness.calls.failGuard = False
    execute_intents(harness, recover, current)
    assert harness.controller.fieldCampaign.recoveryOrders == 1
    assert harness.controller.fieldCampaign.lastRecoveryAttemptTick == 300
    harness.brain.tick = 599
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 600
    again = campaign_intents(harness, reconcile(harness))
    assert len(again) == 1 and again[0].get("mode") == "recover"


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_campaign_guard_actor_lifecycle_is_revalidated_before_first_full_order(
    mutation: str,
) -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activation = campaign_intents(harness, observation)
    assert activation
    if mutation == "dead":
        engineer.Dead = True
    elif mutation == "captured":
        engineer.options.army = 2
    else:
        replacement = harness.unit(
            entityId=2,
            blueprintId="uel0105",
            position=[12, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([acu, replacement, *combat])
        harness.observe()
    execute_intents(harness, activation, observation)
    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert harness.controller.fieldCampaign.state == "awaiting_order"


def test_cancelled_campaign_operation_cannot_activate_stale_guard_mission() -> None:
    harness, _, _, _, observation = start_campaign()
    activation = campaign_intents(harness, observation)
    assert activation
    harness.controller.pending["2:1"] = None
    harness.controller.reservations["cluster-a"] = None

    execute_intents(harness, activation, observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert harness.controller.fieldCampaign.state == "awaiting_order"


def test_malicious_defense_intent_cannot_clear_or_order_field_cohort() -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    field, home = expected_initial_cohorts(24, 2)
    current = reconcile(harness)
    clear_before = len(harness.calls.clear)
    aggressive_before = len(harness.calls.aggressive)

    execute_intents(
        harness,
        [
            {
                "kind": "defend_wave",
                "actorTokens": field,
                "position": [40, 2, 20],
                "priority": 2,
                "reason": "malicious_overlap",
            }
        ],
        current,
    )

    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.aggressive) == aggressive_before
    execute_intents(
        harness,
        [
            {
                "kind": "defend_wave",
                "actorTokens": [field[0], *home],
                "position": [40, 2, 20],
                "priority": 2,
                "reason": "mixed_overlap",
            }
        ],
        current,
    )
    assert actor_tokens_from_call(harness.calls.aggressive[len(harness.calls.aggressive)]) == home


def test_campaign_guard_engineer_reuses_cached_member_before_any_unrelated_work() -> None:
    second = marker("cluster-a-2", 90, 20)
    harness, acu, engineer, combat, observation = start_campaign(extra_markers=[second])
    activate_campaign(harness, observation)
    mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[80, 2, 20])
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from([acu, engineer, mex, *combat])
    harness.brain.tick = 100
    current = reconcile(harness)
    builds = [
        intent for intent in policy_intents(harness, current)
        if intent.get("kind") in {"build_structure", "assist_structure"}
            and intent.get("actorToken") == "2:1"
    ]

    assert len(builds) == 1
    assert builds[0].get("siteKey") == "cluster-a-2"
    assert builds[0].get("clusterKey") == "cluster-a"
    assert builds[0].get("reason") == "frontier_expansion"


def test_only_one_campaign_connected_frontier_job_is_planned_at_a_time() -> None:
    second = marker("cluster-a-2", 90, 20)
    harness, acu, engineer, combat, observation = start_campaign(extra_markers=[second])
    extra_engineer = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[13, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([acu, engineer, extra_engineer, *combat])
    harness.brain.tick = 10
    current = reconcile(harness)
    frontier = [
        intent for intent in policy_intents(harness, current)
        if intent.get("reason") == "frontier_expansion"
    ]
    assert frontier == []


def test_cached_lost_member_rebuild_preempts_unrelated_rebuild_even_with_later_actor_token() -> None:
    second = marker("cluster-a-2", 90, 20)
    harness, acu, engineer, combat, observation = start_campaign(extra_markers=[second])
    activate_campaign(harness, observation)
    unrelated = harness.unit(entityId=3, blueprintId="uel0105", position=[20, 2, 20])
    cached = harness.unit(entityId=4, blueprintId="uel0105", position=[20, 2, 20])
    unrelated.options.idleState = False
    unrelated.options.states = lua_value(harness.lua, {"Moving": True})
    cached.options.idleState = False
    cached.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.units = harness.lua.table_from([acu, engineer, unrelated, cached, *combat])
    harness.brain.tick = 20
    harness.observe()
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="unrelated-lost",
        position=[30, 2, 20],
        reason="rebuild_mex",
    )
    inject_structure_operation(
        harness,
        actor_token="4:1",
        site_key="cluster-a-2",
        position=[90, 2, 20],
        reason="rebuild_mex",
    )
    current = reconcile(harness)
    retarget = campaign_intents(harness, current)
    assert len(retarget) == 1
    assert retarget[0].get("mode") == "retarget"
    assert retarget[0].get("engineerToken") == "4:1"


def test_cached_member_rebuild_with_cluster_none_keeps_same_campaign_identity() -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    operation = harness.controller.pending["2:1"]
    operation.reason = "rebuild_mex"
    operation.clusterKey = None
    harness.brain.tick = 10
    current = reconcile(harness)

    assert harness.controller.fieldCampaign.clusterKey == "cluster-a"
    assert harness.controller.fieldCampaign.objectiveKey == "cluster-a"
    assert not [
        intent for intent in campaign_intents(harness, current)
        if intent.get("mode") == "retarget"
    ]


@pytest.mark.parametrize("failure", [None, "clear", "guard"])
def test_held_campaign_transitions_to_next_connected_objective_once_and_atomically(
    failure: str | None,
) -> None:
    next_marker = marker("cluster-b", 140, 20)
    harness, acu, engineer, combat, observation = start_campaign(extra_markers=[next_marker])
    activate_campaign(harness, observation)
    original = plain(harness.controller.fieldCampaign)
    mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[80, 2, 20])
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from([acu, engineer, mex, *combat])
    harness.brain.tick = 100
    reconcile(harness)
    harness.brain.tick = 250
    held = reconcile(harness)
    assert plain(held)["macro"].get("campaignState") == "awaiting_objective"
    next_engineer = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[20, 2, 20],
        canBuild={"ueb1103": True},
        idleState=False,
        states=lua_value(harness.lua, {"Moving": True}),
    )
    harness.brain.units = harness.lua.table_from([acu, engineer, next_engineer, mex, *combat])
    harness.brain.tick = 251
    harness.observe()
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="cluster-b",
        cluster_key="cluster-b",
        position=[140, 2, 20],
        reason="frontier_expansion",
    )
    current = reconcile(harness)
    transition = campaign_intents(harness, current)
    assert len(transition) == 1 and transition[0].get("mode") == "transition"
    assert transition[0].get("actorTokens") == original["fieldTokens"]
    before = plain(harness.controller.fieldCampaign)
    if failure == "clear":
        harness.calls.failClear = True
    elif failure == "guard":
        harness.calls.failGuard = True
    execute_intents(harness, transition, current)
    if failure:
        assert plain(harness.controller.fieldCampaign) == before
        if failure == "clear":
            harness.calls.failClear = False
        else:
            harness.calls.failGuard = False
        execute_intents(harness, transition, current)
    assert harness.controller.fieldCampaign.serial == original["serial"]
    assert harness.controller.fieldCampaign.clusterKey == "cluster-b"
    assert harness.controller.fieldCampaign.objectiveKey == "cluster-b"
    assert plain(harness.controller.fieldCampaign.fieldTokens) == original["fieldTokens"]


@pytest.mark.parametrize("invalid", ["missing", "unreachable"])
def test_invalid_objective_releases_only_the_objective_not_sticky_cohorts(invalid: str) -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    field, home = expected_initial_cohorts(24, 2)
    if invalid == "missing":
        harness.controller.markers.mass = lua_value(harness.lua, [])
    else:
        harness.controller.markers.mass[1].reachable = False
        harness.controller.markers.mass[1].engineerReachable = False
        harness.controller.markers.mass[1].landReachable = False
    harness.brain.tick = 10
    current = reconcile(harness)
    macro = plain(current)["macro"]

    assert macro.get("campaignState") == "awaiting_objective"
    assert macro.get("fieldTokens") == field
    assert macro.get("homeTokens") == home


def test_transient_site_backoff_does_not_invalidate_or_transition_campaign() -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    harness.controller.blockedSites["cluster-a"] = 1000
    harness.brain.tick = 10
    current = reconcile(harness)

    assert plain(current)["macro"].get("campaignState") == "active"
    assert harness.controller.fieldCampaign.clusterKey == "cluster-a"
    assert campaign_intents(harness, current) == []


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_field_lifecycle_before_activation_reconciles_pending_full_order_to_exact_live_tokens(
    mutation: str,
) -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    victim = combat[0]
    units = [acu, engineer, *combat]
    if mutation == "dead":
        victim.Dead = True
        units.remove(victim)
    elif mutation == "captured":
        victim.options.army = 2
    else:
        units[units.index(victim)] = harness.unit(
            entityId=victim.options.entityId,
            blueprintId="uel0104",
            position=[10, 2, 20],
        )
    harness.brain.units = harness.lua.table_from(list(reversed(units)))
    harness.brain.tick = 1
    current = reconcile(harness)
    macro = plain(current)["macro"]
    activation = campaign_intents(harness, current)

    assert len(activation) == 1 and activation[0].get("mode") == "activate"
    assert activation[0].get("actorTokens") == macro.get("fieldTokens")
    assert "1000:1" not in activation[0].get("actorTokens")
    if mutation == "recycled":
        assert "1000:2" in activation[0].get("actorTokens")


def test_foundation_fraction_progress_prevents_false_campaign_stuck_recovery() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    foundation = harness.unit(
        entityId=50,
        blueprintId="ueb1103",
        position=[80, 2, 20],
        fraction=0.1,
    )
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Building": True})
    harness.brain.units = harness.lua.table_from([acu, engineer, foundation, *combat])
    harness.brain.tick = 250
    reconcile(harness)
    foundation.options.fraction = 0.2
    harness.brain.tick = 300
    current = reconcile(harness)

    assert harness.controller.fieldCampaign.lastProgressTick == 300
    assert not [
        intent for intent in campaign_intents(harness, current)
        if intent.get("mode") == "recover"
    ]


def test_awaiting_objective_prefers_rebuild_before_new_frontier_transition() -> None:
    next_marker = marker("cluster-b", 140, 20)
    rebuild_marker = marker("lost-home", 40, 20)
    harness, acu, engineer, combat, observation = start_campaign(
        extra_markers=[next_marker, rebuild_marker]
    )
    activate_campaign(harness, observation)
    mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[80, 2, 20])
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from([acu, engineer, mex, *combat])
    harness.brain.tick = 100
    reconcile(harness)
    harness.brain.tick = 250
    reconcile(harness)
    frontier_engineer = harness.unit(entityId=3, blueprintId="uel0105", position=[20, 2, 20])
    rebuild_engineer = harness.unit(entityId=4, blueprintId="uel0105", position=[20, 2, 20])
    for actor in [frontier_engineer, rebuild_engineer]:
        actor.options.idleState = False
        actor.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, frontier_engineer, rebuild_engineer, mex, *combat]
    )
    harness.brain.tick = 251
    harness.observe()
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="cluster-b",
        cluster_key="cluster-b",
        position=[140, 2, 20],
        reason="frontier_expansion",
    )
    inject_structure_operation(
        harness,
        actor_token="4:1",
        site_key="lost-home",
        position=[40, 2, 20],
        reason="rebuild_mex",
    )
    current = reconcile(harness)
    transition = campaign_intents(harness, current)

    assert len(transition) == 1
    assert transition[0].get("mode") == "transition"
    assert transition[0].get("engineerToken") == "4:1"


def test_crossing_full_campaign_gate_reallocates_once_then_keeps_exact_survivors() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=23, aa=2)
    activate_campaign(harness, observation)
    promoted = harness.unit(entityId=9000, blueprintId="uel0201", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from([acu, engineer, *combat, promoted])
    harness.brain.tick = 10
    current = reconcile(harness)
    field, home = expected_initial_cohorts(24, 2)
    # The additional tank sorts after the original deterministic cohort.
    assert plain(current)["macro"].get("fieldTokens") == field
    assert plain(current)["macro"].get("homeTokens") == sorted([*home[:-1], "9000:1"])
    activation = campaign_intents(harness, current)
    assert len(activation) == 1 and activation[0].get("mode") == "activate"


def test_static_live_runtime_defaults_to_campaign_and_gates_every_legacy_screen_path() -> None:
    controller_source = source("lua/AI/Overmind4/Controller.lua")
    policy_source = source("lua/AI/Overmind4/Policy.lua")

    assert "fieldCampaignEnabled = true" in controller_source
    assert "intent.kind == 'frontier_screen'\n            and controller.fieldCampaignEnabled ~= true" in controller_source
    assert "snapshot.macro.campaignEnabled == true" in policy_source
    assert "FieldCampaignDecision(snapshot, intents)" in policy_source


def test_new_aa_fills_under_target_field_aa_without_reshuffling_survivors() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=24, aa=2)
    activate_campaign(harness, observation)
    original_field, original_home = expected_initial_cohorts(24, 2)
    new_aa = harness.unit(entityId=9000, blueprintId="uel0104", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from([acu, engineer, *combat, new_aa])
    harness.brain.tick = 10
    at_25 = reconcile(harness)
    macro_25 = plain(at_25)["macro"]

    # Sticky assignments may temporarily miss the ideal AA ratio, but the
    # exact 25-unit doctrine remains 18 field / 7 home.  AA pressure must not
    # silently grow the field cohort beyond its unit budget.
    assert macro_25.get("fieldTokens") == original_field
    assert macro_25.get("homeTokens") == sorted([*original_home, "9000:1"])
    assert macro_25.get("fieldAa") == 1
    assert macro_25.get("homeAa") == 2
    assert campaign_intents(harness, at_25) == []

    new_tank = harness.unit(entityId=9001, blueprintId="uel0201", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, *combat, new_aa, new_tank]
    )
    harness.brain.tick = 20
    at_26 = reconcile(harness)
    assert plain(at_26)["macro"].get("fieldTokens") == sorted(
        [*original_field, "9001:1"]
    )
    assert plain(at_26)["macro"].get("homeTokens") == sorted(
        [*original_home, "9000:1"]
    )
    reinforcement = campaign_intents(harness, at_26)
    assert len(reinforcement) == 1
    assert reinforcement[0].get("mode") == "reinforce"
    assert reinforcement[0].get("actorTokens") == ["9001:1"]


def test_mission_age_resets_on_successful_objective_transition() -> None:
    next_marker = marker("cluster-b", 140, 20)
    harness, acu, engineer, combat, observation = start_campaign(extra_markers=[next_marker])
    activate_campaign(harness, observation)
    mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[80, 2, 20])
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from([acu, engineer, mex, *combat])
    harness.brain.tick = 100
    reconcile(harness)
    harness.brain.tick = 250
    reconcile(harness)
    next_engineer = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[20, 2, 20],
        idleState=False,
        states=lua_value(harness.lua, {"Moving": True}),
    )
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, next_engineer, mex, *combat]
    )
    harness.brain.tick = 251
    harness.observe()
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="cluster-b",
        cluster_key="cluster-b",
        position=[140, 2, 20],
        reason="frontier_expansion",
    )
    transition_observation = reconcile(harness)
    execute_intents(
        harness,
        campaign_intents(harness, transition_observation),
        transition_observation,
    )
    harness.brain.tick = 300
    after = reconcile(harness)
    assert plain(after)["macro"].get("campaignMissionAge") == 49


def test_home_regroup_and_factory_rally_remain_at_base_during_campaign_selection_churn() -> None:
    next_marker = marker("cluster-b", 140, 20)
    harness, acu, engineer, combat, observation = start_campaign(extra_markers=[next_marker])
    activate_campaign(harness, observation)
    field, home = expected_initial_cohorts(24, 2)
    by_id = {int(unit.options.entityId): unit for unit in combat}
    for token in home:
        by_id[int(token.split(":")[0])].options.position = lua_value(
            harness.lua,
            [140, 2, 20],
        )
    mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[80, 2, 20])
    factory = harness.unit(entityId=60, blueprintId="ueb0101", position=[10, 2, 20])
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from([acu, engineer, mex, factory, *combat])
    harness.brain.tick = 100
    current = reconcile(harness)
    intents = policy_intents(harness, current)
    rally = [intent for intent in intents if intent.get("kind") == "rally"]
    regroup = [intent for intent in intents if intent.get("kind") == "regroup_wave"]

    assert plain(current)["macro"].get("rallyPosition") == plain(current.basePosition)
    assert len(rally) == 1 and rally[0].get("position") == plain(current.basePosition)
    assert len(regroup) == 1
    assert regroup[0].get("position") == plain(current.basePosition)
    assert regroup[0].get("actorTokens") == home
    assert set(regroup[0].get("actorTokens") or []).isdisjoint(field)
    execute_intents(harness, rally, current)
    rally_count = len(harness.calls.rally)

    # Removing the speculative next marker changes the legacy selected rally
    # anchor, but must not invalidate the already-issued campaign/base rally.
    harness.controller.markers.mass = lua_value(
        harness.lua,
        [marker("cluster-a", 80, 20)],
    )
    harness.brain.tick = 101
    stable = reconcile(harness)
    assert not [
        intent for intent in policy_intents(harness, stable)
        if intent.get("kind") == "rally"
    ]
    assert len(harness.calls.rally) == rally_count


def test_single_campaign_engineer_can_build_and_transition_to_next_objective_after_hold() -> None:
    next_marker = marker("cluster-b", 140, 20)
    harness, acu, engineer, combat, observation = start_campaign(extra_markers=[next_marker])
    activate_campaign(harness, observation)
    mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[80, 2, 20])
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from([acu, engineer, mex, *combat])
    harness.brain.tick = 100
    reconcile(harness)
    harness.brain.tick = 250
    awaiting = reconcile(harness)
    builds = [
        intent for intent in policy_intents(harness, awaiting)
        if intent.get("reason") == "frontier_expansion"
    ]

    assert len(builds) == 1
    assert builds[0].get("actorToken") == "2:1"
    assert builds[0].get("siteKey") == "cluster-b"
    execute_intents(harness, builds, awaiting)
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.tick = 251
    current = reconcile(harness)
    transition = campaign_intents(harness, current)
    assert len(transition) == 1
    assert transition[0].get("mode") == "transition"
    assert transition[0].get("engineerToken") == "2:1"


def test_campaign_engineer_rebuilds_any_lost_mex_before_next_cached_member() -> None:
    second = marker("cluster-a-2", 90, 20)
    remote_owned = marker("remote-owned", 200, 20)
    harness, acu, engineer, combat, observation = start_campaign(
        extra_markers=[second, remote_owned]
    )
    activate_campaign(harness, observation)
    first_mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[80, 2, 20])
    remote_mex = harness.unit(entityId=51, blueprintId="ueb1103", position=[200, 2, 20])
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, first_mex, remote_mex, *combat]
    )
    harness.brain.tick = 50
    reconcile(harness)
    harness.brain.units = harness.lua.table_from([acu, engineer, first_mex, *combat])
    harness.brain.tick = 60
    current = reconcile(harness)
    builds = [
        intent for intent in policy_intents(harness, current)
        if intent.get("actorToken") == "2:1"
            and intent.get("kind") in {"build_structure", "assist_structure"}
    ]

    assert len(builds) == 1
    assert builds[0].get("reason") == "rebuild_mex"
    assert builds[0].get("siteKey") == "remote-owned"


@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_stale_activation_guard_is_replaced_next_tick_without_order_loop(
    mutation: str,
) -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    stale = campaign_intents(harness, observation)
    assert stale and stale[0].get("engineerToken") == "2:1"
    if mutation == "dead":
        engineer.Dead = True
        replacement = harness.unit(entityId=3, blueprintId="uel0105", position=[12, 2, 20])
        replacement_token = "3:1"
        units = [acu, replacement, *combat]
    elif mutation == "captured":
        engineer.options.army = 2
        replacement = harness.unit(entityId=3, blueprintId="uel0105", position=[12, 2, 20])
        replacement_token = "3:1"
        units = [acu, engineer, replacement, *combat]
    else:
        replacement = harness.unit(entityId=2, blueprintId="uel0105", position=[12, 2, 20])
        replacement_token = "2:2"
        units = [acu, replacement, *combat]
    replacement.options.idleState = False
    replacement.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.units = harness.lua.table_from(units)
    harness.brain.tick = 10
    harness.observe()
    harness.controller.pending["2:1"] = None
    harness.controller.reservations["cluster-a"] = None
    inject_structure_operation(
        harness,
        actor_token=replacement_token,
        site_key="cluster-a",
        cluster_key="cluster-a",
        position=[80, 2, 20],
        reason="frontier_expansion",
    )
    current = reconcile(harness)
    activation = campaign_intents(harness, current)

    assert len(activation) == 1 and activation[0].get("mode") == "activate"
    assert activation[0].get("engineerToken") == replacement_token
    execute_intents(harness, activation, current)
    assert harness.controller.fieldCampaign.state == "active"
    assert harness.controller.fieldCampaign.engineerToken == replacement_token


def test_cancelled_activation_without_replacement_stops_stale_orders_and_replans_site() -> None:
    harness, _, engineer, _, observation = start_campaign()
    harness.controller.pending["2:1"] = None
    harness.controller.reservations["cluster-a"] = None
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.tick = 10
    current = reconcile(harness)

    assert campaign_intents(harness, current) == []
    rebuild = [
        intent for intent in policy_intents(harness, current)
        if intent.get("actorToken") == "2:1"
            and intent.get("siteKey") == "cluster-a"
    ]
    assert len(rebuild) == 1
    assert rebuild[0].get("reason") == "frontier_expansion"


def test_stale_retarget_guard_adopts_replacement_operation_and_retries_atomically() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    install_markers(
        harness,
        [
            layered_marker("cluster-a", 80, 20),
            layered_marker("lost-home", 35, 20),
        ],
    )
    first = harness.unit(entityId=3, blueprintId="uel0105", position=[20, 2, 20])
    first.options.idleState = False
    first.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.units = harness.lua.table_from([acu, engineer, first, *combat])
    harness.brain.tick = 20
    harness.observe()
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="lost-home",
        position=[35, 2, 20],
        reason="rebuild_mex",
    )
    stale_observation = reconcile(harness)
    assert campaign_intents(harness, stale_observation)[0].get("engineerToken") == "3:1"

    first.Dead = True
    replacement = harness.unit(entityId=4, blueprintId="uel0105", position=[20, 2, 20])
    replacement.options.idleState = False
    replacement.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.units = harness.lua.table_from([acu, engineer, replacement, *combat])
    harness.brain.tick = 21
    harness.observe()
    harness.controller.pending["3:1"] = None
    harness.controller.reservations["lost-home"] = None
    inject_structure_operation(
        harness,
        actor_token="4:1",
        site_key="lost-home",
        position=[35, 2, 20],
        reason="rebuild_mex",
    )
    current = reconcile(harness)
    retarget = campaign_intents(harness, current)

    assert len(retarget) == 1 and retarget[0].get("mode") == "retarget"
    assert retarget[0].get("engineerToken") == "4:1"
    execute_intents(harness, retarget, current)
    assert harness.controller.fieldCampaign.engineerToken == "4:1"


def test_recalled_campaign_resumes_on_replacement_builder_after_old_guard_dies() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    engineer.Dead = True
    replacement = harness.unit(entityId=3, blueprintId="uel0105", position=[12, 2, 20])
    replacement.options.idleState = False
    replacement.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.units = harness.lua.table_from([acu, replacement, *combat])
    harness.brain.tick = 20
    harness.observe()
    harness.controller.pending["2:1"] = None
    harness.controller.reservations["cluster-a"] = None
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="cluster-a",
        cluster_key="cluster-a",
        position=[80, 2, 20],
        reason="frontier_expansion",
    )
    acu.options.health = 75
    reconcile(harness)
    harness.brain.tick = 320
    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)

    assert len(resume) == 1 and resume[0].get("mode") == "resume"
    assert resume[0].get("engineerToken") == "3:1"
    execute_intents(harness, resume, ready)
    assert harness.controller.fieldCampaign.state == "active"
    assert harness.controller.fieldCampaign.engineerToken == "3:1"


def test_cancelling_structure_operation_cannot_create_a_field_campaign() -> None:
    harness, _, _, _, _ = start_campaign()
    harness.controller.fieldCampaign = None
    operation = harness.controller.pending["2:1"]
    operation.phase = "cancelling"
    operation.cancelReason = "timeout"
    harness.brain.tick = 10

    current = reconcile(harness)

    assert harness.controller.fieldCampaign is None
    assert plain(current)["macro"].get("campaignState") == "idle"
    assert campaign_intents(harness, current) == []


@pytest.mark.parametrize(
    "mutation,value",
    [
        ("reason", "energy_recovery"),
        ("buildRole", "power_generator"),
        ("position", [35, 2, 20]),
        ("phase", "cancelling"),
        ("cancelReason", "timeout"),
    ],
)
def test_activation_revalidates_exact_campaign_operation_before_any_field_order(
    mutation: str,
    value: Any,
) -> None:
    harness, _, _, _, observation = start_campaign()
    activation = campaign_intents(harness, observation)
    assert len(activation) == 1
    operation = harness.controller.pending["2:1"]
    setattr(
        operation,
        mutation,
        lua_value(harness.lua, value) if mutation == "position" else value,
    )

    execute_intents(harness, activation, observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert harness.controller.fieldCampaign.state == "awaiting_order"
    assert harness.controller.fieldCampaign.fullFieldOrders == 0


@pytest.mark.parametrize("seed", range(4))
def test_full_gate_expands_the_surviving_early_field_without_demoting_it(seed: int) -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=23, aa=2, seed=seed)
    activate_campaign(harness, observation)
    initial_field = set(plain(harness.controller.fieldCampaign.fieldTokens))
    field_tanks = sorted(token for token in initial_field if token.startswith("2"))
    assert len(field_tanks) == 3
    removed_ids = {int(token.split(":")[0]) for token in field_tanks}
    survivors = [unit for unit in combat if int(unit.options.entityId) not in removed_ids]
    replacements: list[Any] = []

    for offset in range(3):
        replacement = harness.unit(
            entityId=9000 + offset,
            blueprintId="uel0201",
            position=[10, 2, 20],
        )
        replacements.append(replacement)
        ordered = [acu, engineer, *survivors, *replacements]
        random.Random(seed + offset + 10).shuffle(ordered)
        harness.brain.units = harness.lua.table_from(ordered)
        harness.brain.tick = 10 + offset
        current = reconcile(harness)
        execute_intents(harness, campaign_intents(harness, current), current)

    pre_gate_field = set(plain(harness.controller.fieldCampaign.fieldTokens))
    assert {"1000:1", "9000:1", "9001:1", "9002:1"} == pre_gate_field

    gate_unit = harness.unit(entityId=9003, blueprintId="uel0201", position=[10, 2, 20])
    all_units = [acu, engineer, *survivors, *replacements, gate_unit]
    random.Random(seed + 100).shuffle(all_units)
    harness.brain.units = harness.lua.table_from(all_units)
    harness.brain.tick = 20
    at_gate = reconcile(harness)
    macro = plain(at_gate)["macro"]

    assert macro.get("fieldUnits") == 18
    assert macro.get("homeUnits") == 6
    assert pre_gate_field.issubset(set(macro.get("fieldTokens") or []))
    assert "1001:1" in set(macro.get("homeTokens") or [])
    activation = campaign_intents(harness, at_gate)
    assert len(activation) == 1
    assert activation[0].get("mode") == "activate"
    assert activation[0].get("actorTokens") == macro.get("fieldTokens")


@pytest.mark.parametrize("fail_first", [False, True])
def test_enabling_campaign_retires_a_preexisting_legacy_frontier_mission_once(
    fail_first: bool,
) -> None:
    harness, _, _, _, observation = start_campaign()
    _, home = expected_initial_cohorts(24, 2)
    legacy_token = home[0]
    harness.controller.frontierMission = lua_value(
        harness.lua,
        {
            "engineerToken": "2:1",
            "clusterKey": "legacy-cluster",
            "escortTokens": [legacy_token],
            "issuedTick": 0,
        },
    )
    harness.controller.frontierAssignments[legacy_token] = lua_value(
        harness.lua,
        {
            "engineerToken": "2:1",
            "clusterKey": "legacy-cluster",
            "issuedTick": 0,
        },
    )
    harness.calls.failClear = fail_first
    harness.brain.tick = 10

    reconcile(harness)

    if fail_first:
        assert harness.controller.frontierMission is not None
        assert harness.controller.frontierAssignments[legacy_token] is not None
        harness.calls.failClear = False
        harness.brain.tick = 11
        reconcile(harness)
    assert harness.controller.frontierMission is None
    assert harness.controller.frontierAssignments[legacy_token] is None
    assert actor_tokens_from_call(harness.calls.clear[len(harness.calls.clear)]) == [legacy_token]


def test_recalled_campaign_stays_in_emergency_when_objective_temporarily_disappears() -> None:
    harness, acu, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    assert harness.controller.fieldCampaign.state == "recalled"
    harness.controller.markers.mass = lua_value(harness.lua, [])
    harness.brain.tick = 11

    missing = reconcile(harness)

    assert harness.controller.fieldCampaign.state == "recalled"
    assert harness.controller.fieldCampaign.emergency is True
    assert campaign_intents(harness, missing) == []


def test_recovery_full_field_order_is_counted_by_churn_telemetry() -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    assert harness.controller.fieldCampaign.fullFieldOrders == 1
    harness.brain.tick = 300
    stuck = reconcile(harness)
    recovery = campaign_intents(harness, stuck)
    assert len(recovery) == 1 and recovery[0].get("mode") == "recover"

    execute_intents(harness, recovery, stuck)

    assert harness.controller.fieldCampaign.recoveryOrders == 1
    assert harness.controller.fieldCampaign.fullFieldOrders == 2


def test_failed_legacy_retirement_blocks_overlapping_campaign_activation_until_retry() -> None:
    harness, _, _, _, observation = start_campaign()
    field, _ = expected_initial_cohorts(24, 2)
    legacy_token = field[0]
    harness.controller.frontierMission = lua_value(
        harness.lua,
        {
            "engineerToken": "2:1",
            "clusterKey": "legacy-cluster",
            "escortTokens": [legacy_token],
            "issuedTick": 0,
        },
    )
    harness.controller.frontierAssignments[legacy_token] = lua_value(
        harness.lua,
        {
            "engineerToken": "2:1",
            "clusterKey": "legacy-cluster",
            "issuedTick": 0,
        },
    )
    harness.calls.failClear = True
    harness.brain.tick = 10
    blocked = reconcile(harness)

    assert campaign_intents(harness, blocked) == []
    execute_intents(
        harness,
        [
            {
                "kind": CAMPAIGN_KIND,
                "mode": "activate",
                "actorTokens": field,
                "engineerToken": "2:1",
                "position": [80, 2, 20],
                "campaignSerial": 1,
                "clusterKey": "cluster-a",
                "objectiveKey": "cluster-a",
                "priority": 24,
            }
        ],
        blocked,
    )
    assert len(harness.calls.guard) == 0
    assert harness.controller.fieldCampaign.state == "awaiting_order"

    harness.calls.failClear = False
    harness.brain.tick = 11
    ready = reconcile(harness)
    activation = campaign_intents(harness, ready)
    assert len(activation) == 1 and activation[0].get("mode") == "activate"
    execute_intents(harness, activation, ready)
    assert harness.controller.frontierMission is None
    assert harness.controller.fieldCampaign.state == "active"


def test_live_legacy_mission_blocks_direct_campaign_execute_before_reconcile() -> None:
    harness, _, _, _, observation = start_campaign()
    activation = campaign_intents(harness, observation)
    field, _ = expected_initial_cohorts(24, 2)
    legacy_token = field[0]
    harness.controller.frontierMission = lua_value(
        harness.lua,
        {
            "engineerToken": "2:1",
            "clusterKey": "legacy-cluster",
            "escortTokens": [legacy_token],
            "issuedTick": 0,
        },
    )
    harness.controller.frontierAssignments[legacy_token] = lua_value(
        harness.lua,
        {
            "engineerToken": "2:1",
            "clusterKey": "legacy-cluster",
            "issuedTick": 0,
        },
    )

    execute_intents(harness, activation, observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert harness.controller.fieldCampaign.state == "awaiting_order"


def test_campaign_start_invalidates_a_legacy_frontier_factory_rally_once() -> None:
    harness, acu, engineer, combat, _ = start_campaign()
    harness.controller.fieldCampaign = None
    factory = harness.unit(entityId=60, blueprintId="ueb0101", position=[10, 2, 20])
    harness.controller.rallied["60:1"] = True
    harness.brain.units = harness.lua.table_from([acu, engineer, factory, *combat])
    harness.brain.tick = 10

    reconcile(harness)
    harness.brain.tick = 11
    current = reconcile(harness)
    rally = [intent for intent in policy_intents(harness, current) if intent.get("kind") == "rally"]

    assert len(rally) == 1
    assert rally[0].get("actorToken") == "60:1"
    assert rally[0].get("position") == plain(current.basePosition)
    execute_intents(harness, rally, current)
    harness.controller.selectedFrontierCluster = "volatile-next"
    harness.brain.tick = 12
    stable = reconcile(harness)
    assert not [intent for intent in policy_intents(harness, stable) if intent.get("kind") == "rally"]
    assert len(harness.calls.rally) == 1


def test_full_gate_is_deferred_during_recall_then_resumes_the_full_cohort_once() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=23, aa=2)
    activate_campaign(harness, observation)
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    promoted = harness.unit(entityId=9000, blueprintId="uel0201", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from([acu, engineer, *combat, promoted])
    acu.options.health = 74.9
    harness.brain.tick = 11

    unsafe = reconcile(harness)

    assert harness.controller.fieldCampaign.state == "recalled"
    assert plain(unsafe)["macro"].get("fieldUnits") == 4
    assert plain(unsafe)["macro"].get("homeUnits") == 20
    assert campaign_intents(harness, unsafe) == []
    acu.options.health = 75
    harness.brain.tick = 12
    reconcile(harness)
    harness.brain.tick = 311
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 312
    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)
    assert len(resume) == 1 and resume[0].get("mode") == "resume"
    assert len(resume[0].get("actorTokens") or []) == 18
    execute_intents(harness, resume, ready)
    assert harness.controller.fieldCampaign.state == "active"
    assert harness.controller.fieldCampaign.fullFieldOrders == 2
    harness.brain.tick = 313
    assert campaign_intents(harness, reconcile(harness)) == []


def test_full_gate_preserves_awaiting_objective_after_the_cluster_hold() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=23, aa=2)
    activate_campaign(harness, observation)
    mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[80, 2, 20])
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from([acu, engineer, mex, *combat])
    harness.brain.tick = 100
    reconcile(harness)
    harness.brain.tick = 250
    held = reconcile(harness)
    assert plain(held)["macro"].get("campaignState") == "awaiting_objective"
    promoted = harness.unit(entityId=9000, blueprintId="uel0201", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from([acu, engineer, mex, *combat, promoted])
    harness.brain.tick = 251

    at_gate = reconcile(harness)

    assert plain(at_gate)["macro"].get("campaignState") == "awaiting_objective"
    assert plain(at_gate)["macro"].get("fieldUnits") == 18
    assert plain(at_gate)["macro"].get("homeUnits") == 6
    assert campaign_intents(harness, at_gate) == []


def test_full_gate_preserves_an_atomic_pending_rebuild_retarget() -> None:
    harness, acu, original_engineer, combat, observation = start_campaign(total=23, aa=2)
    activate_campaign(harness, observation)
    install_markers(
        harness,
        [
            layered_marker("cluster-a", 80, 20),
            layered_marker("lost-home", 35, 20),
        ],
    )
    rebuild_engineer = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[20, 2, 20],
        idleState=False,
        states=lua_value(harness.lua, {"Moving": True}),
    )
    harness.brain.units = harness.lua.table_from(
        [acu, original_engineer, rebuild_engineer, *combat]
    )
    harness.brain.tick = 20
    harness.observe()
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="lost-home",
        position=[35, 2, 20],
        reason="rebuild_mex",
    )
    pending = reconcile(harness)
    retarget = campaign_intents(harness, pending)
    assert len(retarget) == 1 and retarget[0].get("mode") == "retarget"
    promoted = harness.unit(entityId=9000, blueprintId="uel0201", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from(
        [acu, original_engineer, rebuild_engineer, *combat, promoted]
    )
    harness.brain.tick = 21

    at_gate = reconcile(harness)
    retarget = campaign_intents(harness, at_gate)

    assert len(retarget) == 1
    assert retarget[0].get("mode") == "retarget"
    assert retarget[0].get("engineerToken") == "3:1"
    assert len(retarget[0].get("actorTokens") or []) == 18
    execute_intents(harness, retarget, at_gate)
    assert harness.controller.fieldCampaign.engineerToken == "3:1"
    clear_count = len(harness.calls.clear)
    guard_count = len(harness.calls.guard)
    harness.brain.tick = 22
    stable = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, stable), stable)
    assert len(harness.calls.clear) == clear_count
    assert len(harness.calls.guard) == guard_count


def test_invalid_recalled_objective_resumes_once_on_valid_replacement_cluster() -> None:
    replacement_marker = marker("cluster-b", 140, 20)
    harness, acu, old_engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    replacement = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[20, 2, 20],
        idleState=False,
        states=lua_value(harness.lua, {"Moving": True}),
    )
    harness.brain.units = harness.lua.table_from([acu, old_engineer, replacement, *combat])
    harness.controller.markers.mass = lua_value(harness.lua, [replacement_marker])
    harness.brain.tick = 20
    harness.observe()
    harness.controller.pending["2:1"] = None
    harness.controller.reservations["cluster-a"] = None
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="cluster-b",
        cluster_key="cluster-b",
        position=[140, 2, 20],
        reason="frontier_expansion",
    )
    acu.options.health = 75
    reconcile(harness)
    harness.brain.tick = 319
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 320
    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)

    assert len(resume) == 1 and resume[0].get("mode") == "resume"
    assert resume[0].get("engineerToken") == "3:1"
    assert resume[0].get("clusterKey") == "cluster-b"
    execute_intents(harness, resume, ready)
    campaign = plain(harness.controller.fieldCampaign)
    assert campaign.get("state") == "active"
    assert campaign.get("clusterKey") == "cluster-b"
    assert campaign.get("objectiveKey") == "cluster-b"
    assert campaign.get("engineerToken") == "3:1"
    assert campaign.get("memberKeys") == ["cluster-b"]
    clear_count = len(harness.calls.clear)
    guard_count = len(harness.calls.guard)
    harness.brain.tick = 321
    stable = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, stable), stable)
    assert len(harness.calls.clear) == clear_count
    assert len(harness.calls.guard) == guard_count


@pytest.mark.parametrize("mutation,value", [("phase", "cancelling"), ("reason", "energy_recovery"), ("position", [90, 2, 20])])
def test_replacement_resume_revalidates_exact_operation_before_any_field_order(
    mutation: str,
    value: Any,
) -> None:
    replacement_marker = marker("cluster-b", 140, 20)
    harness, acu, old_engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    replacement = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[20, 2, 20],
        idleState=False,
        states=lua_value(harness.lua, {"Moving": True}),
    )
    harness.brain.units = harness.lua.table_from([acu, old_engineer, replacement, *combat])
    harness.controller.markers.mass = lua_value(harness.lua, [replacement_marker])
    harness.brain.tick = 20
    harness.observe()
    harness.controller.pending["2:1"] = None
    harness.controller.reservations["cluster-a"] = None
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="cluster-b",
        cluster_key="cluster-b",
        position=[140, 2, 20],
        reason="frontier_expansion",
    )
    acu.options.health = 75
    reconcile(harness)
    harness.brain.tick = 320
    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)
    assert len(resume) == 1
    operation = harness.controller.pending["3:1"]
    setattr(
        operation,
        mutation,
        lua_value(harness.lua, value) if mutation == "position" else value,
    )
    clear_before = len(harness.calls.clear)
    guard_before = len(harness.calls.guard)

    execute_intents(harness, resume, ready)

    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.guard) == guard_before
    assert harness.controller.fieldCampaign.state == "recalled"
    assert harness.controller.fieldCampaign.emergency is True


@pytest.mark.parametrize("seed", range(4))
def test_recalled_campaign_refills_field_losses_only_at_the_safe_resume_gate(seed: int) -> None:
    harness, acu, engineer, combat, observation = start_campaign(seed=seed)
    activate_campaign(harness, observation)
    field, home = expected_initial_cohorts(24, 2)
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    by_id = {int(unit.options.entityId): unit for unit in combat}
    home_units = [by_id[int(token.split(":")[0])] for token in home]
    random.Random(seed + 50).shuffle(home_units)
    harness.brain.units = harness.lua.table_from([acu, engineer, *home_units])
    harness.brain.tick = 11
    depleted = reconcile(harness)
    assert plain(depleted)["macro"].get("fieldUnits") == 0
    assert plain(depleted)["macro"].get("homeUnits") == 6
    assert campaign_intents(harness, depleted) == []
    acu.options.health = 75
    harness.brain.tick = 12
    reconcile(harness)
    harness.brain.tick = 311
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 312

    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)

    assert plain(ready)["macro"].get("fieldUnits") == 2
    assert plain(ready)["macro"].get("homeUnits") == 4
    assert len(resume) == 1 and resume[0].get("mode") == "resume"
    assert len(resume[0].get("actorTokens") or []) == 2
    execute_intents(harness, resume, ready)
    assert harness.controller.fieldCampaign.state == "active"


def test_dead_recalled_builder_is_replanned_during_healthy_hysteresis_then_resumes() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    engineer.Dead = True
    replacement = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([acu, replacement, *combat])
    harness.brain.tick = 20
    harness.observe()
    harness.controller.pending["2:1"] = None
    harness.controller.reservations["cluster-a"] = None
    acu.options.health = 75

    recovering = reconcile(harness)
    replacement_build = [
        intent for intent in policy_intents(harness, recovering)
        if intent.get("actorToken") == "3:1"
            and intent.get("siteKey") == "cluster-a"
            and intent.get("reason") == "frontier_expansion"
    ]
    assert len(replacement_build) == 1
    execute_intents(harness, replacement_build, recovering)
    replacement.options.idleState = False
    replacement.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.tick = 319
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 320
    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)
    assert len(resume) == 1 and resume[0].get("mode") == "resume"
    assert resume[0].get("engineerToken") == "3:1"
    execute_intents(harness, resume, ready)
    assert harness.controller.fieldCampaign.state == "active"
    assert harness.controller.fieldCampaign.engineerToken == "3:1"


def test_disappeared_pending_resume_clears_stale_intent_and_replans_immediately() -> None:
    harness, acu, engineer, _, observation = start_campaign()
    activate_campaign(harness, observation)
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    acu.options.health = 75
    harness.brain.tick = 20
    reconcile(harness)
    harness.brain.tick = 320
    stale_observation = reconcile(harness)
    assert campaign_intents(harness, stale_observation)[0].get("mode") == "resume"
    harness.controller.pending["2:1"] = None
    harness.controller.reservations["cluster-a"] = None
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    harness.brain.tick = 321

    replanning = reconcile(harness)

    assert campaign_intents(harness, replanning) == []
    assert plain(replanning)["macro"].get("campaignIntentMode") == "none"
    build = [
        intent for intent in policy_intents(harness, replanning)
        if intent.get("actorToken") == "2:1"
            and intent.get("siteKey") == "cluster-a"
    ]
    assert len(build) == 1
    execute_intents(harness, build, replanning)
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.tick = 322
    retried = reconcile(harness)
    resume = campaign_intents(harness, retried)
    assert len(resume) == 1 and resume[0].get("mode") == "resume"


def test_invalid_recalled_cluster_replaced_by_rebuild_has_coherent_completion_state() -> None:
    replacement_marker = marker("lost-home", 40, 20)
    harness, acu, old_engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    replacement = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[20, 2, 20],
        idleState=False,
        states=lua_value(harness.lua, {"Moving": True}),
    )
    harness.brain.units = harness.lua.table_from([acu, old_engineer, replacement, *combat])
    harness.controller.markers.mass = lua_value(harness.lua, [replacement_marker])
    harness.brain.tick = 20
    harness.observe()
    harness.controller.pending["2:1"] = None
    harness.controller.reservations["cluster-a"] = None
    inject_structure_operation(
        harness,
        actor_token="3:1",
        site_key="lost-home",
        position=[40, 2, 20],
        reason="rebuild_mex",
    )
    acu.options.health = 75
    reconcile(harness)
    harness.brain.tick = 320
    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)
    assert len(resume) == 1 and resume[0].get("mode") == "resume"
    execute_intents(harness, resume, ready)
    campaign = plain(harness.controller.fieldCampaign)
    assert campaign.get("clusterKey") == "lost-home"
    assert campaign.get("memberKeys") == ["lost-home"]
    mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[40, 2, 20])
    replacement.options.idleState = True
    replacement.options.states = lua_value(harness.lua, {})
    harness.brain.units = harness.lua.table_from(
        [acu, old_engineer, replacement, mex, *combat]
    )
    harness.brain.tick = 321
    completed = reconcile(harness)
    assert plain(completed)["macro"].get("campaignState") == "holding"


@pytest.mark.parametrize("seed", range(4))
def test_amphibious_only_rebuild_stays_noncampaign_while_next_land_rebuild_is_adopted(
    seed: int,
) -> None:
    amphib = layered_marker(
        "cached-amphib",
        90,
        20,
        engineer_reachable=True,
        land_reachable=True,
    )
    valid = layered_marker("valid-lost", 140, 20)
    extra_markers = [amphib, valid]
    random.Random(seed).shuffle(extra_markers)
    harness, acu, campaign_engineer, combat, observation = start_campaign(
        seed=seed,
        extra_markers=extra_markers,
    )
    activate_campaign(harness, observation)
    amphib_mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[90, 2, 20])
    valid_mex = harness.unit(entityId=51, blueprintId="ueb1103", position=[140, 2, 20])
    first = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[15, 2, 20],
        canBuild={"ueb1103": True},
    )
    second = harness.unit(
        entityId=4,
        blueprintId="uel0105",
        position=[16, 2, 20],
        canBuild={"ueb1103": True},
    )
    owned_units = [
        acu,
        campaign_engineer,
        first,
        second,
        amphib_mex,
        valid_mex,
        *combat,
    ]
    random.Random(seed + 20).shuffle(owned_units)
    harness.brain.units = harness.lua.table_from(owned_units)
    harness.brain.tick = 20
    reconcile(harness)
    controller_marker(harness, "cached-amphib").landReachable = False
    lost_units = [acu, campaign_engineer, first, second, *combat]
    random.Random(seed + 40).shuffle(lost_units)
    harness.brain.units = harness.lua.table_from(lost_units)
    harness.brain.tick = 21
    lost = reconcile(harness)
    rebuilds = [
        intent for intent in policy_intents(harness, lost)
        if intent.get("kind") in {"build_structure", "assist_structure"}
            and intent.get("reason") == "rebuild_mex"
            and intent.get("actorToken") in {"3:1", "4:1"}
    ]

    assert [(intent.get("actorToken"), intent.get("siteKey")) for intent in rebuilds] == [
        ("3:1", "cached-amphib"),
        ("4:1", "valid-lost"),
    ]
    amphib_intent = rebuilds[0]
    assert amphib_intent.get("clusterKey") != plain(
        harness.controller.fieldCampaign
    ).get("clusterKey")
    execute_intents(harness, rebuilds, lost)
    first.options.idleState = False
    first.options.states = lua_value(harness.lua, {"Moving": True})
    second.options.idleState = False
    second.options.states = lua_value(harness.lua, {"Moving": True})
    assert harness.controller.pending["3:1"] is not None
    assert harness.controller.pending["4:1"] is not None
    clear_before = len(harness.calls.clear)
    guard_before = len(harness.calls.guard)
    harness.brain.tick = 22
    current = reconcile(harness)
    retarget = campaign_intents(harness, current)

    assert len(retarget) == 1
    assert retarget[0].get("mode") == "retarget"
    assert retarget[0].get("engineerToken") == "4:1"
    assert retarget[0].get("objectiveKey") == "valid-lost"
    execute_intents(harness, retarget, current)
    assert len(harness.calls.clear) == clear_before + 1
    assert len(harness.calls.guard) == guard_before + 1
    assert harness.calls.guard[len(harness.calls.guard)].target.options.entityId == 4
    assert harness.controller.fieldCampaign.objectiveKey == "valid-lost"
    assert harness.controller.fieldCampaign.engineerToken == "4:1"
    assert harness.controller.pending["3:1"] is not None


def prepare_reachability_sensitive_campaign_intent(mode: str) -> tuple[Any, Any, dict[str, Any], str]:
    if mode == "activate":
        harness, _, _, _, observation = start_campaign()
        intent = campaign_intents(harness, observation)[0]
        return harness, observation, intent, "cluster-a"
    if mode == "retarget":
        target = layered_marker("lost-home", 35, 20)
        harness, acu, engineer, combat, observation = start_campaign(extra_markers=[target])
        activate_campaign(harness, observation)
        next_engineer = harness.unit(
            entityId=3,
            blueprintId="uel0105",
            position=[20, 2, 20],
            idleState=False,
            states=lua_value(harness.lua, {"Moving": True}),
        )
        harness.brain.units = harness.lua.table_from([acu, engineer, next_engineer, *combat])
        harness.brain.tick = 20
        harness.observe()
        inject_structure_operation(
            harness,
            actor_token="3:1",
            site_key="lost-home",
            position=[35, 2, 20],
            reason="rebuild_mex",
        )
        current = reconcile(harness)
        intent = campaign_intents(harness, current)[0]
        assert intent.get("mode") == "retarget"
        return harness, current, intent, "lost-home"
    if mode == "transition":
        target = layered_marker("cluster-b", 140, 20)
        harness, acu, engineer, combat, observation = start_campaign(extra_markers=[target])
        activate_campaign(harness, observation)
        mex = harness.unit(entityId=50, blueprintId="ueb1103", position=[80, 2, 20])
        engineer.options.idleState = True
        engineer.options.states = lua_value(harness.lua, {})
        harness.brain.units = harness.lua.table_from([acu, engineer, mex, *combat])
        harness.brain.tick = 100
        reconcile(harness)
        harness.brain.tick = 250
        reconcile(harness)
        next_engineer = harness.unit(
            entityId=3,
            blueprintId="uel0105",
            position=[20, 2, 20],
            idleState=False,
            states=lua_value(harness.lua, {"Moving": True}),
        )
        harness.brain.units = harness.lua.table_from(
            [acu, engineer, next_engineer, mex, *combat]
        )
        harness.brain.tick = 251
        harness.observe()
        inject_structure_operation(
            harness,
            actor_token="3:1",
            site_key="cluster-b",
            cluster_key="cluster-b",
            position=[140, 2, 20],
            reason="frontier_expansion",
        )
        current = reconcile(harness)
        intent = campaign_intents(harness, current)[0]
        assert intent.get("mode") == "transition"
        return harness, current, intent, "cluster-b"
    harness, acu, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    if mode == "reinforce":
        first_new = harness.unit(
            entityId=9000,
            blueprintId="uel0201",
            position=[10, 2, 20],
        )
        second_new = harness.unit(
            entityId=9001,
            blueprintId="uel0201",
            position=[10, 2, 20],
        )
        current_units = list(harness.brain.units.values())
        harness.brain.units = harness.lua.table_from([*current_units, first_new])
        harness.brain.tick = 10
        assert campaign_intents(harness, reconcile(harness)) == []
        harness.brain.units = harness.lua.table_from(
            [*current_units, first_new, second_new]
        )
        harness.brain.tick = 20
        current = reconcile(harness)
        intent = campaign_intents(harness, current)[0]
        assert intent.get("mode") == "reinforce"
        assert intent.get("actorTokens") == ["9001:1"]
        return harness, current, intent, "cluster-a"
    if mode == "recover":
        harness.brain.tick = 300
        current = reconcile(harness)
        intent = campaign_intents(harness, current)[0]
        assert intent.get("mode") == "recover"
        return harness, current, intent, "cluster-a"
    assert mode == "resume"
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    acu.options.health = 75
    harness.brain.tick = 20
    reconcile(harness)
    harness.brain.tick = 320
    current = reconcile(harness)
    intent = campaign_intents(harness, current)[0]
    assert intent.get("mode") == "resume"
    return harness, current, intent, "cluster-a"


@pytest.mark.parametrize(
    "mode",
    ["activate", "retarget", "transition", "resume", "recover", "reinforce"],
)
@pytest.mark.parametrize("mutation", ["engineer_reach", "land_reach", "site_position"])
def test_every_full_field_operation_revalidates_exact_live_site_before_execute(
    mode: str,
    mutation: str,
) -> None:
    harness, stale_observation, intent, site_key = prepare_reachability_sensitive_campaign_intent(mode)
    target = controller_marker(harness, site_key)
    old_position = plain(target.position)
    before = plain(harness.controller.fieldCampaign)
    clear_before = len(harness.calls.clear)
    guard_before = len(harness.calls.guard)
    move_before = len(harness.calls.move)
    if mutation == "engineer_reach":
        target.engineerReachable = False
    elif mutation == "land_reach":
        target.landReachable = False
    else:
        target.position = lua_value(
            harness.lua,
            [old_position[0] + 5, old_position[1], old_position[2]],
        )
    harness.observe()

    execute_intents(harness, [intent], stale_observation)

    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.guard) == guard_before
    assert len(harness.calls.move) == move_before
    assert plain(harness.controller.fieldCampaign) == before
    target.engineerReachable = True
    target.landReachable = True
    target.position = lua_value(harness.lua, old_position)
    harness.observe()
    harness.brain.tick += 1
    retry_observation = reconcile(harness)
    retry = campaign_intents(harness, retry_observation)
    assert len(retry) == 1 and retry[0].get("mode") == mode
    execute_intents(harness, retry, retry_observation)
    if mode == "recall":
        assert len(harness.calls.move) == move_before + 1
    else:
        assert len(harness.calls.guard) == guard_before + 1


def test_transient_rebuild_backoff_does_not_block_exact_land_retarget_execute() -> None:
    harness, observation, retarget, site_key = prepare_reachability_sensitive_campaign_intent(
        "retarget"
    )
    harness.controller.blockedSites[site_key] = harness.brain.tick + 1000
    harness.observe()
    guard_before = len(harness.calls.guard)

    execute_intents(harness, [retarget], observation)

    assert len(harness.calls.guard) == guard_before + 1
    assert harness.controller.fieldCampaign.objectiveKey == site_key
