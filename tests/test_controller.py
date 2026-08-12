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
        ScenarioInfo = { Options = { TeamSpawn = 'fixed' } }
        calls = {
            own = {}, enemy = {}, nav = {}, navLabel = {}, navPath = {}, canBuild = {}, terrain = {},
            buildMobile = {}, buildFactory = {}, rally = {}, aggressive = {},
            guard = {}, move = {}, clear = {}, reclaim = {}, reclaimQuery = {},
            upgrade = {}, patrol = {}, transportLoad = {}, transportUnload = {},
            macroBuildPortfolio = {}, macroUpdateJobLedger = {},
            macroPlanExpansion = {}, macroPlanRegionPackage = {},
            macroPlanReclaim = {}, macroPlanTech = {},
            intelligenceUpdateMemory = {}, intelligencePlanRadar = {},
            intelligencePlanScoutRoute = {}, intelligencePlanAir = {},
            intelligencePlanTransport = {}, intelligenceAdvanceTransport = {},
            forceAssign = {}, forceReconcile = {}, forceHandleHomeBreach = {},
            policySnapshots = {},
            waits = {}, sequence = {}, orderTrace = {}, unitReclaimInspections = 0,
        }
        directorResults = {
            macroPlan = { valid = true, lanes = {}, regions = {}, intents = {} },
            jobLedger = { jobs = {} },
            expansionPlan = { jobs = {}, denials = {}, intents = {} },
            regionPackagePlan = { requiredRoles = {}, intents = {} },
            reclaimPlan = { jobs = {}, intents = {} },
            techPlan = { intents = {} },
            intelState = { contacts = {}, threat = {}, expansionSafety = {} },
            radarIntents = {},
            scoutPlan = { intents = {} },
            airPlan = { orders = {}, intents = {} },
            transportPlan = { mode = 'hold', intents = {} },
            forcePlan = { assignments = {}, ownershipByToken = {}, intents = {} },
            homeBreachPlan = false,
        }

        BlueprintData = {
            ueb0101 = {
                BlueprintId = 'ueb0101',
                Footprint = { SizeX = 5, SizeZ = 5 },
                Physics = { SkirtSizeX = 8, SkirtSizeZ = 8, SkirtOffsetX = -1.5, SkirtOffsetZ = -1.5 },
                Economy = { BuildTime = 300, BuildCostMass = 240, BuildCostEnergy = 2100, BuildRate = 20 },
            },
            ueb0102 = {
                BlueprintId = 'ueb0102',
                Footprint = { SizeX = 5, SizeZ = 5 },
                Physics = { SkirtSizeX = 8, SkirtSizeZ = 8, SkirtOffsetX = -1.5, SkirtOffsetZ = -1.5 },
                Economy = { BuildTime = 300, BuildCostMass = 210, BuildCostEnergy = 2400, BuildRate = 20 },
            },
            ueb0201 = {
                BlueprintId = 'ueb0201',
                General = { UpgradesFrom = 'ueb0101' },
                Footprint = { SizeX = 5, SizeZ = 5 },
                Physics = { SkirtSizeX = 8, SkirtSizeZ = 8, SkirtOffsetX = -1.5, SkirtOffsetZ = -1.5 },
                Economy = { BuildTime = 2300, BuildCostMass = 1410, BuildCostEnergy = 11200, BuildRate = 40, DifferentialUpgradeCostCalculation = true },
            },
            zeb9501 = {
                BlueprintId = 'zeb9501',
                General = { UpgradesFrom = 'ueb0101' },
                Footprint = { SizeX = 5, SizeZ = 5 },
                Physics = { SkirtSizeX = 8, SkirtSizeZ = 8, SkirtOffsetX = -1.5, SkirtOffsetZ = -1.5 },
                Economy = { BuildTime = 1200, BuildCostMass = 580, BuildCostEnergy = 4800, BuildRate = 40, DifferentialUpgradeCostCalculation = true },
            },
            ueb1101 = {
                BlueprintId = 'ueb1101',
                Footprint = { SizeX = 1, SizeZ = 1 },
                Physics = { SkirtSizeX = 2, SkirtSizeZ = 2, SkirtOffsetX = -0.5, SkirtOffsetZ = -0.5 },
                Economy = { BuildTime = 125, BuildCostMass = 75, BuildCostEnergy = 750, ProductionPerSecondEnergy = 20 },
            },
            ueb1102 = {
                BlueprintId = 'ueb1102',
                Footprint = { SizeX = 3, SizeZ = 3 },
                Physics = { SkirtSizeX = 6, SkirtSizeZ = 6, SkirtOffsetX = -1.5, SkirtOffsetZ = -1.5 },
                Economy = { BuildTime = 400, BuildCostMass = 160, BuildCostEnergy = 800, ProductionPerSecondEnergy = 100 },
            },
            ueb1103 = {
                BlueprintId = 'ueb1103',
                Footprint = { SizeX = 1, SizeZ = 1 },
                Physics = { SkirtSizeX = 2, SkirtSizeZ = 2, SkirtOffsetX = -0.5, SkirtOffsetZ = -0.5 },
                Economy = { BuildTime = 60, BuildCostMass = 36, BuildCostEnergy = 360, ProductionPerSecondMass = 2, MaintenanceConsumptionPerSecondEnergy = 2 },
            },
            ueb1202 = {
                BlueprintId = 'ueb1202',
                General = { UpgradesFrom = 'ueb1103' },
                Economy = { BuildTime = 900, BuildCostMass = 900, BuildCostEnergy = 5400 },
            },
            ueb1302 = {
                BlueprintId = 'ueb1302',
                General = { UpgradesFrom = 'ueb1202' },
                Economy = { BuildTime = 2875, BuildCostMass = 4600, BuildCostEnergy = 31600 },
            },
            ueb2101 = { BlueprintId = 'ueb2101', Economy = { BuildTime = 500, BuildCostMass = 250, BuildCostEnergy = 2500 } },
            ueb2104 = { BlueprintId = 'ueb2104', Economy = { BuildTime = 300, BuildCostMass = 120, BuildCostEnergy = 900 } },
            ueb3101 = { BlueprintId = 'ueb3101', Economy = { BuildTime = 400, BuildCostMass = 80, BuildCostEnergy = 800 } },
            uel0001 = { BlueprintId = 'uel0001', Economy = { BuildRate = 10, ProductionPerSecondMass = 1, ProductionPerSecondEnergy = 20 } },
            uel0101 = { BlueprintId = 'uel0101', Economy = { BuildTime = 60, BuildCostMass = 12, BuildCostEnergy = 80 } },
            uel0103 = { BlueprintId = 'uel0103', Economy = { BuildTime = 200, BuildCostMass = 36, BuildCostEnergy = 180 } },
            uel0104 = { BlueprintId = 'uel0104', Economy = { BuildTime = 220, BuildCostMass = 55, BuildCostEnergy = 275 } },
            uel0105 = { BlueprintId = 'uel0105', Economy = { BuildTime = 260, BuildCostMass = 52, BuildCostEnergy = 260, BuildRate = 5 } },
            uel0106 = { BlueprintId = 'uel0106', Economy = { BuildTime = 120, BuildCostMass = 30, BuildCostEnergy = 120 } },
            uel0201 = { BlueprintId = 'uel0201', Economy = { BuildTime = 300, BuildCostMass = 56, BuildCostEnergy = 266 } },
            uea0101 = { BlueprintId = 'uea0101', Economy = { BuildTime = 200, BuildCostMass = 40, BuildCostEnergy = 580 } },
            uea0102 = { BlueprintId = 'uea0102', Economy = { BuildTime = 500, BuildCostMass = 50, BuildCostEnergy = 2250 } },
            uea0103 = { BlueprintId = 'uea0103', Economy = { BuildTime = 500, BuildCostMass = 60, BuildCostEnergy = 3000 } },
            uea0107 = { BlueprintId = 'uea0107', Economy = { BuildTime = 600, BuildCostMass = 100, BuildCostEnergy = 4000 } },
            uel0202 = { BlueprintId = 'uel0202', Economy = { BuildTime = 880, BuildCostMass = 198, BuildCostEnergy = 990 } },
            uel0205 = { BlueprintId = 'uel0205', Economy = { BuildTime = 800, BuildCostMass = 160, BuildCostEnergy = 800 } },
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
                local stored = BlueprintData[self.options.blueprintId or ''] or {}
                return {
                    BlueprintId = self.options.blueprintId or 'uel0001',
                    Footprint = self.options.footprint or stored.Footprint,
                    Size = self.options.blueprintSize or stored.Size,
                    Physics = self.options.blueprintPhysics or stored.Physics or {},
                    Economy = self.options.blueprintEconomy or stored.Economy or {},
                    General = self.options.blueprintGeneral or stored.General or {},
                    Intel = self.options.blueprintIntel or {},
                    Categories = self.options.blueprintCategories or stored.Categories,
                    CategoriesHash = self.options.blueprintCategoriesHash or stored.CategoriesHash,
                }
            end
            function unit:GetBuildRate()
                if self.options.buildRate ~= nil then return self.options.buildRate end
                local stored = BlueprintData[self.options.blueprintId or ''] or {}
                return stored.Economy and stored.Economy.BuildRate or nil
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
                if name == 'Attached' and self.options.attached ~= nil then
                    return self.options.attached
                end
                return states[name] or false
            end
            function unit:IsPaused() return self.options.paused or false end
            function unit:IsIntelEnabled(kind)
                if self.options.failVisionEnabled then error('vision state failed') end
                return kind == 'Vision' and self.options.visionEnabled ~= false
            end
            function unit:GetIntelRadius(kind)
                if kind ~= 'Vision' then return 0 end
                local intel = self.options.blueprintIntel or {}
                return self.options.visionRadius or intel.VisionRadius or 10
            end
            function unit:CanBuild(blueprintId)
                local canBuild = self.options.canBuild or {}
                return canBuild[blueprintId] == true
            end
            function unit:GetFocusUnit() return self.options.focusUnit end
            function unit:GetTransport() return self.options.transport end
            function unit:GetCargo() return self.options.cargo or {} end
            function unit:GetBlip(army)
                local options = self.options
                return {
                    IsSeenNow = function(_, observedArmy)
                        return observedArmy == army and options.seenNow ~= false
                    end,
                    IsOnRadar = function(_, observedArmy)
                        return observedArmy == army
                            and (options.onRadar == true or options.seenNow ~= false)
                    end,
                }
            end
            return unit
        end

        function MakeProp(options)
            local prop = {
                options = options,
                Dead = options.Dead or false,
                EntityId = options.entityId,
                MaxMassReclaim = options.mass,
                MaxEnergyReclaim = options.energy,
                ReclaimLeft = options.reclaimLeft == nil and 1 or options.reclaimLeft,
                CachePosition = options.cachePosition,
            }
            function prop:BeenDestroyed()
                if self.options.failDestroyed then error('destroyed state failed') end
                if self.options.isUnit then
                    calls.unitReclaimInspections = calls.unitReclaimInspections + 1
                end
                return self.options.destroyed or false
            end
            function prop:GetEntityId() return self.options.entityId end
            function prop:GetPosition() return self.options.position end
            return prop
        end

        function IsProp(entity)
            if calls.failIsProp then error('prop identity failed') end
            return entity and entity.options and entity.options.isUnit ~= true
        end

        brain = {
            Army = 1,
            units = {},
            supportUnits = {},
            enemies = {},
            tick = 0,
            startX = 10,
            startZ = 20,
            faction = 1,
            canBuildAt = true,
            reclaimables = {},
            energyTrend = -1,
            energyStoredRatio = 0.2,
            energyIncome = 20,
            energyUsage = 21,
            energyRequested = 21,
            energyStored = 3900,
            massTrend = 1,
            massStoredRatio = 0.5,
            massIncome = 2,
            massUsage = 1,
            massRequested = 1,
            massStored = 650,
            armyStats = {
                Economy_TotalProduced_Mass = 0,
                Economy_TotalConsumed_Mass = 0,
                Economy_Reclaimed_Mass = 0,
                Economy_AccumExcess_Mass = 0,
                Economy_TotalProduced_Energy = 0,
                Economy_TotalConsumed_Energy = 0,
                Economy_Reclaimed_Energy = 0,
                Economy_AccumExcess_Energy = 0,
            },
        }
        function brain:GetArmyStartPos() return self.startX, self.startZ end
        function brain:GetFactionIndex() return self.faction end
        function brain:GetListOfUnits(category, idle, requireBuilt)
            table.insert(calls.own, { category, idle, requireBuilt })
            local result = {}
            for _, unit in pairs(self.units or {}) do table.insert(result, unit) end
            for _, unit in pairs(self.supportUnits or {}) do table.insert(result, unit) end
            return result
        end
        function brain:GetUnitsAroundPoint(category, position, radius, alliance)
            table.insert(calls.enemy, { category, {position[1], position[2], position[3]}, radius, alliance })
            return self.enemies
        end
        function brain:GetEconomyTrend(resource) return resource == 'ENERGY' and self.energyTrend or self.massTrend end
        function brain:GetEconomyStoredRatio(resource) return resource == 'ENERGY' and self.energyStoredRatio or self.massStoredRatio end
        function brain:GetEconomyStored(resource) return resource == 'ENERGY' and self.energyStored or self.massStored end
        function brain:GetEconomyIncome(resource) return resource == 'ENERGY' and self.energyIncome or self.massIncome end
        function brain:GetEconomyUsage(resource) return resource == 'ENERGY' and self.energyUsage or self.massUsage end
        function brain:GetEconomyRequested(resource) return resource == 'ENERGY' and self.energyRequested or self.massRequested end
        function brain:GetUnitBlueprint(blueprintId) return BlueprintData[blueprintId] end
        function brain:GetArmyStat(name, default)
            local value = self.armyStats and self.armyStats[name]
            if value == nil then return { Value = default } end
            if type(value) == 'table' then return value end
            return { Value = value }
        end
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
                if calls.failCanPath then error('can path failed') end
                if calls.canPathMode == 'nil' then return nil, calls.canPathReason or 'SystemError' end
                if calls.canPathMode == 'false' then return false, calls.canPathReason or 'Unpathable' end
                if calls.canPathMode == 'true' then return true end
                return destination[1] ~= 999
            end,
            GetLabel = function(layer, position)
                table.insert(calls.navLabel, { layer, {position[1], position[2], position[3]} })
                if calls.failGetLabel then error('label failed') end
                local positionKey = tostring(position[1]) .. ':' .. tostring(position[3])
                if calls.labelByPosition and calls.labelByPosition[positionKey] ~= nil then
                    return calls.labelByPosition[positionKey]
                end
                local index = table.getn(calls.navLabel)
                if calls.labelValues then return calls.labelValues[index] end
                return 1
            end,
            PathTo = function(layer, origin, destination)
                table.insert(calls.navPath, { layer, {origin[1], origin[2], origin[3]}, {destination[1], destination[2], destination[3]} })
                if calls.failPath then error('path failed') end
                if calls.pathError then return nil, calls.pathError end
                if calls.pathReturnNil then return nil, calls.pathCount, calls.pathLength end
                if calls.pathWaypoints ~= nil then
                    return calls.pathWaypoints, calls.pathCount, calls.pathLength
                end
                local dx = destination[1] - origin[1]
                local dz = destination[3] - origin[3]
                return { {destination[1], destination[2], destination[3]} }, 1, math.sqrt(dx * dx + dz * dz)
            end,
        }

        function GetGameTick() return brain.tick end
        function GetTerrainHeight(x, z) table.insert(calls.terrain, {x, z}); return x + z / 100 end
        function GetSurfaceHeight(x, z) return GetTerrainHeight(x, z) end
        function Rect(x0, z0, x1, z1) return { x0, z0, x1, z1 } end
        function GetReclaimablesInRect(rect)
            table.insert(calls.reclaimQuery, { rect[1], rect[2], rect[3], rect[4] })
            if calls.failReclaimQuery
                or tonumber(calls.failReclaimQueryAt) == table.getn(calls.reclaimQuery)
            then
                error('reclaim query failed')
            end
            local found = {}
            for _, prop in pairs(brain.reclaimables or {}) do
                local position = prop.CachePosition or prop:GetPosition()
                if position
                    and position[1] >= rect[1] and position[1] <= rect[3]
                    and position[3] >= rect[2] and position[3] <= rect[4]
                then
                    table.insert(found, prop)
                end
            end
            return found
        end
        function IssueBuildMobile(units, position, blueprintId, alternatives)
            table.insert(calls.orderTrace, {
                kind = 'build_mobile', units = units, position = position,
                blueprintId = blueprintId,
            })
            table.insert(calls.buildMobile, { units = units, position = position, blueprintId = blueprintId, alternatives = alternatives, argc = 4 })
            if calls.failBuildMobile
                or tonumber(calls.failBuildMobileAt) == table.getn(calls.buildMobile)
            then error('build mobile failed') end
            return { kind = 'build-mobile' }
        end
        function IssueBuildFactory(units, blueprintId, count)
            table.insert(calls.buildFactory, { units = units, blueprintId = blueprintId, count = count })
            if calls.failBuildFactory then error('factory build failed') end
            for _, factory in ipairs(units) do
                factory.options.queue = { { commandType = 7, blueprintId = blueprintId } }
                factory.options.idleState = false
                factory.options.states = factory.options.states or {}
                factory.options.states.Building = true
            end
            return { kind = 'build-factory' }
        end
        function IssueUpgrade(units, blueprintId)
            table.insert(calls.sequence, 'upgrade')
            table.insert(calls.upgrade, { units = units, blueprintId = blueprintId })
            if calls.failUpgrade then error('upgrade failed') end
            for _, factory in ipairs(units) do
                factory.options.idleState = false
                factory.options.states = factory.options.states or {}
                factory.options.states.Upgrading = true
                factory.options.queue = { { commandType = 27, blueprintId = blueprintId } }
            end
            return { kind = 'upgrade' }
        end
        function IssuePatrol(units, position)
            table.insert(calls.sequence, 'patrol')
            table.insert(calls.patrol, { units = units, position = position })
            if calls.failPatrol then error('patrol failed') end
            return { kind = 'patrol' }
        end
        function IssueTransportLoad(units, transport)
            table.insert(calls.sequence, 'transport_load')
            table.insert(calls.transportLoad, { units = units, transport = transport })
            if calls.failTransportLoad then error('transport load failed') end
            transport.options.cargo = {}
            for _, unit in ipairs(units) do
                unit.options.attached = true
                unit.options.transport = transport
                table.insert(transport.options.cargo, unit)
            end
            return { kind = 'transport-load' }
        end
        function IssueTransportUnload(transports, position)
            table.insert(calls.sequence, 'transport_unload')
            table.insert(calls.transportUnload, { transports = transports, position = position })
            if calls.failTransportUnload then error('transport unload failed') end
            if not calls.keepCargoAttached then
                for _, transport in ipairs(transports) do
                    for _, unit in ipairs(transport.options.cargo or {}) do
                        unit.options.attached = false
                        unit.options.transport = nil
                        unit.options.position = { position[1], position[2], position[3] }
                    end
                    transport.options.cargo = {}
                end
            end
            return { kind = 'transport-unload' }
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
            table.insert(calls.sequence, 'aggressive')
            table.insert(calls.aggressive, { units = units, position = position })
            if calls.failAggressive
                or tonumber(calls.failAggressiveAt) == table.getn(calls.aggressive)
            then error('aggressive failed') end
            return { kind = 'aggressive' }
        end
        function IssueGuard(units, target)
            table.insert(calls.sequence, 'guard')
            table.insert(calls.orderTrace, {
                kind = 'guard', units = units, target = target,
            })
            table.insert(calls.guard, { units = units, target = target })
            if calls.failGuard
                or tonumber(calls.failGuardAt) == table.getn(calls.guard)
            then
                error('guard failed')
            end
            return { kind = 'guard' }
        end
        function IssueMove(units, position)
            table.insert(calls.sequence, 'move')
            table.insert(calls.move, { units = units, position = position })
            if calls.failMove
                or tonumber(calls.failMoveAt) == table.getn(calls.move)
            then error('move failed') end
            return { kind = 'move' }
        end
        function IssueClearCommands(units)
            table.insert(calls.sequence, 'clear')
            table.insert(calls.clear, { units = units })
            if calls.failClear
                or tonumber(calls.failClearAt) == table.getn(calls.clear)
            then
                error('clear failed')
            end
            return { kind = 'clear' }
        end
        function IssueReclaim(units, target)
            table.insert(calls.sequence, 'reclaim')
            table.insert(calls.reclaim, { units = units, target = target })
            if calls.failReclaim
                or tonumber(calls.failReclaimAt) == table.getn(calls.reclaim)
            then error('reclaim failed') end
            return { kind = 'reclaim' }
        end
        MacroDirectorStub = {
            BuildPortfolio = function(snapshot)
                table.insert(calls.macroBuildPortfolio, snapshot)
                return directorResults.macroPlan
            end,
            UpdateJobLedger = function(ledger, snapshot)
                table.insert(calls.macroUpdateJobLedger, {
                    ledger = ledger,
                    snapshot = snapshot,
                })
                return directorResults.jobLedger
            end,
            ClusterRegions = function() return {} end,
            AdvanceRegion = function(region) return region end,
            PlanExpansion = function(snapshot)
                table.insert(calls.macroPlanExpansion, snapshot)
                return directorResults.expansionPlan
            end,
            PlanRegionPackage = function(region, snapshot)
                table.insert(calls.macroPlanRegionPackage, {
                    region = region,
                    snapshot = snapshot,
                })
                return directorResults.regionPackagePlan
            end,
            PlanReclaim = function(snapshot)
                table.insert(calls.macroPlanReclaim, snapshot)
                return directorResults.reclaimPlan
            end,
            PlanTech = function(snapshot)
                table.insert(calls.macroPlanTech, snapshot)
                return directorResults.techPlan
            end,
        }
        IntelligenceStub = {
            UpdateMemory = function(previous, snapshot)
                table.insert(calls.intelligenceUpdateMemory, {
                    previous = previous,
                    snapshot = snapshot,
                })
                return directorResults.intelState
            end,
            PlanRadar = function(regions, coverage)
                table.insert(calls.intelligencePlanRadar, {
                    regions = regions,
                    coverage = coverage,
                })
                return directorResults.radarIntents
            end,
            PlanScoutRoute = function(snapshot)
                table.insert(calls.intelligencePlanScoutRoute, snapshot)
                return directorResults.scoutPlan
            end,
            PlanAir = function(snapshot)
                table.insert(calls.intelligencePlanAir, snapshot)
                return directorResults.airPlan
            end,
            SelectBomberTarget = function() return nil end,
            ValidateBomberIntent = function() return { valid = false } end,
            PlanTransport = function(snapshot)
                table.insert(calls.intelligencePlanTransport, snapshot)
                return directorResults.transportPlan
            end,
            AdvanceTransport = function(mission, event)
                table.insert(calls.intelligenceAdvanceTransport, {
                    mission = mission,
                    event = event,
                })
                local advanced = {}
                for key, value in pairs(mission or {}) do advanced[key] = value end
                local function ExactCargo(expected, observed)
                    if table.getn(expected or {}) ~= table.getn(observed or {}) then
                        return false
                    end
                    local found = {}
                    for _, token in ipairs(observed or {}) do found[token] = true end
                    for _, token in ipairs(expected or {}) do
                        if found[token] ~= true then return false end
                    end
                    return true
                end
                if event and event.kind == 'load_ordered' then
                    advanced.state = 'loading'
                elseif event and event.kind == 'observed'
                    and advanced.state == 'loading'
                    and event.transportToken == advanced.transportToken
                    and ExactCargo(advanced.cargoTokens, event.attachedCargoTokens)
                then
                    advanced.state = 'loaded'
                elseif event and event.kind == 'observed'
                    and (advanced.state == 'loaded' or advanced.state == 'flying')
                    and event.transportToken == advanced.transportToken
                    and not ExactCargo(advanced.cargoTokens, event.attachedCargoTokens)
                then
                    advanced.state = 'released'
                    advanced.released = true
                    advanced.retryable = true
                    advanced.retryCount = (tonumber(advanced.retryCount) or 0) + 1
                elseif event and event.kind == 'unload_ordered' then
                    advanced.state = 'unloading'
                elseif event and event.kind == 'observed'
                    and advanced.state == 'unloading'
                    and event.transportToken == advanced.transportToken
                    and table.getn(event.attachedCargoTokens or {}) == 0
                then
                    advanced.state = 'completed'
                    advanced.released = true
                end
                return advanced
            end,
        }
        ForceDirectorStub = {
            Assign = function(snapshot)
                table.insert(calls.forceAssign, snapshot)
                return directorResults.forcePlan
            end,
            Reconcile = function(plan, snapshot)
                table.insert(calls.forceReconcile, {
                    plan = plan,
                    snapshot = snapshot,
                })
                return directorResults.forcePlan
            end,
            HandleHomeBreach = function(snapshot, plan)
                table.insert(calls.forceHandleHomeBreach, {
                    snapshot = snapshot,
                    plan = plan,
                })
                if directorResults.homeBreachPlan then
                    return directorResults.homeBreachPlan
                end
                return plan
            end,
        }
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
        "/mods/overmind4/lua/AI/Overmind4/MacroDirector.lua": lua.table_from({"MacroDirector": lua.globals().MacroDirectorStub}),
        "/mods/overmind4/lua/AI/Overmind4/Intelligence.lua": lua.table_from({"Intelligence": lua.globals().IntelligenceStub}),
        "/mods/overmind4/lua/AI/Overmind4/ForceDirector.lua": lua.table_from({"ForceDirector": lua.globals().ForceDirectorStub}),
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
    assert controller.crossMapOffenseEnabled is False
    # Legacy unit tests exercise the retired adapters in isolation. Live
    # controllers default to the secured field campaign; campaign tests opt
    # back into that production doctrine explicitly after using this harness.
    controller.fieldCampaignEnabled = False
    # Legacy executor tests opt back into dormant offense adapters explicitly.
    controller.crossMapOffenseEnabled = True
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


def commander_force(
    harness: ControllerHarness,
    *,
    combat_count: int = 24,
    artillery_count: int = 4,
    health_ratio: float = 1,
    acu_idle: bool = True,
    acu_near_staging: bool = True,
) -> tuple[Any, list[Any], Any]:
    staging = plain(harness.controller.stagingPosition)
    acu_position = staging if acu_near_staging else plain(harness.controller.basePosition)
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        position=acu_position,
        health=health_ratio * 100,
        maxHealth=100,
        idleState=acu_idle,
    )
    units: list[Any] = [acu]
    combat: list[Any] = []
    tank_count = max(0, combat_count - artillery_count)
    for offset in range(tank_count):
        combat.append(
            harness.unit(
                entityId=offset + 2,
                blueprintId="uel0201",
                position=staging,
            )
        )
    for offset in range(artillery_count):
        combat.append(
            harness.unit(
                entityId=tank_count + offset + 2,
                blueprintId="uel0103",
                position=staging,
            )
        )
    units.extend(combat)
    harness.brain.units = harness.lua.table_from(units)
    return acu, combat, harness.observe()


def commander_push_intent(observation: Any, tokens: list[str] | None = None) -> dict[str, Any]:
    combat_tokens = tokens or [
        unit["token"]
        for unit in plain(observation.units)
        if unit["role"] in {"tank", "artillery", "anti_air", "lab"}
    ]
    return {
        "kind": "commander_push",
        "acuToken": "1:1",
        "actorTokens": combat_tokens,
        "position": plain(observation.targetPosition),
        "priority": 40,
        "reason": "acu_led_concentration",
    }


def commander_mobilize_intent(observation: Any, tokens: list[str] | None = None) -> dict[str, Any]:
    intent = commander_push_intent(observation, tokens)
    intent.update(
        {
            "kind": "mobilize_commander",
            "position": plain(observation.stagingPosition),
            "priority": 1,
            "reason": "assemble_commander",
        }
    )
    return intent


def activate_commander_push(harness: ControllerHarness, commander_token: str = "1:1") -> None:
    harness.controller.initialWaveSent = True
    harness.controller.commanderPushActive = True
    harness.controller.commanderMobilizing = False
    harness.controller.commanderRetreating = False
    harness.controller.commanderToken = commander_token


def commander_reinforcement_intent(
    observation: Any,
    tokens: list[str] | None = None,
) -> dict[str, Any]:
    intent = commander_push_intent(observation, tokens)
    intent.update(
        {
            "kind": "reinforce_commander",
            "reason": "reinforce_commander",
        }
    )
    return intent


def test_create_converts_two_value_start_position_and_generates_navigation_once() -> None:
    harness = make_harness()
    assert plain(harness.controller.basePosition) == [10, 10.2, 20]
    assert harness.controller.commanderPushActive is False
    assert harness.controller.commanderMobilizing is False
    assert harness.controller.commanderRetreating is False
    assert harness.controller.commanderToken is None
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


def test_created_telemetry_names_occupied_target_and_emits_exact_objective_geometry() -> None:
    harness = make_harness()

    created = next(line for line in harness.logs if "event=created" in line)
    expected = {
        "target_name=ARMY_2",
        "base_x=10",
        "base_z=20",
        "target_x=110",
        "target_z=120",
        "staging_x=33",
        "staging_z=43",
        "occupied_spawns=2",
    }

    assert harness.controller.targetName == "ARMY_2"
    assert plain(harness.controller.targetPosition) == [110, 3, 120]
    assert all(field in created for field in expected)
    assert len(harness.calls.own) == 0
    assert len(harness.calls.enemy) == 0


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


def test_can_build_invokes_engine_bound_callable_with_owner_and_accepts_truthy_result() -> None:
    harness = make_harness()
    acu = harness.unit(entityId=1, blueprintId="uel0001")
    harness.lua.globals().probeUnit = acu
    harness.lua.execute(
        """
        boundCanBuildCalls = {}
        probeUnit.CanBuild = setmetatable({}, {
            __call = function(callable, owner, blueprintId)
                table.insert(boundCanBuildCalls, {
                    ownerMatches = owner == probeUnit,
                    blueprintId = blueprintId,
                })
                return 1
            end,
        })
        """
    )
    harness.brain.units = harness.lua.table_from([acu])

    record = plain(harness.observe().units)[0]
    calls = plain(harness.lua.globals().boundCanBuildCalls)

    assert record["canBuild"] == {
        "air_factory": True,
        "land_factory": True,
        "power_generator": True,
        "mass_extractor": True,
    }
    assert calls == [
        {"ownerMatches": True, "blueprintId": "ueb0102"},
        {"ownerMatches": True, "blueprintId": "ueb0101"},
        {"ownerMatches": True, "blueprintId": "ueb1101"},
        {"ownerMatches": True, "blueprintId": "ueb1103"},
    ]


def test_can_build_colon_method_accepts_non_boolean_truthy_result() -> None:
    harness = make_harness()
    acu = harness.unit(entityId=1, blueprintId="uel0001")
    harness.lua.globals().probeUnit = acu
    harness.lua.execute(
        """
        function probeUnit:CanBuild(blueprintId)
            if self ~= probeUnit then error('missing method owner') end
            return 'available'
        end
        """
    )
    harness.brain.units = harness.lua.table_from([acu])

    record = plain(harness.observe().units)[0]

    assert all(record["canBuild"].values())


def test_can_build_missing_error_false_and_nil_results_fail_closed() -> None:
    definitions = (
        "probeUnit.CanBuild = nil",
        "function probeUnit:CanBuild(blueprintId) error('engine failure') end",
        "function probeUnit:CanBuild(blueprintId) return false end",
        "function probeUnit:CanBuild(blueprintId) return nil end",
    )
    for definition in definitions:
        harness = make_harness()
        acu = harness.unit(entityId=1, blueprintId="uel0001")
        harness.lua.globals().probeUnit = acu
        harness.lua.execute(definition)
        harness.brain.units = harness.lua.table_from([acu])

        record = plain(harness.observe().units)[0]

        assert not any(record["canBuild"].values()), definition


def test_rally_only_queue_is_idle_but_active_build_and_moving_actor_are_busy() -> None:
    harness = make_harness()
    rally = {"commandType": 2, "type": "Move", "position": [35, 2, 45], "isRally": True}
    rallied_factory = harness.unit(
        entityId=1,
        blueprintId="ueb0101",
        queue=[rally],
        # FAF may report a factory with only its persistent rally command as
        # non-idle.  That command must not block the production queue.
        idleState=False,
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
    harness.brain.energyIncome = 30
    harness.brain.energyRequested = 10
    harness.brain.energyUsage = 10
    harness.brain.energyTrend = 20
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
    factory.options.idleState = False

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


def test_incomplete_mex_foundation_retains_only_its_distinct_site_reservation() -> None:
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

    assert harness.controller.pending["1:1"] is not None
    assert harness.controller.reservations[near.key] is not None
    assert harness.controller.pending["2:1"] is not None
    assert harness.controller.reservations[far.key] is not None


def test_incomplete_free_placement_foundation_retains_matching_operation() -> None:
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

    assert harness.controller.pending["1:1"] is not None
    assert harness.controller.pending["2:1"] is not None


def test_adjacent_completed_power_generator_does_not_complete_new_placement() -> None:
    harness = make_harness()
    engineer = harness.unit(entityId=1, blueprintId="uel0105", canBuild={"ueb1101": True})
    completed_neighbor = harness.unit(
        entityId=2,
        blueprintId="ueb1101",
        position=[32, 0, 40],
    )
    harness.brain.units = harness.lua.table_from([engineer, completed_neighbor])
    execute_intents(
        harness,
        [{
            "kind": "build_structure",
            "actorToken": "1:1",
            "buildRole": "power_generator",
            "position": [30, 0, 40],
        }],
    )
    harness.brain.tick = 1

    harness.lua.globals().Controller.Reconcile(harness.controller, harness.observe())

    assert harness.controller.pending["1:1"] is not None


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
    acu = harness.unit(entityId=1, blueprintId="uel0001")
    tank = harness.unit(entityId=9, blueprintId="uel0201")
    arty = harness.unit(entityId=4, blueprintId="uel0103")
    scout = harness.unit(entityId=2, blueprintId="uel0101")
    harness.brain.units = harness.lua.table_from([tank, scout, arty, acu])
    observation = harness.observe()
    execute_intents(harness, [{"kind": "attack_wave", "actorTokens": ["9:1", "1:1", "2:1", "4:1"], "position": [110, 0, 120]}], observation)
    call = harness.calls.aggressive[1]
    assert len(call.units) == 2
    assert [call.units[index].GetEntityId(call.units[index]) for index in (1, 2)] == [4, 9]


def test_commander_mobilization_atomically_clears_guards_moves_and_owns_full_cohort() -> None:
    harness = make_harness()
    acu, _, observation = commander_force(
        harness,
        combat_count=29,
        artillery_count=5,
        health_ratio=0.75,
        acu_near_staging=False,
    )
    valid_tokens = [
        record["token"]
        for record in plain(observation.units)
        if record["role"] in {"tank", "artillery"}
    ]
    supplied = list(reversed(valid_tokens)) + [valid_tokens[0], "1:1", "999:1", None]
    intent = commander_mobilize_intent(observation, supplied)
    expected_ids = [int(token.split(":")[0]) for token in sorted(valid_tokens)]
    own_queries = len(harness.calls.own)
    enemy_queries = len(harness.calls.enemy)

    execute_intents(harness, [intent], observation)
    execute_intents(harness, [intent], observation)

    assert plain(harness.calls.sequence) == ["clear", "guard", "move"]
    assert len(harness.calls.clear) == 1
    assert [
        harness.calls.clear[1].units[index].GetEntityId(harness.calls.clear[1].units[index])
        for index in range(1, len(harness.calls.clear[1].units) + 1)
    ] == expected_ids
    assert len(harness.calls.guard) == 1
    assert harness.lua.eval("function(a, b) return rawequal(a, b) end")(
        harness.calls.guard[1].target,
        acu,
    )
    assert [
        harness.calls.guard[1].units[index].GetEntityId(harness.calls.guard[1].units[index])
        for index in range(1, len(harness.calls.guard[1].units) + 1)
    ] == expected_ids
    assert len(harness.calls.move) == 1
    assert len(harness.calls.move[1].units) == 1
    assert harness.lua.eval("function(a, b) return rawequal(a, b) end")(
        harness.calls.move[1].units[1],
        acu,
    )
    assert plain(harness.calls.move[1].position) == plain(harness.controller.stagingPosition)
    assert len(harness.calls.aggressive) == 0
    assert len(harness.calls.buildMobile) == 0
    assert harness.controller.initialWaveSent is False
    assert harness.controller.commanderMobilizing is True
    assert harness.controller.commanderPushActive is False
    assert harness.controller.commanderRetreating is False
    assert harness.controller.commanderToken == "1:1"
    assert all(
        harness.controller.waveAssignments[token] is not None
        and harness.controller.waveAssignments[token].commanderEscort is True
        for token in valid_tokens
    )
    assert harness.controller.waveAssignments["1:1"] is None
    assert len(plain(harness.controller.waveAssignments)) == 29
    assert len(harness.calls.own) == own_queries
    assert len(harness.calls.enemy) == enemy_queries
    assert any("command=mobilize_commander" in line for line in harness.logs)


def test_commander_mobilization_revalidates_acu_gate_cohort_and_position() -> None:
    def assert_rejected(harness: ControllerHarness) -> None:
        assert len(harness.calls.sequence) == 0
        assert len(harness.calls.clear) == 0
        assert len(harness.calls.guard) == 0
        assert len(harness.calls.move) == 0
        assert harness.controller.initialWaveSent is False
        assert harness.controller.commanderPushActive is False
        assert harness.controller.commanderMobilizing is False
        assert harness.controller.commanderRetreating is False
        assert harness.controller.commanderToken is None
        assert plain(harness.controller.waveAssignments) == {}

    cases = (
        {"acu_idle": False},
        {"health_ratio": 0.749},
    )
    for options in cases:
        harness = make_harness()
        _, _, observation = commander_force(harness, acu_near_staging=False, **options)
        execute_intents(harness, [commander_mobilize_intent(observation)], observation)
        assert_rejected(harness)

    incomplete = make_harness()
    acu, _, observation = commander_force(incomplete, acu_near_staging=False)
    acu.options.fraction = 0.5
    observation = incomplete.observe()
    execute_intents(incomplete, [commander_mobilize_intent(observation)], observation)
    assert_rejected(incomplete)

    near = make_harness()
    _, _, observation = commander_force(near, acu_near_staging=True)
    execute_intents(near, [commander_mobilize_intent(observation)], observation)
    assert_rejected(near)

    pending = make_harness()
    _, _, observation = commander_force(pending, acu_near_staging=False)
    pending.controller.pending["1:1"] = lua_value(
        pending.lua,
        {"actorToken": "1:1", "kind": "build_structure", "issuedTick": 0},
    )
    execute_intents(pending, [commander_mobilize_intent(observation)], observation)
    assert_rejected(pending)

    for combat_count, artillery_count in ((23, 4), (24, 3)):
        below_gate = make_harness()
        _, _, observation = commander_force(
            below_gate,
            combat_count=combat_count,
            artillery_count=artillery_count,
            acu_near_staging=False,
        )
        execute_intents(below_gate, [commander_mobilize_intent(observation)], observation)
        assert_rejected(below_gate)

    malformed_target = make_harness()
    _, _, observation = commander_force(malformed_target, acu_near_staging=False)
    intent = commander_mobilize_intent(observation)
    intent["position"] = [999, 0, 999]
    execute_intents(malformed_target, [intent], observation)
    assert_rejected(malformed_target)

    for bad_position in (None, {}, [35], "bad", 7):
        malformed = make_harness()
        _, _, observation = commander_force(malformed, acu_near_staging=False)
        intent = commander_mobilize_intent(observation)
        intent["position"] = bad_position
        execute_intents(malformed, [intent], observation)
        assert_rejected(malformed)


def test_commander_mobilization_rolls_back_or_leaves_no_state_on_each_order_failure() -> None:
    def assert_pristine(harness: ControllerHarness) -> None:
        assert harness.controller.initialWaveSent is False
        assert harness.controller.commanderPushActive is False
        assert harness.controller.commanderMobilizing is False
        assert harness.controller.commanderRetreating is False
        assert harness.controller.commanderToken is None
        assert plain(harness.controller.waveAssignments) == {}

    clear_failure = make_harness()
    _, _, observation = commander_force(clear_failure, acu_near_staging=False)
    clear_intent = commander_mobilize_intent(observation)
    clear_failure.calls.failClear = True
    execute_intents(clear_failure, [clear_intent], observation)
    assert plain(clear_failure.calls.sequence) == ["clear"]
    assert_pristine(clear_failure)
    clear_failure.calls.failClear = False
    execute_intents(clear_failure, [clear_intent], observation)
    assert plain(clear_failure.calls.sequence)[-3:] == ["clear", "guard", "move"]
    assert clear_failure.controller.commanderMobilizing is True

    guard_failure = make_harness()
    _, _, observation = commander_force(guard_failure, acu_near_staging=False)
    guard_intent = commander_mobilize_intent(observation)
    guard_failure.calls.failGuard = True
    execute_intents(guard_failure, [guard_intent], observation)
    assert plain(guard_failure.calls.sequence) == ["clear", "guard"]
    assert_pristine(guard_failure)
    guard_failure.calls.failGuard = False
    execute_intents(guard_failure, [guard_intent], observation)
    assert plain(guard_failure.calls.sequence)[-3:] == ["clear", "guard", "move"]
    assert guard_failure.controller.commanderMobilizing is True

    move_failure = make_harness()
    _, _, observation = commander_force(move_failure, acu_near_staging=False)
    intent = commander_mobilize_intent(observation)
    move_failure.calls.failMove = True
    execute_intents(move_failure, [intent], observation)
    assert plain(move_failure.calls.sequence) == ["clear", "guard", "move", "clear"]
    assert len(move_failure.calls.clear[2].units) == 24
    assert_pristine(move_failure)

    move_failure.calls.failMove = False
    execute_intents(move_failure, [intent], observation)
    assert plain(move_failure.calls.sequence)[-3:] == ["clear", "guard", "move"]
    assert move_failure.controller.commanderMobilizing is True


def test_commander_push_guards_exact_deduplicated_combat_then_moves_only_acu() -> None:
    harness = make_harness()
    acu, combat, observation = commander_force(harness, health_ratio=0.75)
    valid_tokens = [record["token"] for record in plain(observation.units) if record["role"] in {"tank", "artillery"}]
    supplied = list(reversed(valid_tokens)) + [valid_tokens[0], "1:1", "999:1"]
    intent = commander_push_intent(observation, supplied)
    own_queries = len(harness.calls.own)
    enemy_queries = len(harness.calls.enemy)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.guard) == 1
    guard = harness.calls.guard[1]
    assert harness.lua.eval("function(a, b) return rawequal(a, b) end")(guard.target, acu)
    guarded_ids = [guard.units[index].GetEntityId(guard.units[index]) for index in range(1, len(guard.units) + 1)]
    expected_ids = [
        int(token.split(":")[0])
        for token in sorted(valid_tokens)
    ]
    assert guarded_ids == expected_ids
    assert plain(harness.calls.sequence) == ["clear", "guard", "aggressive"]
    assert len(harness.calls.clear) == 1
    cleared_ids = [
        harness.calls.clear[1].units[index].GetEntityId(harness.calls.clear[1].units[index])
        for index in range(1, len(harness.calls.clear[1].units) + 1)
    ]
    assert cleared_ids == expected_ids
    assert len(harness.calls.aggressive) == 1
    aggressive = harness.calls.aggressive[1]
    assert len(aggressive.units) == 1
    assert harness.lua.eval("function(a, b) return rawequal(a, b) end")(
        aggressive.units[1],
        acu,
    )
    assert harness.controller.initialWaveSent is True
    assert harness.controller.commanderPushActive is True
    assert harness.controller.commanderRetreating is False
    assert harness.controller.commanderToken == "1:1"
    assert harness.controller.waveAssignments["1:1"] is None
    assert all(harness.controller.waveAssignments[token] is not None for token in valid_tokens)
    assert len(harness.calls.own) == own_queries
    assert len(harness.calls.enemy) == enemy_queries
    assert any("name=commander_push" in line for line in harness.logs)


def test_step_keeps_ready_commander_cohort_local_during_macro_experiment() -> None:
    harness = make_harness()
    commander_force(harness, acu_near_staging=False)

    harness.lua.globals().Controller.Step(harness.controller)

    assert len(harness.calls.move) == 0
    assert len(harness.calls.guard) == 0
    assert len(harness.calls.clear) == 0
    assert len(harness.calls.aggressive) == 0
    assert harness.controller.initialWaveSent is False
    assert harness.controller.commanderMobilizing is False
    assert harness.controller.commanderPushActive is False
    assert len(plain(harness.controller.waveAssignments)) == 0


def test_persistent_immediate_contact_during_mobilization_uses_only_unassigned_reserves() -> None:
    harness = make_harness()
    acu, combat, observation = commander_force(harness, acu_near_staging=False)
    execute_intents(harness, [commander_mobilize_intent(observation)], observation)
    committed_tokens = {
        record["token"]
        for record in plain(observation.units)
        if record["role"] in {"tank", "artillery"}
    }
    reserves = [
        harness.unit(entityId=90, blueprintId="uel0201", position=plain(harness.controller.stagingPosition)),
        harness.unit(entityId=91, blueprintId="uel0103", position=plain(harness.controller.stagingPosition)),
    ]
    harness.brain.units = harness.lua.table_from([acu, *combat, *reserves])
    harness.brain.enemies = harness.lua.table_from(
        [harness.unit(entityId=200, blueprintId="url0201", army=2, position=[11, 2, 20])]
    )

    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    intents = plain(harness.lua.globals().Policy.Decide(observation))
    defense = [intent for intent in intents if intent["kind"] == "defend_wave"]

    assert not [intent for intent in intents if intent["kind"] == "retreat"]
    assert not [intent for intent in intents if intent["kind"] == "mobilize_commander"]
    assert not [intent for intent in intents if intent["kind"] == "commander_push"]
    assert len(defense) == 1
    assert set(defense[0]["actorTokens"]) == {"90:1", "91:1"}
    assert not set(defense[0]["actorTokens"]) & committed_tokens

    execute_intents(harness, intents, observation)
    assert len(harness.calls.guard) == 1
    assert len(harness.calls.move) == 1
    assert all(harness.controller.waveAssignments[token] is not None for token in committed_tokens)


def test_legacy_mobilized_state_never_transitions_to_cross_map_push() -> None:
    harness = make_harness()
    acu, combat, observation = commander_force(harness, acu_near_staging=False)
    execute_intents(harness, [commander_mobilize_intent(observation)], observation)
    combat[0].options.destroyed = True
    replacement = harness.unit(
        entityId=3,
        blueprintId="uel0201",
        position=plain(harness.controller.stagingPosition),
    )
    acu.options.position = lua_value(harness.lua, plain(harness.controller.stagingPosition))
    acu.options.idleState = True
    harness.brain.units = harness.lua.table_from([acu, replacement, *combat[2:]])
    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    intents = plain(harness.lua.globals().Policy.Decide(observation))
    assert not [
        intent for intent in intents
        if intent["kind"] in {"mobilize_commander", "commander_push", "reinforce_commander", "attack_wave"}
    ]
    assert len(harness.calls.aggressive) == 0


def test_losing_legacy_escorts_clears_state_without_rearming_offense() -> None:
    harness = make_harness()
    acu, _, observation = commander_force(harness, acu_near_staging=False)
    execute_intents(harness, [commander_mobilize_intent(observation)], observation)
    unrelated = harness.unit(
        entityId=90,
        blueprintId="uel0201",
        position=[110, 2, 120],
    )
    harness.controller.waveAssignments["90:1"] = lua_value(
        harness.lua,
        {
            "issuedTick": 0,
            "position": [110, 2, 120],
            "commanderEscort": False,
        },
    )
    harness.brain.units = harness.lua.table_from([acu, unrelated])

    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)

    assert harness.controller.commanderMobilizing is False
    assert harness.controller.commanderPushActive is False
    assert harness.controller.commanderRetreating is False
    assert harness.controller.commanderToken is None
    assert harness.controller.initialWaveSent is False
    assert harness.controller.waveAssignments["90:1"] is not None

    staging = plain(harness.controller.stagingPosition)
    fresh = [
        harness.unit(
            entityId=100 + offset,
            blueprintId="uel0103" if offset >= 20 else "uel0201",
            position=staging,
        )
        for offset in range(24)
    ]
    harness.brain.units = harness.lua.table_from([acu, unrelated, *fresh])
    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    intents = plain(harness.lua.globals().Policy.Decide(observation))

    assert not [
        intent for intent in intents
        if intent["kind"] in {"mobilize_commander", "commander_push", "reinforce_commander", "attack_wave"}
    ]
    assert harness.controller.commanderMobilizing is False
    assert harness.controller.commanderToken is None
    assert harness.controller.waveAssignments["90:1"] is not None


def test_legacy_mobilized_guard_is_never_given_a_push_by_policy() -> None:
    harness = make_harness()
    acu, _, observation = commander_force(harness, acu_near_staging=False)
    execute_intents(harness, [commander_mobilize_intent(observation)], observation)
    acu.options.position = lua_value(harness.lua, plain(harness.controller.stagingPosition))
    acu.options.idleState = True
    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    intents = plain(harness.lua.globals().Policy.Decide(observation))

    assert not [intent for intent in intents if intent["kind"] == "commander_push"]
    assert plain(harness.calls.sequence) == ["clear", "guard", "move"]
    assert harness.controller.commanderMobilizing is True
    assert harness.controller.commanderPushActive is False
    assert harness.controller.initialWaveSent is False
    assert len(plain(harness.controller.waveAssignments)) == 24
    assert len(harness.calls.guard) == 1


def test_low_health_mobilizing_commander_enters_existing_escort_recovery() -> None:
    harness = make_harness()
    acu, _, observation = commander_force(harness, acu_near_staging=False)
    execute_intents(harness, [commander_mobilize_intent(observation)], observation)
    acu.options.health = 74.9
    acu.options.maxHealth = 100
    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    intents = plain(harness.lua.globals().Policy.Decide(observation))
    retreat = next(intent for intent in intents if intent["kind"] == "retreat")

    execute_intents(harness, [retreat], observation)

    assert harness.controller.commanderMobilizing is False
    assert harness.controller.commanderPushActive is False
    assert harness.controller.commanderRetreating is True
    assert harness.controller.commanderToken == "1:1"
    assert len(plain(harness.controller.waveAssignments)) == 24


def test_commander_push_revalidates_gate_unique_tokens_and_unit_eligibility() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, combat_count=23, artillery_count=4)
    tokens = [record["token"] for record in plain(observation.units) if record["role"] in {"tank", "artillery"}]
    execute_intents(harness, [commander_push_intent(observation, tokens + [tokens[0]])], observation)
    assert len(harness.calls.guard) == 0

    only_three_arty = make_harness()
    _, _, observation = commander_force(only_three_arty, combat_count=24, artillery_count=3)
    execute_intents(only_three_arty, [commander_push_intent(observation)], observation)
    assert len(only_three_arty.calls.guard) == 0

    off_stage = make_harness()
    _, combat, _ = commander_force(off_stage)
    combat[0].options.position = lua_value(
        off_stage.lua,
        [110, 2, 120],
    )
    observation = off_stage.observe()
    execute_intents(off_stage, [commander_push_intent(observation)], observation)
    assert len(off_stage.calls.guard) == 0

    assigned = make_harness()
    _, _, _ = commander_force(assigned)
    assigned.controller.waveAssignments["2:1"] = lua_value(
        assigned.lua,
        {"issuedTick": 0, "position": plain(assigned.controller.stagingPosition)},
    )
    observation = assigned.observe()
    execute_intents(assigned, [commander_push_intent(observation)], observation)
    assert len(assigned.calls.guard) == 0


def test_commander_push_revalidates_exact_healthy_idle_complete_nonpending_acu() -> None:
    for options in ({"health_ratio": 0.749}, {"acu_idle": False}):
        harness = make_harness()
        _, _, observation = commander_force(harness, **options)
        execute_intents(harness, [commander_push_intent(observation)], observation)
        assert len(harness.calls.guard) == 0

    pending = make_harness()
    _, _, observation = commander_force(pending)
    pending.controller.pending["1:1"] = lua_value(
        pending.lua,
        {"actorToken": "1:1", "kind": "build_structure", "issuedTick": 0},
    )
    execute_intents(pending, [commander_push_intent(observation)], observation)
    assert len(pending.calls.guard) == 0

    incomplete = make_harness()
    acu, _, _ = commander_force(incomplete)
    acu.options.fraction = 0.5
    observation = incomplete.observe()
    execute_intents(incomplete, [commander_push_intent(observation)], observation)
    assert len(incomplete.calls.guard) == 0

    missing = make_harness()
    _, combat, _ = commander_force(missing)
    missing.brain.units = missing.lua.table_from(combat)
    observation = missing.observe()
    intent = commander_push_intent(observation)
    intent["acuToken"] = "1:1"
    execute_intents(missing, [intent], observation)
    assert len(missing.calls.guard) == 0


def test_commander_push_commits_atomically_across_both_engine_orders() -> None:
    guard_failure = make_harness()
    _, _, observation = commander_force(guard_failure)
    guard_failure.calls.failGuard = True
    execute_intents(guard_failure, [commander_push_intent(observation)], observation)
    assert len(guard_failure.calls.guard) == 1
    assert len(guard_failure.calls.aggressive) == 0
    assert plain(guard_failure.calls.sequence) == ["clear", "guard"]
    assert guard_failure.controller.commanderPushActive is False
    assert plain(guard_failure.controller.waveAssignments) == {}

    aggressive_failure = make_harness()
    _, _, observation = commander_force(aggressive_failure)
    aggressive_failure.calls.failAggressive = True
    execute_intents(aggressive_failure, [commander_push_intent(observation)], observation)
    assert len(aggressive_failure.calls.guard) == 1
    assert len(aggressive_failure.calls.aggressive) == 1
    assert len(aggressive_failure.calls.clear) == 2
    assert len(aggressive_failure.calls.clear[1].units) == 24
    assert len(aggressive_failure.calls.clear[2].units) == 24
    assert plain(aggressive_failure.calls.sequence) == [
        "clear",
        "guard",
        "aggressive",
        "clear",
    ]
    assert aggressive_failure.controller.initialWaveSent is False
    assert aggressive_failure.controller.commanderPushActive is False
    assert plain(aggressive_failure.controller.waveAssignments) == {}

    clear_failure = make_harness()
    _, _, observation = commander_force(clear_failure)
    clear_failure.calls.failClear = True
    execute_intents(clear_failure, [commander_push_intent(observation)], observation)
    assert len(clear_failure.calls.clear) == 1
    assert len(clear_failure.calls.guard) == 0
    assert len(clear_failure.calls.aggressive) == 0
    assert clear_failure.controller.initialWaveSent is False
    assert clear_failure.controller.commanderPushActive is False
    assert plain(clear_failure.controller.waveAssignments) == {}


def test_initial_offstage_mobilization_still_rejects_twenty_three_total_with_four_artillery() -> None:
    harness = make_harness()
    _, _, observation = commander_force(
        harness,
        combat_count=23,
        artillery_count=4,
        acu_near_staging=False,
    )

    execute_intents(harness, [commander_mobilize_intent(observation)], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert harness.controller.commanderMobilizing is False
    assert plain(harness.controller.waveAssignments) == {}


def test_initial_offstage_mobilization_still_rejects_twenty_four_total_with_three_artillery() -> None:
    harness = make_harness()
    _, _, observation = commander_force(
        harness,
        combat_count=24,
        artillery_count=3,
        acu_near_staging=False,
    )

    execute_intents(harness, [commander_mobilize_intent(observation)], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert harness.controller.commanderMobilizing is False
    assert plain(harness.controller.waveAssignments) == {}


def test_streaming_reinforcement_accepts_one_zero_artillery_actor() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, combat_count=1, artillery_count=0)
    activate_commander_push(harness)
    intent = commander_reinforcement_intent(observation)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.guard) == 1
    assert len(harness.calls.guard[1].units) == 1
    assert set(plain(harness.controller.waveAssignments)) == set(intent["actorTokens"])


def test_streaming_reinforcement_accepts_twenty_three_zero_artillery_actors() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, combat_count=23, artillery_count=0)
    activate_commander_push(harness)
    intent = commander_reinforcement_intent(observation)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.guard) == 1
    assert len(harness.calls.guard[1].units) == 23
    assert set(plain(harness.controller.waveAssignments)) == set(intent["actorTokens"])


def test_streaming_reinforcement_accepts_twenty_four_zero_artillery_actors() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, combat_count=24, artillery_count=0)
    activate_commander_push(harness)
    intent = commander_reinforcement_intent(observation)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.guard) == 1
    assert len(harness.calls.guard[1].units) == 24
    assert set(plain(harness.controller.waveAssignments)) == set(intent["actorTokens"])


def test_streaming_reinforcement_accepts_every_actor_in_oversized_cohort() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, combat_count=41, artillery_count=0)
    activate_commander_push(harness)
    intent = commander_reinforcement_intent(observation)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.guard) == 1
    assert len(harness.calls.guard[1].units) == 41
    assert set(plain(harness.controller.waveAssignments)) == set(intent["actorTokens"])


def test_streaming_reinforcement_deduplicates_tokens_without_dropping_actor() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, combat_count=1, artillery_count=0)
    activate_commander_push(harness)
    token = commander_reinforcement_intent(observation)["actorTokens"][0]
    intent = commander_reinforcement_intent(observation, [token, token, token])

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.clear) == 1
    assert len(harness.calls.clear[1].units) == 1
    assert len(harness.calls.guard) == 1
    assert len(harness.calls.guard[1].units) == 1
    assert set(plain(harness.controller.waveAssignments)) == {token}


def test_streaming_reinforcement_success_is_exact_clear_then_guard_transaction() -> None:
    harness = make_harness()
    harness.brain.tick = 321
    acu, combat, observation = commander_force(harness, combat_count=3, artillery_count=0)
    activate_commander_push(harness)
    intent = commander_reinforcement_intent(observation)

    execute_intents(harness, [intent], observation)

    assert plain(harness.calls.sequence) == ["clear", "guard"]
    assert len(harness.calls.clear[1].units) == 3
    assert len(harness.calls.guard[1].units) == 3
    assert harness.lua.eval("function(a, b) return rawequal(a, b) end")(
        harness.calls.guard[1].target,
        acu,
    )
    assert all(
        harness.lua.eval("function(a, b) return rawequal(a, b) end")(
            harness.calls.clear[1].units[index],
            combat[index - 1],
        )
        for index in range(1, 4)
    )
    assert harness.controller.initialWaveSent is True
    assert harness.controller.commanderPushActive is True
    assert harness.controller.commanderToken == "1:1"
    assert harness.controller.lastReinforcementTick == 321
    assignments = plain(harness.controller.waveAssignments)
    assert set(assignments) == set(intent["actorTokens"])
    assert all(assignment["commanderEscort"] is True for assignment in assignments.values())
    assert any(
        "event=order" in line
        and "command=reinforce_commander" in line
        and "units=3" in line
        for line in harness.logs
    )


def test_streaming_reinforcement_clear_failure_is_pristine_and_immediately_retryable() -> None:
    harness = make_harness()
    harness.brain.tick = 77
    _, _, observation = commander_force(harness, combat_count=1, artillery_count=0)
    activate_commander_push(harness)
    intent = commander_reinforcement_intent(observation)
    before_tick = harness.controller.lastReinforcementTick
    harness.calls.failClear = True

    execute_intents(harness, [intent], observation)

    assert plain(harness.calls.sequence) == ["clear"]
    assert plain(harness.controller.waveAssignments) == {}
    assert harness.controller.lastReinforcementTick == before_tick
    assert harness.controller.commanderPushActive is True
    assert harness.controller.commanderToken == "1:1"
    assert not any("command=reinforce_commander" in line for line in harness.logs)

    harness.calls.failClear = False
    execute_intents(harness, [intent], observation)

    assert plain(harness.calls.sequence) == ["clear", "clear", "guard"]
    assert set(plain(harness.controller.waveAssignments)) == set(intent["actorTokens"])
    assert harness.controller.lastReinforcementTick == 77


def test_streaming_reinforcement_guard_failure_is_pristine_and_immediately_retryable() -> None:
    harness = make_harness()
    harness.brain.tick = 88
    _, _, observation = commander_force(harness, combat_count=1, artillery_count=0)
    activate_commander_push(harness)
    intent = commander_reinforcement_intent(observation)
    before_tick = harness.controller.lastReinforcementTick
    harness.calls.failGuard = True

    execute_intents(harness, [intent], observation)

    assert plain(harness.calls.sequence) == ["clear", "guard"]
    assert plain(harness.controller.waveAssignments) == {}
    assert harness.controller.lastReinforcementTick == before_tick
    assert harness.controller.commanderPushActive is True
    assert harness.controller.commanderToken == "1:1"
    assert not any("command=reinforce_commander" in line for line in harness.logs)

    harness.calls.failGuard = False
    execute_intents(harness, [intent], observation)

    assert plain(harness.calls.sequence) == ["clear", "guard", "clear", "guard"]
    assert set(plain(harness.controller.waveAssignments)) == set(intent["actorTokens"])
    assert harness.controller.lastReinforcementTick == 88


def test_reinforcement_guards_live_commander_and_assigns_only_after_success() -> None:
    harness = make_harness()
    acu, _, observation = commander_force(harness, acu_idle=False)
    harness.controller.initialWaveSent = True
    harness.controller.commanderPushActive = True
    harness.controller.commanderToken = "1:1"
    intent = commander_push_intent(observation)
    intent["kind"] = "reinforce_commander"

    execute_intents(harness, [intent], observation)
    execute_intents(harness, [intent], observation)

    assert len(harness.calls.guard) == 1
    assert plain(harness.calls.sequence) == ["clear", "guard"]
    assert harness.lua.eval("function(a, b) return rawequal(a, b) end")(
        harness.calls.guard[1].target,
        acu,
    )
    assert len(harness.calls.aggressive) == 0
    assert harness.controller.waveAssignments["1:1"] is None
    assert all(
        harness.controller.waveAssignments[token] is not None
        for token in intent["actorTokens"]
    )

    failed = make_harness()
    _, _, observation = commander_force(failed, acu_idle=False)
    failed.controller.initialWaveSent = True
    failed.controller.commanderPushActive = True
    failed.controller.commanderToken = "1:1"
    failed.calls.failGuard = True
    failed_intent = commander_push_intent(observation)
    failed_intent["kind"] = "reinforce_commander"
    execute_intents(failed, [failed_intent], observation)
    assert plain(failed.controller.waveAssignments) == {}

    clear_failed = make_harness()
    _, _, observation = commander_force(clear_failed, acu_idle=False)
    clear_failed.controller.initialWaveSent = True
    clear_failed.controller.commanderPushActive = True
    clear_failed.controller.commanderToken = "1:1"
    clear_failed.calls.failClear = True
    clear_failed_intent = commander_push_intent(observation)
    clear_failed_intent["kind"] = "reinforce_commander"
    execute_intents(clear_failed, [clear_failed_intent], observation)
    assert len(clear_failed.calls.clear) == 1
    assert len(clear_failed.calls.guard) == 0
    assert plain(clear_failed.controller.waveAssignments) == {}


def test_streaming_reinforcement_rejects_empty_cohort() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, combat_count=0, artillery_count=0)
    activate_commander_push(harness)

    execute_intents(harness, [commander_reinforcement_intent(observation, [])], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert plain(harness.controller.waveAssignments) == {}


def test_streaming_reinforcement_rejects_stale_token_without_partial_assignment() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness)
    activate_commander_push(harness)
    intent = commander_reinforcement_intent(observation)
    intent["actorTokens"].append("999:1")

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert plain(harness.controller.waveAssignments) == {}


def test_streaming_reinforcement_rejects_dead_actor_changed_after_observation() -> None:
    harness = make_harness()
    _, combat, observation = commander_force(harness)
    activate_commander_push(harness)
    combat[0].options.destroyed = True

    execute_intents(harness, [commander_reinforcement_intent(observation)], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert plain(harness.controller.waveAssignments) == {}


def test_streaming_reinforcement_rejects_captured_actor_changed_after_observation() -> None:
    harness = make_harness()
    _, combat, observation = commander_force(harness)
    activate_commander_push(harness)
    combat[0].options.army = 2

    execute_intents(harness, [commander_reinforcement_intent(observation)], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert plain(harness.controller.waveAssignments) == {}


def test_streaming_reinforcement_rejects_recycled_actor_token_without_touching_replacement() -> None:
    harness = make_harness()
    acu, combat, stale_observation = commander_force(harness)
    activate_commander_push(harness)
    replacement = harness.unit(
        entityId=2,
        blueprintId="uel0201",
        position=plain(harness.controller.stagingPosition),
    )
    harness.brain.units = harness.lua.table_from([acu, replacement, *combat[1:]])
    fresh_observation = harness.observe()
    assert any(record["token"] == "2:2" for record in plain(fresh_observation.units))

    execute_intents(
        harness,
        [commander_reinforcement_intent(stale_observation)],
        stale_observation,
    )

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert plain(harness.controller.waveAssignments) == {}


def test_streaming_reinforcement_rejects_actor_that_became_incomplete_or_offstage() -> None:
    for change in ("incomplete", "offstage"):
        harness = make_harness()
        _, combat, observation = commander_force(harness)
        activate_commander_push(harness)
        if change == "incomplete":
            combat[0].options.fraction = 0.5
        else:
            combat[0].options.position = lua_value(harness.lua, [110, 2, 120])

        execute_intents(harness, [commander_reinforcement_intent(observation)], observation)

        assert len(harness.calls.clear) == 0
        assert len(harness.calls.guard) == 0
        assert plain(harness.controller.waveAssignments) == {}


def test_streaming_reinforcement_rejects_pending_actor_without_partial_assignment() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, combat_count=25, artillery_count=5)
    activate_commander_push(harness)
    token = commander_reinforcement_intent(observation)["actorTokens"][0]
    harness.controller.pending[token] = lua_value(
        harness.lua,
        {"actorToken": token, "kind": "factory_build", "issuedTick": 0},
    )

    execute_intents(harness, [commander_reinforcement_intent(observation)], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert plain(harness.controller.waveAssignments) == {}


def test_streaming_reinforcement_rejects_already_assigned_actor_without_reassigning_anyone() -> None:
    harness = make_harness()
    _, _, _ = commander_force(harness, combat_count=25, artillery_count=5)
    activate_commander_push(harness)
    token = "2:1"
    existing = {
        "issuedTick": 0,
        "position": plain(harness.controller.stagingPosition),
        "commanderEscort": True,
    }
    harness.controller.waveAssignments[token] = lua_value(harness.lua, existing)
    observation = harness.observe()

    execute_intents(harness, [commander_reinforcement_intent(observation)], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert plain(harness.controller.waveAssignments) == {token: existing}


def test_streaming_reinforcement_rejects_malformed_actor_token_without_partial_assignment() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness)
    activate_commander_push(harness)
    intent = commander_reinforcement_intent(observation)
    intent["actorTokens"].append(12345)

    execute_intents(harness, [intent], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert plain(harness.controller.waveAssignments) == {}


def test_streaming_reinforcement_revalidates_live_complete_healthy_exact_commander() -> None:
    missing = make_harness()
    _, combat, _ = commander_force(missing)
    activate_commander_push(missing)
    missing.brain.units = missing.lua.table_from(combat)
    observation = missing.observe()
    execute_intents(missing, [commander_reinforcement_intent(observation)], observation)
    assert len(missing.calls.guard) == 0

    incomplete = make_harness()
    acu, _, _ = commander_force(incomplete)
    activate_commander_push(incomplete)
    acu.options.fraction = 0.5
    observation = incomplete.observe()
    execute_intents(incomplete, [commander_reinforcement_intent(observation)], observation)
    assert len(incomplete.calls.guard) == 0

    unhealthy = make_harness()
    _, _, observation = commander_force(unhealthy, health_ratio=0.749)
    activate_commander_push(unhealthy)
    execute_intents(unhealthy, [commander_reinforcement_intent(observation)], observation)
    assert len(unhealthy.calls.guard) == 0

    malformed = make_harness()
    _, _, observation = commander_force(malformed)
    activate_commander_push(malformed)
    acu_record = next(record for record in observation.units.values() if record.role == "acu")
    acu_record.healthRatio = "malformed"
    execute_intents(malformed, [commander_reinforcement_intent(observation)], observation)
    assert len(malformed.calls.guard) == 0


def test_streaming_reinforcement_rejects_commander_captured_after_observation() -> None:
    harness = make_harness()
    acu, _, observation = commander_force(harness)
    activate_commander_push(harness)
    acu.options.army = 2

    execute_intents(harness, [commander_reinforcement_intent(observation)], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert plain(harness.controller.waveAssignments) == {}


def test_streaming_reinforcement_rejects_recycled_commander_token() -> None:
    harness = make_harness()
    _, combat, stale_observation = commander_force(harness)
    activate_commander_push(harness)
    replacement = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        position=plain(harness.controller.stagingPosition),
    )
    harness.brain.units = harness.lua.table_from([replacement, *combat])
    fresh_observation = harness.observe()
    assert any(record["token"] == "1:2" for record in plain(fresh_observation.units))

    execute_intents(
        harness,
        [commander_reinforcement_intent(stale_observation)],
        stale_observation,
    )

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert plain(harness.controller.waveAssignments) == {}


def test_streaming_reinforcement_rejects_pending_commander() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness)
    activate_commander_push(harness)
    harness.controller.pending["1:1"] = lua_value(
        harness.lua,
        {"actorToken": "1:1", "kind": "build_structure", "issuedTick": 0},
    )

    execute_intents(harness, [commander_reinforcement_intent(observation)], observation)

    assert len(harness.calls.clear) == 0
    assert len(harness.calls.guard) == 0
    assert plain(harness.controller.waveAssignments) == {}


def test_successful_streaming_actor_cannot_execute_another_combat_intent_same_decision() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, combat_count=1, artillery_count=0)
    activate_commander_push(harness)
    reinforcement = commander_reinforcement_intent(observation)
    attack = {
        "kind": "attack_wave",
        "actorTokens": reinforcement["actorTokens"],
        "position": plain(observation.targetPosition),
        "priority": 50,
    }

    execute_intents(harness, [reinforcement, attack], observation)

    assert len(harness.calls.guard) == 1
    assert len(harness.calls.aggressive) == 0
    assert set(plain(harness.controller.waveAssignments)) == set(reinforcement["actorTokens"])


def test_failed_commander_push_consumes_doctrine_actors_for_the_step() -> None:
    harness = make_harness()
    acu, _, observation = commander_force(harness)
    acu.options.canBuild = lua_value(harness.lua, {"ueb0101": True})
    observation = harness.observe()
    push = commander_push_intent(observation)
    harness.calls.failGuard = True
    lower_attack = {
        "kind": "attack_wave",
        "actorTokens": push["actorTokens"],
        "position": plain(observation.targetPosition),
        "priority": 50,
    }
    lower_build = {
        "kind": "build_structure",
        "actorToken": "1:1",
        "buildRole": "land_factory",
        "position": plain(observation.placements.land_factory[1]),
        "priority": 51,
    }

    execute_intents(harness, [push, lower_attack, lower_build], observation)

    assert len(harness.calls.guard) == 1
    assert len(harness.calls.aggressive) == 0
    assert len(harness.calls.buildMobile) == 0


def test_reinforcement_fails_closed_when_push_or_leader_is_not_active() -> None:
    inactive = make_harness()
    _, _, observation = commander_force(inactive)
    intent = commander_push_intent(observation)
    intent["kind"] = "reinforce_commander"
    execute_intents(inactive, [intent], observation)
    assert len(inactive.calls.guard) == 0

    wrong_leader = make_harness()
    _, _, observation = commander_force(wrong_leader)
    wrong_leader.controller.commanderPushActive = True
    wrong_leader.controller.commanderToken = "99:1"
    execute_intents(wrong_leader, [intent], observation)
    assert len(wrong_leader.calls.guard) == 0


def test_active_commander_retreat_latches_recovery_and_retains_escorts_after_move() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, health_ratio=0.749, acu_near_staging=False)
    harness.controller.initialWaveSent = True
    harness.controller.commanderPushActive = True
    harness.controller.commanderToken = "1:1"
    harness.controller.waveAssignments["2:1"] = lua_value(
        harness.lua,
        {"issuedTick": 0, "position": plain(harness.controller.stagingPosition), "commanderEscort": True},
    )
    retreat = {"kind": "retreat", "actorToken": "1:1", "position": plain(harness.controller.basePosition)}

    execute_intents(harness, [retreat], observation)

    assert len(harness.calls.move) == 1
    assert harness.controller.commanderPushActive is False
    assert harness.controller.commanderRetreating is True
    assert harness.controller.waveAssignments["2:1"] is not None
    assert len(harness.calls.clear) == 1
    assert len(harness.calls.clear[1].units) == 1

    failed = make_harness()
    _, _, failed_observation = commander_force(failed, health_ratio=0.749, acu_near_staging=False)
    failed.controller.commanderPushActive = True
    failed.controller.commanderToken = "1:1"
    failed.controller.waveAssignments["2:1"] = lua_value(
        failed.lua,
        {"issuedTick": 0, "position": plain(failed.controller.stagingPosition), "commanderEscort": True},
    )
    failed.calls.failMove = True
    execute_intents(failed, [retreat], failed_observation)
    assert failed.controller.commanderPushActive is True
    assert failed.controller.commanderRetreating is False
    assert failed.controller.waveAssignments["2:1"] is not None
    failed.calls.failMove = False
    execute_intents(failed, [retreat], failed_observation)
    assert len(failed.calls.move) == 2
    assert failed.controller.commanderRetreating is True


def test_failed_retreat_clear_stops_move_state_change_and_cooldown() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, health_ratio=0.749, acu_near_staging=False)
    harness.controller.commanderPushActive = True
    harness.controller.commanderToken = "1:1"
    harness.controller.waveAssignments["2:1"] = lua_value(
        harness.lua,
        {
            "issuedTick": 0,
            "position": plain(harness.controller.stagingPosition),
            "commanderEscort": True,
        },
    )
    retreat = {"kind": "retreat", "actorToken": "1:1", "position": plain(harness.controller.basePosition)}
    harness.calls.failClear = True

    execute_intents(harness, [retreat], observation)

    assert len(harness.calls.clear) == 1
    assert len(harness.calls.move) == 0
    assert harness.controller.commanderPushActive is True
    assert harness.controller.commanderRetreating is False
    assert harness.controller.waveAssignments["2:1"] is not None

    harness.calls.failClear = False
    execute_intents(harness, [retreat], observation)
    assert len(harness.calls.clear) == 2
    assert len(harness.calls.move) == 1
    assert harness.controller.commanderPushActive is False
    assert harness.controller.commanderRetreating is True
    assert harness.controller.waveAssignments["2:1"] is not None


def test_ordinary_retreat_does_not_release_unrelated_attack_assignments() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, health_ratio=0.54, acu_near_staging=False)
    harness.controller.waveAssignments["2:1"] = lua_value(
        harness.lua,
        {"issuedTick": 0, "position": plain(harness.controller.stagingPosition)},
    )

    execute_intents(
        harness,
        [{"kind": "retreat", "actorToken": "1:1", "position": plain(harness.controller.basePosition)}],
        observation,
    )

    assert harness.controller.waveAssignments["2:1"] is not None
    assert harness.controller.commanderRetreating is False


def test_commander_recovery_clears_only_at_home_and_leader_loss_clears_escort_state() -> None:
    harness = make_harness()
    acu, _, observation = commander_force(harness, health_ratio=0.9, acu_near_staging=False)
    acu.options.position = lua_value(harness.lua, [60, 2, 60])
    harness.controller.commanderRetreating = True
    harness.controller.commanderToken = "1:1"
    harness.controller.waveAssignments["2:1"] = lua_value(
        harness.lua,
        {
            "issuedTick": 0,
            "position": plain(harness.controller.stagingPosition),
            "commanderEscort": True,
        },
    )
    harness.controller.waveAssignments["3:1"] = lua_value(
        harness.lua,
        {"issuedTick": 0, "position": plain(harness.controller.stagingPosition)},
    )
    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    assert harness.controller.commanderRetreating is True
    assert observation.state.commanderRetreating is True
    assert harness.controller.waveAssignments["2:1"] is not None
    assert len(harness.calls.clear) == 0

    acu.options.position = lua_value(harness.lua, plain(harness.controller.basePosition))
    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    assert harness.controller.commanderRetreating is False
    assert observation.state.commanderRetreating is False
    assert harness.controller.commanderToken is None
    assert harness.controller.waveAssignments["2:1"] is None
    assert harness.controller.waveAssignments["3:1"] is not None
    assert len(harness.calls.clear) == 1
    assert len(harness.calls.clear[1].units) == 1
    assert harness.calls.clear[1].units[1].GetEntityId(harness.calls.clear[1].units[1]) == 2

    lost = make_harness()
    _, combat, _ = commander_force(lost)
    lost.controller.commanderPushActive = True
    lost.controller.commanderRetreating = True
    lost.controller.commanderToken = "1:1"
    lost.controller.waveAssignments["2:1"] = lua_value(
        lost.lua,
        {"issuedTick": 0, "position": plain(lost.controller.stagingPosition), "commanderEscort": True},
    )
    lost.brain.units = lost.lua.table_from(combat)
    observation = lost.observe()
    lost.lua.globals().Controller.Reconcile(lost.controller, observation)
    assert lost.controller.commanderPushActive is False
    assert lost.controller.commanderRetreating is False
    assert lost.controller.commanderToken is None
    assert lost.controller.waveAssignments["2:1"] is None


def test_retreating_commander_escorts_remain_assigned_and_excluded_from_defense() -> None:
    harness = make_harness()
    acu, _, observation = commander_force(harness, health_ratio=0.749, acu_near_staging=False)
    acu.options.position = lua_value(harness.lua, [60, 2, 60])
    harness.controller.commanderPushActive = True
    harness.controller.commanderToken = "1:1"
    harness.controller.waveAssignments["2:1"] = lua_value(
        harness.lua,
        {
            "issuedTick": 0,
            "position": plain(harness.controller.stagingPosition),
            "commanderEscort": True,
        },
    )
    observation = harness.observe()
    execute_intents(
        harness,
        [{"kind": "retreat", "actorToken": "1:1", "position": plain(harness.controller.basePosition)}],
        observation,
    )
    harness.brain.enemies = harness.lua.table_from(
        [harness.unit(entityId=90, blueprintId="url0201", position=[20, 2, 25])]
    )

    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    intents = plain(harness.lua.globals().Policy.Decide(observation))
    defense = [intent for intent in intents if intent["kind"] == "defend_wave"]

    assert harness.controller.commanderRetreating is True
    assert harness.controller.waveAssignments["2:1"] is not None
    assert next(record for record in plain(observation.units) if record["token"] == "2:1")["assignedToWave"] is True
    assert defense
    assert "2:1" not in defense[0]["actorTokens"]


def test_recovery_stays_latched_until_home_escort_clear_succeeds() -> None:
    harness = make_harness()
    _, _, observation = commander_force(harness, acu_near_staging=False)
    harness.controller.commanderRetreating = True
    harness.controller.commanderToken = "1:1"
    harness.controller.waveAssignments["2:1"] = lua_value(
        harness.lua,
        {
            "issuedTick": 0,
            "position": plain(harness.controller.stagingPosition),
            "commanderEscort": True,
        },
    )
    harness.calls.failClear = True

    harness.lua.globals().Controller.Reconcile(harness.controller, observation)

    assert len(harness.calls.clear) == 1
    assert harness.controller.commanderRetreating is True
    assert harness.controller.commanderToken == "1:1"
    assert harness.controller.waveAssignments["2:1"] is not None

    harness.calls.failClear = False
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)
    assert len(harness.calls.clear) == 2
    assert harness.controller.commanderRetreating is False
    assert harness.controller.commanderToken is None
    assert harness.controller.waveAssignments["2:1"] is None


def test_recycled_commander_entity_cannot_inherit_active_push_state() -> None:
    harness = make_harness()
    old_acu, combat, _ = commander_force(harness)
    harness.controller.commanderPushActive = True
    harness.controller.commanderToken = "1:1"
    harness.controller.waveAssignments["2:1"] = lua_value(
        harness.lua,
        {"issuedTick": 0, "position": plain(harness.controller.stagingPosition), "commanderEscort": True},
    )
    replacement = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        position=plain(harness.controller.stagingPosition),
    )
    assert replacement != old_acu
    harness.brain.units = harness.lua.table_from([replacement, *combat])

    observation = harness.observe()
    harness.lua.globals().Controller.Reconcile(harness.controller, observation)

    assert any(record["token"] == "1:2" for record in plain(observation.units))
    assert harness.controller.commanderPushActive is False
    assert harness.controller.commanderToken is None
    assert harness.controller.waveAssignments["2:1"] is None


def test_destroyed_or_captured_commander_clears_active_push_and_escorts() -> None:
    for condition in ("destroyed", "captured"):
        harness = make_harness()
        acu, _, _ = commander_force(harness)
        harness.controller.commanderPushActive = True
        harness.controller.commanderToken = "1:1"
        harness.controller.waveAssignments["2:1"] = lua_value(
            harness.lua,
            {
                "issuedTick": 0,
                "position": plain(harness.controller.stagingPosition),
                "commanderEscort": True,
            },
        )
        if condition == "destroyed":
            acu.options.destroyed = True
        else:
            acu.options.army = 2

        observation = harness.observe()
        harness.lua.globals().Controller.Reconcile(harness.controller, observation)

        assert harness.controller.commanderPushActive is False
        assert harness.controller.commanderToken is None
        assert harness.controller.waveAssignments["2:1"] is None


def test_missing_captured_or_recycled_commander_clears_mobilization_and_escorts() -> None:
    for condition in ("missing", "captured", "recycled"):
        harness = make_harness()
        acu, combat, _ = commander_force(harness, acu_near_staging=False)
        harness.controller.commanderMobilizing = True
        harness.controller.commanderToken = "1:1"
        harness.controller.waveAssignments["2:1"] = lua_value(
            harness.lua,
            {
                "issuedTick": 0,
                "position": plain(harness.controller.stagingPosition),
                "commanderEscort": True,
            },
        )
        if condition == "missing":
            harness.brain.units = harness.lua.table_from(combat)
        elif condition == "captured":
            acu.options.army = 2
        else:
            replacement = harness.unit(
                entityId=1,
                blueprintId="uel0001",
                position=plain(harness.controller.basePosition),
            )
            harness.brain.units = harness.lua.table_from([replacement, *combat])

        observation = harness.observe()
        harness.lua.globals().Controller.Reconcile(harness.controller, observation)

        assert harness.controller.commanderMobilizing is False
        assert harness.controller.commanderPushActive is False
        assert harness.controller.commanderRetreating is False
        assert harness.controller.commanderToken is None
        assert harness.controller.waveAssignments["2:1"] is None


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


def test_retreat_clear_exception_retains_preempted_build_and_reservation_until_retry() -> None:
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
    harness.calls.failClear = True
    retreat = {"kind": "retreat", "actorToken": "1:1", "position": [10, 0, 20]}

    execute_intents(harness, [retreat], observation)

    assert len(harness.calls.clear) == 1
    assert len(harness.calls.move) == 0
    assert harness.controller.pending["1:1"] is not None
    assert harness.controller.reservations[build["siteKey"]].actorToken == "1:1"
    harness.calls.failClear = False

    execute_intents(harness, [retreat], observation)

    assert len(harness.calls.clear) == 2
    assert len(harness.calls.move) == 1
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


def test_snapshot_telemetry_exposes_opening_gate_inputs_and_policy_output() -> None:
    harness = make_harness()
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        fraction=1,
        idleState=True,
        canBuild={"ueb0101": True},
    )
    harness.brain.units = harness.lua.table_from([acu])

    harness.lua.globals().Controller.Step(harness.controller)

    snapshot = next(line for line in harness.logs if "event=snapshot" in line)
    expected = {
        "acu_present=true",
        "acu_complete=true",
        "acu_idle=true",
        "acu_can_land_factory=true",
        "land_factory_placements=13",
        "mass_markers=3",
        "target_path=true",
        "policy_intents=1",
        "first_intent=build_structure",
        "first_build_role=land_factory",
    }
    assert all(field in snapshot for field in expected)


def test_snapshot_telemetry_counts_complete_combat_geometry_and_acu_state() -> None:
    harness = make_harness()
    acu = harness.unit(
        entityId=1,
        blueprintId="uel0001",
        position=[12, 2, 22],
        health=75,
        maxHealth=100,
    )
    assigned_near = harness.unit(entityId=2, blueprintId="uel0201", position=[110, 2, 110])
    assigned_far = harness.unit(entityId=3, blueprintId="uel0103", position=[80, 2, 80])
    available = harness.unit(entityId=4, blueprintId="uel0104", position=[33, 2, 43])
    incomplete = harness.unit(
        entityId=5,
        blueprintId="uel0201",
        position=[33, 2, 43],
        fraction=0.5,
    )
    harness.brain.units = harness.lua.table_from(
        [acu, assigned_near, assigned_far, available, incomplete]
    )
    harness.controller.waveAssignments["2:1"] = lua_value(
        harness.lua, {"issuedTick": 0, "position": [110, 2, 110]}
    )
    harness.controller.waveAssignments["3:1"] = lua_value(
        harness.lua, {"issuedTick": 0, "position": [80, 2, 80]}
    )

    harness.lua.globals().Controller.Step(harness.controller)

    snapshot = next(line for line in harness.logs if "event=snapshot" in line)
    expected = {
        "combat_total=3",
        "combat_assigned=2",
        "combat_available=1",
        "combat_near_staging=1",
        "assigned_min_target_distance=10",
        "assigned_max_target_distance=50",
        "acu_x=12",
        "acu_z=22",
        "acu_health_ratio=0.75",
        "enemy_contact=false",
    }
    order_names = (
        "buildMobile",
        "buildFactory",
        "rally",
        "guard",
        "aggressive",
        "move",
        "clear",
    )

    assert all(field in snapshot for field in expected)
    assert len(harness.calls.own) == 1
    assert len(harness.calls.enemy) == 1
    assert all(len(harness.calls[name]) == 0 for name in order_names)


def test_snapshot_combat_geometry_is_safe_without_assigned_units_acu_or_target() -> None:
    harness = make_harness()
    harness.controller.targetPosition = lua_value(harness.lua, ["malformed"])
    harness.brain.units = harness.lua.table_from([])
    enemy = harness.unit(entityId=90, blueprintId="url0201", position=[16, 2, 26])
    harness.brain.enemies = harness.lua.table_from([enemy])

    harness.lua.globals().Controller.Step(harness.controller)

    snapshot = next(line for line in harness.logs if "event=snapshot" in line)
    expected = {
        "combat_total=0",
        "combat_assigned=0",
        "combat_available=0",
        "combat_near_staging=0",
        "assigned_min_target_distance=-1",
        "assigned_max_target_distance=-1",
        "acu_x=-1",
        "acu_z=-1",
        "acu_health_ratio=-1",
        "enemy_contact=true",
    }
    order_names = (
        "buildMobile",
        "buildFactory",
        "rally",
        "guard",
        "aggressive",
        "move",
        "clear",
    )

    assert all(field in snapshot for field in expected)
    assert len(harness.calls.own) == 1
    assert len(harness.calls.enemy) == 1
    assert all(len(harness.calls[name]) == 0 for name in order_names)


def test_observation_is_single_pass_for_one_thousand_units() -> None:
    harness = make_harness()
    units = [harness.unit(entityId=index, blueprintId="uel0201", position=[index, 2, 20]) for index in range(1, 1001)]
    harness.brain.units = harness.lua.table_from(units)
    observation = harness.observe()
    assert len(observation.units) == 1000
    assert len(harness.calls.own) == 1 and len(harness.calls.enemy) == 1
