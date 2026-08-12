from __future__ import annotations

from typing import Any

import pytest

from conftest import source
from test_controller import execute_intents, make_harness
from test_policy import lua_value, plain
from tools.overmind4_runner import parsing


def _set_director_result(harness: Any, name: str, value: Any) -> None:
    harness.lua.globals().directorResults[name] = lua_value(harness.lua, value)


def _set_starved_economy(harness: Any) -> None:
    harness.brain.massIncome = 0
    harness.brain.massRequested = 2
    harness.brain.massUsage = 2
    harness.brain.massTrend = -2
    harness.brain.massStored = 0
    harness.brain.massStoredRatio = 0
    harness.brain.energyIncome = 0
    harness.brain.energyRequested = 20
    harness.brain.energyUsage = 20
    harness.brain.energyTrend = -20
    harness.brain.energyStored = 0
    harness.brain.energyStoredRatio = 0


def _use_real_macro_job_ledger(harness: Any) -> None:
    """Keep the Controller harness adapters but exercise the production ledger."""
    harness.lua.execute(source("lua/AI/Overmind4/MacroDirector.lua"))
    harness.lua.execute(
        "MacroDirectorStub.UpdateJobLedger = MacroDirector.UpdateJobLedger"
    )


def _use_real_macro_expansion_and_job_ledger(harness: Any) -> None:
    """Exercise production expansion selection and its persistent job ledger."""
    _use_real_macro_job_ledger(harness)
    harness.lua.execute("MacroDirectorStub.PlanExpansion = MacroDirector.PlanExpansion")


def _configure_local_expansion(
    harness: Any,
    *,
    actor_token: str = "72:1",
    operation_id: str = "mex:home:near",
) -> tuple[dict[str, Any], dict[str, Any]]:
    site = plain(harness.controller.markers.mass[1])
    job = {
        "id": operation_id,
        "kind": "build_mex",
        "actorToken": actor_token,
        "targetKey": site["key"],
        "siteKey": site["key"],
        "regionKey": "home",
        "position": site["position"],
        "estimatedTravelTicks": 10,
        "requiresEscort": False,
    }
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(harness, "expansionPlan", {"jobs": [job], "denials": []})
    return site, job


def _operation_events(harness: Any, operation_id: str) -> list[dict[str, str]]:
    return [
        fields
        for line in harness.logs
        if (fields := parsing.overmind_marker_fields(line)) is not None
        and fields.get("kind") == "operation"
        and fields.get("operation") == operation_id
    ]


def _assert_operation_stream_clean(harness: Any) -> None:
    telemetry = parsing.parse_log("\n".join(harness.logs), "runtime-contract", 1)
    assert telemetry.operation_integrity_reason is None


def _same_lua_reference(harness: Any, left: Any, right: Any) -> bool:
    return bool(harness.lua.eval("function(a, b) return a == b end")(left, right))


def test_real_portfolio_funds_opening_factory_before_future_factory_queues() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/MacroDirector.lua"))
    harness.lua.execute("MacroDirectorStub.BuildPortfolio = MacroDirector.BuildPortfolio")
    harness.brain.units = harness.lua.table_from([
        harness.unit(
            entityId=1,
            blueprintId="uel0001",
            canBuild={"ueb0101": True},
        )
    ])
    harness.brain.massIncome = 0.1
    harness.brain.massRequested = 0
    harness.brain.massUsage = 0
    harness.brain.massTrend = 0.1
    harness.brain.massStored = 650
    harness.brain.energyIncome = 2
    harness.brain.energyRequested = 0
    harness.brain.energyUsage = 0
    harness.brain.energyTrend = 2
    harness.brain.energyStored = 4000

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb0101"


def test_banked_post_mex_tech_commits_the_first_t2_land_hq_during_a_stall() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/MacroDirector.lua"))
    harness.lua.execute(
        "local RealBuildPortfolio = MacroDirector.BuildPortfolio; "
        "MacroDirectorStub.BuildPortfolio = function(snapshot) "
        "table.insert(calls.macroBuildPortfolio, snapshot); "
        "return RealBuildPortfolio(snapshot) end"
    )
    harness.lua.execute("Policy.Decide = function() return {} end")
    mexes = [
        harness.unit(entityId=entity_id, blueprintId="ueb1103")
        for entity_id in range(10, 18)
    ] + [
        harness.unit(entityId=18, blueprintId="ueb1202"),
        harness.unit(entityId=19, blueprintId="ueb1202"),
    ]
    factories = [
        harness.unit(
            entityId=entity_id,
            blueprintId="ueb0101",
            canBuild={"ueb0201": True},
        )
        for entity_id in (20, 21)
    ]
    harness.brain.units = harness.lua.table_from([*mexes, *factories])
    harness.brain.massIncome = 2.9
    harness.brain.massRequested = 3.1
    harness.brain.massUsage = 2.9
    harness.brain.massTrend = -0.2
    harness.brain.massStored = 5000
    harness.brain.massStoredRatio = 1
    harness.brain.energyIncome = 29
    harness.brain.energyRequested = 31
    harness.brain.energyUsage = 29
    harness.brain.energyTrend = -2
    harness.brain.energyStored = 50000
    harness.brain.energyStoredRatio = 1

    harness.lua.globals().Controller.Step(harness.controller)

    macro_input = plain(harness.calls.macroBuildPortfolio[1])
    tech_request = next(
        request for request in macro_input["requests"] if request["lane"] == "tech"
    )
    assert tech_request["required"] is True
    assert tech_request.get("optional") is not True
    assert plain(harness.controller.macroPlan)["lanes"]["tech"]["admitted"] is True


def test_nine_mex_macro_uses_rolling_demand_for_the_first_t2_upgrade() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/MacroDirector.lua"))
    harness.lua.execute(
        "local RealBuildPortfolio = MacroDirector.BuildPortfolio; "
        "MacroDirectorStub.BuildPortfolio = function(snapshot) "
        "table.insert(calls.macroBuildPortfolio, snapshot); "
        "return RealBuildPortfolio(snapshot) end"
    )
    harness.lua.execute("Policy.Decide = function() return {} end")
    mexes = [
        harness.unit(
            entityId=entity_id,
            blueprintId="ueb1103",
            canBuild={"ueb1202": True},
        )
        for entity_id in range(10, 19)
    ]
    factories = [
        harness.unit(entityId=entity_id, blueprintId="ueb0101")
        for entity_id in (20, 21, 22)
    ]
    air_factory = harness.unit(entityId=23, blueprintId="ueb0102")
    air_package = [
        harness.unit(entityId=30, blueprintId="uea0101"),
        *[
            harness.unit(entityId=entity_id, blueprintId="uea0102")
            for entity_id in range(31, 39)
        ],
        harness.unit(entityId=39, blueprintId="uea0103"),
        harness.unit(entityId=40, blueprintId="uea0107"),
    ]
    harness.brain.units = harness.lua.table_from(
        [*mexes, *factories, air_factory, *air_package]
    )
    harness.brain.tick = 5815
    harness.brain.massIncome = 2.1
    harness.brain.massRequested = 4.46
    harness.brain.massUsage = 4.46
    harness.brain.massTrend = 1.34
    harness.brain.massStored = 1110
    harness.brain.massStoredRatio = 1
    harness.brain.energyIncome = 20
    harness.brain.energyRequested = 36.79
    harness.brain.energyUsage = 36.79
    harness.brain.energyTrend = 9.77
    harness.brain.energyStored = 4000
    harness.brain.energyStoredRatio = 1
    harness.controller.economyLedger = lua_value(
        harness.lua,
        {
            "valid": True,
            "inputValid": True,
            "lastTick": 5815,
            "recurringMassIncome": 2.1,
            "recurringEnergyIncome": 20,
            "massRequested": 0.76,
            "energyRequested": 10.23,
            "massDemandSatisfaction": 1,
            "energyDemandSatisfaction": 1,
            "oneTimeMassReserve": 1110,
            "oneTimeEnergyReserve": 4000,
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    macro_input = plain(harness.calls.macroBuildPortfolio[1])
    assert macro_input["economy"]["massRequested"] == pytest.approx(0.76)
    assert macro_input["economy"]["energyRequested"] == pytest.approx(10.23)
    assert any(
        request["lane"] == "air_production"
        for request in macro_input["requests"]
    ), macro_input["counts"]
    assert plain(harness.controller.macroPlan)["lanes"]["tech"]["admitted"] is True


def test_lost_mex_backlog_publishes_up_to_four_independent_rebuild_grants() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    fourth_site = {
        "occupiedSpawn": False,
        "distance": 50,
        "engineerReachable": True,
        "kind": "mass",
        "key": "Mass:50000:50000",
        "position": [50, 3, 50],
        "reachable": True,
        "landReachable": True,
        "localSite": True,
        "name": "Fourth Mass",
    }
    harness.controller.markers.mass[4] = lua_value(harness.lua, fourth_site)
    for site in plain(harness.controller.markers.mass):
        harness.controller.mexHistory[site["key"]] = lua_value(
            harness.lua, {"everOwned": True, "lost": True}
        )

    harness.lua.globals().Controller.Step(harness.controller)

    macro_input = plain(harness.calls.macroBuildPortfolio[1])
    assert [
        request["id"]
        for request in macro_input["requests"]
        if request["lane"] == "mex_rebuild"
    ] == ["mex-1", "mex-2", "mex-3", "mex-4"]


def test_full_bank_factory_growth_precedes_optional_engineer_and_air_reserves() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/MacroDirector.lua"))
    harness.lua.execute(
        "local RealBuildPortfolio = MacroDirector.BuildPortfolio; "
        "MacroDirectorStub.BuildPortfolio = function(snapshot) "
        "table.insert(calls.macroBuildPortfolio, snapshot); "
        "return RealBuildPortfolio(snapshot) end"
    )
    harness.lua.execute("Policy.Decide = function() return {} end")
    mexes = [
        harness.unit(entityId=entity_id, blueprintId="ueb1103")
        for entity_id in range(10, 20)
    ] + [harness.unit(entityId=20, blueprintId="ueb1202")]
    # The live 10-minute artifact had 11 completed mex, nine engineers, eight
    # interceptors and a full mass bank, but optional air/engineer grants
    # consumed the remaining energy reserve before funded factory growth.
    engineers = [
        harness.unit(
            entityId=entity_id,
            blueprintId="uel0105",
            canBuild={"ueb0101": True, "ueb0102": True},
        )
        for entity_id in range(100, 109)
    ]
    factories = [
        harness.unit(entityId=30, blueprintId="ueb0101"),
        harness.unit(entityId=31, blueprintId="ueb0101"),
        harness.unit(entityId=32, blueprintId="ueb0102"),
    ]
    air_package = [
        harness.unit(entityId=200, blueprintId="uea0101"),
        *[
            harness.unit(entityId=entity_id, blueprintId="uea0102")
            for entity_id in range(201, 209)
        ],
        harness.unit(entityId=209, blueprintId="uea0103"),
        harness.unit(entityId=210, blueprintId="uea0107"),
    ]
    harness.brain.units = harness.lua.table_from(
        [*mexes, *engineers, *factories, *air_package]
    )
    harness.brain.tick = 5815
    harness.brain.massIncome = 2.1
    harness.brain.massRequested = 1.9466667
    harness.brain.massUsage = 1.9466667
    harness.brain.massTrend = 0.1533333
    harness.brain.massStored = 635
    harness.brain.massStoredRatio = 0.945
    harness.brain.energyIncome = 30
    harness.brain.energyRequested = 24.1843
    harness.brain.energyUsage = 24.1843
    harness.brain.energyTrend = 5.8157
    harness.brain.energyStored = 4000
    harness.brain.energyStoredRatio = 1
    harness.controller.economyLedger = lua_value(
        harness.lua,
        {
            "valid": True,
            "inputValid": True,
            "lastTick": 5815,
            "recurringMassIncome": 2.1,
            "recurringEnergyIncome": 30,
            "massRequested": 1.9466667,
            "energyRequested": 24.1843,
            "massDemandSatisfaction": 1,
            "energyDemandSatisfaction": 1,
            "oneTimeMassReserve": 635,
            "oneTimeEnergyReserve": 4000,
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    macro_input = plain(harness.calls.macroBuildPortfolio[1])
    assert any(
        request["lane"] == "engineers" for request in macro_input["requests"]
    )
    assert any(
        request["lane"] == "land_production"
        for request in macro_input["requests"]
    )
    assert plain(harness.controller.macroPlan)["lanes"]["factory_growth"][
        "admitted"
    ] is True
    assert any(
        call.blueprintId == "ueb0101"
        for call in harness.calls.buildMobile.values()
    )


def test_two_t2_mex_full_bank_funds_hq_before_more_t1_factory_growth() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/MacroDirector.lua"))
    harness.lua.execute(
        "local RealBuildPortfolio = MacroDirector.BuildPortfolio; "
        "MacroDirectorStub.BuildPortfolio = function(snapshot) "
        "table.insert(calls.macroBuildPortfolio, snapshot); "
        "return RealBuildPortfolio(snapshot) end; "
        "MacroDirectorStub.PlanTech = MacroDirector.PlanTech"
    )
    harness.lua.execute("Policy.Decide = function() return {} end")
    mexes = [
        harness.unit(entityId=entity_id, blueprintId="ueb1103")
        for entity_id in range(10, 22)
    ] + [
        harness.unit(entityId=22, blueprintId="ueb1202"),
        harness.unit(entityId=23, blueprintId="ueb1202"),
    ]
    factories = [
        harness.unit(
            entityId=entity_id,
            blueprintId="ueb0101",
            canBuild={"ueb0201": True},
        )
        for entity_id in range(30, 36)
    ]
    air_factory = harness.unit(entityId=36, blueprintId="ueb0102")
    engineers = [
        harness.unit(entityId=entity_id, blueprintId="uel0105")
        for entity_id in range(100, 116)
    ]
    air_package = [
        harness.unit(entityId=200, blueprintId="uea0101"),
        *[
            harness.unit(entityId=entity_id, blueprintId="uea0102")
            for entity_id in range(201, 209)
        ],
        harness.unit(entityId=209, blueprintId="uea0103"),
        harness.unit(entityId=210, blueprintId="uea0107"),
    ]
    harness.brain.units = harness.lua.table_from(
        [*mexes, *factories, air_factory, *engineers, *air_package]
    )
    harness.brain.tick = 8875
    harness.brain.massIncome = 3.72
    harness.brain.massRequested = 2.24
    harness.brain.massUsage = 2.24
    harness.brain.massTrend = 1.48
    harness.brain.massStored = 1370
    harness.brain.massStoredRatio = 1
    harness.brain.energyIncome = 32.098
    harness.brain.energyRequested = 26.894
    harness.brain.energyUsage = 26.894
    harness.brain.energyTrend = 5.204
    harness.brain.energyStored = 4000
    harness.brain.energyStoredRatio = 1
    harness.controller.economyLedger = lua_value(
        harness.lua,
        {
            "valid": True,
            "inputValid": True,
            "lastTick": 8875,
            "recurringMassIncome": 3.72,
            "recurringEnergyIncome": 32.098,
            "massRequested": 2.24,
            "energyRequested": 26.894,
            "massDemandSatisfaction": 1,
            "energyDemandSatisfaction": 1,
            "oneTimeMassReserve": 1370,
            "oneTimeEnergyReserve": 4000,
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    macro_input = plain(harness.calls.macroBuildPortfolio[1])
    assert sum(
        request["lane"] == "tech" for request in macro_input["requests"]
    ) == 1
    assert plain(harness.controller.macroPlan)["lanes"]["tech"]["admitted"] is True
    assert plain(harness.controller.macroPlan)["lanes"]["factory_growth"][
        "admitted"
    ] is False
    assert len(harness.calls.upgrade) == 1
    assert harness.calls.upgrade[1].blueprintId == "ueb0201"

    harness.lua.globals().Controller.Step(harness.controller)
    next_input = plain(harness.calls.macroBuildPortfolio[2])
    assert not any(
        request["lane"] == "tech" for request in next_input["requests"]
    )
    assert any(
        request["lane"] == "factory_growth" for request in next_input["requests"]
    )
    assert len(harness.calls.upgrade) == 1


def test_air_production_request_persists_after_the_opening_air_mix_is_complete() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/MacroDirector.lua"))
    harness.lua.execute(
        "local RealBuildPortfolio = MacroDirector.BuildPortfolio; "
        "MacroDirectorStub.BuildPortfolio = function(snapshot) "
        "table.insert(calls.macroBuildPortfolio, snapshot); "
        "return RealBuildPortfolio(snapshot) end; "
        "Policy.Decide = function() return {} end"
    )
    air_factory = harness.unit(
        entityId=20,
        blueprintId="ueb0102",
        canBuild={"uea0102": True, "uea0103": True},
    )
    air_package = [
        harness.unit(entityId=30, blueprintId="uea0101"),
        *[
            harness.unit(entityId=entity_id, blueprintId="uea0102")
            for entity_id in range(31, 43)
        ],
        harness.unit(entityId=43, blueprintId="uea0103"),
        harness.unit(entityId=44, blueprintId="uea0103"),
        harness.unit(entityId=45, blueprintId="uea0107"),
    ]
    harness.brain.units = harness.lua.table_from([air_factory, *air_package])
    harness.brain.massIncome = 4.4
    harness.brain.massRequested = 3.7
    harness.brain.massUsage = 3.7
    harness.brain.massTrend = 0.7
    harness.brain.massStored = 1679
    harness.brain.massStoredRatio = 1
    harness.brain.energyIncome = 84
    harness.brain.energyRequested = 44
    harness.brain.energyUsage = 44
    harness.brain.energyTrend = 40
    harness.brain.energyStored = 4000
    harness.brain.energyStoredRatio = 1

    harness.lua.globals().Controller.Step(harness.controller)

    macro_input = plain(harness.calls.macroBuildPortfolio[1])
    air_requests = [
        request
        for request in macro_input["requests"]
        if request["lane"] == "air_production"
    ]
    assert len(air_requests) == 1
    assert air_requests[0]["required"] is True
    assert air_requests[0]["massDrain"] == pytest.approx(0.2)
    assert air_requests[0]["energyDrain"] == pytest.approx(9)


@pytest.mark.parametrize(
    ("grant_count", "expected_orders"),
    ((0, 0), (1, 1), (2, 2), (4, 3)),
)
def test_air_grants_map_one_for_one_to_idle_factory_queues(
    grant_count: int,
    expected_orders: int,
) -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/Intelligence.lua"))
    harness.lua.execute(
        "local RealPlanAir = Intelligence.PlanAir; "
        "IntelligenceStub.PlanAir = function(snapshot) "
        "table.insert(calls.intelligencePlanAir, snapshot); "
        "return RealPlanAir(snapshot) end; "
        "Policy.Decide = function() return {} end"
    )
    factories = [
        harness.unit(
            entityId=entity_id,
            blueprintId="ueb0102",
            canBuild={"uea0102": True, "uea0103": True},
        )
        for entity_id in (20, 21, 22)
    ]
    air_package = [
        harness.unit(entityId=30, blueprintId="uea0101"),
        *[
            harness.unit(entityId=entity_id, blueprintId="uea0102")
            for entity_id in range(31, 43)
        ],
        harness.unit(entityId=43, blueprintId="uea0103"),
        harness.unit(entityId=44, blueprintId="uea0103"),
        harness.unit(entityId=45, blueprintId="uea0107"),
    ]
    harness.brain.units = harness.lua.table_from([*factories, *air_package])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"air_production": {"admitted": grant_count > 0}},
            "grants": [
                {
                    "requestId": f"air-{index}",
                    "lane": "air_production",
                    "source": "recurring",
                }
                for index in range(grant_count)
            ],
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    air_input = plain(harness.calls.intelligencePlanAir[1])
    assert air_input["fundedSlots"] == min(grant_count, 3)
    assert len(harness.calls.buildFactory) == expected_orders
    assert all(
        call.blueprintId in {"uea0102", "uea0103"}
        for call in harness.calls.buildFactory.values()
    )


@pytest.mark.parametrize(
    ("completed_scout", "expected_blueprint"),
    ((False, "uea0101"), (True, "uea0107")),
)
def test_opening_scout_and_transport_do_not_wait_for_optional_air_grants(
    completed_scout: bool,
    expected_blueprint: str,
) -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/Intelligence.lua"))
    harness.lua.execute(
        "local RealPlanAir = Intelligence.PlanAir; "
        "IntelligenceStub.PlanAir = function(snapshot) "
        "return RealPlanAir(snapshot) end; "
        "Policy.Decide = function() return {} end"
    )
    air_factory = harness.unit(
        entityId=20,
        blueprintId="ueb0102",
        canBuild={"uea0101": True, "uea0107": True},
    )
    units = [air_factory]
    if completed_scout:
        units.append(harness.unit(entityId=30, blueprintId="uea0101"))
    harness.brain.units = harness.lua.table_from(units)
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"air_production": {"admitted": False}},
            "grants": [],
            "regions": [
                {"key": "home", "position": [10, 2, 10]},
                {"key": "front", "position": [300, 2, 300]},
            ],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildFactory) == 1
    assert harness.calls.buildFactory[1].blueprintId == expected_blueprint


def test_ten_km_expansion_beyond_safe_local_radius_requires_an_escort() -> None:
    harness = make_harness()
    harness.lua.execute("ScenarioInfo.size = { 512, 512 }")

    harness.lua.globals().Controller.Step(harness.controller)

    expansion_input = plain(harness.calls.macroPlanExpansion[1])
    assert expansion_input["controlledRadius"] == 120


def test_force_owned_moving_combat_remains_available_as_region_bootstrap_escort() -> None:
    harness = make_harness()
    tank = harness.unit(
        entityId=70,
        blueprintId="uel0201",
        position=[20, 2, 20],
    )
    anti_air = harness.unit(
        entityId=71,
        blueprintId="uel0104",
        position=[22, 2, 20],
    )
    tank.options.idleState = False
    tank.options.movingState = True
    anti_air.options.idleState = False
    anti_air.options.movingState = True
    harness.brain.units = harness.lua.table_from([tank, anti_air])

    harness.lua.globals().Controller.Step(harness.controller)

    expansion_input = plain(harness.calls.macroPlanExpansion[1])
    escorts = {escort["token"]: escort for escort in expansion_input["escorts"]}
    assert escorts["70:1"]["available"] is True
    assert escorts["71:1"]["available"] is True


def test_funded_mex_expansion_does_not_claim_the_missing_hydro_builder() -> None:
    harness = make_harness()
    _use_real_macro_expansion_and_job_ledger(harness)
    engineer = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1102": True, "ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 1,
            "lanes": {
                "energy_recovery": {"admitted": True},
                "mex_rebuild": {"admitted": True},
            },
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb1102"


def test_full_bank_reserves_one_engineer_for_t2_mex_adjacency_before_expansion() -> None:
    harness = make_harness()
    _use_real_macro_expansion_and_job_ledger(harness)
    harness.lua.execute("Policy.Decide = function() return {} end")
    storage_builder = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[46, 2, 50],
        canBuild={"ueb1103": True, "ueb1106": True},
    )
    expansion_builder = harness.unit(
        entityId=73,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True, "ueb1106": True},
    )
    t2_mex = harness.unit(
        entityId=40,
        blueprintId="ueb1202",
        position=[50, 2, 50],
    )
    hydro = harness.unit(entityId=41, blueprintId="ueb1102")
    harness.brain.units = harness.lua.table_from([
        storage_builder,
        expansion_builder,
        t2_mex,
        hydro,
    ])
    harness.brain.massStored = 1600
    harness.brain.massStoredRatio = 1
    harness.brain.massTrend = 1
    harness.brain.energyStored = 2400
    harness.brain.energyStoredRatio = 0.6
    harness.brain.energyTrend = 10
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    calls = plain(harness.calls.buildMobile)
    assert sorted([
        (call["units"][0]["options"]["entityId"], call["blueprintId"])
        for call in calls
    ]) == [
        (72, "ueb1106"),
        (73, "ueb1103"),
    ]


def test_controller_assembles_director_snapshot_in_dependency_order_and_persists_state() -> None:
    harness = make_harness()
    _set_director_result(
        harness,
        "intelState",
        {
            "epoch": 1,
            "contacts": {"enemy:1": {"role": "bomber", "lastSeenTick": 0}},
            "threat": {"air": 4, "home": 2},
            "expansionSafety": {"front": "safe"},
        },
    )
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {
                "air_production": {"admitted": True},
                "mex_rebuild": {"admitted": True},
            },
            "regions": [
                {"key": "home", "state": "secured", "position": [10, 2, 20]}
            ],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "forcePlan",
        {
            "epoch": 1,
            "assignments": {"home": [], "field": []},
            "ownershipByToken": {},
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "radarIntents",
        [
            {
                "kind": "build_structure",
                "buildRole": "radar",
                "regionKey": "home",
                "position": [18, 2, 20],
            }
        ],
    )
    _set_director_result(
        harness,
        "jobLedger",
        {
            "epoch": 1,
            "jobs": {
                "mex:front:1": {
                    "id": "mex:front:1",
                    "phase": "travelling",
                    "actorToken": "eng-1:1",
                }
            },
        },
    )
    visible_enemy = harness.unit(
        entityId=90,
        blueprintId="uel0105",
        army=2,
        position=[40, 2, 40],
        seenNow=True,
        onRadar=True,
    )
    radar_enemy = harness.unit(
        entityId=91,
        blueprintId="uel0001",
        army=2,
        position=[80, 2, 80],
        seenNow=False,
        onRadar=True,
    )
    hidden_enemy = harness.unit(
        entityId=92,
        blueprintId="ueb0101",
        army=2,
        position=[120, 2, 120],
        seenNow=False,
        onRadar=False,
    )
    harness.brain.enemies = harness.lua.table_from(
        [visible_enemy, radar_enemy, hidden_enemy]
    )
    harness.lua.execute(
        "Policy.Decide = function(snapshot) "
        "table.insert(calls.policySnapshots, snapshot); return {} end"
    )

    harness.lua.globals().Controller.Step(harness.controller)
    first = harness.calls.policySnapshots[1]

    assert len(harness.calls.intelligenceUpdateMemory) == 1
    assert len(harness.calls.macroBuildPortfolio) == 1
    assert len(harness.calls.macroUpdateJobLedger) == 1
    assert len(harness.calls.intelligencePlanRadar) == 1
    assert len(harness.calls.forceAssign) == 1
    macro_input = plain(harness.calls.macroBuildPortfolio[1])
    force_input = plain(harness.calls.forceAssign[1])
    radar_input = plain(harness.calls.intelligencePlanRadar[1])
    intel_input = plain(harness.calls.intelligenceUpdateMemory[1].snapshot)
    observed_contacts = {
        (item["source"], item["role"], tuple(item["position"]))
        for item in intel_input["observations"]
    }
    assert observed_contacts == {
        ("vision", "engineer", (40, 2, 40)),
        ("radar", "unknown_mobile", (80, 2, 80)),
    }
    assert macro_input["intelState"]["threat"] == {"air": 4, "home": 2}
    assert macro_input["intelState"]["expansionSafety"] == {"front": "safe"}
    assert force_input["intelState"]["threat"]["air"] == 4
    assert force_input["macroPlan"]["regions"][0]["key"] == "home"
    assert radar_input["regions"][0]["key"] == "home"
    assert plain(first.intelState)["epoch"] == 1
    assert plain(first.macroPlan)["epoch"] == 1
    assert plain(first.forcePlan)["epoch"] == 1
    assert plain(first.jobLedger)["epoch"] == 1
    assert plain(first.directorIntents)[0]["buildRole"] == "radar"

    _set_director_result(
        harness,
        "intelState",
        {
            "epoch": 2,
            "contacts": {},
            "threat": {"air": 3},
            "expansionSafety": {"front": "contested"},
        },
    )
    harness.lua.globals().Controller.Step(harness.controller)
    second = harness.calls.policySnapshots[2]

    prior = plain(harness.calls.intelligenceUpdateMemory[2].previous)
    assert prior["epoch"] == 1
    previous_ledger = plain(harness.calls.macroUpdateJobLedger[2].ledger)
    assert previous_ledger["epoch"] == 1
    reconciled_force_plans = [
        plain(call.plan) for call in harness.calls.forceReconcile.values()
    ]
    assert any(plan.get("epoch") == 1 for plan in reconciled_force_plans)
    second_macro_input = plain(harness.calls.macroBuildPortfolio[2])
    second_force_input = plain(harness.calls.forceAssign[2])
    assert second_macro_input["intelState"]["expansionSafety"]["front"] == "contested"
    assert second_force_input["intelState"]["threat"]["air"] == 3
    assert plain(second.intelState)["epoch"] == 2
    assert plain(harness.controller.intelState)["epoch"] == 2
    assert plain(harness.controller.macroPlan)["epoch"] == 1
    assert plain(harness.controller.forcePlan)["epoch"] == 1


def test_observer_brain_snapshots_initialize_empty_finalize_after_force_plan_and_survive_stop() -> None:
    harness = make_harness()

    initial_force = plain(harness.brain.Overmind4ForcePlan)
    assert initial_force["epoch"] == 0
    assert set(initial_force["assignments"]) == {
        "home", "garrison", "field", "response", "raider"
    }
    assert all(len(tokens) == 0 for tokens in initial_force["assignments"].values())
    assert plain(harness.brain.Overmind4EntityGenerations) == {}

    tank = harness.unit(
        entityId=60,
        blueprintId="uel0201",
        position=[20, 2, 20],
    )
    harness.brain.units = harness.lua.table_from([tank])
    _set_director_result(
        harness,
        "forcePlan",
        {
            "epoch": 7,
            "assignments": {
                "home": [],
                "garrison": [],
                "field": ["60:1"],
                "response": [],
                "raider": [],
                "unassigned": [],
            },
            "ownershipByToken": {"60:1": "field"},
            "regionAssignments": {},
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "homeBreachPlan",
        {
            "epoch": 7,
            "assignments": {
                "home": [],
                "garrison": [],
                "field": [],
                "response": ["60:1"],
                "raider": [],
                "unassigned": [],
            },
            "ownershipByToken": {"60:1": "response"},
            "regionAssignments": {},
            "intents": [],
        },
    )
    harness.lua.execute("Policy.Decide = function() return {} end")

    harness.lua.globals().Controller.Step(harness.controller)

    exported = plain(harness.brain.Overmind4ForcePlan)
    assert exported["epoch"] == 7
    assert exported["assignments"]["response"] == ["60:1"]
    assert all(
        len(exported["assignments"][bucket]) == 0
        for bucket in ("home", "garrison", "field", "raider")
    )
    generation = harness.brain.Overmind4EntityGenerations[60]
    assert generation.generation == 1
    assert _same_lua_reference(harness, generation.reference, tank)

    harness.controller.forcePlan.assignments.response[1] = "mutated:1"
    harness.controller.entityGenerations[60].generation = 99
    assert plain(harness.brain.Overmind4ForcePlan)["assignments"]["response"] == [
        "60:1"
    ]
    assert harness.brain.Overmind4EntityGenerations[60].generation == 1

    harness.lua.globals().Controller.Stop(harness.controller, "victory")
    assert plain(harness.brain.Overmind4ForcePlan) == exported
    assert _same_lua_reference(
        harness,
        harness.brain.Overmind4EntityGenerations[60].reference,
        tank,
    )


def test_observer_snapshots_filter_stale_foreign_dead_and_recycled_identities() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    first = harness.unit(
        entityId=60,
        blueprintId="uel0201",
        position=[20, 2, 20],
    )
    harness.brain.units = harness.lua.table_from([first])
    _set_director_result(
        harness,
        "forcePlan",
        {
            "epoch": 1,
            "assignments": {"field": ["60:1"]},
            "ownershipByToken": {"60:1": "field"},
            "regionAssignments": {},
            "intents": [],
        },
    )
    harness.lua.globals().Controller.Step(harness.controller)
    assert _same_lua_reference(
        harness,
        harness.brain.Overmind4EntityGenerations[60].reference,
        first,
    )

    recycled = harness.unit(
        entityId=60,
        blueprintId="uel0201",
        position=[21, 2, 20],
    )
    captured = harness.unit(
        entityId=61,
        blueprintId="uel0201",
        army=2,
        position=[22, 2, 20],
    )
    dead = harness.unit(
        entityId=62,
        blueprintId="uel0201",
        Dead=True,
        position=[23, 2, 20],
    )
    harness.brain.units = harness.lua.table_from([recycled, captured, dead])
    _set_director_result(
        harness,
        "forcePlan",
        {
            "epoch": 2,
            "assignments": {
                "home": ["60:1", "61:1", "62:1", "999:1"],
                "field": ["60:2"],
            },
            "ownershipByToken": {
                "60:1": "home",
                "60:2": "field",
                "61:1": "home",
                "62:1": "home",
                "999:1": "home",
            },
            "regionAssignments": {},
            "intents": [],
        },
    )
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    recycled_force = plain(harness.brain.Overmind4ForcePlan)
    assert recycled_force["epoch"] == 2
    assert recycled_force["assignments"]["field"] == ["60:2"]
    assert all(
        len(recycled_force["assignments"][bucket]) == 0
        for bucket in ("home", "garrison", "response", "raider")
    )
    exported_generations = harness.brain.Overmind4EntityGenerations
    assert len(plain(exported_generations)) == 1
    assert _same_lua_reference(harness, exported_generations[60].reference, recycled)
    assert exported_generations[60].generation == 2


def test_unsupported_controller_still_initializes_isolated_empty_observer_snapshots() -> None:
    first = make_harness()
    first_force = first.brain.Overmind4ForcePlan
    first_generations = first.brain.Overmind4EntityGenerations
    first.brain.faction = 2

    unsupported = first.lua.globals().Controller.Create(first.brain)

    assert unsupported.unsupported is True
    unsupported_force = plain(first.brain.Overmind4ForcePlan)
    assert unsupported_force["epoch"] == 0
    assert set(unsupported_force["assignments"]) == {
        "home", "garrison", "field", "response", "raider"
    }
    assert all(
        len(tokens) == 0
        for tokens in unsupported_force["assignments"].values()
    )
    assert plain(first.brain.Overmind4EntityGenerations) == {}
    assert not _same_lua_reference(
        first, first.brain.Overmind4ForcePlan, first_force
    )
    assert not _same_lua_reference(
        first, first.brain.Overmind4EntityGenerations, first_generations
    )


def test_observation_uses_bounded_remote_radar_and_scout_sensor_anchors() -> None:
    harness = make_harness()
    radar = harness.unit(
        entityId=10,
        blueprintId="ueb3101",
        position=[300, 2, 300],
        blueprintIntel={"RadarRadius": 90, "VisionRadius": 10},
    )
    scout = harness.unit(
        entityId=11,
        blueprintId="uea0101",
        position=[500, 20, 500],
        blueprintIntel={"VisionRadius": 45},
    )
    harness.brain.units = harness.lua.table_from([radar, scout])

    harness.observe()

    queries = [plain(harness.calls.enemy[index]) for index in range(1, len(harness.calls.enemy) + 1)]
    assert ["MOBILE", [10, 10.2, 20], 65, "Enemy"] in queries
    assert ["ALLUNITS", [300, 2, 300], 90, "Enemy"] in queries
    assert ["ALLUNITS", [500, 20, 500], 45, "Enemy"] in queries
    assert len(queries) <= 9


def test_visual_enemy_roles_use_faction_neutral_blueprint_categories_while_radar_stays_unknown() -> None:
    harness = make_harness()
    bomber = harness.unit(
        entityId=30,
        blueprintId="uea0103",
        position=[10, 20, 20],
    )
    aeon_engineer = harness.unit(
        entityId=90,
        blueprintId="ual0105",
        blueprintCategories=["MOBILE", "LAND", "ENGINEER", "TECH1"],
        army=2,
        position=[40, 2, 40],
        seenNow=True,
        onRadar=True,
    )
    seraphim_mex = harness.unit(
        entityId=91,
        blueprintId="xsb1103",
        blueprintCategories=["STRUCTURE", "MASSEXTRACTION", "TECH1"],
        army=2,
        position=[50, 2, 50],
        seenNow=True,
        onRadar=True,
    )
    cybran_radar_only_engineer = harness.unit(
        entityId=92,
        blueprintId="url0105",
        blueprintCategories=["MOBILE", "LAND", "ENGINEER", "TECH1"],
        army=2,
        position=[60, 2, 60],
        seenNow=False,
        onRadar=True,
    )
    aeon_factory = harness.unit(
        entityId=93,
        blueprintId="uab0101",
        blueprintCategories=["STRUCTURE", "FACTORY", "LAND", "TECH1"],
        army=2,
        position=[70, 2, 70],
        seenNow=True,
        onRadar=True,
    )
    seraphim_static_aa = harness.unit(
        entityId=94,
        blueprintId="xsb2104",
        blueprintCategories=["STRUCTURE", "DEFENSE", "ANTIAIR", "TECH1"],
        army=2,
        position=[80, 2, 80],
        seenNow=True,
        onRadar=True,
    )
    harness.brain.units = harness.lua.table_from([bomber])
    harness.brain.enemies = harness.lua.table_from(
        [aeon_engineer, seraphim_mex, cybran_radar_only_engineer, aeon_factory, seraphim_static_aa]
    )

    observation = harness.observe()
    contacts = plain(observation.enemyObservations)
    roles = {(contact["source"], tuple(contact["position"])): contact["role"] for contact in contacts}

    assert roles[("vision", (40, 2, 40))] == "engineer"
    assert roles[("vision", (50, 2, 50))] == "mass_extractor"
    assert roles[("radar", (60, 2, 60))] == "unknown_mobile"
    assert roles[("vision", (70, 2, 70))] == "factory"
    assert roles[("vision", (80, 2, 80))] == "static_anti_air"

    engineer_contact = next(
        contact for contact in contacts if contact["position"] == [40, 2, 40]
    )
    execute_intents(
        harness,
        [
            {
                "kind": "bomber_raid",
                "actorToken": "30:1",
                "targetToken": engineer_contact["token"],
                "targetRole": "engineer",
                "position": [40, 2, 40],
            }
        ],
        observation,
    )
    assert len(harness.calls.aggressive) == 1


def test_idle_bomber_harasses_public_mass_route_without_visual_target() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    bomber = harness.unit(
        entityId=30,
        blueprintId="uea0103",
        position=[10, 20, 20],
    )
    harness.brain.units = harness.lua.table_from([bomber])
    public_sites = [plain(harness.controller.markers.mass[index]) for index in (1, 2)]
    _set_director_result(
        harness,
        "scoutPlan",
        {
            "nextObjectiveKey": public_sites[0]["key"],
            "objectiveKeys": [site["key"] for site in public_sites],
            "waypoints": [site["position"] for site in public_sites],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.clear) == 1
    assert len(harness.calls.aggressive) == 0
    assert [
        (plain(call.position)[0], plain(call.position)[2])
        for call in harness.calls.move.values()
    ] == [(site["position"][0], site["position"][2]) for site in public_sites]
    mission = plain(harness.controller.bomberMissions["30:1"])
    assert mission["publicHarass"] is True
    assert mission["objectiveKeys"] == [site["key"] for site in public_sites]


def test_persistent_radar_contact_becomes_a_scout_classification_objective() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/Intelligence.lua"))
    harness.lua.execute(
        "IntelligenceStub.UpdateMemory = Intelligence.UpdateMemory; "
        "local RealPlanScoutRoute = Intelligence.PlanScoutRoute; "
        "IntelligenceStub.PlanScoutRoute = function(snapshot) "
        "table.insert(calls.intelligencePlanScoutRoute, snapshot); "
        "return RealPlanScoutRoute(snapshot) end; "
        "Policy.Decide = function() return {} end"
    )
    radar_contact = harness.unit(
        entityId=90,
        blueprintId="uab0101",
        blueprintCategories=["STRUCTURE", "FACTORY", "LAND", "TECH1"],
        army=2,
        position=[180, 2, 180],
        seenNow=False,
        onRadar=True,
    )
    harness.brain.enemies = harness.lua.table_from([radar_contact])

    harness.lua.globals().Controller.Step(harness.controller)
    harness.brain.tick = 40
    scout = harness.unit(entityId=30, blueprintId="uea0101", position=[10, 20, 20])
    harness.brain.units = harness.lua.table_from([scout])
    harness.lua.globals().Controller.Step(harness.controller)

    classification = [
        objective
        for objective in plain(harness.calls.intelligencePlanScoutRoute[2])["objectives"]
        if objective["key"].startswith("intel:")
    ]
    assert len(classification) == 1
    assert classification[0]["position"] == [180, 2, 180]
    assert any(
        plain(call.position)[0] == 180 and plain(call.position)[2] == 180
        for call in harness.calls.patrol.values()
    )


def test_three_scouts_receive_disjoint_public_route_sectors() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    scouts = [
        harness.unit(entityId=30 + index, blueprintId="uea0101", position=[10, 20, 20])
        for index in range(3)
    ]
    harness.brain.units = harness.lua.table_from(scouts)
    public_sites = [plain(harness.controller.markers.mass[index]) for index in range(1, 4)]
    _set_director_result(
        harness,
        "scoutPlan",
        {
            "nextObjectiveKey": public_sites[0]["key"],
            "objectiveKeys": [site["key"] for site in public_sites],
            "waypoints": [site["position"] for site in public_sites],
        },
    )

    for tick in range(3):
        harness.brain.tick = tick
        harness.lua.globals().Controller.Step(harness.controller)

    routes = {}
    for call in harness.calls.patrol.values():
        token = f"{call.units[1].options.entityId}:1"
        routes.setdefault(token, set()).add(
            (plain(call.position)[0], plain(call.position)[2])
        )
    assert set(routes) == {"30:1", "31:1", "32:1"}
    assert all(len(route) == 1 for route in routes.values())
    assert set.union(*routes.values()) == {
        (site["position"][0], site["position"][2]) for site in public_sites
    }


def test_scout_partition_uses_luaplus_compatible_modulo() -> None:
    assert "(index - 1) % 3" not in source("lua/AI/Overmind4/Controller.lua")


def test_scout_input_targets_enemy_spawn_and_ignores_owned_or_unoccupied_points() -> None:
    harness = make_harness()
    near_site = plain(harness.controller.markers.mass[1])
    own_mex = harness.unit(
        entityId=70,
        blueprintId="ueb1103",
        position=near_site["position"],
    )
    harness.brain.units = harness.lua.table_from([own_mex])

    harness.lua.globals().Controller.Step(harness.controller)

    objectives = plain(harness.calls.intelligencePlanScoutRoute[1])["objectives"]
    by_key = {objective["key"]: objective for objective in objectives}
    assert "spawn:ARMY_2" in by_key
    assert by_key["spawn:ARMY_2"]["strategic"] is True
    assert "spawn:ARMY_1" not in by_key
    assert "spawn:ARMY_3" not in by_key
    assert near_site["key"] not in by_key


def test_visual_mex_preempts_an_active_public_bomber_harass_route() -> None:
    harness = make_harness()
    bomber = harness.unit(
        entityId=30,
        blueprintId="uea0103",
        position=[10, 20, 20],
    )
    enemy_mex = harness.unit(
        entityId=90,
        blueprintId="ueb1103",
        blueprintCategories=["STRUCTURE", "MASSEXTRACTION", "TECH1"],
        army=2,
        position=[80, 2, 80],
        seenNow=True,
        onRadar=True,
    )
    harness.brain.units = harness.lua.table_from([bomber])
    harness.brain.enemies = harness.lua.table_from([enemy_mex])
    harness.controller.bomberMissions["30:1"] = lua_value(
        harness.lua,
        {
            "bomberToken": "30:1",
            "publicHarass": True,
            "objectiveKeys": [plain(harness.controller.markers.mass[1])["key"]],
            "issuedTick": 0,
        },
    )
    harness.lua.execute(
        "IntelligenceStub.SelectBomberTarget = function() return { "
        "targetToken = '90:1', targetRole = 'mass_extractor', "
        "position = { 80, 2, 80 } } end"
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.clear) == 1
    assert len(harness.calls.aggressive) == 1
    assert plain(harness.calls.aggressive[1].position) == [80, 2, 80]
    mission = plain(harness.controller.bomberMissions["30:1"])
    assert mission["targetToken"] == "90:1"
    assert mission.get("publicHarass") is not True


def test_idle_bomber_attacks_recently_scouted_mex_after_vision_is_lost() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/Intelligence.lua"))
    harness.lua.execute(
        "IntelligenceStub.UpdateMemory = Intelligence.UpdateMemory"
    )
    harness.lua.execute("Policy.Decide = function() return {} end")
    bomber = harness.unit(
        entityId=30,
        blueprintId="uea0103",
        position=[10, 20, 20],
    )
    harness.brain.units = harness.lua.table_from([bomber])
    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 100
    harness.controller.intelState = lua_value(
        harness.lua,
        {
            "epoch": 1,
            "threat": {},
            "expansionSafety": {},
            "contacts": {
                "90:1": {
                    "token": "90:1",
                    "role": "mass_extractor_t2",
                    "position": [80, 2, 80],
                    "source": "vision",
                    "currentlyVisual": False,
                    "current": False,
                    "lastSeenTick": 50,
                }
            },
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.clear) == 1
    assert len(harness.calls.aggressive) == 1
    raid_position = plain(harness.calls.aggressive[1].position)
    assert [raid_position[0], raid_position[2]] == [80, 80]
    mission = plain(harness.controller.bomberMissions["30:1"])
    assert mission["targetToken"] == "90:1"
    assert mission["rememberedRaid"] is True


def test_idle_bomber_avoids_recently_scouted_mex_under_remembered_aa() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/Intelligence.lua"))
    harness.lua.execute("IntelligenceStub.UpdateMemory = Intelligence.UpdateMemory")
    harness.lua.execute("Policy.Decide = function() return {} end")
    bomber = harness.unit(entityId=30, blueprintId="uea0103", position=[10, 20, 20])
    harness.brain.units = harness.lua.table_from([bomber])
    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 100
    harness.controller.intelState = lua_value(
        harness.lua,
        {
            "epoch": 1,
            "threat": {},
            "expansionSafety": {},
            "contacts": {
                "90:1": {
                    "token": "90:1", "role": "mass_extractor_t2",
                    "position": [80, 2, 80], "source": "vision",
                    "currentlyVisual": False, "current": False, "lastSeenTick": 50,
                },
                "91:1": {
                    "token": "91:1", "role": "static_anti_air",
                    "position": [90, 2, 80], "source": "vision",
                    "currentlyVisual": False, "current": False, "lastSeenTick": 50,
                },
            },
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.aggressive) == 0


def test_recent_scout_contact_defers_unescorted_mex_until_intelligence_expires() -> None:
    harness = make_harness()
    _use_real_macro_expansion_and_job_ledger(harness)
    harness.lua.execute(source("lua/AI/Overmind4/Intelligence.lua"))
    harness.lua.execute(
        "IntelligenceStub.UpdateMemory = Intelligence.UpdateMemory; "
        "MacroDirectorStub.ClusterRegions = MacroDirector.ClusterRegions; "
        "MacroDirectorStub.AdvanceRegion = MacroDirector.AdvanceRegion"
    )
    harness.lua.execute("Policy.Decide = function() return {} end")
    site = plain(harness.controller.markers.mass[1])
    harness.controller.markers.mass = lua_value(harness.lua, [site])
    engineer = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
    )
    enemy_tank = harness.unit(
        entityId=90,
        blueprintId="uel0201",
        army=2,
        position=site["position"],
        seenNow=True,
        onRadar=True,
    )
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.enemies = harness.lua.table_from([enemy_tank])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)
    assert not any(
        call.blueprintId == "ueb1103" for call in harness.calls.buildMobile.values()
    )
    safety = plain(harness.controller.intelState)["expansionSafety"]
    assert set(safety.values()) == {"contested"}

    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 100
    harness.lua.globals().Controller.Step(harness.controller)
    assert not any(
        call.blueprintId == "ueb1103" for call in harness.calls.buildMobile.values()
    )

    harness.brain.tick = 601
    harness.lua.globals().Controller.Step(harness.controller)
    assert sum(
        call.blueprintId == "ueb1103" for call in harness.calls.buildMobile.values()
    ) == 1


def test_interceptors_leave_base_to_engage_visible_air_and_return_after_contact() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    interceptors = [
        harness.unit(
            entityId=100 + index,
            blueprintId="uea0102",
            position=[10 + index, 20, 20],
        )
        for index in range(10)
    ]
    enemy_scout = harness.unit(
        entityId=200,
        blueprintId="uea0101",
        army=2,
        position=[80, 30, 80],
        seenNow=True,
        onRadar=True,
    )
    enemy_fighter = harness.unit(
        entityId=201,
        blueprintId="uea0102",
        army=2,
        position=[70, 30, 70],
        seenNow=True,
        onRadar=True,
    )
    harness.brain.units = harness.lua.table_from(interceptors)
    harness.brain.enemies = harness.lua.table_from([enemy_scout, enemy_fighter])

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.clear) == 1
    assert len(harness.calls.aggressive) == 1
    intercept_position = plain(harness.calls.aggressive[1].position)
    assert [intercept_position[0], intercept_position[2]] == [70, 70]
    mission = plain(harness.controller.airInterceptMission)
    assert mission["targetToken"] == "201:1"
    assert len(mission["actorTokens"]) == 8

    harness.brain.enemies = harness.lua.table_from([])
    harness.brain.tick = 120
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.clear) == 2
    assert len(harness.calls.patrol) == 1
    assert harness.controller.airInterceptMission is None


def test_low_fuel_interceptor_loads_into_live_air_staging_before_new_missions() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    interceptor = harness.unit(
        entityId=100,
        blueprintId="uea0102",
        position=[30, 20, 30],
        fuelRatio=0.15,
    )
    staging = harness.unit(
        entityId=200,
        blueprintId="ueb5202",
        position=[20, 2, 20],
        hasTransportSpace=True,
    )
    harness.brain.units = harness.lua.table_from([interceptor, staging])

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.transportLoad) == 1
    assert _same_lua_reference(
        harness, harness.calls.transportLoad[1].units[1], interceptor
    )
    assert _same_lua_reference(
        harness, harness.calls.transportLoad[1].transport, staging
    )
    assert plain(harness.controller.airRefuelMissions)["100:1"]["stagingToken"] == "200:1"


def test_public_bomber_harass_releases_after_route_and_reissues_without_churn() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    bomber = harness.unit(
        entityId=30,
        blueprintId="uea0103",
        position=[10, 20, 20],
    )
    harness.brain.units = harness.lua.table_from([bomber])
    site = plain(harness.controller.markers.mass[1])
    _set_director_result(
        harness,
        "scoutPlan",
        {
            "nextObjectiveKey": site["key"],
            "objectiveKeys": [site["key"]],
            "waypoints": [site["position"]],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)
    bomber.options.idleState = False
    harness.brain.tick = 9
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.move) == 1

    bomber.options.idleState = True
    harness.brain.tick = 18
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.move) == 2


def test_step_default_merge_adapts_every_planner_output_once_and_persists_lifecycle() -> None:
    harness = make_harness()
    harness.controller.crossMapOffenseEnabled = False
    expansion_engineer = harness.unit(
        entityId=10,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
    )
    package_engineer = harness.unit(
        entityId=11,
        blueprintId="uel0105",
        position=[11, 2, 20],
        canBuild={"ueb2101": True},
    )
    reclaim_engineer = harness.unit(
        entityId=12,
        blueprintId="uel0105",
        position=[12, 2, 20],
        blueprintIntel={"VisionRadius": 10},
    )
    radar_engineer = harness.unit(
        entityId=14,
        blueprintId="uel0105",
        position=[14, 2, 20],
        canBuild={"ueb3101": True},
    )
    tech_factory = harness.unit(
        entityId=20,
        blueprintId="ueb0101",
        position=[10, 2, 22],
        canBuild={"ueb0201": True},
    )
    scout = harness.unit(
        entityId=30,
        blueprintId="uea0101",
        position=[10, 20, 20],
    )
    air_factory = harness.unit(
        entityId=40,
        blueprintId="ueb0102",
        position=[12, 2, 22],
        canBuild={"uea0102": True},
    )
    transport = harness.unit(
        entityId=50,
        blueprintId="uea0107",
        position=[14, 20, 20],
        cargo=[],
    )
    cargo_engineer = harness.unit(
        entityId=51,
        blueprintId="uel0105",
        position=[14, 2, 20],
    )
    responder = harness.unit(
        entityId=60,
        blueprintId="uel0201",
        position=[16, 2, 20],
    )
    harness.brain.units = harness.lua.table_from(
        [
            expansion_engineer,
            package_engineer,
            reclaim_engineer,
            radar_engineer,
            tech_factory,
            scout,
            air_factory,
            transport,
            cargo_engineer,
            responder,
        ]
    )
    reclaim_prop = harness.lua.globals().MakeProp(
        lua_value(
            harness.lua,
            {
                "entityId": 501,
                "position": [13, 2, 20],
                "cachePosition": [13, 2, 20],
                "mass": 500,
            },
        )
    )
    harness.brain.reclaimables = harness.lua.table_from([reclaim_prop])
    harness.brain.energyTrend = 180
    harness.brain.energyIncome = 200
    harness.brain.energyUsage = 20
    harness.brain.energyRequested = 20
    harness.brain.energyStored = 10000
    harness.brain.energyStoredRatio = 0.9
    harness.brain.massTrend = 18
    harness.brain.massIncome = 20
    harness.brain.massUsage = 2
    harness.brain.massRequested = 2
    harness.brain.massStored = 1000
    harness.brain.massStoredRatio = 0.9

    near_site = plain(harness.controller.markers.mass[1])
    home_position = plain(harness.controller.basePosition)
    expansion_job = {
        "id": "mex:front:1",
        "kind": "build_mex",
        "actorToken": "10:1",
        "targetKey": near_site["key"],
        "regionKey": "front",
        "position": near_site["position"],
        "estimatedTravelTicks": 30,
    }
    region = {
        "key": "front",
        "state": "establishing",
        "position": [100, 2, 100],
    }
    _set_director_result(
        harness,
        "expansionPlan",
        {"jobs": [expansion_job], "denials": []},
    )
    _set_director_result(
        harness,
        "regionPackagePlan",
        {
            "requiredRoles": ["point_defense"],
            "garrisonMinimum": 4,
            "garrisonAntiAirMinimum": 1,
            "persistent": True,
        },
    )
    _set_director_result(
        harness,
        "reclaimPlan",
        {
            "jobs": [
                {
                    "id": "reclaim:prop:501",
                    "kind": "reclaim",
                    "actorToken": "12:1",
                    "targetKey": "prop:501",
                    "regionKey": "home",
                    "requiresLiveVisionRevalidation": True,
                }
            ]
        },
    )
    _set_director_result(
        harness,
        "techPlan",
        {
            "hqAction": "start_t2",
            "hqSourceToken": "20:1",
            "remainingT1ProductionLanes": 1,
            "t2ProductionRoles": ["t2_direct_fire", "t2_anti_air"],
        },
    )
    _set_director_result(
        harness,
        "scoutPlan",
        {
            "objectiveKeys": [near_site["key"]],
            "nextObjectiveKey": near_site["key"],
            "waypoints": [near_site["position"]],
            "coverageAgeTicks": {near_site["key"]: 3000},
        },
    )
    _set_director_result(
        harness,
        "airPlan",
        {"orders": [{"buildRole": "interceptor"}]},
    )
    _set_director_result(
        harness,
        "transportPlan",
        {
            "mode": "airlift",
            "missionId": "airlift:front",
            "state": "planned",
            "siteKey": "remote-safe",
            "transportToken": "50:1",
            "cargoTokens": ["51:1"],
            "dropPosition": [300, 303, 300],
            "dropTolerance": 20,
            "retryCount": 0,
        },
    )
    _set_director_result(
        harness,
        "radarIntents",
        [
            {
                "kind": "build_structure",
                "actorToken": "14:1",
                "buildRole": "radar",
                "regionKey": "front",
                "position": [104, 2, 100],
                "reason": "establish_region_radar",
                "priority": 2,
            }
        ],
    )

    def set_state_epoch(epoch: int) -> None:
        _set_director_result(
            harness,
            "intelState",
            {
                "epoch": epoch,
                "contacts": {},
                "threat": {"home": 1, "air": 0},
                "expansionSafety": {"front": "safe"},
            },
        )
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": True,
                "epoch": epoch,
                "lanes": {"mex_rebuild": {"admitted": True}},
                "regions": [region],
                "intents": [],
            },
        )
        _set_director_result(
            harness,
            "jobLedger",
            {
                "epoch": epoch,
                "jobs": {
                    expansion_job["id"]: {
                        **expansion_job,
                        "phase": "travelling",
                        "deadlineTick": 600,
                    }
                },
            },
        )
        force_state = {
            "epoch": epoch,
            "assignments": {
                "home": [],
                "garrison": [],
                "field": [],
                "response": ["60:1"],
                "raider": [],
                "unassigned": [],
            },
            "ownershipByToken": {"60:1": "response"},
        }
        _set_director_result(harness, "forcePlan", force_state)
        _set_director_result(
            harness,
            "homeBreachPlan",
            {
                **force_state,
                "responseIntent": {
                    "actorTokens": ["60:1"],
                    "position": home_position,
                    "priority": "immediate_home_breach",
                },
            },
        )

    set_state_epoch(1)
    harness.lua.globals().Controller.Step(harness.controller)

    planners = {
        "expansion": harness.calls.macroPlanExpansion,
        "package": harness.calls.macroPlanRegionPackage,
        "reclaim": harness.calls.macroPlanReclaim,
        "tech": harness.calls.macroPlanTech,
        "scout": harness.calls.intelligencePlanScoutRoute,
        "radar": harness.calls.intelligencePlanRadar,
        "air": harness.calls.intelligencePlanAir,
        "transport": harness.calls.intelligencePlanTransport,
        "home-breach": harness.calls.forceHandleHomeBreach,
    }
    assert {name: len(calls) for name, calls in planners.items()} == {
        name: 1 for name in planners
    }
    first_new_jobs = plain(harness.calls.macroUpdateJobLedger[1].snapshot)[
        "newJobs"
    ]
    assert len(first_new_jobs) == 1
    assert {
        key: first_new_jobs[0][key]
        for key in ("id", "actorToken", "targetKey", "regionKey")
    } == {
        key: expansion_job[key]
        for key in ("id", "actorToken", "targetKey", "regionKey")
    }

    assert len(harness.calls.buildMobile) == 2
    structure_builds = {
        call.blueprintId: {
            "actor": call.units[1].options.entityId,
            "position": plain(call.position),
        }
        for call in harness.calls.buildMobile.values()
    }
    assert structure_builds == {
        "ueb2101": {"actor": 11, "position": [100, 101, 100]},
        "ueb3101": {"actor": 14, "position": [104, 105, 100]},
    }
    assert len(harness.calls.reclaim) == 1
    assert harness.calls.reclaim[1].units[1].options.entityId == 12
    assert harness.calls.reclaim[1].target.EntityId == 501
    assert len(harness.calls.upgrade) == 1
    assert harness.calls.upgrade[1].units[1].options.entityId == 20
    assert harness.calls.upgrade[1].blueprintId == "ueb0201"
    assert len(harness.calls.patrol) == 1
    assert harness.calls.patrol[1].units[1].options.entityId == 30
    assert plain(harness.calls.patrol[1].position) == [12, 12.2, 20]
    assert len(harness.calls.buildFactory) == 1
    assert harness.calls.buildFactory[1].units[1].options.entityId == 40
    assert harness.calls.buildFactory[1].blueprintId == "uea0102"
    assert harness.calls.buildFactory[1].count == 1
    assert len(harness.calls.transportLoad) == 1
    assert harness.calls.transportLoad[1].transport.options.entityId == 50
    assert harness.calls.transportLoad[1].units[1].options.entityId == 51
    assert len(harness.calls.move) == 1
    assert harness.calls.move[1].units[1].options.entityId == 60
    assert plain(harness.calls.move[1].position) == home_position
    assert sorted(
        call.units[1].options.entityId for call in harness.calls.clear.values()
    ) == [30, 60]
    for calls in (
        harness.calls.aggressive,
        harness.calls.guard,
        harness.calls.rally,
        harness.calls.transportUnload,
    ):
        assert len(calls) == 0

    pending = plain(harness.controller.pending)
    assert pending["11:1"]["buildRole"] == "point_defense"
    assert pending["14:1"]["buildRole"] == "radar"
    assert pending["12:1"]["kind"] == "reclaim"
    assert pending["20:1"]["kind"] == "factory_upgrade"
    assert pending["40:1"]["kind"] == "factory_build"
    assert harness.controller.reclaimReservations["prop:501"] == "12:1"
    assert harness.controller.airScoutAssignments["30:1"] is True
    assert plain(harness.controller.transportMissions["airlift:front"])["state"] == "loading"
    assert plain(harness.controller.forcePlan)["ownershipByToken"]["60:1"] == "response"

    first_order_counts = {
        "build": len(harness.calls.buildMobile),
        "reclaim": len(harness.calls.reclaim),
        "upgrade": len(harness.calls.upgrade),
        "patrol": len(harness.calls.patrol),
        "production": len(harness.calls.buildFactory),
        "load": len(harness.calls.transportLoad),
        "response": len(harness.calls.move),
        "clear": len(harness.calls.clear),
    }
    set_state_epoch(2)
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    assert {name: len(calls) for name, calls in planners.items()} == {
        name: 2 for name in planners
    }
    second_new_jobs = plain(harness.calls.macroUpdateJobLedger[2].snapshot)[
        "newJobs"
    ]
    assert len(second_new_jobs) == 0
    assert {
        "build": len(harness.calls.buildMobile),
        "reclaim": len(harness.calls.reclaim),
        "upgrade": len(harness.calls.upgrade),
        "patrol": len(harness.calls.patrol),
        "production": len(harness.calls.buildFactory),
        "load": len(harness.calls.transportLoad),
        "response": len(harness.calls.move),
        "clear": len(harness.calls.clear),
    } == first_order_counts
    assert len(harness.calls.transportUnload) == 1
    unload = harness.calls.transportUnload[1]
    assert unload.transports[1].options.entityId == 50
    assert plain(unload.position) == [300, 303, 300]
    assert plain(harness.controller.transportMissions["airlift:front"])["state"] == "unloading"
    second_pending = plain(harness.controller.pending)
    assert set(second_pending) >= {"11:1", "12:1", "14:1", "20:1", "40:1"}
    assert harness.controller.reclaimReservations["prop:501"] == "12:1"
    assert harness.controller.airScoutAssignments["30:1"] is True
    assert plain(harness.controller.forcePlan)["ownershipByToken"]["60:1"] == "response"

    assert plain(harness.calls.intelligenceUpdateMemory[2].previous)["epoch"] == 1
    assert plain(harness.calls.macroUpdateJobLedger[2].ledger)["epoch"] == 1
    assert plain(harness.calls.macroBuildPortfolio[2])["previousMacroPlan"]["epoch"] == 1
    second_transport_snapshot = plain(harness.calls.intelligencePlanTransport[2])
    assert second_transport_snapshot["transportMissions"]["airlift:front"]["state"] == "loading"
    assert any(
        plain(call.plan).get("epoch") == 1
        for call in harness.calls.forceReconcile.values()
    )

    set_state_epoch(3)
    harness.brain.tick = 2
    harness.lua.globals().Controller.Step(harness.controller)

    assert {name: len(calls) for name, calls in planners.items()} == {
        name: 3 for name in planners
    }
    assert len(
        plain(harness.calls.macroUpdateJobLedger[3].snapshot)["newJobs"]
    ) == 0
    assert {
        "build": len(harness.calls.buildMobile),
        "reclaim": len(harness.calls.reclaim),
        "upgrade": len(harness.calls.upgrade),
        "patrol": len(harness.calls.patrol),
        "production": len(harness.calls.buildFactory),
        "load": len(harness.calls.transportLoad),
        "response": len(harness.calls.move),
        "clear": len(harness.calls.clear),
    } == first_order_counts
    assert len(harness.calls.transportUnload) == 1
    assert plain(harness.controller.intelState)["epoch"] == 3
    assert plain(harness.controller.macroPlan)["epoch"] == 3
    assert plain(harness.controller.jobLedger)["epoch"] == 3
    assert plain(harness.controller.forcePlan)["epoch"] == 3
    assert harness.controller.transportMissions["airlift:front"] is None
    transport_events = [
        plain(call.event)
        for call in harness.calls.intelligenceAdvanceTransport.values()
    ]
    assert [event["kind"] for event in transport_events] == [
        "load_ordered",
        "observed",
        "unload_ordered",
        "observed",
    ]
    assert transport_events[1]["attachedCargoTokens"] == ["51:1"]
    assert len(transport_events[3]["attachedCargoTokens"]) == 0
    assert [
        event["phase"] for event in _operation_events(harness, "airlift:front")
    ] == [
        "opportunity",
        "selected",
        "admitted",
        "ordered",
        "progressing",
        "completed",
    ]
    _assert_operation_stream_clean(harness)

def test_step_turns_macro_targets_and_t2_roles_into_exact_growth_orders_once() -> None:
    harness = make_harness()
    harness.controller.crossMapOffenseEnabled = False
    land_builder = harness.unit(
        entityId=10,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb0101": True},
    )
    air_builder = harness.unit(
        entityId=11,
        blueprintId="uel0105",
        position=[11, 2, 20],
        canBuild={"ueb0102": True},
    )
    t1_factory = harness.unit(
        entityId=20,
        blueprintId="ueb0101",
        position=[10, 2, 22],
        canBuild={"uel0105": True},
    )
    t2_direct_factory = harness.unit(
        entityId=21,
        blueprintId="ueb0201",
        position=[12, 2, 22],
        canBuild={"uel0202": True},
    )
    t2_aa_factory = harness.unit(
        entityId=22,
        blueprintId="ueb0201",
        position=[14, 2, 22],
        canBuild={"uel0205": True},
    )
    harness.brain.units = harness.lua.table_from(
        [
            land_builder,
            air_builder,
            t1_factory,
            t2_direct_factory,
            t2_aa_factory,
        ]
    )
    _set_starved_economy(harness)

    def set_epoch(epoch: int, *, grow: bool) -> None:
        _set_director_result(
            harness,
            "intelState",
            {
                "epoch": epoch,
                "contacts": {},
                "threat": {"home": 0, "air": 0},
                "expansionSafety": {},
            },
        )
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": True,
                "epoch": epoch,
                "engineerTarget": 3 if grow else 2,
                "factoryTarget": 5 if grow else 3,
                "landFactoryTarget": 4 if grow else 3,
                "airFactoryTarget": 1 if grow else 0,
                "lanes": {
                    "engineers": {"admitted": grow},
                    "factory_growth": {"admitted": grow},
                    "land_production": {"admitted": grow},
                },
                "regions": [],
                "intents": [],
            },
        )
        _set_director_result(
            harness,
            "jobLedger",
            {"epoch": epoch, "jobs": {}, "releasedActorTokens": []},
        )
        _set_director_result(
            harness,
            "techPlan",
            {
                "hqAction": "hold",
                "t2ProductionRoles": (
                    ["t2_direct_fire", "t2_anti_air"] if grow else []
                ),
            },
        )
        _set_director_result(
            harness,
            "forcePlan",
            {
                "epoch": epoch,
                "assignments": {
                    "home": [],
                    "garrison": [],
                    "field": [],
                    "response": [],
                    "raider": [],
                    "unassigned": [],
                },
                "ownershipByToken": {},
                "intents": [],
            },
        )

    # The same observed economy and units issue nothing while the funded
    # targets equal current capacity. This is the causal control for the
    # target increase below; the legacy Policy still runs through Step.
    set_epoch(1, grow=False)
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.buildMobile) == 0
    assert len(harness.calls.buildFactory) == 0

    set_epoch(2, grow=True)
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    structures = {
        call.blueprintId: call.units[1].options.entityId
        for call in harness.calls.buildMobile.values()
    }
    assert structures == {"ueb0101": 10, "ueb0102": 11}
    production = {
        call.units[1].options.entityId: (call.blueprintId, call.count)
        for call in harness.calls.buildFactory.values()
    }
    assert production == {
        20: ("uel0105", 1),
        21: ("uel0202", 1),
        22: ("uel0205", 1),
    }
    assert plain(harness.controller.macroPlan)["engineerTarget"] == 3
    assert plain(harness.controller.macroPlan)["factoryTarget"] == 5
    first_order_counts = (
        len(harness.calls.buildMobile),
        len(harness.calls.buildFactory),
    )

    set_epoch(3, grow=True)
    harness.brain.tick = 2
    harness.lua.globals().Controller.Step(harness.controller)

    assert (
        len(harness.calls.buildMobile),
        len(harness.calls.buildFactory),
    ) == first_order_counts
    assert set(plain(harness.controller.pending)) >= {
        "10:1",
        "11:1",
        "20:1",
        "21:1",
        "22:1",
    }
    assert plain(harness.calls.macroBuildPortfolio[3])["previousMacroPlan"][
        "epoch"
    ] == 2


def test_one_factory_grant_uses_idle_acu_for_first_air_before_third_land() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        canBuild={"ueb0102": True},
    )
    engineer = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        canBuild={"ueb0101": True, "ueb0102": True},
    )
    factories = [
        harness.unit(entityId=20 + index, blueprintId="ueb0101")
        for index in range(2)
    ]
    opening_economy = [
        *[
            harness.unit(entityId=30 + index, blueprintId="ueb1101")
            for index in range(4)
        ],
        *[
            harness.unit(entityId=40 + index, blueprintId="ueb1103")
            for index in range(4)
        ],
    ]
    harness.brain.units = harness.lua.table_from(
        [acu, engineer, *factories, *opening_economy]
    )
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "landFactoryTarget": 3,
            "airFactoryTarget": 1,
            "lanes": {"factory_growth": {"admitted": True}},
            "grants": [
                {
                    "requestId": "factory-1",
                    "lane": "factory_growth",
                    "source": "bank",
                }
            ],
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    order = harness.calls.buildMobile[1]
    assert order.blueprintId == "ueb0102"
    assert order.units[1].options.entityId == 1


def test_acu_second_land_factory_precedes_first_air_director_claim() -> None:
    harness = make_harness()
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        canBuild={"ueb0101": True, "ueb0102": True},
    )
    land = harness.unit(entityId=20, blueprintId="ueb0101")
    power = [
        harness.unit(entityId=30 + index, blueprintId="ueb1101")
        for index in range(2)
    ]
    mex = [
        harness.unit(entityId=40 + index, blueprintId="ueb1103")
        for index in range(4)
    ]
    harness.brain.units = harness.lua.table_from([acu, land, *power, *mex])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "landFactoryTarget": 2,
            "airFactoryTarget": 1,
            "lanes": {"factory_growth": {"admitted": False}},
            "grants": [],
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb0101"


def test_reclaiming_acu_builds_funded_second_air_when_field_engineers_are_busy() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        idleState=False,
        states={"Moving": True},
        canBuild={"ueb0102": True},
    )
    land_factories = [
        harness.unit(entityId=20 + index, blueprintId="ueb0101")
        for index in range(6)
    ]
    air_factory = harness.unit(entityId=30, blueprintId="ueb0102")
    busy_engineers = [
        harness.unit(
            entityId=40 + index,
            blueprintId="uel0105",
            idleState=False,
            states={"Moving": True},
        )
        for index in range(8)
    ]
    harness.brain.units = harness.lua.table_from(
        [acu, *land_factories, air_factory, *busy_engineers]
    )
    harness.controller.reclaimPatrolAssignments["1:1"] = True
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "landFactoryTarget": 6,
            "airFactoryTarget": 4,
            "lanes": {"factory_growth": {"admitted": True}},
            "grants": [
                {
                    "requestId": "factory-1",
                    "lane": "factory_growth",
                    "source": "bank",
                }
            ],
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    order = harness.calls.buildMobile[1]
    assert order.blueprintId == "ueb0102"
    assert order.units[1].options.entityId == 1
    assert harness.controller.reclaimPatrolAssignments["1:1"] is None


def test_single_factory_grant_fills_larger_air_deficit_before_more_land() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    engineer = harness.unit(
        entityId=10,
        blueprintId="uel0105",
        canBuild={"ueb0101": True, "ueb0102": True},
    )
    land = [
        harness.unit(entityId=20 + index, blueprintId="ueb0101")
        for index in range(3)
    ]
    air = harness.unit(entityId=30, blueprintId="ueb0102")
    power = [
        harness.unit(entityId=40 + index, blueprintId="ueb1101")
        for index in range(12)
    ]
    harness.brain.units = harness.lua.table_from([engineer, *land, air, *power])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "landFactoryTarget": 6,
            "airFactoryTarget": 3,
            "lanes": {"factory_growth": {"admitted": True}},
            "grants": [
                {
                    "requestId": "factory-1",
                    "lane": "factory_growth",
                    "source": "bank",
                }
            ],
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb0102"


def test_factory_director_cannot_take_acu_while_power_target_is_unmet() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        canBuild={"ueb0102": True},
    )
    land_factories = [
        harness.unit(entityId=20 + index, blueprintId="ueb0101")
        for index in range(4)
    ]
    air_factories = [
        harness.unit(entityId=30 + index, blueprintId="ueb0102")
        for index in range(2)
    ]
    power = [
        harness.unit(entityId=40 + index, blueprintId="ueb1101")
        for index in range(10)
    ]
    mex = [
        harness.unit(entityId=60 + index, blueprintId="ueb1103")
        for index in range(17)
    ]
    harness.brain.units = harness.lua.table_from(
        [acu, *land_factories, *air_factories, *power, *mex]
    )
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "landFactoryTarget": 9,
            "airFactoryTarget": 3,
            "lanes": {"factory_growth": {"admitted": True}},
            "grants": [
                {
                    "requestId": "factory-1",
                    "lane": "factory_growth",
                    "source": "bank",
                }
            ],
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 0


@pytest.mark.parametrize(
    ("power_count", "has_hydro", "expected_orders"),
    [
        (1, True, 0),
        (2, False, 1),
        (2, True, 1),
    ],
)
def test_acu_first_air_starts_after_two_generators_with_or_without_hydro(
    power_count: int,
    has_hydro: bool,
    expected_orders: int,
) -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        canBuild={"ueb0102": True},
    )
    land_factory = harness.unit(entityId=20, blueprintId="ueb0101")
    power = [
        harness.unit(entityId=30 + index, blueprintId="ueb1101")
        for index in range(power_count)
    ]
    mexes = [
        harness.unit(entityId=40 + index, blueprintId="ueb1103")
        for index in range(4)
    ]
    hydro = [harness.unit(entityId=50, blueprintId="ueb1102")] if has_hydro else []
    harness.brain.units = harness.lua.table_from(
        [acu, land_factory, *power, *mexes, *hydro]
    )
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "landFactoryTarget": 1,
            "airFactoryTarget": 1,
            "lanes": {"factory_growth": {"admitted": True}},
            "grants": [
                {
                    "requestId": "factory-1",
                    "lane": "factory_growth",
                    "source": "bank",
                }
            ],
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == expected_orders
    if expected_orders:
        order = harness.calls.buildMobile[1]
        assert order.blueprintId == "ueb0102"
        assert order.units[1].options.entityId == 1


def test_acu_starts_first_air_after_two_power_and_local_mex() -> None:
    harness = make_harness()
    mass_positions = [[12 + index * 4, 2, 20] for index in range(4)]
    harness.controller.markers.mass = lua_value(
        harness.lua,
        [
            {
                "key": f"Mass:local:{index}",
                "name": f"Local {index}",
                "kind": "mass",
                "position": position,
                "distance": 2 + index * 4,
                "localSite": True,
                "reachable": True,
                "engineerReachable": True,
                "landReachable": True,
            }
            for index, position in enumerate(mass_positions)
        ],
    )
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        canBuild={"ueb0102": True, "ueb1101": True, "ueb1103": True},
    )
    land_factory = harness.unit(entityId=20, blueprintId="ueb0101")
    opening_economy = [
        *[
            harness.unit(
                entityId=30 + index,
                blueprintId="ueb1101",
                position=[4 + index * 4, 2, 34],
            )
            for index in range(2)
        ],
        *[
            harness.unit(
                entityId=40 + index,
                blueprintId="ueb1103",
                position=mass_positions[index],
            )
            for index in range(4)
        ],
    ]
    harness.brain.units = harness.lua.table_from(
        [acu, land_factory, *opening_economy]
    )
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "landFactoryTarget": 1,
            "airFactoryTarget": 1,
            "lanes": {
                "energy_recovery": {"admitted": True},
                "factory_growth": {"admitted": False},
            },
            "grants": [
                {
                    "requestId": "energy-1",
                    "lane": "energy_recovery",
                    "source": "bank",
                },
            ],
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    order = harness.calls.buildMobile[1]
    assert order.blueprintId == "ueb0102"
    assert order.units[1].options.entityId == 1


def test_acu_completes_first_land_factory_before_starting_first_air() -> None:
    harness = make_harness()
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        canBuild={"ueb0101": True, "ueb0102": True},
    )
    harness.brain.units = harness.lua.table_from([acu])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "landFactoryTarget": 1,
            "airFactoryTarget": 1,
            "lanes": {"factory_growth": {"admitted": True}},
            "grants": [
                {
                    "requestId": "factory-1",
                    "lane": "factory_growth",
                    "source": "bank",
                }
            ],
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb0101"


def test_single_t2_lane_uses_completed_and_pending_deficits_to_build_tank_then_aa() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    factory = harness.unit(
        entityId=20,
        blueprintId="ueb0201",
        position=[10, 2, 22],
        canBuild={"uel0202": True, "uel0205": True},
    )
    harness.brain.units = harness.lua.table_from([factory])
    macro_plan = {
        "valid": True,
        "epoch": 1,
        "lanes": {"land_production": {"admitted": True}},
        "grants": [
            {
                "requestId": "land-production-1",
                "lane": "land_production",
                "source": "recurring",
            }
        ],
        "regions": [],
        "intents": [],
    }
    _set_director_result(harness, "macroPlan", macro_plan)
    _set_director_result(
        harness,
        "techPlan",
        {"t2ProductionRoles": ["t2_direct_fire", "t2_anti_air"]},
    )

    harness.lua.globals().Controller.Step(harness.controller)
    assert [call.blueprintId for call in harness.calls.buildFactory.values()] == [
        "uel0202"
    ]

    tank = harness.unit(
        entityId=21,
        blueprintId="uel0202",
        position=[12, 2, 22],
    )
    factory.options.queue = lua_value(harness.lua, {})
    factory.options.states = lua_value(harness.lua, {})
    factory.options.idleState = True
    harness.brain.units = harness.lua.table_from([factory, tank])
    macro_plan["epoch"] = 2
    macro_plan["grants"][0]["requestId"] = "land-production-2"
    _set_director_result(harness, "macroPlan", macro_plan)
    harness.brain.tick = 20
    harness.lua.globals().Controller.Step(harness.controller)

    assert [call.blueprintId for call in harness.calls.buildFactory.values()] == [
        "uel0202",
        "uel0205",
    ]


def test_two_t2_lanes_fill_direct_fire_and_anti_air_deficits_in_parallel() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    factories = [
        harness.unit(
            entityId=entity_id,
            blueprintId="ueb0201",
            position=[10 + index * 2, 2, 22],
            canBuild={"uel0202": True, "uel0205": True},
        )
        for index, entity_id in enumerate((20, 21))
    ]
    harness.brain.units = harness.lua.table_from(factories)
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"land_production": {"admitted": True}},
            "grants": [
                {"requestId": "land-1", "lane": "land_production", "source": "recurring"},
                {"requestId": "land-2", "lane": "land_production", "source": "bank"},
            ],
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "techPlan",
        {"t2ProductionRoles": ["t2_direct_fire", "t2_anti_air"]},
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert sorted(
        call.blueprintId for call in harness.calls.buildFactory.values()
    ) == ["uel0202", "uel0205"]
    assert sorted(
        call.units[1].options.entityId for call in harness.calls.buildFactory.values()
    ) == [20, 21]


def test_funded_t2_support_lane_upgrade_uses_exact_support_blueprint_and_pending_role() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    t1_a = harness.unit(
        entityId=20,
        blueprintId="ueb0101",
        position=[10, 2, 22],
        canBuild={"zeb9501": True},
    )
    t1_b = harness.unit(
        entityId=21,
        blueprintId="ueb0101",
        position=[12, 2, 22],
    )
    hq = harness.unit(
        entityId=22,
        blueprintId="ueb0201",
        position=[14, 2, 22],
    )
    harness.brain.units = harness.lua.table_from([t1_a, t1_b, hq])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"tech": {"admitted": True}},
            "grants": [
                {"requestId": "tech-support-1", "lane": "tech", "source": "bank"}
            ],
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "techPlan",
        {
            "supportAction": "start_t2_support",
            "supportSourceToken": "20:1",
            "supportUpgradeRole": "land_factory_t2_support",
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.upgrade) == 1
    assert harness.calls.upgrade[1].units[1].options.entityId == 20
    assert harness.calls.upgrade[1].blueprintId == "zeb9501"
    pending = plain(harness.controller.pending)["20:1"]
    assert pending["upgradeRole"] == "land_factory_t2_support"
    assert pending["operationId"] == "tech:t2_support"


def test_step_binds_land_and_aa_escorts_before_remote_expansion_departure_once() -> None:
    harness = make_harness()
    harness.controller.crossMapOffenseEnabled = False
    land_escort = harness.unit(
        entityId=70,
        blueprintId="uel0201",
        position=[10, 2, 20],
    )
    aa_escort = harness.unit(
        entityId=71,
        blueprintId="uel0104",
        position=[11, 2, 20],
    )
    engineer = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    alternate_aa = harness.unit(
        entityId=68,
        blueprintId="uel0104",
        position=[8, 2, 20],
    )
    alternate_land = harness.unit(
        entityId=69,
        blueprintId="uel0201",
        position=[9, 2, 20],
    )
    harness.brain.units = harness.lua.table_from(
        [alternate_aa, alternate_land, land_escort, aa_escort, engineer]
    )
    _set_starved_economy(harness)
    remote_site = plain(harness.controller.markers.mass[2])
    assert remote_site["name"] == "Far Mass"
    expansion_job = {
        "id": "mex:front:far",
        "kind": "build_mex",
        "actorToken": "72:1",
        "targetKey": remote_site["key"],
        "siteKey": remote_site["key"],
        "regionKey": "front",
        "position": remote_site["position"],
        "estimatedTravelTicks": 300,
        "escortTokens": ["70:1", "71:1"],
    }
    region = {
        "key": "front",
        "state": "planned",
        "position": remote_site["position"],
        "requiresGarrison": True,
        "requiresAntiAir": True,
    }
    harness.lua.execute(
        "MacroDirectorStub.AdvanceRegion = function(region, event) "
        "local result = {}; for key, value in pairs(region) do result[key] = value end; "
        "if event and event.event == 'package_ordered' then result.state = 'establishing' end; "
        "return result end"
    )

    def set_epoch(epoch: int) -> None:
        _set_director_result(
            harness,
            "intelState",
            {
                "epoch": epoch,
                "contacts": {},
                "threat": {"home": 0, "air": 0},
                "expansionSafety": {"front": "safe"},
            },
        )
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": True,
                "epoch": epoch,
                "fundedExpansionSlots": 1,
                "lanes": {"mex_rebuild": {"admitted": True}},
                "regions": [region],
                "intents": [],
            },
        )
        _set_director_result(
            harness,
            "expansionPlan",
            {"jobs": [expansion_job], "denials": []},
        )
        _set_director_result(
            harness,
            "jobLedger",
            {
                "epoch": epoch,
                "jobs": {
                    expansion_job["id"]: {
                        **expansion_job,
                        "phase": "travelling",
                        "deadlineTick": 900,
                    }
                },
                "releasedActorTokens": [],
            },
        )
        force_plan = {
            "epoch": epoch,
            "assignments": {
                "home": [],
                "garrison": ["68:1", "69:1", "70:1", "71:1"],
                "field": [],
                "response": [],
                "raider": [],
                "unassigned": [],
            },
            "ownershipByToken": {
                "68:1": "garrison",
                "69:1": "garrison",
                "70:1": "garrison",
                "71:1": "garrison",
            },
            "regionAssignments": {
                "front": {
                    "actorTokens": ["68:1", "69:1", "70:1", "71:1"],
                    "antiAirCount": 2,
                    "ready": True,
                }
            },
            "intents": [],
        }
        _set_director_result(harness, "forcePlan", force_plan)

    set_epoch(1)
    harness.lua.globals().Controller.Step(harness.controller)

    force_input = plain(harness.calls.forceAssign[1])
    assert force_input["macroPlan"]["regions"][0]["state"] == "establishing"
    assert force_input["macroPlan"]["regions"][0]["bootstrapEscortTokens"] == [
        "70:1",
        "71:1",
    ]
    assert plain(harness.controller.macroPlan)["regions"][0]["state"] == "establishing"

    assert [call.kind for call in harness.calls.orderTrace.values()] == [
        "guard",
        "build_mobile",
    ]
    guard = harness.calls.guard[1]
    assert [
        guard.units[index].options.entityId
        for index in range(1, len(guard.units) + 1)
    ] == [70, 71]
    assert guard.target.options.entityId == 72
    build = harness.calls.buildMobile[1]
    assert build.units[1].options.entityId == 72
    assert build.blueprintId == "ueb1103"
    assert plain(build.position) == [40, 40.4, 40]
    assert plain(harness.controller.forcePlan)["ownershipByToken"] == {
        "68:1": "garrison",
        "69:1": "garrison",
        "70:1": "garrison",
        "71:1": "garrison",
    }
    assert len(
        plain(harness.calls.macroUpdateJobLedger[1].snapshot)["newJobs"]
    ) == 1

    set_epoch(2)
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.orderTrace) == 2
    assert len(harness.calls.guard) == 1
    assert len(harness.calls.buildMobile) == 1
    assert len(
        plain(harness.calls.macroUpdateJobLedger[2].snapshot)["newJobs"]
    ) == 0
    assert plain(harness.calls.macroUpdateJobLedger[2].ledger)["epoch"] == 1
    assert plain(harness.controller.jobLedger)["jobs"][expansion_job["id"]][
        "actorToken"
    ] == "72:1"
    operation_events = [
        fields
        for line in harness.logs
        if (fields := parsing.overmind_marker_fields(line)) is not None
        and fields.get("kind") == "operation"
    ]
    expansion_events = [
        event
        for event in operation_events
        if event.get("operation") == expansion_job["id"]
    ]
    assert [event["phase"] for event in expansion_events] == [
        "opportunity",
        "selected",
        "admitted",
        "ordered",
    ]
    assert all(event["army"] == "1" for event in expansion_events)
    assert all(int(event["tick"]) >= 0 for event in expansion_events)


def test_policy_receives_own_director_state_but_never_observer_opponent_aggregates() -> None:
    harness = make_harness()
    harness.lua.globals().OM4BenchmarkLatest = lua_value(
        harness.lua,
        {
            "opponent_mass_income": 999999,
            "opponent_factories": 999999,
            "bothArmies": [{"army": 1}, {"army": 2}],
        },
    )
    harness.lua.execute(
        "Policy.Decide = function(snapshot) "
        "table.insert(calls.policySnapshots, snapshot); return {} end"
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.policySnapshots) == 1
    snapshot = plain(harness.calls.policySnapshots[1])
    assert "macroPlan" in snapshot
    assert "intelState" in snapshot
    assert "forcePlan" in snapshot
    serialized = repr(snapshot)
    director_inputs = repr(
        {
            "intel": plain(harness.calls.intelligenceUpdateMemory),
            "macro": plain(harness.calls.macroBuildPortfolio),
            "radar": plain(harness.calls.intelligencePlanRadar),
            "force": plain(harness.calls.forceAssign),
            "reconcile": plain(harness.calls.forceReconcile),
        }
    )
    for forbidden in (
        "999999",
        "opponent_mass_income",
        "opponent_factories",
        "bothArmies",
    ):
        assert forbidden not in serialized
        assert forbidden not in director_inputs


def test_region_package_and_mex_upgrade_intents_issue_exact_blueprints_and_persist_jobs() -> None:
    harness = make_harness()
    engineers = []
    for entity_id in (10, 11, 12):
        engineers.append(
            harness.unit(
                entityId=entity_id,
                blueprintId="uel0105",
                position=[10 + entity_id, 2, 20],
                canBuild={
                    "ueb3101": True,
                    "ueb2101": True,
                    "ueb2104": True,
                },
            )
        )
    mex = harness.unit(
        entityId=20,
        blueprintId="ueb1103",
        position=[15, 2, 15],
        canBuild={"ueb1202": True},
    )
    harness.brain.units = harness.lua.table_from([*engineers, mex])
    observation = harness.observe()
    intents = [
        {
            "kind": "build_structure",
            "actorToken": "10:1",
            "buildRole": "radar",
            "regionKey": "front",
            "position": [100, 2, 100],
            "reason": "region_package",
        },
        {
            "kind": "build_structure",
            "actorToken": "11:1",
            "buildRole": "point_defense",
            "regionKey": "front",
            "position": [104, 2, 100],
            "reason": "region_package",
        },
        {
            "kind": "build_structure",
            "actorToken": "12:1",
            "buildRole": "static_anti_air",
            "regionKey": "front",
            "position": [108, 2, 100],
            "reason": "region_package",
        },
        {
            "kind": "structure_upgrade",
            "actorToken": "20:1",
            "upgradeRole": "mass_extractor_t2",
            "siteKey": "front-mex",
            "reason": "stagger_mex_upgrade",
        },
    ]

    execute_intents(harness, intents, observation)

    build_calls = plain(harness.calls.buildMobile)
    assert [call["blueprintId"] for call in build_calls] == [
        "ueb3101",
        "ueb2101",
        "ueb2104",
    ]
    assert len(harness.calls.upgrade) == 1
    assert harness.calls.upgrade[1].blueprintId == "ueb1202"
    pending = plain(harness.controller.pending)
    operations = list(pending.values()) if isinstance(pending, dict) else pending
    assert {operation["buildRole"] for operation in operations} >= {
        "radar",
        "point_defense",
        "static_anti_air",
        "mass_extractor_t2",
    }


def test_arriving_mex_builder_reclaims_wreck_then_retries_the_same_build() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=10,
        blueprintId="uel0105",
        position=[40, 2, 40],
        canBuild={"ueb1103": True},
    )
    wreck = harness.lua.globals().MakeProp(
        lua_value(
            harness.lua,
            {
                "entityId": 900,
                "mass": 36,
                "energy": 0,
                "position": [40, 2, 40],
            },
        )
    )
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.reclaimables = harness.lua.table_from([wreck])
    harness.brain.canBuildAt = False
    intent = {
        "kind": "build_structure",
        "actorToken": "10:1",
        "buildRole": "mass_extractor",
        "siteKey": "wrecked-mex",
        "position": [40, 2, 40],
        "reason": "regional_expansion",
        "operationId": "mex:front:wrecked-mex",
        "operationAttempt": 0,
    }
    harness.controller.jobLedger.jobs[intent["operationId"]] = lua_value(
        harness.lua,
        {
            "id": intent["operationId"],
            "actorToken": "10:1",
            "targetKey": "wrecked-mex",
            "phase": "travelling",
        },
    )

    execute_intents(harness, [intent])

    assert len(harness.calls.reclaim) == 1
    assert len(harness.calls.buildMobile) == 0
    assert plain(harness.controller.jobLedger.jobs[intent["operationId"]]).get(
        "ordered"
    ) is not True

    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Reclaiming": True})
    execute_intents(harness, [intent], harness.observe())
    assert len(harness.calls.reclaim) == 1
    assert len(harness.calls.buildMobile) == 0

    harness.brain.reclaimables = harness.lua.table_from([])
    harness.brain.canBuildAt = True
    engineer.options.idleState = True
    engineer.options.states = lua_value(harness.lua, {})
    execute_intents(harness, [intent], harness.observe())

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb1103"
    assert plain(harness.controller.pending)["10:1"]["siteKey"] == "wrecked-mex"


def test_region_package_and_radar_always_require_a_valid_funded_expansion_lane() -> None:
    cases = (
        (True, {"admitted": False, "preserved": False}, False),
        (False, {"admitted": True, "preserved": False}, False),
        (True, {"admitted": True, "preserved": False}, True),
        (True, {"admitted": False, "preserved": True}, True),
    )
    for valid, lane, expected in cases:
        harness = make_harness()
        harness.lua.execute(
            "Policy.Decide = function(snapshot) "
            "table.insert(calls.policySnapshots, snapshot); return {} end"
        )
        engineers = [
            harness.unit(
                entityId=entity_id,
                blueprintId="uel0105",
                position=[10 + entity_id, 2, 20],
                canBuild={"ueb3101": True, "ueb2101": True},
            )
            for entity_id in (10, 11)
        ]
        harness.brain.units = harness.lua.table_from(engineers)
        region = {
            "key": "front",
            "state": "secured",
            "position": [100, 2, 100],
        }
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": valid,
                "epoch": 1,
                "stalled": False,
                "lanes": {"mex_rebuild": lane},
                "regions": [region],
                "intents": [],
            },
        )
        _set_director_result(
            harness, "regionPackagePlan", {"requiredRoles": ["point_defense"]}
        )
        _set_director_result(
            harness,
            "radarIntents",
            [
                {
                    "buildRole": "radar",
                    "regionKey": "front",
                    "position": [104, 2, 100],
                }
            ],
        )

        harness.lua.globals().Controller.Step(harness.controller)

        builds = sorted(
            call.blueprintId for call in harness.calls.buildMobile.values()
        )
        director_intents = plain(harness.calls.policySnapshots[1])["directorIntents"]
        funded_intents = [
            intent
            for intent in director_intents
            if intent.get("buildRole") in {"radar", "point_defense"}
        ]
        if expected:
            assert builds == ["ueb2101", "ueb3101"]
            assert len(funded_intents) == 2
        else:
            assert builds == []
            assert funded_intents == []


def test_package_and_intelligence_radar_semantically_dedupe_with_retry() -> None:
    radar_orders = (
        (11, 12),
        (12, 11),
    )
    for order in radar_orders:
        harness = make_harness()
        harness.lua.execute(
            "Policy.Decide = function(snapshot) "
            "table.insert(calls.policySnapshots, snapshot); return {} end"
        )
        engineers = [
            harness.unit(
                entityId=entity_id,
                blueprintId="uel0105",
                position=[entity_id, 2, 20],
                canBuild={"ueb3101": True},
            )
            for entity_id in (10, 11, 12)
        ]
        harness.brain.units = harness.lua.table_from(engineers)
        region = {
            "key": "front",
            "state": "secured",
            "position": [100, 2, 100],
        }
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": True,
                "epoch": 1,
                "lanes": {"mex_rebuild": {"admitted": True}},
                "regions": [region],
                "intents": [],
            },
        )
        _set_director_result(
            harness, "regionPackagePlan", {"requiredRoles": ["radar"]}
        )
        _set_director_result(
            harness,
            "radarIntents",
            [
                {
                    "actorToken": f"{entity_id}:1",
                    "buildRole": "radar",
                    "regionKey": "front",
                    "position": [104 + index, 2, 100],
                }
                for index, entity_id in enumerate(order)
            ],
        )

        harness.lua.globals().Controller.Step(harness.controller)

        radar_intents = [
            intent
            for intent in plain(harness.calls.policySnapshots[1])["directorIntents"]
            if intent.get("buildRole") == "radar"
        ]
        assert len(radar_intents) == 1
        assert radar_intents[0]["actorToken"] == "10:1"
        assert len(harness.calls.buildMobile) == 1
        assert harness.calls.buildMobile[1].units[1].options.entityId == 10
        pending = plain(harness.controller.pending)
        assert list(pending) == ["10:1"]
        assert pending["10:1"]["regionKey"] == "front"

        harness.brain.tick = 1
        harness.lua.globals().Controller.Step(harness.controller)
        assert len(harness.calls.buildMobile) == 1
        assert list(plain(harness.controller.pending)) == ["10:1"]

    retry = make_harness()
    retry.lua.execute(
        "Policy.Decide = function(snapshot) "
        "table.insert(calls.policySnapshots, snapshot); return {} end"
    )
    retry_engineers = [
        retry.unit(
            entityId=entity_id,
            blueprintId="uel0105",
            position=[entity_id, 2, 20],
            canBuild={"ueb3101": True},
        )
        for entity_id in (10, 11)
    ]
    retry.brain.units = retry.lua.table_from(retry_engineers)
    retry_region = {
        "key": "front",
        "state": "secured",
        "position": [100, 2, 100],
    }
    _set_director_result(
        retry,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [retry_region],
            "intents": [],
        },
    )
    _set_director_result(
        retry, "regionPackagePlan", {"requiredRoles": ["radar"]}
    )
    _set_director_result(
        retry,
        "radarIntents",
        [
            {
                "actorToken": "11:1",
                "buildRole": "radar",
                "regionKey": "front",
                "position": [104, 2, 100],
            }
        ],
    )
    retry.calls.failBuildMobile = True
    retry.lua.globals().Controller.Step(retry.controller)
    assert len(retry.calls.buildMobile) == 1
    assert len(retry.controller.pending) == 0

    retry.calls.failBuildMobile = False
    retry.brain.tick = 1
    retry.lua.globals().Controller.Step(retry.controller)
    assert len(retry.calls.buildMobile) == 2
    assert [
        call.units[1].options.entityId for call in retry.calls.buildMobile.values()
    ] == [10, 10]
    assert list(plain(retry.controller.pending)) == ["10:1"]


def test_completed_regional_radar_suppresses_stale_intelligence_intent() -> None:
    harness = make_harness()
    harness.lua.execute(
        "Policy.Decide = function(snapshot) "
        "table.insert(calls.policySnapshots, snapshot); return {} end"
    )
    engineers = [
        harness.unit(
            entityId=entity_id,
            blueprintId="uel0105",
            position=[entity_id, 2, 20],
            canBuild={"ueb3101": True},
        )
        for entity_id in (10, 11)
    ]
    harness.brain.units = harness.lua.table_from(engineers)
    region = {"key": "front", "state": "secured", "position": [100, 2, 100]}
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [region],
            "intents": [],
        },
    )
    _set_director_result(
        harness, "regionPackagePlan", {"requiredRoles": ["radar"]}
    )
    _set_director_result(
        harness,
        "radarIntents",
        [
            {
                "actorToken": "11:1",
                "buildRole": "radar",
                "regionKey": "front",
                "position": [104, 2, 100],
            }
        ],
    )

    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.buildMobile) == 1
    assert list(plain(harness.controller.pending)) == ["10:1"]

    completed_radar = harness.unit(
        entityId=80,
        blueprintId="ueb3101",
        position=[100, 2, 100],
    )
    harness.brain.units = harness.lua.table_from([*engineers, completed_radar])
    _set_director_result(harness, "regionPackagePlan", {"requiredRoles": []})
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert plain(harness.controller.pending) == {}
    second_radar_intents = [
        intent
        for intent in plain(harness.calls.policySnapshots[2])["directorIntents"]
        if intent.get("buildRole") == "radar"
    ]
    assert second_radar_intents == []


def test_radar_semantic_dedupe_keeps_distinct_regions_distinct() -> None:
    harness = make_harness()
    harness.lua.execute(
        "Policy.Decide = function(snapshot) "
        "table.insert(calls.policySnapshots, snapshot); return {} end"
    )
    engineers = [
        harness.unit(
            entityId=entity_id,
            blueprintId="uel0105",
            position=[entity_id, 2, 20],
            canBuild={"ueb3101": True},
        )
        for entity_id in (10, 11, 12, 13)
    ]
    harness.brain.units = harness.lua.table_from(engineers)
    regions = [
        {"key": "front-a", "state": "secured", "position": [100, 2, 100]},
        {"key": "front-b", "state": "secured", "position": [200, 2, 200]},
    ]
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": regions,
            "intents": [],
        },
    )
    _set_director_result(
        harness, "regionPackagePlan", {"requiredRoles": ["radar"]}
    )
    _set_director_result(
        harness,
        "radarIntents",
        [
            {
                "actorToken": f"{12 + index}:1",
                "buildRole": "radar",
                "regionKey": region["key"],
                "position": region["position"],
            }
            for index, region in enumerate(regions)
        ],
    )

    harness.lua.globals().Controller.Step(harness.controller)

    radar_intents = [
        intent
        for intent in plain(harness.calls.policySnapshots[1])["directorIntents"]
        if intent.get("buildRole") == "radar"
    ]
    assert [(intent["regionKey"], intent["actorToken"]) for intent in radar_intents] == [
        ("front-a", "10:1"),
        ("front-b", "11:1"),
    ]
    assert len(harness.calls.buildMobile) == 2
    pending_regions = sorted(
        operation["regionKey"] for operation in plain(harness.controller.pending).values()
    )
    assert pending_regions == ["front-a", "front-b"]


def test_singleton_region_radar_uses_bounded_live_alternate_build_probes() -> None:
    harness = make_harness()
    harness.lua.execute(
        "Policy.Decide = function(snapshot) "
        "table.insert(calls.policySnapshots, snapshot); return {} end"
    )
    engineer = harness.unit(
        entityId=10,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb3101": True},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    remote_site = plain(harness.controller.markers.mass[2])
    region = {
        "key": "front",
        "state": "secured",
        "position": remote_site["position"],
        "memberKeys": [remote_site["key"]],
    }
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "stalled": False,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [region],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "radarIntents",
        [
            {
                "buildRole": "radar",
                "regionKey": "front",
                "position": remote_site["position"],
            }
        ],
    )
    harness.lua.execute(
        "brain.packageProbeCount = 0; "
        "brain.canBuildAt = function(blueprintId, position) "
        "if blueprintId ~= 'ueb3101' then return true end; "
        "brain.packageProbeCount = brain.packageProbeCount + 1; "
        "return brain.packageProbeCount == 2 end"
    )

    harness.lua.globals().Controller.Step(harness.controller)

    radar_probes = [
        plain(call)[1]
        for call in harness.calls.canBuild.values()
        if plain(call)[0] == "ueb3101"
    ]
    assert len(radar_probes) == 2
    assert len(harness.calls.buildMobile) == 1
    built = plain(harness.calls.buildMobile[1].position)
    assert (built[0], built[2]) != (
        remote_site["position"][0],
        remote_site["position"][2],
    )
    director_intent = next(
        intent
        for intent in plain(harness.calls.policySnapshots[1])["directorIntents"]
        if intent.get("buildRole") == "radar"
    )
    assert 2 <= len(director_intent["positionCandidates"]) <= 8


def test_bomber_transport_garrison_and_home_response_issue_exact_low_level_orders() -> None:
    harness = make_harness()
    bomber = harness.unit(
        entityId=30,
        blueprintId="uea0103",
        position=[10, 20, 20],
    )
    transport = harness.unit(
        entityId=31,
        blueprintId="uea0107",
        position=[10, 20, 22],
    )
    cargo = harness.unit(
        entityId=32,
        blueprintId="uel0105",
        position=[10, 2, 22],
    )
    garrison = harness.unit(
        entityId=33,
        blueprintId="uel0201",
        position=[10, 2, 20],
    )
    responder = harness.unit(
        entityId=34,
        blueprintId="uel0104",
        position=[12, 2, 20],
    )
    enemy_engineer = harness.unit(
        entityId=90,
        blueprintId="uel0105",
        army=2,
        position=[40, 2, 40],
    )
    harness.brain.units = harness.lua.table_from(
        [bomber, transport, cargo, garrison, responder]
    )
    harness.brain.enemies = harness.lua.table_from([])
    stale_observation = harness.observe()
    bomber_intent = {
        "kind": "bomber_raid",
        "actorToken": "30:1",
        "targetToken": "90:1",
        "targetRole": "engineer",
        "position": [40, 2, 40],
    }

    execute_intents(harness, [bomber_intent], stale_observation)
    assert len(harness.calls.aggressive) == 0

    harness.brain.enemies = harness.lua.table_from([enemy_engineer])
    observation = harness.observe()

    execute_intents(
        harness,
        [
            bomber_intent,
            {
                "kind": "transport_load",
                "missionId": "airlift:front",
                "transportToken": "31:1",
                "cargoTokens": ["32:1"],
                "dropPosition": [300, 2, 300],
            },
            {
                "kind": "region_garrison",
                "regionKey": "front",
                "actorTokens": ["33:1"],
                "position": [100, 2, 100],
            },
            {
                "kind": "home_response",
                "actorTokens": ["34:1"],
                "position": [10, 2, 20],
                "priority": "immediate_home_breach",
            },
        ],
        observation,
    )

    assert len(harness.calls.transportLoad) == 1
    assert harness.calls.transportLoad[1].transport.options.entityId == 31
    assert harness.calls.transportLoad[1].units[1].options.entityId == 32
    assert len(harness.calls.aggressive) == 1
    assert plain(harness.calls.aggressive[1].position) == [40, 2, 40]
    assert harness.calls.aggressive[1].units[1].options.entityId == 30
    assert len(harness.calls.aggressive[1].units) == 1
    assert len(harness.calls.move) == 2
    move_actors = {}
    for index in range(1, len(harness.calls.move) + 1):
        call = harness.calls.move[index]
        position = tuple(plain(call.position))
        move_actors[position] = [
            call.units[actor_index].options.entityId
            for actor_index in range(1, len(call.units) + 1)
        ]
    assert move_actors == {(10, 2, 20): [34], (100, 2, 100): [33]}
    mission = plain(harness.controller.transportMissions["airlift:front"])
    assert mission["state"] == "loading"
    assert mission["transportToken"] == "31:1"
    assert mission["cargoTokens"] == ["32:1"]
    assert plain(harness.controller.bomberMissions["30:1"])["targetToken"] == "90:1"

    attached = harness.observe()
    execute_intents(
        harness,
        [
            {
                "kind": "transport_unload",
                "missionId": "airlift:front",
                "transportToken": "31:1",
                "cargoTokens": ["32:1"],
                "dropPosition": [300, 2, 300],
            }
        ],
        attached,
    )
    assert len(harness.calls.transportUnload) == 1
    assert plain(harness.calls.transportUnload[1].position) == [300, 2, 300]

    completed = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, completed)
    assert harness.controller.transportMissions["airlift:front"] is None


def test_loaded_transport_reconcile_releases_retryably_when_exact_cargo_disappears() -> None:
    harness = make_harness()
    transport = harness.unit(
        entityId=31,
        blueprintId="uea0107",
        position=[10, 20, 22],
        cargo=[],
    )
    cargo = harness.unit(
        entityId=32,
        blueprintId="uel0105",
        position=[10, 2, 22],
        attached=False,
    )
    harness.brain.units = harness.lua.table_from([transport, cargo])
    harness.controller.transportMissions["airlift:front"] = lua_value(
        harness.lua,
        {
            "missionId": "airlift:front",
            "state": "loaded",
            "transportToken": "31:1",
            "cargoTokens": ["32:1"],
            "siteKey": "front",
            "dropPosition": [300, 2, 300],
            "deadlineTick": 900,
            "retryCount": 0,
        },
    )

    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)

    assert harness.controller.transportMissions["airlift:front"] is None
    history = plain(harness.controller.transportHistory["airlift:front"])
    assert history["retryable"] is True
    assert history["retryCount"] == 1


def test_completed_airlift_orders_its_engineer_to_build_the_exact_drop_mex() -> None:
    harness = make_harness()
    drop = [300, 2, 300]
    transport = harness.unit(
        entityId=31,
        blueprintId="uea0107",
        position=drop,
        cargo=[],
    )
    cargo = harness.unit(
        entityId=32,
        blueprintId="uel0105",
        position=drop,
        attached=False,
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([transport, cargo])
    harness.controller.markers.mass = lua_value(
        harness.lua,
        [
            {
                "key": "front",
                "name": "Front",
                "kind": "mass",
                "position": drop,
                "distance": 200,
                "localSite": False,
                "reachable": True,
                "engineerReachable": True,
            }
        ],
    )
    harness.controller.transportMissions["airlift:front"] = lua_value(
        harness.lua,
        {
            "missionId": "airlift:front",
            "state": "unloading",
            "transportToken": "31:1",
            "cargoTokens": ["32:1"],
            "siteKey": "front",
            "dropPosition": drop,
            "dropTolerance": 20,
            "deadlineTick": 900,
            "retryCount": 0,
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    cargo_moves = [
        call
        for call in harness.calls.move.values()
        if call.units[1].options.entityId == 32
    ]
    assert len(cargo_moves) == 1
    cargo_move_position = plain(cargo_moves[0].position)
    cargo_clearance = (
        (cargo_move_position[0] - 300) ** 2
        + (cargo_move_position[2] - 300) ** 2
    ) ** 0.5
    assert 18 <= cargo_clearance <= 22
    transport_moves = [
        call
        for call in harness.calls.move.values()
        if call.units[1].options.entityId == 31
    ]
    assert len(transport_moves) == 1
    assert not [
        call
        for call in harness.calls.buildMobile.values()
        if call.blueprintId == "ueb1103"
    ]

    cargo.options.position = lua_value(harness.lua, cargo_move_position)
    harness.brain.tick = harness.brain.tick + 9
    harness.lua.globals().Controller.Step(harness.controller)

    mex_orders = [
        call
        for call in harness.calls.buildMobile.values()
        if call.blueprintId == "ueb1103"
    ]
    assert len(mex_orders) == 1
    assert mex_orders[0].units[1].options.entityId == 32
    assert tuple(plain(mex_orders[0].position)[index] for index in (0, 2)) == (
        300,
        300,
    )
    assert harness.controller.transportMissions["airlift:front"] is None
    assert len(harness.calls.transportLoad) == 0


@pytest.mark.parametrize("retarget", [False, True])
def test_airlift_unload_reserves_the_exact_drop_mex_without_building_before_detach(
    retarget: bool,
) -> None:
    harness = make_harness()
    drop = [300, 2, 300]
    cargo = harness.unit(
        entityId=32,
        blueprintId="uel0105",
        position=[10, 2, 22],
        attached=True,
        canBuild={},
    )
    transport = harness.unit(
        entityId=31,
        blueprintId="uea0107",
        position=[10, 20, 22],
        cargo=[cargo],
    )
    harness.brain.units = harness.lua.table_from([transport, cargo])
    harness.observe()
    harness.brain.units = harness.lua.table_from([transport])
    markers = [
        {
            "key": "front",
            "name": "Front",
            "kind": "mass",
            "position": drop,
            "distance": 200,
            "localSite": False,
            "reachable": True,
            "engineerReachable": True,
        }
    ]
    if retarget:
        markers.append(
            {
                "key": "alternate",
                "name": "Alternate",
                "kind": "mass",
                "position": [320, 2, 300],
                "distance": 220,
                "localSite": False,
                "reachable": True,
                "engineerReachable": True,
            }
        )
        harness.lua.execute(
            "brain.canBuildAt = function(blueprintId, position) "
            "return blueprintId ~= 'ueb1103' or position[1] >= 320 end"
        )
    harness.controller.markers.mass = lua_value(harness.lua, markers)
    harness.controller.transportMissions["airlift:front"] = lua_value(
        harness.lua,
        {
            "missionId": "airlift:front",
            "state": "loaded",
            "transportToken": "31:1",
            "cargoTokens": ["32:1"],
            "siteKey": "front",
            "dropPosition": drop,
            "dropTolerance": 20,
            "deadlineTick": 900,
            "retryCount": 0,
            "requireLiveDropValidation": True,
        },
    )
    harness.controller.transportCargoRefs = harness.lua.table_from(
        {"airlift:front": harness.lua.table_from({"32:1": cargo})}
    )
    harness.lua.execute("Policy.Decide = function() return {} end")

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.transportUnload) == 1
    unload_position = plain(harness.calls.transportUnload[1].position)
    expected_x = 320 if retarget else 300
    unload_distance = (
        (unload_position[0] - expected_x) ** 2
        + (unload_position[2] - 300) ** 2
    ) ** 0.5
    assert 8 <= unload_distance <= 12
    transport_moves = [
        call
        for call in harness.calls.move.values()
        if call.units[1].options.entityId == 31
    ]
    assert transport_moves == []
    cargo_moves = [
        call
        for call in harness.calls.move.values()
        if call.units[1].options.entityId == 32
    ]
    assert len(cargo_moves) == 1
    cargo_move_position = plain(cargo_moves[0].position)
    cargo_clearance = (
        (cargo_move_position[0] - expected_x) ** 2
        + (cargo_move_position[2] - 300) ** 2
    ) ** 0.5
    assert 18 <= cargo_clearance <= 22
    mex_orders = [
        call
        for call in harness.calls.buildMobile.values()
        if call.blueprintId == "ueb1103"
    ]
    assert mex_orders == []
    mission = plain(harness.controller.transportMissions["airlift:front"])
    assert mission["siteKey"] == ("alternate" if retarget else "front")
    assert mission["deliveryBuildQueued"] is False
    assert mission["deliveryClearanceQueued"] is True


def test_airlift_delivery_retargets_when_the_drop_mex_becomes_blocked() -> None:
    harness = make_harness()
    drop = [300, 2, 300]
    cargo = harness.unit(
        entityId=32,
        blueprintId="uel0105",
        position=[290, 2, 300],
        attached=False,
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([cargo])
    harness.controller.markers.mass = lua_value(
        harness.lua,
        [
            {
                "key": "front",
                "name": "Front",
                "kind": "mass",
                "position": drop,
                "distance": 200,
                "localSite": False,
                "reachable": True,
                "engineerReachable": True,
            },
            {
                "key": "alternate",
                "name": "Alternate",
                "kind": "mass",
                "position": [330, 2, 300],
                "distance": 230,
                "localSite": False,
                "reachable": True,
                "engineerReachable": True,
            },
        ],
    )
    harness.controller.transportDeliveries["front"] = lua_value(
        harness.lua,
        {
            "actorToken": "32:1",
            "missionId": "airlift:front",
            "siteKey": "front",
            "position": drop,
            "completedTick": -200,
        },
    )
    harness.lua.execute("Policy.Decide = function() return {} end")
    harness.lua.execute(
        "brain.canBuildAt = function(blueprintId, position) "
        "return blueprintId ~= 'ueb1103' or position[1] >= 330 end"
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 0
    assert len(harness.calls.move) == 0
    assert harness.controller.transportDeliveries["front"] is None
    assert harness.controller.transportDeliveries["alternate"] is not None

    harness.brain.tick = harness.brain.tick + 1
    harness.lua.globals().Controller.Step(harness.controller)

    cargo_move = next(
        call
        for call in harness.calls.move.values()
        if call.units[1].options.entityId == 32
    )
    cargo.options.position = lua_value(harness.lua, plain(cargo_move.position))
    harness.brain.tick = harness.brain.tick + 9
    harness.lua.globals().Controller.Step(harness.controller)

    mex_orders = [
        call
        for call in harness.calls.buildMobile.values()
        if call.blueprintId == "ueb1103"
    ]
    assert len(mex_orders) == 1
    assert mex_orders[0].units[1].options.entityId == 32
    assert tuple(plain(mex_orders[0].position)[index] for index in (0, 2)) == (
        330,
        300,
    )
    assert harness.controller.transportDeliveries["alternate"] is not None
    assert harness.controller.blockedSites["front"] is not None

    harness.controller.pending["32:1"].accepted = True
    cargo.options.position = lua_value(harness.lua, [326, 2, 300])
    harness.brain.tick = harness.brain.tick + 27
    harness.lua.globals().Controller.Reconcile(
        harness.controller,
        harness.observe(),
    )

    assert harness.controller.pending["32:1"] is not None
    assert harness.controller.blockedSites["alternate"] is None


def test_airlift_skips_the_nearest_physically_unbuildable_mex() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/Intelligence.lua"))
    harness.lua.execute(
        "IntelligenceStub.PlanTransport = Intelligence.PlanTransport"
    )
    engineer = harness.unit(
        entityId=32,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
    )
    transport = harness.unit(
        entityId=31,
        blueprintId="uea0107",
        position=[10, 20, 22],
    )
    harness.brain.units = harness.lua.table_from([transport, engineer])
    harness.controller.markers.mass = lua_value(
        harness.lua,
        [
            {
                "key": "blocked",
                "name": "Blocked",
                "kind": "mass",
                "position": [200, 2, 200],
                "distance": 250,
                "reachable": True,
                "engineerReachable": True,
            },
            {
                "key": "usable",
                "name": "Usable",
                "kind": "mass",
                "position": [220, 2, 200],
                "distance": 270,
                "reachable": True,
                "engineerReachable": True,
            },
        ],
    )
    harness.lua.execute(
        "brain.canBuildAt = function(blueprintId, position) "
        "return blueprintId ~= 'ueb1103' or position[1] >= 220 end; "
        "Policy.Decide = function() return {} end"
    )
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"air_production": {"admitted": True}},
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.transportLoad) == 1
    mission = plain(harness.controller.transportMissions["airlift:usable"])
    assert mission["siteKey"] == "usable"
    assert harness.controller.transportMissions["airlift:blocked"] is None


@pytest.mark.parametrize("work_source", ["policy", "director"])
def test_unloading_airlift_keeps_cargo_engineer_out_of_other_work(
    work_source: str,
) -> None:
    harness = make_harness()
    drop = [300, 2, 300]
    cargo = harness.unit(
        entityId=32,
        blueprintId="uel0105",
        position=drop,
        attached=True,
        canBuild={"ueb3101": True},
    )
    transport = harness.unit(
        entityId=31,
        blueprintId="uea0107",
        position=drop,
        cargo=[cargo],
    )
    harness.brain.units = harness.lua.table_from([transport, cargo])
    harness.controller.transportMissions["airlift:front"] = lua_value(
        harness.lua,
        {
            "missionId": "airlift:front",
            "state": "unloading",
            "transportToken": "31:1",
            "cargoTokens": ["32:1"],
            "siteKey": "front",
            "dropPosition": drop,
            "dropTolerance": 20,
            "deadlineTick": 900,
            "retryCount": 0,
        },
    )
    if work_source == "policy":
        harness.lua.execute(
            "Policy.Decide = function() return {{"
            "kind = 'build_structure', actorToken = '32:1', buildRole = 'radar', "
            "position = { 20, 2, 20 }, reason = 'policy_probe' }} end"
        )
    else:
        harness.lua.execute("Policy.Decide = function() return {} end")
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": True,
                "epoch": 1,
                "lanes": {"mex_rebuild": {"admitted": True}},
                "regions": [],
                "intents": [],
            },
        )
        _set_director_result(
            harness,
            "radarIntents",
            [
                {
                    "kind": "build_structure",
                    "buildRole": "radar",
                    "regionKey": "front",
                    "position": [20, 2, 20],
                }
            ],
        )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 0
    assert plain(harness.controller.transportMissions["airlift:front"])["state"] == (
        "unloading"
    )


def test_loaded_transport_reconcile_rejects_attached_foreign_extra_cargo() -> None:
    harness = make_harness()
    cargo = harness.unit(
        entityId=32,
        blueprintId="uel0105",
        position=[10, 2, 22],
        attached=True,
    )
    foreign_extra = harness.unit(
        entityId=99,
        blueprintId="url0105",
        army=2,
        position=[10, 2, 22],
        attached=True,
    )
    transport = harness.unit(
        entityId=31,
        blueprintId="uea0107",
        position=[10, 20, 22],
        cargo=[cargo, foreign_extra],
    )
    harness.brain.units = harness.lua.table_from([transport, cargo])
    harness.controller.transportMissions["airlift:front"] = lua_value(
        harness.lua,
        {
            "missionId": "airlift:front",
            "state": "loaded",
            "transportToken": "31:1",
            "cargoTokens": ["32:1"],
            "siteKey": "front",
            "dropPosition": [300, 2, 300],
            "deadlineTick": 900,
            "retryCount": 0,
        },
    )

    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)

    assert harness.controller.transportMissions["airlift:front"] is None
    assert plain(harness.controller.transportHistory["airlift:front"])[
        "retryable"
    ] is True


def test_loading_an_existing_transport_needs_no_air_production_grant() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    transport = harness.unit(
        entityId=31,
        blueprintId="uea0107",
        position=[10, 20, 20],
        cargo=[],
    )
    cargo = harness.unit(
        entityId=32,
        blueprintId="uel0105",
        position=[10, 2, 20],
    )
    harness.brain.units = harness.lua.table_from([transport, cargo])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"air_production": {"admitted": False}},
            "grants": [],
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "transportPlan",
        {
            "mode": "airlift",
            "missionId": "airlift:front",
            "siteKey": "front",
            "transportToken": "31:1",
            "cargoTokens": ["32:1"],
            "dropPosition": [300, 2, 300],
            "dropTolerance": 20,
            "retryCount": 0,
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.transportLoad) == 1
    assert harness.controller.transportMissions["airlift:front"] is not None


def test_airlift_command_failure_rejects_attempt_then_retries_same_semantic_operation() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    transport = harness.unit(
        entityId=31,
        blueprintId="uea0107",
        position=[10, 20, 20],
        cargo=[],
    )
    cargo = harness.unit(
        entityId=32,
        blueprintId="uel0105",
        position=[10, 2, 20],
    )
    harness.brain.units = harness.lua.table_from([transport, cargo])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"air_production": {"admitted": True}},
            "grants": [
                {
                    "requestId": "airlift-1",
                    "lane": "air_production",
                    "source": "bank",
                }
            ],
            "regions": [],
            "intents": [],
        },
    )
    mission = {
        "mode": "airlift",
        "missionId": "airlift:front",
        "siteKey": "remote-safe",
        "transportToken": "31:1",
        "cargoTokens": ["32:1"],
        "dropPosition": [300, 303, 300],
        "dropTolerance": 20,
        "retryCount": 0,
    }
    _set_director_result(harness, "transportPlan", mission)
    harness.calls.failTransportLoad = True

    harness.lua.globals().Controller.Step(harness.controller)

    first = _operation_events(harness, "airlift:front")
    assert [event["phase"] for event in first] == [
        "opportunity",
        "selected",
        "admitted",
        "rejected",
    ]
    assert all(event.get("attempt") == "0" for event in first[1:])
    assert len(harness.controller.transportMissions) == 0

    harness.calls.failTransportLoad = False
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    assert [
        event["phase"] for event in _operation_events(harness, "airlift:front")
    ] == [
        "opportunity",
        "selected",
        "admitted",
        "rejected",
        "selected",
        "admitted",
        "ordered",
    ]
    assert _operation_events(harness, "airlift:front")[-1]["attempt"] == "1"
    assert len(harness.calls.transportLoad) == 2
    _assert_operation_stream_clean(harness)


def test_home_breach_causal_episode_is_stable_while_sustained_and_renews_after_clear() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    responder = harness.unit(
        entityId=60,
        blueprintId="uel0201",
        position=[20, 2, 20],
    )
    harness.brain.units = harness.lua.table_from([responder])
    response_plan = {
        "epoch": 1,
        "assignments": {"response": ["60:1"]},
        "ownershipByToken": {"60:1": "response"},
        "regionAssignments": {},
        "intents": [],
        "responseIntent": {
            "actorTokens": ["60:1"],
            "position": [10, 10.2, 20],
            "priority": "immediate_home_breach",
        },
    }
    _set_director_result(harness, "forcePlan", response_plan)
    _set_director_result(harness, "homeBreachPlan", response_plan)
    _set_director_result(
        harness,
        "intelState",
        {"contacts": {}, "threat": {"home": 2}, "expansionSafety": {}},
    )

    harness.lua.globals().Controller.Step(harness.controller)
    assert [
        event["phase"] for event in _operation_events(harness, "breach:home:1")
    ] == ["opportunity", "selected", "admitted", "ordered"]
    assert len(harness.calls.move) == 1

    responder.options.states = lua_value(harness.lua, {"Moving": True})
    responder.options.idleState = False
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)
    assert [
        event["phase"] for event in _operation_events(harness, "breach:home:1")
    ] == ["opportunity", "selected", "admitted", "ordered", "progressing"]
    assert len(harness.calls.move) == 1

    cleared_plan = {
        "epoch": 2,
        "assignments": {"home": ["60:1"]},
        "ownershipByToken": {"60:1": "home"},
        "regionAssignments": {},
        "intents": [],
    }
    _set_director_result(harness, "forcePlan", cleared_plan)
    _set_director_result(harness, "homeBreachPlan", False)
    _set_director_result(
        harness,
        "intelState",
        {"contacts": {}, "threat": {"home": 0}, "expansionSafety": {}},
    )
    responder.options.states = lua_value(harness.lua, {})
    responder.options.idleState = True
    harness.brain.tick = 2
    harness.lua.globals().Controller.Step(harness.controller)
    assert _operation_events(harness, "breach:home:1")[-1]["phase"] == "completed"

    _set_director_result(harness, "forcePlan", response_plan)
    _set_director_result(harness, "homeBreachPlan", response_plan)
    _set_director_result(
        harness,
        "intelState",
        {"contacts": {}, "threat": {"home": 1}, "expansionSafety": {}},
    )
    harness.brain.tick = 3
    harness.lua.globals().Controller.Step(harness.controller)
    assert [
        event["phase"] for event in _operation_events(harness, "breach:home:2")
    ] == ["opportunity", "selected", "admitted", "ordered"]
    _assert_operation_stream_clean(harness)


def test_home_breach_failed_move_rejects_attempt_without_false_ordered_then_retries() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    responder = harness.unit(
        entityId=60,
        blueprintId="uel0201",
        position=[20, 2, 20],
    )
    harness.brain.units = harness.lua.table_from([responder])
    response_plan = {
        "epoch": 1,
        "assignments": {"response": ["60:1"]},
        "ownershipByToken": {"60:1": "response"},
        "regionAssignments": {},
        "intents": [],
        "responseIntent": {
            "actorTokens": ["60:1"],
            "position": [10, 10.2, 20],
            "priority": "immediate_home_breach",
        },
    }
    _set_director_result(harness, "forcePlan", response_plan)
    _set_director_result(harness, "homeBreachPlan", response_plan)
    harness.calls.failMove = True

    harness.lua.globals().Controller.Step(harness.controller)

    first = _operation_events(harness, "breach:home:1")
    assert [event["phase"] for event in first] == [
        "opportunity",
        "selected",
        "admitted",
        "rejected",
    ]
    assert all(event["phase"] != "ordered" for event in first)

    harness.calls.failMove = False
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)
    events = _operation_events(harness, "breach:home:1")
    assert [event["phase"] for event in events[-3:]] == [
        "selected",
        "admitted",
        "ordered",
    ]
    assert events[-1]["attempt"] == "1"
    assert len(harness.calls.move) == 2
    _assert_operation_stream_clean(harness)


def test_failed_escorted_expansion_never_reports_ordered_before_build_command_succeeds() -> None:
    harness = make_harness()
    land = harness.unit(entityId=70, blueprintId="uel0201", position=[10, 2, 20])
    aa = harness.unit(entityId=71, blueprintId="uel0104", position=[11, 2, 20])
    engineer = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([land, aa, engineer])
    harness.controller.forcePlan = lua_value(
        harness.lua,
        {
            "ownershipByToken": {"70:1": "garrison", "71:1": "garrison"},
            "regionAssignments": {
                "front": {
                    "actorTokens": ["70:1", "71:1"],
                    "antiAirCount": 1,
                    "ready": False,
                }
            },
        },
    )
    harness.controller.jobLedger = lua_value(
        harness.lua, {"jobs": {"mex:front:far": {"phase": "travelling"}}}
    )
    harness.calls.failBuildMobile = True
    observation = harness.observe()

    execute_intents(
        harness,
        [
            {
                "kind": "escorted_expansion",
                "actorToken": "72:1",
                "buildRole": "mass_extractor",
                "siteKey": plain(harness.controller.markers.mass[2])["key"],
                "targetKey": plain(harness.controller.markers.mass[2])["key"],
                "regionKey": "front",
                "forceRegion": "front",
                "position": plain(harness.controller.markers.mass[2])["position"],
                "operationId": "mex:front:far",
                "escortTokens": ["70:1", "71:1"],
                "escortBootstrap": True,
            }
        ],
        observation,
    )

    phases = [
        fields
        for line in harness.logs
        if (fields := parsing.overmind_marker_fields(line)) is not None
        and fields.get("kind") == "operation"
        and fields.get("operation") == "mex:front:far"
    ]
    assert [event["phase"] for event in phases] == [
        "opportunity",
        "selected",
        "admitted",
        "rejected",
    ]
    assert phases[-1]["reason"] == "command_error"


def test_invalid_escorted_expansion_reports_preflight_rejection() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    harness.controller.forcePlan = lua_value(
        harness.lua, {"ownershipByToken": {}, "regionAssignments": {}}
    )
    observation = harness.observe()

    execute_intents(
        harness,
        [
            {
                "kind": "escorted_expansion",
                "actorToken": "72:1",
                "buildRole": "mass_extractor",
                "forceRegion": "front",
                "operationId": "mex:front:invalid",
                "escortTokens": [],
                "position": [40, 3, 40],
            }
        ],
        observation,
    )

    events = [
        fields
        for line in harness.logs
        if (fields := parsing.overmind_marker_fields(line)) is not None
        and fields.get("kind") == "operation"
        and fields.get("operation") == "mex:front:invalid"
    ]
    assert [event["phase"] for event in events] == [
        "opportunity",
        "selected",
        "admitted",
        "rejected",
    ]
    assert events[-1]["reason"] == "escort_preflight_failed"


def test_local_unescorted_expansion_reports_full_success_lifecycle_once() -> None:
    harness = make_harness()
    engineer = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    site = plain(harness.controller.markers.mass[1])
    job = {
        "id": "mex:home:near",
        "kind": "build_mex",
        "actorToken": "72:1",
        "targetKey": site["key"],
        "siteKey": site["key"],
        "regionKey": "home",
        "position": site["position"],
        "estimatedTravelTicks": 10,
        "requiresEscort": False,
    }
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(harness, "expansionPlan", {"jobs": [job], "denials": []})
    _set_director_result(
        harness,
        "jobLedger",
        {
            "epoch": 1,
            "jobs": {job["id"]: {**job, "phase": "travelling", "deadlineTick": 900}},
            "releasedActorTokens": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    events = [
        fields
        for line in harness.logs
        if (fields := parsing.overmind_marker_fields(line)) is not None
        and fields.get("kind") == "operation"
        and fields.get("operation") == job["id"]
    ]
    assert [event["phase"] for event in events] == [
        "opportunity",
        "selected",
        "admitted",
        "ordered",
    ]


def test_one_consumable_mex_grant_funds_exactly_one_of_two_valid_operations_permutation_stably() -> None:
    outcomes = []
    for reverse in (False, True):
        harness = make_harness()
        _use_real_macro_job_ledger(harness)
        harness.lua.execute("Policy.Decide = function() return {} end")
        engineers = [
            harness.unit(
                entityId=entity_id,
                blueprintId="uel0105",
                position=position,
                canBuild={"ueb1103": True},
            )
            for entity_id, position in ((72, [12, 2, 20]), (73, [39, 2, 40]))
        ]
        harness.brain.units = harness.lua.table_from(engineers)
        near = plain(harness.controller.markers.mass[1])
        far = plain(harness.controller.markers.mass[2])
        jobs = [
            {
                "id": operation_id,
                "actorToken": actor,
                "targetKey": site["key"],
                "siteKey": site["key"],
                "position": site["position"],
                "estimatedTravelTicks": 30,
            }
            for operation_id, actor, site in (
                ("mex:a", "72:1", near),
                ("mex:b", "73:1", far),
            )
        ]
        if reverse:
            jobs.reverse()
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": True,
                "epoch": 1,
                "fundedExpansionSlots": 2,
                "lanes": {"mex_rebuild": {"admitted": True}},
                "grants": [
                    {
                        "requestId": "mex-grant-1",
                        "lane": "mex_rebuild",
                        "source": "recurring",
                        "massDrain": 0.3,
                        "energyDrain": 3,
                        "massCost": 36,
                        "energyCost": 360,
                    }
                ],
                "regions": [],
                "intents": [],
            },
        )
        _set_director_result(
            harness,
            "expansionPlan",
            {"jobs": jobs, "denials": []},
        )

        harness.lua.globals().Controller.Step(harness.controller)

        assert len(harness.calls.buildMobile) == 1
        outcomes.append(
            (
                harness.calls.buildMobile[1].units[1].options.entityId,
                plain(harness.controller.fundingGrants)["mex-grant-1"][
                    "operationId"
                ],
            )
        )

    assert outcomes == [(72, "mex:a"), (72, "mex:a")]


def test_mex_causal_operation_reports_reconcile_progress_and_completion_once() -> None:
    harness = make_harness()
    _use_real_macro_job_ledger(harness)
    harness.lua.execute("Policy.Decide = function() return {} end")
    engineer = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    site, job = _configure_local_expansion(harness)

    harness.lua.globals().Controller.Step(harness.controller)
    assert [
        event["phase"] for event in _operation_events(harness, job["id"])
    ] == ["opportunity", "selected", "admitted", "ordered"]

    foundation = harness.unit(
        entityId=80,
        blueprintId="ueb1103",
        position=site["position"],
        fraction=0.4,
    )
    harness.brain.units = harness.lua.table_from([engineer, foundation])
    harness.brain.tick = 10
    harness.lua.globals().Controller.Step(harness.controller)
    assert [
        event["phase"] for event in _operation_events(harness, job["id"])
    ] == [
        "opportunity",
        "selected",
        "admitted",
        "ordered",
        "progressing",
    ]

    foundation.options.fraction = 1
    harness.brain.tick = 20
    harness.lua.globals().Controller.Step(harness.controller)
    assert [
        event["phase"] for event in _operation_events(harness, job["id"])
    ] == [
        "opportunity",
        "selected",
        "admitted",
        "ordered",
        "progressing",
        "completed",
    ]
    assert len(harness.controller.pending) == 0

    harness.brain.tick = 30
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(_operation_events(harness, job["id"])) == 6


def test_reclaim_causal_operation_keeps_stable_id_until_observed_completion() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    engineer = harness.unit(
        entityId=12,
        blueprintId="uel0105",
        position=[10, 2, 20],
        blueprintIntel={"VisionRadius": 20},
    )
    prop = harness.lua.globals().MakeProp(
        lua_value(
            harness.lua,
            {
                "entityId": 501,
                "position": [13, 2, 20],
                "cachePosition": [13, 2, 20],
                "mass": 500,
            },
        )
    )
    harness.brain.units = harness.lua.table_from([engineer])
    harness.brain.reclaimables = harness.lua.table_from([prop])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"reclaim": {"admitted": True}},
            "grants": [
                {"requestId": "reclaim-1", "lane": "reclaim", "source": "recurring"}
            ],
            "regions": [
                {
                    "key": "home",
                    "state": "secured",
                    "position": [10, 2, 20],
                    "radius": 80,
                }
            ],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "reclaimPlan",
        {
            "jobs": [
                {
                    "id": "reclaim:prop:501",
                    "actorToken": "12:1",
                    "targetKey": "prop:501",
                    "targetValue": 500,
                    "regionKey": "home",
                    "position": [13, 2, 20],
                    "requiresLiveVisionRevalidation": True,
                }
            ]
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert [
        event["phase"]
        for event in _operation_events(harness, "reclaim:prop:501")
    ] == ["opportunity", "selected", "admitted", "ordered"]
    assert plain(harness.controller.pending)["12:1"]["operationId"] == (
        "reclaim:prop:501"
    )

    prop.ReclaimLeft = 0.5
    _set_director_result(harness, "reclaimPlan", {"jobs": []})
    harness.brain.tick = 300
    harness.lua.globals().Controller.Step(harness.controller)
    assert [
        event["phase"]
        for event in _operation_events(harness, "reclaim:prop:501")
    ][-1] == "progressing"

    harness.brain.reclaimables = harness.lua.table_from([])
    harness.brain.tick = 600
    harness.lua.globals().Controller.Step(harness.controller)
    assert [
        event["phase"]
        for event in _operation_events(harness, "reclaim:prop:501")
    ][-1] == "completed"
    assert len(harness.controller.pending) == 0

    harness.brain.tick = 900
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(_operation_events(harness, "reclaim:prop:501")) == 6
    _assert_operation_stream_clean(harness)


def test_reclaim_actor_is_reserved_before_expansion_planning() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    harness.controller.markers.hydro = harness.lua.table_from([])
    engineers = [
        harness.unit(entityId=12, blueprintId="uel0105", position=[10, 2, 20]),
        harness.unit(entityId=13, blueprintId="uel0105", position=[12, 2, 20]),
    ]
    harness.brain.units = harness.lua.table_from(engineers)
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 2,
            "regions": [
                {
                    "key": "home",
                    "state": "secured",
                    "position": [10, 2, 20],
                    "radius": 80,
                }
            ],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "reclaimPlan",
        {
            "jobs": [
                {
                    "id": "reclaim:prop:501",
                    "actorToken": "12:1",
                    "targetKey": "prop:501",
                    "regionKey": "home",
                    "position": [13, 2, 20],
                }
            ]
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    expansion_input = plain(harness.calls.macroPlanExpansion[1])
    assert [unit["token"] for unit in expansion_input["engineers"]] == ["13:1"]


def test_failed_reclaim_command_returns_its_grant_and_never_reports_ordered() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    engineers = [
        harness.unit(
            entityId=entity_id,
            blueprintId="uel0105",
            position=[10 + entity_id, 2, 20],
            blueprintIntel={"VisionRadius": 30},
        )
        for entity_id in (12, 13)
    ]
    props = [
        harness.lua.globals().MakeProp(
            lua_value(
                harness.lua,
                {
                    "entityId": entity_id,
                    "position": [15 + index, 2, 20],
                    "cachePosition": [15 + index, 2, 20],
                    "mass": 100,
                },
            )
        )
        for index, entity_id in enumerate((501, 502))
    ]
    harness.brain.units = harness.lua.table_from(engineers)
    harness.brain.reclaimables = harness.lua.table_from(props)
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"reclaim": {"admitted": True}},
            "grants": [
                {"requestId": "reclaim-1", "lane": "reclaim", "source": "recurring"}
            ],
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "reclaimPlan",
        {
            "jobs": [
                {
                    "id": f"reclaim:prop:{entity_id}",
                    "actorToken": f"{12 + index}:1",
                    "targetKey": f"prop:{entity_id}",
                    "targetValue": 100,
                    "position": [15 + index, 2, 20],
                    "requiresLiveVisionRevalidation": True,
                }
                for index, entity_id in enumerate((501, 502))
            ]
        },
    )
    harness.calls.failReclaimAt = 1

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.reclaim) == 2
    assert harness.calls.reclaim[2].units[1].options.entityId == 13
    first = _operation_events(harness, "reclaim:prop:501")
    second = _operation_events(harness, "reclaim:prop:502")
    assert first[-1]["phase"] == "rejected"
    assert all(event["phase"] != "ordered" for event in first)
    assert [event["phase"] for event in second][-1:] == ["ordered"]
    grants = plain(harness.controller.fundingGrants)
    assert grants["reclaim-1"]["operationId"] == "reclaim:prop:502"


def test_real_ledger_replacement_reissues_once_for_new_exact_actor_generation() -> None:
    harness = make_harness()
    _use_real_macro_job_ledger(harness)
    harness.lua.execute(
        "Policy.Decide = function(snapshot) "
        "table.insert(calls.policySnapshots, snapshot); return {} end"
    )
    original = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([original])
    site, job = _configure_local_expansion(harness)

    harness.lua.globals().Controller.Step(harness.controller)
    assert [
        call.units[1].options.entityId for call in harness.calls.buildMobile.values()
    ] == [72]
    assert plain(harness.controller.pending)["72:1"]["operationId"] == job["id"]

    recycled = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[11, 2, 20],
        canBuild={"ueb1103": True},
    )
    dead = harness.unit(
        entityId=68,
        blueprintId="uel0105",
        position=[11, 2, 20],
        canBuild={"ueb1103": True},
        Dead=True,
    )
    captured = harness.unit(
        entityId=69,
        blueprintId="uel0105",
        position=[11, 2, 20],
        canBuild={"ueb1103": True},
        army=2,
    )
    malformed = harness.unit(
        entityId=70,
        blueprintId="uel0105",
        position=[11, 2, 20],
        canBuild={},
    )
    tank = harness.unit(
        entityId=71,
        blueprintId="uel0201",
        position=[11, 2, 20],
        canBuild={"ueb1103": True},
    )
    replacement = harness.unit(
        entityId=73,
        blueprintId="uel0105",
        position=[13, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from(
        [recycled, dead, captured, malformed, tank, replacement]
    )
    harness.brain.tick = 1

    harness.lua.globals().Controller.Step(harness.controller)

    assert [
        call.units[1].options.entityId for call in harness.calls.buildMobile.values()
    ] == [72, 73]
    pending = plain(harness.controller.pending)
    assert list(pending) == ["73:1"]
    assert pending["73:1"]["operationId"] == job["id"]
    assert pending["73:1"]["operationAttempt"] == 1
    assert plain(harness.controller.reservations)[site["key"]]["actorToken"] == "73:1"
    ledger_job = plain(harness.controller.jobLedger)["jobs"][job["id"]]
    assert ledger_job["actorToken"] == "73:1"
    assert ledger_job["retryCount"] == 1
    ordered = [
        event for event in _operation_events(harness, job["id"])
        if event["phase"] == "ordered"
    ]
    assert [(event["actor"], event["attempt"]) for event in ordered] == [
        ("72:1", "0"),
        ("73:1", "1"),
    ]

    harness.brain.tick = 2
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.buildMobile) == 2


def test_multi_tick_job_claims_prevent_one_exact_engineer_owning_two_active_mex_jobs() -> None:
    harness = make_harness()
    _use_real_macro_job_ledger(harness)
    harness.lua.execute("Policy.Decide = function() return {} end")
    first_engineer = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    replacement = harness.unit(
        entityId=73,
        blueprintId="uel0105",
        position=[39, 2, 40],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([first_engineer, replacement])
    near = plain(harness.controller.markers.mass[1])
    far = plain(harness.controller.markers.mass[2])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 2,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "grants": [
                {"requestId": "mex-1", "lane": "mex_rebuild", "source": "recurring"},
                {"requestId": "mex-2", "lane": "mex_rebuild", "source": "bank"},
            ],
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "expansionPlan",
        {
            "jobs": [
                {
                    "id": "mex:a",
                    "actorToken": "72:1",
                    "targetKey": near["key"],
                    "position": near["position"],
                    "estimatedTravelTicks": 30,
                }
            ],
            "denials": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)
    assert plain(harness.controller.jobLedger)["jobs"]["mex:a"]["actorToken"] == "72:1"
    assert len(harness.calls.buildMobile) == 0

    _set_director_result(
        harness,
        "expansionPlan",
        {
            "jobs": [
                {
                    "id": "mex:b",
                    "actorToken": "72:1",
                    "targetKey": far["key"],
                    "siteKey": far["key"],
                    "position": far["position"],
                    "estimatedTravelTicks": 30,
                }
            ],
            "denials": [],
        },
    )
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    jobs = plain(harness.controller.jobLedger)["jobs"]
    active = {
        job_id: job
        for job_id, job in jobs.items()
        if job["phase"] not in {"completed", "retryable", "cancelled"}
    }
    assert {job["actorToken"] for job in active.values()} == {"72:1", "73:1"}
    assert active["mex:a"]["actorToken"] == "72:1"
    assert active["mex:b"]["actorToken"] == "73:1"
    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].units[1].options.entityId == 73
    assert set(plain(harness.controller.pending)) == {"73:1"}
    assert list(plain(harness.controller.pending)) == ["73:1"]


def test_real_ledger_replacement_fails_closed_without_an_eligible_new_identity() -> None:
    harness = make_harness()
    _use_real_macro_job_ledger(harness)
    harness.lua.execute("Policy.Decide = function() return {} end")
    original = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([original])
    _, job = _configure_local_expansion(harness)
    harness.lua.globals().Controller.Step(harness.controller)

    recycled = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
    )
    malformed = harness.unit(
        entityId=70,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild=None,
    )
    captured = harness.unit(
        entityId=69,
        blueprintId="uel0105",
        position=[10, 2, 20],
        canBuild={"ueb1103": True},
        army=2,
    )
    harness.brain.units = harness.lua.table_from([recycled, malformed, captured])
    harness.brain.tick = 1

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert len(harness.controller.pending) == 0
    ledger_job = plain(harness.controller.jobLedger)["jobs"][job["id"]]
    assert ledger_job["phase"] == "retryable"
    assert ledger_job["failureReason"] == "actor_unavailable"
    assert ledger_job["actorToken"] == "72:1"


def test_real_expansion_recycled_identity_stays_quarantined_when_same_job_returns() -> None:
    harness = make_harness()
    _use_real_macro_expansion_and_job_ledger(harness)
    harness.lua.execute("Policy.Decide = function() return {} end")
    harness.controller.markers.mass = harness.lua.table_from(
        [harness.controller.markers.mass[1]]
    )
    original = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([original])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    first_pending = plain(harness.controller.pending)
    assert list(first_pending) == ["72:1"]
    operation_id = first_pending["72:1"]["operationId"]
    assert [
        call.units[1].options.entityId for call in harness.calls.buildMobile.values()
    ] == [72]

    recycled = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([recycled])
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    quarantined = plain(harness.controller.jobLedger)["jobs"][operation_id]
    assert quarantined["phase"] == "retryable"
    assert quarantined["failureReason"] == "actor_unavailable"
    assert quarantined["actorToken"] == "72:1"
    assert plain(harness.controller.pending) == {}

    harness.brain.tick = 2
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert plain(harness.controller.pending) == {}
    still_quarantined = plain(harness.controller.jobLedger)["jobs"][operation_id]
    assert still_quarantined["phase"] == "retryable"
    assert still_quarantined["actorToken"] == "72:1"


def test_real_expansion_planner_maximizes_jobs_after_site_quarantine() -> None:
    permutations = (
        ((72, 73), False),
        ((73, 72), False),
        ((72, 73), True),
        ((73, 72), True),
    )
    for unit_order, reverse_sites in permutations:
        harness = make_harness()
        _use_real_macro_expansion_and_job_ledger(harness)
        harness.lua.execute("Policy.Decide = function() return {} end")
        near_site = plain(harness.controller.markers.mass[1])
        far_site = plain(harness.controller.markers.mass[2])
        harness.controller.markers.mass = lua_value(harness.lua, [near_site])
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": True,
                "epoch": 1,
                "fundedExpansionSlots": 1,
                "lanes": {"mex_rebuild": {"admitted": True}},
                "regions": [],
                "intents": [],
            },
        )
        original = harness.unit(
            entityId=72,
            blueprintId="uel0105",
            position=[12, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([original])
        harness.lua.globals().Controller.Step(harness.controller)

        first_pending = plain(harness.controller.pending)
        assert list(first_pending) == ["72:1"]
        operation_id = first_pending["72:1"]["operationId"]
        assert len(harness.calls.buildMobile) == 1

        recycled = harness.unit(
            entityId=72,
            blueprintId="uel0105",
            position=[11, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([recycled])
        harness.brain.tick = 1
        harness.lua.globals().Controller.Step(harness.controller)

        quarantined = plain(harness.controller.jobLedger)["jobs"][operation_id]
        assert quarantined["phase"] == "retryable"
        assert quarantined["failureReason"] == "actor_unavailable"
        assert quarantined["actorToken"] == "72:1"
        assert len(harness.calls.buildMobile) == 1

        fresh = harness.unit(
            entityId=73,
            blueprintId="uel0105",
            position=[39, 2, 40],
            canBuild={"ueb1103": True},
        )
        units = {72: recycled, 73: fresh}
        harness.brain.units = harness.lua.table_from(
            [units[entity_id] for entity_id in unit_order]
        )
        sites = [near_site, far_site]
        if reverse_sites:
            sites.reverse()
        harness.controller.markers.mass = lua_value(harness.lua, sites)
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": True,
                "epoch": 2,
                "fundedExpansionSlots": 2,
                "lanes": {"mex_rebuild": {"admitted": True}},
                "regions": [],
                "intents": [],
            },
        )
        harness.brain.tick = 2

        harness.lua.globals().Controller.Step(harness.controller)

        issued = {
            (
                call.units[1].options.entityId,
                round(call.position[1]),
                round(call.position[3]),
            )
            for call in harness.calls.buildMobile.values()
        }
        assert issued == {(72, 12, 20), (73, 12, 20), (72, 40, 40)}
        assert set(plain(harness.controller.pending)) == {"72:2", "73:1"}
        ledger_jobs = plain(harness.controller.jobLedger)["jobs"]
        near_job = next(
            job for job in ledger_jobs.values() if job["siteKey"] == near_site["key"]
        )
        far_job = next(
            job for job in ledger_jobs.values() if job["siteKey"] == far_site["key"]
        )
        assert near_job["actorToken"] == "73:1"
        assert far_job["actorToken"] == "72:2"
        assert near_job["actorLineage"] == {"72": "72:1", "73": "73:1"}
        assert far_job["actorLineage"] == {"72": "72:2"}
        assert near_job["id"] == operation_id
        assert far_job["id"] != operation_id

        harness.brain.tick = 3
        harness.lua.globals().Controller.Step(harness.controller)
        assert len(harness.calls.buildMobile) == 3
        assert set(plain(harness.controller.pending)) == {"72:2", "73:1"}


def test_real_expansion_planner_fails_closed_on_malformed_existing_lineage() -> None:
    harness = make_harness()
    _use_real_macro_expansion_and_job_ledger(harness)
    harness.lua.execute("Policy.Decide = function() return {} end")
    harness.controller.markers.mass = harness.lua.table_from(
        [harness.controller.markers.mass[1]]
    )
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [],
            "intents": [],
        },
    )
    original = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([original])
    harness.lua.globals().Controller.Step(harness.controller)
    operation_id = plain(harness.controller.pending)["72:1"]["operationId"]

    recycled = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[11, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([recycled])
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)
    harness.controller.jobLedger.jobs[operation_id].actorLineage = "malformed"

    fresh = harness.unit(
        entityId=73,
        blueprintId="uel0105",
        position=[13, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([recycled, fresh])
    harness.brain.tick = 2
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert plain(harness.controller.pending) == {}
    preserved = plain(harness.controller.jobLedger)["jobs"][operation_id]
    assert preserved["phase"] == "retryable"
    assert preserved["actorToken"] == "72:1"
    assert preserved["actorLineage"] == "malformed"


def test_recycled_identity_quarantine_survives_until_site_completion() -> None:
    harness = make_harness()
    _use_real_macro_expansion_and_job_ledger(harness)
    harness.lua.execute("Policy.Decide = function() return {} end")
    harness.controller.markers.mass = harness.lua.table_from(
        [harness.controller.markers.mass[1]]
    )
    original = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([original])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)
    operation_id = plain(harness.controller.pending)["72:1"]["operationId"]

    recycled = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    fresh = harness.unit(
        entityId=73,
        blueprintId="uel0105",
        position=[13, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([recycled, fresh])
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    assert [
        call.units[1].options.entityId for call in harness.calls.buildMobile.values()
    ] == [72, 73]
    replaced_job = plain(harness.controller.jobLedger)["jobs"][operation_id]
    assert replaced_job["actorLineage"] == {"72": "72:1", "73": "73:1"}

    harness.brain.units = harness.lua.table_from([recycled])
    harness.brain.tick = 2
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 2
    assert plain(harness.controller.pending) == {}
    quarantined = plain(harness.controller.jobLedger)["jobs"][operation_id]
    assert quarantined["phase"] == "retryable"
    assert quarantined["failureReason"] == "actor_unavailable"
    assert quarantined["actorToken"] == "73:1"
    assert quarantined["actorLineage"] == {"72": "72:1", "73": "73:1"}

    harness.brain.tick = 3
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.buildMobile) == 2
    assert plain(harness.controller.pending) == {}


def test_retryable_quarantine_resets_after_external_owned_completion_and_later_loss() -> None:
    for reverse_completion_units in (False, True):
        harness = make_harness()
        _use_real_macro_expansion_and_job_ledger(harness)
        harness.lua.execute("Policy.Decide = function() return {} end")
        site = plain(harness.controller.markers.mass[1])
        harness.controller.markers.mass = lua_value(harness.lua, [site])
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": True,
                "epoch": 1,
                "fundedExpansionSlots": 1,
                "lanes": {"mex_rebuild": {"admitted": True}},
                "regions": [],
                "intents": [],
            },
        )
        original = harness.unit(
            entityId=72,
            blueprintId="uel0105",
            position=[12, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([original])
        harness.lua.globals().Controller.Step(harness.controller)
        operation_id = plain(harness.controller.pending)["72:1"]["operationId"]

        recycled = harness.unit(
            entityId=72,
            blueprintId="uel0105",
            position=[12, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([recycled])
        harness.brain.tick = 1
        harness.lua.globals().Controller.Step(harness.controller)
        quarantined = plain(harness.controller.jobLedger)["jobs"][operation_id]
        assert quarantined["phase"] == "retryable"
        assert quarantined["actorLineage"] == {"72": "72:1"}

        completed_mex = harness.unit(
            entityId=80,
            blueprintId="ueb1103",
            position=site["position"],
        )
        completion_units = [recycled, completed_mex]
        if reverse_completion_units:
            completion_units.reverse()
        harness.brain.units = harness.lua.table_from(completion_units)
        harness.brain.tick = 2
        harness.lua.globals().Controller.Step(harness.controller)

        completed_job = plain(harness.controller.jobLedger)["jobs"][operation_id]
        assert completed_job["phase"] == "completed"
        assert "failureReason" not in completed_job
        assert len(harness.calls.buildMobile) == 1
        assert plain(harness.controller.pending) == {}

        harness.brain.units = harness.lua.table_from([recycled])
        harness.brain.tick = 3
        harness.lua.globals().Controller.Step(harness.controller)

        assert len(harness.calls.buildMobile) == 2
        restarted = plain(harness.controller.pending)["72:2"]
        assert restarted["operationId"] == operation_id
        assert restarted["operationAttempt"] == 1
        restarted_job = plain(harness.controller.jobLedger)["jobs"][operation_id]
        assert restarted_job["actorToken"] == "72:2"
        assert restarted_job["actorLineage"] == {"72": "72:2"}
        assert restarted_job["retryCount"] == 2

        harness.brain.tick = 4
        harness.lua.globals().Controller.Step(harness.controller)
        assert len(harness.calls.buildMobile) == 2
        assert list(plain(harness.controller.pending)) == ["72:2"]


def test_retryable_quarantine_ignores_captured_and_malformed_mex_boundaries() -> None:
    for reverse_boundary_units in (False, True):
        harness = make_harness()
        _use_real_macro_expansion_and_job_ledger(harness)
        harness.lua.execute("Policy.Decide = function() return {} end")
        site = plain(harness.controller.markers.mass[1])
        harness.controller.markers.mass = lua_value(harness.lua, [site])
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": True,
                "epoch": 1,
                "fundedExpansionSlots": 1,
                "lanes": {"mex_rebuild": {"admitted": True}},
                "regions": [],
                "intents": [],
            },
        )
        original = harness.unit(
            entityId=72,
            blueprintId="uel0105",
            position=[12, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([original])
        harness.lua.globals().Controller.Step(harness.controller)
        operation_id = plain(harness.controller.pending)["72:1"]["operationId"]

        recycled = harness.unit(
            entityId=72,
            blueprintId="uel0105",
            position=[12, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([recycled])
        harness.brain.tick = 1
        harness.lua.globals().Controller.Step(harness.controller)

        captured_mex = harness.unit(
            entityId=80,
            blueprintId="ueb1103",
            position=site["position"],
            army=2,
        )
        malformed_mex = harness.unit(
            entityId=81,
            blueprintId="ueb1103",
            position=site["position"],
            malformedBlueprint=True,
        )
        boundary_units = [recycled, captured_mex, malformed_mex]
        if reverse_boundary_units:
            boundary_units.reverse()
        harness.brain.units = harness.lua.table_from(boundary_units)
        harness.brain.tick = 2
        harness.lua.globals().Controller.Step(harness.controller)

        preserved = plain(harness.controller.jobLedger)["jobs"][operation_id]
        assert preserved["phase"] == "retryable"
        assert preserved["actorLineage"] == {"72": "72:1"}
        assert len(harness.calls.buildMobile) == 1
        assert plain(harness.controller.pending) == {}


def test_expansion_lifecycle_has_no_injected_job_epoch_escape_hatch() -> None:
    assert "jobEpoch" not in source("lua/AI/Overmind4/Controller.lua")


def test_completed_expansion_site_starts_new_attempt_after_real_site_reset() -> None:
    harness = make_harness()
    _use_real_macro_expansion_and_job_ledger(harness)
    harness.lua.execute("Policy.Decide = function() return {} end")
    harness.controller.markers.mass = harness.lua.table_from(
        [harness.controller.markers.mass[1]]
    )
    engineer = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)
    first_pending = plain(harness.controller.pending)["72:1"]
    operation_id = first_pending["operationId"]
    completed_mex = harness.unit(
        entityId=80,
        blueprintId="ueb1103",
        position=first_pending["position"],
    )
    harness.brain.units = harness.lua.table_from([engineer, completed_mex])
    harness.brain.tick = 1

    harness.lua.globals().Controller.Step(harness.controller)

    assert plain(harness.controller.pending) == {}
    completed_job = plain(harness.controller.jobLedger)["jobs"][operation_id]
    assert completed_job["phase"] == "completed"

    recycled = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([recycled])
    harness.brain.tick = 2
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 2
    restarted = plain(harness.controller.pending)["72:2"]
    assert restarted["operationId"] == operation_id
    assert restarted["operationAttempt"] == 1
    restarted_job = plain(harness.controller.jobLedger)["jobs"][operation_id]
    assert restarted_job["actorToken"] == "72:2"
    assert restarted_job["actorLineage"] == {"72": "72:2"}


def test_retryable_job_rejects_malformed_lineage_without_overwriting_history() -> None:
    malformed_changes = (
        {"actorToken": None},
        {"actorToken": "72"},
        {"actorToken": "72:new"},
        {"actorToken": "malformed"},
        {"actorToken": "73:1", "actorLineage": "malformed"},
        {"actorToken": "73:1", "actorLineage": {"73": "73:2"}},
        {"actorToken": "73:1", "siteKey": "other-site"},
        {"actorToken": "73:1", "position": [float("inf"), 2, 20]},
    )
    for changes in malformed_changes:
        harness = make_harness()
        _use_real_macro_job_ledger(harness)
        harness.lua.execute("Policy.Decide = function() return {} end")
        original = harness.unit(
            entityId=72,
            blueprintId="uel0105",
            position=[12, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([original])
        harness.observe()
        recycled = harness.unit(
            entityId=72,
            blueprintId="uel0105",
            position=[12, 2, 20],
            canBuild={"ueb1103": True},
        )
        fresh = harness.unit(
            entityId=73,
            blueprintId="uel0105",
            position=[13, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([recycled, fresh])
        _, template = _configure_local_expansion(harness)
        previous = {
            **template,
            "phase": "retryable",
            "failureReason": "actor_unavailable",
            "retryCount": 1,
        }
        incoming = {**template, "actorToken": "72:2", **changes}
        harness.controller.jobLedger = lua_value(
            harness.lua,
            {
                "epoch": 1,
                "jobs": {template["id"]: previous},
                "releasedActorTokens": [],
            },
        )
        _set_director_result(
            harness, "expansionPlan", {"jobs": [incoming], "denials": []}
        )

        harness.lua.globals().Controller.Step(harness.controller)

        assert len(harness.calls.buildMobile) == 0
        assert plain(harness.controller.pending) == {}
        preserved = plain(harness.controller.jobLedger)["jobs"][template["id"]]
        assert preserved["actorToken"] == "72:1"
        assert preserved["phase"] == "retryable"


def test_conflicting_duplicate_expansion_jobs_fail_closed_in_every_order() -> None:
    conflicts = (
        {"position": [13, 2, 20]},
        {"estimatedTravelTicks": 11},
        {"regionKey": "conflicting-region"},
        {"requiresEscort": True},
        {"payload": {"priority": 2, "tags": ["b", "a"]}},
    )
    for changes in conflicts:
        for reverse in (False, True):
            harness = make_harness()
            _use_real_macro_job_ledger(harness)
            harness.lua.execute("Policy.Decide = function() return {} end")
            engineer = harness.unit(
                entityId=72,
                blueprintId="uel0105",
                position=[12, 2, 20],
                canBuild={"ueb1103": True},
            )
            harness.brain.units = harness.lua.table_from([engineer])
            _, template = _configure_local_expansion(harness)
            conflicting = {**template, **changes}
            jobs = [template, conflicting]
            if reverse:
                jobs.reverse()
            _set_director_result(
                harness,
                "expansionPlan",
                {"jobs": {2: jobs[0], 7: "malformed", 11: jobs[1]}, "denials": []},
            )

            harness.lua.globals().Controller.Step(harness.controller)

            assert len(harness.calls.buildMobile) == 0
            assert plain(harness.controller.pending) == {}
            assert plain(harness.controller.jobLedger)["jobs"] == {}


def test_identical_duplicate_expansion_jobs_dedupe_with_sparse_malformed_input() -> None:
    for indices in ((1, 2), (2, 11), (11, 2)):
        harness = make_harness()
        _use_real_macro_job_ledger(harness)
        harness.lua.execute("Policy.Decide = function() return {} end")
        engineer = harness.unit(
            entityId=72,
            blueprintId="uel0105",
            position=[12, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([engineer])
        _, template = _configure_local_expansion(harness)
        jobs = {
            indices[0]: {**template, "payload": {"tags": ["a", "b"]}},
            7: {"id": template["id"], "position": [float("nan"), 2, 20]},
            indices[1]: {**template, "payload": {"tags": ["a", "b"]}},
            99: "malformed",
        }
        _set_director_result(
            harness, "expansionPlan", {"jobs": jobs, "denials": []}
        )

        harness.lua.globals().Controller.Step(harness.controller)

        assert len(harness.calls.buildMobile) == 1
        assert list(plain(harness.controller.pending)) == ["72:1"]
        assert list(plain(harness.controller.jobLedger)["jobs"]) == [template["id"]]


def test_non_table_new_jobs_do_not_block_a_valid_fresh_identity() -> None:
    for entries in (
        ("malformed", "fresh", 7),
        (7, "fresh", "malformed"),
        (None, "fresh", 7),
        ("fresh", None),
    ):
        harness = make_harness()
        _use_real_macro_job_ledger(harness)
        harness.lua.execute("Policy.Decide = function() return {} end")
        original = harness.unit(
            entityId=72,
            blueprintId="uel0105",
            position=[12, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([original])
        harness.observe()
        recycled = harness.unit(
            entityId=72,
            blueprintId="uel0105",
            position=[11, 2, 20],
            canBuild={"ueb1103": True},
        )
        fresh = harness.unit(
            entityId=73,
            blueprintId="uel0105",
            position=[13, 2, 20],
            canBuild={"ueb1103": True},
        )
        harness.brain.units = harness.lua.table_from([recycled, fresh])
        _, template = _configure_local_expansion(harness)
        fresh_job = {**template, "actorToken": "73:1"}
        jobs = [fresh_job if entry == "fresh" else entry for entry in entries]
        harness.controller.jobLedger = lua_value(
            harness.lua,
            {
                "epoch": 1,
                "jobs": {
                    template["id"]: {
                        **template,
                        "phase": "retryable",
                        "failureReason": "actor_unavailable",
                        "retryCount": 1,
                    }
                },
                "releasedActorTokens": [],
            },
        )
        _set_director_result(
            harness, "expansionPlan", {"jobs": jobs, "denials": []}
        )

        harness.lua.globals().Controller.Step(harness.controller)

        assert [
            call.units[1].options.entityId
            for call in harness.calls.buildMobile.values()
        ] == [73]
        assert list(plain(harness.controller.pending)) == ["73:1"]


def test_failed_expansion_command_becomes_a_new_attempt_then_dedupes_after_success() -> None:
    harness = make_harness()
    _use_real_macro_job_ledger(harness)
    harness.lua.execute("Policy.Decide = function() return {} end")
    engineer = harness.unit(
        entityId=72,
        blueprintId="uel0105",
        position=[12, 2, 20],
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    _, job = _configure_local_expansion(harness)
    harness.calls.failBuildMobile = True

    harness.lua.globals().Controller.Step(harness.controller)

    first_job = plain(harness.controller.jobLedger)["jobs"][job["id"]]
    assert first_job["phase"] == "retryable"
    assert first_job["retryCount"] == 1
    assert first_job["failureReason"] == "command_error"
    assert len(harness.controller.pending) == 0
    assert len(harness.calls.buildMobile) == 1

    harness.calls.failBuildMobile = False
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 2
    pending = plain(harness.controller.pending)["72:1"]
    assert pending["operationAttempt"] == 1
    assert plain(harness.controller.jobLedger)["jobs"][job["id"]]["retryCount"] == 1
    events = _operation_events(harness, job["id"])
    assert [event["phase"] for event in events] == [
        "opportunity",
        "selected",
        "admitted",
        "rejected",
        "selected",
        "admitted",
        "ordered",
    ]
    assert [
        (event["actor"], event["attempt"])
        for event in events
        if event["phase"] in {"rejected", "ordered"}
    ] == [("72:1", "0"), ("72:1", "1")]

    harness.brain.tick = 2
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.buildMobile) == 2


def test_unescorted_expansion_denial_reports_causal_denied_lifecycle() -> None:
    harness = make_harness()
    site = plain(harness.controller.markers.mass[2])
    denial = {
        "id": "mex:front:far",
        "actorToken": "72:1",
        "siteKey": site["key"],
        "regionKey": "front",
        "reason": "escort_not_ready",
    }
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness, "expansionPlan", {"jobs": [], "denials": [denial]}
    )

    harness.lua.globals().Controller.Step(harness.controller)

    events = [
        fields
        for line in harness.logs
        if (fields := parsing.overmind_marker_fields(line)) is not None
        and fields.get("kind") == "operation"
        and fields.get("operation") == denial["id"]
    ]
    assert [event["phase"] for event in events] == [
        "opportunity",
        "selected",
        "denied",
    ]
    assert events[-1]["reason"] == "escort_not_ready"


def test_aggregate_escort_capacity_denial_reports_blocked_job_count() -> None:
    harness = make_harness()
    denial = {
        "id": "expansion:escort-capacity",
        "reason": "escort_capacity_limited",
        "blockedCount": 2,
    }
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "fundedExpansionSlots": 2,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness, "expansionPlan", {"jobs": [], "denials": [denial]}
    )

    harness.lua.globals().Controller.Step(harness.controller)

    events = [
        fields
        for line in harness.logs
        if (fields := parsing.overmind_marker_fields(line)) is not None
        and fields.get("kind") == "operation"
        and fields.get("operation") == denial["id"]
    ]
    assert events[-1]["phase"] == "denied"
    assert events[-1]["reason"] == "escort_capacity_limited"
    assert events[-1]["blocked_count"] == "2"


def test_step_adapts_a_current_visual_bomber_target_into_one_live_raid() -> None:
    harness = make_harness()
    bomber = harness.unit(
        entityId=30,
        blueprintId="uea0103",
        position=[10, 20, 20],
    )
    enemy_engineer = harness.unit(
        entityId=90,
        blueprintId="uel0105",
        army=2,
        position=[40, 2, 40],
        seenNow=True,
        onRadar=True,
    )
    harness.brain.units = harness.lua.table_from([bomber])
    harness.brain.enemies = harness.lua.table_from([enemy_engineer])
    harness.lua.execute(
        "IntelligenceStub.SelectBomberTarget = function() "
        "return { targetToken = '90:1', targetRole = 'engineer', "
        "position = { 40, 2, 40 } } end"
    )

    harness.lua.globals().Controller.Step(harness.controller)
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.aggressive) == 1
    assert plain(harness.controller.bomberMissions)["30:1"]["targetToken"] == "90:1"


def test_t2_hq_causal_operation_starts_only_after_upgrade_success_then_progresses_and_completes() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    source_factory = harness.unit(
        entityId=20,
        blueprintId="ueb0101",
        position=[15, 2, 15],
        canBuild={"ueb0201": True},
    )
    harness.brain.units = harness.lua.table_from([source_factory])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"tech": {"admitted": True}},
            "grants": [
                {
                    "requestId": "tech-1",
                    "lane": "tech",
                    "source": "recurring",
                }
            ],
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "techPlan",
        {"hqAction": "start_t2", "hqSourceToken": "20:1"},
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert [
        event["phase"] for event in _operation_events(harness, "tech:t2_hq")
    ] == ["opportunity", "selected", "admitted", "ordered"]
    pending = plain(harness.controller.pending)["20:1"]
    assert pending["operationId"] == "tech:t2_hq"
    assert pending["operationAttempt"] == 0

    foundation = harness.unit(
        entityId=21,
        blueprintId="ueb0201",
        position=[15, 2, 15],
        fraction=0.4,
    )
    source_factory.options.focusUnit = foundation
    harness.brain.units = harness.lua.table_from([source_factory, foundation])
    _set_director_result(harness, "techPlan", {})
    harness.brain.tick = 10
    harness.lua.globals().Controller.Step(harness.controller)
    assert [
        event["phase"] for event in _operation_events(harness, "tech:t2_hq")
    ] == ["opportunity", "selected", "admitted", "ordered", "progressing"]

    foundation.options.fraction = 1
    harness.brain.tick = 20
    harness.lua.globals().Controller.Step(harness.controller)
    assert [
        event["phase"] for event in _operation_events(harness, "tech:t2_hq")
    ] == [
        "opportunity",
        "selected",
        "admitted",
        "ordered",
        "progressing",
        "completed",
    ]
    assert len(harness.controller.pending) == 0

    harness.brain.tick = 30
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(_operation_events(harness, "tech:t2_hq")) == 6


def test_hybrid_tech_grant_executes_one_staggered_mex_upgrade() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    mex = harness.unit(
        entityId=20,
        blueprintId="ueb1103",
        position=[15, 2, 15],
        canBuild={"ueb1202": True},
    )
    harness.brain.units = harness.lua.table_from([mex])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"tech": {"admitted": True}},
            "grants": [
                {"requestId": "tech-1", "lane": "tech", "source": "hybrid"}
            ],
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "techPlan",
        {
            "hqAction": "hold",
            "mexUpgradeSiteKeys": ["20:1"],
            "mexUpgradeRolesBySite": {"20:1": "mass_extractor_t2"},
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.upgrade) == 1
    assert harness.calls.upgrade[1].blueprintId == "ueb1202"


def test_banked_safe_mex_upgrade_does_not_wait_for_hq_tech_grant() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    mex = harness.unit(
        entityId=20,
        blueprintId="ueb1103",
        position=[15, 2, 15],
        canBuild={"ueb1202": True},
    )
    harness.brain.units = harness.lua.table_from([mex])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"tech": {"admitted": False}},
            "grants": [],
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "techPlan",
        {
            "hqAction": "hold",
            "mexUpgradeSiteKeys": ["20:1"],
            "mexUpgradeRolesBySite": {"20:1": "mass_extractor_t2"},
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.upgrade) == 1
    assert harness.calls.upgrade[1].blueprintId == "ueb1202"


def test_uncontested_remote_owned_mex_is_upgradeable_before_region_package_finishes() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/MacroDirector.lua"))
    harness.lua.execute("MacroDirectorStub.PlanTech = MacroDirector.PlanTech")
    harness.lua.execute("Policy.Decide = function() return {} end")
    mex = harness.unit(
        entityId=20,
        blueprintId="ueb1103",
        position=[150, 2, 150],
        canBuild={"ueb1202": True},
    )
    harness.brain.units = harness.lua.table_from([mex])
    marker = harness.controller.markers.mass[1]
    marker.position = lua_value(harness.lua, [150, 2, 150])
    marker_key = marker.key
    harness.brain.massStoredRatio = 1
    harness.brain.energyStoredRatio = 1
    harness.brain.massTrend = 1
    harness.brain.energyTrend = 10
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"tech": {"admitted": False}},
            "regions": [
                {
                    "key": "remote",
                    "state": "establishing",
                    "memberKeys": [marker_key],
                    "position": [150, 2, 150],
                }
            ],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "intelState",
        {"contacts": {}, "threat": {}, "expansionSafety": {"remote": "safe"}},
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.upgrade) == 1
    assert harness.calls.upgrade[1].blueprintId == "ueb1202"


def test_first_air_staging_facility_is_added_to_a_secured_region_package() -> None:
    harness = make_harness()
    harness.lua.execute(source("lua/AI/Overmind4/MacroDirector.lua"))
    harness.lua.execute(
        "MacroDirectorStub.PlanRegionPackage = MacroDirector.PlanRegionPackage"
    )
    harness.lua.execute("Policy.Decide = function() return {} end")
    engineer = harness.unit(
        entityId=10,
        blueprintId="uel0105",
        position=[80, 2, 80],
        canBuild={"ueb5202": True},
    )
    air = [
        harness.unit(entityId=100 + index, blueprintId="uea0102")
        for index in range(8)
    ]
    harness.brain.units = harness.lua.table_from([engineer, *air])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"mex_rebuild": {"admitted": True}},
            "regions": [
                {"key": "front", "state": "secured", "position": [80, 2, 80]}
            ],
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildMobile) == 1
    assert harness.calls.buildMobile[1].blueprintId == "ueb5202"


def test_failed_t3_hq_command_is_rejected_without_false_ordered_phase_and_retries_by_attempt() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    factory = harness.unit(
        entityId=20,
        blueprintId="ueb0201",
        position=[15, 2, 15],
        canBuild={"ueb0301": True},
    )
    harness.brain.units = harness.lua.table_from([factory])
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {"tech": {"admitted": True}},
            "grants": [{"requestId": "tech-1", "lane": "tech", "source": "bank"}],
            "regions": [],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "techPlan",
        {
            "t3Action": "admit",
            "t3UpgradeRole": "land_factory_t3",
        },
    )
    harness.calls.failUpgrade = True

    harness.lua.globals().Controller.Step(harness.controller)

    first = _operation_events(harness, "tech:t3")
    assert [event["phase"] for event in first] == [
        "opportunity",
        "selected",
        "admitted",
        "rejected",
    ]
    assert all(event.get("attempt") == "0" for event in first[1:])
    assert len(harness.controller.pending) == 0

    harness.calls.failUpgrade = False
    harness.brain.tick = 1
    harness.lua.globals().Controller.Step(harness.controller)

    events = _operation_events(harness, "tech:t3")
    assert [event["phase"] for event in events] == [
        "opportunity",
        "selected",
        "admitted",
        "rejected",
        "selected",
        "admitted",
        "ordered",
    ]
    assert events[-1]["attempt"] == "1"
    assert len(harness.calls.upgrade) == 2

    harness.brain.tick = 2
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.upgrade) == 2

    foundation = harness.unit(
        entityId=21,
        blueprintId="ueb0301",
        blueprintGeneral={"UpgradesFrom": "ueb0201"},
        position=[15, 2, 15],
        fraction=0.4,
    )
    factory.options.focusUnit = foundation
    harness.brain.units = harness.lua.table_from([factory, foundation])
    _set_director_result(harness, "techPlan", {})
    harness.brain.tick = 10
    harness.lua.globals().Controller.Step(harness.controller)
    assert _operation_events(harness, "tech:t3")[-1]["phase"] == "progressing"

    foundation.options.fraction = 1
    harness.brain.tick = 20
    harness.lua.globals().Controller.Step(harness.controller)
    assert _operation_events(harness, "tech:t3")[-1]["phase"] == "completed"
    _assert_operation_stream_clean(harness)


def test_structure_upgrade_supports_the_staggered_t2_to_t3_mex_step() -> None:
    harness = make_harness()
    mex = harness.unit(
        entityId=20,
        blueprintId="ueb1202",
        position=[15, 2, 15],
        canBuild={"ueb1302": True},
    )
    harness.brain.units = harness.lua.table_from([mex])
    observation = harness.observe()

    execute_intents(
        harness,
        [
            {
                "kind": "structure_upgrade",
                "actorToken": "20:1",
                "upgradeRole": "mass_extractor_t3",
                "siteKey": "front-mex",
                "reason": "stagger_mex_upgrade",
            }
        ],
        observation,
    )

    assert len(harness.calls.upgrade) == 1
    assert harness.calls.upgrade[1].blueprintId == "ueb1302"
    assert plain(harness.controller.pending)["20:1"]["buildRole"] == "mass_extractor_t3"


def test_factory_upgrade_supports_funded_t2_to_t3_hq_admission() -> None:
    harness = make_harness()
    factory = harness.unit(
        entityId=20,
        blueprintId="ueb0201",
        position=[15, 2, 15],
        canBuild={"ueb0301": True},
    )
    harness.brain.units = harness.lua.table_from([factory])
    observation = harness.observe()

    execute_intents(
        harness,
        [
            {
                "kind": "factory_upgrade",
                "actorToken": "20:1",
                "upgradeRole": "land_factory_t3",
                "reason": "funded_t3_hq",
            }
        ],
        observation,
    )

    assert len(harness.calls.upgrade) == 1
    assert harness.calls.upgrade[1].blueprintId == "ueb0301"
    assert plain(harness.controller.pending)["20:1"]["buildRole"] == "land_factory_t3"


def test_cross_map_commander_push_and_attack_wave_remain_disabled_in_live_director_mode() -> None:
    harness = make_harness()
    harness.controller.crossMapOffenseEnabled = False
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        position=[10, 2, 20],
    )
    tanks = [
        harness.unit(
            entityId=index,
            blueprintId="uel0201",
            position=[10, 2, 20],
        )
        for index in range(2, 8)
    ]
    harness.brain.units = harness.lua.table_from([acu, *tanks])
    observation = harness.observe()
    tokens = [f"{index}:1" for index in range(2, 8)]

    execute_intents(
        harness,
        [
            {
                "kind": "commander_push",
                "acuToken": "1:1",
                "actorTokens": tokens,
                "position": plain(harness.controller.targetPosition),
            },
            {
                "kind": "attack_wave",
                "actorTokens": tokens,
                "position": plain(harness.controller.targetPosition),
            },
        ],
        observation,
    )

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert len(harness.calls.move) == 0
    assert len(harness.calls.aggressive) == 0


def test_sub_assault_field_stays_assembled_even_when_regions_are_contested() -> None:
    regions = [
        {"key": "a-suspended", "state": "suspended", "position": [500, 2, 500]},
        {"key": "b-planned", "state": "planned", "position": [450, 2, 450]},
        {"key": "c-lost", "state": "lost", "position": [400, 2, 400]},
        {
            "key": "d-secured",
            "state": "secured",
            "productionAnchor": True,
            "position": [350, 2, 350],
        },
        {"key": "e-establishing", "state": "establishing", "position": [250, 2, 250]},
        {"key": "z-contested", "state": "contested", "position": [100, 2, 100]},
    ]
    outcomes = []
    for ordered in (regions, list(reversed(regions))):
        harness = make_harness()
        harness.lua.execute("Policy.Decide = function() return {} end")
        tank = harness.unit(
            entityId=60,
            blueprintId="uel0201",
            position=[20, 2, 20],
        )
        harness.brain.units = harness.lua.table_from([tank])
        _set_director_result(
            harness,
            "macroPlan",
            {
                "valid": True,
                "epoch": 1,
                "lanes": {},
                "regions": ordered,
                "intents": [],
            },
        )
        _set_director_result(
            harness,
            "forcePlan",
            {
                "epoch": 1,
                "assignments": {"field": ["60:1"]},
                "ownershipByToken": {"60:1": "field"},
                "regionAssignments": {},
                "intents": [],
            },
        )

        harness.lua.globals().Controller.Step(harness.controller)

        assert len(harness.calls.aggressive) == 0
        assert len(harness.calls.move) == 0
        outcomes.append(len(harness.calls.aggressive))

    assert outcomes == [0, 0]


def test_sub_assault_field_does_not_snake_to_friendly_secured_mex() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    tanks = [
        harness.unit(entityId=70 + index, blueprintId="uel0201")
        for index in range(19)
    ]
    tokens = [f"{70 + index}:1" for index in range(19)]
    harness.brain.units = harness.lua.table_from(tanks)
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {},
            "regions": [
                {
                    "key": "friendly-mex",
                    "state": "secured",
                    "productionAnchor": True,
                    "position": [350, 2, 350],
                }
            ],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "forcePlan",
        {
            "epoch": 1,
            "assignments": {"field": tokens},
            "ownershipByToken": {token: "field" for token in tokens},
            "regionAssignments": {},
            "intents": [],
        },
    )
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.aggressive) == 0
    assert len(harness.calls.move) == 0


def test_raider_ownership_dispatches_four_unit_groups_to_distinct_regions() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    tanks = [
        harness.unit(
            entityId=60 + index,
            blueprintId="uel0201",
            position=[20, 2, 20],
        )
        for index in range(12)
    ]
    tokens = [f"{60 + index}:1" for index in range(12)]
    regions = [
        {"key": "a-contested", "state": "contested", "position": [100, 2, 100]},
        {"key": "b-planned", "state": "planned", "position": [300, 2, 300]},
        {"key": "c-secured", "state": "secured", "position": [200, 2, 200]},
    ]
    harness.brain.units = harness.lua.table_from(tanks)
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {},
            "regions": regions,
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "forcePlan",
        {
            "epoch": 1,
            "assignments": {"raider": tokens},
            "ownershipByToken": {token: "raider" for token in tokens},
            "regionAssignments": {},
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "intelState",
        {
            "contacts": {
                "enemy-factory": {
                    "token": "enemy-factory",
                    "role": "factory",
                    "position": [150, 2, 150],
                    "lastSeenTick": 0,
                },
                "enemy-mex-a": {
                    "token": "enemy-mex-a",
                    "role": "mass_extractor",
                    "position": [250, 2, 250],
                    "lastSeenTick": 0,
                },
                "enemy-mex-b": {
                    "token": "enemy-mex-b",
                    "role": "mass_extractor_t2",
                    "position": [350, 2, 350],
                    "lastSeenTick": 0,
                },
            },
            "threat": {},
            "expansionSafety": {},
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.aggressive) == 3
    assert sorted(len(call.units) for call in harness.calls.aggressive.values()) == [4, 4, 4]
    assert {
        tuple(plain(call.position)) for call in harness.calls.aggressive.values()
    } == {(150, 2, 150)}

    harness.brain.tick = 101
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.aggressive) == 3


def test_mature_field_force_rallies_then_launches_one_coherent_enemy_spawn_assault() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    tanks = [
        harness.unit(entityId=100 + index, blueprintId="uel0201")
        for index in range(16)
    ] + [
        harness.unit(entityId=116, blueprintId="uel0103"),
        harness.unit(entityId=117, blueprintId="uel0103"),
        harness.unit(entityId=118, blueprintId="uel0104"),
        harness.unit(entityId=119, blueprintId="uel0104"),
    ]
    tokens = [f"{100 + index}:1" for index in range(20)]
    harness.brain.units = harness.lua.table_from(tanks)
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {},
            "regions": [
                {"key": "secured", "state": "secured", "position": [60, 2, 60]}
            ],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "forcePlan",
        {
            "epoch": 1,
            "assignments": {"field": tokens},
            "ownershipByToken": {token: "field" for token in tokens},
            "regionAssignments": {},
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.aggressive) == 0
    assert len(harness.calls.move) == 1
    assert plain(harness.calls.move[1].position) == [60, 2, 60]

    for tank in tanks:
        tank.options.position = harness.lua.table_from([60, 2, 60])
    harness.calls.pathWaypoints = lua_value(
        harness.lua,
        [[80, 2, 80], plain(harness.controller.targetPosition)]
    )
    harness.calls.pathCount = 2
    harness.calls.pathLength = 100
    harness.brain.tick = 10
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.clear) == 1
    assert len(harness.calls.move) == 2
    assert plain(harness.calls.move[2].position) == [80, 2, 80]
    assert len(harness.calls.aggressive) == 1
    assert len(harness.calls.aggressive[1].units) == 20
    assert plain(harness.calls.aggressive[1].position) == plain(
        harness.controller.targetPosition
    )

    harness.brain.tick = 20
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.aggressive) == 1


def test_mature_field_force_pressures_recent_enemy_factory_instead_of_empty_spawn() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    tanks = [
        harness.unit(entityId=100 + index, blueprintId="uel0201")
        for index in range(16)
    ] + [
        harness.unit(entityId=116, blueprintId="uel0103"),
        harness.unit(entityId=117, blueprintId="uel0103"),
        harness.unit(entityId=118, blueprintId="uel0104"),
        harness.unit(entityId=119, blueprintId="uel0104"),
    ]
    tokens = [f"{100 + index}:1" for index in range(20)]
    harness.brain.units = harness.lua.table_from(tanks)
    harness.brain.tick = 500
    _set_director_result(
        harness,
        "macroPlan",
        {
            "valid": True,
            "epoch": 1,
            "lanes": {},
            "regions": [
                {"key": "secured", "state": "secured", "position": [60, 2, 60]}
            ],
            "intents": [],
        },
    )
    _set_director_result(
        harness,
        "intelState",
        {
            "contacts": {
                "enemy-factory": {
                    "token": "enemy-factory",
                    "role": "factory",
                    "position": [75, 2, 190],
                    "lastSeenTick": 450,
                }
            },
            "threat": {},
            "expansionSafety": {},
        },
    )
    _set_director_result(
        harness,
        "forcePlan",
        {
            "epoch": 1,
            "assignments": {"field": tokens},
            "ownershipByToken": {token: "field" for token in tokens},
            "regionAssignments": {},
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.aggressive) == 0
    for tank in tanks:
        tank.options.position = harness.lua.table_from([60, 2, 60])
    harness.brain.tick = 510
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.aggressive) == 1
    assert plain(harness.calls.aggressive[1].position) == [75, 2, 190]


def test_visible_ground_cluster_dispatches_regional_response_force() -> None:
    harness = make_harness()
    harness.lua.execute("Policy.Decide = function() return {} end")
    responders = [
        harness.unit(entityId=200 + index, blueprintId="uel0201")
        for index in range(8)
    ]
    response_tokens = [f"{200 + index}:1" for index in range(8)]
    enemies = [
        harness.unit(
            entityId=300 + index,
            blueprintId="uel0201",
            blueprintCategories=["MOBILE", "LAND", "DIRECTFIRE", "TECH1"],
            army=2,
            position=[200, 2, 200],
            seenNow=True,
            onRadar=True,
        )
        for index in range(4)
    ]
    harness.brain.units = harness.lua.table_from(responders)
    harness.brain.enemies = harness.lua.table_from(enemies)
    _set_director_result(
        harness,
        "macroPlan",
        {"valid": True, "epoch": 1, "lanes": {}, "regions": [], "intents": []},
    )
    _set_director_result(
        harness,
        "forcePlan",
        {
            "epoch": 1,
            "assignments": {"response": response_tokens},
            "ownershipByToken": {token: "response" for token in response_tokens},
            "regionAssignments": {},
            "intents": [],
        },
    )

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.aggressive) == 1
    assert plain(harness.calls.aggressive[1].position) == [200, 2, 200]

    for enemy in enemies:
        enemy.options.position = harness.lua.table_from([205, 2, 205])
    harness.brain.tick = 9
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.aggressive) == 1

    harness.brain.tick = 60
    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.aggressive) == 2
