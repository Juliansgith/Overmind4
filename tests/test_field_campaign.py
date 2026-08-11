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
    team_spawn_mode: Any = "fixed",
    target_position: list[float] | None = None,
    target_name: str | None = None,
    macro_ready: bool = True,
    readiness_mex: int = 8,
    readiness_land_factories: int = 3,
    readiness_air_factories: int = 0,
    economy_updates: dict[str, Any] | None = None,
) -> tuple[Any, Any, Any, list[Any], Any]:
    harness = make_harness()
    if team_spawn_mode != "fixed":
        harness.lua.globals().ScenarioInfo.Options.TeamSpawn = team_spawn_mode
        harness.controller = harness.lua.globals().Controller.Create(harness.brain)
    harness.controller.fieldCampaignEnabled = True
    harness.controller.crossMapOffenseEnabled = False
    if target_position is not None:
        harness.controller.targetPosition = lua_value(harness.lua, target_position)
        harness.controller.targetPath = True
    if target_name is not None:
        harness.controller.targetName = target_name
    if economy_updates:
        for key, value in economy_updates.items():
            setattr(harness.brain, key, value)
    position = position or [80, 2, 20]
    install_markers(
        harness,
        [
            layered_marker(
                site_key,
                position[0],
                position[2],
                engineer_reachable=reachable,
                land_reachable=reachable,
            ),
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
    if macro_ready:
        support = [
            harness.unit(
                entityId=3000 + index,
                blueprintId="ueb1103",
                position=[3 + index, 2, 4],
            )
            for index in range(readiness_mex)
        ] + [
            harness.unit(
                entityId=3100 + index,
                blueprintId="ueb0101",
                position=[4 + index, 2, 8],
                idleState=False,
                states={"Building": True},
            )
            for index in range(readiness_land_factories)
        ] + [
            harness.unit(
                entityId=3200 + index,
                blueprintId="ueb0102",
                position=[4 + index, 2, 12],
                idleState=False,
                states={"Building": True},
            )
            for index in range(readiness_air_factories)
        ]
        harness.brain.supportUnits = harness.lua.table_from(support)
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


def restore_combat_readiness(
    harness: Any,
    acu: Any,
    engineer: Any,
    combat: list[Any],
    *,
    start_id: int = 96000,
) -> list[Any]:
    live = [
        actor for actor in combat
        if not actor.Dead
        and not bool(actor.options.destroyed)
        and int(actor.options.army or 1) == 1
    ]
    live_aa = sum(
        1 for actor in live
        if str(actor.options.blueprintId).lower() in {"uel0104", "uel0205"}
    )
    needed_aa = max(0, 2 - live_aa)
    needed_total = max(0, 24 - len(live))
    replacements = [
        harness.unit(
            entityId=start_id + index,
            blueprintId="uel0104" if index < needed_aa else "uel0201",
            position=[10, 2, 20],
        )
        for index in range(needed_total)
    ]
    ready = [*live, *replacements]
    harness.brain.units = harness.lua.table_from([acu, engineer, *ready])
    return ready


def assert_campaign_cohort_indexes(campaign: Any) -> None:
    state = plain(campaign)
    field = state.get("fieldTokens") or []
    home = state.get("homeTokens") or []
    field_index = state.get("fieldTokenSet") or {}
    home_index = state.get("homeTokenSet") or {}

    assert field == sorted(field)
    assert home == sorted(home)
    assert set(field_index) == set(field)
    assert set(home_index) == set(home)
    assert all(value is True for value in field_index.values())
    assert all(value is True for value in home_index.values())
    assert set(field).isdisjoint(home)


def attrited_home_campaign(
    *,
    seed: int = 0,
    home_survivors: int = 0,
    enemy_x: float | None = 15,
) -> tuple[Any, Any, Any, list[Any], list[str], list[str], Any]:
    harness, acu, engineer, combat, observation = start_campaign(seed=seed)
    activate_campaign(harness, observation)
    field, home = expected_initial_cohorts(24, 2)
    by_token = {
        f"{int(actor.options.entityId)}:1": actor
        for actor in combat
    }
    for token in home[home_survivors:]:
        by_token[token].Dead = True
    live_tokens = [*field, *home[:home_survivors]]
    live_combat = [by_token[token] for token in live_tokens]
    units = [acu, engineer, *live_combat]
    random.Random(seed + 100).shuffle(units)
    harness.brain.units = harness.lua.table_from(units)
    if enemy_x is None:
        harness.brain.enemies = harness.lua.table_from([])
    else:
        enemy = harness.unit(
            entityId=99000,
            blueprintId="uel0201",
            army=2,
            position=[enemy_x, 2, 20],
        )
        harness.brain.enemies = harness.lua.table_from([enemy])
    harness.brain.tick = 20
    return harness, acu, engineer, live_combat, field, home, reconcile(harness)


def expected_attrition_emergency_cohorts(
    field: list[str],
    existing_home: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    anti_air = [token for token in field if token.startswith("1000:")]
    non_aa = [token for token in field if token not in anti_air]
    emergency_field = sorted([*anti_air[:1], *non_aa[:3]])
    emergency_home = sorted(
        (set(field) - set(emergency_field)) | set(existing_home or [])
    )
    return emergency_field, emergency_home


def health_recalled_home_attrition(
    *,
    seed: int = 0,
    home_survivors: int = 0,
    enemy_x: float | None = 15,
) -> tuple[Any, Any, Any, list[Any], list[str], list[str], Any]:
    harness, acu, engineer, combat, observation = start_campaign(seed=seed)
    activate_campaign(harness, observation)
    field, home = expected_initial_cohorts(24, 2)
    acu.options.health = 69
    harness.brain.tick = 10
    low = reconcile(harness)
    execute_intents(harness, campaign_intents(harness, low), low)
    assert harness.controller.fieldCampaign.state == "recalled"
    assert harness.controller.fieldCampaign.emergencyReason == "acu_health"

    by_token = {
        f"{int(actor.options.entityId)}:1": actor
        for actor in combat
    }
    for token in home[home_survivors:]:
        by_token[token].Dead = True
    live_tokens = [*field, *home[:home_survivors]]
    live_combat = [by_token[token] for token in live_tokens]
    units = [acu, engineer, *live_combat]
    random.Random(seed + 500).shuffle(units)
    harness.brain.units = harness.lua.table_from(units)
    acu.options.health = 75
    if enemy_x is None:
        harness.brain.enemies = harness.lua.table_from([])
    else:
        enemy = harness.unit(
            entityId=99200,
            blueprintId="uel0201",
            army=2,
            position=[enemy_x, 2, 20],
        )
        harness.brain.enemies = harness.lua.table_from([enemy])
    harness.brain.tick = 20
    return harness, acu, engineer, live_combat, field, home, reconcile(harness)


def second_recalled_attrition_epoch(
    *,
    seed: int = 0,
    remaining_field: int = 4,
) -> tuple[Any, Any, Any, list[Any], list[str], list[str], Any]:
    harness, acu, engineer, live_combat, field, _, current = attrited_home_campaign(
        seed=seed,
        home_survivors=0,
    )
    execute_intents(harness, campaign_intents(harness, current), current)
    emergency_field, emergency_home = expected_attrition_emergency_cohorts(field)
    by_token = {
        f"{int(actor.options.entityId)}:1": actor
        for actor in live_combat
    }
    survivors = emergency_field[:remaining_field]
    for token in [*emergency_home, *emergency_field[remaining_field:]]:
        by_token[token].Dead = True
    surviving_units = [by_token[token] for token in survivors]
    units = [acu, engineer, *surviving_units]
    random.Random(seed + 700).shuffle(units)
    harness.brain.units = harness.lua.table_from(units)
    harness.brain.tick = 30
    return (
        harness,
        acu,
        engineer,
        surviving_units,
        emergency_field,
        emergency_home,
        reconcile(harness),
    )


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
def test_sub_readiness_force_keeps_campaign_idle_while_macro_work_continues(
    total: int,
    aa: int,
) -> None:
    harness, _, _, _, observation = start_campaign(total=total, aa=aa)
    macro = plain(observation)["macro"]

    assert macro.get("campaignState") == "idle"
    assert macro.get("campaignReady") is False
    assert macro.get("fieldTokens") in ([], {})
    assert macro.get("homeTokens") in ([], {})
    assert harness.controller.fieldCampaign is None
    assert campaign_intents(harness, observation) == []
    assert any(
        intent.get("kind") == "build_structure"
        for intent in plain(observation.pending)
    )


def test_activation_orders_exact_full_field_once_and_stays_quiet_for_600_ticks() -> None:
    harness, _, _, combat, observation = start_campaign()
    field, _ = expected_initial_cohorts(24, 2)
    intent, _ = activate_campaign(harness, observation)

    assert intent["actorTokens"] == field
    assert plain(harness.calls.sequence)[:2] == ["clear", "aggressive"]
    assert actor_tokens_from_call(harness.calls.clear[1]) == field
    assert actor_tokens_from_call(harness.calls.aggressive[1]) == field
    assert len(harness.calls.guard) == 0
    assert harness.controller.fieldCampaign.state == "active"
    assert harness.controller.fieldCampaign.fullFieldOrders == 1
    clear_count = len(harness.calls.clear)
    aggressive_count = len(harness.calls.aggressive)

    for tick, x in [(1, 20), (50, 35), (299, 55), (599, 76)]:
        harness.brain.tick = tick
        for actor in combat:
            if f"{int(actor.options.entityId)}:1" in field:
                actor.options.position = lua_value(harness.lua, [x, 2, 20])
        current = reconcile(harness)
        execute_intents(harness, campaign_intents(harness, current), current)

    assert len(harness.calls.clear) == clear_count
    assert len(harness.calls.aggressive) == aggressive_count
    assert harness.controller.fieldCampaign.fullFieldOrders == 1


def test_ian_selected_frontier_churn_cannot_recreate_the_same_live_campaign_543_times() -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    clear_count = len(harness.calls.clear)
    aggressive_count = len(harness.calls.aggressive)

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
    assert len(harness.calls.aggressive) - aggressive_count <= 1


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
    aggressive_count = len(harness.calls.aggressive)
    execute_intents(harness, campaign, at_26)
    assert len(harness.calls.clear) == clear_count
    assert actor_tokens_from_call(harness.calls.aggressive[aggressive_count + 1]) == ["9001:1"]


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


@pytest.mark.parametrize("failure", ["clear", "aggressive"])
def test_full_field_activation_failure_is_atomic_and_immediately_retryable(failure: str) -> None:
    harness, _, _, _, observation = start_campaign()
    field, _ = expected_initial_cohorts(24, 2)
    campaign = campaign_intents(harness, observation)
    assert campaign and campaign[0].get("actorTokens") == field
    if failure == "clear":
        harness.calls.failClear = True
    else:
        harness.calls.failAggressive = True

    execute_intents(harness, campaign, observation)

    assert harness.controller.fieldCampaign.state == "awaiting_order"
    assert harness.controller.fieldCampaign.fullFieldOrders == 0
    assert plain(harness.controller.fieldCampaign.fieldTokens) == field
    if failure == "clear":
        assert len(harness.calls.aggressive) == 0
        harness.calls.failClear = False
    else:
        assert len(harness.calls.aggressive) == 1
        harness.calls.failAggressive = False
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
    after_reconcile = plain(harness.controller.fieldCampaign)
    for key in (
        "pendingMode",
        "pendingTokens",
        "pendingEmergencyReason",
        "pendingRecallFieldTokens",
        "pendingRecallHomeTokens",
        "fieldTokens",
        "homeTokens",
        "state",
    ):
        assert after_reconcile.get(key) == before.get(key)


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
    harness, acu, _, _, observation = start_campaign()
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
    aggressive_before = len(harness.calls.aggressive)
    execute_intents(harness, resume, ready)
    assert len(harness.calls.aggressive) == aggressive_before + 1
    assert actor_tokens_from_call(harness.calls.aggressive[aggressive_before + 1]) == field
    assert len(harness.calls.guard) == 0
    assert harness.controller.fieldCampaign.state == "active"
    assert harness.controller.fieldCampaign.emergency is False
    assert harness.controller.fieldCampaign.modeSwitches == 2

    harness.brain.tick = 1102
    stable = reconcile(harness)
    assert not [
        intent for intent in campaign_intents(harness, stable)
        if intent.get("mode") in {"recall", "resume"}
    ]


@pytest.mark.parametrize(
    ("tick", "expected_mode"),
    [(299, None), (300, None), (599, None), (600, "rollback")],
)
def test_stuck_recovery_has_an_exact_300_tick_lower_bound_and_rate_limit(
    tick: int,
    expected_mode: str | None,
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
    modes = [intent.get("mode") for intent in campaign_intents(harness, current)]
    assert modes == ([] if expected_mode is None else [expected_mode])
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


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("home_survivors", [0, 3])
def test_immediate_contact_with_an_attrited_home_reserve_recalls_the_sticky_field_once(
    seed: int,
    home_survivors: int,
) -> None:
    harness, _, _, _, field, home, current = attrited_home_campaign(
        seed=seed,
        home_survivors=home_survivors,
    )
    macro = plain(current)["macro"]
    campaign = campaign_intents(harness, current)

    assert macro.get("fieldTokens") == field
    assert (macro.get("homeTokens") or []) == home[:home_survivors]
    assert macro.get("homeUnits") == home_survivors
    assert len(campaign) == 1
    assert campaign[0].get("mode") == "recall"
    assert campaign[0].get("actorTokens") == field
    assert campaign[0].get("position") == plain(current.basePosition)
    assert plain(harness.controller.fieldCampaign).get("pendingEmergencyReason") == (
        "home_reserve"
    )


@pytest.mark.parametrize(
    "enemy_x,home_survivors,expect_recall",
    [
        (30, 3, True),
        (30.01, 3, False),
        (15, 4, False),
    ],
)
def test_home_reserve_recall_uses_exact_contact_and_four_defender_boundaries(
    enemy_x: float,
    home_survivors: int,
    expect_recall: bool,
) -> None:
    harness, _, _, _, field, home, current = attrited_home_campaign(
        home_survivors=home_survivors,
        enemy_x=enemy_x,
    )
    campaign = campaign_intents(harness, current)
    recalls = [intent for intent in campaign if intent.get("mode") == "recall"]
    defend = [
        intent for intent in policy_intents(harness, current)
        if intent.get("kind") == "defend_wave"
    ]

    assert bool(recalls) is expect_recall
    assert plain(harness.controller.fieldCampaign.fieldTokens) == field
    assert plain(harness.controller.fieldCampaign.homeTokens) == home[:home_survivors]
    if not expect_recall and home_survivors == 4:
        assert len(defend) == 1
        assert defend[0].get("actorTokens") == home[:4]
        assert set(defend[0].get("actorTokens") or []).isdisjoint(field)


@pytest.mark.parametrize("enemy_x", [None, 40])
def test_non_immediate_contact_or_attrition_alone_never_reshuffles_or_recalls_field(
    enemy_x: float | None,
) -> None:
    harness, _, _, _, field, _, current = attrited_home_campaign(
        home_survivors=0,
        enemy_x=enemy_x,
    )

    assert not [
        intent for intent in campaign_intents(harness, current)
        if intent.get("mode") == "recall"
    ]
    assert plain(harness.controller.fieldCampaign.fieldTokens) == field
    assert (plain(harness.controller.fieldCampaign.homeTokens) or []) == []


@pytest.mark.parametrize("failure", ["clear", "move"])
def test_home_reserve_emergency_recall_is_atomic_retryable_and_one_per_episode(
    failure: str,
) -> None:
    harness, _, _, _, field, _, current = attrited_home_campaign(home_survivors=0)
    recall = campaign_intents(harness, current)
    assert len(recall) == 1 and recall[0].get("mode") == "recall"
    before = plain(harness.controller.fieldCampaign)
    order_events_before = len(
        [line for line in harness.logs if "event=campaign_order" in line]
    )
    if failure == "clear":
        harness.calls.failClear = True
    else:
        harness.calls.failMove = True

    execute_intents(harness, recall, current)

    assert plain(harness.controller.fieldCampaign) == before
    assert len(
        [line for line in harness.logs if "event=campaign_order" in line]
    ) == order_events_before
    if failure == "clear":
        assert len(harness.calls.move) == 0
        harness.calls.failClear = False
    else:
        assert len(harness.calls.move) == 1
        harness.calls.failMove = False
    execute_intents(harness, recall, current)
    assert harness.controller.fieldCampaign.state == "recalled"
    assert harness.controller.fieldCampaign.emergencyReason == "home_reserve"
    emergency_field, emergency_home = expected_attrition_emergency_cohorts(field)
    assert plain(harness.controller.fieldCampaign.fieldTokens) == emergency_field
    assert plain(harness.controller.fieldCampaign.homeTokens) == emergency_home
    assert actor_tokens_from_call(harness.calls.move[len(harness.calls.move)]) == field
    assert_campaign_cohort_indexes(harness.controller.fieldCampaign)
    recall_events = [
        line
        for line in harness.logs
        if "event=campaign_order" in line and "command=recall" in line
    ]
    assert len(recall_events) == 1
    clear_after = len(harness.calls.clear)
    move_after = len(harness.calls.move)

    for tick in [21, 100, 500]:
        harness.brain.tick = tick
        contact = reconcile(harness)
        execute_intents(harness, campaign_intents(harness, contact), contact)

    assert len(harness.calls.clear) == clear_after
    assert len(harness.calls.move) == move_after
    assert plain(harness.controller.fieldCampaign.fieldTokens) == emergency_field
    assert plain(harness.controller.fieldCampaign.homeTokens) == emergency_home


@pytest.mark.parametrize("seed", range(3))
def test_same_tick_immediate_defense_and_attrition_recall_use_disjoint_exact_actors(
    seed: int,
) -> None:
    harness, _, _, _, field, home, current = attrited_home_campaign(
        seed=seed,
        home_survivors=3,
    )
    intents = policy_intents(harness, current)
    recall = [
        intent
        for intent in intents
        if intent.get("kind") == CAMPAIGN_KIND and intent.get("mode") == "recall"
    ]
    defend = [intent for intent in intents if intent.get("kind") == "defend_wave"]

    assert len(recall) == 1 and recall[0].get("actorTokens") == field
    assert len(defend) == 1 and defend[0].get("actorTokens") == home[:3]
    assert set(recall[0].get("actorTokens") or []).isdisjoint(
        defend[0].get("actorTokens") or []
    )
    execute_intents(harness, intents, current)

    expected_field, expected_home = expected_attrition_emergency_cohorts(
        field,
        home[:3],
    )
    move_actor_sets = [
        actor_tokens_from_call(harness.calls.move[index])
        for index in range(1, len(harness.calls.move) + 1)
    ]
    aggressive_actor_sets = [
        actor_tokens_from_call(harness.calls.aggressive[index])
        for index in range(1, len(harness.calls.aggressive) + 1)
    ]
    assert field in move_actor_sets
    assert home[:3] in aggressive_actor_sets
    assert plain(harness.controller.fieldCampaign.fieldTokens) == expected_field
    assert plain(harness.controller.fieldCampaign.homeTokens) == expected_home
    assert_campaign_cohort_indexes(harness.controller.fieldCampaign)


def test_home_reserve_emergency_resumes_once_after_four_defenders_and_300_safe_ticks() -> None:
    harness, acu, engineer, field_units, field, _, current = attrited_home_campaign(
        home_survivors=0
    )
    recall = campaign_intents(harness, current)
    assert len(recall) == 1 and recall[0].get("mode") == "recall"
    execute_intents(harness, recall, current)
    emergency_field, emergency_home = expected_attrition_emergency_cohorts(field)
    harness.brain.units = harness.lua.table_from([acu, engineer, *field_units])
    harness.brain.tick = 21
    under_contact = reconcile(harness)
    assert campaign_intents(harness, under_contact) == []
    assert plain(under_contact)["macro"].get("fieldTokens") == emergency_field
    assert plain(under_contact)["macro"].get("homeTokens") == emergency_home

    restore_combat_readiness(harness, acu, engineer, field_units)
    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 100
    first_safe = reconcile(harness)
    assert campaign_intents(harness, first_safe) == []
    harness.brain.tick = 399
    safe_299 = reconcile(harness)
    assert campaign_intents(harness, safe_299) == []
    harness.brain.tick = 400
    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)

    assert len(resume) == 1 and resume[0].get("mode") == "resume"
    assert len(resume[0].get("actorTokens") or []) == 18
    assert set(emergency_field) <= set(resume[0].get("actorTokens") or [])
    execute_intents(harness, resume, ready)
    assert harness.controller.fieldCampaign.state == "active"
    assert harness.controller.fieldCampaign.emergency is False
    assert harness.controller.fieldCampaign.emergencyReason is None
    assert harness.controller.fieldCampaign.modeSwitches == 2
    assert_campaign_cohort_indexes(harness.controller.fieldCampaign)
    harness.brain.tick = 401
    stable = reconcile(harness)
    assert not [
        intent for intent in campaign_intents(harness, stable)
        if intent.get("mode") in {"recall", "resume"}
    ]


def test_home_reserve_safe_window_resets_on_contact_flicker() -> None:
    harness, acu, engineer, field_units, _, _, current = attrited_home_campaign(
        home_survivors=0
    )
    recall = campaign_intents(harness, current)
    assert len(recall) == 1 and recall[0].get("mode") == "recall"
    execute_intents(harness, recall, current)
    restore_combat_readiness(harness, acu, engineer, field_units)
    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 100
    reconcile(harness)
    harness.brain.tick = 399
    assert campaign_intents(harness, reconcile(harness)) == []
    enemy = harness.unit(
        entityId=99001,
        blueprintId="uel0201",
        army=2,
        position=[15, 2, 20],
    )
    harness.brain.enemies = harness.lua.table_from([enemy])
    harness.brain.tick = 400
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 401
    reconcile(harness)
    harness.brain.tick = 700
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 701
    resume = campaign_intents(harness, reconcile(harness))
    assert len(resume) == 1 and resume[0].get("mode") == "resume"


@pytest.mark.parametrize("home_survivors", [0, 3])
def test_successful_attrition_rebalance_restores_exact_home_defenders_next_tick(
    home_survivors: int,
) -> None:
    harness, _, _, _, field, home, current = attrited_home_campaign(
        home_survivors=home_survivors
    )
    execute_intents(harness, campaign_intents(harness, current), current)
    expected_field, expected_home = expected_attrition_emergency_cohorts(
        field,
        home[:home_survivors],
    )
    harness.brain.tick = 21
    next_contact = reconcile(harness)
    defend = [
        intent for intent in policy_intents(harness, next_contact)
        if intent.get("kind") == "defend_wave"
    ]

    assert plain(next_contact)["macro"].get("fieldTokens") == expected_field
    assert plain(next_contact)["macro"].get("homeTokens") == expected_home
    assert len(defend) == 1
    assert defend[0].get("actorTokens") == expected_home
    assert set(defend[0].get("actorTokens") or []).isdisjoint(expected_field)
    aggressive_before = len(harness.calls.aggressive)
    execute_intents(harness, defend, next_contact)
    assert len(harness.calls.aggressive) == aggressive_before + 1
    assert actor_tokens_from_call(
        harness.calls.aggressive[len(harness.calls.aggressive)]
    ) == expected_home


def test_failed_attrition_recall_latches_across_contact_clear_and_reconcile() -> None:
    harness, _, _, _, _, _, current = attrited_home_campaign(home_survivors=0)
    recall = campaign_intents(harness, current)
    harness.calls.failClear = True
    execute_intents(harness, recall, current)
    harness.calls.failClear = False
    before = plain(harness.controller.fieldCampaign)
    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 301

    retry_observation = reconcile(harness)
    retry = campaign_intents(harness, retry_observation)

    after_reconcile = plain(harness.controller.fieldCampaign)
    assert after_reconcile["pendingMode"] == before["pendingMode"] == "recall"
    assert after_reconcile["pendingTokens"] == before["pendingTokens"]
    assert after_reconcile["pendingRecallFieldTokens"] == before["pendingRecallFieldTokens"]
    assert after_reconcile["pendingRecallHomeTokens"] == before["pendingRecallHomeTokens"]
    assert after_reconcile["fieldTokens"] == before["fieldTokens"]
    assert after_reconcile["homeTokens"] == before["homeTokens"]
    assert after_reconcile["state"] == before["state"]
    assert len(retry) == 1 and retry[0].get("mode") == "recall"
    execute_intents(harness, retry, retry_observation)
    assert harness.controller.fieldCampaign.state == "recalled"
    assert harness.controller.fieldCampaign.emergencyReason == "home_reserve"


@pytest.mark.parametrize("cohort", ["field", "home"])
@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_attrition_recall_revalidates_every_staged_cohort_generation_before_clear(
    cohort: str,
    mutation: str,
) -> None:
    harness, acu, engineer, live_combat, field, home, stale = attrited_home_campaign(
        home_survivors=3
    )
    recall = campaign_intents(harness, stale)
    token = field[-1] if cohort == "field" else home[0]
    entity_id = int(token.split(":", 1)[0])
    actor = next(
        unit for unit in live_combat
        if int(unit.options.entityId) == entity_id
    )
    units = [acu, engineer, *live_combat]
    if mutation == "dead":
        actor.Dead = True
    elif mutation == "captured":
        actor.options.army = 2
    else:
        replacement = harness.unit(
            entityId=entity_id,
            blueprintId="uel0201",
            position=[10, 2, 20],
        )
        units[units.index(actor)] = replacement
    harness.brain.units = harness.lua.table_from(units)
    harness.observe()
    before = plain(harness.controller.fieldCampaign)
    clear_before = len(harness.calls.clear)
    move_before = len(harness.calls.move)

    execute_intents(harness, recall, stale)

    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.move) == move_before
    assert plain(harness.controller.fieldCampaign) == before
    harness.brain.tick = 21
    fresh = reconcile(harness)
    retry = campaign_intents(harness, fresh)
    assert len(retry) == 1 and retry[0].get("mode") == "recall"
    execute_intents(harness, retry, fresh)
    assert harness.controller.fieldCampaign.state == "recalled"
    assert_campaign_cohort_indexes(harness.controller.fieldCampaign)


@pytest.mark.parametrize("seed", range(3))
def test_nearest_base_distractor_cannot_hide_position_only_immediate_acu_contact(
    seed: int,
) -> None:
    harness, acu, _, _, _, _, _ = attrited_home_campaign(
        seed=seed,
        home_survivors=0,
        enemy_x=None,
    )
    acu.options.position = lua_value(harness.lua, [50, 2, 20])
    distractor = harness.unit(
        entityId=99010,
        blueprintId="uel0201",
        army=2,
        position=[11, 2, 20],
    )
    immediate = harness.unit(
        entityId=99011,
        blueprintId="uel0201",
        army=2,
        position=[35, 2, 20],
    )
    forbidden = harness.lua.eval("function() error('forbidden enemy intel') end")
    for enemy in [distractor, immediate]:
        enemy.GetBlueprint = forbidden
        enemy.GetArmy = forbidden
    enemies = [distractor, immediate]
    random.Random(seed).shuffle(enemies)
    harness.brain.enemies = harness.lua.table_from(enemies)
    harness.brain.tick = 21

    current = reconcile(harness)
    recall = campaign_intents(harness, current)
    contact = plain(current.enemyContact)

    assert contact.get("immediate") is True
    assert contact.get("position") == [35, 2, 20]
    assert len(recall) == 1 and recall[0].get("mode") == "recall"
    enemy_body = source("lua/AI/Overmind4/Controller.lua").split(
        "local function NormalizeEnemyContact", 1
    )[1].split("local function SiteSnapshot", 1)[0]
    assert "GetBlueprint" not in enemy_body
    assert "GetArmy" not in enemy_body


@pytest.mark.parametrize("blocking_enemy_x", [15, 40])
def test_any_contact_resets_attrition_resume_safe_window(
    blocking_enemy_x: float,
) -> None:
    harness, acu, engineer, field_units, _, _, current = attrited_home_campaign(
        home_survivors=0
    )
    execute_intents(harness, campaign_intents(harness, current), current)
    restore_combat_readiness(harness, acu, engineer, field_units)
    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 100
    reconcile(harness)
    harness.brain.tick = 399
    assert not [
        intent for intent in campaign_intents(harness, reconcile(harness))
        if intent.get("mode") == "resume"
    ]
    blocker = harness.unit(
        entityId=99020,
        blueprintId="uel0201",
        army=2,
        position=[blocking_enemy_x, 2, 20],
    )
    harness.brain.enemies = harness.lua.table_from([blocker])
    harness.brain.tick = 400
    assert not [
        intent for intent in campaign_intents(harness, reconcile(harness))
        if intent.get("mode") == "resume"
    ]
    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 401
    reconcile(harness)
    harness.brain.tick = 700
    assert not [
        intent for intent in campaign_intents(harness, reconcile(harness))
        if intent.get("mode") == "resume"
    ]
    harness.brain.tick = 701
    ready = campaign_intents(harness, reconcile(harness))
    assert len(ready) == 1 and ready[0].get("mode") == "resume"


def test_attrition_resume_waits_for_four_live_home_defenders_then_300_ticks() -> None:
    harness, acu, engineer, field_units, _, _, current = attrited_home_campaign(
        home_survivors=0
    )
    execute_intents(harness, campaign_intents(harness, current), current)
    campaign = plain(harness.controller.fieldCampaign)
    field = campaign["fieldTokens"]
    home = campaign["homeTokens"]
    by_token = {
        f"{int(actor.options.entityId)}:1": actor
        for actor in field_units
    }
    for token in home[3:]:
        by_token[token].Dead = True
    three_home_units = [by_token[token] for token in [*field, *home[:3]]]
    harness.brain.units = harness.lua.table_from([acu, engineer, *three_home_units])
    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 100
    at_three = reconcile(harness)
    assert plain(at_three)["macro"].get("homeUnits") == 3
    assert campaign_intents(harness, at_three) == []
    replacement = harness.unit(
        entityId=9300,
        blueprintId="uel0201",
        position=[10, 2, 20],
    )
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, *three_home_units, replacement]
    )
    restore_combat_readiness(
        harness,
        acu,
        engineer,
        [*three_home_units, replacement],
        start_id=96100,
    )
    harness.brain.tick = 200
    reconcile(harness)
    harness.brain.tick = 499
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 500
    resume = campaign_intents(harness, reconcile(harness))
    assert len(resume) == 1 and resume[0].get("mode") == "resume"


def test_attrition_resume_safe_window_resets_when_acu_dips_below_point_seven_five() -> None:
    harness, acu, engineer, field_units, _, _, current = attrited_home_campaign(
        home_survivors=0
    )
    execute_intents(harness, campaign_intents(harness, current), current)
    assert harness.controller.fieldCampaign.state == "recalled"
    restore_combat_readiness(harness, acu, engineer, field_units, start_id=96200)
    harness.brain.enemies = harness.lua.table_from([])
    acu.options.health = 75
    harness.brain.tick = 100
    reconcile(harness)
    harness.brain.tick = 399
    assert campaign_intents(harness, reconcile(harness)) == []

    acu.options.health = 74.9
    harness.brain.tick = 400
    assert campaign_intents(harness, reconcile(harness)) == []
    assert harness.controller.fieldCampaign.healthySinceTick is None

    acu.options.health = 75
    harness.brain.tick = 401
    reconcile(harness)
    harness.brain.tick = 700
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 701
    resume = campaign_intents(harness, reconcile(harness))
    assert len(resume) == 1 and resume[0].get("mode") == "resume"


def test_recalled_attrition_campaign_defers_full_gate_until_composite_safe_window() -> None:
    harness, acu, engineer, field_units, field, _, current = attrited_home_campaign(
        home_survivors=0
    )
    execute_intents(harness, campaign_intents(harness, current), current)
    emergency_field, emergency_home = expected_attrition_emergency_cohorts(field)
    campaign = harness.controller.fieldCampaign
    assert campaign.state == "recalled"
    assert campaign.fullCohorts is False
    assert plain(campaign.orderedTokens) == {}
    assert plain(campaign.fieldTokens) == emergency_field
    assert plain(campaign.homeTokens) == emergency_home

    reinforcements = [
        harness.unit(
            entityId=9300,
            blueprintId="uel0104",
            position=[10, 2, 20],
        )
    ] + [
        harness.unit(
            entityId=9301 + index,
            blueprintId="uel0201",
            position=[10, 2, 20],
        )
        for index in range(5)
    ]
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, *field_units, *reinforcements]
    )
    harness.brain.tick = 320
    under_contact = reconcile(harness)
    assert campaign_intents(harness, under_contact) == []
    assert plain(campaign.fieldTokens) == emergency_field
    assert len(campaign.homeTokens) == 20
    assert campaign.fullCohorts is False

    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 321
    reconcile(harness)
    harness.brain.tick = 620
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 621
    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)
    expected_field = field
    expected_home = sorted(
        f"{int(actor.options.entityId)}:1" for actor in reinforcements
    )

    assert len(resume) == 1 and resume[0].get("mode") == "resume"
    assert resume[0].get("actorTokens") == expected_field
    assert plain(campaign.fieldTokens) == expected_field
    assert plain(campaign.homeTokens) == expected_home
    assert campaign.fullCohorts is True
    execute_intents(harness, resume, ready)
    assert campaign.state == "active"
    assert campaign.emergency is False
    assert_campaign_cohort_indexes(campaign)


@pytest.mark.parametrize("seed", range(4))
def test_health_recalled_campaign_stages_home_reserve_rebalance_after_home_attrition(
    seed: int,
) -> None:
    harness, _, _, _, field, _, current = health_recalled_home_attrition(seed=seed)
    intents = campaign_intents(harness, current)
    campaign = plain(harness.controller.fieldCampaign)
    expected_field, expected_home = expected_attrition_emergency_cohorts(field)

    assert campaign.get("state") == "recalled"
    assert campaign.get("emergencyReason") == "acu_health"
    assert not [intent for intent in intents if intent.get("mode") == "resume"]
    assert len(intents) == 1 and intents[0].get("mode") == "recall"
    assert intents[0].get("actorTokens") == field
    assert campaign.get("pendingEmergencyReason") == "home_reserve"
    assert campaign.get("pendingRecallFieldTokens") == expected_field
    assert campaign.get("pendingRecallHomeTokens") == expected_home


@pytest.mark.parametrize("seed", range(4))
def test_recalled_home_rebalance_stages_a_second_epoch_after_demoted_home_dies(
    seed: int,
) -> None:
    harness, _, _, _, emergency_field, _, current = second_recalled_attrition_epoch(
        seed=seed
    )
    intents = campaign_intents(harness, current)
    campaign = plain(harness.controller.fieldCampaign)

    assert campaign.get("state") == "recalled"
    assert campaign.get("emergencyReason") == "home_reserve"
    assert len(intents) == 1 and intents[0].get("mode") == "recall"
    assert intents[0].get("actorTokens") == emergency_field
    assert (campaign.get("pendingRecallFieldTokens") or []) == []
    assert campaign.get("pendingRecallHomeTokens") == emergency_field
    assert not [intent for intent in intents if intent.get("mode") == "resume"]


@pytest.mark.parametrize(
    "home_survivors,enemy_x,expect_recall",
    [
        (3, 30, True),
        (3, 30.01, False),
        (3, 40, False),
        (4, 15, False),
    ],
)
def test_recalled_home_attrition_uses_exact_immediate_and_four_home_boundaries(
    home_survivors: int,
    enemy_x: float,
    expect_recall: bool,
) -> None:
    harness, _, _, _, _, home, current = health_recalled_home_attrition(
        home_survivors=home_survivors,
        enemy_x=enemy_x,
    )
    recall = [
        intent
        for intent in campaign_intents(harness, current)
        if intent.get("mode") == "recall"
    ]

    assert bool(recall) is expect_recall
    assert plain(harness.controller.fieldCampaign.homeTokens) == home[:home_survivors]
    assert not [
        intent
        for intent in campaign_intents(harness, current)
        if intent.get("mode") == "resume"
    ]


@pytest.mark.parametrize("failure", ["clear", "move"])
@pytest.mark.parametrize("epoch", ["health", "second"])
def test_recalled_attrition_rebalance_failure_latches_across_contact_flicker(
    failure: str,
    epoch: str,
) -> None:
    if epoch == "health":
        harness, _, _, _, expected_actors, _, current = health_recalled_home_attrition()
    else:
        harness, _, _, _, expected_actors, _, current = second_recalled_attrition_epoch()
    recall = campaign_intents(harness, current)
    assert len(recall) == 1 and recall[0].get("mode") == "recall"
    before = plain(harness.controller.fieldCampaign)
    events_before = len(
        [line for line in harness.logs if "event=campaign_order" in line]
    )
    if failure == "clear":
        harness.calls.failClear = True
    else:
        harness.calls.failMove = True

    execute_intents(harness, recall, current)

    assert plain(harness.controller.fieldCampaign) == before
    assert len(
        [line for line in harness.logs if "event=campaign_order" in line]
    ) == events_before
    if failure == "clear":
        harness.calls.failClear = False
    else:
        harness.calls.failMove = False
    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick += 1
    retry_observation = reconcile(harness)
    retry = campaign_intents(harness, retry_observation)

    assert len(retry) == 1 and retry[0].get("mode") == "recall"
    assert retry[0].get("actorTokens") == expected_actors
    execute_intents(harness, retry, retry_observation)
    assert harness.controller.fieldCampaign.state == "recalled"
    assert harness.controller.fieldCampaign.pendingMode is None
    assert_campaign_cohort_indexes(harness.controller.fieldCampaign)
    success_events = [
        line
        for line in harness.logs
        if "event=campaign_order" in line and "command=recall" in line
    ]
    assert len(success_events) == 2


@pytest.mark.parametrize("cohort", ["field", "home"])
@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_recalled_attrition_revalidates_staged_generations_before_first_clear(
    cohort: str,
    mutation: str,
) -> None:
    harness, acu, engineer, live_combat, field, home, stale = (
        health_recalled_home_attrition(home_survivors=3)
    )
    recall = campaign_intents(harness, stale)
    assert len(recall) == 1 and recall[0].get("mode") == "recall"
    token = field[-1] if cohort == "field" else home[0]
    entity_id = int(token.split(":", 1)[0])
    actor = next(
        unit
        for unit in live_combat
        if int(unit.options.entityId) == entity_id
    )
    units = [acu, engineer, *live_combat]
    if mutation == "dead":
        actor.Dead = True
    elif mutation == "captured":
        actor.options.army = 2
    else:
        replacement = harness.unit(
            entityId=entity_id,
            blueprintId="uel0201",
            position=[10, 2, 20],
        )
        units[units.index(actor)] = replacement
    harness.brain.units = harness.lua.table_from(units)
    harness.observe()
    before = plain(harness.controller.fieldCampaign)
    clear_before = len(harness.calls.clear)
    move_before = len(harness.calls.move)

    execute_intents(harness, recall, stale)

    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.move) == move_before
    assert plain(harness.controller.fieldCampaign) == before
    harness.brain.tick += 1
    fresh = reconcile(harness)
    retry = campaign_intents(harness, fresh)
    assert len(retry) == 1 and retry[0].get("mode") == "recall"
    execute_intents(harness, retry, fresh)
    assert harness.controller.fieldCampaign.state == "recalled"
    assert_campaign_cohort_indexes(harness.controller.fieldCampaign)


def test_repeated_recalled_attrition_epochs_emit_once_and_restore_defenders_each_time() -> None:
    harness, acu, engineer, live_combat, field, _, current = health_recalled_home_attrition()
    first = campaign_intents(harness, current)
    execute_intents(harness, first, current)
    first_field, first_home = expected_attrition_emergency_cohorts(field)
    assert plain(harness.controller.fieldCampaign.fieldTokens) == first_field
    assert plain(harness.controller.fieldCampaign.homeTokens) == first_home
    harness.brain.tick = 21
    stable_contact = reconcile(harness)
    assert campaign_intents(harness, stable_contact) == []
    first_defend = [
        intent
        for intent in policy_intents(harness, stable_contact)
        if intent.get("kind") == "defend_wave"
    ]
    assert len(first_defend) == 1
    assert first_defend[0].get("actorTokens") == first_home
    assert set(first_defend[0].get("actorTokens") or []).isdisjoint(first_field)

    by_token = {
        f"{int(actor.options.entityId)}:1": actor
        for actor in live_combat
    }
    for token in first_home:
        by_token[token].Dead = True
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, *[by_token[token] for token in first_field]]
    )
    harness.brain.tick = 30
    second_observation = reconcile(harness)
    second = campaign_intents(harness, second_observation)
    assert len(second) == 1 and second[0].get("mode") == "recall"
    execute_intents(harness, second, second_observation)

    assert (plain(harness.controller.fieldCampaign.fieldTokens) or []) == []
    assert plain(harness.controller.fieldCampaign.homeTokens) == first_field
    assert harness.controller.fieldCampaign.modeSwitches == 3
    clear_after = len(harness.calls.clear)
    move_after = len(harness.calls.move)
    for tick in [31, 100, 600]:
        harness.brain.tick = tick
        stable = reconcile(harness)
        execute_intents(harness, campaign_intents(harness, stable), stable)
    assert len(harness.calls.clear) == clear_after
    assert len(harness.calls.move) == move_after
    final_defend = [
        intent
        for intent in policy_intents(harness, stable)
        if intent.get("kind") == "defend_wave"
    ]
    assert len(final_defend) == 1
    assert final_defend[0].get("actorTokens") == first_field


@pytest.mark.parametrize("remaining", [1, 2, 3, 4])
def test_recalled_attrition_with_four_or_fewer_survivors_demotes_all_and_stops(
    remaining: int,
) -> None:
    harness, _, _, _, emergency_field, _, current = second_recalled_attrition_epoch(
        remaining_field=remaining
    )
    survivors = emergency_field[:remaining]
    recall = campaign_intents(harness, current)

    assert len(recall) == 1 and recall[0].get("actorTokens") == survivors
    execute_intents(harness, recall, current)
    assert (plain(harness.controller.fieldCampaign.fieldTokens) or []) == []
    assert plain(harness.controller.fieldCampaign.homeTokens) == survivors
    assert_campaign_cohort_indexes(harness.controller.fieldCampaign)
    calls_after = (len(harness.calls.clear), len(harness.calls.move))
    for tick in [31, 100, 500]:
        harness.brain.tick = tick
        stable = reconcile(harness)
        assert campaign_intents(harness, stable) == []
    assert (len(harness.calls.clear), len(harness.calls.move)) == calls_after
    defend = [
        intent
        for intent in policy_intents(harness, stable)
        if intent.get("kind") == "defend_wave"
    ]
    assert len(defend) == 1
    assert defend[0].get("actorTokens") == survivors


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


@pytest.mark.parametrize("failure", ["clear", "aggressive"])
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
        harness.calls.failAggressive = True
    execute_intents(harness, recover, current)
    assert plain(harness.controller.fieldCampaign) == before
    if failure == "clear":
        harness.calls.failClear = False
    else:
        harness.calls.failAggressive = False
    execute_intents(harness, recover, current)
    assert harness.controller.fieldCampaign.recoveryOrders == 1
    assert harness.controller.fieldCampaign.lastRecoveryAttemptTick == 300
    harness.brain.tick = 599
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 600
    again = campaign_intents(harness, reconcile(harness))
    assert len(again) == 1 and again[0].get("mode") == "rollback"


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


def test_campaign_engineer_finishes_cached_area_members_before_unrelated_work() -> None:
    second = layered_marker("cluster-a-2", 90, 20)
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


def test_one_campaign_connected_job_does_not_serialize_independent_expansion() -> None:
    second = marker("cluster-a-2", 90, 20)
    independent = marker("independent", 140, 20)
    harness, acu, engineer, combat, observation = start_campaign(
        extra_markers=[second, independent]
    )
    extra_engineer = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        position=[13, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([acu, engineer, extra_engineer, *combat])
    harness.brain.massIncome = 2
    harness.brain.massRequested = 0.5
    harness.brain.massUsage = 0.5
    harness.brain.massTrend = 1.5
    harness.brain.energyIncome = 30
    harness.brain.energyRequested = 10
    harness.brain.energyUsage = 10
    harness.brain.energyTrend = 20
    harness.brain.massStored = 100
    harness.brain.energyStored = 1000
    harness.brain.tick = 10
    current = reconcile(harness)
    frontier = [
        intent for intent in policy_intents(harness, current)
        if intent.get("reason") == "frontier_expansion"
    ]
    assert len(frontier) == 1
    assert frontier[0]["actorToken"] == "3:1"
    assert frontier[0]["siteKey"] == "independent"
    assert frontier[0].get("clusterKey") is None


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

    if mutation == "recycled":
        assert len(activation) == 1
        assert activation[0].get("mode") == "activate"
        assert activation[0].get("actorTokens") == macro.get("fieldTokens")
        assert "1000:1" not in activation[0].get("actorTokens")
        assert "1000:2" in activation[0].get("actorTokens")
    else:
        assert activation == []
        assert macro.get("campaignReady") is False
        assert macro.get("campaignIntentMode") == "none"
        assert harness.controller.fieldCampaign.state == "awaiting_order"


def test_static_live_runtime_defaults_to_campaign_and_gates_every_legacy_screen_path() -> None:
    controller_source = source("lua/AI/Overmind4/Controller.lua")
    policy_source = source("lua/AI/Overmind4/Policy.lua")

    assert "fieldCampaignEnabled = true" in controller_source
    assert "intent.kind == 'frontier_screen'" in controller_source
    assert "or controller.fieldCampaign == nil" in controller_source
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


def test_campaign_waits_at_idle_until_full_gate_then_activates_once() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=23, aa=2)
    assert harness.controller.fieldCampaign is None
    assert campaign_intents(harness, observation) == []
    promoted = harness.unit(entityId=9000, blueprintId="uel0201", position=[10, 2, 20])
    harness.brain.units = harness.lua.table_from([acu, engineer, *combat, promoted])
    harness.brain.tick = 1
    ready = reconcile(harness)
    activation = campaign_intents(harness, ready)
    assert len(activation) == 1 and activation[0].get("mode") == "activate"
    assert len(activation[0].get("actorTokens") or []) == 18
    execute_intents(harness, activation, ready)
    assert harness.controller.fieldCampaign.state == "active"
    assert harness.controller.fieldCampaign.fullFieldOrders == 1
    harness.brain.tick = 2
    assert campaign_intents(harness, reconcile(harness)) == []


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
    restore_combat_readiness(
        harness,
        acu,
        engineer,
        home_units,
        start_id=9400,
    )
    acu.options.health = 75
    harness.brain.tick = 12
    reconcile(harness)
    harness.brain.tick = 311
    assert campaign_intents(harness, reconcile(harness)) == []
    harness.brain.tick = 312

    ready = reconcile(harness)
    resume = campaign_intents(harness, ready)

    assert plain(ready)["macro"].get("fieldUnits") == 18
    assert plain(ready)["macro"].get("homeUnits") == 6
    assert len(resume) == 1 and resume[0].get("mode") == "resume"
    assert len(resume[0].get("actorTokens") or []) == 18
    execute_intents(harness, resume, ready)
    assert harness.controller.fieldCampaign.state == "active"


def test_campaign_hot_membership_consumers_use_constant_time_token_indexes() -> None:
    controller_source = source("lua/AI/Overmind4/Controller.lua")
    bodies = {
        "normalize": controller_source.split(
            "local function NormalizeOwnUnit", 1
        )[1].split("local function NormalizeEnemyContact", 1)[0],
        "macro": controller_source.split(
            "local function MacroSnapshot", 1
        )[1].split("local function PlacementSnapshot", 1)[0],
        "flags": controller_source.split(
            "local function ApplyCampaignFlags", 1
        )[1].split("local function RelevantCampaignOperation", 1)[0],
        "combat": controller_source.split(
            "local function ExecuteCombatGroup", 1
        )[1].split("local function ExecuteRetreat", 1)[0],
        "campaign_execute": controller_source.split(
            "local function ExecuteFieldCampaign", 1
        )[1].split("Controller = {}", 1)[0],
    }

    for name, body in bodies.items():
        assert "ArrayContains" not in body, name
    prune = controller_source.split(
        "local function CampaignPruneAndFill", 1
    )[1].split("local function ApplyCampaignFlags", 1)[0]
    assert "table.sort(field)" not in prune
    assert "table.sort(home)" not in prune
    assert "fieldTokenSet" in controller_source
    assert "homeTokenSet" in controller_source


def test_one_thousand_unit_campaign_keeps_exact_indexes_and_stable_array_identity() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=1000, aa=14)
    activate_campaign(harness, observation)
    campaign = harness.controller.fieldCampaign
    assert_campaign_cohort_indexes(campaign)
    assert len(campaign.fieldTokens) == 750
    assert len(campaign.homeTokens) == 250
    field_reference = campaign.fieldTokens
    home_reference = campaign.homeTokens
    field_index_reference = campaign.fieldTokenSet
    home_index_reference = campaign.homeTokenSet
    rawequal = harness.lua.eval("rawequal")

    permutations = [
        list(reversed(combat)),
        combat[::2] + combat[1::2],
        list(combat),
    ]
    for tick, reordered in enumerate(permutations, start=10):
        harness.brain.units = harness.lua.table_from([*reordered, engineer, acu])
        harness.brain.tick = tick
        current = reconcile(harness)
        campaign = harness.controller.fieldCampaign

        assert_campaign_cohort_indexes(campaign)
        assert rawequal(field_reference, campaign.fieldTokens)
        assert rawequal(home_reference, campaign.homeTokens)
        assert rawequal(field_index_reference, campaign.fieldTokenSet)
        assert rawequal(home_index_reference, campaign.homeTokenSet)
        macro = plain(current)["macro"]
        assert macro.get("fieldTokens") == plain(field_reference)
        assert macro.get("homeTokens") == plain(home_reference)
        assert macro.get("fieldUnits") == 750
        assert macro.get("homeUnits") == 250


@pytest.mark.parametrize(
    "corruption",
    ["missing", "overlap", "foreign", "extra_array_key"],
)
def test_campaign_rebuilds_malformed_cohort_indexes_without_changing_assignments(
    corruption: str,
) -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    campaign = harness.controller.fieldCampaign
    field_before = plain(campaign.fieldTokens)
    home_before = plain(campaign.homeTokens)
    field_reference = campaign.fieldTokens
    home_reference = campaign.homeTokens
    campaign.fieldTokenSet = lua_value(
        harness.lua,
        {token: True for token in field_before},
    )
    campaign.homeTokenSet = lua_value(
        harness.lua,
        {token: True for token in home_before},
    )
    if corruption == "missing":
        campaign.fieldTokenSet = None
    elif corruption == "overlap":
        campaign.homeTokenSet[field_before[0]] = True
    elif corruption == "foreign":
        campaign.fieldTokenSet["not-a-live-generation"] = True
    else:
        campaign.fieldTokens["malformed"] = "not-a-live-generation"
    harness.brain.tick = 10

    current = reconcile(harness)

    assert_campaign_cohort_indexes(campaign)
    assert plain(campaign.fieldTokens) == field_before
    assert plain(campaign.homeTokens) == home_before
    assert harness.lua.eval("rawequal")(
        field_reference,
        campaign.fieldTokens,
    ) is (corruption != "extra_array_key")
    assert harness.lua.eval("rawequal")(home_reference, campaign.homeTokens)
    assert plain(current)["macro"].get("fieldTokens") == field_before
    assert plain(current)["macro"].get("homeTokens") == home_before


def test_stable_thousand_unit_reconcile_never_resorts_or_rebuilds_cohorts() -> None:
    harness, acu, engineer, combat, observation = start_campaign(total=1000, aa=14)
    activate_campaign(harness, observation)
    campaign = harness.controller.fieldCampaign
    field_reference = campaign.fieldTokens
    home_reference = campaign.homeTokens
    field_index_reference = campaign.fieldTokenSet
    home_index_reference = campaign.homeTokenSet
    harness.brain.units = harness.lua.table_from(
        [*reversed(combat), engineer, acu]
    )
    harness.brain.tick = 10
    current = harness.observe()
    harness.lua.execute(
        """
        CampaignOriginalSort = table.sort
        CampaignSortSizes = {}
        table.sort = function(values, comparator)
            table.insert(CampaignSortSizes, table.getn(values or {}))
            return CampaignOriginalSort(values, comparator)
        end
        """
    )
    try:
        harness.lua.globals().Controller.Reconcile(harness.controller, current)
    finally:
        harness.lua.execute(
            "table.sort = CampaignOriginalSort; CampaignOriginalSort = nil"
        )

    sort_sizes = plain(harness.lua.globals().CampaignSortSizes) or []
    rawequal = harness.lua.eval("rawequal")
    assert 1000 not in sort_sizes
    assert rawequal(field_reference, campaign.fieldTokens)
    assert rawequal(home_reference, campaign.homeTokens)
    assert rawequal(field_index_reference, campaign.fieldTokenSet)
    assert rawequal(home_index_reference, campaign.homeTokenSet)
    prune = source("lua/AI/Overmind4/Controller.lua").split(
        "local function CampaignPruneAndFill", 1
    )[1].split("local function ApplyCampaignFlags", 1)[0]
    assert prune.index("CampaignCohortsStable") < prune.index("local field = {}")


def test_repaired_false_positive_field_index_restores_home_defender_eligibility() -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    campaign = harness.controller.fieldCampaign
    field, home = expected_initial_cohorts(24, 2)
    poisoned_home = home[0]
    campaign.fieldTokenSet[poisoned_home] = True
    enemy = harness.unit(
        entityId=99100,
        blueprintId="uel0201",
        army=2,
        position=[40, 2, 20],
    )
    harness.brain.enemies = harness.lua.table_from([enemy])
    harness.brain.tick = 10

    current = reconcile(harness)
    record = next(
        unit
        for unit in plain(current.units)
        if unit.get("token") == poisoned_home
    )
    defend = [
        intent
        for intent in policy_intents(harness, current)
        if intent.get("kind") == "defend_wave"
    ]

    assert record.get("fieldCohort") is False
    assert record.get("homeCohort") is True
    assert record.get("assignedToWave") is False
    assert plain(current)["macro"].get("homeReserveCount") == len(home)
    assert len(defend) == 1
    assert defend[0].get("actorTokens") == home
    assert set(defend[0].get("actorTokens") or []).isdisjoint(field)


@pytest.mark.parametrize("index_name", ["fieldTokenSet", "homeTokenSet"])
@pytest.mark.parametrize("malformed", [17, True, "malformed"])
def test_observe_then_reconcile_repairs_non_table_campaign_indexes_fail_closed(
    index_name: str,
    malformed: Any,
) -> None:
    harness, _, _, _, observation = start_campaign()
    activate_campaign(harness, observation)
    campaign = harness.controller.fieldCampaign
    setattr(campaign, index_name, malformed)
    harness.brain.tick = 10

    current = reconcile(harness)

    assert_campaign_cohort_indexes(campaign)
    macro = plain(current)["macro"]
    assert macro.get("fieldUnits") == 18
    assert macro.get("homeUnits") == 6
    assert macro.get("fieldAa") == 1
    assert macro.get("homeAa") == 1
