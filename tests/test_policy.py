from __future__ import annotations

import copy
import random
from typing import Any

from conftest import execute, lua_sequence, runtime, source


def lua_value(lua: Any, value: Any) -> Any:
    if isinstance(value, dict):
        table = lua.table()
        for key, item in value.items():
            table[key] = lua_value(lua, item)
        return table
    if isinstance(value, (list, tuple)):
        table = lua.table()
        for index, item in enumerate(value, 1):
            table[index] = lua_value(lua, item)
        return table
    return value


def plain(value: Any) -> Any:
    if hasattr(value, "items"):
        keys = list(value.keys())
        if keys and all(isinstance(key, int) for key in keys):
            return [plain(value[index]) for index in sorted(keys)]
        return {key: plain(item) for key, item in value.items()}
    return value


def base_snapshot(**updates: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "tick": 0,
        "basePosition": [10, 2, 10],
        "stagingPosition": [35, 2, 35],
        "targetPosition": [110, 2, 110],
        "targetPath": True,
        "economy": {
            "energyTrend": 2,
            "energyStoredRatio": 0.8,
            "massTrend": 1,
            "massStoredRatio": 0.5,
        },
        "units": [
            {
                "token": "1:1",
                "role": "acu",
                "complete": True,
                "idle": True,
                "healthRatio": 1,
                "position": [10, 2, 10],
                "canBuild": {
                    "land_factory": True,
                    "power_generator": True,
                    "mass_extractor": True,
                },
            }
        ],
        "pending": [],
        "sites": {"mass": [], "hydro": []},
        "placements": {
            "land_factory": [[18, 2, 18], [22, 2, 18]],
            "power_generator": [[8, 2, 18], [12, 2, 18], [16, 2, 18]],
        },
        "enemyContact": None,
        "state": {
            "initialWaveSent": False,
            "lastWaveTick": -10000,
            "lastReinforcementTick": -10000,
        },
    }
    snapshot.update(updates)
    return snapshot


def decide(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    lua = execute("lua/AI/Overmind4/Policy.lua")
    original = copy.deepcopy(snapshot)
    result = plain(lua.globals().Policy.Decide(lua_value(lua, snapshot)))
    assert snapshot == original, "the pure policy must not mutate its input"
    return result


def role_counts(*roles: str) -> list[dict[str, Any]]:
    return [
        {
            "token": f"{index + 10}:1",
            "role": role,
            "complete": True,
            "idle": role not in {"mass_extractor", "power_generator", "hydrocarbon"},
            "healthRatio": 1,
            "position": [20 + index, 2, 20],
            "canBuild": {},
            "availableForWave": role in {"tank", "artillery", "anti_air", "lab"},
            "assignedToWave": False,
            "nearStaging": True,
        }
        for index, role in enumerate(roles)
    ]


def intents_of(result: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [intent for intent in result if intent["kind"] == kind]


def test_empty_opening_orders_land_factory_first() -> None:
    result = decide(base_snapshot())
    build = intents_of(result, "build_structure")
    assert build[0]["actorToken"] == "1:1"
    assert build[0]["buildRole"] == "land_factory"
    assert build[0]["position"] == [18, 2, 18]


def test_pending_structure_counts_as_opening_progress() -> None:
    snapshot = base_snapshot(
        pending=[{"actorToken": "1:1", "kind": "build_structure", "buildRole": "land_factory"}]
    )
    assert intents_of(decide(snapshot), "build_structure") == []


def test_opening_builds_exactly_two_power_generators_sequentially() -> None:
    for count, expected in ((0, "power_generator"), (1, "power_generator"), (2, "mass_extractor")):
        roles = ["land_factory"] + ["power_generator"] * count
        sites = [
            {
                "key": "m1",
                "name": "Mass 1",
                "position": [12, 2, 12],
                "distance": 3,
                "localSite": True,
                "reachable": True,
                "occupied": False,
                "reserved": False,
            }
        ]
        snapshot = base_snapshot(
            units=base_snapshot()["units"] + role_counts(*roles),
            sites={"mass": sites, "hydro": []},
        )
        assert intents_of(decide(snapshot), "build_structure")[0]["buildRole"] == expected


def test_opening_claims_four_local_mexes_in_distance_name_order() -> None:
    sites = [
        {"key": "m3", "name": "Zulu", "position": [14, 2, 10], "distance": 4, "localSite": True, "reachable": True, "occupied": False, "reserved": False},
        {"key": "m1", "name": "Bravo", "position": [12, 2, 10], "distance": 2, "localSite": True, "reachable": True, "occupied": False, "reserved": False},
        {"key": "m2", "name": "Alpha", "position": [8, 2, 10], "distance": 2, "localSite": True, "reachable": True, "occupied": False, "reserved": False},
        {"key": "m4", "name": "Omega", "position": [16, 2, 10], "distance": 6, "localSite": True, "reachable": True, "occupied": False, "reserved": False},
    ]
    units = base_snapshot()["units"] + role_counts("land_factory", "power_generator", "power_generator")
    result = decide(base_snapshot(units=units, sites={"mass": sites, "hydro": []}))
    build = intents_of(result, "build_structure")[0]
    assert (build["buildRole"], build["siteKey"]) == ("mass_extractor", "m2")

    for site in sites[:3]:
        site["reserved"] = True
    sites[2]["reserved"] = True
    result = decide(base_snapshot(units=units, sites={"mass": sites, "hydro": []}))
    assert intents_of(result, "build_structure")[0]["siteKey"] == "m4"


def test_reserved_local_mexes_count_as_progress_toward_four() -> None:
    sites = [
        {"key": f"m{i}", "name": f"M{i}", "position": [10 + i, 2, 10], "distance": i, "localSite": True, "reachable": True, "occupied": i <= 2, "reserved": i > 2,}
        for i in range(1, 5)
    ]
    units = base_snapshot()["units"] + role_counts("land_factory", "power_generator", "power_generator")
    result = decide(base_snapshot(units=units, sites={"mass": sites, "hydro": []}))
    assert intents_of(result, "build_structure")[0]["buildRole"] == "land_factory"


def test_malformed_occupied_reserved_and_unreachable_sites_are_ignored() -> None:
    sites = [
        {"key": "missing-position", "name": "A", "distance": 1, "localSite": True, "reachable": True, "occupied": False, "reserved": False},
        {"key": "occupied", "name": "B", "position": [11, 2, 11], "distance": 2, "localSite": True, "reachable": True, "occupied": True, "reserved": False},
        {"key": "reserved", "name": "C", "position": [12, 2, 12], "distance": 3, "localSite": True, "reachable": True, "occupied": False, "reserved": True},
        {"key": "unreachable", "name": "D", "position": [13, 2, 13], "distance": 4, "localSite": True, "reachable": False, "occupied": False, "reserved": False},
    ]
    units = base_snapshot()["units"] + role_counts("land_factory", "power_generator", "power_generator")
    assert intents_of(decide(base_snapshot(units=units, sites={"mass": sites, "hydro": []})), "build_structure") == []


def test_blocked_nearest_resource_site_advances_to_farther_buildable_site() -> None:
    snapshot = post_opening_snapshot("engineer")
    snapshot["sites"]["mass"].extend(
        [
            {"key": "near", "name": "Near", "position": [20, 2, 20], "distance": 14, "localSite": False, "reachable": True, "occupied": False, "reserved": False, "buildable": False},
            {"key": "far", "name": "Far", "position": [40, 2, 40], "distance": 42, "localSite": False, "reachable": True, "occupied": False, "reserved": False, "buildable": True},
        ]
    )

    engineer_builds = [
        intent
        for intent in intents_of(decide(snapshot), "build_structure")
        if intent["actorToken"] != "1:1"
    ]

    assert engineer_builds[0]["siteKey"] == "far"


def post_opening_snapshot(*extra_roles: str, **updates: Any) -> dict[str, Any]:
    local_sites = [
        {"key": f"local-{i}", "name": f"Local {i}", "position": [10 + i, 2, 10], "distance": i, "localSite": True, "reachable": True, "occupied": True, "reserved": False}
        for i in range(1, 5)
    ]
    snapshot = base_snapshot(
        units=base_snapshot()["units"]
        + role_counts("land_factory", "land_factory", "power_generator", "power_generator", "mass_extractor", "mass_extractor", "mass_extractor", "mass_extractor", *extra_roles),
        sites={"mass": local_sites, "hydro": []},
    )
    for unit in snapshot["units"]:
        if unit["role"] == "engineer":
            unit["canBuild"] = {
                "hydrocarbon": True,
                "mass_extractor": True,
                "power_generator": True,
                "land_factory": True,
            }
    snapshot.update(updates)
    return snapshot


def test_engineer_claims_reachable_hydro_before_expansion() -> None:
    snapshot = post_opening_snapshot("engineer")
    snapshot["sites"]["hydro"] = [
        {"key": "bad", "name": "A", "position": [15, 2, 15], "distance": 7, "reachable": False, "occupied": False, "reserved": False},
        {"key": "hydro", "name": "B", "position": [20, 2, 20], "distance": 14, "reachable": True, "occupied": False, "reserved": False},
    ]
    build = [i for i in intents_of(decide(snapshot), "build_structure") if i["actorToken"] != "1:1"]
    assert any((i["buildRole"], i.get("siteKey")) == ("hydrocarbon", "hydro") for i in build)


def test_hydro_is_engineer_only() -> None:
    snapshot = post_opening_snapshot()
    snapshot["sites"]["hydro"] = [{"key": "h", "name": "H", "position": [20, 2, 20], "distance": 14, "reachable": True, "occupied": False, "reserved": False}]
    assert not any(i.get("buildRole") == "hydrocarbon" for i in decide(snapshot))


def test_energy_recovery_preempts_engineer_expansion() -> None:
    snapshot = post_opening_snapshot("engineer")
    snapshot["sites"]["mass"].append({"key": "forward", "name": "Forward", "position": [30, 2, 30], "distance": 28, "localSite": False, "reachable": True, "occupied": False, "reserved": False})
    snapshot["economy"] = {"energyTrend": -2, "energyStoredRatio": 0.2, "massTrend": 1, "massStoredRatio": 0.5}
    engineer_intent = next(i for i in intents_of(decide(snapshot), "build_structure") if i["actorToken"] != "1:1")
    assert engineer_intent["buildRole"] == "power_generator"


def test_engineers_admit_third_factory_after_six_mexes() -> None:
    snapshot = post_opening_snapshot("engineer", "mass_extractor", "mass_extractor")
    build = [i for i in intents_of(decide(snapshot), "build_structure") if i["actorToken"] != "1:1"]
    assert any(i["buildRole"] == "land_factory" for i in build)


def test_engineer_cannot_bypass_acu_second_factory_opener() -> None:
    local_sites = [
        {"key": f"local-{i}", "name": f"Local {i}", "position": [10 + i, 2, 10], "distance": i, "localSite": True, "reachable": True, "occupied": True, "reserved": False}
        for i in range(1, 5)
    ]
    units = base_snapshot()["units"] + role_counts(
        "land_factory",
        "power_generator",
        "power_generator",
        "mass_extractor",
        "mass_extractor",
        "mass_extractor",
        "mass_extractor",
        "mass_extractor",
        "mass_extractor",
        "engineer",
    )
    engineer = next(unit for unit in units if unit["role"] == "engineer")
    engineer["canBuild"] = {
        "land_factory": True,
        "mass_extractor": True,
        "power_generator": True,
        "hydrocarbon": True,
    }
    result = decide(base_snapshot(units=units, sites={"mass": local_sites, "hydro": []}))
    factory_builders = [
        intent["actorToken"]
        for intent in intents_of(result, "build_structure")
        if intent["buildRole"] == "land_factory"
    ]

    assert factory_builders == ["1:1"]


def test_acu_power_opener_and_engineer_recovery_never_share_a_placement() -> None:
    units = base_snapshot()["units"] + role_counts("land_factory", "engineer")
    engineer = next(unit for unit in units if unit["role"] == "engineer")
    engineer["canBuild"] = {"power_generator": True}
    snapshot = base_snapshot(units=units)
    snapshot["economy"] = {"energyTrend": -2, "energyStoredRatio": 0.1, "massTrend": 1, "massStoredRatio": 0.5}

    power = [
        intent
        for intent in intents_of(decide(snapshot), "build_structure")
        if intent["buildRole"] == "power_generator"
    ]

    assert len(power) == 1
    assert power[0]["actorToken"] == "1:1"


def test_engineer_power_and_factory_plans_reserve_distinct_shared_placements() -> None:
    snapshot = post_opening_snapshot(
        "engineer",
        "engineer",
        "mass_extractor",
        "mass_extractor",
    )
    shared = [[30, 2, 30], [34, 2, 30], [38, 2, 30], [42, 2, 30]]
    snapshot["placements"] = {
        "land_factory": copy.deepcopy(shared),
        "power_generator": copy.deepcopy(shared),
    }
    snapshot["economy"] = {
        "energyTrend": -2,
        "energyStoredRatio": 0.1,
        "massTrend": 1,
        "massStoredRatio": 0.5,
    }

    builds = [
        intent
        for intent in intents_of(decide(snapshot), "build_structure")
        if intent["actorToken"] != "1:1" and "siteKey" not in intent
    ]
    coordinates = [(intent["position"][0], intent["position"][2]) for intent in builds]

    assert {intent["buildRole"] for intent in builds} == {"power_generator", "land_factory"}
    assert len(coordinates) == len(set(coordinates))


def test_pending_power_placement_reserves_same_coordinate_for_next_policy_step() -> None:
    shared = [[30, 2, 30], [34, 2, 30], [38, 2, 30], [42, 2, 30]]
    first_snapshot = post_opening_snapshot(
        "engineer",
        "mass_extractor",
        "mass_extractor",
    )
    first_snapshot["placements"] = {
        "land_factory": copy.deepcopy(shared),
        "power_generator": copy.deepcopy(shared),
    }
    first_snapshot["economy"] = {
        "energyTrend": -2,
        "energyStoredRatio": 0.1,
        "massTrend": 1,
        "massStoredRatio": 0.5,
    }
    first = next(
        intent
        for intent in intents_of(decide(first_snapshot), "build_structure")
        if intent["actorToken"] != "1:1"
    )

    assert first["buildRole"] == "power_generator"
    assert first.get("placementKey") == "Placement:38000:30000"

    second_snapshot = post_opening_snapshot(
        "engineer",
        "engineer",
        "mass_extractor",
        "mass_extractor",
    )
    second_snapshot["placements"] = {
        "land_factory": copy.deepcopy(shared),
        "power_generator": copy.deepcopy(shared),
    }
    second_snapshot["pending"] = [
        {
            "actorToken": first["actorToken"],
            "kind": first["kind"],
            "buildRole": first["buildRole"],
            "placementKey": first["placementKey"],
        }
    ]
    second = next(
        intent
        for intent in intents_of(decide(second_snapshot), "build_structure")
        if intent["actorToken"] != "1:1"
    )

    assert second["buildRole"] == "land_factory"
    assert second["placementKey"] == "Placement:42000:30000"
    assert second["placementKey"] != first["placementKey"]


def test_factory_counts_completed_incomplete_and_pending_engineers() -> None:
    snapshot = post_opening_snapshot("engineer")
    snapshot["units"] += [dict(role_counts("engineer")[0], token="98:1", complete=False, idle=False)]
    snapshot["pending"] = [{"actorToken": "10:1", "kind": "factory_build", "buildRole": "engineer"}]
    assert not any(i.get("buildRole") == "engineer" for i in intents_of(decide(snapshot), "factory_build"))


def test_multiple_factories_use_virtual_counts_for_engineers_scout_and_mix() -> None:
    snapshot = post_opening_snapshot("engineer", "engineer", "engineer")
    snapshot["units"] += role_counts("land_factory", "scout", "tank", "tank", "tank", "tank")
    factories = [u for u in snapshot["units"] if u["role"] == "land_factory"]
    for factory in factories:
        factory["idle"] = True
        factory["canBuild"] = {role: True for role in ("engineer", "scout", "tank", "artillery", "anti_air")}
    builds = intents_of(decide(snapshot), "factory_build")
    assert len(builds) == len(factories)
    assert [intent["buildRole"] for intent in builds[:3]] == ["artillery", "tank", "tank"]


def test_scout_is_built_once_and_replaced_if_lost() -> None:
    snapshot = post_opening_snapshot("engineer", "engineer", "engineer")
    factory = next(u for u in snapshot["units"] if u["role"] == "land_factory")
    factory["canBuild"] = {"scout": True, "tank": True, "artillery": True, "anti_air": True}
    assert intents_of(decide(snapshot), "factory_build")[0]["buildRole"] == "scout"
    snapshot["units"] += role_counts("scout")
    assert intents_of(decide(snapshot), "factory_build")[0]["buildRole"] != "scout"


def combat_snapshot(combat: list[str], tick: int = 2000, arty: int | None = None) -> dict[str, Any]:
    snapshot = post_opening_snapshot("engineer", "engineer", "engineer", tick=tick)
    snapshot["units"] += role_counts(*combat)
    for unit in snapshot["units"]:
        if unit["role"] == "land_factory":
            unit["idle"] = False
    return snapshot


COMMANDER_KINDS = {"stage_acu", "commander_push", "reinforce_commander"}


def commander_snapshot(
    *,
    near_staging: bool = True,
    idle: bool = True,
    health: float = 1,
    initial_wave_sent: bool = False,
    commander_push_active: bool = False,
    commander_retreating: bool = False,
) -> dict[str, Any]:
    snapshot = combat_snapshot(["tank"] * 20 + ["artillery"] * 4)
    acu = snapshot["units"][0]
    acu.update(
        {
            "complete": True,
            "idle": idle,
            "healthRatio": health,
            "nearStaging": near_staging,
            "position": snapshot["stagingPosition"] if near_staging else snapshot["basePosition"],
        }
    )
    snapshot["state"] = {
        "initialWaveSent": initial_wave_sent,
        "commanderPushActive": commander_push_active,
        "commanderRetreating": commander_retreating,
    }
    return snapshot


def tactical_intents(result: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        intent
        for intent in result
        if intent["kind"] in COMMANDER_KINDS or intent["kind"] == "attack_wave"
    ]


def test_first_push_stages_offstage_acu_without_suppressing_independent_factory() -> None:
    snapshot = commander_snapshot(near_staging=False)
    factory = next(unit for unit in snapshot["units"] if unit["role"] == "land_factory")
    factory["idle"] = True
    factory["canBuild"] = {"tank": True}
    snapshot["sites"]["mass"].append(
        {
            "key": "forward",
            "name": "Forward",
            "position": [60, 2, 60],
            "distance": 70,
            "localSite": False,
            "reachable": True,
            "occupied": False,
            "reserved": False,
        }
    )

    result = decide(snapshot)
    stage = intents_of(result, "stage_acu")

    assert stage == [
        {
            "kind": "stage_acu",
            "actorToken": "1:1",
            "position": snapshot["stagingPosition"],
            "priority": 34,
            "reason": "stage_commander",
        }
    ]
    assert intents_of(result, "factory_build")
    assert any(
        intent.get("buildRole") == "mass_extractor"
        and intent.get("actorToken") != "1:1"
        for intent in intents_of(result, "build_structure")
    )
    assert not any(
        intent.get("actorToken") == "1:1" and intent["kind"] == "build_structure"
        for intent in result
    )
    assert len(tactical_intents(result)) == 1


def test_first_push_waits_while_offstage_acu_is_moving() -> None:
    snapshot = commander_snapshot(near_staging=False, idle=False)

    result = decide(snapshot)

    assert tactical_intents(result) == []


def test_first_push_uses_exact_near_staging_acu_and_all_available_combat() -> None:
    snapshot = commander_snapshot()

    result = decide(snapshot)
    push = intents_of(result, "commander_push")

    assert len(push) == 1
    assert push[0]["acuToken"] == "1:1"
    assert len(push[0]["actorTokens"]) == 24
    assert push[0]["position"] == snapshot["targetPosition"]
    assert push[0]["reason"] == "acu_led_concentration"
    assert not intents_of(result, "attack_wave")


def test_first_push_fails_closed_for_missing_incomplete_pending_or_low_acu() -> None:
    snapshots: list[dict[str, Any]] = []

    missing = commander_snapshot()
    missing["units"] = [unit for unit in missing["units"] if unit["role"] != "acu"]
    snapshots.append(missing)

    incomplete = commander_snapshot()
    incomplete["units"][0]["complete"] = False
    snapshots.append(incomplete)

    pending = commander_snapshot()
    pending["pending"] = [
        {"actorToken": "1:1", "kind": "build_structure", "buildRole": "power_generator"}
    ]
    snapshots.append(pending)

    snapshots.append(commander_snapshot(health=0.74))

    for snapshot in snapshots:
        result = decide(snapshot)
        assert tactical_intents(result) == []
        assert not intents_of(result, "retreat")


def test_first_push_fails_closed_for_missing_or_malformed_state() -> None:
    for state in (None, "malformed", {}, {"initialWaveSent": "no"}):
        snapshot = commander_snapshot()
        snapshot["state"] = state

        assert tactical_intents(decide(snapshot)) == []


def test_post_initial_reinforces_active_commander_or_falls_back_to_combat_wave() -> None:
    active = commander_snapshot(initial_wave_sent=True, commander_push_active=True, idle=False)
    reinforcement = intents_of(decide(active), "reinforce_commander")
    assert len(reinforcement) == 1
    assert reinforcement[0]["acuToken"] == "1:1"
    assert len(reinforcement[0]["actorTokens"]) == 24
    assert not intents_of(decide(active), "attack_wave")

    inactive = commander_snapshot(initial_wave_sent=True, commander_push_active=False)
    attack = intents_of(decide(inactive), "attack_wave")
    assert len(attack) == 1
    assert len(attack[0]["actorTokens"]) == 24

    missing = commander_snapshot(initial_wave_sent=True, commander_push_active=True)
    missing["units"] = [unit for unit in missing["units"] if unit["role"] != "acu"]
    assert intents_of(decide(missing), "attack_wave")
    assert not intents_of(decide(missing), "reinforce_commander")


def test_push_uses_point_seventy_five_retreat_threshold_without_changing_normal_threshold() -> None:
    active = commander_snapshot(
        health=0.749,
        initial_wave_sent=True,
        commander_push_active=True,
    )
    assert intents_of(decide(active), "retreat")
    assert tactical_intents(decide(active)) == []

    ordinary = commander_snapshot(
        health=0.749,
        initial_wave_sent=True,
        commander_push_active=False,
    )
    assert not intents_of(decide(ordinary), "retreat")
    assert intents_of(decide(ordinary), "attack_wave")

    boundary = commander_snapshot(
        health=0.75,
        initial_wave_sent=True,
        commander_push_active=True,
    )
    assert not intents_of(decide(boundary), "retreat")
    assert intents_of(decide(boundary), "reinforce_commander")


def test_active_push_with_malformed_health_never_defaults_to_healthy() -> None:
    for health in (None, "unknown"):
        snapshot = commander_snapshot(
            initial_wave_sent=True,
            commander_push_active=True,
        )
        snapshot["units"][0]["healthRatio"] = health

        result = decide(snapshot)

        assert not intents_of(result, "reinforce_commander")
        assert not intents_of(result, "attack_wave")


def test_commander_retreat_recovery_suppresses_tactics_and_regroup_on_next_tick() -> None:
    snapshot = commander_snapshot(
        health=0.74,
        initial_wave_sent=True,
        commander_retreating=True,
    )
    for unit in snapshot["units"]:
        if unit["role"] in {"tank", "artillery"}:
            unit["availableForWave"] = False
            unit["assignedToWave"] = False
            unit["nearStaging"] = False
    snapshot["economy"] = {
        "energyTrend": -2,
        "energyStoredRatio": 0.1,
        "massTrend": 1,
        "massStoredRatio": 0.5,
    }

    result = decide(snapshot)

    assert intents_of(result, "retreat")
    assert not intents_of(result, "regroup_wave")
    assert tactical_intents(result) == []
    assert any(
        intent.get("buildRole") == "power_generator"
        and intent.get("actorToken") != "1:1"
        for intent in intents_of(result, "build_structure")
    )


def test_healed_commander_recovery_keeps_retreating_home_and_allows_factories() -> None:
    snapshot = commander_snapshot(
        health=0.9,
        initial_wave_sent=True,
        commander_retreating=True,
    )
    factory = next(unit for unit in snapshot["units"] if unit["role"] == "land_factory")
    factory["idle"] = True
    factory["canBuild"] = {"tank": True}

    result = decide(snapshot)

    assert intents_of(result, "retreat")
    assert tactical_intents(result) == []
    assert not intents_of(result, "regroup_wave")
    assert intents_of(result, "factory_build")


def test_acu_emergency_preempts_all_build_and_attack_intents() -> None:
    snapshot = commander_snapshot()
    snapshot["units"][0]["healthRatio"] = 0.54
    result = decide(snapshot)
    assert result[0]["kind"] == "retreat"
    assert result[0]["actorToken"] == "1:1"
    assert not intents_of(result, "build_structure")
    assert not intents_of(result, "attack_wave")
    assert not any(intent["kind"] in COMMANDER_KINDS for intent in result)


def test_low_health_acu_retreat_allows_independent_factory_production() -> None:
    snapshot = commander_snapshot()
    snapshot["units"][0]["healthRatio"] = 0.54
    for factory in (unit for unit in snapshot["units"] if unit["role"] == "land_factory"):
        factory["idle"] = True
        factory["canBuild"] = {"tank": True, "artillery": True, "anti_air": True}

    result = decide(snapshot)

    assert intents_of(result, "retreat")
    assert intents_of(result, "factory_build")
    assert not intents_of(result, "attack_wave")
    assert not any(
        intent.get("buildRole") in {"mass_extractor", "hydrocarbon"}
        for intent in intents_of(result, "build_structure")
    )


def test_current_intel_defense_preempts_expansion_and_attack() -> None:
    snapshot = commander_snapshot()
    snapshot["enemyContact"] = {"position": [18, 2, 18], "immediate": False}
    result = decide(snapshot)
    defense = intents_of(result, "defend_wave")
    assert defense and len(defense[0]["actorTokens"]) == 24
    assert not intents_of(result, "build_structure")
    assert not intents_of(result, "attack_wave")
    assert not any(intent["kind"] in COMMANDER_KINDS for intent in result)

    active = commander_snapshot(
        initial_wave_sent=True,
        commander_push_active=True,
        idle=False,
    )
    active["enemyContact"] = {"position": [18, 2, 18], "immediate": False}
    active_result = decide(active)
    assert intents_of(active_result, "defend_wave")
    assert tactical_intents(active_result) == []


def test_contact_without_defenders_keeps_energy_recovery_and_factory_production_running() -> None:
    snapshot = post_opening_snapshot("engineer", "engineer", "engineer", "scout")
    snapshot["enemyContact"] = {"position": [18, 2, 18], "immediate": False}
    snapshot["economy"] = {"energyTrend": -2, "energyStoredRatio": 0.1, "massTrend": 1, "massStoredRatio": 0.5}
    for factory in (unit for unit in snapshot["units"] if unit["role"] == "land_factory"):
        factory["canBuild"] = {"tank": True, "artillery": True, "anti_air": True}

    result = decide(snapshot)

    assert any(intent.get("buildRole") == "power_generator" for intent in intents_of(result, "build_structure"))
    assert intents_of(result, "factory_build")
    assert not intents_of(result, "attack_wave")


def test_defense_uses_completed_unassigned_combat_even_when_off_staging() -> None:
    snapshot = combat_snapshot(["tank", "tank", "artillery"])
    for unit in snapshot["units"]:
        if unit["role"] in {"tank", "artillery"}:
            unit["availableForWave"] = False
            unit["nearStaging"] = False
            unit["assignedToWave"] = False
    snapshot["enemyContact"] = {"position": [18, 2, 18], "immediate": False}

    defense = intents_of(decide(snapshot), "defend_wave")

    assert len(defense) == 1
    assert len(defense[0]["actorTokens"]) == 3


def test_off_staging_defenders_regroup_after_contact_clears() -> None:
    snapshot = combat_snapshot(["tank", "tank", "artillery"])
    for unit in snapshot["units"]:
        if unit["role"] in {"tank", "artillery"}:
            unit["availableForWave"] = False
            unit["nearStaging"] = False
            unit["assignedToWave"] = False
    snapshot["enemyContact"] = None

    regroup = intents_of(decide(snapshot), "regroup_wave")

    assert len(regroup) == 1
    assert len(regroup[0]["actorTokens"]) == 3
    assert regroup[0]["position"] == snapshot["stagingPosition"]


def test_twenty_four_with_only_three_artillery_never_launches_at_any_time_or_state() -> None:
    for initial_wave_sent in (False, True):
        snapshot = commander_snapshot(initial_wave_sent=initial_wave_sent)
        artillery = next(unit for unit in snapshot["units"] if unit["role"] == "artillery")
        artillery["role"] = "tank"
        snapshot["tick"] = 999999

        assert tactical_intents(decide(snapshot)) == []


def test_twenty_three_with_four_artillery_never_launches_at_any_time_or_state() -> None:
    for initial_wave_sent in (False, True):
        snapshot = commander_snapshot(initial_wave_sent=initial_wave_sent)
        tank = next(unit for unit in snapshot["units"] if unit["role"] == "tank")
        snapshot["units"].remove(tank)
        snapshot["tick"] = 999999

        assert tactical_intents(decide(snapshot)) == []


def test_exactly_twenty_four_with_four_artillery_launches_every_available_unit() -> None:
    initial = commander_snapshot()
    push = intents_of(decide(initial), "commander_push")
    assert len(push) == 1
    assert len(push[0]["actorTokens"]) == 24
    assert push[0]["reason"] == "acu_led_concentration"

    later = commander_snapshot(initial_wave_sent=True)
    attack = intents_of(decide(later), "attack_wave")
    assert len(attack) == 1
    assert len(attack[0]["actorTokens"]) == 24
    assert attack[0]["reason"] == "concentration_gate"


def test_oversized_concentrated_wave_launches_every_available_unit() -> None:
    snapshot = combat_snapshot(["tank"] * 27 + ["artillery"] * 5)
    snapshot["state"] = {
        "initialWaveSent": True,
        "commanderPushActive": False,
        "commanderRetreating": False,
    }

    attack = intents_of(decide(snapshot), "attack_wave")

    assert len(attack) == 1
    assert len(attack[0]["actorTokens"]) == 32


def test_concentration_gate_has_no_time_escape_and_still_requires_target_path() -> None:
    below_gate = commander_snapshot()
    artillery = next(unit for unit in below_gate["units"] if unit["role"] == "artillery")
    artillery["role"] = "tank"
    below_gate["tick"] = 999999999
    assert tactical_intents(decide(below_gate)) == []

    ready = commander_snapshot()
    ready["tick"] = 999999999
    ready["targetPath"] = False
    assert tactical_intents(decide(ready)) == []


def test_concentration_gate_fails_closed_for_missing_or_malformed_state() -> None:
    for state in (None, "malformed", {"initialWaveSent": "unknown"}):
        snapshot = commander_snapshot()
        snapshot["state"] = state

        assert tactical_intents(decide(snapshot)) == []


def test_wave_never_includes_acu_engineer_scout_incomplete_or_unavailable() -> None:
    snapshot = commander_snapshot()
    snapshot["units"] += role_counts("engineer", "scout")
    snapshot["units"].append(dict(role_counts("tank")[0], token="99:1", complete=False, availableForWave=True))
    snapshot["units"].append(dict(role_counts("tank")[0], token="100:1", complete=True, availableForWave=False))
    tokens = intents_of(decide(snapshot), "commander_push")[0]["actorTokens"]
    assert "1:1" not in tokens and "99:1" not in tokens and "100:1" not in tokens
    assert len(tokens) == 24


def test_nil_optional_fields_are_safe_and_policy_is_deterministic_under_permutation() -> None:
    snapshot = combat_snapshot(["tank"] * 15 + ["artillery"] * 3)
    snapshot.pop("enemyContact")
    baseline = decide(snapshot)
    shuffled = copy.deepcopy(snapshot)
    random.Random(77).shuffle(shuffled["units"])
    random.Random(78).shuffle(shuffled["sites"]["mass"])
    assert decide(shuffled) == baseline


def test_policy_handles_missing_distance_when_game_math_has_no_huge() -> None:
    lua = runtime()
    lua.execute("math.huge = nil")
    lua.execute(source("lua/AI/Overmind4/Policy.lua"))
    snapshot = base_snapshot()
    snapshot["sites"]["mass"] = [
        {"key": "malformed", "name": "Malformed", "position": [12, 2, 12], "localSite": True, "reachable": True, "occupied": False, "reserved": False}
    ]

    result = lua.globals().Policy.Decide(lua_value(lua, snapshot))

    assert result is not None


def test_policy_uses_no_engine_global_or_import() -> None:
    lua = execute("lua/AI/Overmind4/Policy.lua")
    assert lua.globals().Policy.Decide(lua_value(lua, base_snapshot())) is not None
