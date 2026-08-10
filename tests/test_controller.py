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
            function unit:IsIdleState()
                if self.options.idleState ~= nil then return self.options.idleState end
                local states = self.options.states or {}
                return not (
                    self.options.paused
                    or states.Building
                    or states.Upgrading
                    or states.Enhancing
                    or states.Moving
                )
            end
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
            for _, factory in ipairs(units) do
                factory.options.queue = { { commandType = 7, blueprintId = blueprintId } }
                factory.options.idleState = false
                factory.options.states = factory.options.states or {}
                factory.options.states.Building = true
            end
            return { kind = 'build-factory' }
        end
        function IssueFactoryRallyPoint(units, position)
            table.insert(calls.rally, { units = units, position = position })
            for _, factory in ipairs(units) do
                factory.options.queue = {
                    { commandType = 2, type = 'Move', position = position, isRally = true },
                }
                factory.options.idleState = true
            end
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
        harness.unit(entityId=4, blueprintId=factory_id, queue=[{"commandType": 7}], idleState=False, states={"Building": True}, canBuild={"uel0201": True}),
        harness.unit(entityId=5, blueprintId=factory_id, canBuild={"uel0201": False}),
    ]
    harness.brain.units = harness.lua.table_from(units)
    observed = plain(harness.observe().units)
    assert [unit["idle"] for unit in observed[:4]] == [False, False, False, False]
    assert observed[4]["canBuild"]["tank"] is False


def test_rally_only_queue_is_idle_but_active_build_and_moving_actor_are_busy() -> None:
    harness = make_harness()
    rally = {"commandType": 2, "type": "Move", "position": [35, 2, 45], "isRally": True}
    rallied_factory = harness.unit(
        entityId=1,
        blueprintId="ueb0101",
        queue=[rally],
        idleState=True,
        canBuild={"uel0105": True},
    )
    building_factory = harness.unit(
        entityId=2,
        blueprintId="ueb0101",
        queue=[{"commandType": 7, "blueprintId": "uel0201"}],
        idleState=False,
        states={"Building": True},
        canBuild={"uel0201": True},
    )
    moving_engineer = harness.unit(
        entityId=3,
        blueprintId="uel0105",
        queue=[{"commandType": 2}],
        idleState=False,
        states={"Moving": True},
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([rallied_factory, building_factory, moving_engineer])

    observed = plain(harness.observe().units)

    assert [record["idle"] for record in observed] == [True, False, False]
    assert [record["busy"] for record in observed] == [False, True, True]


def test_rally_integration_leaves_factory_eligible_for_production_next_step() -> None:
    harness = make_harness()
    factory = harness.unit(
        entityId=1,
        blueprintId="ueb0101",
        idleState=True,
        canBuild={"uel0105": True},
    )
    harness.brain.units = harness.lua.table_from([factory])

    harness.lua.globals().Controller.Step(harness.controller)
    assert len(harness.calls.rally) == 1
    assert factory.options.queue[1].isRally is True

    harness.brain.tick = 10
    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.buildFactory) == 1
    assert harness.calls.buildFactory[1].blueprintId == "uel0105"


def test_same_name_resource_markers_get_coordinate_identity_and_stable_sort() -> None:
    harness = make_harness()
    duplicate_name_markers = [
        {"Name": "Unknown", "Position": [12, 3, 20]},
        {"Name": "Unknown", "Position": [8, 3, 20]},
        {"Name": "Unknown", "Position": [12, 3, 20]},
    ]
    harness.marker_sources.Mass = lua_value(harness.lua, duplicate_name_markers)
    first = harness.lua.globals().Controller.Create(harness.brain)
    first_sites = plain(first.markers.mass)

    harness.marker_sources.Mass = lua_value(harness.lua, list(reversed(duplicate_name_markers)))
    second = harness.lua.globals().Controller.Create(harness.brain)
    second_sites = plain(second.markers.mass)

    first_keys = [site["key"] for site in first_sites]
    second_keys = [site["key"] for site in second_sites]
    assert first_keys == second_keys
    assert len(first_keys) == len(set(first_keys)) == 2

    first.reservations[first_keys[0]] = lua_value(harness.lua, {"actorToken": "1:1", "issuedTick": 0})
    snapshot = plain(harness.lua.globals().Controller.Observe(first))
    reserved_by_key = {site["key"]: site["reserved"] for site in snapshot["sites"]["mass"]}
    assert reserved_by_key[first_keys[0]] is True
    assert reserved_by_key[first_keys[1]] is False


def test_resource_buildability_probes_only_chosen_site_then_advances() -> None:
    harness = make_harness()
    harness.marker_sources.Mass = lua_value(
        harness.lua,
        [
            {"Name": "Near", "Position": [12, 3, 20]},
            {"Name": "Far", "Position": [40, 3, 40]},
        ],
    )
    harness.marker_sources.Hydrocarbon = lua_value(harness.lua, [])
    harness.lua.execute(
        "brain.canBuildAt = function(blueprintId, position) return position[1] ~= 12 end"
    )
    controller = harness.lua.globals().Controller.Create(harness.brain)
    harness.controller = controller
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        idleState=True,
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([engineer])

    observation = harness.lua.globals().Controller.Observe(controller)
    mex_probes_before = [
        call for call in plain(harness.calls.canBuild)
        if call[0] == "ueb1103"
    ]
    near = controller.markers.mass[1]
    execute_intents(
        harness,
        [{"kind": "build_structure", "actorToken": "1:1", "buildRole": "mass_extractor", "siteKey": near.key, "position": plain(near.position)}],
        observation,
    )
    sites = plain(harness.lua.globals().Controller.Observe(controller).sites.mass)
    mex_probes_after = [
        call for call in plain(harness.calls.canBuild)
        if call[0] == "ueb1103"
    ]

    assert mex_probes_before == []
    assert len(mex_probes_after) == 1
    assert mex_probes_after[0][1][0] == 12
    assert [(site["name"], site["buildable"]) for site in sites] == [
        ("Near", False),
        ("Far", True),
    ]


def test_silently_rejected_resource_site_backs_off_then_expires() -> None:
    harness = make_harness()
    harness.marker_sources.Mass = lua_value(
        harness.lua,
        [
            {"Name": "Near", "Position": [12, 3, 20]},
            {"Name": "Far", "Position": [40, 3, 40]},
        ],
    )
    harness.marker_sources.Hydrocarbon = lua_value(harness.lua, [])
    harness.lua.execute(
        """
        function brain:GetEconomyTrend(resource) return 1 end
        function brain:GetEconomyStoredRatio(resource) return 0.8 end
        """
    )
    controller = harness.lua.globals().Controller.Create(harness.brain)
    harness.controller = controller
    engineer = harness.unit(
        entityId=1,
        blueprintId="uel0105",
        idleState=True,
        canBuild={"ueb1103": True},
    )
    harness.brain.units = harness.lua.table_from([engineer])
    near_key = controller.markers.mass[1].key
    first = controller.markers.mass[1].position
    observation = harness.lua.globals().Controller.Observe(controller)
    assert not any(call[0] == "ueb1103" for call in plain(harness.calls.canBuild))
    execute_intents(
        harness,
        [{"kind": "build_structure", "actorToken": "1:1", "buildRole": "mass_extractor", "siteKey": near_key, "position": plain(first)}],
        observation,
    )

    harness.brain.tick = 13
    rejected = harness.lua.globals().Controller.Observe(controller)
    harness.lua.globals().Controller.Reconcile(controller, rejected)
    after_rejection = harness.lua.globals().Controller.Observe(controller)
    sites = plain(after_rejection.sites.mass)
    next_intents = plain(harness.lua.globals().Policy.Decide(after_rejection))

    assert [(site["name"], site["buildable"]) for site in sites] == [
        ("Near", False),
        ("Far", True),
    ]
    next_mass = next(
        intent for intent in next_intents
        if intent.get("kind") == "build_structure" and intent.get("buildRole") == "mass_extractor"
    )
    assert next_mass["siteKey"] == controller.markers.mass[2].key

    harness.brain.tick = 314
    expired = plain(harness.lua.globals().Controller.Observe(controller).sites.mass)
    assert expired[0]["buildable"] is True


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


def test_free_placement_key_survives_controller_pending_snapshot() -> None:
    harness = make_harness()
    acu = harness.unit(entityId=1, blueprintId="uel0001", canBuild={"ueb1101": True})
    harness.brain.units = harness.lua.table_from([acu])
    intent = {
        "kind": "build_structure",
        "actorToken": "1:1",
        "buildRole": "power_generator",
        "placementKey": "Placement:30000:40000",
        "position": [30, 0, 40],
    }

    execute_intents(harness, [intent])
    pending = plain(harness.observe().pending)

    assert harness.controller.pending["1:1"].placementKey == intent["placementKey"]
    assert pending[0]["placementKey"] == intent["placementKey"]
    assert pending[0].get("siteKey") is None


def test_one_completed_mex_releases_only_its_distinct_site_reservation() -> None:
    harness = make_harness()
    first_engineer = harness.unit(entityId=1, blueprintId="uel0105", canBuild={"ueb1103": True})
    second_engineer = harness.unit(entityId=2, blueprintId="uel0105", canBuild={"ueb1103": True})
    harness.brain.units = harness.lua.table_from([first_engineer, second_engineer])
    near = harness.controller.markers.mass[1]
    far = harness.controller.markers.mass[2]
    execute_intents(
        harness,
        [
            {"kind": "build_structure", "actorToken": "1:1", "buildRole": "mass_extractor", "siteKey": near.key, "position": plain(near.position)},
            {"kind": "build_structure", "actorToken": "2:1", "buildRole": "mass_extractor", "siteKey": far.key, "position": plain(far.position)},
        ],
    )
    near_mex = harness.unit(
        entityId=3,
        blueprintId="ueb1103",
        position=plain(near.position),
        fraction=0.1,
    )
    harness.brain.units = harness.lua.table_from([first_engineer, second_engineer, near_mex])
    harness.brain.tick = 4

    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())

    assert harness.controller.pending["1:1"] is None
    assert harness.controller.reservations[near.key] is None
    assert harness.controller.pending["2:1"] is not None
    assert harness.controller.reservations[far.key] is not None


def test_one_completed_free_placement_releases_only_matching_coordinate() -> None:
    harness = make_harness()
    first_engineer = harness.unit(entityId=1, blueprintId="uel0105", canBuild={"ueb1101": True})
    second_engineer = harness.unit(entityId=2, blueprintId="uel0105", canBuild={"ueb1101": True})
    harness.brain.units = harness.lua.table_from([first_engineer, second_engineer])
    execute_intents(
        harness,
        [
            {"kind": "build_structure", "actorToken": "1:1", "buildRole": "power_generator", "placementKey": "Placement:30000:40000", "position": [30, 0, 40]},
            {"kind": "build_structure", "actorToken": "2:1", "buildRole": "power_generator", "placementKey": "Placement:60000:70000", "position": [60, 0, 70]},
        ],
    )
    first_pgen = harness.unit(
        entityId=3,
        blueprintId="ueb1101",
        position=[30.5, 0, 40.5],
        fraction=0.1,
    )
    harness.brain.units = harness.lua.table_from([first_engineer, second_engineer, first_pgen])
    harness.brain.tick = 4

    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())

    assert harness.controller.pending["1:1"] is None
    assert harness.controller.pending["2:1"] is not None


def test_same_role_factory_completion_releases_only_idle_accepted_factory() -> None:
    harness = make_harness()
    first_factory = harness.unit(entityId=1, blueprintId="ueb0101", canBuild={"uel0201": True})
    second_factory = harness.unit(entityId=2, blueprintId="ueb0101", canBuild={"uel0201": True})
    harness.brain.units = harness.lua.table_from([first_factory, second_factory])
    execute_intents(
        harness,
        [
            {"kind": "factory_build", "actorToken": "1:1", "buildRole": "tank"},
            {"kind": "factory_build", "actorToken": "2:1", "buildRole": "tank"},
        ],
    )
    harness.brain.tick = 3
    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())
    assert harness.controller.pending["1:1"].accepted is True
    assert harness.controller.pending["2:1"].accepted is True

    first_factory.options.idleState = True
    first_factory.options.states.Building = False
    first_factory.options.queue = harness.lua.table_from([])
    tank = harness.unit(entityId=3, blueprintId="uel0201")
    harness.brain.units = harness.lua.table_from([first_factory, second_factory, tank])
    harness.brain.tick = 4

    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())

    assert harness.controller.pending["1:1"] is None
    assert harness.controller.pending["2:1"] is not None


def test_accepted_site_build_returning_idle_without_foundation_is_rejected_and_backed_off() -> None:
    harness = make_harness()
    engineer = harness.unit(entityId=1, blueprintId="uel0105", canBuild={"ueb1103": True})
    harness.brain.units = harness.lua.table_from([engineer])
    site = harness.controller.markers.mass[1]
    execute_intents(
        harness,
        [{"kind": "build_structure", "actorToken": "1:1", "buildRole": "mass_extractor", "siteKey": site.key, "position": plain(site.position)}],
    )
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.tick = 3
    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())
    assert harness.controller.pending["1:1"].accepted is True

    engineer.options.idleState = True
    engineer.options.states.Moving = False
    harness.brain.tick = 4
    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())
    sites = plain(harness.observe().sites.mass)

    assert harness.controller.pending["1:1"] is None
    assert harness.controller.reservations[site.key] is None
    assert sites[0]["buildable"] is False


def test_accepted_free_placement_returning_idle_is_temporarily_removed() -> None:
    harness = make_harness()
    engineer = harness.unit(entityId=1, blueprintId="uel0105", canBuild={"ueb1101": True})
    harness.brain.units = harness.lua.table_from([engineer])
    position = plain(harness.controller.placementSeeds[1])
    placement_key = f"Placement:{round(position[0] * 1000)}:{round(position[2] * 1000)}"
    execute_intents(
        harness,
        [{"kind": "build_structure", "actorToken": "1:1", "buildRole": "power_generator", "placementKey": placement_key, "position": position}],
    )
    engineer.options.idleState = False
    engineer.options.states = lua_value(harness.lua, {"Moving": True})
    harness.brain.tick = 3
    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())
    assert harness.controller.pending["1:1"].accepted is True

    engineer.options.idleState = True
    engineer.options.states.Moving = False
    harness.brain.tick = 4
    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())
    blocked = plain(harness.observe().placements.power_generator)

    assert harness.controller.pending["1:1"] is None
    assert position not in blocked

    harness.brain.tick = 305
    expired = plain(harness.observe().placements.power_generator)
    assert position in expired


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


def test_stationary_live_attacker_remains_assigned_and_is_not_regrouped_home() -> None:
    harness = make_harness()
    tank = harness.unit(
        entityId=2,
        blueprintId="uel0201",
        position=[110, 2, 120],
        idleState=False,
    )
    harness.brain.units = harness.lua.table_from([tank])
    execute_intents(
        harness,
        [{"kind": "attack_wave", "actorTokens": ["2:1"], "position": [200, 0, 200]}],
    )
    assert harness.controller.waveAssignments["2:1"] is not None

    harness.brain.tick = 301
    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())
    after_reconcile = harness.observe()
    intents = plain(harness.lua.globals().Policy.Decide(after_reconcile))

    assert harness.controller.waveAssignments["2:1"] is not None
    assert not any(intent.get("kind") == "regroup_wave" for intent in intents)


def test_dead_attacker_releases_wave_assignment() -> None:
    harness = make_harness()
    tank = harness.unit(entityId=2, blueprintId="uel0201", position=[110, 2, 120])
    harness.brain.units = harness.lua.table_from([tank])
    execute_intents(
        harness,
        [{"kind": "attack_wave", "actorTokens": ["2:1"], "position": [200, 0, 200]}],
    )
    tank.options.destroyed = True
    harness.brain.tick = 301

    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())

    assert harness.controller.waveAssignments["2:1"] is None


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


def test_retreat_releases_preempted_build_pending_and_reservation_immediately() -> None:
    harness = make_harness()
    acu = harness.unit(entityId=1, blueprintId="uel0001", canBuild={"ueb1103": True})
    harness.brain.units = harness.lua.table_from([acu])
    observation = harness.observe()
    build = {
        "kind": "build_structure",
        "actorToken": "1:1",
        "buildRole": "mass_extractor",
        "siteKey": "Mass:12000:20000",
        "position": [12, 0, 20],
    }
    execute_intents(harness, [build], observation)
    assert harness.controller.pending["1:1"] is not None
    assert harness.controller.reservations[build["siteKey"]] is not None

    execute_intents(
        harness,
        [{"kind": "retreat", "actorToken": "1:1", "position": [10, 0, 20]}],
        observation,
    )

    assert harness.controller.pending["1:1"] is None
    assert harness.controller.reservations[build["siteKey"]] is None


def test_retreat_reentry_starts_fresh_safety_epoch_and_cancels_new_build() -> None:
    harness = make_harness()
    acu = harness.unit(entityId=1, blueprintId="uel0001", canBuild={"ueb1103": True})
    harness.brain.units = harness.lua.table_from([acu])
    retreat = {"kind": "retreat", "actorToken": "1:1", "position": [10, 0, 20]}

    execute_intents(harness, [retreat])
    harness.brain.tick = 1
    execute_intents(harness, [retreat])
    assert len(harness.calls.clear) == 1
    assert len(harness.calls.move) == 1

    execute_intents(harness, [])
    harness.brain.tick = 10
    build = {
        "kind": "build_structure",
        "actorToken": "1:1",
        "buildRole": "mass_extractor",
        "siteKey": "Mass:12000:20000",
        "position": [12, 0, 20],
    }
    execute_intents(harness, [build])
    assert harness.controller.pending["1:1"] is not None
    assert harness.controller.reservations[build["siteKey"]] is not None

    harness.brain.tick = 20
    execute_intents(harness, [retreat])

    assert harness.controller.pending["1:1"] is None
    assert harness.controller.reservations[build["siteKey"]] is None
    assert len(harness.calls.clear) == 2
    assert len(harness.calls.move) == 2


def test_defense_reentry_clears_regroup_and_orders_fresh_defense_within_cooldown() -> None:
    harness = make_harness()
    tank = harness.unit(entityId=2, blueprintId="uel0201", position=[70, 2, 70])
    harness.brain.units = harness.lua.table_from([tank])
    defense = {"kind": "defend_wave", "actorTokens": ["2:1"], "position": [20, 0, 20]}
    regroup = {"kind": "regroup_wave", "actorTokens": ["2:1"], "position": [35, 0, 45]}

    execute_intents(harness, [defense])
    harness.brain.tick = 1
    execute_intents(harness, [defense])
    assert len(harness.calls.clear) == 1
    assert len(harness.calls.aggressive) == 1

    execute_intents(harness, [])
    harness.brain.tick = 10
    execute_intents(harness, [regroup])
    assert len(harness.calls.move) == 1

    harness.brain.tick = 20
    execute_intents(harness, [defense])

    assert len(harness.calls.clear) == 2
    assert len(harness.calls.aggressive) == 2


def test_regroup_uses_bounded_move_without_clear_or_aggressive_order() -> None:
    harness = make_harness()
    tank = harness.unit(entityId=2, blueprintId="uel0201", position=[70, 2, 70])
    harness.brain.units = harness.lua.table_from([tank])
    observation = harness.observe()
    regroup = {"kind": "regroup_wave", "actorTokens": ["2:1"], "position": [35, 0, 45]}

    execute_intents(harness, [regroup], observation)
    execute_intents(harness, [regroup], observation)

    assert len(harness.calls.move) == 1
    assert len(harness.calls.clear) == 0
    assert len(harness.calls.aggressive) == 0


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
