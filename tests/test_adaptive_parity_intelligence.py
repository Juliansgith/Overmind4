from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from adaptive_parity_helpers import director_path, director_present, invoke
from conftest import execute


MODULE = "Intelligence.lua"
GLOBAL = "Intelligence"


def test_intelligence_is_a_dedicated_runtime_module() -> None:
    assert director_path(MODULE).is_file()


def test_catalog_pins_every_new_observation_and_executor_role() -> None:
    lua = execute("lua/AI/Overmind4/Catalog.lua")
    catalog = lua.globals().Catalog
    expected = {
        "radar": "ueb3101",
        "point_defense": "ueb2101",
        "static_anti_air": "ueb2104",
        "bomber": "uea0103",
        "transport": "uea0107",
        "mass_extractor_t2": "ueb1202",
        "mass_extractor_t3": "ueb1302",
    }

    assert {role: catalog.IdFor(role) for role in expected} == expected
    assert {blueprint: catalog.RoleFor(blueprint) for blueprint in expected.values()} == {
        blueprint: role for role, blueprint in expected.items()
    }


@pytest.mark.skipif(not director_present(MODULE), reason="Intelligence RED module missing")
class TestFairIntel:
    def test_radar_plan_covers_every_active_region_once_and_repairs_losses(self) -> None:
        regions = [
            {"key": "home", "state": "secured", "position": [0, 0, 0]},
            {"key": "front", "state": "establishing", "position": [200, 0, 0]},
            {"key": "new", "state": "establishing", "position": [300, 0, 0]},
            {"key": "planned", "state": "planned", "position": [350, 0, 0]},
            {"key": "lost", "state": "lost", "position": [400, 0, 0]},
        ]
        coverage = [
            {"regionKey": "home", "role": "radar", "live": True},
            {"regionKey": "front", "role": "radar", "live": False},
        ]

        plan = invoke(MODULE, GLOBAL, "PlanRadar", regions, coverage)

        assert [(intent["regionKey"], intent["reason"]) for intent in plan] == [
            ("front", "restore_region_radar"),
            ("new", "establish_region_radar"),
        ]

    def test_scout_route_cycles_multiple_public_objectives_in_stable_order(self) -> None:
        objectives = [
            {"key": "front-b", "position": [200, 0, 50], "public": True},
            {"key": "region-a", "position": [100, 0, 0], "public": True},
            {"key": "enemy-spawn", "position": [400, 0, 400], "public": True},
            {"key": "hidden-contact", "position": [20, 0, 20], "public": False},
        ]

        plan = invoke(
            MODULE,
            GLOBAL,
            "PlanScoutRoute",
            {"tick": 3000, "objectives": objectives, "lastCoveredTicks": {}},
        )

        assert plan["objectiveKeys"] == ["enemy-spawn", "front-b", "region-a"]
        assert len(plan["waypoints"]) == 3
        assert len({tuple(point) for point in plan["waypoints"]}) == 3

    def test_scout_coverage_age_drives_next_objective_instead_of_random_patrol(self) -> None:
        snapshot = {
            "tick": 3000,
            "objectives": [
                {"key": "a", "position": [10, 0, 10], "public": True},
                {"key": "b", "position": [20, 0, 20], "public": True},
                {"key": "c", "position": [30, 0, 30], "public": True},
            ],
            "lastCoveredTicks": {"a": 2900, "b": 1000, "c": 2500},
        }

        plan = invoke(MODULE, GLOBAL, "PlanScoutRoute", snapshot)

        assert plan["coverageAgeTicks"] == {"a": 100, "b": 2000, "c": 500}
        assert plan["nextObjectiveKey"] == "b"

    def test_enemy_memory_accepts_only_current_own_vision_or_radar_safe_observations(self) -> None:
        observations = [
            {"token": "vision", "role": "engineer", "position": [10, 0, 10], "source": "vision", "current": True},
            {"token": "radar", "role": "unknown_mobile", "position": [20, 0, 20], "source": "radar", "current": True},
            {"token": "stale", "role": "mex", "position": [30, 0, 30], "source": "vision", "current": False},
            {"token": "global", "role": "commander", "position": [40, 0, 40], "source": "opponent_brain", "current": True},
            {"token": "hidden", "role": "factory", "position": [50, 0, 50], "source": "global_unit_list", "current": True},
        ]

        state = invoke(
            MODULE,
            GLOBAL,
            "UpdateMemory",
            {"contacts": {}},
            {"tick": 1000, "observations": observations},
        )

        assert set(state["contacts"]) == {"radar", "vision"}
        assert state["contacts"]["vision"]["role"] == "engineer"
        assert state["contacts"]["radar"]["role"] == "unknown_mobile"

    @pytest.mark.parametrize(
        ("tick", "retained"),
        [(1599, True), (1600, False)],
    )
    def test_enemy_memory_expires_at_exact_600_tick_boundary(
        self, tick: int, retained: bool
    ) -> None:
        prior = {
            "contacts": {
                "enemy": {
                    "token": "enemy",
                    "role": "engineer",
                    "position": [10, 0, 10],
                    "lastSeenTick": 1000,
                    "source": "vision",
                }
            }
        }

        state = invoke(
            MODULE,
            GLOBAL,
            "UpdateMemory",
            prior,
            {"tick": tick, "observations": []},
        )

        assert ("enemy" in state["contacts"]) is retained


def air_snapshot(**updates: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "fundedSlots": 1,
        "completed": {
            "air_scout": 0,
            "interceptor": 0,
            "bomber": 0,
            "transport": 0,
        },
        "pending": [],
        "needs": {
            "scoutCoverageStale": True,
            "airThreat": True,
            "visibleRaidTarget": True,
            "remoteSafeExpansion": True,
        },
        "factories": [{"token": "air-1", "idle": True, "tier": 1}],
    }
    snapshot.update(updates)
    return snapshot


@pytest.mark.skipif(not director_present(MODULE), reason="Intelligence RED module missing")
class TestAirAndMobility:
    @pytest.mark.parametrize(
        ("scouts", "interceptors", "expected"),
        [(0, 0, "air_scout"), (1, 0, "interceptor"), (1, 4, "bomber")],
    )
    def test_air_mix_builds_scout_then_four_interceptors_before_funded_specialists(
        self, scouts: int, interceptors: int, expected: str
    ) -> None:
        snapshot = air_snapshot()
        snapshot["completed"].update(
            {"air_scout": scouts, "interceptor": interceptors}
        )

        plan = invoke(MODULE, GLOBAL, "PlanAir", snapshot)

        assert plan["orders"][0]["buildRole"] == expected
        if expected == "bomber":
            snapshot["completed"]["bomber"] = 1
            snapshot["needs"]["visibleRaidTarget"] = False
            transport_plan = invoke(MODULE, GLOBAL, "PlanAir", snapshot)
            assert transport_plan["orders"][0]["buildRole"] == "transport"

    def test_bomber_targets_only_current_visual_engineer_then_mex_fallback(self) -> None:
        observations = [
            {"token": "hidden-eng", "role": "engineer", "position": [1, 0, 1], "currentlyVisual": False},
            {"token": "mex", "role": "mass_extractor", "position": [50, 0, 50], "currentlyVisual": True},
            {"token": "eng", "role": "engineer", "position": [100, 0, 100], "currentlyVisual": True},
        ]

        engineer = invoke(MODULE, GLOBAL, "SelectBomberTarget", observations)
        fallback = invoke(MODULE, GLOBAL, "SelectBomberTarget", observations[:2])

        assert (engineer["targetToken"], engineer["targetRole"]) == ("eng", "engineer")
        assert (fallback["targetToken"], fallback["targetRole"]) == ("mex", "mass_extractor")
        assert invoke(MODULE, GLOBAL, "SelectBomberTarget", observations[:1]) is None

    def test_bomber_execution_revalidates_live_ownership_generation_and_current_vision(self) -> None:
        intent = {
            "bomberToken": "bomber:2",
            "targetToken": "engineer:7",
            "targetRole": "engineer",
        }
        valid = {
            "ownUnits": [{"token": "bomber:2", "role": "bomber", "live": True, "owned": True, "idle": True}],
            "observations": [{"token": "engineer:7", "role": "engineer", "live": True, "currentlyVisual": True}],
        }

        assert invoke(MODULE, GLOBAL, "ValidateBomberIntent", intent, valid)["valid"] is True
        for mutation in (
            {"ownUnits": [], "observations": valid["observations"]},
            {"ownUnits": [{**valid["ownUnits"][0], "owned": False}], "observations": valid["observations"]},
            {"ownUnits": valid["ownUnits"], "observations": [{**valid["observations"][0], "currentlyVisual": False}]},
            {"ownUnits": valid["ownUnits"], "observations": [{**valid["observations"][0], "token": "engineer:8"}]},
        ):
            assert invoke(
                MODULE, GLOBAL, "ValidateBomberIntent", intent, mutation
            )["valid"] is False

    @pytest.mark.parametrize(
        ("distance", "expected"),
        [(900, "walk"), (2600, "airlift")],
    )
    def test_transport_chooses_walk_nearby_and_airlift_for_remote_safe_profitable_site(
        self, distance: int, expected: str
    ) -> None:
        snapshot = {
            "engineer": {"token": "eng:1", "position": [0, 0, 0], "live": True, "owned": True},
            "transport": {"token": "transport:1", "position": [0, 0, 10], "live": True, "owned": True, "idle": True},
            "site": {
                "key": "remote",
                "position": [distance, 0, 0],
                "landEtaTicks": 1199 if expected == "walk" else 1201,
                "safe": True,
                "profitMass": 400,
                "reachable": True,
            },
        }

        plan = invoke(MODULE, GLOBAL, "PlanTransport", snapshot)

        assert plan["mode"] == expected
        assert plan["siteKey"] == "remote"

    def test_transport_rejects_unsafe_unprofitable_or_unreachable_drop(self) -> None:
        base = {
            "engineer": {"token": "eng:1", "position": [0, 0, 0], "live": True, "owned": True},
            "transport": {"token": "transport:1", "position": [0, 0, 10], "live": True, "owned": True, "idle": True},
            "site": {
                "key": "remote",
                "position": [2600, 0, 0],
                "landEtaTicks": 1201,
                "safe": True,
                "profitMass": 400,
                "reachable": True,
            },
        }
        mutations = (
            {"safe": False},
            {"profitMass": 0},
            {"reachable": False},
        )

        for mutation in mutations:
            snapshot = copy.deepcopy(base)
            snapshot["site"].update(mutation)
            plan = invoke(MODULE, GLOBAL, "PlanTransport", snapshot)
            assert plan["mode"] == "hold", mutation
            assert plan["retryable"] is True, mutation

    def test_transport_lifecycle_requires_exact_cargo_attachment_and_detached_arrival(self) -> None:
        mission: dict[str, Any] = {
            "state": "planned",
            "transportToken": "transport:1",
            "cargoTokens": ["eng:1"],
            "dropPosition": [2600, 0, 0],
            "dropTolerance": 20,
            "retryCount": 0,
        }
        events = (
            ({"kind": "load_ordered", "tick": 100}, "loading"),
            ({"kind": "observed", "tick": 110, "transportToken": "transport:1", "attachedCargoTokens": ["eng:1"]}, "loaded"),
            ({"kind": "unload_ordered", "tick": 120}, "unloading"),
            ({"kind": "observed", "tick": 125, "transportToken": "transport:1", "attachedCargoTokens": ["eng:1"]}, "unloading"),
            ({"kind": "observed", "tick": 130, "transportToken": "transport:1", "attachedCargoTokens": [], "cargoPositions": {"eng:1": [2620, 0, 0]}}, "completed"),
        )

        for event, expected in events:
            mission = invoke(MODULE, GLOBAL, "AdvanceTransport", mission, event)
            assert mission["state"] == expected

        assert mission["released"] is True

    def test_transport_death_capture_generation_mismatch_timeout_and_wrong_cargo_release_retryably(self) -> None:
        loading = {
            "state": "loading",
            "transportToken": "transport:1",
            "cargoTokens": ["eng:1"],
            "dropPosition": [2600, 0, 0],
            "dropTolerance": 20,
            "deadlineTick": 500,
            "retryCount": 0,
        }
        failures = (
            {"kind": "transport_dead", "tick": 200},
            {"kind": "transport_captured", "tick": 200},
            {"kind": "cargo_dead", "tick": 200, "cargoToken": "eng:1"},
            {"kind": "cargo_captured", "tick": 200, "cargoToken": "eng:1"},
            {"kind": "observed", "tick": 200, "transportToken": "transport:2", "attachedCargoTokens": ["eng:1"]},
            {"kind": "observed", "tick": 501, "transportToken": "transport:1", "attachedCargoTokens": []},
            {"kind": "observed", "tick": 200, "transportToken": "transport:1", "attachedCargoTokens": ["eng:2"]},
            {"kind": "observed", "tick": 200, "transportToken": "transport:1", "attachedCargoTokens": ["eng:1", "eng:2"]},
        )

        for event in failures:
            result = invoke(
                MODULE, GLOBAL, "AdvanceTransport", copy.deepcopy(loading), event
            )
            assert result["state"] == "released", event
            assert result["retryable"] is True, event
            assert result["released"] is True, event
            assert result["retryCount"] == 1, event

        unloading = {
            **loading,
            "state": "unloading",
            "deadlineTick": 700,
        }
        outside_drop = invoke(
            MODULE,
            GLOBAL,
            "AdvanceTransport",
            unloading,
            {
                "kind": "observed",
                "tick": 300,
                "transportToken": "transport:1",
                "attachedCargoTokens": [],
                "cargoPositions": {"eng:1": [2620.01, 0, 0]},
            },
        )
        assert outside_drop["state"] == "unloading"
        assert outside_drop["released"] is not True

    def test_intelligence_module_has_no_engine_global_hidden_scan_or_warp_surface(self) -> None:
        text = director_path(MODULE).read_text(encoding="utf-8")
        for forbidden in (
            "ArmyBrains",
            "GetArmyBrain",
            "GetCurrentEnemy",
            "GetListOfUnits",
            "GetUnitsAroundPoint",
            "GetEntitiesInRect",
            "GetUnitsInRect",
            "Warp",
            "Issue",
            "import(",
        ):
            assert forbidden not in text


def test_current_ai_runtime_does_not_receive_observer_opponent_aggregates() -> None:
    runtime_paths = [
        Path("lua/AI/Overmind4/Controller.lua"),
        Path("lua/AI/Overmind4/Policy.lua"),
        *(director_path(name) for name in ("MacroDirector.lua", "Intelligence.lua", "ForceDirector.lua")),
    ]
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in runtime_paths if path.is_file()
    )

    for forbidden in (
        "opponentAggregate",
        "opponentIncome",
        "opponentSpend",
        "opponentReclaim",
        "benchmarkCheckpoints",
        "benchmarkOpponent",
        "OM4BenchmarkLatest",
    ):
        assert forbidden not in combined
