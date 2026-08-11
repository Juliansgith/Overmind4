from __future__ import annotations

from typing import Any

from test_controller import execute_intents, make_harness
from test_policy import lua_value, plain


def _set_director_result(harness: Any, name: str, value: dict[str, Any]) -> None:
    harness.lua.globals().directorResults[name] = lua_value(harness.lua, value)


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
