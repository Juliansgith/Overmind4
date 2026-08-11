from __future__ import annotations

import copy
import itertools
import random
from typing import Any

import pytest

from test_controller import execute_intents, make_harness
from test_economy_escalation import (
    activate_campaign,
    campaign_state,
    economy_policy_snapshot,
    engineer_record,
    only,
    set_support,
)
from test_field_campaign import (
    campaign_intents,
    layered_marker,
    policy_intents,
    reconcile,
    restore_combat_readiness,
    start_campaign,
)
from test_policy import decide, intents_of, lua_value, plain
from test_pressure_front_campaign import (
    activate_pressure_front,
    complete_mex,
    forward_graph_campaign,
    hold_cluster,
)
from test_secured_frontier_doctrine import macro_snapshot, mass_site


def placement_key(position: list[float]) -> str:
    return f"Placement:{round(position[0] * 1000)}:{round(position[2] * 1000)}"


def placement_builds(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        intent
        for intent in intents_of(decide(snapshot), "build_structure")
        if intent.get("siteKey") is None
    ]


def footprint_rect(role: str, position: list[float]) -> tuple[float, float, float, float]:
    if role in {"power_generator", "mass_extractor"}:
        size = 2
    elif role == "hydrocarbon":
        size = 6
    else:
        size = 8
    half = size / 2
    return position[0] - half, position[2] - half, position[0] + half, position[2] + half


def footprints_overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return (
        left[0] < right[2]
        and right[0] < left[2]
        and left[1] < right[3]
        and right[1] < left[3]
    )


def test_same_decide_rejects_cross_role_footprint_overlap() -> None:
    power = [14.2426, 2, 34.1421]
    overlapping_factory = [16.3640, 2, 39.0919]
    safe_factory = [40, 2, 40]
    snapshot = economy_policy_snapshot("engineer")
    snapshot["economy"].update(energyTrend=-1, energyStoredRatio=0.1)
    snapshot["macro"].update(
        factoryTarget=3,
        factoryDemand=3,
        massSurplusTicks=300,
    )
    snapshot["placements"].update(
        power_generator=[power],
        land_factory=[overlapping_factory, safe_factory],
        air_factory=[],
    )

    builds = intents_of(decide(snapshot), "build_structure")
    by_role = {intent["buildRole"]: intent for intent in builds}

    assert by_role["power_generator"]["position"] == power
    assert by_role["land_factory"]["position"] == safe_factory


@pytest.mark.parametrize("seed", range(4))
def test_site_bound_hydro_reserves_skirt_before_same_decide_factory(seed: int) -> None:
    hydro_position = [20, 2, 20]
    overlapping_factory = [22, 2, 20]
    safe_factory = [50, 2, 20]
    snapshot = economy_policy_snapshot("engineer", "engineer")
    snapshot["sites"]["hydro"] = [{
        "key": "hydro",
        "name": "hydro",
        "position": hydro_position,
        "distance": 10,
        "localSite": False,
        "reachable": True,
        "buildable": True,
        "occupied": False,
        "reserved": False,
    }]
    snapshot["placements"]["land_factory"] = [
        overlapping_factory,
        safe_factory,
    ]
    snapshot["macro"].update(
        factoryTarget=3,
        factoryDemand=3,
        massSurplusTicks=300,
    )
    random.Random(seed).shuffle(snapshot["units"])

    builds = intents_of(decide(snapshot), "build_structure")
    hydro = next(intent for intent in builds if intent["buildRole"] == "hydrocarbon")
    factory = next(intent for intent in builds if intent["buildRole"] == "land_factory")

    assert hydro["position"] == hydro_position
    assert factory["position"] == safe_factory
    assert not footprints_overlap(
        footprint_rect("hydrocarbon", hydro["position"]),
        footprint_rect("land_factory", factory["position"]),
    )


@pytest.mark.parametrize("seed", range(4))
def test_site_bound_lost_mex_reserves_skirt_before_same_decide_power(seed: int) -> None:
    mex_position = [20, 2, 20]
    overlapping_power = [21.5, 2, 20]
    safe_power = [30, 2, 20]
    snapshot = economy_policy_snapshot("engineer", "engineer")
    snapshot["sites"]["mass"].append(
        mass_site("lost", 20, 20, lost=True)
    )
    snapshot["placements"]["power_generator"] = [
        overlapping_power,
        safe_power,
    ]
    snapshot["economy"].update(energyTrend=-1, energyStoredRatio=0.1)
    snapshot["macro"].update(lostMexCount=1, constructionBacklog=1)
    random.Random(seed).shuffle(snapshot["units"])

    builds = intents_of(decide(snapshot), "build_structure")
    mex = next(intent for intent in builds if intent.get("siteKey") == "lost")
    power = next(intent for intent in builds if intent["buildRole"] == "power_generator")

    assert mex["position"] == mex_position
    assert power["position"] == safe_power
    assert not footprints_overlap(
        footprint_rect("mass_extractor", mex["position"]),
        footprint_rect("power_generator", power["position"]),
    )


@pytest.mark.parametrize("seed", range(4))
def test_speculative_expansion_skips_site_overlapping_prior_factory_placement(
    seed: int,
) -> None:
    overlapping_site = mass_site("near", 20, 20, frontier=True)
    safe_site = mass_site("safe", 70, 20, frontier=True)
    snapshot = economy_policy_snapshot("engineer", "engineer")
    snapshot["sites"]["mass"].extend([overlapping_site, safe_site])
    snapshot["placements"]["land_factory"] = [[22, 2, 20]]
    snapshot["macro"].update(
        factoryTarget=3,
        factoryDemand=3,
        massSurplusTicks=300,
        selectedFrontierSite="near",
    )
    random.Random(seed).shuffle(snapshot["units"])

    builds = intents_of(decide(snapshot), "build_structure")
    factory = next(intent for intent in builds if intent["buildRole"] == "land_factory")
    expansion = next(
        intent for intent in builds
        if intent.get("reason") == "frontier_expansion"
    )

    assert factory["position"] == [22, 2, 20]
    assert expansion["siteKey"] == "safe"
    assert not footprints_overlap(
        footprint_rect("land_factory", factory["position"]),
        footprint_rect("mass_extractor", expansion["position"]),
    )


def test_exact_factory_skirt_edge_touch_is_legal_but_epsilon_overlap_is_not() -> None:
    first = [20, 2, 20]
    edge_touch = [28, 2, 20]
    overlap = [27.999, 2, 20]
    snapshot = economy_policy_snapshot("engineer")
    snapshot["macro"].update(factoryTarget=4, factoryDemand=4, massSurplusTicks=300)
    snapshot["pending"] = [{
        "kind": "build_structure",
        "actorToken": "900:1",
        "buildRole": "land_factory",
        "position": first,
        "placementKey": placement_key(first),
    }]

    snapshot["placements"]["land_factory"] = [overlap, edge_touch]
    factory = next(
        intent
        for intent in placement_builds(snapshot)
        if intent.get("buildRole") == "land_factory"
    )

    assert factory["position"] == edge_touch


@pytest.mark.parametrize("occupied_kind", ["pending", "foundation"])
def test_existing_unfinished_footprint_blocks_overlapping_air_factory(
    occupied_kind: str,
) -> None:
    occupied = [14.2426, 2, 34.1421]
    overlap = [16.3640, 2, 39.0919]
    safe = [40, 2, 40]
    snapshot = economy_policy_snapshot("hydrocarbon", "engineer")
    snapshot["placements"]["air_factory"] = [overlap, safe]
    if occupied_kind == "pending":
        snapshot["pending"] = [{
            "kind": "build_structure",
            "actorToken": "900:1",
            "buildRole": "land_factory",
            "position": occupied,
            "placementKey": placement_key(occupied),
        }]
    else:
        snapshot["foundations"] = [{
            "role": "land_factory",
            "targetToken": "900:1",
            "position": occupied,
            "placementKey": placement_key(occupied),
            "reserved": False,
        }]

    air = [
        intent
        for intent in placement_builds(snapshot)
        if intent.get("buildRole") == "air_factory"
    ]

    assert len(air) == 1
    assert air[0]["position"] == safe


@pytest.mark.parametrize("seed", range(4))
def test_candidate_generation_excludes_completed_structure_footprints_and_stays_bounded(
    seed: int,
) -> None:
    occupied = [14.2426, 2, 34.1421]
    overlap = [16.3640, 2, 39.0919]
    safe = [40, 2, 40]
    harness = make_harness()
    factory = harness.unit(
        entityId=70,
        blueprintId="ueb0101",
        position=occupied,
    )
    harness.brain.units = harness.lua.table_from([factory])
    seeds = [overlap, safe]
    random.Random(seed).shuffle(seeds)
    harness.controller.placementSeeds = lua_value(harness.lua, seeds)

    observation = harness.observe()
    candidates = [
        position
        for values in plain(observation.placements).values()
        for position in values
    ]

    assert not any(
        abs(position[0] - overlap[0]) < 0.0001
        and abs(position[2] - overlap[2]) < 0.0001
        for position in candidates
    )
    assert len(harness.calls.canBuild) <= 96


@pytest.mark.parametrize(
    ("blueprint_id", "occupied_role", "overlap"),
    [
        ("ueb1101", "power_generator", [24.9, 2, 20]),
        ("ueb1102", "hydrocarbon", [26.9, 2, 20]),
    ],
)
def test_completed_power_or_hydro_footprint_blocks_structure_candidates(
    blueprint_id: str,
    occupied_role: str,
    overlap: list[float],
) -> None:
    harness = make_harness()
    occupied = harness.unit(
        entityId=70,
        blueprintId=blueprint_id,
        position=[20, 2, 20],
    )
    harness.brain.units = harness.lua.table_from([occupied])
    harness.controller.placementSeeds = lua_value(harness.lua, [overlap, [50, 2, 50]])

    observation = harness.observe()
    candidates = [
        (role, position)
        for role, values in plain(observation.placements).items()
        for position in values
    ]

    assert not any(
        footprints_overlap(
            footprint_rect(occupied_role, [20, 2, 20]),
            footprint_rect(role, position),
        )
        for role, position in candidates
    )


@pytest.mark.parametrize("seed", range(4))
def test_generated_cross_role_candidates_are_pairwise_footprint_disjoint(seed: int) -> None:
    harness = make_harness()
    seeds = [
        [14.2426, 2, 34.1421],
        [16.3640, 2, 39.0919],
        [40, 2, 40],
    ]
    random.Random(seed).shuffle(seeds)
    harness.controller.placementSeeds = lua_value(harness.lua, seeds)

    observation = harness.observe()
    candidates = [
        (role, position)
        for role, positions in plain(observation.placements).items()
        for position in positions
    ]

    for left_index, (left_role, left_position) in enumerate(candidates):
        for right_role, right_position in candidates[left_index + 1:]:
            assert not footprints_overlap(
                footprint_rect(left_role, left_position),
                footprint_rect(right_role, right_position),
            )
    assert len(harness.calls.canBuild) <= 96


@pytest.mark.parametrize("role", ["land_factory", "power_generator", "air_factory"])
def test_actual_selected_placement_uses_nearest_remaining_builder_for_every_role(
    role: str,
) -> None:
    blocked = [20, 2, 20]
    selected = [100, 2, 20]
    extras = ["hydrocarbon"] if role == "air_factory" else []
    snapshot = economy_policy_snapshot("engineer", *extras)
    engineers = sorted(
        (unit for unit in snapshot["units"] if unit["role"] == "engineer"),
        key=lambda unit: unit["token"],
    )
    engineers[0].update(token="10:1", position=[20, 2, 20])
    engineers[1].update(token="99:1", position=[99, 2, 20])
    snapshot["placements"][role] = [blocked, selected]
    snapshot["pending"] = [{
        "kind": "build_structure",
        "actorToken": "900:1",
        "buildRole": "power_generator",
        "position": blocked,
        "placementKey": placement_key(blocked),
    }]
    snapshot["macro"].update(
        factoryTarget=3,
        factoryDemand=3,
        massSurplusTicks=300,
    )
    if role == "power_generator":
        snapshot["economy"].update(energyTrend=-1, energyStoredRatio=0.1)
    else:
        snapshot["economy"].update(energyTrend=1, energyStoredRatio=0.8)
    if role != "land_factory":
        snapshot["macro"].update(factoryTarget=2, factoryDemand=2)

    selected_build = next(
        intent
        for intent in placement_builds(snapshot)
        if intent.get("buildRole") == role
    )

    assert selected_build["position"] == selected
    assert selected_build["actorToken"] == "99:1"


@pytest.mark.parametrize("role", ["land_factory", "power_generator", "air_factory"])
def test_nearest_placement_builder_is_chosen_after_lost_and_orphan_jobs(
    role: str,
) -> None:
    extras = ["hydrocarbon"] if role == "air_factory" else []
    snapshot = economy_policy_snapshot("engineer", "engineer", "engineer", *extras)
    engineers = sorted(
        (unit for unit in snapshot["units"] if unit["role"] == "engineer"),
        key=lambda unit: unit["token"],
    )
    engineers[0].update(token="10:1", position=[99, 2, 20])
    engineers[1].update(token="20:1", position=[40, 2, 20])
    engineers[2].update(token="90:1", position=[0, 2, 20])
    engineers[3].update(token="99:1", position=[21, 2, 20])
    snapshot["sites"]["mass"].append(mass_site("lost", 20, 20, lost=True))
    foundation_role = "power_generator"
    snapshot["foundations"] = [{
        "role": foundation_role,
        "targetToken": "foundation:1",
        "position": [40, 2, 20],
        "placementKey": placement_key([40, 2, 20]),
        "reserved": False,
    }]
    snapshot["placements"][role] = [[100, 2, 20]]
    snapshot["macro"].update(
        lostMexCount=1,
        constructionBacklog=2,
        factoryTarget=3,
        factoryDemand=3,
        massSurplusTicks=300,
    )
    if role == "power_generator":
        snapshot["economy"].update(energyTrend=-1, energyStoredRatio=0.1)
    else:
        snapshot["economy"].update(energyTrend=1, energyStoredRatio=0.8)
    if role != "land_factory":
        snapshot["macro"].update(factoryTarget=2, factoryDemand=2)

    result = decide(snapshot)
    builds = intents_of(result, "build_structure")
    assist = intents_of(result, "assist_structure")
    placement = next(
        (intent for intent in builds if intent.get("buildRole") == role),
        None,
    )
    lost = next(intent for intent in builds if intent.get("siteKey") == "lost")

    assert lost["actorToken"] == "99:1"
    assert assist[0]["actorToken"] == "20:1"
    assert placement is not None
    assert placement["position"] == [100, 2, 20]
    assert placement["actorToken"] == "10:1"


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("existing_connected", [False, True])
def test_active_campaign_limits_connected_mex_work_but_keeps_other_macro_jobs(
    seed: int,
    existing_connected: bool,
) -> None:
    snapshot = macro_snapshot(
        "engineer", "engineer", "engineer", "engineer", "engineer", "engineer"
    )
    snapshot["macro"].update(
        campaignEnabled=True,
        campaignState="active",
        campaignCluster="front",
        campaignMemberKeys=["front-a", "front-b"],
        campaignReady=True,
        lostMexCount=3,
        constructionBacklog=5,
        activeFrontierJobs=0,
    )
    sites = [
        mass_site("front-a", 80, 20, lost=True, frontier=True),
        mass_site("front-b", 84, 20, lost=True, frontier=True),
        mass_site("rear-lost", 20, 20, lost=True),
        mass_site("safe-next", 40, 20, frontier=True),
    ]
    for site in sites:
        site["engineerReachable"] = True
        site["landReachable"] = True
    sites[-1]["clusterKey"] = "next"
    random.Random(seed).shuffle(sites)
    snapshot["sites"]["mass"] = sites
    if existing_connected:
        snapshot["pending"] = [{
            "kind": "build_structure",
            "actorToken": "999:1",
            "buildRole": "mass_extractor",
            "siteKey": "front-a",
            "clusterKey": "front",
            "position": [80, 2, 20],
            "reason": "rebuild_mex",
        }]
    engineers = [unit for unit in snapshot["units"] if unit["role"] == "engineer"]
    for index, engineer in enumerate(engineers):
        engineer.update(position=[10 + index * 4, 2, 20], visionRadius=10)
    snapshot["reclaim"] = [{
        "key": "prop",
        "position": engineers[-1]["position"],
        "mass": 100,
        "reserved": False,
        "observerToken": engineers[-1]["token"],
        "observedTick": 0,
        "visionRadius": 10,
    }]
    random.Random(seed + 100).shuffle(snapshot["units"])

    result = decide(snapshot)
    mex = [
        intent
        for intent in intents_of(result, "build_structure")
        if intent.get("buildRole") == "mass_extractor"
    ]
    connected = [
        intent for intent in mex
        if intent.get("siteKey") in {"front-a", "front-b"}
    ]

    assert len(connected) == (0 if existing_connected else 1)
    assert any(intent.get("siteKey") == "rear-lost" for intent in mex)
    assert any(intent.get("siteKey") == "safe-next" for intent in mex)
    assert len(intents_of(result, "reclaim")) == 1
    assert len({intent["actorToken"] for intent in [*mex, *intents_of(result, "reclaim")]}) == len(
        [*mex, *intents_of(result, "reclaim")]
    )


@pytest.mark.parametrize("seed", range(6))
def test_connected_mex_foundation_consumes_campaign_job_slot_without_blocking_rear_rebuild(
    seed: int,
) -> None:
    snapshot = macro_snapshot("engineer", "engineer", "engineer")
    snapshot["macro"].update(
        campaignEnabled=True,
        campaignState="active",
        campaignCluster="front",
        campaignMemberKeys=["front-a", "front-b"],
        campaignReady=True,
        lostMexCount=2,
        constructionBacklog=3,
    )
    foundation_site = mass_site(
        "front-a",
        80,
        20,
        occupied=True,
        complete=False,
        frontier=True,
    )
    foundation_site.update(
        engineerReachable=True,
        landReachable=True,
        targetToken="foundation:front-a",
        clusterKey="front",
    )
    front_lost = mass_site("front-b", 84, 20, lost=True, frontier=True)
    front_lost.update(engineerReachable=True, landReachable=True, clusterKey="front")
    rear_lost = mass_site("rear-lost", 20, 20, lost=True)
    rear_lost.update(engineerReachable=True, landReachable=True)
    sites = [foundation_site, front_lost, rear_lost]
    random.Random(seed).shuffle(sites)
    snapshot["sites"]["mass"] = sites
    snapshot["foundations"] = [{
        "role": "mass_extractor",
        "targetToken": "foundation:front-a",
        "position": [80, 2, 20],
        "placementKey": placement_key([80, 2, 20]),
        "reserved": False,
    }]
    random.Random(seed + 40).shuffle(snapshot["units"])

    result = decide(snapshot)
    connected = [
        intent
        for intent in [
            *intents_of(result, "build_structure"),
            *intents_of(result, "assist_structure"),
        ]
        if intent.get("siteKey") in {"front-a", "front-b"}
        or intent.get("targetToken") == "foundation:front-a"
    ]
    rear = [
        intent
        for intent in intents_of(result, "build_structure")
        if intent.get("siteKey") == "rear-lost"
    ]

    assert len(connected) == 1
    assert connected[0]["kind"] == "assist_structure"
    assert connected[0]["targetToken"] == "foundation:front-a"
    assert len(rear) == 1
    assert connected[0]["actorToken"] != rear[0]["actorToken"]


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("existing_connected", [False, True])
def test_acu_opening_rebuild_consumes_the_single_campaign_connected_job(
    seed: int,
    existing_connected: bool,
) -> None:
    snapshot = macro_snapshot("engineer", "engineer")
    snapshot["macro"].update(
        campaignEnabled=True,
        campaignState="active",
        campaignCluster="front",
        campaignMemberKeys=["front-a", "front-b"],
        campaignReady=True,
        lostMexCount=2,
        constructionBacklog=2,
    )
    sites = [
        mass_site("front-a", 12, 20, lost=True, frontier=True, local=True),
        mass_site("front-b", 14, 20, lost=True, frontier=True, local=True),
    ]
    for site in sites:
        site["engineerReachable"] = True
        site["landReachable"] = True
        site["clusterKey"] = "front"
    random.Random(seed).shuffle(sites)
    snapshot["sites"]["mass"] = sites
    if existing_connected:
        snapshot["pending"] = [{
            "kind": "build_structure",
            "actorToken": "999:1",
            "buildRole": "mass_extractor",
            "siteKey": "front-a",
            "clusterKey": "front",
            "position": [12, 2, 20],
            "reason": "rebuild_mex",
        }]
    random.Random(seed + 20).shuffle(snapshot["units"])

    result = decide(snapshot)
    connected = [
        intent
        for intent in intents_of(result, "build_structure")
        if intent.get("siteKey") in {"front-a", "front-b"}
    ]

    assert len(connected) == (0 if existing_connected else 1)
    if not existing_connected:
        assert connected[0]["actorToken"] == "1:1"


def stage_attrition_rollback() -> tuple[Any, Any, Any, list[Any], Any, dict[str, Any]]:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    field = set(campaign_state(harness)["fieldTokens"])
    killed = set(sorted(token for token in field if token.startswith("2"))[:5])
    survivors = [
        actor
        for actor in combat
        if f"{int(actor.options.entityId)}:1" not in killed
    ]
    replacements = [
        harness.unit(entityId=9700 + index, blueprintId="uel0201")
        for index in range(5)
    ]
    live_combat = [*survivors, *replacements]
    harness.brain.units = harness.lua.table_from([acu, engineer, *live_combat])
    harness.brain.tick = 100
    current = reconcile(harness)
    rollback = only(campaign_intents(harness, current), "field_campaign")
    assert rollback["mode"] == "rollback"
    return harness, acu, engineer, live_combat, current, rollback


def stage_no_progress_rollback() -> tuple[Any, Any, Any, list[Any], Any, dict[str, Any]]:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    harness.brain.tick = 300
    first = reconcile(harness)
    recovery = only(campaign_intents(harness, first), "field_campaign")
    assert recovery["mode"] == "recover"
    execute_intents(harness, [recovery], first)
    harness.brain.tick = 600
    current = reconcile(harness)
    rollback = only(campaign_intents(harness, current), "field_campaign")
    assert rollback["mode"] == "rollback"
    return harness, acu, engineer, combat, current, rollback


def test_staged_rebuilding_resume_clears_on_readiness_loss_and_retries_after_restore() -> None:
    harness, _, _, _, rollback_observation, rollback = stage_attrition_rollback()
    execute_intents(harness, [rollback], rollback_observation)
    harness.brain.tick = 699
    cooling = reconcile(harness)
    assert campaign_intents(harness, cooling) == []
    harness.brain.tick = 700
    ready = reconcile(harness)
    resume = only(campaign_intents(harness, ready), "field_campaign")
    assert resume["mode"] == "resume"

    harness.brain.supportUnits = harness.lua.table_from([])
    harness.brain.tick = 701
    not_ready = reconcile(harness)
    before = campaign_state(harness)
    clear_before = len(harness.calls.clear)
    aggressive_before = len(harness.calls.aggressive)

    assert not_ready.macro.campaignReady is False
    assert campaign_intents(harness, not_ready) == []
    execute_intents(harness, [resume], not_ready)
    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.aggressive) == aggressive_before
    assert campaign_state(harness) == before

    set_support(harness, mex=8, land=3)
    harness.brain.tick = 702
    restored = reconcile(harness)
    retry = only(campaign_intents(harness, restored), "field_campaign")
    assert retry["mode"] == "resume"


def test_injected_rebuilding_resume_fails_closed_when_live_readiness_is_false() -> None:
    harness, _, _, _, rollback_observation, rollback = stage_attrition_rollback()
    execute_intents(harness, [rollback], rollback_observation)
    harness.brain.tick = 700
    ready = reconcile(harness)
    resume = only(campaign_intents(harness, ready), "field_campaign")
    assert resume["mode"] == "resume"
    harness.brain.supportUnits = harness.lua.table_from([])
    not_ready = harness.observe()
    assert not_ready.macro.campaignReady is False
    before = campaign_state(harness)
    clear_before = len(harness.calls.clear)
    aggressive_before = len(harness.calls.aggressive)

    execute_intents(harness, [resume], not_ready)

    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.aggressive) == aggressive_before
    assert campaign_state(harness) == before


@pytest.mark.parametrize("trigger", ["attrition", "no_progress"])
@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled"])
def test_staged_rollback_prunes_exact_actor_generation_and_retries_live_set(
    trigger: str,
    mutation: str,
) -> None:
    staged = stage_attrition_rollback() if trigger == "attrition" else stage_no_progress_rollback()
    harness, acu, engineer, combat, _, rollback = staged
    stale_token = rollback["actorTokens"][0]
    by_token = {
        f"{int(actor.options.entityId)}:1": actor
        for actor in combat
    }
    stale_actor = by_token[stale_token]
    live = list(combat)
    if mutation == "dead":
        stale_actor.Dead = True
    elif mutation == "captured":
        stale_actor.options.army = 2
    else:
        entity_id = int(stale_actor.options.entityId)
        replacement = harness.unit(
            entityId=entity_id,
            blueprintId="uel0201",
            generationMarker="replacement",
        )
        live = [actor for actor in live if actor is not stale_actor]
        live.append(replacement)
        harness.controller.unitRefs[stale_token] = replacement
    harness.brain.units = harness.lua.table_from([acu, engineer, *live])
    harness.brain.tick += 1

    before = campaign_state(harness)
    clear_before = len(harness.calls.clear)
    move_before = len(harness.calls.move)
    execute_intents(harness, [rollback])
    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.move) == move_before
    assert campaign_state(harness) == before

    current = reconcile(harness)
    retry = only(campaign_intents(harness, current), "field_campaign")
    expected = campaign_state(harness)["fieldTokens"]

    assert retry["mode"] == "rollback"
    assert retry["actorTokens"] == expected
    assert stale_token not in retry["actorTokens"]
    execute_intents(harness, [retry], current)
    assert campaign_state(harness)["state"] == "rebuilding"
    if mutation == "recycled":
        replacement_token = f"{int(stale_actor.options.entityId)}:2"
        state = campaign_state(harness)
        assert replacement_token in [*state["fieldTokens"], *state["homeTokens"]]
        if replacement_token in retry["actorTokens"]:
            commanded = harness.calls.clear[len(harness.calls.clear)].units
            assert any(
                str(commanded[index].options.generationMarker or "") == "replacement"
                for index in range(1, len(commanded) + 1)
            )


@pytest.mark.parametrize("trigger", ["attrition", "no_progress"])
def test_zero_live_field_during_staged_rollback_enters_rebuilding_without_orders(
    trigger: str,
) -> None:
    staged = stage_attrition_rollback() if trigger == "attrition" else stage_no_progress_rollback()
    harness, acu, engineer, combat, _, _ = staged
    field = set(campaign_state(harness)["fieldTokens"])
    harness.brain.units = harness.lua.table_from([acu, engineer])
    harness.brain.tick += 1
    clear_before = len(harness.calls.clear)
    move_before = len(harness.calls.move)

    current = reconcile(harness)

    assert campaign_state(harness)["state"] == "rebuilding"
    state = campaign_state(harness)
    assert state.get("pendingMode") in {None, "none"}
    assert state.get("pendingTokens") is None or state.get("pendingTokens") in ([], {})
    assert campaign_intents(harness, current) == []
    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.move) == move_before
    logical_rollback_tick = int(harness.brain.tick)
    assert campaign_state(harness)["lastRollbackTick"] == logical_rollback_tick

    harness.brain.units = harness.lua.table_from([acu, engineer, *combat])
    harness.brain.tick = logical_rollback_tick + 599
    cooling = reconcile(harness)
    assert campaign_intents(harness, cooling) == []
    if trigger == "no_progress":
        anchor = campaign_state(harness)["anchorPosition"]
        completed = harness.unit(
            entityId=99991,
            blueprintId="ueb1103",
            position=anchor,
        )
        harness.brain.units = harness.lua.table_from(
            [acu, engineer, completed, *combat]
        )
    harness.brain.tick = logical_rollback_tick + 600
    boundary = reconcile(harness)
    assert only(campaign_intents(harness, boundary), "field_campaign")["mode"] == "resume"


def test_direct_zero_field_attrition_rebuild_stamps_same_600_tick_hysteresis() -> None:
    harness, acu, engineer, combat, observation = start_campaign()
    activate_campaign(harness, observation)
    field = set(campaign_state(harness)["fieldTokens"])
    home = [
        actor
        for actor in combat
        if f"{int(actor.options.entityId)}:1" not in field
    ]
    harness.brain.units = harness.lua.table_from([acu, engineer, *home])
    harness.brain.tick = 100

    logical = reconcile(harness)

    state = campaign_state(harness)
    assert state["state"] == "rebuilding"
    assert state["rollbackReason"] == "field_attrition"
    assert state["lastRollbackTick"] == 100
    assert campaign_intents(harness, logical) == []

    harness.brain.units = harness.lua.table_from([acu, engineer, *combat])
    harness.brain.tick = 699
    cooling = reconcile(harness)
    assert campaign_intents(harness, cooling) == []
    harness.brain.tick = 700
    boundary = reconcile(harness)
    assert only(campaign_intents(harness, boundary), "field_campaign")["mode"] == "resume"


def test_zero_field_rebuild_stages_cohort_only_on_atomic_resume_success() -> None:
    harness, acu, engineer, combat, _, _ = stage_attrition_rollback()
    harness.brain.units = harness.lua.table_from([acu, engineer])
    harness.brain.tick = 101
    reconcile(harness)
    before = campaign_state(harness)
    assert before["state"] == "rebuilding"
    assert before["fieldTokens"] in ([], {})

    harness.brain.units = harness.lua.table_from([acu, engineer, *combat])
    harness.brain.tick = 701
    ready = reconcile(harness)
    resume = only(campaign_intents(harness, ready), "field_campaign")
    assert resume["mode"] == "resume"
    assert len(resume["actorTokens"]) == 18
    assert campaign_state(harness)["fieldTokens"] in ([], {})

    harness.calls.failAggressive = True
    execute_intents(harness, [resume], ready)
    failed = campaign_state(harness)
    assert failed["state"] == "rebuilding"
    assert failed["fieldTokens"] in ([], {})

    harness.calls.failAggressive = False
    retry_observation = reconcile(harness)
    retry = only(campaign_intents(harness, retry_observation), "field_campaign")
    execute_intents(harness, [retry], retry_observation)
    committed = campaign_state(harness)
    assert committed["state"] == "active"
    assert len(committed["fieldTokens"]) == 18
    assert len(committed["homeTokens"]) == 6


@pytest.mark.parametrize("trigger", ["attrition", "no_progress"])
@pytest.mark.parametrize("failure", ["clear", "move"])
def test_each_rollback_trigger_is_atomic_on_command_failure_and_retryable(
    trigger: str,
    failure: str,
) -> None:
    staged = stage_attrition_rollback() if trigger == "attrition" else stage_no_progress_rollback()
    harness, _, _, _, observation, rollback = staged
    before = campaign_state(harness)
    setattr(harness.calls, f"fail{failure.title()}", True)

    execute_intents(harness, [rollback], observation)

    assert campaign_state(harness) == before
    setattr(harness.calls, f"fail{failure.title()}", False)
    execute_intents(harness, [rollback], observation)
    assert campaign_state(harness)["state"] == "rebuilding"


def test_committed_rollback_has_600_tick_cooldown_before_repeat_attrition() -> None:
    harness, acu, engineer, combat, observation, rollback = stage_attrition_rollback()
    execute_intents(harness, [rollback], observation)
    assert campaign_state(harness)["lastRollbackTick"] == 100
    spare = harness.unit(
        entityId=77,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1101": True},
    )
    harness.brain.units = harness.lua.table_from([acu, engineer, spare, *combat])
    factory = next(
        harness.brain.supportUnits[index]
        for index in range(1, len(harness.brain.supportUnits) + 1)
        if str(harness.brain.supportUnits[index].options.blueprintId).lower()
        == "ueb0101"
    )
    factory.options.idleState = True
    factory.options.states = lua_value(harness.lua, {})
    factory.options.canBuild = lua_value(harness.lua, {"uel0201": True})
    harness.brain.tick = 101
    early_resume = reconcile(harness)
    assert campaign_intents(harness, early_resume) == []
    macro_work = policy_intents(harness, early_resume)
    assert any(intent.get("kind") == "rally" for intent in macro_work)
    execute_intents(harness, macro_work, early_resume)
    harness.brain.tick = 102
    spending = reconcile(harness)
    assert not any(
        intent.get("kind") == "factory_build"
        for intent in policy_intents(harness, spending)
    )
    assert spending.macro.allocatorDeniedRequest == "factory_queue"
    assert spending.macro.allocatorDeniedReason == "recurring_budget"
    harness.brain.tick = 699
    before_boundary_resume = reconcile(harness)
    assert campaign_intents(harness, before_boundary_resume) == []
    harness.brain.tick = 700
    resume_observation = reconcile(harness)
    resume = only(campaign_intents(harness, resume_observation), "field_campaign")
    assert resume["mode"] == "resume"
    execute_intents(harness, [resume], resume_observation)

    field = set(campaign_state(harness)["fieldTokens"])
    killed = set(sorted(field)[:5])
    survivors = [
        actor
        for actor in combat
        if f"{int(actor.options.entityId)}:1" not in killed
    ]
    replacements = [
        harness.unit(entityId=9900 + index, blueprintId="uel0201")
        for index in range(5)
    ]
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, spare, *survivors, *replacements]
    )

    harness.brain.tick = 701
    early = reconcile(harness)
    assert only(campaign_intents(harness, early), "field_campaign")["mode"] == "rollback"


def test_injected_resume_inside_rollback_cooldown_fails_closed() -> None:
    harness, _, _, _, observation, rollback = stage_attrition_rollback()
    execute_intents(harness, [rollback], observation)
    state = campaign_state(harness)
    harness.controller.fieldCampaign.pendingMode = "resume"
    harness.controller.fieldCampaign.pendingTokens = lua_value(
        harness.lua,
        state["fieldTokens"],
    )
    harness.brain.tick = 101
    current = harness.observe()
    injected = {
        "kind": "field_campaign",
        "mode": "resume",
        "campaignKind": state["kind"],
        "campaignSerial": state["serial"],
        "clusterKey": state["clusterKey"],
        "objectiveKey": state["anchorKey"],
        "position": state["anchorPosition"],
        "actorTokens": state["fieldTokens"],
        "priority": 24,
    }
    before = campaign_state(harness)
    clear_before = len(harness.calls.clear)
    aggressive_before = len(harness.calls.aggressive)

    execute_intents(harness, [injected], current)

    assert len(harness.calls.clear) == clear_before
    assert len(harness.calls.aggressive) == aggressive_before
    assert campaign_state(harness) == before


@pytest.mark.parametrize("terminal", ["transition", "assault"])
def test_new_objective_resets_recovery_epoch_before_second_window_rollback(
    terminal: str,
) -> None:
    if terminal == "transition":
        harness, acu, engineer, combat, observation = forward_graph_campaign()
        completed = [
            complete_mex(harness, 810, [45, 2, 35]),
            complete_mex(harness, 811, [55, 2, 45]),
        ]
    else:
        harness, acu, engineer, combat, observation = start_campaign(
            site_key="last-front",
            cluster_key="last-front",
            position=[100, 2, 100],
        )
        completed = [complete_mex(harness, 812, [100, 2, 100])]
    activate_pressure_front(harness, observation)
    harness.brain.tick = 300
    old_recovery_observation = reconcile(harness)
    old_recovery = only(campaign_intents(harness, old_recovery_observation), "field_campaign")
    assert old_recovery["mode"] == "recover"
    execute_intents(harness, [old_recovery], old_recovery_observation)
    assert campaign_state(harness)["recoveryWindows"] == 1

    hold_cluster(harness, acu, engineer, combat, completed, start_tick=310)
    harness.brain.tick = 460
    forward_observation = reconcile(harness)
    forward = only(campaign_intents(harness, forward_observation), "field_campaign")
    assert forward["mode"] == terminal
    execute_intents(harness, [forward], forward_observation)
    assert campaign_state(harness)["recoveryWindows"] == 0

    harness.brain.tick = 461
    reconcile(harness)
    harness.brain.tick = 761
    first_new_stall = reconcile(harness)
    first = only(campaign_intents(harness, first_new_stall), "field_campaign")
    assert first["mode"] == "recover"
    execute_intents(harness, [first], first_new_stall)
    harness.brain.tick = 1061
    second_new_stall = reconcile(harness)
    assert only(campaign_intents(harness, second_new_stall), "field_campaign")["mode"] == "rollback"


def t2_ready_snapshot() -> dict[str, Any]:
    snapshot = economy_policy_snapshot(
        *("mass_extractor" for _ in range(4)),
        "land_factory",
        "air_factory",
        "hydrocarbon",
    )
    for unit in snapshot["units"]:
        if unit["role"] == "land_factory":
            unit["idle"] = True
            unit["canBuild"]["land_factory_t2"] = True
    snapshot["economy"].update(
        massIncome=1.5,
        massRequested=1.5,
        massUsage=1.5,
        massStoredRatio=0.5,
        massTrend=0,
        energyIncome=30,
        energyUsage=20,
        energyRequested=20,
        energyStoredRatio=0.5,
        energyTrend=0,
    )
    return snapshot


def test_observation_preserves_requested_energy_separately_from_capped_usage() -> None:
    harness = make_harness()
    harness.brain.energyIncome = 30
    harness.brain.energyUsage = 30
    harness.brain.energyRequested = 30.0001

    economy = plain(harness.observe().economy)

    assert economy["energyIncome"] == 30
    assert economy["energyUsage"] == 30
    assert economy["energyRequested"] == pytest.approx(30.0001)


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"massIncome": 1.5, "massRequested": 1.5}, True),
        ({"massIncome": 1.5, "massRequested": 1.5001}, False),
        ({"massIncome": -0.01}, False),
        ({"massIncome": float("nan")}, False),
        ({"massIncome": float("inf")}, False),
        ({"massIncome": "1.5"}, False),
        ({"massRequested": -0.01}, False),
        ({"massRequested": float("nan")}, False),
        ({"massRequested": float("inf")}, False),
        ({"massRequested": None}, False),
        ({"massRequested": "1.0"}, False),
        ({"energyIncome": -0.01}, False),
        ({"energyIncome": float("nan")}, False),
        ({"energyIncome": float("inf")}, False),
        ({"energyIncome": "30"}, False),
        ({"energyRequested": 30}, True),
        ({"energyRequested": 30.0001}, False),
        ({"energyRequested": -0.01}, False),
        ({"energyRequested": float("nan")}, False),
        ({"energyRequested": float("inf")}, False),
        ({"energyRequested": None}, False),
        ({"energyRequested": "20"}, False),
        ({"energyIncome": 30, "energyUsage": 30, "energyRequested": 30.0001}, False),
        ({"energyUsage": float("inf")}, False),
    ],
)
def test_t2_upgrade_requires_finite_nonstalled_engine_rate_contract(
    updates: dict[str, Any],
    expected: bool,
) -> None:
    snapshot = t2_ready_snapshot()
    snapshot["economy"].update(updates)

    upgrades = intents_of(decide(snapshot), "factory_upgrade")

    assert bool(upgrades) is expected


@pytest.mark.parametrize(
    ("producer", "product", "product_id", "domain_swap"),
    [
        ("ueb0101", "tank", "uel0201", "ueb0102"),
        ("ueb0102", "interceptor", "uea0102", "ueb0101"),
        ("ueb0201", "t2_direct_fire", "uel0202", "ueb0101"),
    ],
)
@pytest.mark.parametrize("mutation", ["dead", "captured", "recycled", "domain_swap"])
def test_factory_production_revalidates_live_owned_generation_and_domain(
    producer: str,
    product: str,
    product_id: str,
    domain_swap: str,
    mutation: str,
) -> None:
    harness = make_harness()
    factory = harness.unit(
        entityId=80,
        blueprintId=producer,
        canBuild={product_id: True},
    )
    harness.brain.units = harness.lua.table_from([factory])
    observation = harness.observe()
    if mutation == "dead":
        factory.Dead = True
    elif mutation == "captured":
        factory.options.army = 2
    elif mutation == "recycled":
        replacement = harness.unit(
            entityId=80,
            blueprintId=producer,
            canBuild={product_id: True},
        )
        harness.brain.units = harness.lua.table_from([replacement])
        harness.controller.unitRefs["80:1"] = replacement
    else:
        factory.options.blueprintId = domain_swap
        factory.options.canBuild = lua_value(harness.lua, {product_id: True})

    execute_intents(harness, [{
        "kind": "factory_build",
        "actorToken": "80:1",
        "buildRole": product,
        "priority": 31,
    }], observation)

    assert len(harness.calls.buildFactory) == 0
    assert harness.controller.pending["80:1"] is None


@pytest.mark.parametrize(
    ("producer", "product", "product_id"),
    [
        ("ueb0101", "tank", "uel0201"),
        ("ueb0102", "interceptor", "uea0102"),
        ("ueb0201", "t2_direct_fire", "uel0202"),
    ],
)
@pytest.mark.parametrize("state", ["Building", "Upgrading", "Paused"])
def test_factory_production_rejects_live_busy_or_paused_actor_before_queue_mutation(
    producer: str,
    product: str,
    product_id: str,
    state: str,
) -> None:
    harness = make_harness()
    factory = harness.unit(
        entityId=80,
        blueprintId=producer,
        canBuild={product_id: True},
    )
    harness.brain.units = harness.lua.table_from([factory])
    observation = harness.observe()
    if state == "Paused":
        factory.options.paused = True
    else:
        factory.options.states = lua_value(harness.lua, {state: True})
        factory.options.idleState = False

    execute_intents(harness, [{
        "kind": "factory_build",
        "actorToken": "80:1",
        "buildRole": product,
        "priority": 31,
    }], observation)

    assert len(harness.calls.buildFactory) == 0
    assert harness.controller.pending["80:1"] is None


@pytest.mark.parametrize("incomplete_role", ["mass_extractor", "land_factory", "hydrocarbon"])
def test_air_milestone_counts_only_completed_prerequisites(incomplete_role: str) -> None:
    snapshot = economy_policy_snapshot("engineer", "hydrocarbon")
    if incomplete_role == "mass_extractor":
        removed = next(unit for unit in snapshot["units"] if unit["role"] == "mass_extractor")
        snapshot["units"].remove(removed)
    elif incomplete_role == "land_factory":
        removed = next(unit for unit in snapshot["units"] if unit["role"] == "land_factory")
        snapshot["units"].remove(removed)
    else:
        snapshot["units"] = [
            unit for unit in snapshot["units"]
            if unit["role"] != "hydrocarbon"
        ]
    snapshot["foundations"] = [{
        "role": incomplete_role,
        "targetToken": "foundation:1",
        "position": [30, 2, 30],
        "placementKey": placement_key([30, 2, 30]),
        "reserved": False,
    }]
    snapshot["pending"] = [{
        "kind": "build_structure",
        "actorToken": "900:1",
        "buildRole": incomplete_role,
        "targetToken": "foundation:1",
        "position": [30, 2, 30],
        "placementKey": placement_key([30, 2, 30]),
    }]

    air = [
        intent
        for intent in placement_builds(snapshot)
        if intent.get("buildRole") == "air_factory"
    ]

    assert air == []


def test_exact_completed_air_milestone_emits_one_air_factory() -> None:
    snapshot = economy_policy_snapshot("engineer", "hydrocarbon")
    air = [
        intent
        for intent in placement_builds(snapshot)
        if intent.get("buildRole") == "air_factory"
    ]
    assert len(air) == 1


@pytest.mark.parametrize("duplicate_kind", ["pending", "foundation", "incomplete_unit"])
def test_unfinished_air_factory_suppresses_duplicate_without_counting_as_complete(
    duplicate_kind: str,
) -> None:
    snapshot = economy_policy_snapshot("engineer", "hydrocarbon")
    if duplicate_kind == "pending":
        snapshot["pending"] = [{
            "kind": "build_structure",
            "actorToken": "900:1",
            "buildRole": "air_factory",
            "position": [30, 2, 30],
            "placementKey": placement_key([30, 2, 30]),
        }]
    elif duplicate_kind == "foundation":
        snapshot["foundations"] = [{
            "role": "air_factory",
            "targetToken": "foundation:air",
            "position": [30, 2, 30],
            "placementKey": placement_key([30, 2, 30]),
            "reserved": False,
        }]
    else:
        snapshot["units"].append({
            "token": "foundation:air",
            "role": "air_factory",
            "complete": False,
            "idle": False,
            "position": [30, 2, 30],
            "canBuild": {},
        })
        snapshot["foundations"] = [{
            "role": "air_factory",
            "targetToken": "foundation:air",
            "position": [30, 2, 30],
            "placementKey": placement_key([30, 2, 30]),
            "reserved": False,
        }]
    assert not [
        intent
        for intent in placement_builds(snapshot)
        if intent.get("buildRole") == "air_factory"
    ]


def issue_upgrade_with_focus() -> tuple[Any, Any, Any]:
    harness = make_harness()
    source = harness.unit(
        entityId=70,
        blueprintId="ueb0101",
        position=[12, 2, 20],
        canBuild={"ueb0201": True},
    )
    target = harness.unit(
        entityId=71,
        blueprintId="ueb0201",
        position=[12.2, 2, 20],
        fraction=0.2,
        idleState=False,
        states={"BeingBuilt": True},
    )
    harness.brain.units = harness.lua.table_from([source])
    observation = harness.observe()
    execute_intents(harness, [{
        "kind": "factory_upgrade",
        "actorToken": "70:1",
        "upgradeRole": "land_factory_t2",
        "priority": 23,
    }], observation)
    source.options.focusUnit = target
    harness.brain.units = harness.lua.table_from([source, target])
    harness.brain.tick = 3
    reconcile(harness)
    pending = harness.controller.pending["70:1"]
    assert pending.upgradeTargetToken == "71:1"
    assert pending.accepted is True
    assert source.options.queue[1].commandType == 27
    return harness, source, target


def test_binding_exact_upgrade_focus_records_initial_progress_heartbeat() -> None:
    harness, _, _ = issue_upgrade_with_focus()
    assert harness.controller.pending["70:1"].lastProgressTick == 3


@pytest.mark.parametrize("tick", [901, 2899])
def test_progressing_upgrade_survives_generic_900_timeout_until_derived_deadline(
    tick: int,
) -> None:
    harness, _, target = issue_upgrade_with_focus()
    target.options.fraction = 0.4 if tick == 901 else 0.8
    harness.brain.tick = tick

    reconcile(harness)

    stored = harness.controller.pending["70:1"]
    assert stored is not None
    pending = plain(stored)
    assert pending["kind"] == "factory_upgrade"
    assert pending["upgradeTargetToken"] == "71:1"
    assert pending["deadlineTick"] == 2900
    assert pending["lastProgressTick"] == tick


def test_upgrade_no_progress_stall_starts_cancellation_after_900_tick_grace() -> None:
    harness, source, _ = issue_upgrade_with_focus()
    harness.brain.tick = 903
    reconcile(harness)
    at_boundary = harness.controller.pending["70:1"]
    assert at_boundary is not None
    assert at_boundary.phase == "building"
    assert len(harness.calls.clear) == 0

    harness.brain.tick = 904
    reconcile(harness)
    stalled = harness.controller.pending["70:1"]
    assert stalled is not None
    assert stalled.phase == "cancelling"
    assert stalled.cancelReason == "stalled"
    assert len(harness.calls.clear) == 1

    source.options.states = lua_value(harness.lua, {})
    source.options.queue = lua_value(harness.lua, {})
    source.options.idleState = True
    harness.brain.tick = 905
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None
    assert str(harness.controller.upgradeState).startswith("failed:stalled")


def progress_upgrade_at(harness: Any, target: Any, tick: int, fraction: float) -> None:
    target.options.fraction = fraction
    harness.brain.tick = tick
    reconcile(harness)
    pending = harness.controller.pending["70:1"]
    assert pending is not None
    assert pending.lastProgressTick == tick


def test_upgrade_hard_deadline_cancels_source_and_retains_ownership_until_idle() -> None:
    harness, source, target = issue_upgrade_with_focus()
    progress_upgrade_at(harness, target, 2000, 0.5)
    harness.brain.tick = 2900

    reconcile(harness)

    stored = harness.controller.pending["70:1"]
    assert stored is not None
    pending = plain(stored)
    assert pending["phase"] == "cancelling"
    assert pending["cancelReason"] == "timeout"
    assert len(harness.calls.clear) == 1

    source.options.states = lua_value(harness.lua, {})
    source.options.queue = lua_value(harness.lua, {})
    source.options.idleState = True
    harness.brain.tick = 2901
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None
    assert str(harness.controller.upgradeState).startswith("failed:timeout")


def test_upgrade_deadline_clear_failure_retains_and_retries_exact_operation() -> None:
    harness, source, target = issue_upgrade_with_focus()
    progress_upgrade_at(harness, target, 2000, 0.5)
    harness.calls.failClear = True
    harness.brain.tick = 2900
    reconcile(harness)
    stored = harness.controller.pending["70:1"]
    assert stored is not None
    first = plain(stored)
    assert first["phase"] == "cancelling"
    assert first["cancelAttempts"] == 1

    harness.calls.failClear = False
    harness.brain.tick = 2901
    reconcile(harness)
    stored = harness.controller.pending["70:1"]
    assert stored is not None
    second = plain(stored)
    assert second["phase"] == "cancelling"
    assert second["cancelAttempts"] == 2
    source.options.states = lua_value(harness.lua, {})
    source.options.queue = lua_value(harness.lua, {})
    source.options.idleState = True
    harness.brain.tick = 2902
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None


def test_upgrade_completion_at_hard_deadline_wins_without_cancellation() -> None:
    harness, _, target = issue_upgrade_with_focus()
    target.options.fraction = 1
    target.options.states = lua_value(harness.lua, {})
    target.options.idleState = True
    harness.brain.tick = 2900

    reconcile(harness)

    assert harness.controller.pending["70:1"] is None
    assert harness.controller.upgradeState == "completed"
    assert len(harness.calls.clear) == 0


def test_accepted_upgrade_that_loses_exact_source_identity_releases_without_clearing_unrelated_work() -> None:
    harness, source, _ = issue_upgrade_with_focus()
    source.options.states = lua_value(harness.lua, {"Building": True})
    source.options.focusUnit = None
    source.options.queue = lua_value(harness.lua, [{
        "commandType": 3,
        "blueprintId": "uel0201",
    }])
    source.options.idleState = False
    harness.brain.tick = 4

    reconcile(harness)

    assert harness.controller.pending["70:1"] is None
    assert str(harness.controller.upgradeState).startswith("failed:rejected")
    assert len(harness.calls.clear) == 0


@pytest.mark.parametrize("mutation", ["dead", "captured"])
def test_accepted_upgrade_with_lost_exact_target_cancels_still_active_source(
    mutation: str,
) -> None:
    harness, source, target = issue_upgrade_with_focus()
    if mutation == "dead":
        target.Dead = True
        units = [source]
    elif mutation == "captured":
        target.options.army = 2
        units = [source, target]
    harness.brain.units = harness.lua.table_from(units)
    harness.brain.tick = 4

    reconcile(harness)

    pending = harness.controller.pending["70:1"]
    assert pending is not None
    assert pending.phase == "cancelling"
    assert pending.cancelReason == "target_missing"
    assert len(harness.calls.clear) == 1

    source.options.states = lua_value(harness.lua, {})
    source.options.focusUnit = None
    source.options.queue = lua_value(harness.lua, {})
    source.options.idleState = True
    harness.brain.tick = 5
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None
    assert str(harness.controller.upgradeState).startswith("failed:target_missing")


def test_recycled_upgrade_target_with_new_focus_generation_is_quarantined_without_clear() -> None:
    harness, source, _ = issue_upgrade_with_focus()
    replacement = harness.unit(
        entityId=71,
        blueprintId="ueb0201",
        fraction=0.2,
        idleState=False,
        states={"BeingBuilt": True},
    )
    source.options.focusUnit = replacement
    harness.brain.units = harness.lua.table_from([source, replacement])
    harness.brain.tick = 4

    reconcile(harness)

    pending = harness.controller.pending["70:1"]
    assert pending is not None
    assert pending.phase == "building"
    assert len(harness.calls.clear) == 0

    source.options.states = lua_value(harness.lua, {})
    source.options.queue = lua_value(harness.lua, {})
    source.options.focusUnit = None
    source.options.idleState = True
    harness.brain.tick = 5
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None
    assert len(harness.calls.clear) == 0


def test_changed_upgrade_focus_and_queue_is_quarantined_without_clearing_unknown_work() -> None:
    harness, source, _ = issue_upgrade_with_focus()
    unrelated = harness.unit(
        entityId=72,
        blueprintId="ueb0201",
        fraction=0.1,
        idleState=False,
        states={"BeingBuilt": True},
    )
    source.options.focusUnit = unrelated
    source.options.queue = lua_value(harness.lua, [{
        "commandType": 3,
        "blueprintId": "uel0201",
    }])
    harness.brain.units = harness.lua.table_from([source, unrelated])
    harness.brain.tick = 4

    reconcile(harness)

    pending = harness.controller.pending["70:1"]
    assert pending is not None
    assert pending.phase == "building"
    assert pending.accepted is True
    assert len(harness.calls.clear) == 0

    source.options.states = lua_value(harness.lua, {"Building": True})
    source.options.focusUnit = None
    harness.brain.tick = 5
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None
    assert len(harness.calls.clear) == 0


def test_failed_upgrade_clear_retry_revalidates_exact_focus_and_queue_before_clearing() -> None:
    harness, source, target = issue_upgrade_with_focus()
    target.Dead = True
    harness.brain.units = harness.lua.table_from([source])
    harness.calls.failClear = True
    harness.brain.tick = 4
    reconcile(harness)
    assert harness.controller.pending["70:1"].phase == "cancelling"
    assert len(harness.calls.clear) == 1

    unrelated = harness.unit(
        entityId=72,
        blueprintId="ueb0201",
        fraction=0.1,
        idleState=False,
        states={"BeingBuilt": True},
    )
    source.options.focusUnit = unrelated
    source.options.queue = lua_value(harness.lua, [{
        "commandType": 3,
        "blueprintId": "uel0201",
    }])
    harness.brain.units = harness.lua.table_from([source, unrelated])
    harness.calls.failClear = False
    harness.brain.tick = 5
    reconcile(harness)
    assert harness.controller.pending["70:1"].phase == "cancelling"
    assert len(harness.calls.clear) == 1

    source.options.states = lua_value(harness.lua, {"Building": True})
    source.options.focusUnit = None
    harness.brain.tick = 6
    reconcile(harness)
    assert harness.controller.pending["70:1"].phase == "cancelling"
    assert len(harness.calls.clear) == 1

    source.options.states = lua_value(harness.lua, {})
    source.options.queue = lua_value(harness.lua, {})
    source.options.idleState = True
    harness.brain.tick = 7
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None
    assert len(harness.calls.clear) == 1


def test_upgrade_cancellation_waits_for_idle_and_not_upgrading_confirmation() -> None:
    harness, source, target = issue_upgrade_with_focus()
    progress_upgrade_at(harness, target, 2000, 0.5)
    harness.brain.tick = 2900
    reconcile(harness)
    assert harness.controller.pending["70:1"].phase == "cancelling"
    assert len(harness.calls.clear) == 1

    source.options.idleState = True
    harness.brain.tick = 2901
    reconcile(harness)

    assert harness.controller.pending["70:1"].phase == "cancelling"
    assert len(harness.calls.clear) == 2

    source.options.states = lua_value(harness.lua, {})
    source.options.focusUnit = None
    source.options.queue = lua_value(harness.lua, {})
    harness.brain.tick = 2902
    reconcile(harness)
    assert harness.controller.pending["70:1"] is None
    assert str(harness.controller.upgradeState).startswith("failed:timeout")
