local Catalog = import('/mods/overmind4/lua/AI/Overmind4/Catalog.lua').Catalog
local Policy = import('/mods/overmind4/lua/AI/Overmind4/Policy.lua').Policy
local Telemetry = import('/mods/overmind4/lua/AI/Overmind4/Telemetry.lua').Telemetry
local MarkerUtilities = import('/lua/sim/MarkerUtilities.lua')
local NavUtils = import('/lua/sim/NavUtils.lua')

local STEP_TICKS = 10
local DEFENSE_RADIUS = 65
local IMMEDIATE_DANGER_DISTANCE = 20
local LOCAL_MASS_DISTANCE = 45
local PLACEMENT_MATCH_DISTANCE = 2
local STAGING_FRACTION = 0.23
local STAGING_RADIUS = 48
local COMMANDER_STAGING_RADIUS = 12
local COMMANDER_HOME_RADIUS = 20
local COMMANDER_PUSH_HEALTH_RATIO = 0.75
local COMMANDER_PUSH_COMBAT = 24
local COMMANDER_PUSH_ARTILLERY = 4
local VERIFY_TICKS = 3
local REJECT_TICKS = 12
local OPERATION_TIMEOUT_TICKS = 900
local REORDER_COOLDOWN_TICKS = 100
local WAVE_STUCK_TICKS = 300
local SNAPSHOT_INTERVAL_TICKS = 300
local SITE_BACKOFF_TICKS = 300
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
    if not a
        or not b
        or type(a) ~= 'table'
        or type(b) ~= 'table'
        or type(a[1]) ~= 'number'
        or type(a[3]) ~= 'number'
        or type(b[1]) ~= 'number'
        or type(b[3]) ~= 'number'
    then
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

local function BlockSite(controller, siteKey, reason)
    if not siteKey then return end
    controller.blockedSites[siteKey] = CurrentTick(controller) + SITE_BACKOFF_TICKS
    Emit(controller, 'site_blocked', {
        reason = reason or 'unknown',
        site = siteKey,
    })
end

local function SiteIsBlocked(controller, siteKey)
    local blockedUntil = controller.blockedSites[siteKey]
    if not blockedUntil then return false end
    if CurrentTick(controller) >= blockedUntil then
        controller.blockedSites[siteKey] = nil
        return false
    end
    return true
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

local function PlacementKey(position)
    return 'Placement:'
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
    local candidate = candidates[1]
    if not candidate then return 'none', nil end
    return candidate.name, CopyPosition(candidate.position)
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
            placementKey = operation.placementKey,
            position = CopyPosition(operation.position),
            issuedTick = operation.issuedTick,
        })
    end
    return pending
end

local function CanUnitBuild(unit, blueprintId)
    if not unit or not blueprintId then return false end
    local ok, result = pcall(function() return unit:CanBuild(blueprintId) end)
    return ok and result ~= nil and result ~= false
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
    local assignment = controller.waveAssignments[token]
    local assigned = assignment ~= nil
    local stagingRadius = role == 'acu' and COMMANDER_STAGING_RADIUS or STAGING_RADIUS
    local nearStaging = DistanceSquared(position, controller.stagingPosition)
        <= stagingRadius * stagingRadius

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
        commanderEscort = assignment and assignment.commanderEscort == true or false,
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
            buildable = not SiteIsBlocked(controller, marker.key),
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
            if not SiteIsBlocked(controller, PlacementKey(seed))
                and SafeCall(false, controller.brain.CanBuildStructureAt, controller.brain, blueprintId, seed) == true
            then
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
        commanderPushActive = controller.commanderPushActive,
        commanderMobilizing = controller.commanderMobilizing,
        commanderRetreating = controller.commanderRetreating,
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
    if reason == 'rejected' or reason == 'timeout' or reason == 'command_error' then
        BlockSite(controller, operation.siteKey or operation.placementKey, reason)
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

local function PlacementOccupied(observation, operation)
    if not operation.placementKey or not operation.position then return false end
    local maximumDistance = PLACEMENT_MATCH_DISTANCE * PLACEMENT_MATCH_DISTANCE
    for _, unit in ipairs(observation.units or {}) do
        if unit.role == operation.buildRole
            and DistanceSquared(unit.position, operation.position) <= maximumDistance
        then
            return true
        end
    end
    return false
end

local function OperationCompleted(operation, observation, record)
    if operation.kind == 'build_structure' then
        if operation.siteKey then
            return SiteOccupied(observation, operation.siteKey)
        end
        return PlacementOccupied(observation, operation)
    end
    return operation.kind == 'factory_build'
        and operation.accepted == true
        and record.idle == true
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

local function OrderCoolingDown(controller, signature)
    local previous = controller.lastOrders[signature]
    return previous ~= nil
        and CurrentTick(controller) - previous < REORDER_COOLDOWN_TICKS
end

local function RememberOrder(controller, signature)
    controller.lastOrders[signature] = CurrentTick(controller)
end

local function UpdateSafetyEpisodes(controller, intents)
    local present = { retreat = false, defend = false }
    for _, intent in ipairs(intents or {}) do
        if intent.kind == 'retreat' then
            present.retreat = true
        elseif intent.kind == 'defend_wave' then
            present.defend = true
        end
    end
    for _, kind in ipairs({ 'retreat', 'defend' }) do
        if present[kind] then
            if controller.safetyActive[kind] ~= true then
                controller.safetyEpisodes[kind] = controller.safetyEpisodes[kind] + 1
            end
            controller.safetyActive[kind] = true
        else
            controller.safetyActive[kind] = false
        end
    end
end

local function RecordPending(controller, intent)
    local position = CopyPosition(intent.position)
    local placementKey = nil
    if not intent.siteKey and position then
        placementKey = PlacementKey(position)
    end
    local operation = {
        actorToken = intent.actorToken,
        kind = intent.kind,
        buildRole = intent.buildRole,
        siteKey = intent.siteKey,
        placementKey = placementKey,
        position = position,
        issuedTick = CurrentTick(controller),
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

local function ExecuteStructure(controller, intent, record)
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
        BlockSite(controller, intent.siteKey or PlacementKey(position), 'preflight')
        return false
    end
    local actor = controller.unitRefs[intent.actorToken]
    if not actor or not CanUnitBuild(actor, blueprintId) then return false end

    RecordPending(controller, intent)
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

local function ExecuteFactoryProduction(controller, intent, record)
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
    RecordPending(controller, intent)
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

local function HealthyCommander(record)
    local health = record and tonumber(record.healthRatio) or nil
    return record
        and record.role == 'acu'
        and record.complete == true
        and health ~= nil
        and health >= COMMANDER_PUSH_HEALTH_RATIO
end

local function GroupRecords(controller, tokens, recordByToken, usedActors)
    local selected = {}
    local sorted = {}
    local seen = {}
    for _, token in ipairs(tokens or {}) do
        if type(token) == 'string' and not seen[token] then
            seen[token] = true
            TableInsert(sorted, token)
        end
    end
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

local function CommanderCohort(controller, tokens, recordByToken, usedActors)
    local records = GroupRecords(controller, tokens, recordByToken, usedActors)
    local eligible = {}
    local actors = {}
    local artillery = 0
    for _, record in ipairs(records) do
        local actor = controller.unitRefs[record.token]
        if actor
            and record.availableForWave == true
            and record.nearStaging == true
            and record.assignedToWave ~= true
            and not controller.waveAssignments[record.token]
        then
            TableInsert(eligible, record)
            TableInsert(actors, actor)
            if record.role == 'artillery' then
                artillery = artillery + 1
            end
        end
    end
    if TableGetn(eligible) < COMMANDER_PUSH_COMBAT
        or artillery < COMMANDER_PUSH_ARTILLERY
    then
        return nil, nil
    end
    return eligible, actors
end

local function AssignCommanderCohort(controller, records, usedActors)
    local tick = CurrentTick(controller)
    for _, record in ipairs(records) do
        usedActors[record.token] = true
        controller.waveAssignments[record.token] = {
            issuedTick = tick,
            position = CopyPosition(record.position),
            commanderEscort = true,
        }
    end
end

local function OwnedCommanderCohort(controller, recordByToken, usedActors)
    local records = {}
    local actors = {}
    for _, token in ipairs(SortedKeys(controller.waveAssignments)) do
        local assignment = controller.waveAssignments[token]
        local record = recordByToken[token]
        local actor = controller.unitRefs[token]
        if assignment
            and assignment.commanderEscort == true
            and record
            and COMBAT_ROLES[record.role]
            and record.complete == true
            and actor
            and not usedActors[token]
        then
            TableInsert(records, record)
            TableInsert(actors, actor)
        end
    end
    if TableGetn(records) == 0 then return nil, nil end
    return records, actors
end

local function ExecuteCommanderMobilization(controller, intent, recordByToken, usedActors)
    if controller.initialWaveSent == true
        or controller.commanderPushActive == true
        or controller.commanderMobilizing == true
        or controller.commanderRetreating == true
        or type(intent.acuToken) ~= 'string'
        or usedActors[intent.acuToken]
        or controller.pending[intent.acuToken]
        or controller.targetPath ~= true
        or DistanceSquared(intent.position, controller.stagingPosition) > 4
    then
        return false
    end
    local acuRecord = recordByToken[intent.acuToken]
    if not HealthyCommander(acuRecord)
        or acuRecord.idle ~= true
        or acuRecord.nearStaging ~= false
    then
        return false
    end
    local acuActor = controller.unitRefs[intent.acuToken]
    local records, actors = CommanderCohort(
        controller,
        intent.actorTokens,
        recordByToken,
        usedActors
    )
    local position = TerrainPosition(controller.stagingPosition)
    if not acuActor or not records or not position then return false end

    local clearOk = pcall(function() IssueClearCommands(actors) end)
    if not clearOk then return false end
    local guardOk = pcall(function() IssueGuard(actors, acuActor) end)
    if not guardOk then return false end
    local moveOk = pcall(function() IssueMove({ acuActor }, position) end)
    if not moveOk then
        pcall(function() IssueClearCommands(actors) end)
        return false
    end

    AssignCommanderCohort(controller, records, usedActors)
    usedActors[intent.acuToken] = true
    controller.commanderMobilizing = true
    controller.commanderPushActive = false
    controller.commanderRetreating = false
    controller.commanderToken = intent.acuToken
    Emit(controller, 'milestone', {
        name = 'commander_mobilized',
        units = TableGetn(actors),
    })
    Emit(controller, 'order', {
        actor = intent.acuToken,
        command = 'mobilize_commander',
        role = 'battlegroup',
        units = TableGetn(actors),
    })
    return true
end

local function ExecuteCommanderPush(controller, intent, recordByToken, usedActors)
    local mobilized = controller.commanderMobilizing == true
    if controller.initialWaveSent == true
        or controller.commanderPushActive == true
        or controller.commanderRetreating == true
        or type(intent.acuToken) ~= 'string'
        or usedActors[intent.acuToken]
        or controller.pending[intent.acuToken]
        or controller.targetPath ~= true
        or DistanceSquared(intent.position, controller.targetPosition) > 4
        or (mobilized and controller.commanderToken ~= intent.acuToken)
    then
        return false
    end
    local acuRecord = recordByToken[intent.acuToken]
    if not HealthyCommander(acuRecord)
        or acuRecord.idle ~= true
        or acuRecord.nearStaging ~= true
    then
        return false
    end
    local acuActor = controller.unitRefs[intent.acuToken]
    local records = nil
    local actors = nil
    if mobilized then
        records, actors = OwnedCommanderCohort(controller, recordByToken, usedActors)
    else
        records, actors = CommanderCohort(
            controller,
            intent.actorTokens,
            recordByToken,
            usedActors
        )
    end
    local position = TerrainPosition(controller.targetPosition)
    if not acuActor or not records or not position then return false end

    if not mobilized then
        local clearOk = pcall(function() IssueClearCommands(actors) end)
        if not clearOk then return false end
        local guardOk = pcall(function() IssueGuard(actors, acuActor) end)
        if not guardOk then return false end
    end
    local moveOk = pcall(function() IssueAggressiveMove({ acuActor }, position) end)
    if not moveOk then
        if not mobilized then
            pcall(function() IssueClearCommands(actors) end)
        end
        return false
    end

    local tick = CurrentTick(controller)
    AssignCommanderCohort(controller, records, usedActors)
    usedActors[intent.acuToken] = true
    controller.initialWaveSent = true
    controller.commanderPushActive = true
    controller.commanderMobilizing = false
    controller.commanderRetreating = false
    controller.commanderToken = intent.acuToken
    controller.lastWaveTick = tick
    controller.lastReinforcementTick = tick
    Emit(controller, 'milestone', {
        name = 'commander_push',
        units = TableGetn(actors),
    })
    Emit(controller, 'order', {
        actor = intent.acuToken,
        command = 'commander_push',
        role = 'battlegroup',
        units = TableGetn(actors),
    })
    return true
end

local function ExecuteCommanderReinforcement(controller, intent, recordByToken, usedActors)
    if controller.initialWaveSent ~= true
        or controller.commanderPushActive ~= true
        or controller.commanderRetreating == true
        or type(intent.acuToken) ~= 'string'
        or controller.commanderToken ~= intent.acuToken
        or usedActors[intent.acuToken]
    then
        return false
    end
    local acuRecord = recordByToken[intent.acuToken]
    local acuActor = controller.unitRefs[intent.acuToken]
    if not HealthyCommander(acuRecord) or not acuActor then return false end
    local records, actors = CommanderCohort(
        controller,
        intent.actorTokens,
        recordByToken,
        usedActors
    )
    if not records then return false end
    local clearOk = pcall(function() IssueClearCommands(actors) end)
    if not clearOk then return false end
    local ok = pcall(function() IssueGuard(actors, acuActor) end)
    if not ok then return false end

    AssignCommanderCohort(controller, records, usedActors)
    usedActors[intent.acuToken] = true
    controller.lastReinforcementTick = CurrentTick(controller)
    Emit(controller, 'order', {
        actor = intent.acuToken,
        command = 'reinforce_commander',
        role = 'combat',
        units = TableGetn(actors),
    })
    return true
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
    if intent.kind == 'defend_wave' then
        signature = signature .. ':safety:' .. tostring(controller.safetyEpisodes.defend)
    end
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
    ReleaseOperation(controller, intent.actorToken, 'retreat_preempted')
    local signature = Signature(intent)
        .. ':safety:' .. tostring(controller.safetyEpisodes.retreat)
    if OrderCoolingDown(controller, signature) then return false end
    local clearKey = 'retreat:' .. tostring(controller.safetyEpisodes.retreat)
        .. ':' .. intent.actorToken
    if not controller.safetyCleared[clearKey] then
        local clearOk = pcall(function() IssueClearCommands({ actor }) end)
        if not clearOk then return false end
        controller.safetyCleared[clearKey] = true
    end
    local ok = pcall(function() IssueMove({ actor }, position) end)
    if not ok then return false end
    RememberOrder(controller, signature)
    if (controller.commanderPushActive == true
        or controller.commanderMobilizing == true)
        and controller.commanderToken == intent.actorToken
    then
        controller.commanderPushActive = false
        controller.commanderMobilizing = false
        controller.commanderRetreating = true
    end
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
    controller.occupiedSpawns = 0
    for _, marker in ipairs(controller.markers.spawn) do
        if marker.occupiedSpawn then
            controller.occupiedSpawns = controller.occupiedSpawns + 1
        end
    end
    controller.targetName, controller.targetPosition = ChooseTarget(
        controller.markers.spawn,
        controller.basePosition
    )
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
        blockedSites = {},
        rallied = {},
        waveAssignments = {},
        safetyCleared = {},
        safetyActive = { retreat = false, defend = false },
        safetyEpisodes = { retreat = 0, defend = 0 },
        lastOrders = {},
        initialWaveSent = false,
        commanderPushActive = false,
        commanderMobilizing = false,
        commanderRetreating = false,
        lastWaveTick = -10000,
        lastReinforcementTick = -10000,
        lastSnapshotTick = -SNAPSHOT_INTERVAL_TICKS,
        lastErrorTick = -REORDER_COOLDOWN_TICKS,
    }
    Controller.InitializeMap(controller)
    local base = controller.basePosition or {}
    local target = controller.targetPosition or {}
    local staging = controller.stagingPosition or {}
    Emit(controller, controller.unsupported and 'unsupported_faction' or 'created', {
        faction = brain:GetFactionIndex(),
        target_name = controller.targetName or 'none',
        base_x = tonumber(base[1]) or -1,
        base_z = tonumber(base[3]) or -1,
        target_x = tonumber(target[1]) or -1,
        target_z = tonumber(target[3]) or -1,
        staging_x = tonumber(staging[1]) or -1,
        staging_z = tonumber(staging[3]) or -1,
        occupied_spawns = tonumber(controller.occupiedSpawns) or 0,
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

local function ClearCommanderState(controller)
    controller.commanderPushActive = false
    controller.commanderMobilizing = false
    controller.commanderRetreating = false
    controller.commanderToken = nil
    for _, token in ipairs(SortedKeys(controller.waveAssignments)) do
        local assignment = controller.waveAssignments[token]
        if assignment and assignment.commanderEscort == true then
            controller.waveAssignments[token] = nil
        end
    end
end

local function HasLiveCommanderEscort(controller, records)
    for _, token in ipairs(SortedKeys(controller.waveAssignments)) do
        local assignment = controller.waveAssignments[token]
        if assignment
            and assignment.commanderEscort == true
            and records[token]
            and controller.unitRefs[token]
        then
            return true
        end
    end
    return false
end

local function CompleteCommanderRecovery(controller, records)
    local actors = {}
    local escortTokens = {}
    for _, token in ipairs(SortedKeys(controller.waveAssignments)) do
        local assignment = controller.waveAssignments[token]
        if assignment and assignment.commanderEscort == true then
            TableInsert(escortTokens, token)
            if records[token] and controller.unitRefs[token] then
                TableInsert(actors, controller.unitRefs[token])
            end
        end
    end
    if TableGetn(actors) > 0 then
        local ok = pcall(function() IssueClearCommands(actors) end)
        if not ok then return false end
    end
    for _, token in ipairs(escortTokens) do
        controller.waveAssignments[token] = nil
    end
    controller.commanderPushActive = false
    controller.commanderMobilizing = false
    controller.commanderRetreating = false
    controller.commanderToken = nil
    return true
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
        elseif OperationCompleted(operation, observation, record) then
            ReleaseOperation(controller, token, nil)
        elseif operation.kind == 'build_structure'
            and operation.accepted == true
            and record.idle == true
        then
            ReleaseOperation(controller, token, 'rejected')
        elseif elapsed >= VERIFY_TICKS then
            if record.busy then operation.accepted = true end
            if not operation.accepted and elapsed > REJECT_TICKS then
                ReleaseOperation(controller, token, 'rejected')
            elseif elapsed > OPERATION_TIMEOUT_TICKS then
                ReleaseOperation(controller, token, 'timeout')
            end
        end
    end

    if controller.commanderPushActive == true
        or controller.commanderMobilizing == true
        or controller.commanderRetreating == true
    then
        local commander = controller.commanderToken
            and records[controller.commanderToken]
            or nil
        if not commander
            or commander.role ~= 'acu'
            or commander.complete ~= true
        then
            ClearCommanderState(controller)
        elseif controller.commanderMobilizing == true
            and not HasLiveCommanderEscort(controller, records)
        then
            ClearCommanderState(controller)
        elseif controller.commanderRetreating == true
            and DistanceSquared(commander.position, controller.basePosition)
                <= COMMANDER_HOME_RADIUS * COMMANDER_HOME_RADIUS
        then
            CompleteCommanderRecovery(controller, records)
        end
    end

    for _, token in ipairs(SortedKeys(controller.waveAssignments)) do
        local assignment = controller.waveAssignments[token]
        local record = records[token]
        if not record then
            controller.waveAssignments[token] = nil
        elseif tick - assignment.issuedTick >= WAVE_STUCK_TICKS then
            assignment.issuedTick = tick
            assignment.position = CopyPosition(record.position)
        end
    end

    observation.pending = PendingArray(controller)
    observation.state = StateSnapshot(controller)
end

Controller.Execute = function(controller, intents, observation)
    local records = RecordByToken(observation.units)
    local ordered = {}
    for _, intent in ipairs(intents or {}) do TableInsert(ordered, intent) end
    UpdateSafetyEpisodes(controller, ordered)
    table.sort(ordered, function(a, b)
        local ap = tonumber(a.priority) or 1000
        local bp = tonumber(b.priority) or 1000
        if ap == bp then return Signature(a) < Signature(b) end
        return ap < bp
    end)
    local usedActors = {}

    for _, intent in ipairs(ordered) do
        if intent.kind == 'mobilize_commander' then
            ExecuteCommanderMobilization(controller, intent, records, usedActors)
            if type(intent.acuToken) == 'string' then
                usedActors[intent.acuToken] = true
            end
            for _, token in ipairs(intent.actorTokens or {}) do
                if type(token) == 'string' then usedActors[token] = true end
            end
        elseif intent.kind == 'commander_push' then
            ExecuteCommanderPush(controller, intent, records, usedActors)
            if type(intent.acuToken) == 'string' then
                usedActors[intent.acuToken] = true
            end
            for _, token in ipairs(intent.actorTokens or {}) do
                if type(token) == 'string' then usedActors[token] = true end
            end
        elseif intent.kind == 'reinforce_commander' then
            ExecuteCommanderReinforcement(controller, intent, records, usedActors)
            if type(intent.acuToken) == 'string' then
                usedActors[intent.acuToken] = true
            end
            for _, token in ipairs(intent.actorTokens or {}) do
                if type(token) == 'string' then usedActors[token] = true end
            end
        elseif intent.kind == 'attack_wave'
            or intent.kind == 'defend_wave'
            or intent.kind == 'regroup_wave'
        then
            ExecuteCombatGroup(controller, intent, records, usedActors)
            if intent.kind == 'defend_wave' then
                for _, token in ipairs(intent.actorTokens or {}) do
                    if type(token) == 'string' then usedActors[token] = true end
                end
            end
        elseif intent.actorToken and not usedActors[intent.actorToken] then
            local record = records[intent.actorToken]
            if record then
                local issued = false
                if intent.kind == 'build_structure' then
                    issued = ExecuteStructure(controller, intent, record)
                elseif intent.kind == 'factory_build' then
                    issued = ExecuteFactoryProduction(controller, intent, record)
                elseif intent.kind == 'rally' then
                    issued = ExecuteRally(controller, intent, record)
                elseif intent.kind == 'retreat' then
                    issued = ExecuteRetreat(controller, intent, record)
                end
                if issued
                    or intent.kind == 'retreat'
                then
                    usedActors[intent.actorToken] = true
                end
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
        local acu = nil
        local combatTotal = 0
        local combatAssigned = 0
        local combatAvailable = 0
        local combatNearStaging = 0
        local assignedMinTargetDistance = -1
        local assignedMaxTargetDistance = -1
        for _, unit in ipairs(observation.units) do
            if unit.role == 'acu' then
                acu = unit
            elseif COMBAT_ROLES[unit.role] and unit.complete == true then
                combatTotal = combatTotal + 1
                if unit.availableForWave == true then
                    combatAvailable = combatAvailable + 1
                end
                if unit.nearStaging == true then
                    combatNearStaging = combatNearStaging + 1
                end
                if unit.assignedToWave == true then
                    combatAssigned = combatAssigned + 1
                    if observation.targetPosition then
                        local distance = Distance(unit.position, observation.targetPosition)
                        if assignedMinTargetDistance < 0 or distance < assignedMinTargetDistance then
                            assignedMinTargetDistance = distance
                        end
                        if assignedMaxTargetDistance < 0 or distance > assignedMaxTargetDistance then
                            assignedMaxTargetDistance = distance
                        end
                    end
                end
            end
        end
        local firstIntent = intents[1] or {}
        local placements = observation.placements or {}
        local sites = observation.sites or {}
        local acuPosition = acu and acu.position or {}
        Emit(controller, 'snapshot', {
            phase = phase,
            units = TableGetn(observation.units),
            pending = CountArray(controller.pending),
            reservations = CountArray(controller.reservations),
            acu_present = acu ~= nil,
            acu_complete = acu and acu.complete == true or false,
            acu_idle = acu and acu.idle == true or false,
            acu_can_land_factory = acu
                and acu.canBuild
                and acu.canBuild.land_factory == true
                or false,
            land_factory_placements = TableGetn(placements.land_factory or {}),
            mass_markers = TableGetn(sites.mass or {}),
            target_path = observation.targetPath == true,
            policy_intents = TableGetn(intents),
            first_intent = tostring(firstIntent.kind or 'none'),
            first_build_role = tostring(firstIntent.buildRole or 'none'),
            combat_total = combatTotal,
            combat_assigned = combatAssigned,
            combat_available = combatAvailable,
            combat_near_staging = combatNearStaging,
            assigned_min_target_distance = assignedMinTargetDistance,
            assigned_max_target_distance = assignedMaxTargetDistance,
            acu_x = tonumber(acuPosition[1]) or -1,
            acu_z = tonumber(acuPosition[3]) or -1,
            acu_health_ratio = acu and tonumber(acu.healthRatio) or -1,
            enemy_contact = observation.enemyContact ~= nil,
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
