from __future__ import annotations

import copy
import random
from typing import Any

from conftest import execute, lua_sequence


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


def test_acu_emergency_preempts_all_build_and_attack_intents() -> None:
    snapshot = combat_snapshot(["tank"] * 15 + ["artillery"] * 3)
    snapshot["units"][0]["healthRatio"] = 0.54
    result = decide(snapshot)
    assert result[0]["kind"] == "retreat"
    assert result[0]["actorToken"] == "1:1"
    assert not intents_of(result, "build_structure")
    assert not intents_of(result, "attack_wave")


def test_current_intel_defense_preempts_expansion_and_attack() -> None:
    snapshot = combat_snapshot(["tank"] * 15 + ["artillery"] * 3)
    snapshot["enemyContact"] = {"position": [18, 2, 18], "immediate": False}
    result = decide(snapshot)
    defense = intents_of(result, "defend_wave")
    assert defense and len(defense[0]["actorTokens"]) == 18
    assert not intents_of(result, "build_structure")
    assert not intents_of(result, "attack_wave")


def test_attack_threshold_requires_eighteen_combat_and_three_artillery() -> None:
    assert not intents_of(decide(combat_snapshot(["tank"] * 15 + ["artillery"] * 2)), "attack_wave")
    attack = intents_of(decide(combat_snapshot(["tank"] * 15 + ["artillery"] * 3)), "attack_wave")
    assert len(attack) == 1
    assert len(attack[0]["actorTokens"]) == 18


def test_timed_force_attacks_with_ten_but_never_without_path() -> None:
    snapshot = combat_snapshot(["tank"] * 9 + ["artillery"], tick=3600)
    assert intents_of(decide(snapshot), "attack_wave")
    snapshot["targetPath"] = False
    assert not intents_of(decide(snapshot), "attack_wave")


def test_reinforcements_wait_for_eight_or_bounded_delay() -> None:
    snapshot = combat_snapshot(["tank"] * 7, tick=5000)
    snapshot["state"] = {"initialWaveSent": True, "lastWaveTick": 4000, "lastReinforcementTick": 4500}
    assert not intents_of(decide(snapshot), "attack_wave")
    snapshot["units"] += role_counts("artillery")
    assert intents_of(decide(snapshot), "attack_wave")
    snapshot = combat_snapshot(["tank"] * 4, tick=6000)
    snapshot["state"] = {"initialWaveSent": True, "lastWaveTick": 4000, "lastReinforcementTick": 5000}
    assert intents_of(decide(snapshot), "attack_wave")


def test_wave_never_includes_acu_engineer_scout_incomplete_or_unavailable() -> None:
    snapshot = combat_snapshot(["tank"] * 15 + ["artillery"] * 3)
    snapshot["units"] += role_counts("engineer", "scout")
    snapshot["units"].append(dict(role_counts("tank")[0], token="99:1", complete=False, availableForWave=True))
    snapshot["units"].append(dict(role_counts("tank")[0], token="100:1", complete=True, availableForWave=False))
    tokens = intents_of(decide(snapshot), "attack_wave")[0]["actorTokens"]
    assert "1:1" not in tokens and "99:1" not in tokens and "100:1" not in tokens
    assert len(tokens) == 18


def test_nil_optional_fields_are_safe_and_policy_is_deterministic_under_permutation() -> None:
    snapshot = combat_snapshot(["tank"] * 15 + ["artillery"] * 3)
    snapshot.pop("enemyContact")
    baseline = decide(snapshot)
    shuffled = copy.deepcopy(snapshot)
    random.Random(77).shuffle(shuffled["units"])
    random.Random(78).shuffle(shuffled["sites"]["mass"])
    assert decide(shuffled) == baseline


def test_policy_uses_no_engine_global_or_import() -> None:
    lua = execute("lua/AI/Overmind4/Policy.lua")
    assert lua.globals().Policy.Decide(lua_value(lua, base_snapshot())) is not None
