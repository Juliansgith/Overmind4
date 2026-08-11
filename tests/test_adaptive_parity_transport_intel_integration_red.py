from __future__ import annotations

import math
from typing import Any

import pytest

from conftest import source
from test_controller import make_harness
from test_policy import lua_value, plain


def _set_director_result(harness: Any, name: str, value: Any) -> None:
    harness.lua.globals().directorResults[name] = lua_value(harness.lua, value)


def _capture_policy_snapshots(harness: Any) -> None:
    harness.lua.execute(
        "Policy.Decide = function(snapshot) "
        "table.insert(calls.policySnapshots, snapshot); return {} end"
    )


def _use_real_intelligence_planners(
    harness: Any, *, scout: bool = False, transport: bool = False
) -> None:
    harness.lua.execute(source("lua/AI/Overmind4/Intelligence.lua"))
    harness.lua.execute("RealIntelligence = Intelligence")
    if scout:
        harness.lua.execute(
            "IntelligenceStub.PlanScoutRoute = function(snapshot) "
            "table.insert(calls.intelligencePlanScoutRoute, snapshot); "
            "return RealIntelligence.PlanScoutRoute(snapshot) end"
        )
    if transport:
        harness.lua.execute(
            "IntelligenceStub.PlanTransport = function(snapshot) "
            "table.insert(calls.intelligencePlanTransport, snapshot); "
            "return RealIntelligence.PlanTransport(snapshot) end"
        )


def _mass_marker(key: str, position: list[float]) -> dict[str, Any]:
    distance = math.hypot(position[0] - 10, position[2] - 20)
    return {
        "key": key,
        "name": key,
        "kind": "mass",
        "position": position,
        "distance": distance,
        "localSite": distance <= 60,
        "reachable": True,
        "engineerReachable": True,
        "landReachable": True,
    }


def _mobile_units(harness: Any, *, with_transport: bool = True) -> list[Any]:
    units = [
        harness.unit(
            entityId=71,
            blueprintId="uel0105",
            position=[10, 2, 20],
        )
    ]
    if with_transport:
        units.append(
            harness.unit(
                entityId=81,
                blueprintId="uea0107",
                position=[12, 20, 20],
                cargo=[],
            )
        )
    return units


@pytest.mark.parametrize("reverse_markers", [False, True])
def test_transport_filters_all_candidates_before_ranking_safe_site(
    reverse_markers: bool,
) -> None:
    harness = make_harness()
    _capture_policy_snapshots(harness)
    harness.brain.tick = 100
    harness.brain.units = harness.lua.table_from(_mobile_units(harness))
    unsafe = _mass_marker("a-unsafe-nearest", [150, 3, 20])
    # Keep the second candidate outside the runtime's explicit 80-unit
    # current-contact danger radius while remaining the next-nearest option.
    safe = _mass_marker("b-safe-next", [240, 3, 20])
    markers = [unsafe, safe]
    if reverse_markers:
        markers.reverse()
    harness.controller.markers.mass = lua_value(harness.lua, markers)
    intel_state = {
        "contacts": {
            "enemy:unsafe": {
                "token": "enemy:unsafe",
                "position": unsafe["position"],
                "lastSeenTick": 100,
                "source": "vision",
            }
        },
        "threat": {},
        "expansionSafety": {},
    }
    harness.controller.intelState = lua_value(harness.lua, intel_state)
    _set_director_result(harness, "intelState", intel_state)

    harness.lua.globals().Controller.Step(harness.controller)

    transport_input = plain(harness.calls.intelligencePlanTransport[1])
    assert transport_input["site"]["key"] == "b-safe-next"
    assert transport_input["site"]["safe"] is True


def test_completed_airlift_history_is_cleared_when_owned_mex_is_lost() -> None:
    harness = make_harness()
    _capture_policy_snapshots(harness)
    site = _mass_marker("remote-retake", [190, 3, 20])
    harness.controller.markers.mass = lua_value(harness.lua, [site])
    mobile_units = _mobile_units(harness)
    owned_mex = harness.unit(
        entityId=91,
        blueprintId="ueb1103",
        position=site["position"],
    )
    harness.brain.units = harness.lua.table_from([*mobile_units, owned_mex])
    history_key = "airlift:remote-retake"
    harness.controller.transportHistory[history_key] = lua_value(
        harness.lua,
        {
            "state": "completed",
            "siteKey": site["key"],
            "tick": 0,
            "retryable": False,
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    first_input = plain(harness.calls.intelligencePlanTransport[1])
    assert first_input.get("site") is None
    assert harness.controller.transportHistory[history_key] is not None

    harness.brain.tick = 10
    harness.brain.units = harness.lua.table_from(mobile_units)
    harness.lua.globals().Controller.Step(harness.controller)

    second_input = plain(harness.calls.intelligencePlanTransport[2])
    assert second_input.get("site") is not None
    assert second_input["site"]["key"] == site["key"]
    assert harness.controller.transportHistory[history_key] is None


@pytest.mark.parametrize(
    ("site_position", "with_transport", "expected_mode"),
    [
        ([110, 3, 20], False, "walk"),
        ([210, 3, 20], True, "airlift"),
    ],
)
def test_macro_expansion_and_transport_share_walk_or_airlift_site_choice(
    site_position: list[float],
    with_transport: bool,
    expected_mode: str,
) -> None:
    harness = make_harness()
    _capture_policy_snapshots(harness)
    _use_real_intelligence_planners(harness, transport=True)
    site = _mass_marker("shared-mobility-site", site_position)
    harness.controller.markers.mass = lua_value(harness.lua, [site])
    harness.brain.units = harness.lua.table_from(
        _mobile_units(harness, with_transport=with_transport)
    )

    harness.lua.globals().Controller.Step(harness.controller)

    macro_site = plain(harness.calls.macroPlanExpansion[1])["sites"][0]
    policy_snapshot = harness.calls.policySnapshots[1]
    transport_plan = plain(policy_snapshot.transportPlan)
    transport_input = plain(harness.calls.intelligencePlanTransport[1])
    assert macro_site["key"] == site["key"]
    assert macro_site["reachable"] is True
    assert transport_input.get("site") is not None
    assert transport_input["site"]["key"] == site["key"]
    assert transport_plan["siteKey"] == site["key"]
    assert transport_plan["mode"] == expected_mode


def _run_scaled_scout_step(reverse_markers: bool) -> tuple[list[Any], int]:
    harness = make_harness()
    _capture_policy_snapshots(harness)
    _use_real_intelligence_planners(harness, scout=True)
    markers = [
        _mass_marker(
            f"mass:{index:03d}",
            [200 + index, 3, 100 + (index % 17)],
        )
        for index in range(640)
    ]
    if reverse_markers:
        markers.reverse()
    harness.controller.markers.mass = lua_value(harness.lua, markers)
    scout = harness.unit(
        entityId=31,
        blueprintId="uea0101",
        position=[10, 20, 20],
    )
    harness.brain.units = harness.lua.table_from([scout])

    harness.lua.globals().Controller.Step(harness.controller)

    objective_count = len(
        plain(harness.calls.intelligencePlanScoutRoute[1])["objectives"]
    )
    patrol_positions = [
        plain(call.position) for call in harness.calls.patrol.values()
    ]
    return patrol_positions, objective_count


def test_controller_bounds_scout_orders_to_32_on_640_marker_map_permutations() -> None:
    forward_positions, forward_objectives = _run_scaled_scout_step(False)
    reverse_positions, reverse_objectives = _run_scaled_scout_step(True)

    # Three public spawn markers are added to the 640 public mass markers.
    assert forward_objectives == reverse_objectives == 643
    assert len(forward_positions) == len(reverse_positions) == 32
    assert reverse_positions == forward_positions
