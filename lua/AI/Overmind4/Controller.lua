local Catalog = import('/mods/overmind4/lua/AI/Overmind4/Catalog.lua').Catalog
local Policy = import('/mods/overmind4/lua/AI/Overmind4/Policy.lua').Policy
local Telemetry = import('/mods/overmind4/lua/AI/Overmind4/Telemetry.lua').Telemetry
local MarkerUtilities = import('/lua/sim/MarkerUtilities.lua')
local NavUtils = import('/lua/sim/NavUtils.lua')

local STEP_TICKS = 10
local DEFENSE_RADIUS = 65
local IMMEDIATE_DANGER_DISTANCE = 20
local LOCAL_MASS_DISTANCE = 45
local STAGING_FRACTION = 0.23
local STAGING_RADIUS = 48
local VERIFY_TICKS = 3
local REJECT_TICKS = 12
local OPERATION_TIMEOUT_TICKS = 900
local REORDER_COOLDOWN_TICKS = 100
local WAVE_STUCK_TICKS = 300
local WAVE_STUCK_DISTANCE = 4
local SNAPSHOT_INTERVAL_TICKS = 300
local TableGetn = table.getn
local TableInsert = table.insert

local BUILD_ROLES = {
    acu = { 'land_factory', 'power_generator', 'mass_extractor' },
    engineer = { 'hydrocarbon', 'land_factory', 'mass_extractor', 'power_generator' },
    land_factory = { 'anti_air', 'artillery', 'engineer', 'lab', 'scout', 'tank' },
}

local COMBAT_ROLES = {
    anti_air = true,
    artillery = true,
    lab = true,
    tank = true,
}

local function SafeCall(defaultValue, fn, ...)
    local ok, value = pcall(fn, unpack(arg))
    if ok then
        return value
    end
    return defaultValue
end

local function CopyPosition(position)
    if type(position) ~= 'table'
        or type(position[1]) ~= 'number'
        or type(position[3]) ~= 'number'
    then
        return nil
    end
    return { position[1], tonumber(position[2]) or 0, position[3] }
end

local function TerrainPosition(position)
    local copy = CopyPosition(position)
    if not copy then
        return nil
    end
    copy[2] = GetTerrainHeight(copy[1], copy[3])
    return copy
end

local function DistanceSquared(a, b)
    if not a or not b then
        return 1000000000000
    end
    local dx = a[1] - b[1]
    local dz = a[3] - b[3]
    return dx * dx + dz * dz
end

local function Distance(a, b)
    return math.sqrt(DistanceSquared(a, b))
end

local function CurrentTick(controller)
    if controller.brain.tick ~= nil then
        return tonumber(controller.brain.tick) or 0
    end
    return tonumber(GetGameTick()) or 0
end

local function CountArray(values)
    local count = 0
    for _, _ in pairs(values or {}) do
        count = count + 1
    end
    return count
end

local function SortedKeys(values)
    local keys = {}
    for key, _ in pairs(values or {}) do
        TableInsert(keys, key)
    end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    return keys
end

local function Emit(controller, event, fields)
    fields = fields or {}
    fields.army = controller.brain.Army
    fields.event = event
    fields.tick = CurrentTick(controller)
    Telemetry.Emit('controller', fields)
end

local function MarkerArray(kind)
    local markers, count = MarkerUtilities.GetMarkersByType(kind)
    local copy = {}
    count = tonumber(count) or CountArray(markers)
    for index = 1, count do
        local marker = markers[index]
        if marker then
            local position = CopyPosition(marker.Position or marker.position)
            if position then
                TableInsert(copy, {
                    name = tostring(marker.Name or marker.name or (kind .. ' ' .. tostring(index))),
                    position = position,
                    occupiedSpawn = marker.IsOccupied == true,
                })
            end
        end
    end
    return copy
end

local function SortMarkers(markers, basePosition)
    for _, marker in ipairs(markers) do
        marker.distance = Distance(basePosition, marker.position)
    end
    table.sort(markers, function(a, b)
        if a.distance == b.distance then
            if a.name == b.name then
                if a.position[1] == b.position[1] then
                    return a.position[3] < b.position[3]
                end
                return a.position[1] < b.position[1]
            end
            return a.name < b.name
        end
        return a.distance < b.distance
    end)
end

local function QuantizedCoordinate(value)
    value = value * 1000
    if value >= 0 then
        return math.floor(value + 0.5)
    end
    return math.ceil(value - 0.5)
end

local function ResourceKey(kind, position)
    return kind .. ':'
        .. tostring(QuantizedCoordinate(position[1])) .. ':'
        .. tostring(QuantizedCoordinate(position[3]))
end

local function Reachable(basePosition, position)
    local ok, result = pcall(NavUtils.CanPathTo, 'Land', basePosition, position)
    return ok and result == true
end

local function ResourceMarkers(kind, basePosition)
    local resources = MarkerArray(kind)
    SortMarkers(resources, basePosition)
    local unique = {}
    local seen = {}
    for _, marker in ipairs(resources) do
        marker.key = ResourceKey(kind, marker.position)
        if not seen[marker.key] then
            seen[marker.key] = true
            marker.reachable = Reachable(basePosition, marker.position)
            marker.localSite = marker.distance <= LOCAL_MASS_DISTANCE
            TableInsert(unique, marker)
        end
    end
    return unique
end

local function ChooseTarget(spawns, basePosition)
    local occupied = {}
    local fallback = {}
    for _, spawn in ipairs(spawns) do
        if DistanceSquared(spawn.position, basePosition) > 25 then
            TableInsert(fallback, spawn)
            if spawn.occupiedSpawn then
                TableInsert(occupied, spawn)
            end
        end
    end
    local candidates = TableGetn(occupied) > 0 and occupied or fallback
    table.sort(candidates, function(a, b)
        if a.distance == b.distance then
            return a.name < b.name
        end
        return a.distance > b.distance
    end)
    return candidates[1] and CopyPosition(candidates[1].position) or nil
end

local function StagingPosition(basePosition, targetPosition)
    if not targetPosition then
        return CopyPosition(basePosition)
    end
    local x = basePosition[1] + (targetPosition[1] - basePosition[1]) * STAGING_FRACTION
    local z = basePosition[3] + (targetPosition[3] - basePosition[3]) * STAGING_FRACTION
    return TerrainPosition({ x, 0, z })
end

local function PlacementSeeds(controller)
    local base = controller.basePosition
    local target = controller.targetPosition or { base[1] + 1, base[2], base[3] }
    local dx = target[1] - base[1]
    local dz = target[3] - base[3]
    local length = math.sqrt(dx * dx + dz * dz)
    if length < 1 then
        dx, dz, length = 1, 0, 1
    end
    local fx, fz = dx / length, dz / length
    local sx, sz = -fz, fx
    local offsets = {
        { 11, 0 }, { 13, 7 }, { 13, -7 }, { 18, 0 },
        { 8, 9 }, { 8, -9 }, { 18, 9 }, { 18, -9 },
        { 24, 0 }, { 24, 9 }, { 24, -9 }, { 6, 14 }, { 6, -14 },
    }
    local seeds = {}
    for _, offset in ipairs(offsets) do
        local x = base[1] + fx * offset[1] + sx * offset[2]
        local z = base[3] + fz * offset[1] + sz * offset[2]
        TableInsert(seeds, TerrainPosition({ x, 0, z }))
    end
    return seeds
end

local function CountRole(units, role)
    local count = 0
    for _, unit in ipairs(units or {}) do
        if unit.role == role then
            count = count + 1
        end
    end
    return count
end

local function RecordByToken(units)
    local records = {}
    for _, unit in ipairs(units or {}) do
        records[unit.token] = unit
    end
    return records
end

local function PendingArray(controller)
    local pending = {}
    for _, token in ipairs(SortedKeys(controller.pending)) do
        local operation = controller.pending[token]
        TableInsert(pending, {
            actorToken = operation.actorToken,
            kind = operation.kind,
            buildRole = operation.buildRole,
            siteKey = operation.siteKey,
            issuedTick = operation.issuedTick,
        })
    end
    return pending
end

local function CanUnitBuild(unit, blueprintId)
    if not unit or not blueprintId or type(unit.CanBuild) ~= 'function' then
        return false
    end
    return SafeCall(false, unit.CanBuild, unit, blueprintId) == true
end

local function UnitToken(controller, unit, entityId)
    local entry = controller.entityGenerations[entityId]
    if not entry then
        entry = { reference = unit, generation = 1 }
        controller.entityGenerations[entityId] = entry
    elseif entry.reference ~= unit then
        entry.reference = unit
        entry.generation = entry.generation + 1
    end
    return tostring(entityId) .. ':' .. tostring(entry.generation)
end

local function NormalizeOwnUnit(controller, unit)
    if not unit or unit.Dead == true then
        return nil
    end
    if SafeCall(true, unit.BeenDestroyed, unit) == true then
        return nil
    end
    if SafeCall(-1, unit.GetArmy, unit) ~= controller.brain.Army then
        return nil
    end

    local blueprint = SafeCall(nil, unit.GetBlueprint, unit)
    local role = blueprint and Catalog.RoleFor(blueprint.BlueprintId) or nil
    local entityId = SafeCall(nil, unit.GetEntityId, unit)
    local position = CopyPosition(SafeCall(nil, unit.GetPosition, unit))
    if not role or entityId == nil or not position then
        return nil
    end

    local fraction = tonumber(SafeCall(0, unit.GetFractionComplete, unit)) or 0
    local complete = fraction >= 1
    local busy = SafeCall(false, unit.IsIdleState, unit) ~= true
        or SafeCall(false, unit.IsUnitState, unit, 'Building') == true
        or SafeCall(false, unit.IsUnitState, unit, 'Upgrading') == true
        or SafeCall(false, unit.IsUnitState, unit, 'Enhancing') == true
        or SafeCall(false, unit.IsUnitState, unit, 'Moving') == true
        or SafeCall(false, unit.IsPaused, unit) == true
    local token = UnitToken(controller, unit, entityId)
    local canBuild = {}
    for _, buildRole in ipairs(BUILD_ROLES[role] or {}) do
        canBuild[buildRole] = CanUnitBuild(unit, Catalog.IdFor(buildRole))
    end
    local health = tonumber(SafeCall(0, unit.GetHealth, unit)) or 0
    local maxHealth = tonumber(SafeCall(1, unit.GetMaxHealth, unit)) or 1
    local healthRatio = maxHealth > 0 and health / maxHealth or 0
    local assigned = controller.waveAssignments[token] ~= nil
    local nearStaging = DistanceSquared(position, controller.stagingPosition) <= STAGING_RADIUS * STAGING_RADIUS

    controller.unitRefs[token] = unit
    return {
        token = token,
        role = role,
        complete = complete,
        idle = complete and not busy,
        busy = busy,
        healthRatio = healthRatio,
        position = position,
        canBuild = canBuild,
        needsRally = role == 'land_factory' and controller.rallied[token] ~= true,
        assignedToWave = assigned,
        nearStaging = nearStaging,
        availableForWave = COMBAT_ROLES[role] == true and complete and not assigned and nearStaging,
    }
end

local function NormalizeEnemyContact(controller, enemies, ownRecords)
    local positions = {}
    for _, enemy in pairs(enemies or {}) do
        local position = CopyPosition(SafeCall(nil, enemy.GetPosition, enemy))
        if position then
            TableInsert(positions, position)
        end
    end
    table.sort(positions, function(a, b)
        local ad = DistanceSquared(a, controller.basePosition)
        local bd = DistanceSquared(b, controller.basePosition)
        if ad == bd then
            if a[1] == b[1] then return a[3] < b[3] end
            return a[1] < b[1]
        end
        return ad < bd
    end)
    if TableGetn(positions) == 0 then
        return nil
    end

    local acuPosition = controller.basePosition
    for _, record in ipairs(ownRecords) do
        if record.role == 'acu' then
            acuPosition = record.position
            break
        end
    end
    return {
        position = positions[1],
        immediate = DistanceSquared(positions[1], acuPosition)
            <= IMMEDIATE_DANGER_DISTANCE * IMMEDIATE_DANGER_DISTANCE,
    }
end

local function SiteSnapshot(controller, markers, ownRecords)
    local sites = {}
    for _, marker in ipairs(markers) do
        local occupied = false
        local expectedRole = marker.kind == 'hydro' and 'hydrocarbon' or 'mass_extractor'
        for _, unit in ipairs(ownRecords) do
            if unit.role == expectedRole and DistanceSquared(unit.position, marker.position) <= 16 then
                occupied = true
                break
            end
        end
        TableInsert(sites, {
            key = marker.key,
            name = marker.name,
            position = CopyPosition(marker.position),
            distance = marker.distance,
            localSite = marker.localSite,
            reachable = marker.reachable,
            buildable = SafeCall(
                false,
                controller.brain.CanBuildStructureAt,
                controller.brain,
                Catalog.IdFor(expectedRole),
                marker.position
            ) == true,
            occupied = occupied,
            reserved = controller.reservations[marker.key] ~= nil,
        })
    end
    return sites
end

local function PlacementSnapshot(controller)
    local placements = { land_factory = {}, power_generator = {} }
    for _, role in ipairs({ 'land_factory', 'power_generator' }) do
        local blueprintId = Catalog.IdFor(role)
        for _, seed in ipairs(controller.placementSeeds) do
            if SafeCall(false, controller.brain.CanBuildStructureAt, controller.brain, blueprintId, seed) == true then
                TableInsert(placements[role], CopyPosition(seed))
            end
        end
    end
    return placements
end

local function StateSnapshot(controller)
    return {
        initialWaveSent = controller.initialWaveSent,
        lastWaveTick = controller.lastWaveTick,
        lastReinforcementTick = controller.lastReinforcementTick,
    }
end

local function Phase(observation)
    local factories = CountRole(observation.units, 'land_factory')
    local combat = CountRole(observation.units, 'tank')
        + CountRole(observation.units, 'artillery')
        + CountRole(observation.units, 'anti_air')
        + CountRole(observation.units, 'lab')
    if observation.state.initialWaveSent then return 'attack' end
    if combat >= 10 then return 'concentrate' end
    if factories >= 2 then return 'expand' end
    return 'opening'
end

local function Signature(intent)
    local position = intent.position or {}
    return tostring(intent.kind) .. ':'
        .. tostring(intent.actorToken or '') .. ':'
        .. tostring(intent.buildRole or '') .. ':'
        .. tostring(intent.siteKey or '') .. ':'
        .. tostring(math.floor((tonumber(position[1]) or 0) + 0.5)) .. ':'
        .. tostring(math.floor((tonumber(position[3]) or 0) + 0.5))
end

local function ReleaseOperation(controller, token, reason)
    local operation = controller.pending[token]
    if not operation then return end
    if operation.siteKey and controller.reservations[operation.siteKey] then
        controller.reservations[operation.siteKey] = nil
    end
    controller.pending[token] = nil
    if reason then
        Emit(controller, 'operation_released', {
            actor = token,
            reason = reason,
            role = operation.buildRole or 'none',
        })
    end
end

local function SiteOccupied(observation, siteKey)
    if not siteKey then return false end
    for _, collection in pairs(observation.sites or {}) do
        for _, site in ipairs(collection or {}) do
            if site.key == siteKey and site.occupied == true then
                return true
            end
        end
    end
    return false
end

local function OrderAllowed(controller, signature)
    local previous = controller.lastOrders[signature]
    local tick = CurrentTick(controller)
    if previous and tick - previous < REORDER_COOLDOWN_TICKS then
        return false
    end
    controller.lastOrders[signature] = tick
    return true
end

local function RecordPending(controller, intent, observation)
    local operation = {
        actorToken = intent.actorToken,
        kind = intent.kind,
        buildRole = intent.buildRole,
        siteKey = intent.siteKey,
        issuedTick = CurrentTick(controller),
        baselineCount = CountRole(observation.units, intent.buildRole),
        accepted = false,
    }
    controller.pending[intent.actorToken] = operation
    if intent.siteKey then
        controller.reservations[intent.siteKey] = {
            actorToken = intent.actorToken,
            issuedTick = operation.issuedTick,
        }
    end
end

local function ExecuteStructure(controller, intent, observation, record)
    if controller.pending[intent.actorToken]
        or record.complete ~= true
        or record.idle ~= true
        or not record.canBuild
        or record.canBuild[intent.buildRole] ~= true
    then
        return false
    end
    if intent.siteKey and controller.reservations[intent.siteKey] then
        return false
    end
    local blueprintId = Catalog.IdFor(intent.buildRole)
    local position = TerrainPosition(intent.position)
    if not blueprintId or not position then return false end
    if SafeCall(false, controller.brain.CanBuildStructureAt, controller.brain, blueprintId, position) ~= true then
        return false
    end
    local actor = controller.unitRefs[intent.actorToken]
    if not actor or not CanUnitBuild(actor, blueprintId) then return false end

    RecordPending(controller, intent, observation)
    local ok = pcall(function() IssueBuildMobile({ actor }, position, blueprintId, {}) end)
    if not ok then
        ReleaseOperation(controller, intent.actorToken, 'command_error')
        return false
    end
    Emit(controller, 'order', {
        actor = intent.actorToken,
        command = 'build_structure',
        role = intent.buildRole,
        site = intent.siteKey or 'placement',
    })
    return true
end

local function ExecuteFactoryProduction(controller, intent, observation, record)
    if controller.pending[intent.actorToken]
        or record.role ~= 'land_factory'
        or record.complete ~= true
        or record.idle ~= true
        or not record.canBuild
        or record.canBuild[intent.buildRole] ~= true
    then
        return false
    end
    local blueprintId = Catalog.IdFor(intent.buildRole)
    local actor = controller.unitRefs[intent.actorToken]
    if not actor or not blueprintId or not CanUnitBuild(actor, blueprintId) then return false end
    RecordPending(controller, intent, observation)
    local ok = pcall(function() IssueBuildFactory({ actor }, blueprintId, 1) end)
    if not ok then
        ReleaseOperation(controller, intent.actorToken, 'command_error')
        return false
    end
    Emit(controller, 'order', {
        actor = intent.actorToken,
        command = 'factory_build',
        role = intent.buildRole,
    })
    return true
end

local function ExecuteRally(controller, intent, record)
    if controller.rallied[intent.actorToken]
        or record.role ~= 'land_factory'
        or record.complete ~= true
    then
        return false
    end
    local actor = controller.unitRefs[intent.actorToken]
    local position = TerrainPosition(intent.position)
    if not actor or not position then return false end
    local ok = pcall(function() IssueFactoryRallyPoint({ actor }, position) end)
    if not ok then return false end
    controller.rallied[intent.actorToken] = true
    Emit(controller, 'order', {
        actor = intent.actorToken,
        command = 'rally',
        role = 'land_factory',
    })
    return true
end

local function GroupRecords(controller, tokens, recordByToken, usedActors)
    local selected = {}
    local sorted = {}
    for _, token in ipairs(tokens or {}) do TableInsert(sorted, token) end
    table.sort(sorted)
    for _, token in ipairs(sorted) do
        local record = recordByToken[token]
        if record
            and COMBAT_ROLES[record.role]
            and record.complete == true
            and not usedActors[token]
        then
            TableInsert(selected, record)
        end
    end
    return selected
end

local function ExecuteCombatGroup(controller, intent, recordByToken, usedActors)
    local records = GroupRecords(controller, intent.actorTokens, recordByToken, usedActors)
    local actors = {}
    local tokens = {}
    for _, record in ipairs(records) do
        local actor = controller.unitRefs[record.token]
        if actor and (intent.kind ~= 'attack_wave' or not controller.waveAssignments[record.token]) then
            TableInsert(actors, actor)
            TableInsert(tokens, record.token)
        end
    end
    if TableGetn(actors) == 0 then return false end

    local position = TerrainPosition(intent.position)
    if not position then return false end
    local signature = Signature(intent) .. ':' .. table.concat(tokens, ',')
    if not OrderAllowed(controller, signature) then return false end

    if intent.kind == 'defend_wave' then
        local clearKey = 'defend:' .. signature
        if not controller.safetyCleared[clearKey] then
            IssueClearCommands(actors)
            controller.safetyCleared[clearKey] = true
        end
    end
    local ok
    if intent.kind == 'regroup_wave' then
        ok = pcall(function() IssueMove(actors, position) end)
    else
        ok = pcall(function() IssueAggressiveMove(actors, position) end)
    end
    if not ok then return false end

    local tick = CurrentTick(controller)
    for _, record in ipairs(records) do
        usedActors[record.token] = true
        if intent.kind == 'attack_wave' then
            controller.waveAssignments[record.token] = {
                issuedTick = tick,
                position = CopyPosition(record.position),
            }
        end
    end
    if intent.kind == 'attack_wave' then
        if controller.initialWaveSent then
            controller.lastReinforcementTick = tick
        else
            controller.initialWaveSent = true
            controller.lastWaveTick = tick
            controller.lastReinforcementTick = tick
            Emit(controller, 'milestone', { name = 'first_wave', units = TableGetn(actors) })
        end
    end
    Emit(controller, 'order', {
        actor = 'group',
        command = intent.kind,
        role = 'combat',
        units = TableGetn(actors),
    })
    return true
end

local function ExecuteRetreat(controller, intent, record)
    if record.role ~= 'acu' or record.complete ~= true then return false end
    local actor = controller.unitRefs[intent.actorToken]
    local position = TerrainPosition(intent.position)
    if not actor or not position then return false end
    local signature = Signature(intent)
    if not OrderAllowed(controller, signature) then return false end
    ReleaseOperation(controller, intent.actorToken, 'retreat_preempted')
    local clearKey = 'retreat:' .. intent.actorToken
    if not controller.safetyCleared[clearKey] then
        IssueClearCommands({ actor })
        controller.safetyCleared[clearKey] = true
    end
    local ok = pcall(function() IssueMove({ actor }, position) end)
    if not ok then return false end
    Emit(controller, 'order', {
        actor = intent.actorToken,
        command = 'retreat',
        role = 'acu',
    })
    return true
end

Controller = {}

Controller.InitializeMap = function(controller)
    if controller.mapInitialized then return end
    controller.mapInitialized = true
    if not NavUtils.IsGenerated() then
        NavUtils.Generate()
    end
    controller.markers = {
        mass = ResourceMarkers('Mass', controller.basePosition),
        hydro = ResourceMarkers('Hydrocarbon', controller.basePosition),
        spawn = MarkerArray('Spawn'),
    }
    for _, marker in ipairs(controller.markers.mass) do marker.kind = 'mass' end
    for _, marker in ipairs(controller.markers.hydro) do marker.kind = 'hydro' end
    SortMarkers(controller.markers.spawn, controller.basePosition)
    controller.targetPosition = ChooseTarget(controller.markers.spawn, controller.basePosition)
    controller.targetPath = controller.targetPosition ~= nil
        and Reachable(controller.basePosition, controller.targetPosition)
    controller.stagingPosition = StagingPosition(controller.basePosition, controller.targetPosition)
    controller.placementSeeds = PlacementSeeds(controller)
end

Controller.Create = function(brain)
    local startX, startZ = brain:GetArmyStartPos()
    local controller = {
        brain = brain,
        stopped = false,
        unsupported = brain:GetFactionIndex() ~= 1,
        basePosition = TerrainPosition({ startX, 0, startZ }),
        entityGenerations = {},
        unitRefs = {},
        pending = {},
        reservations = {},
        rallied = {},
        waveAssignments = {},
        safetyCleared = {},
        lastOrders = {},
        initialWaveSent = false,
        lastWaveTick = -10000,
        lastReinforcementTick = -10000,
        lastSnapshotTick = -SNAPSHOT_INTERVAL_TICKS,
        lastErrorTick = -REORDER_COOLDOWN_TICKS,
    }
    Controller.InitializeMap(controller)
    Emit(controller, controller.unsupported and 'unsupported_faction' or 'created', {
        faction = brain:GetFactionIndex(),
    })
    return controller
end

Controller.Observe = function(controller)
    controller.unitRefs = {}
    local ownUnits = controller.brain:GetListOfUnits(categories.ALLUNITS, false, false) or {}
    local units = {}
    for _, unit in pairs(ownUnits) do
        local record = NormalizeOwnUnit(controller, unit)
        if record then TableInsert(units, record) end
    end
    table.sort(units, function(a, b) return a.token < b.token end)

    local enemies = controller.brain:GetUnitsAroundPoint(
        categories.MOBILE, controller.basePosition, DEFENSE_RADIUS, 'Enemy'
    ) or {}
    local observation = {
        tick = CurrentTick(controller),
        basePosition = CopyPosition(controller.basePosition),
        stagingPosition = CopyPosition(controller.stagingPosition),
        targetPosition = CopyPosition(controller.targetPosition),
        targetPath = controller.targetPath,
        economy = {
            energyTrend = SafeCall(0, controller.brain.GetEconomyTrend, controller.brain, 'ENERGY'),
            energyStoredRatio = SafeCall(0, controller.brain.GetEconomyStoredRatio, controller.brain, 'ENERGY'),
            energyIncome = SafeCall(0, controller.brain.GetEconomyIncome, controller.brain, 'ENERGY'),
            energyUsage = SafeCall(0, controller.brain.GetEconomyUsage, controller.brain, 'ENERGY'),
            massTrend = SafeCall(0, controller.brain.GetEconomyTrend, controller.brain, 'MASS'),
            massStoredRatio = SafeCall(0, controller.brain.GetEconomyStoredRatio, controller.brain, 'MASS'),
            massIncome = SafeCall(0, controller.brain.GetEconomyIncome, controller.brain, 'MASS'),
            massUsage = SafeCall(0, controller.brain.GetEconomyUsage, controller.brain, 'MASS'),
        },
        units = units,
        enemyContact = NormalizeEnemyContact(controller, enemies, units),
        sites = {
            mass = SiteSnapshot(controller, controller.markers.mass, units),
            hydro = SiteSnapshot(controller, controller.markers.hydro, units),
        },
        placements = PlacementSnapshot(controller),
        pending = PendingArray(controller),
        state = StateSnapshot(controller),
    }
    return observation
end

Controller.Reconcile = function(controller, observation)
    local records = RecordByToken(observation.units)
    local tick = CurrentTick(controller)
    for _, token in ipairs(SortedKeys(controller.pending)) do
        local operation = controller.pending[token]
        local record = records[token]
        local elapsed = tick - operation.issuedTick
        if not record then
            ReleaseOperation(controller, token, 'actor_missing')
        elseif SiteOccupied(observation, operation.siteKey)
            or CountRole(observation.units, operation.buildRole) > operation.baselineCount
        then
            ReleaseOperation(controller, token, nil)
        elseif elapsed >= VERIFY_TICKS then
            if record.busy then operation.accepted = true end
            if not operation.accepted and elapsed > REJECT_TICKS then
                ReleaseOperation(controller, token, 'rejected')
            elseif elapsed > OPERATION_TIMEOUT_TICKS then
                ReleaseOperation(controller, token, 'timeout')
            end
        end
    end

    for _, token in ipairs(SortedKeys(controller.waveAssignments)) do
        local assignment = controller.waveAssignments[token]
        local record = records[token]
        if not record then
            controller.waveAssignments[token] = nil
        elseif tick - assignment.issuedTick >= WAVE_STUCK_TICKS then
            if Distance(record.position, assignment.position) < WAVE_STUCK_DISTANCE then
                controller.waveAssignments[token] = nil
                Emit(controller, 'wave_released', { actor = token, reason = 'stuck' })
            else
                assignment.issuedTick = tick
                assignment.position = CopyPosition(record.position)
            end
        end
    end

    observation.pending = PendingArray(controller)
    observation.state = StateSnapshot(controller)
end

Controller.Execute = function(controller, intents, observation)
    local records = RecordByToken(observation.units)
    local ordered = {}
    for _, intent in ipairs(intents or {}) do TableInsert(ordered, intent) end
    table.sort(ordered, function(a, b)
        local ap = tonumber(a.priority) or 1000
        local bp = tonumber(b.priority) or 1000
        if ap == bp then return Signature(a) < Signature(b) end
        return ap < bp
    end)
    local usedActors = {}

    for _, intent in ipairs(ordered) do
        if intent.kind == 'attack_wave'
            or intent.kind == 'defend_wave'
            or intent.kind == 'regroup_wave'
        then
            ExecuteCombatGroup(controller, intent, records, usedActors)
        elseif intent.actorToken and not usedActors[intent.actorToken] then
            local record = records[intent.actorToken]
            if record then
                local issued = false
                if intent.kind == 'build_structure' then
                    issued = ExecuteStructure(controller, intent, observation, record)
                elseif intent.kind == 'factory_build' then
                    issued = ExecuteFactoryProduction(controller, intent, observation, record)
                elseif intent.kind == 'rally' then
                    issued = ExecuteRally(controller, intent, record)
                elseif intent.kind == 'retreat' then
                    issued = ExecuteRetreat(controller, intent, record)
                end
                if issued then usedActors[intent.actorToken] = true end
            end
        end
    end
end

Controller.Step = function(controller)
    if controller.stopped or controller.unsupported then return end
    local observation = Controller.Observe(controller)
    Controller.Reconcile(controller, observation)
    local intents = Policy.Decide(observation)
    Controller.Execute(controller, intents, observation)

    local phase = Phase(observation)
    if phase ~= controller.phase then
        controller.phase = phase
        Emit(controller, 'phase', { name = phase })
    end
    local tick = CurrentTick(controller)
    if tick - controller.lastSnapshotTick >= SNAPSHOT_INTERVAL_TICKS then
        controller.lastSnapshotTick = tick
        Emit(controller, 'snapshot', {
            phase = phase,
            units = TableGetn(observation.units),
            pending = CountArray(controller.pending),
            reservations = CountArray(controller.reservations),
        })
    end
end

Controller.Run = function(owner, controller)
    controller = controller or owner
    Emit(controller, 'started', { step_ticks = STEP_TICKS })
    while not controller.stopped do
        local ok, message = pcall(Controller.Step, controller)
        if not ok then
            local tick = CurrentTick(controller)
            if tick - controller.lastErrorTick >= REORDER_COOLDOWN_TICKS then
                controller.lastErrorTick = tick
                Emit(controller, 'step_error', { message = tostring(message) })
            end
        end
        WaitTicks(STEP_TICKS)
    end
end

Controller.Stop = function(controller, reason)
    if not controller or controller.stopped then return end
    controller.stopped = true
    Emit(controller, 'stopped', { reason = reason or 'unknown' })
end
