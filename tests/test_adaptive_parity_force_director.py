from __future__ import annotations

import copy
import random
from typing import Any

import pytest

from adaptive_parity_helpers import director_path, director_present, invoke


MODULE = "ForceDirector.lua"
GLOBAL = "ForceDirector"
BUCKETS = ("home", "garrison", "field", "response", "raider", "unassigned")


def combat_units(count: int) -> list[dict[str, Any]]:
    units = []
    for index in range(1, count + 1):
        role = "anti_air" if index % 5 == 0 else ("lab" if index % 7 == 0 else "tank")
        units.append(
            {
                "token": f"unit-{index:03d}:1",
                "role": role,
                "complete": True,
                "live": True,
                "owned": True,
                "healthRatio": 1,
                "position": [index, 0, index],
            }
        )
    return units


def force_snapshot(count: int = 40, **updates: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "tick": 6000,
        "units": combat_units(count),
        "home": {"position": [0, 0, 0], "breached": False},
        "regions": [
            {
                "key": "front",
                "state": "establishing",
                "position": [200, 0, 200],
                "requiresGarrison": True,
                "requiresAntiAir": True,
            }
        ],
        "campaign": {"state": "active", "maxOwnedRatio": 0.6},
    }
    snapshot.update(updates)
    return snapshot


def assigned(plan: dict[str, Any], bucket: str) -> list[str]:
    return plan["assignments"].get(bucket, [])


def test_force_director_is_a_dedicated_runtime_module() -> None:
    assert director_path(MODULE).is_file()


@pytest.mark.skipif(not director_present(MODULE), reason="ForceDirector RED module missing")
class TestCombatOwnership:
    def test_every_live_combat_unit_has_exactly_one_explicit_owner(self) -> None:
        plan = invoke(MODULE, GLOBAL, "Assign", force_snapshot())

        tokens = [token for bucket in BUCKETS for token in assigned(plan, bucket)]
        expected = [unit["token"] for unit in combat_units(40)]

        assert len(tokens) == len(set(tokens))
        assert sorted(tokens) == sorted(expected)
        assert set(plan["ownershipByToken"]) == set(expected)

    def test_healthy_force_uses_bounded_home_garrison_field_response_and_raider_proportions(self) -> None:
        plan = invoke(MODULE, GLOBAL, "Assign", force_snapshot(100))
        ratios = plan["ratios"]

        assert 0.20 <= ratios["home"] <= 0.35
        assert 0.10 <= ratios["garrison"] <= 0.20
        assert 0.35 <= ratios["field"] <= 0.60
        assert 0.10 <= ratios["response"] <= 0.20
        assert 0 <= ratios["raider"] <= 0.10
        assert ratios["unassigned"] <= 0.10

    def test_immediate_home_breach_preempts_response_then_field_without_touching_garrison(self) -> None:
        snapshot = force_snapshot()
        plan = invoke(MODULE, GLOBAL, "Assign", snapshot)
        breach = invoke(
            MODULE,
            GLOBAL,
            "HandleHomeBreach",
            {**snapshot, "home": {"position": [0, 0, 0], "breached": True}},
            plan,
        )

        responders = breach["responseIntent"]["actorTokens"]
        assert responders
        assert set(responders).isdisjoint(assigned(plan, "garrison"))
        assert breach["responseIntent"]["position"] == [0, 0, 0]
        assert len(
            [
                token
                for bucket in BUCKETS
                for token in assigned(breach, bucket)
            ]
        ) == len(combat_units(40))

    def test_dead_captured_and_recycled_generations_release_only_the_exact_assignment(self) -> None:
        snapshot = force_snapshot(20)
        plan = invoke(MODULE, GLOBAL, "Assign", snapshot)
        victim = next(token for token in plan["ownershipByToken"])
        base_units = copy.deepcopy(snapshot["units"])
        mutations = []
        mutations.append([unit for unit in base_units if unit["token"] != victim])
        mutations.append(
            [
                ({**unit, "owned": False} if unit["token"] == victim else unit)
                for unit in base_units
            ]
        )
        recycled_id = victim.split(":", 1)[0] + ":2"
        mutations.append(
            [
                ({**unit, "token": recycled_id} if unit["token"] == victim else unit)
                for unit in base_units
            ]
        )

        for live_units in mutations:
            reconciled = invoke(
                MODULE, GLOBAL, "Reconcile", plan, {"units": live_units, "tick": 6010}
            )
            assert victim not in reconciled["ownershipByToken"]
            surviving = {
                unit["token"]
                for unit in live_units
                if unit.get("owned") is not False and unit["token"] != recycled_id
            }
            assert surviving <= set(reconciled["ownershipByToken"])

    def test_campaign_never_monopolizes_or_pins_three_quarters_of_combat(self) -> None:
        for state in ("active", "rebuilding", "recalled"):
            snapshot = force_snapshot(80)
            snapshot["campaign"]["state"] = state
            plan = invoke(MODULE, GLOBAL, "Assign", snapshot)
            assert plan["ratios"]["field"] <= 0.60, state
            assert plan["ratios"]["home"] >= 0.20, state
            assert len(assigned(plan, "response")) >= 8, state

    def test_rebuilding_campaign_does_not_absorb_newly_completed_unordered_units(self) -> None:
        initial_snapshot = force_snapshot(24)
        initial_snapshot["campaign"]["state"] = "rebuilding"
        initial = invoke(MODULE, GLOBAL, "Assign", initial_snapshot)
        grown_snapshot = force_snapshot(28)
        grown_snapshot["campaign"]["state"] = "rebuilding"
        grown_snapshot["previousAssignments"] = initial["assignments"]

        grown = invoke(MODULE, GLOBAL, "Assign", grown_snapshot)
        new_tokens = {f"unit-{index:03d}:1" for index in range(25, 29)}

        assert new_tokens.isdisjoint(assigned(grown, "field"))
        assert new_tokens <= (
            set(assigned(grown, "home"))
            | set(assigned(grown, "response"))
            | set(assigned(grown, "garrison"))
        )

    def test_establishing_expansion_has_bound_land_and_aa_garrison_before_ready(self) -> None:
        plan = invoke(MODULE, GLOBAL, "Assign", force_snapshot(30))
        region = plan["regionAssignments"]["front"]

        assert len(region["actorTokens"]) >= 4
        assert region["antiAirCount"] >= 1
        assert region["ready"] is True
        assert set(region["actorTokens"]) <= set(assigned(plan, "garrison"))

    def test_force_assignment_is_deterministic_under_unit_permutation(self) -> None:
        snapshot = force_snapshot(50)
        expected = invoke(MODULE, GLOBAL, "Assign", snapshot)

        for seed in range(8):
            shuffled = copy.deepcopy(snapshot)
            random.Random(seed).shuffle(shuffled["units"])
            assert invoke(MODULE, GLOBAL, "Assign", shuffled) == expected

    def test_malformed_or_ineligible_units_fail_closed_into_no_combat_order(self) -> None:
        snapshot = force_snapshot(12)
        snapshot["units"] += [
            {"token": "dead:1", "role": "tank", "complete": True, "live": False, "owned": True},
            {"token": "captured:1", "role": "tank", "complete": True, "live": True, "owned": False},
            {"token": "incomplete:1", "role": "tank", "complete": False, "live": True, "owned": True},
            {"token": None, "role": "tank", "complete": True, "live": True, "owned": True},
            {"token": "engineer:1", "role": "engineer", "complete": True, "live": True, "owned": True},
        ]

        plan = invoke(MODULE, GLOBAL, "Assign", snapshot)

        assigned_tokens = set(plan["ownershipByToken"])
        assert all(token.startswith("unit-") for token in assigned_tokens)
        assert len(assigned_tokens) == 12
