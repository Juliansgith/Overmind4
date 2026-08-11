from __future__ import annotations

from typing import Any

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
            "lanes": {"air_production": {"admitted": True}},
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
                "lanes": {},
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
    harness.brain.units = harness.lua.table_from(
        [land_escort, aa_escort, engineer]
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
        "state": "establishing",
        "position": remote_site["position"],
        "requiresGarrison": True,
        "requiresAntiAir": True,
    }

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
                "garrison": ["70:1", "71:1"],
                "field": [],
                "response": [],
                "raider": [],
                "unassigned": [],
            },
            "ownershipByToken": {"70:1": "garrison", "71:1": "garrison"},
            "regionAssignments": {
                "front": {
                    "actorTokens": ["70:1", "71:1"],
                    "antiAirCount": 1,
                    "ready": True,
                }
            },
            "intents": [],
        }
        _set_director_result(harness, "forcePlan", force_plan)

    set_epoch(1)
    harness.lua.globals().Controller.Step(harness.controller)

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
        "travelling",
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
