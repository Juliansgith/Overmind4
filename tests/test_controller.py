from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from conftest import runtime, source
from test_policy import lua_value, plain


@dataclass
class ControllerHarness:
    lua: Any
    brain: Any
    controller: Any
    calls: Any
    marker_sources: Any
    logs: list[str]

    def unit(self, **options: Any) -> Any:
        return self.lua.globals().MakeUnit(lua_value(self.lua, options))

    def observe(self) -> Any:
        return self.lua.globals().Controller.Observe(self.controller)


def make_harness() -> ControllerHarness:
    lua = runtime()
    logs: list[str] = []
    lua.globals().LOG = logs.append
    lua.execute(
        r"""
        categories = { ALLUNITS = 'ALLUNITS', MOBILE = 'MOBILE' }
        calls = {
            own = {}, enemy = {}, nav = {}, canBuild = {}, terrain = {},
            buildMobile = {}, buildFactory = {}, rally = {}, aggressive = {},
            move = {}, clear = {}, waits = {},
        }

        function Count(tableValue)
            local count = 0
            for _, _ in pairs(tableValue or {}) do count = count + 1 end
            return count
        end

        function MakeUnit(options)
            local unit = { options = options, Dead = options.Dead or false }
            function unit:BeenDestroyed() return self.options.destroyed or false end
            function unit:GetArmy() return self.options.army or 1 end
            function unit:GetEntityId() return self.options.entityId or 1 end
            function unit:GetBlueprint()
                if self.options.malformedBlueprint then return {} end
                return { BlueprintId = self.options.blueprintId or 'uel0001' }
            end
            function unit:GetFractionComplete() return self.options.fraction == nil and 1 or self.options.fraction end
            function unit:GetPosition() return self.options.position or { 10, 2, 10 } end
            function unit:GetHealth() return self.options.health or 100 end
            function unit:GetMaxHealth() return self.options.maxHealth or 100 end
            function unit:GetCommandQueue() return self.options.queue or {} end
            function unit:IsUnitState(name)
                local states = self.options.states or {}
                return states[name] or false
            end
            function unit:IsPaused() return self.options.paused or false end
            function unit:CanBuild(blueprintId)
                local canBuild = self.options.canBuild or {}
                return canBuild[blueprintId] == true
            end
            return unit
        end

        brain = {
            Army = 1,
            units = {},
            enemies = {},
            tick = 0,
            startX = 10,
            startZ = 20,
            faction = 1,
            canBuildAt = true,
        }
        function brain:GetArmyStartPos() return self.startX, self.startZ end
        function brain:GetFactionIndex() return self.faction end
        function brain:GetListOfUnits(category, idle, requireBuilt)
            table.insert(calls.own, { category, idle, requireBuilt })
            return self.units
        end
        function brain:GetUnitsAroundPoint(category, position, radius, alliance)
            table.insert(calls.enemy, { category, {position[1], position[2], position[3]}, radius, alliance })
            return self.enemies
        end
        function brain:GetEconomyTrend(resource) return resource == 'ENERGY' and -1 or 1 end
        function brain:GetEconomyStoredRatio(resource) return resource == 'ENERGY' and 0.2 or 0.5 end
        function brain:GetEconomyIncome(resource) return resource == 'ENERGY' and 20 or 2 end
        function brain:GetEconomyUsage(resource) return resource == 'ENERGY' and 21 or 1 end
        function brain:CanBuildStructureAt(blueprintId, position)
            table.insert(calls.canBuild, { blueprintId, {position[1], position[2], position[3]} })
            if type(self.canBuildAt) == 'function' then return self.canBuildAt(blueprintId, position) end
            return self.canBuildAt
        end

        markerSources = {
            Mass = {
                { Name = 'Far Mass', Position = { 40, 3, 40 } },
                { Name = 'Near Mass', Position = { 12, 3, 20 } },
                { Name = 'No Path', Position = { 999, 3, 20 } },
            },
            Hydrocarbon = { { Name = 'Hydro 1', Position = { 25, 3, 25 } } },
            Spawn = {
                { Name = 'ARMY_1', Position = { 10, 3, 20 }, IsOccupied = true },
                { Name = 'ARMY_2', Position = { 110, 3, 120 }, IsOccupied = true },
                { Name = 'ARMY_3', Position = { 60, 3, 60 }, IsOccupied = false },
            },
        }
        MarkerUtilities = { GetMarkersByType = function(kind)
            local value = markerSources[kind] or {}
            return value, Count(value)
        end }
        NavUtils = {
            generated = false,
            IsGenerated = function() return NavUtils.generated end,
            Generate = function() NavUtils.generated = true; NavUtils.generateCalls = (NavUtils.generateCalls or 0) + 1 end,
            CanPathTo = function(layer, origin, destination)
                table.insert(calls.nav, { layer, {origin[1], origin[2], origin[3]}, {destination[1], destination[2], destination[3]} })
                return destination[1] ~= 999
            end,
        }

        function GetGameTick() return brain.tick end
        function GetTerrainHeight(x, z) table.insert(calls.terrain, {x, z}); return x + z / 100 end
        function GetSurfaceHeight(x, z) return GetTerrainHeight(x, z) end
        function IssueBuildMobile(units, position, blueprintId, alternatives)
            table.insert(calls.buildMobile, { units = units, position = position, blueprintId = blueprintId, alternatives = alternatives, argc = 4 })
            return { kind = 'build-mobile' }
        end
        function IssueBuildFactory(units, blueprintId, count)
            table.insert(calls.buildFactory, { units = units, blueprintId = blueprintId, count = count })
            return { kind = 'build-factory' }
        end
        function IssueFactoryRallyPoint(units, position)
            table.insert(calls.rally, { units = units, position = position })
            return { kind = 'rally' }
        end
        function IssueAggressiveMove(units, position)
            table.insert(calls.aggressive, { units = units, position = position })
            return { kind = 'aggressive' }
        end
        function IssueMove(units, position)
            table.insert(calls.move, { units = units, position = position })
            return { kind = 'move' }
        end
        function IssueClearCommands(units)
            table.insert(calls.clear, { units = units })
            return { kind = 'clear' }
        end
        function WaitTicks(ticks) table.insert(calls.waits, ticks) end
        """
    )
    lua.execute(source("lua/AI/Overmind4/Telemetry.lua"))
    lua.execute(source("lua/AI/Overmind4/Catalog.lua"))
    lua.execute(source("lua/AI/Overmind4/Policy.lua"))
    modules = {
        "/mods/overmind4/lua/AI/Overmind4/Telemetry.lua": lua.table_from({"Telemetry": lua.globals().Telemetry}),
        "/mods/overmind4/lua/AI/Overmind4/Catalog.lua": lua.table_from({"Catalog": lua.globals().Catalog}),
        "/mods/overmind4/lua/AI/Overmind4/Policy.lua": lua.table_from({"Policy": lua.globals().Policy}),
        "/lua/sim/MarkerUtilities.lua": lua.globals().MarkerUtilities,
        "/lua/sim/NavUtils.lua": lua.globals().NavUtils,
    }

    def importer(path: str):
        try:
            return modules[path]
        except KeyError as error:
            raise AssertionError(f"unexpected Controller import: {path}") from error

    lua.globals()["import"] = importer
    lua.execute(source("lua/AI/Overmind4/Controller.lua"))
    brain = lua.globals().brain
    controller = lua.globals().Controller.Create(brain)
    return ControllerHarness(
        lua=lua,
        brain=brain,
        controller=controller,
        calls=lua.globals().calls,
        marker_sources=lua.globals().markerSources,
        logs=logs,
    )


def execute_intents(harness: ControllerHarness, intents: list[dict[str, Any]], observation: Any | None = None) -> None:
    observation = observation or harness.observe()
    harness.lua.globals().Controller.Execute(
        harness.controller,
        lua_value(harness.lua, intents),
        observation,
    )


def test_create_converts_two_value_start_position_and_generates_navigation_once() -> None:
    harness = make_harness()
    assert plain(harness.controller.basePosition) == [10, 10.2, 20]
    assert harness.lua.globals().NavUtils.generateCalls == 1
    harness.lua.globals().Controller.InitializeMap(harness.controller)
    assert harness.lua.globals().NavUtils.generateCalls == 1


def test_markers_are_copied_sorted_and_reachability_requires_literal_true() -> None:
    harness = make_harness()
    mass = plain(harness.controller.markers.mass)
    assert [site["name"] for site in mass] == ["Near Mass", "Far Mass", "No Path"]
    assert [site["reachable"] for site in mass] == [True, True, False]
    harness.marker_sources.Mass[1].Position[1] = 777
    assert harness.controller.markers.mass[1].position[1] == 12


def test_public_target_is_farthest_other_spawn_and_staging_is_quarter_vector() -> None:
    harness = make_harness()
    assert plain(harness.controller.targetPosition) == [110, 3, 120]
    staging = plain(harness.controller.stagingPosition)
    assert 32 <= staging[0] <= 35
    assert 42 <= staging[2] <= 45


def test_observe_uses_exact_bounded_own_and_current_intel_enemy_queries() -> None:
    harness = make_harness()
    harness.brain.units = lua_value(harness.lua, [])
    enemy = harness.unit(entityId=80, blueprintId="url0201", position=[16, 4, 26])
    harness.brain.enemies = harness.lua.table_from([enemy])
    observation = plain(harness.observe())
    assert plain(harness.calls.own) == [["ALLUNITS", False, False]]
    enemy_call = plain(harness.calls.enemy)[0]
    assert enemy_call[0] == "MOBILE" and enemy_call[3] == "Enemy"
    assert observation["enemyContact"] == {"position": [16, 4, 26], "immediate": True}
    assert "blueprintId" not in observation["enemyContact"]


def test_observe_filters_destroyed_dead_captured_and_malformed_units_explicitly() -> None:
    harness = make_harness()
    good = harness.unit(entityId=1, blueprintId="UEL0001", position=[10, 2, 20])
    destroyed = harness.unit(entityId=2, blueprintId="uel0105", destroyed=True)
    dead = harness.unit(entityId=3, blueprintId="uel0105", Dead=True)
    captured = harness.unit(entityId=4, blueprintId="uel0105", army=2)
    malformed = harness.unit(entityId=5, malformedBlueprint=True)
    harness.brain.units = harness.lua.table_from([destroyed, captured, good, malformed, dead])
    units = plain(harness.observe().units)
    assert [(unit["token"], unit["role"]) for unit in units] == [("1:1", "acu")]


def test_entity_id_reuse_gets_a_new_generation_token() -> None:
    harness = make_harness()
    first = harness.unit(entityId=9, blueprintId="uel0105")
    harness.brain.units = harness.lua.table_from([first])
    assert harness.observe().units[1].token == "9:1"
    second = harness.unit(entityId=9, blueprintId="uel0105")
    harness.brain.units = harness.lua.table_from([second])
    assert harness.observe().units[1].token == "9:2"


def test_incomplete_paused_upgrading_busy_and_cannot_build_are_fail_closed() -> None:
    harness = make_harness()
    factory_id = "ueb0101"
    units = [
        harness.unit(entityId=1, blueprintId=factory_id, fraction=0.5, canBuild={"uel0201": True}),
        harness.unit(entityId=2, blueprintId=factory_id, paused=True, canBuild={"uel0201": True}),
        harness.unit(entityId=3, blueprintId=factory_id, states={"Upgrading": True}, canBuild={"uel0201": True}),
        harness.unit(entityId=4, blueprintId=factory_id, queue=[{"command": 1}], canBuild={"uel0201": True}),
        harness.unit(entityId=5, blueprintId=factory_id, canBuild={"uel0201": False}),
    ]
    harness.brain.units = harness.lua.table_from(units)
    observed = plain(harness.observe().units)
    assert [unit["idle"] for unit in observed[:4]] == [False, False, False, False]
    assert observed[4]["canBuild"]["tank"] is False


def test_build_mobile_uses_exact_four_arguments_terrain_height_and_empty_alternatives() -> None:
    harness = make_harness()
    acu = harness.unit(entityId=1, blueprintId="uel0001", canBuild={"ueb1101": True})
    harness.brain.units = harness.lua.table_from([acu])
    observation = harness.observe()
    execute_intents(
        harness,
        [{"kind": "build_structure", "actorToken": "1:1", "buildRole": "power_generator", "position": [30, 0, 40]}],
        observation,
    )
    call = harness.calls.buildMobile[1]
    assert call.argc == 4 and call.blueprintId == "ueb1101"
    assert plain(call.position) == [30, 30.4, 40]
    assert len(call.alternatives) == 0


def test_build_rechecks_can_build_at_and_actor_capability_before_order() -> None:
    harness = make_harness()
    acu = harness.unit(entityId=1, blueprintId="uel0001", canBuild={"ueb1101": False})
    harness.brain.units = harness.lua.table_from([acu])
    execute_intents(harness, [{"kind": "build_structure", "actorToken": "1:1", "buildRole": "power_generator", "position": [30, 0, 40]}])
    assert len(harness.calls.buildMobile) == 0
    acu.options.canBuild["ueb1101"] = True
    harness.brain.canBuildAt = False
    execute_intents(harness, [{"kind": "build_structure", "actorToken": "1:1", "buildRole": "power_generator", "position": [30, 0, 40]}])
    assert len(harness.calls.buildMobile) == 0


def test_factory_order_has_exact_blueprint_and_count_and_is_not_reissued_while_pending() -> None:
    harness = make_harness()
    factory = harness.unit(entityId=2, blueprintId="ueb0101", canBuild={"uel0201": True})
    harness.brain.units = harness.lua.table_from([factory])
    intent = {"kind": "factory_build", "actorToken": "2:1", "buildRole": "tank"}
    observation = harness.observe()
    execute_intents(harness, [intent], observation)
    execute_intents(harness, [intent], observation)
    assert len(harness.calls.buildFactory) == 1
    assert harness.calls.buildFactory[1].blueprintId == "uel0201"
    assert harness.calls.buildFactory[1].count == 1


def test_pending_is_not_accepted_or_released_before_three_ticks_then_releases_rejected_order() -> None:
    harness = make_harness()
    acu = harness.unit(entityId=1, blueprintId="uel0001", canBuild={"ueb1101": True})
    harness.brain.units = harness.lua.table_from([acu])
    intent = {"kind": "build_structure", "actorToken": "1:1", "buildRole": "power_generator", "siteKey": "p1", "position": [30, 0, 40]}
    observation = harness.observe()
    execute_intents(harness, [intent], observation)
    assert harness.controller.pending["1:1"] is not None
    for tick in (1, 2, 3):
        harness.brain.tick = tick
        harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())
        assert harness.controller.pending["1:1"] is not None
    harness.brain.tick = 13
    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())
    assert harness.controller.pending["1:1"] is None
    assert harness.controller.reservations.p1 is None


def test_site_reservation_deduplicates_and_releases_on_death_capture_and_occupation() -> None:
    harness = make_harness()
    first = harness.unit(entityId=1, blueprintId="uel0105", canBuild={"ueb1103": True})
    second = harness.unit(entityId=2, blueprintId="uel0105", canBuild={"ueb1103": True})
    harness.brain.units = harness.lua.table_from([first, second])
    intents = [
        {"kind": "build_structure", "actorToken": "1:1", "buildRole": "mass_extractor", "siteKey": "m", "position": [30, 0, 40]},
        {"kind": "build_structure", "actorToken": "2:1", "buildRole": "mass_extractor", "siteKey": "m", "position": [30, 0, 40]},
    ]
    execute_intents(harness, intents)
    assert len(harness.calls.buildMobile) == 1
    first.options.destroyed = True
    harness.brain.tick = 4
    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())
    assert harness.controller.reservations.m is None

    first.options.destroyed = False
    first.options.army = 1
    harness.brain.tick = 20
    execute_intents(harness, [intents[0]])
    first.options.army = 2
    harness.brain.tick = 24
    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())
    assert harness.controller.reservations.m is None


def test_rally_is_issued_once_per_factory_generation() -> None:
    harness = make_harness()
    factory = harness.unit(entityId=2, blueprintId="ueb0101")
    harness.brain.units = harness.lua.table_from([factory])
    observation = harness.observe()
    intent = {"kind": "rally", "actorToken": "2:1", "position": [35, 0, 45]}
    execute_intents(harness, [intent], observation)
    execute_intents(harness, [intent], observation)
    assert len(harness.calls.rally) == 1


def test_wave_orders_only_named_combat_references_in_deterministic_order() -> None:
    harness = make_harness()
    tank = harness.unit(entityId=9, blueprintId="uel0201")
    arty = harness.unit(entityId=4, blueprintId="uel0103")
    scout = harness.unit(entityId=2, blueprintId="uel0101")
    harness.brain.units = harness.lua.table_from([tank, scout, arty])
    observation = harness.observe()
    execute_intents(harness, [{"kind": "attack_wave", "actorTokens": ["9:1", "2:1", "4:1"], "position": [110, 0, 120]}], observation)
    call = harness.calls.aggressive[1]
    assert len(call.units) == 2
    assert [call.units[index].GetEntityId(call.units[index]) for index in (1, 2)] == [4, 9]


def test_retreat_and_defense_clear_only_once_for_same_intent_signature() -> None:
    harness = make_harness()
    acu = harness.unit(entityId=1, blueprintId="uel0001")
    tank = harness.unit(entityId=2, blueprintId="uel0201")
    harness.brain.units = harness.lua.table_from([acu, tank])
    observation = harness.observe()
    retreat = {"kind": "retreat", "actorToken": "1:1", "position": [10, 0, 20]}
    execute_intents(harness, [retreat], observation)
    execute_intents(harness, [retreat], observation)
    assert len(harness.calls.clear) == 1 and len(harness.calls.move) == 1
    defense = {"kind": "defend_wave", "actorTokens": ["2:1"], "position": [20, 0, 20]}
    execute_intents(harness, [defense], observation)
    execute_intents(harness, [defense], observation)
    assert len(harness.calls.clear) == 2 and len(harness.calls.aggressive) == 1


def test_controller_run_yields_positive_ticks_and_recovers_from_step_exception() -> None:
    harness = make_harness()
    harness.lua.execute(
        """
        originalStep = Controller.Step
        Controller.Step = function(controller)
            controller.testSteps = (controller.testSteps or 0) + 1
            if controller.testSteps == 1 then error('boom') end
            controller.stopped = true
        end
        """
    )
    # AIBrain:ForkThread prepends its owning brain before explicit arguments.
    harness.lua.globals().Controller.Run(harness.brain, harness.controller)
    assert harness.controller.testSteps == 2
    assert all(ticks > 0 for ticks in plain(harness.calls.waits))
    assert any("event=step_error" in line for line in harness.logs)


def test_snapshot_telemetry_is_rate_limited_and_phase_changes_are_explicit() -> None:
    harness = make_harness()
    harness.brain.units = harness.lua.table_from([])
    for tick in (0, 1, 50, 299, 300, 301):
        harness.brain.tick = tick
        harness.lua.globals().Controller.Step(harness.controller)
    snapshots = [line for line in harness.logs if "event=snapshot" in line]
    phases = [line for line in harness.logs if "event=phase" in line]
    assert len(snapshots) <= 2
    assert len(phases) == 1


def test_observation_is_single_pass_for_one_thousand_units() -> None:
    harness = make_harness()
    units = [harness.unit(entityId=index, blueprintId="uel0201", position=[index, 2, 20]) for index in range(1, 1001)]
    harness.brain.units = harness.lua.table_from(units)
    observation = harness.observe()
    assert len(observation.units) == 1000
    assert len(harness.calls.own) == 1 and len(harness.calls.enemy) == 1
