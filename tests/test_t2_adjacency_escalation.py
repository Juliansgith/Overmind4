from __future__ import annotations

from typing import Any

import pytest

from test_controller import make_harness
from test_policy import lua_value, plain


def _set_director_result(harness: Any, name: str, value: Any) -> None:
    harness.lua.globals().directorResults[name] = lua_value(harness.lua, value)


def _macro_plan(*, lane: str, grant: bool = True) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "valid": True,
        "epoch": 1,
        "lanes": {lane: {"admitted": True}},
        "regions": [],
        "intents": [],
    }
    if grant:
        plan["grants"] = [
            {
                "requestId": f"{lane}-1",
                "lane": lane,
                "source": "bank",
                "massCost": 1200,
                "energyCost": 12000,
            }
        ]
    return plan


def _healthy_bank(harness: Any) -> None:
    harness.brain.massStoredRatio = 1
    harness.brain.massStored = 5000
    harness.brain.massTrend = 1
    harness.brain.energyStoredRatio = 1
    harness.brain.energyStored = 50000
    harness.brain.energyTrend = 10


def test_completed_t2_hq_builds_one_t2_engineer_before_t2_combat() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    _set_director_result(harness, "macroPlan", _macro_plan(lane="tech"))
    _set_director_result(
        harness,
        "techPlan",
        {"t2ProductionRoles": ["t2_direct_fire", "t2_anti_air"]},
    )
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(
                entityId=20,
                blueprintId="ueb0201",
                canBuild={"uel0208": True, "uel0202": True, "uel0205": True},
            )
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildFactory) == 1
    assert harness.calls.buildFactory[1].blueprintId == "uel0208"


def test_committed_tech_lane_without_a_new_grant_does_not_idle_t2_hq() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    macro_plan = _macro_plan(lane="land_production")
    macro_plan["lanes"]["tech"] = {"admitted": True}
    _set_director_result(harness, "macroPlan", macro_plan)
    _set_director_result(
        harness,
        "techPlan",
        {"t2ProductionRoles": ["t2_direct_fire", "t2_anti_air"]},
    )
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(
                entityId=20,
                blueprintId="ueb0201",
                canBuild={"uel0208": True, "uel0202": True, "uel0205": True},
            )
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildFactory) == 1
    assert harness.calls.buildFactory[1].blueprintId == "uel0202"


@pytest.mark.parametrize("existing", ["completed", "pending"])
def test_t2_engineer_is_not_duplicated(existing: str) -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    _set_director_result(harness, "macroPlan", _macro_plan(lane="tech"))
    _set_director_result(
        harness,
        "techPlan",
        {"t2ProductionRoles": ["t2_direct_fire", "t2_anti_air"]},
    )
    factory = harness.unit(
        entityId=20,
        blueprintId="ueb0201",
        canBuild={"uel0208": True, "uel0202": True, "uel0205": True},
    )
    units = [factory]
    if existing == "completed":
        units.append(harness.unit(entityId=21, blueprintId="uel0208"))
    else:
        harness.controller.pending["20:1"] = lua_value(
            harness.lua,
            {
                "kind": "factory_build",
                "actorToken": "20:1",
                "buildRole": "t2_engineer",
                "issuedTick": 0,
                "deadlineTick": 900,
            },
        )
    harness.brain.units = harness.lua.table_from(units)

    harness.lua.globals().Controller.Step(harness.controller)

    assert not any(
        call.blueprintId == "uel0208" for call in harness.calls.buildFactory.values()
    )


def test_mature_mex_economy_scales_to_three_t2_engineers() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    _set_director_result(
        harness, "macroPlan", _macro_plan(lane="land_production")
    )
    _set_director_result(
        harness,
        "techPlan",
        {"t2ProductionRoles": ["t2_direct_fire", "t2_anti_air"]},
    )
    factory = harness.unit(
        entityId=20,
        blueprintId="ueb0201",
        canBuild={"uel0208": True, "uel0202": True, "uel0205": True},
    )
    mexes = [
        harness.unit(
            entityId=100 + index,
            blueprintId="ueb1202",
            position=[80 + index * 4, 2, 80],
        )
        for index in range(17)
    ]
    harness.brain.units = harness.lua.table_from(
        [factory, harness.unit(entityId=21, blueprintId="uel0208"), *mexes]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildFactory) == 1
    assert harness.calls.buildFactory[1].blueprintId == "uel0208"


def test_t2_generator_candidates_touch_factory_skirt_and_require_t2_builder() -> None:
    harness = make_harness()
    factory = harness.unit(
        entityId=20,
        blueprintId="ueb0201",
        position=[40, 2, 40],
    )
    harness.brain.units = harness.lua.table_from([factory])
    without_builder = plain(harness.observe().placements)
    assert not without_builder.get("power_generator_t2")

    engineer = harness.unit(
        entityId=21,
        blueprintId="uel0208",
        position=[35, 2, 40],
        canBuild={"ueb1201": True},
    )
    harness.brain.units = harness.lua.table_from([factory, engineer])
    candidates = plain(harness.observe().placements)["power_generator_t2"]

    assert candidates
    # Pinned FAF skirts: UEB0201 is 8x8 around this centered placement;
    # UEB1201 is a 6x6 skirt with a -1.5 offset on its 3x3 footprint.
    factory_rect = [36, 36, 44, 44]
    generator_rect = [
        candidates[0][0] - 3,
        candidates[0][2] - 3,
        candidates[0][0] + 3,
        candidates[0][2] + 3,
    ]
    edge_touch = (
        generator_rect[2] == pytest.approx(factory_rect[0])
        or generator_rect[0] == pytest.approx(factory_rect[2])
        or generator_rect[3] == pytest.approx(factory_rect[1])
        or generator_rect[1] == pytest.approx(factory_rect[3])
    )
    assert edge_touch


def test_healthy_t2_engineer_builds_one_adjacent_t2_generator() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    _healthy_bank(harness)
    _set_director_result(
        harness, "macroPlan", _macro_plan(lane="energy_recovery")
    )
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(
                entityId=20,
                blueprintId="ueb0201",
                position=[40, 2, 40],
            ),
            harness.unit(
                entityId=21,
                blueprintId="uel0208",
                position=[35, 2, 40],
                canBuild={"ueb1201": True},
            ),
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb1201"
    pending = plain(harness.controller.pending)
    assert pending["21:1"]["buildRole"] == "power_generator_t2"
    assert pending["21:1"]["reason"] == "factory_adjacency_t2_power"


def test_twelve_mex_with_positive_partial_bank_prebuild_second_t2_generator() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    _healthy_bank(harness)
    harness.brain.massStoredRatio = 0.9
    harness.brain.massTrend = 0.5
    harness.brain.energyStoredRatio = 0.37
    harness.brain.energyTrend = 0.03
    _set_director_result(
        harness, "macroPlan", _macro_plan(lane="energy_recovery")
    )
    mexes = [
        harness.unit(
            entityId=100 + index,
            blueprintId="ueb1103",
            position=[80 + index * 4, 2, 80],
        )
        for index in range(12)
    ]
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(entityId=20, blueprintId="ueb0201", position=[40, 2, 40]),
            harness.unit(entityId=22, blueprintId="ueb1201", position=[50, 2, 40]),
            harness.unit(
                entityId=21,
                blueprintId="uel0208",
                position=[35, 2, 40],
                canBuild={"ueb1201": True},
            ),
            *mexes,
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb1201"


def test_energy_deficit_immediately_adds_next_t2_generator() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    _healthy_bank(harness)
    harness.brain.energyStoredRatio = 0.18
    harness.brain.energyTrend = -1
    harness.brain.energyIncome = 48
    harness.brain.energyRequested = 57
    _set_director_result(
        harness, "macroPlan", _macro_plan(lane="energy_recovery")
    )
    mexes = [
        harness.unit(
            entityId=100 + index,
            blueprintId="ueb1103",
            position=[80 + index * 4, 2, 80],
        )
        for index in range(17)
    ]
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(entityId=20, blueprintId="ueb0201", position=[40, 2, 40]),
            harness.unit(entityId=22, blueprintId="ueb1201", position=[50, 2, 40]),
            harness.unit(
                entityId=21,
                blueprintId="uel0208",
                position=[35, 2, 40],
                canBuild={"ueb1201": True},
            ),
            *mexes,
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb1201"


def test_first_t2_engineer_clears_rally_and_builds_local_power_immediately() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    harness.brain.massStoredRatio = 0.1
    harness.brain.massTrend = 0
    harness.brain.energyStoredRatio = 0.1
    harness.brain.energyTrend = 0
    harness.brain.energyIncome = 30
    harness.brain.energyRequested = 30
    _set_director_result(
        harness, "macroPlan", _macro_plan(lane="energy_recovery")
    )
    mexes = [
        harness.unit(
            entityId=100 + index,
            blueprintId="ueb1103",
            position=[80 + index * 4, 2, 80],
        )
        for index in range(17)
    ]
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(entityId=20, blueprintId="ueb0201", position=[40, 2, 40]),
            harness.unit(
                entityId=21,
                blueprintId="uel0208",
                position=[35, 2, 40],
                canBuild={"ueb1201": True},
                idleState=False,
                states={"Moving": True},
            ),
            *mexes,
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.clear) == 1
    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb1201"


def test_second_t2_engineer_is_reserved_for_local_power_before_touring() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    harness.brain.massStoredRatio = 0.1
    harness.brain.massTrend = 0
    harness.brain.energyStoredRatio = 0.1
    harness.brain.energyTrend = 0
    harness.brain.energyIncome = 30
    harness.brain.energyRequested = 30
    _set_director_result(
        harness, "macroPlan", _macro_plan(lane="energy_recovery")
    )
    mexes = [
        harness.unit(
            entityId=100 + index,
            blueprintId="ueb1103",
            position=[80 + index * 4, 2, 80],
        )
        for index in range(17)
    ]
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(entityId=20, blueprintId="ueb0201", position=[40, 2, 40]),
            harness.unit(entityId=22, blueprintId="ueb1201", position=[31, 2, 40]),
            harness.unit(
                entityId=21,
                blueprintId="uel0208",
                position=[35, 2, 40],
                canBuild={"ueb1201": True},
                idleState=False,
                states={"Moving": True},
            ),
            *mexes,
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.clear) == 1
    assert len(harness.calls.buildMobile) == 1
    target = plain(harness.calls.buildMobile[1].position)
    assert (target[0] - 40) ** 2 + (target[2] - 40) ** 2 < 20**2


def test_t2_power_uses_nearest_builder_candidate_pair_not_first_factory() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    _healthy_bank(harness)
    _set_director_result(
        harness, "macroPlan", _macro_plan(lane="energy_recovery")
    )
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(entityId=20, blueprintId="ueb0201", position=[200, 2, 200]),
            harness.unit(entityId=30, blueprintId="ueb0201", position=[40, 2, 40]),
            harness.unit(
                entityId=31,
                blueprintId="uel0208",
                position=[35, 2, 40],
                canBuild={"ueb1201": True},
            ),
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    target = plain(harness.calls.buildMobile[1].position)
    assert (target[0] - 40) ** 2 + (target[2] - 40) ** 2 < 20**2


def test_factory_rally_does_not_leave_t2_builder_moving_past_the_power_window() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    _healthy_bank(harness)
    _set_director_result(
        harness, "macroPlan", _macro_plan(lane="energy_recovery")
    )
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(entityId=20, blueprintId="ueb0201", position=[40, 2, 40]),
            harness.unit(
                entityId=21,
                blueprintId="uel0208",
                position=[35, 2, 40],
                canBuild={"ueb1201": True},
                idleState=False,
                states={"Moving": True},
            ),
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.clear) == 1
    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb1201"


@pytest.mark.parametrize(
    ("mass_ratio", "energy_ratio"),
    [(0.949, 1), (1, 0.499)],
)
def test_t2_generator_waits_for_safe_physical_bank(
    mass_ratio: float, energy_ratio: float
) -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    _healthy_bank(harness)
    harness.brain.massStoredRatio = mass_ratio
    harness.brain.energyStoredRatio = energy_ratio
    _set_director_result(
        harness, "macroPlan", _macro_plan(lane="energy_recovery")
    )
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(entityId=20, blueprintId="ueb0201", position=[40, 2, 40]),
            harness.unit(
                entityId=21,
                blueprintId="uel0208",
                position=[35, 2, 40],
                canBuild={"ueb1201": True},
            ),
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert not any(
        call.blueprintId == "ueb1201" for call in harness.calls.buildMobile.values()
    )


def test_pending_or_completed_t2_generator_suppresses_another() -> None:
    for existing in ("pending", "completed"):
        harness = make_harness()
        harness.lua.execute("Policy.Decide = function() return {} end")
        _healthy_bank(harness)
        _set_director_result(
            harness, "macroPlan", _macro_plan(lane="energy_recovery")
        )
        units = [
            harness.unit(entityId=20, blueprintId="ueb0201", position=[40, 2, 40]),
            harness.unit(
                entityId=21,
                blueprintId="uel0208",
                position=[35, 2, 40],
                canBuild={"ueb1201": True},
            ),
        ]
        if existing == "completed":
            units.append(
                harness.unit(entityId=22, blueprintId="ueb1201", position=[31, 2, 40])
            )
        else:
            harness.controller.pending["21:1"] = lua_value(
                harness.lua,
                {
                    "kind": "build_structure",
                    "actorToken": "21:1",
                    "buildRole": "power_generator_t2",
                    "position": [31, 2, 40],
                    "issuedTick": 0,
                    "deadlineTick": 900,
                },
            )
        harness.brain.units = harness.lua.table_from(units)

        harness.lua.globals().Controller.Step(harness.controller)

        assert not any(
            call.blueprintId == "ueb1201" for call in harness.calls.buildMobile.values()
        )


def test_completed_t2_hq_funds_cheap_support_upgrade_before_more_mex() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    harness.brain.units = harness.lua.table_from(
        [
            *[
                harness.unit(
                    entityId=index,
                    blueprintId="ueb1202" if index < 12 else "ueb1103",
                )
                for index in range(10, 20)
            ],
            harness.unit(entityId=20, blueprintId="ueb0101"),
            harness.unit(entityId=21, blueprintId="ueb0101"),
            harness.unit(entityId=22, blueprintId="ueb0201"),
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    requests = plain(harness.calls.macroBuildPortfolio[1])["requests"]
    tech_requests = [request for request in requests if request["lane"] == "tech"]
    assert [request["id"] for request in tech_requests] == [
        "tech-support-1",
        "tech-mex-1",
    ]
    assert tech_requests[0]["massCost"] == 340
    assert tech_requests[0]["energyCost"] == 2700
    assert tech_requests[0]["portfolioPriority"] < tech_requests[1]["portfolioPriority"]


def test_two_funded_mex_upgrade_slots_issue_two_distinct_upgrades() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"tech": {"admitted": True}},
            "grants": [
                {"requestId": "tech-1", "lane": "tech", "source": "bank"},
                {"requestId": "tech-2", "lane": "tech", "source": "bank"},
            ],
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "techPlan",
        {
            "mexUpgradeSiteKeys": ["30:1", "31:1"],
            "mexUpgradeRolesBySite": {
                "30:1": "mass_extractor_t2",
                "31:1": "mass_extractor_t2",
            },
        },
    )
    harness.brain.units = harness.lua.table_from(
        [
            harness.unit(
                entityId=30,
                blueprintId="ueb1103",
                canBuild={"ueb1202": True},
            ),
            harness.unit(
                entityId=31,
                blueprintId="ueb1103",
                canBuild={"ueb1202": True},
            ),
        ]
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.upgrade) == 2
    assert {call.units[1].options.entityId for call in harness.calls.upgrade.values()} == {
        30,
        31,
    }
