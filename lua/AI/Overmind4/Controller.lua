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
local BUILD_STALL_TICKS = 900
local BUILD_FINISH_ALLOWANCE_TICKS = 600
local DEFAULT_ENGINEER_SPEED = 1.5
local REORDER_COOLDOWN_TICKS = 100
local WAVE_STUCK_TICKS = 300
local SNAPSHOT_INTERVAL_TICKS = 300
local SITE_BACKOFF_TICKS = 300
local FRONTIER_CLUSTER_DISTANCE = 18
local FRONTIER_SCREEN_MAX = 4
local HOME_RESERVE_MIN = 4
local FIELD_CAMPAIGN_MIN_COMBAT = 24
local FIELD_CAMPAIGN_MIN_AA = 2
local FIELD_CAMPAIGN_EARLY_MAX = 4
local FIELD_CAMPAIGN_HOLD_TICKS = 150
local FIELD_CAMPAIGN_STUCK_TICKS = 300
local FIELD_CAMPAIGN_ANCHOR_RADIUS = 20
local FIELD_CAMPAIGN_RECALL_HEALTH = 0.70
local FIELD_CAMPAIGN_RESUME_HEALTH = 0.75
local FIELD_CAMPAIGN_RESUME_TICKS = 300
local MASS_SURPLUS_TICKS = 300
-- A UEF T1 land factory's most expensive normal queue member is T1 AA:
-- 55 mass / (220 build time / 20 factory build rate) / 10 ticks per second.
local NEXT_FACTORY_SAFE_DRAIN_PER_TICK = 0.5
local MASS_STORED_FLOOR = 0.15
local RECLAIM_QUERY_INTERVAL_TICKS = 300
local RECLAIM_QUERY_RADIUS = 10
local RECLAIM_CONTROL_RADIUS = 45
local MAX_RECLAIM_QUERY_ENGINEERS = 4
local MAX_ACTIVE_RECLAIM_JOBS = MAX_RECLAIM_QUERY_ENGINEERS
local MAX_RECLAIM_CANDIDATES = 64
local MIN_RECLAIM_MASS = 1
local TableGetn = table.getn
local TableInsert = table.insert
local LiveOwnedActor

local BUILD_ROLES = {
    acu = { 'air_factory', 'land_factory', 'power_generator', 'mass_extractor' },
    engineer = { 'air_factory', 'hydrocarbon', 'land_factory', 'mass_extractor', 'power_generator' },
    land_factory = {
        'anti_air', 'artillery', 'engineer', 'lab', 'land_factory_t2',
        'scout', 'tank',
    },
    air_factory = { 'interceptor' },
    land_factory_t2 = { 't2_anti_air', 't2_direct_fire' },
}

local COMBAT_ROLES = {
    anti_air = true,
    artillery = true,
    lab = true,
    tank = true,
    t2_anti_air = true,
    t2_direct_fire = true,
}

local ESCALATION = {
    MAX_PLACEMENT_PROBES = 96,
    MAX_PLACEMENT_RADIUS = 64,
    PLACEMENT_RESULTS_PER_ROLE = 13,
    AIR_ENERGY_STORED = 0.5,
    T2_STORED = 0.5,
    FULL_STORAGE = 0.95,
    CAMPAIGN_MIN_MEX = 8,
    CAMPAIGN_MIN_FACTORIES = 3,
    CAMPAIGN_MIN_LAND_FACTORIES = 2,
    CAMPAIGN_ATTRITION_TICKS = 600,
    CAMPAIGN_ATTRITION_RATIO = 0.25,
    CAMPAIGN_ROLLBACK_COOLDOWN_TICKS = 600,
    ROUTE_PROBE_MAX_ACTORS = 4,
    ROUTE_PROBE_MAX_WAYPOINTS = 32,
    ROUTE_PROBE_MAX_LENGTH = 100000,
    ROUTE_PROBE_STUCK_TICKS = 300,
    ROUTE_PROBE_RELEASE_TICKS = 600,
    ROUTE_BLOCK_TICKS = 600,
    ECONOMY_LEDGER_SAMPLES = 30,
    ECONOMY_LEDGER_INTERVAL_TICKS = 10,
    ALLOCATOR_PLANNING_TICKS = 1200,
    MIN_FACTORY_TARGET = 2,
    MASS_EXPANSION_RESERVE = 0.3,
    ENERGY_EXPANSION_RESERVE = 3,
    LAND_COMBAT_MASS_RESERVE = 0.373333,
    LAND_COMBAT_ENERGY_RESERVE = 1.773333,
    requestLanes = {
        air_factory = 'air',
        hydrocarbon = 'energy',
        interceptor = 'air',
        land_factory = 'factory',
        land_factory_t2 = 'tech',
        mass_extractor = 'expansion',
        power_generator = 'energy',
        engineer = 'engineer',
        anti_air = 'factory',
        artillery = 'factory',
        lab = 'factory',
        scout = 'factory',
        tank = 'factory',
        t2_anti_air = 'factory',
        t2_direct_fire = 'factory',
    },
    antiAirRoles = {
        anti_air = true,
        t2_anti_air = true,
    },
    placementFoundationRoles = {
        air_factory = true,
        land_factory = true,
        land_factory_t2 = true,
        power_generator = true,
    },
    placementObstacleRoles = {
        air_factory = true,
        hydrocarbon = true,
        land_factory = true,
        land_factory_t2 = true,
        mass_extractor = true,
        power_generator = true,
    },
    factoryProducts = {
        air_factory = { interceptor = true },
        land_factory = {
            anti_air = true, artillery = true, engineer = true,
            lab = true, scout = true, tank = true,
        },
        land_factory_t2 = { t2_anti_air = true, t2_direct_fire = true },
    },
}

local function SafeCall(defaultValue, fn, ...)
    local ok, value = pcall(fn, unpack(arg))
    if ok then
        return value
    end
    return defaultValue
end

local function SafeArmyStat(brain, name)
    local raw = SafeCall(nil, brain.GetArmyStat, brain, name, -1)
    if type(raw) ~= 'table' then return -1 end
    local value = tonumber(raw.Value)
    if value == nil then return -1 end
    return value
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

local function CopyArray(values)
    local copy = {}
    for _, value in ipairs(values or {}) do TableInsert(copy, value) end
    return copy
end

local function SameArray(left, right)
    if TableGetn(left or {}) ~= TableGetn(right or {}) then return false end
    for index = 1, TableGetn(left or {}) do
        if left[index] ~= right[index] then return false end
    end
    return true
end

local function ArrayIsSorted(values)
    for index = 2, TableGetn(values or {}) do
        if tostring(values[index - 1]) > tostring(values[index]) then
            return false
        end
    end
    return true
end

local function DenseTokenArray(values)
    if type(values) ~= 'table' then return false end
    local length = TableGetn(values)
    if CountArray(values) ~= length then return false end
    for index = 1, length do
        if type(values[index]) ~= 'string' then return false end
    end
    return true
end

local function BuildTokenSet(values)
    if not DenseTokenArray(values) then return nil end
    local index = {}
    for _, token in ipairs(values or {}) do
        if type(token) ~= 'string' or index[token] == true then return nil end
        index[token] = true
    end
    return index
end

local function TokenSetMatches(values, index)
    if type(index) ~= 'table'
        or CountArray(index) ~= TableGetn(values or {})
    then
        return false
    end
    for _, token in ipairs(values or {}) do
        if index[token] ~= true then return false end
    end
    return true
end

local function CampaignFieldContains(campaign, token)
    return campaign ~= nil
        and type(campaign.fieldTokenSet) == 'table'
        and campaign.fieldTokenSet[token] == true
end

local function CampaignHomeContains(campaign, token)
    return campaign ~= nil
        and type(campaign.homeTokenSet) == 'table'
        and campaign.homeTokenSet[token] == true
end

local function CohortTokenSets(field, home)
    if type(field) ~= 'table' or type(home) ~= 'table' then return nil, nil end
    local fieldSet = BuildTokenSet(field)
    local homeSet = BuildTokenSet(home)
    if not fieldSet or not homeSet then return nil, nil end
    for token, _ in pairs(fieldSet) do
        if homeSet[token] == true then return nil, nil end
    end
    return fieldSet, homeSet
end

local function CommitCampaignCohorts(campaign, field, home)
    if not campaign then return false end
    local fieldSet, homeSet = CohortTokenSets(field, home)
    if not fieldSet then return false end

    if not ArrayIsSorted(field) then table.sort(field) end
    if not ArrayIsSorted(home) then table.sort(home) end
    local fieldChanged = not DenseTokenArray(campaign.fieldTokens)
        or not SameArray(campaign.fieldTokens, field)
    local homeChanged = not DenseTokenArray(campaign.homeTokens)
        or not SameArray(campaign.homeTokens, home)
    local fieldIndexChanged = not TokenSetMatches(field, campaign.fieldTokenSet)
    local homeIndexChanged = not TokenSetMatches(home, campaign.homeTokenSet)

    local nextField = fieldChanged and field or campaign.fieldTokens
    local nextHome = homeChanged and home or campaign.homeTokens
    local nextFieldSet = fieldIndexChanged and fieldSet or campaign.fieldTokenSet
    local nextHomeSet = homeIndexChanged and homeSet or campaign.homeTokenSet
    campaign.fieldTokens = nextField
    campaign.homeTokens = nextHome
    campaign.fieldTokenSet = nextFieldSet
    campaign.homeTokenSet = nextHomeSet
    return true
end

local function IsCampaignPosition(position)
    local copy = CopyPosition(position)
    if not copy then return false end
    for _, index in ipairs({ 1, 2, 3 }) do
        local value = copy[index]
        if value ~= value or math.abs(value) > 10000000 then return false end
    end
    return true
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

local function Reachable(layer, basePosition, position)
    local ok, result = pcall(NavUtils.CanPathTo, layer, basePosition, position)
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
            marker.engineerReachable = Reachable('Amphibious', basePosition, marker.position)
            marker.landReachable = Reachable('Land', basePosition, marker.position)
            marker.reachable = marker.engineerReachable
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
        if unit.role == role and unit.complete == true then
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
            upgradeRole = operation.upgradeRole,
            siteKey = operation.siteKey,
            placementKey = operation.placementKey,
            position = CopyPosition(operation.position),
            issuedTick = operation.issuedTick,
            deadlineTick = operation.deadlineTick,
            cancelReason = operation.cancelReason,
            cancelRequestedTick = operation.cancelRequestedTick,
            lastProgressTick = operation.lastProgressTick,
            lastDistance = operation.lastDistance,
            lastFraction = operation.lastFraction,
            phase = operation.phase,
            reason = operation.reason,
            clusterKey = operation.clusterKey,
            targetToken = operation.targetToken,
            targetKey = operation.targetKey,
            targetValue = operation.targetValue,
            observerToken = operation.observerToken,
            observedTick = operation.observedTick,
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
    local buildingState = SafeCall(false, unit.IsUnitState, unit, 'Building') == true
    local movingState = SafeCall(false, unit.IsUnitState, unit, 'Moving') == true
    local busy = SafeCall(false, unit.IsIdleState, unit) ~= true
        or buildingState
        or SafeCall(false, unit.IsUnitState, unit, 'Upgrading') == true
        or SafeCall(false, unit.IsUnitState, unit, 'Enhancing') == true
        or movingState
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
    local frontierAssignment = controller.frontierAssignments[token]
    local campaign = controller.fieldCampaign
    local fieldCohort = CampaignFieldContains(campaign, token)
    local homeCohort = CampaignHomeContains(campaign, token)
    local campaignEngineer = campaign
        and (campaign.engineerToken == token
            or campaign.desiredEngineerToken == token)
        or false
    local assigned = assignment ~= nil
        or frontierAssignment ~= nil
        or fieldCohort == true
    local stagingRadius = role == 'acu' and COMMANDER_STAGING_RADIUS or STAGING_RADIUS
    local nearStaging = DistanceSquared(position, controller.stagingPosition)
        <= stagingRadius * stagingRadius
    local rallyPosition = controller.rallyPosition or controller.basePosition
    local nearRally = DistanceSquared(position, rallyPosition)
        <= STAGING_RADIUS * STAGING_RADIUS
    local nearHome = DistanceSquared(position, controller.basePosition)
        <= STAGING_RADIUS * STAGING_RADIUS
    local physics = blueprint.Physics or {}
    local economy = blueprint.Economy or {}
    local intel = blueprint.Intel or {}
    local moveSpeed = tonumber(physics.MaxSpeed) or DEFAULT_ENGINEER_SPEED
    local buildRate = tonumber(SafeCall(nil, unit.GetBuildRate, unit))
        or tonumber(economy.BuildRate)
        or 1
    local buildDistance = tonumber(economy.MaxBuildDistance) or 10
    local visionRadius = tonumber(intel.VisionRadius) or RECLAIM_QUERY_RADIUS
    local liveVisionRadius = tonumber(SafeCall(nil, unit.GetIntelRadius, unit, 'Vision'))
    if liveVisionRadius and liveVisionRadius >= 0 then visionRadius = liveVisionRadius end
    local visionEnabled = SafeCall(false, unit.IsIntelEnabled, unit, 'Vision') == true

    controller.unitRefs[token] = unit
    return {
        token = token,
        role = role,
        complete = complete,
        fractionComplete = fraction,
        idle = complete and not busy,
        busy = busy,
        building = buildingState,
        moving = movingState,
        healthRatio = healthRatio,
        position = position,
        canBuild = canBuild,
        needsRally = role == 'land_factory' and controller.rallied[token] ~= true,
        assignedToWave = assigned,
        commanderEscort = assignment and assignment.commanderEscort == true or false,
        frontierEscort = frontierAssignment ~= nil,
        airAssigned = controller.airAssignments[token] == true,
        fieldCohort = fieldCohort == true,
        homeCohort = homeCohort == true,
        campaignEngineer = campaignEngineer == true,
        nearStaging = nearStaging,
        nearRally = nearRally,
        nearHome = nearHome,
        moveSpeed = moveSpeed,
        buildRate = buildRate,
        buildDistance = buildDistance,
        visionRadius = visionRadius,
        visionEnabled = visionEnabled,
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
    local immediatePosition = nil
    local immediateDistance = 1000000000000
    for _, position in ipairs(positions) do
        local distance = DistanceSquared(position, acuPosition)
        if distance <= IMMEDIATE_DANGER_DISTANCE * IMMEDIATE_DANGER_DISTANCE
            and (distance < immediateDistance
                or (distance == immediateDistance
                    and (not immediatePosition
                        or position[1] < immediatePosition[1]
                        or (position[1] == immediatePosition[1]
                            and position[3] < immediatePosition[3]))))
        then
            immediatePosition = position
            immediateDistance = distance
        end
    end
    return {
        position = immediatePosition or positions[1],
        immediate = immediatePosition ~= nil,
    }
end

local function SiteSnapshot(controller, markers, ownRecords)
    local sites = {}
    for _, marker in ipairs(markers) do
        local occupied = false
        local complete = false
        local fractionComplete = 0
        local targetToken = nil
        local expectedRole = marker.kind == 'hydro' and 'hydrocarbon' or 'mass_extractor'
        for _, unit in ipairs(ownRecords) do
            if unit.role == expectedRole and DistanceSquared(unit.position, marker.position) <= 16 then
                occupied = true
                local fraction = tonumber(unit.fractionComplete) or 0
                if unit.complete ~= true
                    and (not targetToken or fraction > fractionComplete)
                then
                    targetToken = unit.token
                end
                if fraction > fractionComplete then
                    fractionComplete = fraction
                end
                if unit.complete == true then complete = true end
            end
        end
        TableInsert(sites, {
            key = marker.key,
            name = marker.name,
            position = CopyPosition(marker.position),
            distance = marker.distance,
            localSite = marker.localSite,
            reachable = marker.reachable,
            engineerReachable = marker.engineerReachable == true and marker.reachable == true,
            landReachable = marker.landReachable == true and marker.reachable == true,
            buildable = not SiteIsBlocked(controller, marker.key),
            occupied = occupied,
            complete = complete,
            fractionComplete = fractionComplete,
            targetToken = complete ~= true and targetToken or nil,
            reserved = controller.reservations[marker.key] ~= nil,
        })
    end
    table.sort(sites, function(a, b)
        local ad = tonumber(a.distance) or 1000000000
        local bd = tonumber(b.distance) or 1000000000
        if ad == bd then return tostring(a.key) < tostring(b.key) end
        return ad < bd
    end)
    return sites
end

local function RefreshFoundationReservations(controller, foundations)
    local reservedTargets = {}
    local reservedPlacements = {}
    for _, operation in pairs(controller.pending or {}) do
        if operation.targetToken then reservedTargets[operation.targetToken] = true end
        if operation.placementKey then reservedPlacements[operation.placementKey] = true end
    end
    for _, foundation in ipairs(foundations or {}) do
        foundation.reserved = reservedTargets[foundation.targetToken] == true
            or reservedPlacements[foundation.placementKey] == true
        if foundation.reserved ~= true then
            for _, operation in pairs(controller.pending or {}) do
                if operation.buildRole == foundation.role
                    and operation.position
                    and DistanceSquared(operation.position, foundation.position)
                        <= PLACEMENT_MATCH_DISTANCE * PLACEMENT_MATCH_DISTANCE
                then
                    foundation.reserved = true
                    break
                end
            end
        end
    end
end

local function FoundationSnapshot(controller, ownRecords)
    local foundations = {}
    for _, unit in ipairs(ownRecords or {}) do
        if ESCALATION.placementFoundationRoles[unit.role] == true
            and unit.complete ~= true
            and type(unit.token) == 'string'
            and CopyPosition(unit.position)
        then
            local placementKey = PlacementKey(unit.position)
            TableInsert(foundations, {
                key = 'Foundation:' .. unit.token,
                targetToken = unit.token,
                role = unit.role,
                position = CopyPosition(unit.position),
                placementKey = placementKey,
                fractionComplete = tonumber(unit.fractionComplete) or 0,
                reserved = false,
            })
        end
    end
    table.sort(foundations, function(a, b)
        if a.role == b.role then return a.targetToken < b.targetToken end
        return a.role < b.role
    end)
    RefreshFoundationReservations(controller, foundations)
    return foundations
end

local function UpdateMexHistory(controller, massSites)
    local owned = 0
    local lost = 0
    for _, site in ipairs(massSites or {}) do
        local history = controller.mexHistory[site.key]
        if not history then
            history = { everOwned = false, lost = false }
            controller.mexHistory[site.key] = history
        end
        if site.complete == true then
            owned = owned + 1
            if history.everOwned == true and history.lost == true then
                history.lost = false
                controller.rebuiltMexCount = controller.rebuiltMexCount + 1
                Emit(controller, 'mex_rebuilt', { site = site.key })
            end
            history.everOwned = true
        elseif history.everOwned == true and site.occupied ~= true then
            if history.lost ~= true then
                history.lost = true
                Emit(controller, 'mex_lost', { site = site.key })
            end
        end
        if history.lost == true then lost = lost + 1 end
        site.everOwned = history.everOwned == true
        site.lost = history.lost == true
    end
    controller.ownedMexCount = owned
    controller.lostMexCount = lost
end

local function SiteValidForFrontier(site)
    return type(site) == 'table'
        and type(site.key) == 'string'
        and CopyPosition(site.position) ~= nil
        and site.engineerReachable == true
        and site.landReachable == true
        and site.lost ~= true
end

local function SiteDistanceToAnchors(site, anchors)
    local best = 1000000000000
    for _, anchor in ipairs(anchors or {}) do
        local distance = Distance(site.position, anchor)
        if distance < best then best = distance end
    end
    return best
end

local function FrontierClusters(controller, massSites)
    local eligible = {}
    local anchors = { CopyPosition(controller.basePosition) }
    for _, site in ipairs(massSites or {}) do
        site.frontierSelected = false
        site.clusterKey = 'none'
        if site.complete == true and CopyPosition(site.position) then
            TableInsert(anchors, CopyPosition(site.position))
        end
        if SiteValidForFrontier(site) then
            TableInsert(eligible, site)
        end
    end
    table.sort(eligible, function(a, b) return a.key < b.key end)

    local assigned = {}
    local clusters = {}
    for _, seed in ipairs(eligible) do
        if not assigned[seed.key] then
            local members = { seed }
            assigned[seed.key] = true
            local cursor = 1
            while cursor <= TableGetn(members) do
                local member = members[cursor]
                for _, candidate in ipairs(eligible) do
                    if not assigned[candidate.key]
                        and Distance(member.position, candidate.position) <= FRONTIER_CLUSTER_DISTANCE
                    then
                        assigned[candidate.key] = true
                        TableInsert(members, candidate)
                    end
                end
                cursor = cursor + 1
            end
            table.sort(members, function(a, b) return a.key < b.key end)
            local unfinished = {}
            local completed = 0
            local adjacentDistance = 1000000000000
            for _, member in ipairs(members) do
                if member.complete == true then
                    completed = completed + 1
                elseif member.buildable == true or member.reserved == true or member.occupied == true then
                    TableInsert(unfinished, member)
                end
                local distance = SiteDistanceToAnchors(member, anchors)
                if distance < adjacentDistance then adjacentDistance = distance end
            end
            -- CanPathTo on both the engineer and land-screen layers is the
            -- connectivity contract.  A Euclidean cutoff deadlocks sparse
            -- maps such as SCMP_006 even though the next cluster is pathable.
            if TableGetn(unfinished) > 0 then
                table.sort(unfinished, function(a, b)
                    local ad = SiteDistanceToAnchors(a, anchors)
                    local bd = SiteDistanceToAnchors(b, anchors)
                    if ad == bd then return a.key < b.key end
                    return ad < bd
                end)
                TableInsert(clusters, {
                    key = members[1].key,
                    members = members,
                    unfinished = unfinished,
                    completed = completed,
                    distance = adjacentDistance,
                })
            end
        end
    end
    table.sort(clusters, function(a, b)
        if a.distance == b.distance then return a.key < b.key end
        return a.distance < b.distance
    end)
    return clusters, anchors
end

local function ClusterContainsRememberedSite(cluster, remembered)
    for _, member in ipairs(cluster.members or {}) do
        if remembered[member.key] then return true end
    end
    return false
end

local function UpdateFrontier(controller, massSites)
    local previousRallyPosition = CopyPosition(controller.rallyPosition)
    local previousSite = controller.selectedFrontierSite
    local clusters, anchors = FrontierClusters(controller, massSites)
    local selected = nil
    if controller.selectedFrontierSites then
        for _, cluster in ipairs(clusters) do
            if ClusterContainsRememberedSite(cluster, controller.selectedFrontierSites) then
                selected = cluster
                break
            end
        end
    end
    if not selected then selected = clusters[1] end

    local previous = controller.selectedFrontierCluster
    controller.selectedFrontierCluster = selected and selected.key or nil
    controller.selectedFrontierSites = nil
    controller.selectedFrontierSite = nil
    controller.frontierOwned = 0
    controller.frontierTotal = 0
    controller.rallyPosition = CopyPosition(controller.basePosition)
    if selected then
        controller.selectedFrontierSites = {}
        controller.frontierOwned = selected.completed
        controller.frontierTotal = TableGetn(selected.members)
        for _, member in ipairs(selected.members) do
            controller.selectedFrontierSites[member.key] = true
            member.frontierSelected = true
            member.clusterKey = selected.key
        end
        for _, member in ipairs(selected.unfinished) do
            if not controller.selectedFrontierSite
                and member.reserved ~= true
                and member.buildable == true
                and member.occupied ~= true
            then
                controller.selectedFrontierSite = member.key
            end
        end
        if not controller.selectedFrontierSite then
            controller.selectedFrontierSite = selected.unfinished[1].key
        end
        local frontierPosition = selected.unfinished[1].position
        local bestAnchor = controller.basePosition
        local bestDistance = Distance(frontierPosition, bestAnchor)
        for _, anchor in ipairs(anchors) do
            local distance = Distance(frontierPosition, anchor)
            if distance < bestDistance then
                bestDistance = distance
                bestAnchor = anchor
            end
        end
        controller.rallyPosition = CopyPosition(bestAnchor)
    end
    if previousRallyPosition
        and DistanceSquared(previousRallyPosition, controller.rallyPosition) > 4
        and not (controller.fieldCampaignEnabled == true
            and controller.fieldCampaign ~= nil)
    then
        controller.rallied = {}
    end
    if previous ~= controller.selectedFrontierCluster
        or previousSite ~= controller.selectedFrontierSite
    then
        Emit(controller, 'frontier_selected', {
            cluster = controller.selectedFrontierCluster or 'none',
            site = controller.selectedFrontierSite or 'none',
        })
    end
end

local function PositionControlled(controller, position, massSites)
    if Distance(position, controller.basePosition) <= RECLAIM_CONTROL_RADIUS then return true end
    for _, site in ipairs(massSites or {}) do
        if site.complete == true
            and Distance(position, site.position) <= RECLAIM_CONTROL_RADIUS
        then
            return true
        end
    end
    return false
end

local function PropAlive(prop)
    return prop
        and prop.Dead ~= true
        and SafeCall(true, prop.BeenDestroyed, prop) ~= true
end

local function ReclaimPropLiveness(prop)
    if not prop or prop.Dead == true then return 'dead' end
    if type(prop.BeenDestroyed) ~= 'function' then return 'unknown' end
    local ok, destroyed = pcall(prop.BeenDestroyed, prop)
    if not ok or type(destroyed) ~= 'boolean' then return 'unknown' end
    if destroyed == true then return 'dead' end
    return 'alive'
end

local function ReclaimPropKey(prop)
    if SafeCall(false, IsProp, prop) ~= true then return nil end
    local entityId = SafeCall(nil, prop.GetEntityId, prop) or prop.EntityId
    if entityId == nil then return nil end
    return 'prop:' .. tostring(entityId)
end

local function ReclaimQueryRadiusForRecord(record)
    if not record
        or record.role ~= 'engineer'
        or record.complete ~= true
        or record.visionEnabled == false
        or not CopyPosition(record.position)
    then
        return nil
    end
    local radius = math.min(
        RECLAIM_QUERY_RADIUS,
        tonumber(record.visionRadius) or RECLAIM_QUERY_RADIUS
    )
    if radius <= 0 then return nil end
    return radius
end

local function NormalizeReclaimProp(prop, center, radius, observerToken, observedTick)
    local key = ReclaimPropKey(prop)
    if not key or not PropAlive(prop) then return nil end
    local position = CopyPosition(prop.CachePosition or SafeCall(nil, prop.GetPosition, prop))
    if not position or Distance(position, center) > radius then return nil end
    local maximumMass = tonumber(prop.MaxMassReclaim)
    local left = tonumber(prop.ReclaimLeft)
    if prop.ReclaimLeft == nil then left = 1 end
    if not maximumMass or maximumMass < 0 or not left or left < 0 then return nil end
    local mass = maximumMass * left
    if mass < MIN_RECLAIM_MASS then return nil end
    return {
        key = key,
        position = position,
        mass = mass,
        reference = prop,
        observerToken = observerToken,
        observedTick = observedTick,
        visionRadius = radius,
    }
end

local function ReclaimSnapshot(controller)
    local candidates = {}
    for _, candidate in ipairs(controller.reclaimCandidates or {}) do
        local reference = controller.reclaimRefs[candidate.key]
        if PropAlive(reference) then
            TableInsert(candidates, {
                key = candidate.key,
                position = CopyPosition(candidate.position),
                mass = candidate.mass,
                reserved = controller.reclaimReservations[candidate.key] ~= nil,
                observerToken = candidate.observerToken,
                observedTick = candidate.observedTick,
                visionRadius = candidate.visionRadius,
            })
        end
    end
    return candidates
end

local function RefreshReclaim(controller, ownRecords, massSites)
    local tick = CurrentTick(controller)
    if tick - controller.lastReclaimQueryTick < RECLAIM_QUERY_INTERVAL_TICKS then
        return ReclaimSnapshot(controller)
    end
    controller.lastReclaimQueryTick = tick
    local byKey = {}
    local refs = {}
    local recordsByToken = {}
    local sortedRecords = {}
    for _, record in ipairs(ownRecords or {}) do
        recordsByToken[record.token] = record
        TableInsert(sortedRecords, record)
    end
    table.sort(sortedRecords, function(a, b)
        return tostring(a.token or '') < tostring(b.token or '')
    end)

    local activeByActor = {}
    local freshness = {}
    for _, actorToken in ipairs(SortedKeys(controller.pending)) do
        local operation = controller.pending[actorToken]
        if operation.kind == 'reclaim' and type(operation.targetKey) == 'string' then
            activeByActor[actorToken] = operation
            freshness[actorToken] = {
                actorToken = actorToken,
                targetKey = operation.targetKey,
                observedTick = tick,
                queried = false,
                covered = false,
                state = 'unknown',
            }
        end
    end

    local queryRecords = {}
    local selectedActors = {}
    local function AddQueryRecord(record)
        if TableGetn(queryRecords) >= MAX_RECLAIM_QUERY_ENGINEERS then return end
        local radius = ReclaimQueryRadiusForRecord(record)
        if not radius
            or selectedActors[record.token]
            or not PositionControlled(controller, record.position, massSites)
        then
            return
        end
        selectedActors[record.token] = true
        TableInsert(queryRecords, { record = record, radius = radius })
    end
    for _, actorToken in ipairs(SortedKeys(activeByActor)) do
        AddQueryRecord(recordsByToken[actorToken])
    end
    for _, record in ipairs(sortedRecords) do
        AddQueryRecord(record)
    end

    local activeRefs = {}
    for _, query in ipairs(queryRecords) do
        local record = query.record
        local radius = query.radius
        local rectangle = nil
        if Rect then
            rectangle = SafeCall(nil, Rect,
                record.position[1] - radius,
                record.position[3] - radius,
                record.position[1] + radius,
                record.position[3] + radius
            )
        end
        if not rectangle then
            rectangle = {
                record.position[1] - radius,
                record.position[3] - radius,
                record.position[1] + radius,
                record.position[3] + radius,
            }
        end
        local queryOk, raw = pcall(function()
            return GetReclaimablesInRect(rectangle)
        end)
        local validResult = queryOk and type(raw) == 'table'
        if not validResult then raw = {} end

        local operation = activeByActor[record.token]
        local activeState = freshness[record.token]
        if activeState and operation then
            local targetPosition = CopyPosition(operation.position)
            if validResult
                and targetPosition
                and Distance(record.position, targetPosition) <= radius
                and PositionControlled(controller, targetPosition, massSites)
            then
                activeState.queried = true
                activeState.covered = true
                activeState.state = 'absent'
            end
        end

        for _, prop in pairs(raw or {}) do
            local propKey = ReclaimPropKey(prop)
            local exactReference = operation
                and operation.targetReference
                and operation.targetReference == prop
            local validIdentity = activeState
                and operation
                and propKey == activeState.targetKey
                and (not operation.targetReference or exactReference)
                or false
            if activeState
                and activeState.covered == true
                and (exactReference or validIdentity)
            then
                activeState.state = 'unknown'
                activeState.value = nil
                if validIdentity then
                    local maximumMass = tonumber(prop.MaxMassReclaim)
                    local reclaimLeft = tonumber(prop.ReclaimLeft)
                    local liveness = ReclaimPropLiveness(prop)
                    if prop.ReclaimLeft == nil then reclaimLeft = 1 end
                    if liveness == 'unknown'
                        or not maximumMass
                        or maximumMass < 0
                        or not reclaimLeft
                        or reclaimLeft < 0
                    then
                        activeState.state = 'unknown'
                        activeState.value = nil
                    else
                        local remaining = liveness == 'alive'
                            and maximumMass * reclaimLeft
                            or 0
                        if remaining >= MIN_RECLAIM_MASS then
                            activeState.state = 'present'
                            activeState.value = remaining
                            activeRefs[activeState.targetKey] = prop
                        else
                            activeState.state = 'depleted'
                            activeState.value = 0
                        end
                    end
                end
            end

            local candidate = NormalizeReclaimProp(
                prop,
                record.position,
                radius,
                record.token,
                tick
            )
            if candidate
                and PositionControlled(controller, candidate.position, massSites)
            then
                local previous = byKey[candidate.key]
                if not previous
                    or candidate.mass > previous.mass
                    or (candidate.mass == previous.mass
                        and candidate.observerToken < previous.observerToken)
                then
                    byKey[candidate.key] = candidate
                    refs[candidate.key] = candidate.reference
                end
            end
        end
    end
    local candidates = {}
    for _, key in ipairs(SortedKeys(byKey)) do
        local candidate = byKey[key]
        candidate.reference = nil
        TableInsert(candidates, candidate)
    end
    table.sort(candidates, function(a, b)
        if a.mass == b.mass then return a.key < b.key end
        return a.mass > b.mass
    end)
    local selected = {}
    local selectedRefs = {}
    for index = 1, math.min(TableGetn(candidates), MAX_RECLAIM_CANDIDATES) do
        local candidate = candidates[index]
        TableInsert(selected, candidate)
        selectedRefs[candidate.key] = refs[candidate.key]
    end
    for targetKey, reference in pairs(activeRefs) do
        selectedRefs[targetKey] = reference
    end
    controller.reclaimCandidates = selected
    controller.reclaimRefs = selectedRefs
    controller.reclaimFreshness = freshness
    return ReclaimSnapshot(controller)
end

ESCALATION.FiniteEconomyNumber = function(value, allowNegative)
    return type(value) == 'number'
        and value == value
        and math.abs(value) <= 1000000000
        and (allowNegative == true or value >= 0)
end

ESCALATION.Median = function(values)
    if type(values) ~= 'table' or TableGetn(values) == 0 then return nil end
    local ordered = CopyArray(values)
    table.sort(ordered)
    local length = TableGetn(ordered)
    local middle = math.floor((length + 1) / 2)
    if length - math.floor(length / 2) == math.floor(length / 2) then
        return (ordered[middle] + ordered[middle + 1]) * 0.5
    end
    return ordered[middle]
end

ESCALATION.UpdateEconomyLedger = function(controller, economy)
    local tick = CurrentTick(controller)
    local valid = ESCALATION.FiniteEconomyNumber(economy.massIncome)
        and ESCALATION.FiniteEconomyNumber(economy.massRequested)
        and ESCALATION.FiniteEconomyNumber(economy.massUsage)
        and ESCALATION.FiniteEconomyNumber(economy.massStoredRatio)
        and ESCALATION.FiniteEconomyNumber(economy.massTrend, true)
        and ESCALATION.FiniteEconomyNumber(economy.energyIncome)
        and ESCALATION.FiniteEconomyNumber(economy.energyRequested)
        and ESCALATION.FiniteEconomyNumber(economy.energyUsage)
        and ESCALATION.FiniteEconomyNumber(economy.energyStoredRatio)
        and ESCALATION.FiniteEconomyNumber(economy.energyTrend, true)
        and economy.massStoredRatio <= 1
        and economy.energyStoredRatio <= 1
    local ledger = controller.economyLedger
    if type(ledger) ~= 'table' then
        ledger = { samples = {}, lastTick = nil, lastStats = nil }
        controller.economyLedger = ledger
    end
    if ledger.lastTick ~= nil and ledger.lastTick == tick then
        economy.ledgerValid = ledger.valid == true
        economy.recurringMassIncome = tonumber(
            ledger.recurringMassIncome) or 0
        economy.recurringEnergyIncome = tonumber(
            ledger.recurringEnergyIncome) or 0
        economy.rollingMassRequested = tonumber(ledger.massRequested) or 0
        economy.rollingEnergyRequested = tonumber(ledger.energyRequested) or 0
        economy.massDemandSatisfaction = tonumber(
            ledger.massDemandSatisfaction) or 0
        economy.energyDemandSatisfaction = tonumber(
            ledger.energyDemandSatisfaction) or 0
        economy.oneTimeMassReserve = tonumber(
            ledger.oneTimeMassReserve) or 0
        economy.oneTimeEnergyReserve = tonumber(
            ledger.oneTimeEnergyReserve) or 0
        return
    end
    local stats = {
        producedMass = SafeArmyStat(controller.brain, 'Economy_TotalProduced_Mass'),
        reclaimedMass = SafeArmyStat(controller.brain, 'Economy_Reclaimed_Mass'),
        excessMass = SafeArmyStat(controller.brain, 'Economy_AccumExcess_Mass'),
        producedEnergy = SafeArmyStat(controller.brain, 'Economy_TotalProduced_Energy'),
        reclaimedEnergy = SafeArmyStat(controller.brain, 'Economy_Reclaimed_Energy'),
        excessEnergy = SafeArmyStat(controller.brain, 'Economy_AccumExcess_Energy'),
    }
    for _, value in pairs(stats) do
        if not ESCALATION.FiniteEconomyNumber(value) then valid = false end
    end
    local recurringMass = valid and economy.massIncome or 0
    local recurringEnergy = valid and economy.energyIncome or 0
    local reclaimedDeltaMass = 0
    local reclaimedDeltaEnergy = 0
    local dt = ledger.lastTick and tick - ledger.lastTick or 0
    if valid and ledger.lastStats and dt > 0 then
        local producedMass = stats.producedMass - ledger.lastStats.producedMass
        local reclaimedMass = stats.reclaimedMass - ledger.lastStats.reclaimedMass
        local producedEnergy = stats.producedEnergy - ledger.lastStats.producedEnergy
        local reclaimedEnergy = stats.reclaimedEnergy - ledger.lastStats.reclaimedEnergy
        local excessMass = stats.excessMass - ledger.lastStats.excessMass
        local excessEnergy = stats.excessEnergy - ledger.lastStats.excessEnergy
        if producedMass < 0 or reclaimedMass < 0 or excessMass < 0
            or producedEnergy < 0 or reclaimedEnergy < 0 or excessEnergy < 0
        then
            valid = false
            ledger.samples = {}
            ledger.lastTick = tick
            ledger.lastStats = stats
        else
            reclaimedDeltaMass = reclaimedMass
            reclaimedDeltaEnergy = reclaimedEnergy
            -- FAF's own score path defines generated recurring production as
            -- TotalProduced minus Reclaimed. Excess is overflow diagnostic;
            -- it is neither recurring demand nor stored reserve.
            recurringMass = math.max(0,
                (producedMass - reclaimedMass) / dt)
            recurringEnergy = math.max(0,
                (producedEnergy - reclaimedEnergy) / dt)
        end
    elseif ledger.lastTick and dt <= 0 and tick ~= ledger.lastTick then
        valid = false
    end

    if valid and ledger.lastTick ~= nil
        and tick - ledger.lastTick >= ESCALATION.ECONOMY_LEDGER_INTERVAL_TICKS
    then
        TableInsert(ledger.samples, {
            tick = tick,
            recurringMass = recurringMass,
            recurringEnergy = recurringEnergy,
            massRequested = economy.massRequested,
            energyRequested = economy.energyRequested,
            massUsage = economy.massUsage,
            energyUsage = economy.energyUsage,
            massStoredRatio = economy.massStoredRatio,
            energyStoredRatio = economy.energyStoredRatio,
            massTrend = economy.massTrend,
            energyTrend = economy.energyTrend,
        })
        while TableGetn(ledger.samples) > ESCALATION.ECONOMY_LEDGER_SAMPLES do
            table.remove(ledger.samples, 1)
        end
        ledger.lastTick = tick
        ledger.lastStats = stats
    elseif valid and ledger.lastTick == nil then
        -- A first GetEconomyIncome sample may be reclaim-contaminated.  It is
        -- baseline evidence only; capacity opens after a positive-dt
        -- TotalProduced-minus-Reclaimed sample.
        ledger.lastTick = tick
        ledger.lastStats = stats
    end

    local massIncome = {}
    local energyIncome = {}
    local massRequested = {}
    local energyRequested = {}
    local massUsage = {}
    local energyUsage = {}
    local massStoredRatio = {}
    local energyStoredRatio = {}
    local massTrend = {}
    local energyTrend = {}
    for _, sample in ipairs(ledger.samples or {}) do
        TableInsert(massIncome, sample.recurringMass)
        TableInsert(energyIncome, sample.recurringEnergy)
        TableInsert(massRequested, sample.massRequested)
        TableInsert(energyRequested, sample.energyRequested)
        TableInsert(massUsage, sample.massUsage)
        TableInsert(energyUsage, sample.energyUsage)
        TableInsert(massStoredRatio, sample.massStoredRatio)
        TableInsert(energyStoredRatio, sample.energyStoredRatio)
        TableInsert(massTrend, sample.massTrend)
        TableInsert(energyTrend, sample.energyTrend)
    end
    local storedMass = SafeCall(-1,
        controller.brain.GetEconomyStored, controller.brain, 'MASS')
    local storedEnergy = SafeCall(-1,
        controller.brain.GetEconomyStored, controller.brain, 'ENERGY')
    ledger.valid = valid and TableGetn(ledger.samples) > 0
    ledger.inputValid = valid
    ledger.recurringMassIncome = ESCALATION.Median(massIncome) or 0
    ledger.recurringEnergyIncome = ESCALATION.Median(energyIncome) or 0
    ledger.massRequested = ESCALATION.Median(massRequested) or 0
    ledger.energyRequested = ESCALATION.Median(energyRequested) or 0
    ledger.massUsage = ESCALATION.Median(massUsage) or 0
    ledger.energyUsage = ESCALATION.Median(energyUsage) or 0
    ledger.massDemandSatisfaction = ledger.massRequested > 0
        and math.min(1, ledger.massUsage / ledger.massRequested) or 1
    ledger.energyDemandSatisfaction = ledger.energyRequested > 0
        and math.min(1, ledger.energyUsage / ledger.energyRequested) or 1
    ledger.massStoredRatio = ESCALATION.Median(massStoredRatio) or 0
    ledger.energyStoredRatio = ESCALATION.Median(energyStoredRatio) or 0
    ledger.massTrend = ESCALATION.Median(massTrend) or 0
    ledger.energyTrend = ESCALATION.Median(energyTrend) or 0
    -- Realized reclaim is already reflected in current storage or consumption.
    -- Keep it as one-time flow telemetry, never add it to the spendable bank.
    ledger.oneTimeMassReserve = ESCALATION.FiniteEconomyNumber(storedMass)
        and storedMass or 0
    ledger.oneTimeEnergyReserve = ESCALATION.FiniteEconomyNumber(storedEnergy)
        and storedEnergy or 0
    ledger.reclaimedMassDelta = reclaimedDeltaMass
    ledger.reclaimedEnergyDelta = reclaimedDeltaEnergy
    ledger.sampleCount = TableGetn(ledger.samples)
    economy.ledgerValid = ledger.valid
    economy.recurringMassIncome = ledger.recurringMassIncome
    economy.recurringEnergyIncome = ledger.recurringEnergyIncome
    economy.rollingMassRequested = ledger.massRequested
    economy.rollingEnergyRequested = ledger.energyRequested
    economy.massDemandSatisfaction = ledger.massDemandSatisfaction
    economy.energyDemandSatisfaction = ledger.energyDemandSatisfaction
    economy.oneTimeMassReserve = ledger.oneTimeMassReserve
    economy.oneTimeEnergyReserve = ledger.oneTimeEnergyReserve
end

ESCALATION.OperationBudget = function(controller, operation, records)
    if type(operation) ~= 'table' then return nil end
    local role = operation.upgradeRole or operation.buildRole
    local blueprintId = role and Catalog.IdFor(role) or nil
    local target = blueprintId
        and SafeCall(nil, controller.brain.GetUnitBlueprint,
            controller.brain, blueprintId)
        or nil
    local economy = type(target) == 'table' and target.Economy or nil
    local actor = records[operation.actorToken]
    local buildRate = actor and tonumber(actor.buildRate) or nil
    local buildTime = economy and tonumber(economy.BuildTime) or nil
    local massCost = economy and tonumber(economy.BuildCostMass) or nil
    local energyCost = economy and tonumber(economy.BuildCostEnergy) or nil
    if not buildRate or buildRate <= 0 or not buildTime or buildTime <= 0
        or not massCost or massCost < 0 or not energyCost or energyCost < 0
    then
        return nil
    end
    if operation.kind == 'factory_upgrade'
        and economy.DifferentialUpgradeCostCalculation == true
        and actor
    then
        local sourceId = Catalog.IdFor(actor.role)
        local source = sourceId and SafeCall(nil,
            controller.brain.GetUnitBlueprint, controller.brain, sourceId) or nil
        local sourceEconomy = type(source) == 'table' and source.Economy or nil
        massCost = math.max(0,
            massCost - (sourceEconomy and tonumber(sourceEconomy.BuildCostMass) or 0))
        energyCost = math.max(0,
            energyCost - (sourceEconomy and tonumber(sourceEconomy.BuildCostEnergy) or 0))
    end
    local durationTicks = buildTime / buildRate * 10
    if durationTicks <= 0 then return nil end
    local lane = ESCALATION.requestLanes[role] or 'construction'
    return {
        lane = lane,
        massDrain = massCost / durationTicks,
        energyDrain = energyCost / durationTicks,
        massCost = massCost,
        energyCost = energyCost,
        durationTicks = durationTicks,
    }
end

local function UpdateMassSurplus(controller, economy)
    local valid = type(economy.massIncome) == 'number'
        and type(economy.massRequested) == 'number'
        and type(economy.massTrend) == 'number'
        and type(economy.massStoredRatio) == 'number'
        and economy.massIncome == economy.massIncome
        and economy.massRequested == economy.massRequested
        and economy.massTrend == economy.massTrend
        and economy.massStoredRatio == economy.massStoredRatio
        and math.abs(economy.massIncome) <= 1000000000
        and math.abs(economy.massRequested) <= 1000000000
        and math.abs(economy.massTrend) <= 1000000000
        and math.abs(economy.massStoredRatio) <= 1000000000
        and economy.massIncome >= 0
        and economy.massRequested >= 0
    local income = valid and economy.massIncome or 0
    local requested = valid and economy.massRequested or 0
    local trend = valid and economy.massTrend or 0
    local stored = valid and economy.massStoredRatio or 0
    local unused = math.max(0, income - requested)
    economy.unusedMass = unused
    local healthy = valid
        and requested <= income
        and unused >= NEXT_FACTORY_SAFE_DRAIN_PER_TICK
        and stored >= MASS_STORED_FLOOR
        and (trend > 0 or stored >= 0.8)
    local tick = CurrentTick(controller)
    if healthy then
        if controller.massSurplusSinceTick == nil then
            controller.massSurplusSinceTick = tick
        end
        controller.massSurplusTicks = tick - controller.massSurplusSinceTick
    else
        controller.massSurplusSinceTick = nil
        controller.massSurplusTicks = 0
    end
end

local function StructureOperation(operation)
    return operation
        and (operation.kind == 'build_structure' or operation.kind == 'assist_structure')
end

local function StructureWorkKey(controller, operation)
    if operation.siteKey then return 'Site:' .. tostring(operation.siteKey) end
    local currentSites = controller.currentSites or {}
    local siteGroups = {
        { role = 'mass_extractor', sites = currentSites.mass or {} },
        { role = 'hydrocarbon', sites = currentSites.hydro or {} },
    }
    for _, group in ipairs(siteGroups) do
        if operation.buildRole == group.role then
            for _, site in ipairs(group.sites) do
                local exactTarget = type(operation.targetToken) == 'string'
                    and operation.targetToken == site.targetToken
                local positionMatch = operation.targetToken == nil
                    and operation.position
                    and DistanceSquared(operation.position, site.position)
                        <= PLACEMENT_MATCH_DISTANCE * PLACEMENT_MATCH_DISTANCE
                if exactTarget or positionMatch then
                    return 'Site:' .. tostring(site.key)
                end
            end
        end
    end
    for _, foundation in ipairs(controller.currentFoundations or {}) do
        if operation.buildRole == foundation.role
            and ((operation.targetToken
                    and operation.targetToken == foundation.targetToken)
                or (operation.placementKey
                    and operation.placementKey == foundation.placementKey)
                or (operation.position
                    and DistanceSquared(operation.position, foundation.position)
                        <= PLACEMENT_MATCH_DISTANCE * PLACEMENT_MATCH_DISTANCE))
        then
            return foundation.placementKey
                or ('Foundation:' .. tostring(foundation.targetToken))
        end
    end
    return operation.placementKey
        or (operation.targetToken and ('Foundation:' .. operation.targetToken))
        or ('Actor:' .. tostring(operation.actorToken))
end

ESCALATION.CommitmentKey = function(controller, operation)
    if type(operation) ~= 'table' then return nil end
    local role = operation.upgradeRole or operation.buildRole
    if type(role) ~= 'string' then return nil end
    if StructureOperation(operation) then
        return role .. ':' .. tostring(StructureWorkKey(controller, operation))
    end
    if operation.kind == 'factory_build'
        or operation.kind == 'factory_upgrade'
    then
        return role .. ':Actor:' .. tostring(operation.actorToken)
    end
    return nil
end

local function MacroSnapshot(controller, units, economy)
    local rebuildJobs = 0
    local frontierJobs = 0
    local reclaimJobs = 0
    local structureJobs = 0
    local constructionWork = {}
    local factoryWork = {}
    local factoryWorkByRole = {
        air_factory = {},
        land_factory = {},
        land_factory_t2 = {},
    }
    for _, site in ipairs((controller.currentSites and controller.currentSites.mass) or {}) do
        if site.complete ~= true
            and (site.lost == true or site.frontierSelected == true)
        then
            constructionWork['Site:' .. tostring(site.key)] = true
        end
    end
    for _, foundation in ipairs(controller.currentFoundations or {}) do
        local key = foundation.placementKey or ('Foundation:' .. tostring(foundation.targetToken))
        constructionWork[key] = true
        if factoryWorkByRole[foundation.role] then
            factoryWork[key] = true
            factoryWorkByRole[foundation.role][key] = true
        end
    end
    for _, operation in pairs(controller.pending or {}) do
        if StructureOperation(operation) then
            structureJobs = structureJobs + 1
            if operation.reason == 'rebuild_mex' then rebuildJobs = rebuildJobs + 1 end
            if operation.reason == 'frontier_expansion' then frontierJobs = frontierJobs + 1 end
            local key = StructureWorkKey(controller, operation)
            constructionWork[key] = true
            if factoryWorkByRole[operation.buildRole] then
                factoryWork[key] = true
                factoryWorkByRole[operation.buildRole][key] = true
            end
        elseif operation.kind == 'factory_upgrade' then
            local key = 'Upgrade:' .. tostring(operation.actorToken)
            for _, foundation in ipairs(controller.currentFoundations or {}) do
                if foundation.role == operation.upgradeRole
                    and operation.position
                    and DistanceSquared(foundation.position, operation.position)
                        <= PLACEMENT_MATCH_DISTANCE * PLACEMENT_MATCH_DISTANCE
                then
                    key = foundation.placementKey
                        or ('Foundation:' .. tostring(foundation.targetToken))
                    break
                end
            end
            factoryWork[key] = true
            if factoryWorkByRole[operation.upgradeRole] then
                factoryWorkByRole[operation.upgradeRole][key] = true
            end
        elseif operation.kind == 'reclaim' then
            reclaimJobs = reclaimJobs + 1
        end
    end
    local frontierWork = 0
    for _, site in ipairs((controller.currentSites and controller.currentSites.mass) or {}) do
        if site.frontierSelected == true and site.complete ~= true then
            frontierWork = frontierWork + 1
        end
    end
    local constructionBacklog = CountArray(constructionWork)
    economy = type(economy) == 'table' and economy or {}
    local completedMex = CountRole(units, 'mass_extractor')
    local completedLandT1 = CountRole(units, 'land_factory')
    local completedLandT2 = CountRole(units, 'land_factory_t2')
    local completedAirT1 = CountRole(units, 'air_factory')
    local completedFactories = completedLandT1 + completedLandT2 + completedAirT1
    local upgradeSourcesCompleted = 0
    for token, operation in pairs(controller.pending or {}) do
        if operation.kind == 'factory_upgrade' then
            for _, unit in ipairs(units or {}) do
                if unit.token == token
                    and unit.role == 'land_factory'
                    and unit.complete == true
                then
                    upgradeSourcesCompleted = upgradeSourcesCompleted + 1
                    break
                end
            end
        end
    end
    local factories = math.max(
        completedFactories,
        completedFactories + CountArray(factoryWork) - upgradeSourcesCompleted
    )
    local expansionOpportunities = 0
    for _, site in ipairs((controller.currentSites and controller.currentSites.mass) or {}) do
        if site.complete ~= true
            and site.occupied ~= true
            and site.reserved ~= true
            and site.buildable == true
            and (site.engineerReachable == true or site.reachable == true)
            and CopyPosition(site.position)
        then
            expansionOpportunities = expansionOpportunities + 1
        end
    end
    local engineerTarget = 2
    local unlockingEngineerNeeded = false
    local completedEngineers = CountRole(units, 'engineer')
    local records = RecordByToken(units)
    local committed = {
        expansion = { mass = 0, energy = 0 },
        energy = { mass = 0, energy = 0 },
        engineer = { mass = 0, energy = 0 },
        factory = { mass = 0, energy = 0 },
        air = { mass = 0, energy = 0 },
        tech = { mass = 0, energy = 0 },
        construction = { mass = 0, energy = 0 },
    }
    local activeMassDrain = 0
    local activeEnergyDrain = 0
    local reservedFutureMassDrain = 0
    local reservedFutureEnergyDrain = 0
    local currentCommitments = {}
    local fundedBuilderWork = {}
    local expansionScheduled = 0
    for _, token in ipairs(SortedKeys(controller.pending or {})) do
        local operation = controller.pending[token]
        local budget = ESCALATION.OperationBudget(controller, operation, records)
        local commitmentKey = ESCALATION.CommitmentKey(controller, operation)
        if budget and commitmentKey and StructureOperation(operation) then
            fundedBuilderWork[commitmentKey] = true
        end
        if commitmentKey then
            local commitment = currentCommitments[commitmentKey]
            if not commitment then
                commitment = {
                    owners = {},
                    massCost = nil,
                    energyCost = nil,
                    maximumFraction = nil,
                    budgetValid = false,
                }
                currentCommitments[commitmentKey] = commitment
            end
            commitment.owners[token] = true
            local fraction = tonumber(operation.lastFraction)
            if ESCALATION.FiniteEconomyNumber(fraction)
                and fraction >= 0 and fraction <= 1
                and (commitment.maximumFraction == nil
                    or fraction > commitment.maximumFraction)
            then
                commitment.maximumFraction = fraction
            end
            if budget then
                commitment.budgetValid = true
                commitment.massCost = math.max(
                    tonumber(commitment.massCost) or 0,
                    budget.massCost
                )
                commitment.energyCost = math.max(
                    tonumber(commitment.energyCost) or 0,
                    budget.energyCost
                )
            end
        end
        if budget then
            local lane = committed[budget.lane] and budget.lane or 'construction'
            committed[lane].mass = committed[lane].mass + budget.massDrain
            committed[lane].energy = committed[lane].energy + budget.energyDrain
            activeMassDrain = activeMassDrain + budget.massDrain
            activeEnergyDrain = activeEnergyDrain + budget.energyDrain
            if operation.accepted ~= true
                or operation.phase == 'travelling'
            then
                reservedFutureMassDrain = reservedFutureMassDrain
                    + budget.massDrain
                reservedFutureEnergyDrain = reservedFutureEnergyDrain
                    + budget.energyDrain
            end
        end
        if StructureOperation(operation)
            and operation.buildRole == 'mass_extractor'
        then
            expansionScheduled = expansionScheduled + 1
        end
    end
    local previousLeases = type(controller.economyCommitmentLeases) == 'table'
        and controller.economyCommitmentLeases or {}
    local nextLeases = {}
    local reservedCommittedMassCost = 0
    local reservedCommittedEnergyCost = 0
    local commitmentBudgetsValid = true
    for _, commitmentKey in ipairs(SortedKeys(currentCommitments)) do
        local current = currentCommitments[commitmentKey]
        local previous = previousLeases[commitmentKey]
        local continuousOwner = false
        if type(previous) == 'table' and type(previous.owners) == 'table' then
            for token, _ in pairs(current.owners) do
                if previous.owners[token] == true then
                    continuousOwner = true
                    break
                end
            end
        end
        if not continuousOwner then previous = nil end
        local maximumFraction = previous
            and ESCALATION.FiniteEconomyNumber(previous.maximumFraction)
            and previous.maximumFraction >= 0
            and previous.maximumFraction <= 1
            and previous.maximumFraction
            or 0
        if ESCALATION.FiniteEconomyNumber(current.maximumFraction)
            and current.maximumFraction >= maximumFraction
        then
            maximumFraction = current.maximumFraction
        end
        local massCost = current.budgetValid == true
            and current.massCost
            or (previous and previous.massCost or nil)
        local energyCost = current.budgetValid == true
            and current.energyCost
            or (previous and previous.energyCost or nil)
        local budgetValid = ESCALATION.FiniteEconomyNumber(massCost)
            and ESCALATION.FiniteEconomyNumber(energyCost)
            and massCost >= 0 and energyCost >= 0
        if not budgetValid then
            commitmentBudgetsValid = false
            massCost = 0
            energyCost = 0
            maximumFraction = 0
        end
        local lease = {
            owners = current.owners,
            massCost = massCost,
            energyCost = energyCost,
            maximumFraction = maximumFraction,
            budgetValid = budgetValid,
        }
        nextLeases[commitmentKey] = lease
        reservedCommittedMassCost = reservedCommittedMassCost
            + massCost * (1 - maximumFraction)
        reservedCommittedEnergyCost = reservedCommittedEnergyCost
            + energyCost * (1 - maximumFraction)
    end
    controller.economyCommitmentLeases = nextLeases
    local ledger = type(controller.economyLedger) == 'table'
        and controller.economyLedger or {}
    local allocatorValid = ledger.valid == true
    local recurringMass = allocatorValid
        and (tonumber(ledger.recurringMassIncome) or 0) or 0
    local recurringEnergy = allocatorValid
        and (tonumber(ledger.recurringEnergyIncome) or 0) or 0
    local rollingMassRequested = allocatorValid
        and (tonumber(ledger.massRequested) or 0) or 0
    local rollingEnergyRequested = allocatorValid
        and (tonumber(ledger.energyRequested) or 0) or 0
    local requiredMassReserve = expansionOpportunities > 0
        and ESCALATION.MASS_EXPANSION_RESERVE or 0
    local requiredEnergyReserve = expansionOpportunities > 0
        and ESCALATION.ENERGY_EXPANSION_RESERVE or 0
    local currentMassRequested = ESCALATION.FiniteEconomyNumber(
        economy.massRequested) and economy.massRequested or 0
    local currentEnergyRequested = ESCALATION.FiniteEconomyNumber(
        economy.energyRequested) and economy.energyRequested or 0
    local expansionAvailableMass = allocatorValid and math.max(0,
        recurringMass - math.max(rollingMassRequested, currentMassRequested)
            - reservedFutureMassDrain) or 0
    local expansionAvailableEnergy = allocatorValid and math.max(0,
        recurringEnergy - math.max(rollingEnergyRequested, currentEnergyRequested)
            - reservedFutureEnergyDrain) or 0
    local availableMass = math.max(0,
        expansionAvailableMass - requiredMassReserve)
    local availableEnergy = math.max(0,
        expansionAvailableEnergy - requiredEnergyReserve)
    local postCombatExpansionFunded = expansionOpportunities > expansionScheduled
        and expansionAvailableMass + 0.000001
            >= ESCALATION.LAND_COMBAT_MASS_RESERVE
                + ESCALATION.MASS_EXPANSION_RESERVE
        and expansionAvailableEnergy + 0.000001
            >= ESCALATION.LAND_COMBAT_ENERGY_RESERVE
                + ESCALATION.ENERGY_EXPANSION_RESERVE
    engineerTarget = math.max(
        math.max(2, math.min(12,
            CountArray(fundedBuilderWork)
                + (postCombatExpansionFunded and 1 or 0))),
        math.min(8, 2 + math.floor(completedMex / 3))
    )
    unlockingEngineerNeeded = postCombatExpansionFunded
        and completedEngineers < engineerTarget
    local supportedFactories = ESCALATION.MIN_FACTORY_TARGET
    if allocatorValid then
        supportedFactories = math.max(ESCALATION.MIN_FACTORY_TARGET,
            math.floor(math.max(0, recurringMass - requiredMassReserve)
                / NEXT_FACTORY_SAFE_DRAIN_PER_TICK + 0.00001))
    end
    controller.factoryTarget = supportedFactories
    local factoryDemand = supportedFactories
    local idleFactories = 0
    for _, unit in ipairs(units or {}) do
        if (unit.role == 'land_factory'
                or unit.role == 'land_factory_t2'
                or unit.role == 'air_factory')
            and unit.complete == true and unit.idle == true
            and not controller.pending[unit.token]
        then
            idleFactories = idleFactories + 1
        end
    end
    local fundedFactories = 0
    local factoryMassBudget = availableMass
    local factoryEnergyBudget = availableEnergy
    if allocatorValid then
        for _, unit in ipairs(units or {}) do
            local requestMass = unit.role == 'air_factory' and 0.2
                or (unit.role == 'land_factory_t2' and 0.9
                    or ESCALATION.LAND_COMBAT_MASS_RESERVE)
            local requestEnergy = unit.role == 'air_factory' and 9
                or (unit.role == 'land_factory_t2' and 4.5
                    or ESCALATION.LAND_COMBAT_ENERGY_RESERVE)
            if (unit.role == 'land_factory'
                    or unit.role == 'land_factory_t2'
                    or unit.role == 'air_factory')
                and unit.complete == true and unit.idle == true
                and not controller.pending[unit.token]
                and factoryMassBudget + 0.000001 >= requestMass
                and factoryEnergyBudget + 0.000001 >= requestEnergy
            then
                fundedFactories = fundedFactories + 1
                factoryMassBudget = factoryMassBudget - requestMass
                factoryEnergyBudget = factoryEnergyBudget - requestEnergy
            end
        end
    end
    local oneTimeMass = commitmentBudgetsValid
        and (allocatorValid or ledger.inputValid == true)
        and math.max(0, (tonumber(ledger.oneTimeMassReserve) or 0)
            - reservedCommittedMassCost) or 0
    local oneTimeEnergy = commitmentBudgetsValid
        and (allocatorValid or ledger.inputValid == true)
        and math.max(0, (tonumber(ledger.oneTimeEnergyReserve) or 0)
            - reservedCommittedEnergyCost) or 0
    local techAdmission = 'structural_prerequisite'
    local techEtaTicks = -1
    if not allocatorValid then
        techAdmission = 'invalid_economy'
    elseif completedLandT1 >= 1
        and completedLandT1 + completedLandT2 >= 2
        and completedAirT1 >= 1
        and completedLandT2 < 1
        and CountArray(factoryWorkByRole.land_factory_t2) < 1
    then
        local massNeed = math.max(0, 1170 - oneTimeMass)
        local energyNeed = math.max(0, 9100 - oneTimeEnergy)
        local massEta = availableMass > 0 and math.ceil(massNeed / availableMass) or 1000000000
        local energyEta = availableEnergy > 0 and math.ceil(energyNeed / availableEnergy) or 1000000000
        techEtaTicks = math.max(massEta, energyEta)
        if availableMass >= 1.017391
            and availableEnergy >= 7.913043
            and techEtaTicks <= ESCALATION.ALLOCATOR_PLANNING_TICKS
        then
            techAdmission = 'admitted'
        else
            techAdmission = 'commitment_deferred'
        end
    end
    controller.allocatorDeniedRequest = idleFactories > fundedFactories
        and 'factory_queue' or 'none'
    controller.allocatorDeniedReason = idleFactories > fundedFactories
        and (not allocatorValid and 'invalid_economy' or 'recurring_budget')
        or 'none'
    local combatCompleted = 0
    local aaCompleted = 0
    for _, unit in ipairs(units or {}) do
        if COMBAT_ROLES[unit.role] and unit.complete == true then
            combatCompleted = combatCompleted + 1
            if unit.role == 'anti_air' or unit.role == 't2_anti_air' then
                aaCompleted = aaCompleted + 1
            end
        end
    end
    local frontierScreen = 0
    local homeReserve = 0
    for _, unit in ipairs(units or {}) do
        if COMBAT_ROLES[unit.role] and unit.complete == true then
            if unit.frontierEscort == true then
                frontierScreen = frontierScreen + 1
            elseif unit.assignedToWave ~= true then
                homeReserve = homeReserve + 1
            end
        end
    end
    local reclaimTarget = 'none'
    local reclaimValue = -1
    for _, token in ipairs(SortedKeys(controller.pending or {})) do
        local operation = controller.pending[token]
        if operation.kind == 'reclaim' then
            reclaimTarget = operation.targetKey or 'none'
            reclaimValue = tonumber(operation.targetValue) or -1
            break
        end
    end
    local progress = -1
    if controller.frontierTotal > 0 then
        progress = controller.frontierOwned / controller.frontierTotal
    end
    local campaign = controller.fieldCampaign
    local route = campaign
        and type(campaign.routeAttempt) == 'table'
        and campaign.routeAttempt
        or nil
    local routeRelease = route and route.state == 'releasing'
    local campaignState = campaign and campaign.state or 'idle'
    local campaignCluster = campaign and campaign.clusterKey or 'none'
    local campaignObjective = campaign and campaign.anchorKey or 'none'
    local fieldTokens = campaign
        and type(campaign.fieldTokens) == 'table'
        and CopyArray(campaign.fieldTokens)
        or {}
    local homeTokens = campaign
        and type(campaign.homeTokens) == 'table'
        and CopyArray(campaign.homeTokens)
        or {}
    local fieldAa = 0
    local fieldCompleted = 0
    local homeAa = 0
    local fieldAtAnchor = 0
    local objectivePosition = campaign and campaign.anchorPosition or nil
    for _, unit in ipairs(units or {}) do
        if unit.complete == true and COMBAT_ROLES[unit.role] then
            if CampaignFieldContains(campaign, unit.token) then
                fieldCompleted = fieldCompleted + 1
                if unit.role == 'anti_air' or unit.role == 't2_anti_air' then
                    fieldAa = fieldAa + 1
                end
                if objectivePosition
                    and Distance(unit.position, objectivePosition)
                        <= FIELD_CAMPAIGN_ANCHOR_RADIUS
                then
                    fieldAtAnchor = fieldAtAnchor + 1
                end
            elseif CampaignHomeContains(campaign, unit.token)
                and (unit.role == 'anti_air' or unit.role == 't2_anti_air')
            then
                homeAa = homeAa + 1
            end
        end
    end
    local homeReadyCount = math.max(0, combatCompleted - math.floor(3 * combatCompleted / 4))
    if campaign then
        homeReadyCount = math.max(0, combatCompleted - fieldCompleted)
    end
    local economyValid = type(economy.massIncome) == 'number'
        and type(economy.massRequested) == 'number'
        and type(economy.massStoredRatio) == 'number'
        and type(economy.massTrend) == 'number'
        and type(economy.energyIncome) == 'number'
        and type(economy.energyStoredRatio) == 'number'
        and type(economy.energyTrend) == 'number'
        and economy.massIncome == economy.massIncome
        and economy.massRequested == economy.massRequested
        and economy.massStoredRatio == economy.massStoredRatio
        and economy.massTrend == economy.massTrend
        and economy.energyIncome == economy.energyIncome
        and economy.energyStoredRatio == economy.energyStoredRatio
        and economy.energyTrend == economy.energyTrend
        and math.abs(economy.massIncome) <= 1000000000
        and math.abs(economy.massRequested) <= 1000000000
        and math.abs(economy.massStoredRatio) <= 1000000000
        and math.abs(economy.massTrend) <= 1000000000
        and math.abs(economy.energyIncome) <= 1000000000
        and math.abs(economy.energyStoredRatio) <= 1000000000
        and math.abs(economy.energyTrend) <= 1000000000
        and economy.massIncome >= 0
        and economy.massRequested >= 0
        and economy.energyIncome >= 0
        and economy.massStoredRatio >= 0
        and economy.massStoredRatio <= 1
        and economy.energyStoredRatio >= 0
        and economy.energyStoredRatio <= 1
    local readinessBlockers = {}
    if completedMex < ESCALATION.CAMPAIGN_MIN_MEX then
        TableInsert(readinessBlockers, 'mex')
    end
    if completedFactories < ESCALATION.CAMPAIGN_MIN_FACTORIES then
        TableInsert(readinessBlockers, 'production_factory')
    end
    if completedLandT1 + completedLandT2 < ESCALATION.CAMPAIGN_MIN_LAND_FACTORIES then
        TableInsert(readinessBlockers, 'land_factory')
    end
    if combatCompleted < FIELD_CAMPAIGN_MIN_COMBAT then
        TableInsert(readinessBlockers, 'combat')
    end
    if aaCompleted < FIELD_CAMPAIGN_MIN_AA then
        TableInsert(readinessBlockers, 'anti_air')
    end
    if homeReadyCount < HOME_RESERVE_MIN then
        TableInsert(readinessBlockers, 'home_reserve')
    end
    if not economyValid then TableInsert(readinessBlockers, 'economy_invalid') end
    local campaignReady = TableGetn(readinessBlockers) == 0
    local economyStage = 'opening'
    if completedMex >= 10
        and completedLandT1 + completedLandT2 >= 3
        and completedAirT1 >= 1
    then
        economyStage = completedLandT2 >= 1 and 't2' or 't2_ready'
    elseif completedMex >= 6
        and completedLandT1 + completedLandT2 >= 2
    then
        economyStage = completedAirT1 >= 1 and 'air_screen' or 'air_ready'
    end
    local tick = CurrentTick(controller)
    return {
        ownedMexCount = controller.ownedMexCount,
        lostMexCount = controller.lostMexCount,
        rebuiltMexCount = controller.rebuiltMexCount,
        activeRebuildJobs = rebuildJobs,
        activeFrontierJobs = frontierJobs,
        activeReclaimJobs = reclaimJobs,
        constructionBacklog = constructionBacklog,
        frontierWork = frontierWork,
        allocatorEnabled = true,
        economyLedgerValid = allocatorValid,
        economyInputValid = ledger.inputValid == true,
        economyLedgerSamples = tonumber(ledger.sampleCount) or 0,
        recurringMassIncome = recurringMass,
        recurringEnergyIncome = recurringEnergy,
        rollingMassRequested = rollingMassRequested,
        rollingEnergyRequested = rollingEnergyRequested,
        rollingMassUsage = allocatorValid
            and (tonumber(ledger.massUsage) or 0) or 0,
        rollingEnergyUsage = allocatorValid
            and (tonumber(ledger.energyUsage) or 0) or 0,
        rollingMassStoredRatio = allocatorValid
            and (tonumber(ledger.massStoredRatio) or 0) or 0,
        rollingEnergyStoredRatio = allocatorValid
            and (tonumber(ledger.energyStoredRatio) or 0) or 0,
        rollingMassTrend = allocatorValid
            and (tonumber(ledger.massTrend) or 0) or 0,
        rollingEnergyTrend = allocatorValid
            and (tonumber(ledger.energyTrend) or 0) or 0,
        massDemandSatisfaction = allocatorValid
            and (tonumber(ledger.massDemandSatisfaction) or 0) or 0,
        energyDemandSatisfaction = allocatorValid
            and (tonumber(ledger.energyDemandSatisfaction) or 0) or 0,
        oneTimeMassReserve = oneTimeMass,
        oneTimeEnergyReserve = oneTimeEnergy,
        reclaimedMassDelta = tonumber(ledger.reclaimedMassDelta) or 0,
        reclaimedEnergyDelta = tonumber(ledger.reclaimedEnergyDelta) or 0,
        activeCommittedMassDrain = activeMassDrain,
        activeCommittedEnergyDrain = activeEnergyDrain,
        committedMassExpansion = committed.expansion.mass,
        committedEnergyExpansion = committed.expansion.energy,
        committedMassEnergy = committed.energy.mass,
        committedEnergyEnergy = committed.energy.energy,
        committedMassEngineer = committed.engineer.mass,
        committedEnergyEngineer = committed.engineer.energy,
        committedMassConstruction = committed.construction.mass,
        committedEnergyConstruction = committed.construction.energy,
        committedMassFactory = committed.factory.mass,
        committedEnergyFactory = committed.factory.energy,
        committedMassAir = committed.air.mass,
        committedEnergyAir = committed.air.energy,
        committedMassTech = committed.tech.mass,
        committedEnergyTech = committed.tech.energy,
        availableRecurringMass = availableMass,
        availableRecurringEnergy = availableEnergy,
        expansionRecurringMassBudget = expansionAvailableMass,
        expansionRecurringEnergyBudget = expansionAvailableEnergy,
        expansionOpportunityCount = expansionOpportunities,
        expansionScheduledCount = expansionScheduled,
        engineerTarget = engineerTarget,
        unlockingEngineerNeeded = unlockingEngineerNeeded,
        engineerDemand = engineerTarget,
        factoryDemand = factoryDemand,
        factoryTarget = controller.factoryTarget,
        factoryFundedCount = fundedFactories,
        factoryIdleCount = idleFactories,
        factoryPhysicalCount = factories,
        completedFactories = completedFactories,
        buildingFactories = math.max(0, factories - completedFactories),
        allocatorDeniedRequest = controller.allocatorDeniedRequest or 'none',
        allocatorDeniedReason = controller.allocatorDeniedReason or 'none',
        techAdmission = techAdmission,
        techEtaTicks = techEtaTicks,
        economyStage = economyStage,
        completedMex = completedMex,
        completedLandT1Factories = completedLandT1,
        completedLandT2Factories = completedLandT2,
        completedAirT1Factories = completedAirT1,
        buildingLandT1Factories = CountArray(factoryWorkByRole.land_factory),
        buildingLandT2Factories = CountArray(factoryWorkByRole.land_factory_t2),
        buildingAirT1Factories = CountArray(factoryWorkByRole.air_factory),
        placementCapacity = tonumber(controller.lastPlacementCapacity) or 0,
        placementProbeCount = tonumber(controller.lastPlacementProbeCount) or 0,
        upgradeState = controller.upgradeState or 'none',
        airScreenCount = tonumber(controller.airScreenCount) or 0,
        campaignReady = campaignReady,
        campaignReadinessBlockers = readinessBlockers,
        campaignReadinessBlocker = readinessBlockers[1] or 'none',
        rollbackReason = campaign and campaign.rollbackReason or 'none',
        fieldAttritionLost = campaign and (tonumber(campaign.attritionLost) or 0) or 0,
        fieldAttritionWindow = campaign and (tonumber(campaign.attritionWindow) or 0) or 0,
        massSurplusTicks = controller.massSurplusTicks,
        selectedFrontierCluster = controller.selectedFrontierCluster or 'none',
        selectedFrontierSite = controller.selectedFrontierSite or 'none',
        frontierOwned = controller.frontierOwned,
        frontierTotal = controller.frontierTotal,
        frontierProgress = progress,
        frontierScreenCount = frontierScreen,
        homeReserveCount = homeReserve,
        reclaimTarget = reclaimTarget,
        reclaimValue = reclaimValue,
        rallyPosition = CopyPosition(campaign
            and controller.basePosition
            or controller.rallyPosition
            or controller.basePosition),
        campaignEnabled = controller.fieldCampaignEnabled == true,
        campaignState = campaignState,
        campaignKind = campaign and campaign.kind or 'none',
        campaignCluster = campaignCluster,
        campaignObjective = campaignObjective,
        campaignAnchorKey = campaign and campaign.anchorKey or 'none',
        campaignAnchorX = campaign
            and campaign.anchorPosition
            and tonumber(campaign.anchorPosition[1])
            or -1,
        campaignAnchorZ = campaign
            and campaign.anchorPosition
            and tonumber(campaign.anchorPosition[3])
            or -1,
        campaignMemberKeys = campaign and CopyArray(campaign.memberKeys) or {},
        fieldTokens = fieldTokens,
        homeTokens = homeTokens,
        fieldUnits = TableGetn(fieldTokens),
        fieldAa = fieldAa,
        fieldAtAnchor = fieldAtAnchor,
        campaignFieldAtAnchor = fieldAtAnchor,
        campaignArrivalQuorum = campaign
            and (tonumber(campaign.arrivalQuorum) or 0)
            or 0,
        campaignForwardDistance = campaign
            and (tonumber(campaign.forwardDistance) or -1)
            or -1,
        homeUnits = TableGetn(homeTokens),
        homeAa = homeAa,
        campaignMissionAge = campaign
            and math.max(0, tick - (tonumber(campaign.missionIssuedTick)
                or tonumber(campaign.startedTick)
                or tick))
            or -1,
        campaignLastProgressTick = campaign
            and (tonumber(campaign.lastProgressTick) or -1)
            or -1,
        campaignFullFieldOrders = campaign
            and (tonumber(campaign.fullFieldOrders) or 0)
            or 0,
        campaignReinforcementOrders = campaign
            and (tonumber(campaign.reinforcementOrders) or 0)
            or 0,
        campaignRecoveryOrders = campaign
            and (tonumber(campaign.recoveryOrders) or 0)
            or 0,
        campaignModeSwitches = campaign
            and (tonumber(campaign.modeSwitches) or 0)
            or 0,
        campaignEmergency = campaign and campaign.emergency == true or false,
        campaignRouteState = route and tostring(route.state) or 'none',
        campaignRouteSource = route
            and tostring(route.sourceAnchorKey or 'none')
            or 'none',
        campaignRouteDestination = route
            and tostring(route.candidateAnchorKey or 'none')
            or 'none',
        campaignRouteProbeUnits = route
            and TableGetn(route.probeTokens or {})
            or 0,
        campaignRouteProbeQuorum = route
            and (tonumber(route.probeQuorum) or 0)
            or 0,
        campaignRouteAtDestination = route
            and (tonumber(route.atDestination) or 0)
            or 0,
        campaignRouteAge = route
            and math.max(0, tick - (tonumber(route.stagedTick) or tick))
            or -1,
        campaignRouteLastProgressTick = route
            and (tonumber(route.lastProgressTick) or -1)
            or -1,
        campaignRouteWaypointCount = route
            and TableGetn(route.waypoints or {})
            or 0,
        campaignRouteLength = route
            and (tonumber(route.routeLength) or -1)
            or -1,
        campaignRouteProgressAge = route
            and math.max(0, tick - (tonumber(route.lastProgressTick) or tick))
            or -1,
        campaignRouteReleaseAge = route
            and route.state == 'releasing'
            and math.max(0, tick - (tonumber(route.releaseStartedTick) or tick))
            or -1,
        campaignRouteLastFailure = route
            and tostring(route.lastFailure or 'none')
            or 'none',
        campaignRouteBlockedCount = campaign
            and (tonumber(campaign.routeBlockedCount) or 0)
            or 0,
        campaignRouteEpoch = route and (tonumber(route.epoch) or -1) or -1,
        campaignRouteKey = route and tostring(route.routeKey or 'none') or 'none',
        campaignRouteFingerprint = route
            and tostring(route.routeFingerprint or 'none')
            or 'none',
        campaignRouteSourceKey = route
            and tostring(route.sourceAnchorKey or 'none')
            or 'none',
        campaignIntentMode = campaign
            and controller.legacyFrontierRetirementPending ~= true
            and campaign.pendingMode
            or 'none',
        campaignIntentTokens = campaign
            and controller.legacyFrontierRetirementPending ~= true
            and CopyArray(campaign.pendingTokens)
            or {},
        campaignIntentKind = campaign
            and (route
                and (routeRelease and route.source.kind or route.candidateKind)
                or campaign.desiredKind
                or campaign.kind)
            or 'none',
        campaignIntentEngineer = 'none',
        campaignIntentRollbackReason = campaign
            and (campaign.pendingRollbackReason or campaign.rollbackReason)
            or 'none',
        campaignIntentCluster = campaign
            and (route
                and (routeRelease
                    and route.source.clusterKey
                    or route.candidateClusterKey)
                or campaign.desiredClusterKey
                or campaign.clusterKey)
            or 'none',
        campaignIntentObjective = campaign
            and (route
                and (routeRelease
                    and route.source.anchorKey
                    or route.candidateAnchorKey)
                or campaign.desiredAnchorKey
                or campaign.anchorKey)
            or 'none',
        campaignIntentPosition = campaign
            and CopyPosition(route
                and (routeRelease
                    and route.source.anchorPosition
                    or route.candidateAnchorPosition)
                or (campaign.pendingMode == 'rollback'
                    and (campaign.lastSecuredAnchorPosition or controller.basePosition)
                    or campaign.desiredAnchorPosition
                    or campaign.anchorPosition))
            or nil,
        campaignSerial = campaign and campaign.serial or -1,
    }
end

ESCALATION.FootprintSpec = function(controller, role)
    if type(role) ~= 'string' or ESCALATION.placementObstacleRoles[role] ~= true then
        return nil
    end
    controller.placementFootprintSpecs = controller.placementFootprintSpecs or {}
    local cached = controller.placementFootprintSpecs[role]
    if cached then return cached end
    local blueprintId = Catalog.IdFor(role)
    local blueprint = blueprintId
        and controller.brain.GetUnitBlueprint
        and SafeCall(nil, controller.brain.GetUnitBlueprint, controller.brain, blueprintId)
        or nil
    if type(blueprint) ~= 'table' then return nil end
    local footprint = type(blueprint.Footprint) == 'table'
        and blueprint.Footprint
        or (type(blueprint.Size) == 'table' and blueprint.Size or {})
    local physics = type(blueprint.Physics) == 'table' and blueprint.Physics or {}
    local footX = math.ceil(math.max(1, tonumber(footprint.SizeX) or 1))
    local footZ = math.ceil(math.max(1, tonumber(footprint.SizeZ) or 1))
    local skirtX = math.max(footX, tonumber(physics.SkirtSizeX) or 1)
    local skirtZ = math.max(footZ, tonumber(physics.SkirtSizeZ) or 1)
    cached = {
        footX = footX,
        footZ = footZ,
        skirtX = skirtX,
        skirtZ = skirtZ,
        offsetX = tonumber(physics.SkirtOffsetX) or 0,
        offsetZ = tonumber(physics.SkirtOffsetZ) or 0,
    }
    controller.placementFootprintSpecs[role] = cached
    return cached
end

ESCALATION.PlacementRect = function(controller, role, position)
    local copy = CopyPosition(position)
    local spec = copy and ESCALATION.FootprintSpec(controller, role) or nil
    if not spec then return nil end
    local minimumX = copy[1] - spec.footX * 0.5 + spec.offsetX
    local minimumZ = copy[3] - spec.footZ * 0.5 + spec.offsetZ
    return {
        minimumX,
        minimumZ,
        minimumX + spec.skirtX,
        minimumZ + spec.skirtZ,
    }
end

ESCALATION.PlacementRectsOverlap = function(left, right)
    return type(left) == 'table'
        and type(right) == 'table'
        and left[1] < right[3]
        and right[1] < left[3]
        and left[2] < right[4]
        and right[2] < left[4]
end

local function PlacementSnapshot(controller, units)
    local placements = {
        air_factory = {},
        land_factory = {},
        power_generator = {},
    }
    local claimed = {}
    local occupiedRects = {}
    local function AddOccupied(role, position)
        local rect = ESCALATION.PlacementRect(controller, role, position)
        if rect then TableInsert(occupiedRects, rect) end
    end
    for _, unit in ipairs(units or {}) do
        if ESCALATION.placementObstacleRoles[unit.role] == true then
            AddOccupied(unit.role, unit.position)
        end
    end
    for _, foundation in ipairs(controller.currentFoundations or {}) do
        if foundation.placementKey then claimed[foundation.placementKey] = true end
        AddOccupied(foundation.role, foundation.position)
    end
    for _, operation in pairs(controller.pending or {}) do
        if operation.placementKey then claimed[operation.placementKey] = true end
        if operation.position and operation.buildRole then
            AddOccupied(operation.buildRole, operation.position)
        end
    end
    local probes = 0
    local roleProbeStart = 0
    local function Consider(role, position)
        if probes >= ESCALATION.MAX_PLACEMENT_PROBES
            or probes - roleProbeStart >= ESCALATION.MAX_PLACEMENT_PROBES / 3
            or TableGetn(placements[role]) >= ESCALATION.PLACEMENT_RESULTS_PER_ROLE
        then
            return
        end
        local candidate = TerrainPosition(position)
        local key = candidate and PlacementKey(candidate) or nil
        if not key or claimed[key] or SiteIsBlocked(controller, key) then return end
        local candidateRect = ESCALATION.PlacementRect(controller, role, candidate)
        if not candidateRect then return end
        for _, occupied in ipairs(occupiedRects) do
            if ESCALATION.PlacementRectsOverlap(candidateRect, occupied) then return end
        end
        probes = probes + 1
        local blueprintId = Catalog.IdFor(role)
        if blueprintId
            and SafeCall(false, controller.brain.CanBuildStructureAt,
                controller.brain, blueprintId, candidate) == true
        then
            claimed[key] = true
            TableInsert(placements[role], candidate)
            TableInsert(occupiedRects, candidateRect)
        end
    end
    local ringOffsets = {
        { 1, 0 }, { 0, 1 }, { -1, 0 }, { 0, -1 },
        { 1, 1 }, { -1, 1 }, { -1, -1 }, { 1, -1 },
    }
    local sortedSeeds = CopyArray(controller.placementSeeds)
    table.sort(sortedSeeds, function(a, b)
        return tostring(PlacementKey(a) or '') < tostring(PlacementKey(b) or '')
    end)
    for _, role in ipairs({ 'power_generator', 'land_factory', 'air_factory' }) do
        roleProbeStart = probes
        for _, seed in ipairs(sortedSeeds) do
            Consider(role, seed)
        end
        local radius = 28
        while radius <= ESCALATION.MAX_PLACEMENT_RADIUS
            and probes < ESCALATION.MAX_PLACEMENT_PROBES
            and probes - roleProbeStart < ESCALATION.MAX_PLACEMENT_PROBES / 3
            and TableGetn(placements[role]) < ESCALATION.PLACEMENT_RESULTS_PER_ROLE
        do
            for _, offset in ipairs(ringOffsets) do
                Consider(role, {
                    controller.basePosition[1] + offset[1] * radius,
                    0,
                    controller.basePosition[3] + offset[2] * radius,
                })
            end
            radius = radius + 7
        end
    end
    controller.lastPlacementProbeCount = probes
    controller.lastPlacementCapacity = TableGetn(placements.land_factory)
        + TableGetn(placements.air_factory)
        + TableGetn(placements.power_generator)
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
    local siteReservation = operation.siteKey
        and controller.reservations[operation.siteKey]
        or nil
    if type(siteReservation) == 'table' and siteReservation.actorToken == token then
        controller.reservations[operation.siteKey] = nil
    end
    if operation.targetKey
        and controller.reclaimReservations[operation.targetKey] == token
    then
        controller.reclaimReservations[operation.targetKey] = nil
    end
    if operation.targetToken
        and controller.foundationReservations[operation.targetToken] == token
    then
        controller.foundationReservations[operation.targetToken] = nil
    end
    if StructureOperation(operation)
        and (reason == 'rejected'
            or reason == 'timeout'
            or reason == 'stalled'
            or reason == 'command_error')
    then
        BlockSite(controller, operation.siteKey or operation.placementKey, reason)
    end
    if operation.kind == 'factory_upgrade' then
        controller.upgradeState = reason and ('failed:' .. tostring(reason)) or 'completed'
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

local function SiteState(observation, siteKey)
    if not siteKey then return nil end
    for _, collection in pairs(observation.sites or {}) do
        for _, site in ipairs(collection or {}) do
            if site.key == siteKey then return site end
        end
    end
    return nil
end

local function PlacementState(observation, operation)
    if not operation.placementKey or not operation.position then return nil end
    local maximumDistance = PLACEMENT_MATCH_DISTANCE * PLACEMENT_MATCH_DISTANCE
    for _, unit in ipairs(observation.units or {}) do
        if unit.role == operation.buildRole
            and DistanceSquared(unit.position, operation.position) <= maximumDistance
        then
            return {
                occupied = true,
                complete = unit.complete == true,
                fractionComplete = tonumber(unit.fractionComplete) or 0,
            }
        end
    end
    return nil
end

local function OperationCompleted(controller, operation, observation, record)
    if StructureOperation(operation) then
        local state = nil
        if operation.siteKey then
            state = SiteState(observation, operation.siteKey)
        else
            state = PlacementState(observation, operation)
        end
        return state and state.complete == true or false
    end
    if operation.kind == 'reclaim' then
        local freshness = controller.reclaimFreshness[operation.actorToken]
        return freshness
            and freshness.actorToken == operation.actorToken
            and freshness.targetKey == operation.targetKey
            and freshness.observedTick == tonumber(observation.tick)
            and freshness.queried == true
            and freshness.covered == true
            and (freshness.state == 'absent' or freshness.state == 'depleted')
            or false
    end
    if operation.kind == 'factory_upgrade' then
        if record
            and record.role == operation.upgradeRole
            and record.complete == true
        then
            return true
        end
        if not operation.upgradeTargetToken and record then
            local actor = controller.unitRefs[operation.actorToken]
            local focus = actor
                and SafeCall(nil, actor.GetFocusUnit, actor)
                or nil
            if focus then
                for _, token in ipairs(SortedKeys(controller.unitRefs or {})) do
                    if controller.unitRefs[token] == focus then
                        local target = nil
                        for _, unit in ipairs(observation.units or {}) do
                            if unit.token == token then target = unit break end
                        end
                        if target
                            and target.role == operation.upgradeRole
                            and ESCALATION.UpgradeTargetActor(
                                controller,
                                token,
                                target
                            ) == focus
                        then
                            operation.upgradeTargetToken = token
                            operation.upgradeTargetReference = focus
                            operation.lastFraction = tonumber(target.fractionComplete) or 0
                            operation.lastProgressTick = CurrentTick(controller)
                            return target.complete == true
                        end
                    end
                end
            end
        end
        if operation.upgradeTargetToken then
            for _, unit in ipairs(observation.units or {}) do
                if unit.token == operation.upgradeTargetToken then
                    if unit.role ~= operation.upgradeRole
                        or not ESCALATION.UpgradeTargetActor(
                            controller,
                            unit.token,
                            unit
                        )
                    then
                        return false
                    end
                    local fraction = tonumber(unit.fractionComplete) or 0
                    if fraction > (tonumber(operation.lastFraction) or 0) + 0.001 then
                        operation.lastFraction = fraction
                        operation.lastProgressTick = CurrentTick(controller)
                    end
                    if unit.complete == true then
                        operation.completedToken = unit.token
                        return true
                    end
                    return false
                end
            end
            return false
        end
        -- An upgrade replacement is authoritative only after the live source
        -- exposes it through GetFocusUnit. A nearby T2 foundation can belong
        -- to another factory, so spatial matching is not a safe identity.
        return false
    end
    return operation.kind == 'factory_build'
        and record
        and operation.accepted == true
        and record.idle == true
end

local function SetOperationPhase(controller, operation, phase)
    if not phase or operation.phase == phase then return end
    local previous = operation.phase or 'unknown'
    operation.phase = phase
    operation.lastProgressTick = CurrentTick(controller)
    Emit(controller, 'job_phase_changed', {
        actor = operation.actorToken,
        from = previous,
        phase = phase,
    })
end

local function OperationProgress(controller, operation, observation, record)
    local progressed = false
    local remainingDistance = nil
    if operation.position and record and record.position then
        local distance = Distance(record.position, operation.position)
        remainingDistance = distance
        operation.lastDistance = distance
        if operation.phase == 'travelling' then
            local speed = tonumber(record.moveSpeed) or DEFAULT_ENGINEER_SPEED
            local heartbeatDistance = math.max(4, speed * 5)
            if not operation.lastProgressPosition then
                operation.lastProgressPosition = CopyPosition(record.position)
            elseif Distance(record.position, operation.lastProgressPosition)
                    >= heartbeatDistance
            then
                operation.lastProgressPosition = CopyPosition(record.position)
                progressed = true
            end
        end
    end
    if StructureOperation(operation) then
        local state = operation.siteKey
            and SiteState(observation, operation.siteKey)
            or PlacementState(observation, operation)
        local fraction = state and tonumber(state.fractionComplete) or 0
        local assistArrived = operation.kind ~= 'assist_structure'
            or record.building == true
            or (remainingDistance ~= nil
                and remainingDistance <= (tonumber(record.buildDistance) or 10))
        if state and state.occupied == true and assistArrived then
            SetOperationPhase(controller, operation, 'building')
        end
        if fraction > (tonumber(operation.lastFraction) or 0) + 0.001 then
            operation.lastFraction = fraction
            progressed = true
        end
    elseif operation.kind == 'reclaim' then
        local freshness = operation.actorToken
            and controller.reclaimFreshness[operation.actorToken]
            or nil
        local remaining = freshness
            and freshness.state == 'present'
            and freshness.observedTick == tonumber(observation.tick)
            and tonumber(freshness.value)
            or nil
        if record and record.busy == true then
            SetOperationPhase(controller, operation, 'reclaiming')
        end
        if remaining
            and remaining + 0.001
                < (tonumber(operation.lastTargetValue) or 1000000000000)
        then
            operation.lastTargetValue = remaining
            progressed = true
        end
    end
    if progressed then
        operation.lastProgressTick = tonumber(observation.tick) or operation.lastProgressTick
    end
    return progressed
end

local function RequestOperationCancellation(controller, operation, record, reason)
    local actor = LiveOwnedActor(
        controller,
        operation.actorToken,
        record,
        record and record.role or nil
    )
    if not actor then return false end
    local tick = CurrentTick(controller)
    if operation.phase ~= 'cancelling' then
        operation.cancelReason = reason or 'timeout'
        operation.cancelRequestedTick = tick
        operation.cancelAttempts = 0
        operation.cancelClearSucceeded = false
        operation.cancelClearTick = nil
        SetOperationPhase(controller, operation, 'cancelling')
    end
    if operation.cancelClearSucceeded == true
        and operation.cancelClearTick == tick
    then
        return true
    end
    local ok = pcall(function() IssueClearCommands({ actor }) end)
    operation.cancelAttempts = (tonumber(operation.cancelAttempts) or 0) + 1
    operation.cancelClearTick = tick
    operation.cancelClearSucceeded = ok
    return ok
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

local function RecordPending(controller, intent, record)
    local position = CopyPosition(intent.position)
    local placementKey = nil
    if not intent.siteKey and position then
        placementKey = PlacementKey(position)
    end
    local tick = CurrentTick(controller)
    local initialDistance = position and record and Distance(record.position, position) or 0
    local speed = record and tonumber(record.moveSpeed) or DEFAULT_ENGINEER_SPEED
    if not speed or speed <= 0 then speed = DEFAULT_ENGINEER_SPEED end
    local buildRate = record and tonumber(record.buildRate) or 1
    if not buildRate or buildRate <= 0 then buildRate = 1 end
    local targetBlueprint = nil
    local targetId = intent.buildRole and Catalog.IdFor(intent.buildRole) or nil
    if targetId and controller.brain.GetUnitBlueprint then
        targetBlueprint = SafeCall(nil, controller.brain.GetUnitBlueprint, controller.brain, targetId)
    end
    local buildTime = targetBlueprint
        and targetBlueprint.Economy
        and tonumber(targetBlueprint.Economy.BuildTime)
        or 60
    local travelTicks = math.ceil((initialDistance / speed) * 10 * 1.75)
    local buildTicks = math.ceil((buildTime / buildRate) * 10 * 2)
    local deadline = tick + math.max(OPERATION_TIMEOUT_TICKS,
        travelTicks + buildTicks + BUILD_FINISH_ALLOWANCE_TICKS)
    local phase = 'travelling'
    if intent.kind == 'assist_structure'
        and initialDistance <= (tonumber(record and record.buildDistance) or 10)
    then
        phase = 'building'
    elseif intent.kind == 'reclaim' and initialDistance <= 2 then
        phase = 'reclaiming'
    elseif intent.kind == 'factory_build'
        or intent.kind == 'factory_upgrade'
    then
        phase = 'building'
    end
    local operation = {
        actorToken = intent.actorToken,
        kind = intent.kind,
        buildRole = intent.buildRole,
        upgradeRole = intent.upgradeRole,
        siteKey = intent.siteKey,
        placementKey = placementKey,
        position = position,
        issuedTick = tick,
        deadlineTick = deadline,
        lastProgressTick = tick,
        lastDistance = initialDistance,
        lastProgressPosition = record and CopyPosition(record.position) or nil,
        initialDistance = initialDistance,
        lastFraction = 0,
        phase = phase,
        accepted = false,
        reason = intent.reason,
        clusterKey = intent.clusterKey,
        targetToken = intent.targetToken,
        targetKey = intent.targetKey,
        targetReference = intent.kind == 'reclaim'
            and intent.targetKey
            and controller.reclaimRefs[intent.targetKey]
            or nil,
        targetValue = intent.targetValue,
        lastTargetValue = intent.targetValue,
        observerToken = intent.observerToken,
        observedTick = intent.observedTick,
        visionRadius = intent.visionRadius,
    }
    controller.pending[intent.actorToken] = operation
    if intent.siteKey then
        controller.reservations[intent.siteKey] = {
            actorToken = intent.actorToken,
            issuedTick = operation.issuedTick,
        }
    end
    if intent.targetKey then
        controller.reclaimReservations[intent.targetKey] = intent.actorToken
    end
    if intent.targetToken then
        controller.foundationReservations[intent.targetToken] = intent.actorToken
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
    local actor = LiveOwnedActor(controller, intent.actorToken, record, record.role)
    if not actor
        or SafeCall(false, actor.IsIdleState, actor) ~= true
        or SafeCall(false, actor.IsUnitState, actor, 'Building') == true
        or SafeCall(false, actor.IsUnitState, actor, 'Moving') == true
        or not CanUnitBuild(actor, blueprintId)
    then
        return false
    end
    if SafeCall(false, controller.brain.CanBuildStructureAt, controller.brain, blueprintId, position) ~= true then
        BlockSite(controller, intent.siteKey or PlacementKey(position), 'preflight')
        return false
    end

    RecordPending(controller, intent, record)
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
    local legal = record and ESCALATION.factoryProducts[record.role] or nil
    if controller.pending[intent.actorToken]
        or not legal
        or legal[intent.buildRole] ~= true
        or record.complete ~= true
        or record.idle ~= true
        or not record.canBuild
        or record.canBuild[intent.buildRole] ~= true
    then
        return false
    end
    local blueprintId = Catalog.IdFor(intent.buildRole)
    local actor = LiveOwnedActor(
        controller,
        intent.actorToken,
        record,
        record.role
    )
    if not actor
        or not blueprintId
        or SafeCall(false, actor.IsIdleState, actor) ~= true
        or SafeCall(false, actor.IsUnitState, actor, 'Building') == true
        or SafeCall(false, actor.IsUnitState, actor, 'Upgrading') == true
        or SafeCall(false, actor.IsPaused, actor) == true
        or not CanUnitBuild(actor, blueprintId)
    then
        return false
    end
    RecordPending(controller, intent, record)
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

ESCALATION.ExecuteUpgrade = function(controller, intent, record)
    if controller.pending[intent.actorToken]
        or record.role ~= 'land_factory'
        or intent.upgradeRole ~= 'land_factory_t2'
        or record.complete ~= true
        or record.idle ~= true
        or not record.canBuild
        or record.canBuild.land_factory_t2 ~= true
    then
        return false
    end
    local blueprintId = Catalog.IdFor(intent.upgradeRole)
    local actor = LiveOwnedActor(controller, intent.actorToken, record, 'land_factory')
    if not actor
        or not blueprintId
        or SafeCall(false, actor.IsIdleState, actor) ~= true
        or SafeCall(false, actor.IsUnitState, actor, 'Upgrading') == true
        or not CanUnitBuild(actor, blueprintId)
    then
        return false
    end
    intent.buildRole = intent.upgradeRole
    intent.position = CopyPosition(record.position)
    RecordPending(controller, intent, record)
    local ok = pcall(function() IssueUpgrade({ actor }, blueprintId) end)
    if not ok then
        ReleaseOperation(controller, intent.actorToken, 'command_error')
        return false
    end
    controller.upgradeState = 'ordered'
    Emit(controller, 'order', {
        actor = intent.actorToken,
        command = 'factory_upgrade',
        role = intent.upgradeRole,
    })
    return true
end

ESCALATION.ExecuteAirScreen = function(
    controller,
    intent,
    records,
    usedActors,
    observation
)
    if type(intent.actorTokens) ~= 'table' then return false end
    local position = TerrainPosition(intent.position)
    local basePosition = observation
        and TerrainPosition(observation.basePosition)
        or nil
    local fairPosition = position
        and basePosition
        and DistanceSquared(position, basePosition) <= 0.01
    local campaign = controller.fieldCampaign
    if not fairPosition
        and campaign
        and TerrainPosition(campaign.anchorPosition)
        and DistanceSquared(position, TerrainPosition(campaign.anchorPosition)) <= 0.01
    then
        fairPosition = true
    end
    if not fairPosition then return false end
    local actors = {}
    local tokens = {}
    local seen = {}
    for _, token in ipairs(intent.actorTokens) do
        local record = records[token]
        if type(token) ~= 'string'
            or seen[token]
            or usedActors[token]
            or controller.airAssignments[token]
            or not record
            or record.role ~= 'interceptor'
            or record.complete ~= true
            or record.idle ~= true
        then
            return false
        end
        local actor = LiveOwnedActor(controller, token, record, 'interceptor')
        if not actor then return false end
        seen[token] = true
        TableInsert(tokens, token)
        TableInsert(actors, actor)
    end
    if TableGetn(actors) == 0 or not position then return false end
    if not pcall(function() IssueClearCommands(actors) end) then return false end
    if not pcall(function() IssuePatrol(actors, position) end) then
        pcall(function() IssueClearCommands(actors) end)
        return false
    end
    for _, token in ipairs(tokens) do
        controller.airAssignments[token] = true
        usedActors[token] = true
    end
    controller.airScreenCount = CountArray(controller.airAssignments)
    Emit(controller, 'order', {
        actor = 'air_screen',
        command = 'patrol',
        role = 'interceptor',
        units = TableGetn(tokens),
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

LiveOwnedActor = function(controller, token, record, expectedRole)
    if type(token) ~= 'string'
        or not record
        or record.token ~= token
        or record.role ~= expectedRole
        or record.complete ~= true
    then
        return nil, nil
    end
    local actor = controller.unitRefs[token]
    if not actor
        or actor.Dead == true
        or SafeCall(true, actor.BeenDestroyed, actor) == true
        or SafeCall(-1, actor.GetArmy, actor) ~= controller.brain.Army
        or (tonumber(SafeCall(0, actor.GetFractionComplete, actor)) or 0) < 1
    then
        return nil, nil
    end
    local entityId = SafeCall(nil, actor.GetEntityId, actor)
    local generation = entityId and controller.entityGenerations[entityId] or nil
    if not generation
        or generation.reference ~= actor
        or token ~= tostring(entityId) .. ':' .. tostring(generation.generation)
    then
        return nil, nil
    end
    local blueprint = SafeCall(nil, actor.GetBlueprint, actor)
    if not blueprint or Catalog.RoleFor(blueprint.BlueprintId) ~= expectedRole then
        return nil, nil
    end
    return actor, CopyPosition(SafeCall(nil, actor.GetPosition, actor))
end

local function LiveOwnedConstructionTarget(controller, token, record, expectedRole)
    if type(token) ~= 'string'
        or not record
        or record.token ~= token
        or record.role ~= expectedRole
        or record.complete == true
    then
        return nil
    end
    local target = controller.unitRefs[token]
    if not target
        or target.Dead == true
        or SafeCall(true, target.BeenDestroyed, target) == true
        or SafeCall(-1, target.GetArmy, target) ~= controller.brain.Army
        or (tonumber(SafeCall(1, target.GetFractionComplete, target)) or 1) >= 1
    then
        return nil
    end
    local entityId = SafeCall(nil, target.GetEntityId, target)
    local generation = entityId and controller.entityGenerations[entityId] or nil
    if not generation
        or generation.reference ~= target
        or token ~= tostring(entityId) .. ':' .. tostring(generation.generation)
    then
        return nil
    end
    local blueprint = SafeCall(nil, target.GetBlueprint, target)
    if not blueprint or Catalog.RoleFor(blueprint.BlueprintId) ~= expectedRole then return nil end
    return target
end

ESCALATION.UpgradeTargetActor = function(controller, token, record)
    local target = nil
    if record and record.complete == true then
        target = LiveOwnedActor(controller, token, record, 'land_factory_t2')
    else
        target = LiveOwnedConstructionTarget(
            controller,
            token,
            record,
            'land_factory_t2'
        )
    end
    if not target then return nil end
    local blueprint = SafeCall(nil, target.GetBlueprint, target)
    local general = blueprint and blueprint.General or nil
    if type(general) ~= 'table'
        or tostring(general.UpgradesFrom or '')
            ~= tostring(Catalog.IdFor('land_factory') or '')
    then
        return nil
    end
    return target
end

ESCALATION.UpgradeInProgress = function(controller, operation, record)
    local actor = LiveOwnedActor(
        controller,
        operation.actorToken,
        record,
        'land_factory'
    )
    if not actor
        or SafeCall(false, actor.IsUnitState, actor, 'Upgrading') ~= true
        or SafeCall(false, actor.IsPaused, actor) == true
        or type(operation.upgradeTargetToken) ~= 'string'
    then
        return false, nil
    end
    local reference = controller.unitRefs[operation.upgradeTargetToken]
    local fraction = reference
        and tonumber(SafeCall(nil, reference.GetFractionComplete, reference))
        or nil
    local target = fraction and ESCALATION.UpgradeTargetActor(
        controller,
        operation.upgradeTargetToken,
        {
            token = operation.upgradeTargetToken,
            role = 'land_factory_t2',
            complete = fraction >= 1,
        }
    ) or nil
    local focus = SafeCall(nil, actor.GetFocusUnit, actor)
    if not target or focus ~= target then return false, nil end
    return true, actor
end

ESCALATION.UpgradeCommandMatches = function(operation, actor)
    local expectedBlueprint = Catalog.IdFor(operation.upgradeRole)
    for _, command in ipairs(SafeCall({}, actor.GetCommandQueue, actor) or {}) do
        if tonumber(command.commandType) == 27
            and tostring(command.blueprintId or '')
                == tostring(expectedBlueprint or '')
        then
            return true
        end
    end
    return false
end

ESCALATION.UpgradeCancellationMatches = function(operation, actor)
    return operation.upgradeTargetReference ~= nil
        and SafeCall(nil, actor.GetFocusUnit, actor)
            == operation.upgradeTargetReference
        and ESCALATION.UpgradeCommandMatches(operation, actor)
end

ESCALATION.UpgradeAccepted = function(controller, operation, record)
    local active, actor = ESCALATION.UpgradeInProgress(
        controller,
        operation,
        record
    )
    if not active then return false end
    return ESCALATION.UpgradeCommandMatches(operation, actor)
end

local function LiveOwnedReference(controller, token, expectedRole)
    if type(token) ~= 'string' then return nil, nil end
    local actor = controller.unitRefs[token]
    if not actor
        or actor.Dead == true
        or SafeCall(true, actor.BeenDestroyed, actor) == true
        or SafeCall(-1, actor.GetArmy, actor) ~= controller.brain.Army
        or (tonumber(SafeCall(0, actor.GetFractionComplete, actor)) or 0) < 1
    then
        return nil, nil
    end
    local entityId = SafeCall(nil, actor.GetEntityId, actor)
    local generation = entityId and controller.entityGenerations[entityId] or nil
    local blueprint = SafeCall(nil, actor.GetBlueprint, actor)
    if not generation
        or generation.reference ~= actor
        or token ~= tostring(entityId) .. ':' .. tostring(generation.generation)
        or not blueprint
        or Catalog.RoleFor(blueprint.BlueprintId) ~= expectedRole
    then
        return nil, nil
    end
    return actor, CopyPosition(SafeCall(nil, actor.GetPosition, actor))
end

local function LiveVisionRadius(actor)
    if not actor or SafeCall(false, actor.IsIntelEnabled, actor, 'Vision') ~= true then
        return nil
    end
    local radius = tonumber(SafeCall(nil, actor.GetIntelRadius, actor, 'Vision'))
    if radius == nil then
        local blueprint = SafeCall(nil, actor.GetBlueprint, actor)
        radius = blueprint and blueprint.Intel and tonumber(blueprint.Intel.VisionRadius) or nil
    end
    if not radius or radius <= 0 then return nil end
    return math.min(RECLAIM_QUERY_RADIUS, radius)
end

local function ReclaimCandidate(controller, key)
    for _, candidate in ipairs(controller.reclaimCandidates or {}) do
        if candidate.key == key then return candidate end
    end
    return nil
end

local function CurrentReclaimTargetVisible(actor, center, radius, target)
    if not actor or not center or not radius or not target then return false end
    local rectangle = SafeCall(nil, Rect,
        center[1] - radius,
        center[3] - radius,
        center[1] + radius,
        center[3] + radius
    ) or {
        center[1] - radius,
        center[3] - radius,
        center[1] + radius,
        center[3] + radius,
    }
    local raw = SafeCall({}, function() return GetReclaimablesInRect(rectangle) end)
    for _, candidate in pairs(raw or {}) do
        if candidate == target then return true end
    end
    return false
end

local function ExecuteAssistStructure(controller, intent, record, recordByToken)
    if controller.pending[intent.actorToken]
        or record.complete ~= true
        or record.idle ~= true
        or not record.canBuild
        or record.canBuild[intent.buildRole] ~= true
        or type(intent.targetToken) ~= 'string'
        or (intent.siteKey and controller.reservations[intent.siteKey])
        or controller.foundationReservations[intent.targetToken]
    then
        return false
    end
    local actor = LiveOwnedActor(controller, intent.actorToken, record, record.role)
    local targetRecord = recordByToken[intent.targetToken]
    local target = LiveOwnedConstructionTarget(
        controller,
        intent.targetToken,
        targetRecord,
        intent.buildRole
    )
    if not actor
        or not target
        or SafeCall(false, actor.IsIdleState, actor) ~= true
    then
        return false
    end

    RecordPending(controller, intent, record)
    local ok = pcall(function() IssueGuard({ actor }, target) end)
    if not ok then
        ReleaseOperation(controller, intent.actorToken, 'command_error')
        return false
    end
    Emit(controller, 'order', {
        actor = intent.actorToken,
        command = 'assist_structure',
        role = intent.buildRole,
        site = intent.siteKey or 'placement',
    })
    return true
end

local function LiveHealthyCommander(controller, token, record)
    if not HealthyCommander(record) or controller.pending[token] then return nil end
    local actor = LiveOwnedActor(controller, token, record, 'acu')
    if not actor then return nil end
    local health = tonumber(SafeCall(nil, actor.GetHealth, actor))
    local maximum = tonumber(SafeCall(nil, actor.GetMaxHealth, actor))
    if not health
        or not maximum
        or maximum <= 0
        or health / maximum < COMMANDER_PUSH_HEALTH_RATIO
    then
        return nil
    end
    return actor
end

local function ExecuteReclaim(controller, intent, record)
    if record.role ~= 'engineer'
        or record.complete ~= true
        or record.idle ~= true
        or controller.pending[intent.actorToken]
        or type(intent.targetKey) ~= 'string'
        or controller.reclaimReservations[intent.targetKey]
    then
        return false
    end
    local activeReclaimJobs = 0
    for _, operation in pairs(controller.pending or {}) do
        if operation.kind == 'reclaim' then
            activeReclaimJobs = activeReclaimJobs + 1
        end
    end
    if activeReclaimJobs >= MAX_ACTIVE_RECLAIM_JOBS then return false end
    local actor, actorPosition = LiveOwnedActor(controller, intent.actorToken, record, 'engineer')
    local candidate = ReclaimCandidate(controller, intent.targetKey)
    local target = controller.reclaimRefs[intent.targetKey]
    local targetPosition = target
        and CopyPosition(target.CachePosition or SafeCall(nil, target.GetPosition, target))
        or nil
    local observer = nil
    local observerPosition = nil
    if candidate then
        observer, observerPosition = LiveOwnedReference(
            controller,
            candidate.observerToken,
            'engineer'
        )
    end
    local actorRadius = LiveVisionRadius(actor)
    local observerRadius = LiveVisionRadius(observer)
    local observedTick = candidate and tonumber(candidate.observedTick) or nil
    local targetMass = target
        and (tonumber(target.MaxMassReclaim) or 0)
            * (tonumber(target.ReclaimLeft) or 0)
        or 0
    if not actor
        or not actorPosition
        or not candidate
        or not observer
        or not observerPosition
        or not observedTick
        or CurrentTick(controller) - observedTick > RECLAIM_QUERY_INTERVAL_TICKS
        or not actorRadius
        or not observerRadius
        or not PropAlive(target)
        or SafeCall(false, IsProp, target) ~= true
        or not targetPosition
        or Distance(actorPosition, targetPosition) > actorRadius
        or Distance(observerPosition, targetPosition) > observerRadius
        or targetMass < MIN_RECLAIM_MASS
        or not CurrentReclaimTargetVisible(
            actor,
            actorPosition,
            actorRadius,
            target
        )
        or not PositionControlled(
            controller,
            targetPosition,
            (controller.currentSites and controller.currentSites.mass) or {}
        )
    then
        return false
    end
    intent.position = targetPosition
    intent.targetValue = targetMass
    intent.observerToken = candidate.observerToken
    intent.observedTick = observedTick
    intent.visionRadius = candidate.visionRadius
    RecordPending(controller, intent, record)
    local ok = pcall(function() IssueReclaim({ actor }, target) end)
    if not ok then
        ReleaseOperation(controller, intent.actorToken, 'command_error')
        return false
    end
    Emit(controller, 'order', {
        actor = intent.actorToken,
        command = 'reclaim',
        role = 'engineer',
        target = intent.targetKey,
        value = intent.targetValue,
    })
    return true
end

local function ExecuteFrontierScreen(controller, intent, recordByToken, usedActors)
    if type(intent.engineerToken) ~= 'string' then return false end
    local frontierOperation = controller.pending[intent.engineerToken]
    if not frontierOperation
        or frontierOperation.reason ~= 'frontier_expansion'
        or not StructureOperation(frontierOperation)
        or frontierOperation.clusterKey ~= intent.clusterKey
    then
        return false
    end
    local existingMission = controller.frontierMission
    if existingMission
        and (existingMission.engineerToken ~= intent.engineerToken
            or existingMission.clusterKey ~= intent.clusterKey)
    then
        return false
    end
    local engineerRecord = recordByToken[intent.engineerToken]
    local engineer = LiveOwnedActor(controller, intent.engineerToken, engineerRecord, 'engineer')
    if not engineer then return false end
    local tokens = {}
    local actors = {}
    local seen = {}
    local displacedToken = intent.displacedToken
    local rotation = displacedToken ~= nil
    for _, token in ipairs(intent.actorTokens or {}) do
        if type(token) ~= 'string' or seen[token] then return false end
        seen[token] = true
        TableInsert(tokens, token)
    end
    table.sort(tokens)
    if TableGetn(tokens) == 0 then return false end
    if rotation and (type(displacedToken) ~= 'string'
        or TableGetn(tokens) ~= 1
        or displacedToken == tokens[1])
    then
        return false
    end
    for _, token in ipairs(tokens) do
        local record = recordByToken[token]
        if usedActors[token]
            or controller.pending[token]
            or controller.waveAssignments[token]
            or controller.frontierAssignments[token]
            or not record
            or not COMBAT_ROLES[record.role]
            or record.complete ~= true
        then
            return false
        end
        local actor = LiveOwnedActor(controller, token, record, record.role)
        if not actor then return false end
        TableInsert(actors, actor)
    end
    if rotation then
        if not existingMission
            or ESCALATION.antiAirRoles[recordByToken[tokens[1]].role] ~= true
        then
            return false
        end
        local missionTokens = {}
        local missionSeen = {}
        local displacedActor = nil
        local screenHasAntiAir = false
        for _, token in ipairs(existingMission.escortTokens or {}) do
            if type(token) ~= 'string' or missionSeen[token] then return false end
            missionSeen[token] = true
            local assignment = controller.frontierAssignments[token]
            local record = recordByToken[token]
            if usedActors[token]
                or controller.pending[token]
                or controller.waveAssignments[token]
                or not assignment
                or assignment.engineerToken ~= intent.engineerToken
                or assignment.clusterKey ~= intent.clusterKey
                or not record
                or not COMBAT_ROLES[record.role]
                or record.complete ~= true
            then
                return false
            end
            local actor = LiveOwnedActor(controller, token, record, record.role)
            if not actor then return false end
            if ESCALATION.antiAirRoles[record.role] then screenHasAntiAir = true end
            if token == displacedToken then
                if ESCALATION.antiAirRoles[record.role] then return false end
                displacedActor = actor
            end
            TableInsert(missionTokens, token)
        end
        if TableGetn(missionTokens) < 1
            or TableGetn(missionTokens) > FRONTIER_SCREEN_MAX
            or screenHasAntiAir
            or not displacedActor
        then
            return false
        end
        local liveHomeReserve = 0
        for token, record in pairs(recordByToken or {}) do
            if type(token) == 'string'
                and COMBAT_ROLES[record.role]
                and record.complete == true
                and record.assignedToWave ~= true
                and not controller.pending[token]
                and not controller.waveAssignments[token]
                and not controller.frontierAssignments[token]
            then
                local actor = LiveOwnedActor(controller, token, record, record.role)
                if actor then liveHomeReserve = liveHomeReserve + 1 end
            end
        end
        if liveHomeReserve < HOME_RESERVE_MIN then return false end

        local clearNewOk = pcall(function() IssueClearCommands(actors) end)
        if not clearNewOk then return false end
        local guardNewOk = pcall(function() IssueGuard(actors, engineer) end)
        if not guardNewOk then
            pcall(function() IssueClearCommands(actors) end)
            return false
        end
        local clearDisplacedOk = pcall(function()
            IssueClearCommands({ displacedActor })
        end)
        if not clearDisplacedOk then
            pcall(function() IssueClearCommands(actors) end)
            return false
        end

        local tick = CurrentTick(controller)
        local replacement = {}
        for _, token in ipairs(missionTokens) do
            if token ~= displacedToken then TableInsert(replacement, token) end
        end
        TableInsert(replacement, tokens[1])
        table.sort(replacement)
        usedActors[tokens[1]] = true
        usedActors[displacedToken] = true
        controller.frontierAssignments[displacedToken] = nil
        controller.frontierAssignments[tokens[1]] = {
            engineerToken = intent.engineerToken,
            clusterKey = intent.clusterKey,
            issuedTick = tick,
        }
        existingMission.escortTokens = replacement
        Emit(controller, 'order', {
            actor = intent.engineerToken,
            command = 'frontier_screen',
            role = 'combat',
            units = 1,
        })
        return true
    end
    local clearOk = pcall(function() IssueClearCommands(actors) end)
    if not clearOk then return false end
    local guardOk = pcall(function() IssueGuard(actors, engineer) end)
    if not guardOk then
        pcall(function() IssueClearCommands(actors) end)
        return false
    end
    local tick = CurrentTick(controller)
    for _, token in ipairs(tokens) do
        usedActors[token] = true
        controller.frontierAssignments[token] = {
            engineerToken = intent.engineerToken,
            clusterKey = intent.clusterKey,
            issuedTick = tick,
        }
    end
    if existingMission then
        for _, token in ipairs(tokens) do
            TableInsert(existingMission.escortTokens, token)
        end
        table.sort(existingMission.escortTokens)
    else
        controller.frontierMission = {
            engineerToken = intent.engineerToken,
            clusterKey = intent.clusterKey,
            escortTokens = tokens,
            issuedTick = tick,
        }
    end
    Emit(controller, 'order', {
        actor = intent.engineerToken,
        command = 'frontier_screen',
        role = 'combat',
        units = TableGetn(actors),
    })
    return true
end

local function ClearFrontierMission(controller)
    local mission = controller.frontierMission
    if not mission then return true end
    local actors = {}
    for _, token in ipairs(mission.escortTokens or {}) do
        local actor = controller.unitRefs[token]
        if actor and PropAlive(actor) then TableInsert(actors, actor) end
    end
    if TableGetn(actors) > 0 then
        local ok = pcall(function() IssueClearCommands(actors) end)
        if not ok then return false end
    end
    for _, token in ipairs(mission.escortTokens or {}) do
        controller.frontierAssignments[token] = nil
    end
    controller.frontierMission = nil
    return true
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

local function StreamingCommanderCohort(controller, tokens, recordByToken, usedActors)
    local unique = {}
    local sorted = {}
    for _, token in ipairs(tokens or {}) do
        if type(token) ~= 'string' then return nil, nil end
        if not unique[token] then
            unique[token] = true
            TableInsert(sorted, token)
        end
    end
    table.sort(sorted)
    if TableGetn(sorted) == 0 then return nil, nil end

    local records = {}
    local actors = {}
    for _, token in ipairs(sorted) do
        local record = recordByToken[token]
        if not record
            or not COMBAT_ROLES[record.role]
            or record.complete ~= true
            or record.availableForWave ~= true
            or record.nearStaging ~= true
            or record.assignedToWave == true
            or usedActors[token]
            or controller.pending[token]
            or controller.waveAssignments[token]
        then
            return nil, nil
        end
        local actor, position = LiveOwnedActor(controller, token, record, record.role)
        if not actor
            or not position
            or DistanceSquared(position, controller.stagingPosition) > STAGING_RADIUS * STAGING_RADIUS
        then
            return nil, nil
        end
        TableInsert(records, record)
        TableInsert(actors, actor)
    end
    return records, actors
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
    local acuActor = LiveHealthyCommander(controller, intent.acuToken, acuRecord)
    if not acuActor then return false end
    local records, actors = StreamingCommanderCohort(
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
        local fieldOwned = CampaignFieldContains(
            controller.fieldCampaign,
            record.token
        )
        if actor
            and not fieldOwned
            and not controller.frontierAssignments[record.token]
            and (intent.kind ~= 'attack_wave' or not controller.waveAssignments[record.token])
        then
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
    for _, token in ipairs(tokens) do
        local record = recordByToken[token]
        usedActors[token] = true
        if intent.kind == 'attack_wave' then
            controller.waveAssignments[token] = {
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
    local actor = LiveOwnedActor(controller, intent.actorToken, record, 'acu')
    local position = TerrainPosition(intent.position)
    if not actor or not position then return false end
    local signature = Signature(intent)
        .. ':safety:' .. tostring(controller.safetyEpisodes.retreat)
    if OrderCoolingDown(controller, signature) then return false end
    local clearKey = 'retreat:' .. tostring(controller.safetyEpisodes.retreat)
        .. ':' .. intent.actorToken
    local preemptingOperation = controller.pending[intent.actorToken] ~= nil
    if preemptingOperation or not controller.safetyCleared[clearKey] then
        local clearOk = pcall(function() IssueClearCommands({ actor }) end)
        if not clearOk then return false end
        controller.safetyCleared[clearKey] = true
    end
    if preemptingOperation then
        ReleaseOperation(controller, intent.actorToken, 'retreat_preempted')
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

local function CampaignCombatRecords(units)
    local records = {}
    for _, record in ipairs(units or {}) do
        if COMBAT_ROLES[record.role] and record.complete == true then
            TableInsert(records, record)
        end
    end
    -- Controller.Observe has already sorted every record by stable token.
    -- Filtering that array preserves the deterministic order without a
    -- second O(n log n) campaign sort every reconciliation.
    return records
end

local function CampaignTargetCounts(records)
    local total = TableGetn(records)
    local antiAir = 0
    for _, record in ipairs(records) do
        if ESCALATION.antiAirRoles[record.role] then antiAir = antiAir + 1 end
    end
    local full = total >= FIELD_CAMPAIGN_MIN_COMBAT
        and antiAir >= FIELD_CAMPAIGN_MIN_AA
    local field = math.min(
        FIELD_CAMPAIGN_EARLY_MAX,
        math.max(0, total - HOME_RESERVE_MIN)
    )
    local fieldAntiAir = math.min(field, antiAir > 0 and 1 or 0)
    if full then
        field = math.floor(3 * total / 4)
        fieldAntiAir = math.max(1, math.min(
            math.floor(3 * antiAir / 4),
            antiAir - 1
        ))
    end
    return total, antiAir, field, fieldAntiAir, full
end

local function SelectCampaignField(records, fieldTarget, fieldAaTarget)
    local selected = {}
    local field = {}
    for _, record in ipairs(records) do
        if ESCALATION.antiAirRoles[record.role]
            and TableGetn(field) < fieldTarget
            and TableGetn(field) < fieldAaTarget
        then
            selected[record.token] = true
            TableInsert(field, record.token)
        end
    end
    for _, record in ipairs(records) do
        if TableGetn(field) < fieldTarget
            and not ESCALATION.antiAirRoles[record.role]
            and not selected[record.token]
        then
            selected[record.token] = true
            TableInsert(field, record.token)
        end
    end
    for _, record in ipairs(records) do
        if TableGetn(field) < fieldTarget and not selected[record.token] then
            selected[record.token] = true
            TableInsert(field, record.token)
        end
    end
    table.sort(field)
    return field, selected
end

local function InitialCampaignCohorts(records)
    local _, _, fieldTarget, fieldAaTarget, full = CampaignTargetCounts(records)
    local field, selected = SelectCampaignField(
        records,
        fieldTarget,
        fieldAaTarget
    )
    local home = {}
    for _, record in ipairs(records) do
        if not selected[record.token] then TableInsert(home, record.token) end
    end
    table.sort(home)
    return field, home, full
end

local function ExpandCampaignField(records, existingField, fieldTarget, fieldAaTarget)
    local field = CopyArray(existingField)
    local selected = {}
    local fieldAa = 0
    for _, token in ipairs(field) do selected[token] = true end
    for _, record in ipairs(records) do
        if selected[record.token] and ESCALATION.antiAirRoles[record.role] then
            fieldAa = fieldAa + 1
        end
    end
    for _, record in ipairs(records) do
        if TableGetn(field) < fieldTarget
            and fieldAa < fieldAaTarget
            and ESCALATION.antiAirRoles[record.role]
            and not selected[record.token]
        then
            selected[record.token] = true
            TableInsert(field, record.token)
            fieldAa = fieldAa + 1
        end
    end
    for _, record in ipairs(records) do
        if TableGetn(field) < fieldTarget
            and not ESCALATION.antiAirRoles[record.role]
            and not selected[record.token]
        then
            selected[record.token] = true
            TableInsert(field, record.token)
        end
    end
    for _, record in ipairs(records) do
        if TableGetn(field) < fieldTarget and not selected[record.token] then
            selected[record.token] = true
            TableInsert(field, record.token)
        end
    end
    local home = {}
    for _, record in ipairs(records) do
        if not selected[record.token] then TableInsert(home, record.token) end
    end
    return field, home
end

local function EmergencyCampaignCohorts(campaign, units)
    local records = CampaignCombatRecords(units)
    local _, _, fieldTarget, fieldAaTarget = CampaignTargetCounts(records)
    local currentField = {}
    for _, record in ipairs(records) do
        if CampaignFieldContains(campaign, record.token) then
            TableInsert(currentField, record)
        end
    end
    fieldTarget = math.min(fieldTarget, TableGetn(currentField))
    local field, selected = SelectCampaignField(
        currentField,
        fieldTarget,
        fieldAaTarget
    )
    local home = {}
    for _, record in ipairs(records) do
        if not selected[record.token] then TableInsert(home, record.token) end
    end
    table.sort(home)
    return field, home
end

local function CampaignSite(controller, siteKey)
    for _, site in ipairs((controller.currentSites and controller.currentSites.mass) or {}) do
        if site.key == siteKey then return site end
    end
    return nil
end

local function ScenarioUsesFixedSpawns()
    return type(ScenarioInfo) == 'table'
        and type(ScenarioInfo.Options) == 'table'
        and ScenarioInfo.Options.TeamSpawn == 'fixed'
end

local function BuildPressureGraph(controller)
    if controller.pressureGraph then return controller.pressureGraph end
    local target = CopyPosition(controller.targetPosition)
    if not IsCampaignPosition(target) then return nil end
    local geometry = {}
    for _, marker in ipairs((controller.markers and controller.markers.mass) or {}) do
        local position = CopyPosition(marker.position)
        if type(marker.key) == 'string'
            and IsCampaignPosition(position)
            and marker.engineerReachable == true
            and marker.landReachable == true
            and marker.reachable == true
        then
            TableInsert(geometry, {
                key = marker.key,
                position = position,
                targetDistanceSquared = DistanceSquared(position, target),
            })
        end
    end
    table.sort(geometry, function(a, b) return a.key < b.key end)
    local assigned = {}
    local clusters = {}
    local bySite = {}
    for _, seed in ipairs(geometry) do
        if assigned[seed.key] ~= true then
            local members = { seed }
            assigned[seed.key] = true
            local cursor = 1
            while cursor <= TableGetn(members) do
                local member = members[cursor]
                for _, candidate in ipairs(geometry) do
                    if assigned[candidate.key] ~= true
                        and DistanceSquared(member.position, candidate.position)
                            <= FRONTIER_CLUSTER_DISTANCE * FRONTIER_CLUSTER_DISTANCE
                    then
                        assigned[candidate.key] = true
                        TableInsert(members, candidate)
                    end
                end
                cursor = cursor + 1
            end
            table.sort(members, function(a, b) return a.key < b.key end)
            local anchor = members[1]
            local memberKeys = {}
            for _, member in ipairs(members) do
                TableInsert(memberKeys, member.key)
                if member.targetDistanceSquared < anchor.targetDistanceSquared
                    or (member.targetDistanceSquared == anchor.targetDistanceSquared
                        and member.key < anchor.key)
                then
                    anchor = member
                end
            end
            local cluster = {
                key = members[1].key,
                members = members,
                memberKeys = memberKeys,
                anchorKey = anchor.key,
                anchorPosition = CopyPosition(anchor.position),
                anchorTargetDistanceSquared = anchor.targetDistanceSquared,
            }
            TableInsert(clusters, cluster)
            for _, member in ipairs(members) do bySite[member.key] = cluster end
        end
    end
    table.sort(clusters, function(a, b) return a.key < b.key end)
    controller.pressureGraph = {
        clusters = clusters,
        bySite = bySite,
        targetName = tostring(controller.targetName or 'none'),
        targetPosition = target,
        targetPath = controller.targetPath == true,
        fixedSpawns = ScenarioUsesFixedSpawns(),
    }
    return controller.pressureGraph
end

local function PressureClusterForSite(controller, siteKey)
    local graph = BuildPressureGraph(controller)
    return graph and graph.bySite[siteKey] or nil
end

local function CampaignSiteSupportsPosition(controller, siteKey, position)
    if type(siteKey) ~= 'string' or not IsCampaignPosition(position) then
        return false
    end
    local site = CampaignSite(controller, siteKey)
    return site ~= nil
        and site.engineerReachable == true
        and site.landReachable == true
        and IsCampaignPosition(site.position)
        and DistanceSquared(site.position, position) <= 0.01
end

local function PressureAnchorLive(controller, anchorKey, anchorPosition)
    return CampaignSiteSupportsPosition(controller, anchorKey, anchorPosition)
end

local function CampaignOperationRecord(observation, operation)
    if not operation or type(operation.actorToken) ~= 'string' then return nil end
    for _, record in ipairs(observation.units or {}) do
        if record.token == operation.actorToken
            and (record.role == 'engineer' or record.role == 'acu')
            and record.complete == true
        then
            return record
        end
    end
    return nil
end

local function ValidCampaignOperation(controller, observation, operation)
    if not StructureOperation(operation)
        or operation.buildRole ~= 'mass_extractor'
        or (operation.reason ~= 'frontier_expansion'
            and operation.reason ~= 'rebuild_mex')
        or type(operation.siteKey) ~= 'string'
        or not IsCampaignPosition(operation.position)
        or operation.phase == 'cancelling'
        or operation.cancelReason ~= nil
        or not CampaignOperationRecord(observation, operation)
        or not CampaignSiteSupportsPosition(
            controller,
            operation.siteKey,
            operation.position
        )
    then
        return false
    end
    return true
end

local function CampaignCandidate(controller, observation)
    for _, token in ipairs(SortedKeys(controller.pending)) do
        local operation = controller.pending[token]
        if operation.reason == 'frontier_expansion'
            and ValidCampaignOperation(controller, observation, operation)
            and PressureClusterForSite(controller, operation.siteKey) ~= nil
        then
            return operation
        end
    end
    return nil
end

local function CampaignSetPending(campaign, mode, tokens)
    campaign.pendingMode = mode
    campaign.pendingTokens = CopyArray(tokens or {})
    table.sort(campaign.pendingTokens)
end

local function InitialPressureMetrics(records, field, anchor)
    local fieldSet = BuildTokenSet(field) or {}
    local distances = {}
    local atAnchor = 0
    for _, record in ipairs(records or {}) do
        if fieldSet[record.token] == true then
            local distance = Distance(record.position, anchor)
            TableInsert(distances, distance)
            if distance <= FIELD_CAMPAIGN_ANCHOR_RADIUS then
                atAnchor = atAnchor + 1
            end
        end
    end
    table.sort(distances)
    local count = TableGetn(distances)
    local quorum = count > 0 and math.ceil(count / 2) or 0
    return atAnchor, quorum, count > 0 and distances[quorum] or -1
end

local function StartFieldCampaign(controller, observation, operation)
    local cluster = PressureClusterForSite(controller, operation.siteKey)
    if not cluster then return end
    local records = CampaignCombatRecords(observation.units)
    local field, home, full = InitialCampaignCohorts(records)
    local atAnchor, quorum, forwardDistance = InitialPressureMetrics(
        records,
        field,
        cluster.anchorPosition
    )
    controller.fieldCampaignSerial = (tonumber(controller.fieldCampaignSerial) or 0) + 1
    local tick = CurrentTick(controller)
    -- Factories may still carry the legacy frontier rally ledger when the
    -- secured campaign doctrine first takes ownership.  Force one base-rally
    -- reconciliation under the new doctrine.
    controller.rallied = {}
    local campaign = {
        serial = controller.fieldCampaignSerial,
        state = full and 'awaiting_order' or 'early_awaiting_order',
        kind = 'pressure_front',
        clusterKey = cluster.key,
        memberKeys = CopyArray(cluster.memberKeys),
        anchorKey = cluster.anchorKey,
        anchorPosition = CopyPosition(cluster.anchorPosition),
        anchorTargetDistanceSquared = cluster.anchorTargetDistanceSquared,
        objectiveKey = cluster.anchorKey,
        objectivePosition = CopyPosition(cluster.anchorPosition),
        objectiveReason = 'pressure_front',
        fieldTokens = field,
        homeTokens = home,
        fieldTokenSet = BuildTokenSet(field),
        homeTokenSet = BuildTokenSet(home),
        orderedTokens = {},
        fullCohorts = full,
        startedTick = tick,
        lastProgressTick = tick,
        bestDistance = forwardDistance,
        bestAtAnchor = atAnchor,
        fieldAtAnchor = atAnchor,
        arrivalQuorum = quorum,
        forwardDistance = forwardDistance,
        progressCohortSize = TableGetn(field),
        lastRecoveryAttemptTick = tick - FIELD_CAMPAIGN_STUCK_TICKS,
        heldSinceTick = nil,
        healthySinceTick = nil,
        emergency = false,
        emergencyReason = nil,
        fullFieldOrders = 0,
        reinforcementOrders = 0,
        recoveryOrders = 0,
        recoveryWindows = 0,
        modeSwitches = 0,
        transitionEvents = 0,
        assaultEvents = 0,
        rollbackOrders = 0,
        rollbackReason = nil,
        routeAttempt = nil,
        routeRollback = nil,
        routeBlocks = {},
        routeBlockedCount = 0,
        routeProbeOrders = 0,
        routeBulkOrders = 0,
        routeReleaseOrders = 0,
        lastSecuredAnchorKey = 'home',
        lastSecuredAnchorPosition = CopyPosition(controller.basePosition),
        attritionBaseline = TableGetn(field),
        attritionWindowTick = tick,
        attritionLost = 0,
        attritionWindow = 0,
    }
    controller.fieldCampaign = campaign
    if TableGetn(field) > 0 then CampaignSetPending(campaign, 'activate', field) end
    Emit(controller, 'campaign_started', {
        cluster = campaign.clusterKey,
        objective = campaign.anchorKey,
        field_units = TableGetn(field),
        home_units = TableGetn(home),
    })
end

local function CampaignCohortsStable(
    campaign,
    records,
    fieldTarget,
    full,
    allowRecalledUpgrade
)
    local field = campaign.fieldTokens
    local home = campaign.homeTokens
    if not DenseTokenArray(field)
        or not DenseTokenArray(home)
        or not ArrayIsSorted(field)
        or not ArrayIsSorted(home)
        or not TokenSetMatches(field, campaign.fieldTokenSet)
        or not TokenSetMatches(home, campaign.homeTokenSet)
        or TableGetn(field) + TableGetn(home) ~= TableGetn(records)
    then
        return false
    end
    if full
        and campaign.fullCohorts ~= true
        and campaign.state ~= 'rebuilding'
        and (campaign.state ~= 'recalled' or allowRecalledUpgrade == true)
    then
        return false
    end
    if campaign.state == 'recalled'
        and allowRecalledUpgrade == true
        and TableGetn(field) < fieldTarget
    then
        return false
    end
    for token, _ in pairs(campaign.fieldTokenSet) do
        if campaign.homeTokenSet[token] == true then return false end
    end
    for _, record in ipairs(records) do
        local fieldMember = campaign.fieldTokenSet[record.token] == true
        local homeMember = campaign.homeTokenSet[record.token] == true
        if fieldMember == homeMember then return false end
    end
    return true
end

local function CampaignPruneAndFill(campaign, units, allowRecalledUpgrade, tick)
    local records = CampaignCombatRecords(units)
    local previousState = campaign.state
    local previousPendingMode = campaign.pendingMode
    local _, _, fieldTarget, fieldAaTarget, full = CampaignTargetCounts(records)
    if CampaignCohortsStable(
        campaign,
        records,
        fieldTarget,
        full,
        allowRecalledUpgrade
    ) then
        return
    end
    local byToken = RecordByToken(records)
    local field = {}
    local home = {}
    local assigned = {}
    for _, token in ipairs(campaign.fieldTokens or {}) do
        if byToken[token] and not assigned[token] then
            assigned[token] = true
            TableInsert(field, token)
        else
            campaign.orderedTokens[token] = nil
        end
    end
    for _, token in ipairs(campaign.homeTokens or {}) do
        if byToken[token] and not assigned[token] then
            assigned[token] = true
            TableInsert(home, token)
        end
    end
    if full
        and campaign.fullCohorts ~= true
        and campaign.state ~= 'rebuilding'
        and (campaign.state ~= 'recalled' or allowRecalledUpgrade == true)
    then
        local fieldSet = {}
        local fieldAa = 0
        for _, token in ipairs(field) do
            fieldSet[token] = true
            if ESCALATION.antiAirRoles[byToken[token].role] then
                fieldAa = fieldAa + 1
            end
        end
        for _, record in ipairs(records) do
            if TableGetn(field) < fieldTarget
                and fieldAa < fieldAaTarget
                and ESCALATION.antiAirRoles[record.role]
                and not fieldSet[record.token]
            then
                fieldSet[record.token] = true
                TableInsert(field, record.token)
                fieldAa = fieldAa + 1
            end
        end
        for _, record in ipairs(records) do
            if TableGetn(field) < fieldTarget
                and not ESCALATION.antiAirRoles[record.role]
                and not fieldSet[record.token]
            then
                fieldSet[record.token] = true
                TableInsert(field, record.token)
            end
        end
        for _, record in ipairs(records) do
            if TableGetn(field) < fieldTarget and not fieldSet[record.token] then
                fieldSet[record.token] = true
                TableInsert(field, record.token)
            end
        end
        home = {}
        assigned = {}
        for _, token in ipairs(field) do assigned[token] = true end
        for _, record in ipairs(records) do
            if not assigned[record.token] then
                assigned[record.token] = true
                TableInsert(home, record.token)
            end
        end
        campaign.fullCohorts = true
        if previousPendingMode == 'activate'
            or previousPendingMode == 'transition'
            or previousPendingMode == 'assault'
            or previousPendingMode == 'recover'
            or previousPendingMode == 'recall'
            or previousPendingMode == 'resume'
            or previousPendingMode == 'rollback'
        then
            CampaignSetPending(campaign, previousPendingMode, field)
        elseif previousState == 'awaiting_order'
            or previousState == 'early_awaiting_order'
        then
            campaign.state = 'awaiting_order'
            CampaignSetPending(campaign, 'activate', field)
        elseif previousState == 'active' then
            local unordered = {}
            for _, token in ipairs(field) do
                if campaign.orderedTokens[token] ~= true then
                    TableInsert(unordered, token)
                end
            end
            if TableGetn(unordered) > 0 then
                CampaignSetPending(campaign, 'reinforce', unordered)
            end
        end
    else
        local fieldAa = 0
        for _, token in ipairs(field) do
            if ESCALATION.antiAirRoles[byToken[token].role] then
                fieldAa = fieldAa + 1
            end
        end
        for _, record in ipairs(records) do
            if not assigned[record.token] then
                local fieldDeficit = fieldTarget - TableGetn(field)
                local homeDeficit = (TableGetn(records) - fieldTarget) - TableGetn(home)
                local chooseField = false
                if campaign.state ~= 'recalled'
                    and campaign.state ~= 'rebuilding'
                    and ESCALATION.antiAirRoles[record.role]
                    and fieldDeficit > 0
                    and fieldAa < fieldAaTarget
                then
                    chooseField = true
                elseif campaign.state ~= 'recalled'
                    and campaign.state ~= 'rebuilding'
                    and fieldDeficit > homeDeficit
                then
                    chooseField = true
                end
                if chooseField then
                    TableInsert(field, record.token)
                    if ESCALATION.antiAirRoles[record.role] then
                        fieldAa = fieldAa + 1
                    end
                else
                    TableInsert(home, record.token)
                end
                assigned[record.token] = true
            end
        end
    end
    if campaign.state == 'recalled'
        and allowRecalledUpgrade == true
        and TableGetn(field) < fieldTarget
    then
        field, home = ExpandCampaignField(
            records,
            field,
            fieldTarget,
            fieldAaTarget
        )
    end
    if not CommitCampaignCohorts(campaign, field, home) then return end
    field = campaign.fieldTokens
    home = campaign.homeTokens
    if campaign.pendingMode == 'activate'
        or campaign.pendingMode == 'transition'
        or campaign.pendingMode == 'assault'
        or campaign.pendingMode == 'recover'
        or campaign.pendingMode == 'recall'
        or campaign.pendingMode == 'resume'
        or campaign.pendingMode == 'rollback'
    then
        if campaign.pendingMode == 'rollback' and TableGetn(field) == 0 then
            campaign.state = 'rebuilding'
            campaign.rollbackReason = campaign.pendingRollbackReason or 'unknown'
            campaign.pendingRollbackReason = nil
            campaign.lastRollbackTick = tonumber(tick) or 0
            campaign.pendingMode = nil
            campaign.pendingTokens = {}
        else
            CampaignSetPending(campaign, campaign.pendingMode, field)
        end
    elseif campaign.pendingMode == 'reinforce' then
        local unordered = {}
        for _, token in ipairs(field) do
            if campaign.orderedTokens[token] ~= true then TableInsert(unordered, token) end
        end
        if TableGetn(unordered) > 0 then
            CampaignSetPending(campaign, 'reinforce', unordered)
        else
            campaign.pendingMode = nil
            campaign.pendingTokens = {}
        end
    end
end

local function ApplyCampaignFlags(controller, campaign, units)
    for _, record in ipairs(units or {}) do
        local field = CampaignFieldContains(campaign, record.token)
        local home = CampaignHomeContains(campaign, record.token)
        local waveAssignment = controller.waveAssignments[record.token]
        local frontierAssignment = controller.frontierAssignments[record.token]
        local assigned = field == true
            or waveAssignment ~= nil
            or frontierAssignment ~= nil
        record.fieldCohort = field == true
        record.homeCohort = home == true
        record.assignedToWave = assigned
        record.commanderEscort = waveAssignment
            and waveAssignment.commanderEscort == true
            or false
        record.frontierEscort = frontierAssignment ~= nil
        record.availableForWave = COMBAT_ROLES[record.role] == true
            and record.complete == true
            and not assigned
            and record.nearStaging == true
        record.campaignEngineer = campaign
            and (record.token == campaign.engineerToken
                or record.token == campaign.desiredEngineerToken)
            or false
    end
end

local function CampaignClusterComplete(controller, campaign)
    if TableGetn(campaign.memberKeys or {}) == 0 then return false end
    for _, siteKey in ipairs(campaign.memberKeys) do
        local site = CampaignSite(controller, siteKey)
        if not site or site.complete ~= true then return false end
    end
    return true
end

local function ClearDesiredCampaignObjective(campaign)
    campaign.desiredKind = nil
    campaign.desiredAnchorKey = nil
    campaign.desiredAnchorPosition = nil
    campaign.desiredAnchorTargetDistanceSquared = nil
    campaign.desiredObjectiveKey = nil
    campaign.desiredObjectivePosition = nil
    campaign.desiredObjectiveReason = nil
    campaign.desiredEngineerToken = nil
    campaign.desiredEngineerRole = nil
    campaign.desiredClusterKey = nil
    campaign.desiredMemberKeys = nil
    campaign.desiredReplacesCampaign = nil
end

-- Route probing is table-scoped to preserve LuaPlus' chunk-local headroom.
-- The campaign's committed area snapshot remains authoritative until a small,
-- fixed probe cohort has physically proven this cached Land route.
ESCALATION.RouteFinite = function(value, minimum, maximum)
    return type(value) == 'number'
        and value == value
        and math.abs(value) <= 1000000000
        and (minimum == nil or value >= minimum)
        and (maximum == nil or value <= maximum)
end

ESCALATION.RouteSnapshot = function(campaign)
    return {
        kind = campaign.kind,
        clusterKey = campaign.clusterKey,
        memberKeys = CopyArray(campaign.memberKeys),
        anchorKey = campaign.anchorKey,
        anchorPosition = CopyPosition(campaign.anchorPosition),
        anchorTargetDistanceSquared = campaign.anchorTargetDistanceSquared,
        objectiveKey = campaign.objectiveKey,
        objectivePosition = CopyPosition(campaign.objectivePosition),
        objectiveReason = campaign.objectiveReason,
        state = campaign.state,
        heldSinceTick = campaign.heldSinceTick,
        lastSecuredAnchorKey = campaign.lastSecuredAnchorKey,
        lastSecuredAnchorPosition = CopyPosition(
            campaign.lastSecuredAnchorPosition
        ),
    }
end

ESCALATION.RouteRestoreSnapshot = function(campaign, snapshot, tick)
    if type(snapshot) ~= 'table'
        or type(snapshot.kind) ~= 'string'
        or type(snapshot.clusterKey) ~= 'string'
        or type(snapshot.anchorKey) ~= 'string'
        or not IsCampaignPosition(snapshot.anchorPosition)
        or type(snapshot.memberKeys) ~= 'table'
    then
        return false
    end
    campaign.kind = snapshot.kind
    campaign.clusterKey = snapshot.clusterKey
    campaign.memberKeys = CopyArray(snapshot.memberKeys)
    campaign.anchorKey = snapshot.anchorKey
    campaign.anchorPosition = CopyPosition(snapshot.anchorPosition)
    campaign.anchorTargetDistanceSquared = snapshot.anchorTargetDistanceSquared
    campaign.objectiveKey = snapshot.objectiveKey or snapshot.anchorKey
    campaign.objectivePosition = CopyPosition(
        snapshot.objectivePosition or snapshot.anchorPosition
    )
    campaign.objectiveReason = snapshot.objectiveReason or snapshot.kind
    campaign.state = snapshot.state == 'holding' and 'holding' or 'active'
    campaign.heldSinceTick = snapshot.heldSinceTick
    campaign.lastSecuredAnchorKey = snapshot.lastSecuredAnchorKey
    campaign.lastSecuredAnchorPosition = CopyPosition(
        snapshot.lastSecuredAnchorPosition
    )
    campaign.lastProgressTick = tick
    campaign.bestDistance = 1000000000000
    campaign.bestAtAnchor = 0
    campaign.progressCohortSize = -1
    campaign.recoveryWindows = 0
    campaign.lastRecoveryAttemptTick = tick - FIELD_CAMPAIGN_STUCK_TICKS
    return true
end

ESCALATION.RouteRestoreCommittedSource = function(controller, campaign, reason)
    local rollback = campaign and campaign.routeRollback or nil
    if type(rollback) ~= 'table' and campaign then
        local release = campaign.routeAttempt
        if type(release) == 'table'
            and release.state == 'releasing'
            and release.restoreOnRelease == true
            and type(release.source) == 'table'
        then
            rollback = {
                routeKey = release.routeKey,
                source = release.source,
            }
        end
    end
    if type(rollback) ~= 'table' then
        if campaign then campaign.routeRollback = nil end
        return false
    end
    local restored = ESCALATION.RouteRestoreSnapshot(
        campaign,
        rollback.source,
        CurrentTick(controller)
    )
    campaign.routeRollback = nil
    if restored then
        Emit(controller, 'campaign_route_restored', {
            route = rollback.routeKey or 'none',
            reason = tostring(reason or 'cancelled'),
            source = campaign.anchorKey or 'none',
        })
    end
    return restored
end

ESCALATION.RouteConfirmCommittedArrival = function(controller, campaign)
    local rollback = campaign and campaign.routeRollback or nil
    local quorum = campaign and tonumber(campaign.arrivalQuorum) or 0
    local arrived = campaign and tonumber(campaign.fieldAtAnchor) or 0
    if type(rollback) ~= 'table' or quorum <= 0 or arrived < quorum then
        return false
    end
    campaign.routeRollback = nil
    Emit(controller, 'campaign_route_arrived', {
        route = rollback.routeKey or 'none',
        epoch = tonumber(rollback.epoch) or -1,
        fingerprint = rollback.routeFingerprint or 'none',
        arrived = arrived,
        quorum = quorum,
    })
    return true
end

ESCALATION.RouteBlockKey = function(sourceAnchorKey, kind, destinationKey)
    if type(sourceAnchorKey) ~= 'string'
        or type(kind) ~= 'string'
        or type(destinationKey) ~= 'string'
    then
        return nil
    end
    return sourceAnchorKey .. '>' .. kind .. ':' .. destinationKey
end

ESCALATION.RouteBlockActive = function(campaign, key, tick)
    if type(campaign.routeBlocks) ~= 'table' or type(key) ~= 'string' then
        return false
    end
    local block = campaign.routeBlocks[key]
    if type(block) ~= 'table' then return false end
    local untilTick = tonumber(block.untilTick)
    if untilTick == nil or tick >= untilTick then
        campaign.routeBlocks[key] = nil
        return false
    end
    return true
end

ESCALATION.RouteBlockedCount = function(campaign, tick)
    local count = 0
    if type(campaign.routeBlocks) ~= 'table' then return count end
    for key, _ in pairs(campaign.routeBlocks) do
        if ESCALATION.RouteBlockActive(campaign, key, tick) then
            count = count + 1
        end
    end
    return count
end

ESCALATION.RouteAddBlock = function(controller, campaign, route, reason)
    if type(route) ~= 'table' or type(route.blockKey) ~= 'string' then return end
    local tick = CurrentTick(controller)
    if type(campaign.routeBlocks) ~= 'table' then campaign.routeBlocks = {} end
    campaign.routeBlocks[route.blockKey] = {
        untilTick = tick + ESCALATION.ROUTE_BLOCK_TICKS,
        reason = tostring(reason or 'route_failed'),
    }
    campaign.routeBlockedCount = ESCALATION.RouteBlockedCount(campaign, tick)
    Emit(controller, 'campaign_route_blocked', {
        route = route.routeKey or 'none',
        epoch = tonumber(route.epoch) or -1,
        fingerprint = route.routeFingerprint or 'none',
        reason = tostring(reason or 'route_failed'),
        age = math.max(0, tick - (tonumber(route.stagedTick) or tick)),
        blocked = campaign.routeBlockedCount,
    })
end

ESCALATION.RouteBoundedInsert = function(values, value, maximum)
    local inserted = false
    for index = 1, TableGetn(values) do
        if tostring(value.token) < tostring(values[index].token) then
            table.insert(values, index, value)
            inserted = true
            break
        end
    end
    if not inserted then TableInsert(values, value) end
    if TableGetn(values) > maximum then table.remove(values) end
end

ESCALATION.RouteProbeRecords = function(controller, observation, campaign)
    local selected = {}
    local selectedSet = {}
    local bestAa = nil
    for _, record in ipairs(observation.units or {}) do
        if CampaignFieldContains(campaign, record.token)
            and COMBAT_ROLES[record.role]
            and record.complete == true
            and Distance(record.position, campaign.anchorPosition)
                <= FIELD_CAMPAIGN_ANCHOR_RADIUS
            and LiveOwnedActor(controller, record.token, record, record.role)
        then
            ESCALATION.RouteBoundedInsert(
                selected,
                record,
                ESCALATION.ROUTE_PROBE_MAX_ACTORS
            )
            if ESCALATION.antiAirRoles[record.role]
                and (not bestAa
                    or tostring(record.token) < tostring(bestAa.token))
            then
                bestAa = record
            end
        end
    end
    for _, record in ipairs(selected) do selectedSet[record.token] = true end
    if bestAa and selectedSet[bestAa.token] ~= true then
        if TableGetn(selected) >= ESCALATION.ROUTE_PROBE_MAX_ACTORS then
            selectedSet[selected[TableGetn(selected)].token] = nil
            table.remove(selected)
        end
        ESCALATION.RouteBoundedInsert(
            selected,
            bestAa,
            ESCALATION.ROUTE_PROBE_MAX_ACTORS
        )
    end
    local tokens = {}
    for _, record in ipairs(selected) do TableInsert(tokens, record.token) end
    table.sort(tokens)
    return tokens
end

ESCALATION.RouteStrategicTargetValid = function(controller)
    local graph = BuildPressureGraph(controller)
    return graph ~= nil
        and graph.fixedSpawns == true
        and ScenarioUsesFixedSpawns()
        and tonumber(controller.occupiedSpawns) == 2
        and graph.targetPath == true
        and controller.targetPath == true
        and IsCampaignPosition(graph.targetPosition)
        and IsCampaignPosition(controller.targetPosition)
        and DistanceSquared(graph.targetPosition, controller.targetPosition) <= 0.01
        and tostring(controller.targetName or 'none') == graph.targetName
end

ESCALATION.RouteCandidateLive = function(controller, route)
    if type(route) ~= 'table'
        or not IsCampaignPosition(route.candidateAnchorPosition)
    then
        return false
    end
    if route.candidateKind == 'strategic_assault' then
        local graph = BuildPressureGraph(controller)
        return ESCALATION.RouteStrategicTargetValid(controller)
            and graph ~= nil
            and route.candidateAnchorKey == 'target:' .. graph.targetName
            and route.candidateClusterKey == 'strategic_assault'
            and DistanceSquared(
                route.candidateAnchorPosition,
                graph.targetPosition
            ) <= 0.01
    end
    if route.candidateKind ~= 'pressure_front' then return false end
    local graph = BuildPressureGraph(controller)
    if not graph then return false end
    for _, cluster in ipairs(graph.clusters or {}) do
        if cluster.key == route.candidateClusterKey
            and cluster.anchorKey == route.candidateAnchorKey
            and SameArray(cluster.memberKeys, route.candidateMemberKeys)
            and DistanceSquared(
                cluster.anchorPosition,
                route.candidateAnchorPosition
            ) <= 0.01
            and PressureAnchorLive(
                controller,
                cluster.anchorKey,
                cluster.anchorPosition
            )
        then
            return true
        end
    end
    return false
end

ESCALATION.RouteSourceAuthoritative = function(campaign, route)
    local source = type(route) == 'table' and route.source or nil
    return type(source) == 'table'
        and campaign.kind == source.kind
        and campaign.clusterKey == source.clusterKey
        and campaign.anchorKey == source.anchorKey
        and SameArray(campaign.memberKeys, source.memberKeys)
        and DistanceSquared(campaign.anchorPosition, source.anchorPosition) <= 0.01
end

ESCALATION.RouteNormalizePath = function(sourcePosition, destination, path, count, length)
    if type(path) ~= 'table'
        or not ESCALATION.RouteFinite(count, 0, ESCALATION.ROUTE_PROBE_MAX_WAYPOINTS)
        or count ~= math.floor(count)
        or not ESCALATION.RouteFinite(length, 0, ESCALATION.ROUTE_PROBE_MAX_LENGTH)
    then
        return nil
    end
    local normalized = {}
    if count == 0 then
        local terminal = CopyPosition(path[0])
        if not IsCampaignPosition(terminal) then return nil end
        TableInsert(normalized, terminal)
    else
        for index = 1, count do
            local waypoint = CopyPosition(path[index])
            if not IsCampaignPosition(waypoint) then return nil end
            TableInsert(normalized, waypoint)
        end
    end
    if TableGetn(normalized) == 0
        or DistanceSquared(normalized[TableGetn(normalized)], destination) > 0.01
    then
        return nil
    end
    local previous = sourcePosition
    local actualLength = 0
    for _, waypoint in ipairs(normalized) do
        local segment = Distance(previous, waypoint)
        if not ESCALATION.RouteFinite(segment, 0, ESCALATION.ROUTE_PROBE_MAX_LENGTH)
        then
            return nil
        end
        actualLength = actualLength + segment
        previous = waypoint
    end
    if not ESCALATION.RouteFinite(
        actualLength,
        0,
        ESCALATION.ROUTE_PROBE_MAX_LENGTH
    ) then
        return nil
    end
    return normalized, actualLength
end

ESCALATION.RouteFingerprint = function(route)
    local source = type(route) == 'table' and route.source or nil
    local release = type(route) == 'table' and route.state == 'releasing'
    if type(source) ~= 'table'
        or type(source.kind) ~= 'string'
        or type(source.clusterKey) ~= 'string'
        or type(source.anchorKey) ~= 'string'
        or not DenseTokenArray(source.memberKeys)
        or not ArrayIsSorted(source.memberKeys)
        or not IsCampaignPosition(source.anchorPosition)
        or not ESCALATION.RouteFinite(
            source.anchorTargetDistanceSquared,
            0,
            1000000000000
        )
        or type(source.objectiveKey) ~= 'string'
        or not IsCampaignPosition(source.objectivePosition)
        or type(source.objectiveReason) ~= 'string'
        or (source.state ~= 'active' and source.state ~= 'holding')
        or (source.heldSinceTick ~= nil
            and not ESCALATION.RouteFinite(
                source.heldSinceTick,
                0,
                1000000000
            ))
        or type(source.lastSecuredAnchorKey) ~= 'string'
        or not IsCampaignPosition(source.lastSecuredAnchorPosition)
        or type(route.sourceAnchorKey) ~= 'string'
        or route.sourceAnchorKey ~= source.anchorKey
        or not IsCampaignPosition(route.sourcePosition)
        or type(route.candidateKind) ~= 'string'
        or type(route.candidateClusterKey) ~= 'string'
        or type(route.candidateAnchorKey) ~= 'string'
        or not DenseTokenArray(route.candidateMemberKeys)
        or not ArrayIsSorted(route.candidateMemberKeys)
        or not IsCampaignPosition(route.candidateAnchorPosition)
        or not IsCampaignPosition(route.destination)
        or not ESCALATION.RouteFinite(route.epoch, 1, 1000000000)
        or route.epoch ~= math.floor(route.epoch)
        or type(route.routeKey) ~= 'string'
        or type(route.blockKey) ~= 'string'
        or route.blockKey ~= ESCALATION.RouteBlockKey(
            route.sourceAnchorKey,
            route.candidateKind,
            route.candidateClusterKey
        )
        or route.routeKey ~= route.blockKey .. ':' .. tostring(route.epoch)
    then
        return nil
    end
    local probeSet = BuildTokenSet(route.probeTokens)
    if not probeSet
        or not ArrayIsSorted(route.probeTokens)
        or TableGetn(route.probeTokens) > ESCALATION.ROUTE_PROBE_MAX_ACTORS
    then
        return nil
    end
    local cleanupSet = nil
    if route.cleanupTokens ~= nil then
        cleanupSet = BuildTokenSet(route.cleanupTokens)
        if not cleanupSet or not ArrayIsSorted(route.cleanupTokens) then
            return nil
        end
        if not release then
            for _, token in ipairs(route.probeTokens) do
                if cleanupSet[token] ~= true then return nil end
            end
        end
    end
    if release then
        if not BuildTokenSet(route.releaseTokens)
            or not ArrayIsSorted(route.releaseTokens)
            or cleanupSet == nil
            or not SameArray(route.releaseTokens, route.cleanupTokens)
            or not ESCALATION.RouteFinite(route.releaseDeadlineTick, 0, 1000000000)
            or type(route.releaseReason) ~= 'string'
        then
            return nil
        end
    else
        if route.releaseTokens ~= nil
            or TableGetn(route.probeTokens) == 0
            or route.probeQuorum ~= math.max(
                1,
                math.ceil(TableGetn(route.probeTokens) / 2)
            )
            or type(route.waypoints) ~= 'table'
            or CountArray(route.waypoints) ~= TableGetn(route.waypoints)
            or not ESCALATION.RouteFinite(
                route.routeLength,
                0,
                ESCALATION.ROUTE_PROBE_MAX_LENGTH
            )
        then
            return nil
        end
        local _, actualLength = ESCALATION.RouteNormalizePath(
            route.sourcePosition,
            route.destination,
            route.waypoints,
            TableGetn(route.waypoints),
            route.routeLength
        )
        if not actualLength or math.abs(actualLength - route.routeLength) > 0.001 then
            return nil
        end
    end

    local hash = 216613626
    local modulus = 2147483647
    local function Mix(value)
        local encoded = tostring(value)
        for index = 1, string.len(encoded) do
            hash = hash * 131 + string.byte(encoded, index)
            hash = hash - math.floor(hash / modulus) * modulus
        end
        hash = hash * 131 + 124
        hash = hash - math.floor(hash / modulus) * modulus
    end
    local function MixPosition(position)
        Mix(position[1])
        Mix(position[2])
        Mix(position[3])
    end
    Mix(release and 'release' or 'route')
    Mix(route.epoch)
    Mix(route.routeKey)
    Mix(route.blockKey)
    Mix(source.kind)
    Mix(source.clusterKey)
    Mix(source.anchorKey)
    MixPosition(source.anchorPosition)
    Mix(source.anchorTargetDistanceSquared)
    for _, key in ipairs(source.memberKeys) do Mix(key) end
    Mix(source.objectiveKey)
    MixPosition(source.objectivePosition)
    Mix(source.objectiveReason)
    Mix(source.state)
    Mix(source.heldSinceTick == nil and 'none' or source.heldSinceTick)
    Mix(source.lastSecuredAnchorKey)
    MixPosition(source.lastSecuredAnchorPosition)
    MixPosition(route.sourcePosition)
    Mix(route.candidateKind)
    Mix(route.candidateClusterKey)
    Mix(route.candidateAnchorKey)
    MixPosition(route.candidateAnchorPosition)
    Mix(route.candidateAnchorTargetDistanceSquared)
    for _, key in ipairs(route.candidateMemberKeys) do Mix(key) end
    MixPosition(route.destination)
    for _, token in ipairs(route.probeTokens) do Mix(token) end
    Mix(cleanupSet and 'cleanup' or 'none')
    if cleanupSet then
        for _, token in ipairs(route.cleanupTokens) do Mix(token) end
    end
    if release then
        Mix(route.releaseDeadlineTick)
        Mix(route.releaseReason)
        Mix(route.restoreOnRelease == true and 'restore' or 'retain')
    else
        Mix(route.probeQuorum)
        Mix(route.routeLength)
        for _, waypoint in ipairs(route.waypoints) do MixPosition(waypoint) end
    end
    return tostring(hash)
end

ESCALATION.RoutePlan = function(controller, campaign, observation, candidate)
    local probeTokens = ESCALATION.RouteProbeRecords(
        controller,
        observation,
        campaign
    )
    if TableGetn(probeTokens) == 0 then return nil, 'no_probe_actor' end
    local sourcePosition = TerrainPosition(campaign.anchorPosition)
    local destination = TerrainPosition(candidate.anchorPosition)
    if not IsCampaignPosition(sourcePosition)
        or not IsCampaignPosition(destination)
    then
        return nil, 'invalid_endpoint'
    end
    local sourceLabelOk, sourceLabel = pcall(function()
        return NavUtils.GetLabel('Land', sourcePosition)
    end)
    local destinationLabelOk, destinationLabel = pcall(function()
        return NavUtils.GetLabel('Land', destination)
    end)
    if not sourceLabelOk
        or not destinationLabelOk
        or not ESCALATION.RouteFinite(sourceLabel, 1, 1000000000)
        or not ESCALATION.RouteFinite(destinationLabel, 1, 1000000000)
        or sourceLabel ~= destinationLabel
    then
        return nil, 'invalid_label'
    end
    local canPathOk, canPath = pcall(function()
        return NavUtils.CanPathTo('Land', sourcePosition, destination)
    end)
    if not canPathOk or canPath ~= true then return nil, 'unpathable' end
    local pathOk, path, count, length = pcall(function()
        return NavUtils.PathTo('Land', sourcePosition, destination)
    end)
    if not pathOk then return nil, 'path_error' end
    local waypoints, actualLength = ESCALATION.RouteNormalizePath(
        sourcePosition,
        destination,
        path,
        count,
        length
    )
    if not waypoints then return nil, 'invalid_path' end
    local source = ESCALATION.RouteSnapshot(campaign)
    local blockKey = ESCALATION.RouteBlockKey(
        source.anchorKey,
        candidate.kind,
        candidate.clusterKey
    )
    if not blockKey then return nil, 'invalid_key' end
    controller.routeAttemptSerial = (tonumber(controller.routeAttemptSerial) or 0) + 1
    local tick = CurrentTick(controller)
    local route = {
        state = 'staged',
        epoch = controller.routeAttemptSerial,
        routeKey = blockKey .. ':' .. tostring(controller.routeAttemptSerial),
        blockKey = blockKey,
        source = source,
        sourceAnchorKey = source.anchorKey,
        sourcePosition = sourcePosition,
        candidateKind = candidate.kind,
        candidateClusterKey = candidate.clusterKey,
        candidateMemberKeys = CopyArray(candidate.memberKeys or {}),
        candidateAnchorKey = candidate.anchorKey,
        candidateAnchorPosition = CopyPosition(candidate.anchorPosition),
        candidateAnchorTargetDistanceSquared = candidate.anchorTargetDistanceSquared,
        destination = destination,
        waypoints = waypoints,
        routeLength = actualLength,
        probeTokens = probeTokens,
        probeQuorum = math.max(1, math.ceil(TableGetn(probeTokens) / 2)),
        atDestination = 0,
        stagedTick = tick,
        lastProgressTick = tick,
        bestDistance = 1000000000000,
        releaseDeadlineTick = tick + ESCALATION.ROUTE_PROBE_RELEASE_TICKS,
    }
    route.routeFingerprint = ESCALATION.RouteFingerprint(route)
    if not route.routeFingerprint then return nil, 'invalid_route' end
    return route, nil
end

ESCALATION.RouteStage = function(controller, observation, campaign, candidate)
    local blockKey = ESCALATION.RouteBlockKey(
        campaign.anchorKey,
        candidate.kind,
        candidate.clusterKey
    )
    local tick = CurrentTick(controller)
    if not blockKey
        or ESCALATION.RouteBlockActive(campaign, blockKey, tick)
    then
        return false
    end
    local route, reason = ESCALATION.RoutePlan(
        controller,
        campaign,
        observation,
        candidate
    )
    if not route then
        if reason ~= 'no_probe_actor' then
            ESCALATION.RouteAddBlock(controller, campaign, {
                blockKey = blockKey,
                routeKey = blockKey,
            }, reason)
        end
        return false
    end
    controller.routeCleanupOwnership = nil
    campaign.routeAttempt = route
    if route.candidateKind == 'pressure_front' then
        campaign.desiredKind = route.candidateKind
        campaign.desiredClusterKey = route.candidateClusterKey
        campaign.desiredMemberKeys = CopyArray(route.candidateMemberKeys)
        campaign.desiredAnchorKey = route.candidateAnchorKey
        campaign.desiredAnchorPosition = CopyPosition(route.candidateAnchorPosition)
        campaign.desiredAnchorTargetDistanceSquared =
            route.candidateAnchorTargetDistanceSquared
    else
        campaign.desiredKind = 'strategic_assault'
        campaign.desiredClusterKey = 'strategic_assault'
        campaign.desiredMemberKeys = {}
        campaign.desiredAnchorKey = route.candidateAnchorKey
        campaign.desiredAnchorPosition = CopyPosition(route.candidateAnchorPosition)
        campaign.desiredAnchorTargetDistanceSquared = 0
    end
    CampaignSetPending(campaign, 'route_probe', route.probeTokens)
    Emit(controller, 'campaign_route_staged', {
        route = route.routeKey,
        epoch = route.epoch,
        fingerprint = route.routeFingerprint,
        source = route.sourceAnchorKey,
        destination = route.candidateAnchorKey,
        waypoints = TableGetn(route.waypoints or {}),
        route_length = tonumber(route.routeLength) or -1,
        units = TableGetn(route.probeTokens),
        quorum = route.probeQuorum,
    })
    return true
end

ESCALATION.RouteLiveRecords = function(controller, observation, tokens)
    local byToken = RecordByToken(observation.units)
    local live = {}
    for _, token in ipairs(tokens or {}) do
        local record = byToken[token]
        if record
            and COMBAT_ROLES[record.role]
            and record.complete == true
            and LiveOwnedActor(controller, token, record, record.role)
        then
            live[token] = record
        end
    end
    return live
end

ESCALATION.RouteProbeMetrics = function(controller, observation, route)
    local live = ESCALATION.RouteLiveRecords(
        controller,
        observation,
        route.probeTokens
    )
    local distances = {}
    local atDestination = 0
    local liveCount = 0
    for _, token in ipairs(route.probeTokens or {}) do
        local record = live[token]
        if record then
            local actor = LiveOwnedActor(
                controller,
                token,
                record,
                record.role
            )
            local position = actor
                and CopyPosition(SafeCall(nil, actor.GetPosition, actor))
                or nil
            if position then
                liveCount = liveCount + 1
                local distance = Distance(position, route.destination)
                TableInsert(distances, distance)
                if distance <= FIELD_CAMPAIGN_ANCHOR_RADIUS then
                    atDestination = atDestination + 1
                end
            end
        end
    end
    table.sort(distances)
    local distance = TableGetn(distances) >= route.probeQuorum
        and distances[route.probeQuorum]
        or 1000000000000
    return live, liveCount, atDestination, distance
end

ESCALATION.RouteClear = function(campaign)
    campaign.routeAttempt = nil
    campaign.pendingMode = nil
    campaign.pendingTokens = {}
    ClearDesiredCampaignObjective(campaign)
end

ESCALATION.RouteBeginRelease = function(
    controller,
    campaign,
    route,
    reason,
    shouldBlock
)
    local tick = CurrentTick(controller)
    local wasReleasing = route.state == 'releasing'
    local ownership = controller.routeCleanupOwnership
    local routeOwnershipValid = false
    if not wasReleasing
        and DenseTokenArray(route.cleanupTokens)
        and ArrayIsSorted(route.cleanupTokens)
    then
        local candidate = {}
        for key, value in pairs(route) do candidate[key] = value end
        candidate.releaseTokens = nil
        routeOwnershipValid = ESCALATION.RouteFingerprint(candidate)
            == route.routeFingerprint
    end
    local recoveryOwnershipValid = type(ownership) == 'table'
        and ownership.routeKey == route.routeKey
        and ownership.epoch == route.epoch
        and DenseTokenArray(ownership.tokens)
        and ArrayIsSorted(ownership.tokens)
        and ownership.routeFingerprint == route.routeFingerprint
    if recoveryOwnershipValid and not wasReleasing then
        local candidate = {}
        for key, value in pairs(route) do candidate[key] = value end
        candidate.cleanupTokens = CopyArray(ownership.tokens)
        candidate.releaseTokens = nil
        recoveryOwnershipValid = ESCALATION.RouteFingerprint(candidate)
            == route.routeFingerprint
    end
    local releaseTokens = nil
    if routeOwnershipValid then
        releaseTokens = CopyArray(route.cleanupTokens)
    elseif recoveryOwnershipValid then
        releaseTokens = CopyArray(ownership.tokens)
    elseif wasReleasing
        and type(route.releaseTokens) == 'table'
        and DenseTokenArray(route.releaseTokens)
        and ArrayIsSorted(route.releaseTokens)
    then
        releaseTokens = CopyArray(route.releaseTokens)
    else
        releaseTokens = CopyArray(route.probeTokens)
    end
    route.state = 'releasing'
    route.bulkTokens = nil
    route.releaseReason = tostring(reason or 'route_failed')
    route.releaseStartedTick = route.releaseStartedTick or tick
    route.releaseDeadlineTick = math.min(
        tonumber(route.releaseDeadlineTick)
            or (tick + ESCALATION.ROUTE_PROBE_STUCK_TICKS),
        tick + ESCALATION.ROUTE_PROBE_STUCK_TICKS
    )
    route.blockOnRelease = shouldBlock == true
        and not routeOwnershipValid
        and not recoveryOwnershipValid
    if route.blockOnRelease then
        ESCALATION.RouteAddBlock(controller, campaign, route, route.releaseReason)
    end
    route.cleanupTokens = CopyArray(releaseTokens)
    route.releaseTokens = releaseTokens
    route.routeFingerprint = ESCALATION.RouteFingerprint(route) or 'invalid'
    campaign.routeAttempt = route
    if TableGetn(releaseTokens) > 0 then
        CampaignSetPending(campaign, 'route_release', releaseTokens)
    else
        campaign.pendingMode = nil
        campaign.pendingTokens = {}
    end
    Emit(controller, 'campaign_route_releasing', {
        route = route.routeKey or 'none',
        epoch = tonumber(route.epoch) or -1,
        fingerprint = route.routeFingerprint or 'none',
        reason = route.releaseReason,
        age = math.max(0, tick - (tonumber(route.stagedTick) or tick)),
        release_age = math.max(
            0,
            tick - (tonumber(route.releaseStartedTick) or tick)
        ),
        units = TableGetn(releaseTokens),
    })
end

ESCALATION.RouteFinalizeRelease = function(controller, campaign, route, reason)
    local tick = CurrentTick(controller)
    if route.restoreOnRelease == true then
        ESCALATION.RouteRestoreSnapshot(campaign, route.source, tick)
    end
    campaign.routeReleaseOrders = (tonumber(campaign.routeReleaseOrders) or 0) + 1
    local ownership = controller.routeCleanupOwnership
    if type(ownership) == 'table'
        and ownership.routeKey == route.routeKey
        and ownership.epoch == route.epoch
    then
        controller.routeCleanupOwnership = nil
    end
    ESCALATION.RouteClear(campaign)
    Emit(controller, 'campaign_route_released', {
        route = route.routeKey or 'none',
        epoch = tonumber(route.epoch) or -1,
        fingerprint = route.routeFingerprint or 'none',
        reason = tostring(reason or route.releaseReason or 'released'),
        age = math.max(0, tick - (tonumber(route.stagedTick) or tick)),
        release_age = math.max(
            0,
            tick - (tonumber(route.releaseStartedTick) or tick)
        ),
    })
end

ESCALATION.RouteCandidateFromCluster = function(cluster)
    return {
        kind = 'pressure_front',
        clusterKey = cluster.key,
        memberKeys = CopyArray(cluster.memberKeys),
        anchorKey = cluster.anchorKey,
        anchorPosition = CopyPosition(cluster.anchorPosition),
        anchorTargetDistanceSquared = cluster.anchorTargetDistanceSquared,
    }
end

ESCALATION.RouteAssaultCandidate = function(controller)
    if not ESCALATION.RouteStrategicTargetValid(controller) then return nil end
    local graph = BuildPressureGraph(controller)
    return {
        kind = 'strategic_assault',
        clusterKey = 'strategic_assault',
        memberKeys = {},
        anchorKey = 'target:' .. graph.targetName,
        anchorPosition = CopyPosition(graph.targetPosition),
        anchorTargetDistanceSquared = 0,
    }
end

local function QuickSelect(values, wanted)
    local left = 1
    local right = TableGetn(values)
    while left < right do
        local pivot = values[math.floor((left + right) / 2)]
        local low = left
        local high = right
        repeat
            while values[low] < pivot do low = low + 1 end
            while values[high] > pivot do high = high - 1 end
            if low <= high then
                values[low], values[high] = values[high], values[low]
                low = low + 1
                high = high - 1
            end
        until low > high
        if wanted <= high then
            right = high
        elseif wanted >= low then
            left = low
        else
            return values[wanted]
        end
    end
    return values[wanted]
end

local function UpdatePressureProgress(controller, observation, campaign)
    local distances = {}
    local atAnchor = 0
    local anchor = campaign.anchorPosition
    for _, record in ipairs(observation.units or {}) do
        if CampaignFieldContains(campaign, record.token)
            and COMBAT_ROLES[record.role]
            and record.complete == true
        then
            local distance = Distance(record.position, anchor)
            TableInsert(distances, distance)
            if distance <= FIELD_CAMPAIGN_ANCHOR_RADIUS then
                atAnchor = atAnchor + 1
            end
        end
    end
    local count = TableGetn(distances)
    local quorum = count > 0 and math.ceil(count / 2) or 0
    local forwardDistance = count > 0 and QuickSelect(distances, quorum) or -1
    campaign.fieldAtAnchor = atAnchor
    campaign.arrivalQuorum = quorum
    campaign.forwardDistance = forwardDistance
    local tick = CurrentTick(controller)
    if campaign.progressCohortSize ~= count then
        campaign.progressCohortSize = count
        campaign.bestDistance = forwardDistance
        campaign.bestAtAnchor = atAnchor
    elseif forwardDistance >= 0
        and forwardDistance + 2 < (tonumber(campaign.bestDistance)
            or 1000000000000)
    then
        campaign.bestAtAnchor = math.max(
            atAnchor,
            tonumber(campaign.bestAtAnchor) or 0
        )
        campaign.bestDistance = forwardDistance
        campaign.lastProgressTick = tick
    end
end

local function PressureClusterUnowned(controller, cluster)
    for _, siteKey in ipairs(cluster.memberKeys or {}) do
        local site = CampaignSite(controller, siteKey)
        if not site or site.complete ~= true then return true end
    end
    return false
end

local function PressureClusterIntersects(cluster, memberSet)
    for _, siteKey in ipairs(cluster.memberKeys or {}) do
        if memberSet[siteKey] == true then return true end
    end
    return false
end

local function NextPressureCluster(controller, campaign)
    local graph = BuildPressureGraph(controller)
    if not graph then return nil end
    local currentMembers = {}
    for _, siteKey in ipairs(campaign.memberKeys or {}) do
        currentMembers[siteKey] = true
    end
    local best = nil
    local bestDistance = 1000000000000
    local tick = CurrentTick(controller)
    for _, cluster in ipairs(graph.clusters or {}) do
        local blockKey = ESCALATION.RouteBlockKey(
            campaign.anchorKey,
            'pressure_front',
            cluster.key
        )
        if not ESCALATION.RouteBlockActive(campaign, blockKey, tick)
            and not PressureClusterIntersects(cluster, currentMembers)
            and cluster.anchorTargetDistanceSquared
                < (tonumber(campaign.anchorTargetDistanceSquared)
                    or 1000000000000)
            and PressureClusterUnowned(controller, cluster)
            and PressureAnchorLive(
                controller,
                cluster.anchorKey,
                cluster.anchorPosition
            )
        then
            local distance = DistanceSquared(
                campaign.anchorPosition,
                cluster.anchorPosition
            )
            if not best
                or distance < bestDistance
                or (distance == bestDistance
                    and (cluster.anchorTargetDistanceSquared
                            < best.anchorTargetDistanceSquared
                        or (cluster.anchorTargetDistanceSquared
                                == best.anchorTargetDistanceSquared
                            and cluster.key < best.key)))
            then
                best = cluster
                bestDistance = distance
            end
        end
    end
    return best
end

local function StrategicTargetValid(controller)
    local graph = BuildPressureGraph(controller)
    return graph ~= nil
        and graph.fixedSpawns == true
        and ScenarioUsesFixedSpawns()
        and tonumber(controller.occupiedSpawns) == 2
        and graph.targetPath == true
        and controller.targetPath == true
        and IsCampaignPosition(graph.targetPosition)
        and IsCampaignPosition(controller.targetPosition)
        and DistanceSquared(graph.targetPosition, controller.targetPosition) <= 0.01
        and tostring(controller.targetName or 'none') == graph.targetName
end

local function StagePressureCluster(campaign, cluster)
    campaign.desiredKind = 'pressure_front'
    campaign.desiredClusterKey = cluster.key
    campaign.desiredMemberKeys = CopyArray(cluster.memberKeys)
    campaign.desiredAnchorKey = cluster.anchorKey
    campaign.desiredAnchorPosition = CopyPosition(cluster.anchorPosition)
    campaign.desiredAnchorTargetDistanceSquared = cluster.anchorTargetDistanceSquared
    campaign.desiredObjectiveKey = cluster.anchorKey
    campaign.desiredObjectivePosition = CopyPosition(cluster.anchorPosition)
    campaign.desiredObjectiveReason = 'pressure_front'
end

local function StageStrategicAssault(controller, campaign)
    if not StrategicTargetValid(controller) then return false end
    local graph = BuildPressureGraph(controller)
    campaign.desiredKind = 'strategic_assault'
    campaign.desiredClusterKey = 'strategic_assault'
    campaign.desiredMemberKeys = {}
    campaign.desiredAnchorKey = 'target:' .. graph.targetName
    campaign.desiredAnchorPosition = CopyPosition(graph.targetPosition)
    campaign.desiredAnchorTargetDistanceSquared = 0
    campaign.desiredObjectiveKey = campaign.desiredAnchorKey
    campaign.desiredObjectivePosition = CopyPosition(graph.targetPosition)
    campaign.desiredObjectiveReason = 'strategic_assault'
    return true
end

ESCALATION.RouteBulkTokens = function(controller, observation, campaign, route)
    local probeSet = BuildTokenSet(route.probeTokens) or {}
    local tokens = {}
    for _, record in ipairs(observation.units or {}) do
        if CampaignFieldContains(campaign, record.token)
            and probeSet[record.token] ~= true
            and COMBAT_ROLES[record.role]
            and record.complete == true
            and LiveOwnedActor(controller, record.token, record, record.role)
        then
            TableInsert(tokens, record.token)
        end
    end
    table.sort(tokens)
    return tokens
end

ESCALATION.RouteUpdate = function(controller, observation, campaign, readinessReady)
    local route = campaign.routeAttempt
    local tick = CurrentTick(controller)
    campaign.routeBlockedCount = ESCALATION.RouteBlockedCount(campaign, tick)
    if route ~= nil and type(route) ~= 'table' then
        ESCALATION.RouteClear(campaign)
        return true
    end
    if type(route) == 'table' then
        local fingerprint = ESCALATION.RouteFingerprint(route)
        if fingerprint == nil or fingerprint ~= route.routeFingerprint then
            if route.state == 'staged' then
                ESCALATION.RouteAddBlock(
                    controller,
                    campaign,
                    route,
                    'route_corrupt'
                )
                ESCALATION.RouteClear(campaign)
                return false
            elseif route.state == 'probing' or route.state == 'proven' then
                ESCALATION.RouteBeginRelease(
                    controller,
                    campaign,
                    route,
                    'route_corrupt',
                    true
                )
                return true
            elseif route.state == 'releasing' then
                campaign.pendingMode = nil
                campaign.pendingTokens = {}
                if tick >= (tonumber(route.releaseDeadlineTick) or tick) then
                    ESCALATION.RouteFinalizeRelease(
                        controller,
                        campaign,
                        route,
                        'release_deadline'
                    )
                end
                return true
            end
            ESCALATION.RouteClear(campaign)
            return true
        end
        if readinessReady ~= true and route.state ~= 'releasing' then
            if route.state == 'staged' then
                ESCALATION.RouteClear(campaign)
            else
                ESCALATION.RouteBeginRelease(
                    controller,
                    campaign,
                    route,
                    'readiness_lost',
                    false
                )
            end
            return true
        end
        if route.state ~= 'releasing'
            and (not ESCALATION.RouteSourceAuthoritative(campaign, route)
                or not ESCALATION.RouteCandidateLive(controller, route))
        then
            if route.state == 'staged' then
                ESCALATION.RouteAddBlock(
                    controller,
                    campaign,
                    route,
                    'objective_invalid'
                )
                ESCALATION.RouteClear(campaign)
                -- No probe actor was ordered, so the old snapshot needs no
                -- cleanup.  Let this reconcile choose a different unblocked
                -- forward component instead of burning an extra planner tick.
                return false
            else
                ESCALATION.RouteBeginRelease(
                    controller,
                    campaign,
                    route,
                    'objective_invalid',
                    true
                )
            end
            return true
        end
        if route.state == 'staged' then
            local dispatchStart = tonumber(route.dispatchFailureTick)
                or tonumber(route.stagedTick)
                or tick
            if tick - dispatchStart >= ESCALATION.ROUTE_PROBE_STUCK_TICKS then
                ESCALATION.RouteBeginRelease(
                    controller,
                    campaign,
                    route,
                    'probe_dispatch_stuck',
                    false
                )
                return true
            end
            local live = ESCALATION.RouteLiveRecords(
                controller,
                observation,
                route.probeTokens
            )
            for _, token in ipairs(route.probeTokens or {}) do
                local record = live[token]
                if not record
                    or not CampaignFieldContains(campaign, token)
                    or Distance(record.position, route.source.anchorPosition)
                        > FIELD_CAMPAIGN_ANCHOR_RADIUS
                then
                    ESCALATION.RouteClear(campaign)
                    return true
                end
            end
            CampaignSetPending(campaign, 'route_probe', route.probeTokens)
            return true
        end
        if route.state == 'probing' or route.state == 'proven' then
            local _, liveCount, atDestination, distance =
                ESCALATION.RouteProbeMetrics(controller, observation, route)
            route.atDestination = atDestination
            if liveCount < route.probeQuorum then
                ESCALATION.RouteBeginRelease(
                    controller,
                    campaign,
                    route,
                    'probe_attrition',
                    false
                )
                return true
            end
            if distance + 2 < (tonumber(route.bestDistance) or 1000000000000)
            then
                route.bestDistance = distance
                route.lastProgressTick = tick
            end
            if atDestination >= route.probeQuorum then
                route.state = 'proven'
                route.provenTick = route.provenTick or tick
                local dispatchStart = tonumber(route.dispatchFailureTick)
                    or tonumber(route.provenTick)
                    or tick
                if tick - dispatchStart >= ESCALATION.ROUTE_PROBE_STUCK_TICKS then
                    ESCALATION.RouteBeginRelease(
                        controller,
                        campaign,
                        route,
                        'bulk_dispatch_stuck',
                        false
                    )
                    return true
                end
                route.bulkTokens = ESCALATION.RouteBulkTokens(
                    controller,
                    observation,
                    campaign,
                    route
                )
                if TableGetn(route.bulkTokens) > 0 then
                    CampaignSetPending(campaign, 'route_commit', route.bulkTokens)
                else
                    campaign.pendingMode = nil
                    campaign.pendingTokens = {}
                end
                if route.provenEvent ~= true then
                    route.provenEvent = true
                    Emit(controller, 'campaign_route_proven', {
                        route = route.routeKey,
                        epoch = route.epoch,
                        fingerprint = route.routeFingerprint,
                        source = route.sourceAnchorKey,
                        destination = route.candidateAnchorKey,
                        waypoints = TableGetn(route.waypoints or {}),
                        route_length = tonumber(route.routeLength) or -1,
                        arrived = atDestination,
                        quorum = route.probeQuorum,
                    })
                end
                return true
            end
            route.state = 'probing'
            campaign.pendingMode = nil
            campaign.pendingTokens = {}
            if tick - (tonumber(route.lastProgressTick) or tick)
                >= ESCALATION.ROUTE_PROBE_STUCK_TICKS
            then
                ESCALATION.RouteBeginRelease(
                    controller,
                    campaign,
                    route,
                    'probe_stuck',
                    true
                )
            end
            return true
        end
        if route.state == 'releasing' then
            local live = ESCALATION.RouteLiveRecords(
                controller,
                observation,
                route.releaseTokens
            )
            local releaseTokens = {}
            for _, token in ipairs(route.releaseTokens or {}) do
                if live[token] then TableInsert(releaseTokens, token) end
            end
            route.cleanupTokens = CopyArray(releaseTokens)
            route.releaseTokens = releaseTokens
            local ownership = controller.routeCleanupOwnership
            if type(ownership) == 'table'
                and ownership.routeKey == route.routeKey
                and ownership.epoch == route.epoch
            then
                ownership.tokens = CopyArray(releaseTokens)
            end
            route.routeFingerprint = ESCALATION.RouteFingerprint(route)
                or 'invalid'
            if type(ownership) == 'table'
                and ownership.routeKey == route.routeKey
                and ownership.epoch == route.epoch
            then
                ownership.routeFingerprint = route.routeFingerprint
            end
            if tick >= (tonumber(route.releaseDeadlineTick) or tick)
                or TableGetn(releaseTokens) == 0
            then
                ESCALATION.RouteFinalizeRelease(
                    controller,
                    campaign,
                    route,
                    'release_deadline'
                )
            else
                CampaignSetPending(campaign, 'route_release', releaseTokens)
            end
            return true
        end
        ESCALATION.RouteClear(campaign)
        return true
    end

    local rollback = campaign.routeRollback
    if type(rollback) == 'table' then
        if not ESCALATION.RouteConfirmCommittedArrival(controller, campaign)
            and tick - (tonumber(campaign.lastProgressTick)
                or tonumber(rollback.committedTick)
                or tick) >= ESCALATION.ROUTE_PROBE_STUCK_TICKS
        then
            local release = {
                state = 'releasing',
                epoch = rollback.epoch,
                routeKey = rollback.routeKey,
                routeFingerprint = rollback.routeFingerprint,
                blockKey = rollback.blockKey,
                source = rollback.source,
                sourceAnchorKey = rollback.source.anchorKey,
                sourcePosition = CopyPosition(
                    rollback.sourcePosition or rollback.source.anchorPosition
                ),
                candidateKind = campaign.kind,
                candidateClusterKey = campaign.clusterKey,
                candidateMemberKeys = CopyArray(campaign.memberKeys),
                candidateAnchorKey = campaign.anchorKey,
                candidateAnchorPosition = CopyPosition(campaign.anchorPosition),
                candidateAnchorTargetDistanceSquared =
                    campaign.anchorTargetDistanceSquared,
                destination = CopyPosition(campaign.anchorPosition),
                probeTokens = {},
                probeQuorum = 0,
                releaseTokens = CopyArray(campaign.fieldTokens),
                restoreOnRelease = true,
                stagedTick = rollback.committedTick,
                releaseDeadlineTick = (tonumber(rollback.committedTick) or tick)
                    + ESCALATION.ROUTE_PROBE_RELEASE_TICKS,
            }
            campaign.routeRollback = nil
            campaign.routeAttempt = release
            ESCALATION.RouteBeginRelease(
                controller,
                campaign,
                release,
                'bulk_stuck',
                true
            )
            return true
        end
    elseif rollback ~= nil then
        campaign.routeRollback = nil
    end
    return false
end

local function CampaignAcuHealth(observation)
    for _, record in ipairs(observation.units or {}) do
        if record.role == 'acu' and record.complete == true then
            return tonumber(record.healthRatio)
        end
    end
    return nil
end

local function UpdateFieldCampaign(controller, observation)
    if controller.fieldCampaignEnabled ~= true then
        ApplyCampaignFlags(controller, nil, observation.units)
        return
    end
    local campaign = controller.fieldCampaign
    if not campaign then
        local candidate = CampaignCandidate(controller, observation)
        if candidate
            and observation.macro
            and observation.macro.campaignReady == true
        then
            StartFieldCampaign(controller, observation, candidate)
        end
        campaign = controller.fieldCampaign
        ApplyCampaignFlags(controller, campaign, observation.units)
        return
    end

    local tick = CurrentTick(controller)
    local health = CampaignAcuHealth(observation)
    local immediateContact = observation.enemyContact ~= nil
        and observation.enemyContact.immediate == true
    local observedByToken = RecordByToken(observation.units)
    local liveBeforePrune = 0
    for _, token in ipairs(campaign.fieldTokens or {}) do
        local record = observedByToken[token]
        if record and record.complete == true and COMBAT_ROLES[record.role] then
            liveBeforePrune = liveBeforePrune + 1
        end
    end
    local attritionBaseline = math.max(
        0,
        tonumber(campaign.attritionBaseline) or liveBeforePrune
    )
    local attritionStart = tonumber(campaign.attritionWindowTick) or tick
    if tick - attritionStart > ESCALATION.CAMPAIGN_ATTRITION_TICKS then
        campaign.attritionBaseline = liveBeforePrune
        campaign.attritionWindowTick = tick
        campaign.attritionLost = 0
        campaign.attritionWindow = 0
        attritionBaseline = liveBeforePrune
    else
        campaign.attritionLost = math.max(0, attritionBaseline - liveBeforePrune)
        campaign.attritionWindow = tick - attritionStart
    end
    CampaignPruneAndFill(campaign, observation.units, false, tick)
    if campaign.pendingMode == 'recall' then
        if campaign.pendingEmergencyReason == 'home_reserve' then
            local emergencyField, emergencyHome = EmergencyCampaignCohorts(
                campaign,
                observation.units
            )
            campaign.pendingRecallFieldTokens = emergencyField
            campaign.pendingRecallHomeTokens = emergencyHome
        end
        CampaignSetPending(campaign, 'recall', campaign.fieldTokens)
        ApplyCampaignFlags(controller, campaign, observation.units)
        return
    end
    local reserveSafe = observation.enemyContact == nil
        and TableGetn(campaign.homeTokens) >= HOME_RESERVE_MIN
    local allowRecalledUpgrade = campaign.state == 'recalled'
        and observation.macro
        and observation.macro.campaignReady == true
        and health ~= nil
        and health >= FIELD_CAMPAIGN_RESUME_HEALTH
        and reserveSafe
        and campaign.healthySinceTick ~= nil
        and tick - campaign.healthySinceTick >= FIELD_CAMPAIGN_RESUME_TICKS
    if allowRecalledUpgrade then
        CampaignPruneAndFill(campaign, observation.units, true, tick)
    end
    ApplyCampaignFlags(controller, campaign, observation.units)
    UpdatePressureProgress(controller, observation, campaign)
    ESCALATION.RouteConfirmCommittedArrival(controller, campaign)
    local liveField = TableGetn(campaign.fieldTokens or {})
    local readinessReady = observation.macro
        and observation.macro.campaignReady == true
    if immediateContact
        and TableGetn(campaign.homeTokens) < HOME_RESERVE_MIN
        and TableGetn(campaign.fieldTokens) > 0
    then
        ESCALATION.RouteRestoreCommittedSource(
            controller,
            campaign,
            'home_reserve'
        )
        if campaign.routeAttempt ~= nil then ESCALATION.RouteClear(campaign) end
        ClearDesiredCampaignObjective(campaign)
        campaign.pendingRollbackReason = nil
        local emergencyField, emergencyHome = EmergencyCampaignCohorts(
            campaign,
            observation.units
        )
        campaign.pendingEmergencyReason = 'home_reserve'
        campaign.pendingRecallFieldTokens = emergencyField
        campaign.pendingRecallHomeTokens = emergencyHome
        CampaignSetPending(campaign, 'recall', campaign.fieldTokens)
        return
    end
    if campaign.state ~= 'recalled'
        and health and health < FIELD_CAMPAIGN_RECALL_HEALTH
        and TableGetn(campaign.fieldTokens) > 0
    then
        ESCALATION.RouteRestoreCommittedSource(
            controller,
            campaign,
            'acu_health'
        )
        if campaign.routeAttempt ~= nil then ESCALATION.RouteClear(campaign) end
        ClearDesiredCampaignObjective(campaign)
        campaign.pendingRollbackReason = nil
        campaign.pendingEmergencyReason = 'acu_health'
        campaign.pendingRecallFieldTokens = nil
        campaign.pendingRecallHomeTokens = nil
        CampaignSetPending(campaign, 'recall', campaign.fieldTokens)
        return
    end
    if not readinessReady
        and (campaign.state == 'awaiting_order'
            or campaign.state == 'early_awaiting_order')
    then
        campaign.pendingMode = nil
        campaign.pendingTokens = {}
        return
    end
    local rollbackReason = nil
    if (campaign.state == 'active' or campaign.state == 'holding')
        and attritionBaseline > 0
        and campaign.attritionLost * 4 >= attritionBaseline
    then
        rollbackReason = 'field_attrition'
    end
    if campaign.state == 'rebuilding' then
        if campaign.pendingMode == 'rollback' then return end
        if campaign.pendingMode == 'resume' and not readinessReady then
            campaign.pendingMode = nil
            campaign.pendingTokens = {}
            campaign.pendingResumeFieldTokens = nil
            campaign.pendingResumeHomeTokens = nil
            campaign.pendingResumeFull = nil
        end
        local rollbackCooldownReady = campaign.lastRollbackTick == nil
            or tick - (tonumber(campaign.lastRollbackTick) or tick)
                >= ESCALATION.CAMPAIGN_ROLLBACK_COOLDOWN_TICKS
        local canResume = readinessReady
            and rollbackCooldownReady
            and ((campaign.rollbackReason == 'field_attrition'
                    and liveField >= attritionBaseline)
                or (campaign.rollbackReason == 'repeated_no_progress'
                    and CampaignClusterComplete(controller, campaign)))
        if canResume and liveField > 0 then
            campaign.pendingResumeFieldTokens = nil
            campaign.pendingResumeHomeTokens = nil
            campaign.pendingResumeFull = nil
            CampaignSetPending(campaign, 'resume', campaign.fieldTokens)
        elseif canResume then
            local resumedField, resumedHome, resumedFull =
                InitialCampaignCohorts(CampaignCombatRecords(observation.units))
            if TableGetn(resumedField) > 0 then
                campaign.pendingResumeFieldTokens = resumedField
                campaign.pendingResumeHomeTokens = resumedHome
                campaign.pendingResumeFull = resumedFull == true
                CampaignSetPending(campaign, 'resume', resumedField)
            end
        end
        return
    end
    if rollbackReason and campaign.pendingMode ~= 'recall' then
        ESCALATION.RouteRestoreCommittedSource(
            controller,
            campaign,
            rollbackReason
        )
        if campaign.routeAttempt ~= nil then ESCALATION.RouteClear(campaign) end
        ClearDesiredCampaignObjective(campaign)
        campaign.pendingRollbackReason = rollbackReason
        if liveField > 0 then
            CampaignSetPending(campaign, 'rollback', campaign.fieldTokens)
        else
            campaign.state = 'rebuilding'
            campaign.rollbackReason = rollbackReason
            campaign.pendingRollbackReason = nil
            campaign.lastRollbackTick = tick
        end
        return
    end
    if campaign.state == 'recalled' then
        if health
            and health >= FIELD_CAMPAIGN_RESUME_HEALTH
            and reserveSafe
            and readinessReady
        then
            if campaign.healthySinceTick == nil then campaign.healthySinceTick = tick end
            if tick - campaign.healthySinceTick >= FIELD_CAMPAIGN_RESUME_TICKS
                and TableGetn(campaign.fieldTokens) > 0
                and ((campaign.kind == 'pressure_front'
                        and PressureAnchorLive(
                            controller,
                            campaign.anchorKey,
                            campaign.anchorPosition
                        ))
                    or (campaign.kind == 'strategic_assault'
                        and StrategicTargetValid(controller)))
            then
                CampaignSetPending(campaign, 'resume', campaign.fieldTokens)
            end
        else
            campaign.healthySinceTick = nil
            campaign.pendingMode = nil
            campaign.pendingTokens = {}
        end
        return
    end
    if ESCALATION.RouteUpdate(
        controller,
        observation,
        campaign,
        readinessReady
    ) then
        return
    end
    if not readinessReady
        and (campaign.pendingMode == 'transition'
            or campaign.pendingMode == 'assault')
    then
        ClearDesiredCampaignObjective(campaign)
        campaign.pendingMode = nil
        campaign.pendingTokens = {}
        return
    end
    if campaign.pendingMode == 'transition'
        and (campaign.desiredKind ~= 'pressure_front'
            or not PressureAnchorLive(
                controller,
                campaign.desiredAnchorKey,
                campaign.desiredAnchorPosition
            ))
    then
        ClearDesiredCampaignObjective(campaign)
        campaign.pendingMode = nil
        campaign.pendingTokens = {}
    elseif campaign.pendingMode == 'assault'
        and (campaign.desiredKind ~= 'strategic_assault'
            or not StrategicTargetValid(controller))
    then
        ClearDesiredCampaignObjective(campaign)
        campaign.pendingMode = nil
        campaign.pendingTokens = {}
    end
    if campaign.pendingMode == 'activate'
        or campaign.pendingMode == 'transition'
        or campaign.pendingMode == 'assault'
        or campaign.pendingMode == 'recover'
        or campaign.pendingMode == 'resume'
        or campaign.pendingMode == 'rollback'
    then
        return
    end
    if campaign.pendingMode == 'reinforce' then return end

    local quorumArrived = campaign.arrivalQuorum > 0
        and campaign.fieldAtAnchor >= campaign.arrivalQuorum
    if not quorumArrived
        and (campaign.state == 'active' or campaign.state == 'holding')
        and tick - (tonumber(campaign.lastProgressTick) or tick)
            >= FIELD_CAMPAIGN_STUCK_TICKS
        and tick - (tonumber(campaign.lastRecoveryAttemptTick) or -1000000)
            >= FIELD_CAMPAIGN_STUCK_TICKS
        and TableGetn(campaign.fieldTokens) > 0
    then
        if (tonumber(campaign.recoveryWindows) or 0) >= 1 then
            campaign.pendingRollbackReason = 'repeated_no_progress'
            CampaignSetPending(campaign, 'rollback', campaign.fieldTokens)
        else
            CampaignSetPending(campaign, 'recover', campaign.fieldTokens)
        end
        return
    end

    if campaign.kind == 'pressure_front' then
        if CampaignClusterComplete(controller, campaign) then
            if campaign.heldSinceTick == nil then campaign.heldSinceTick = tick end
            campaign.state = 'holding'
            if tick - campaign.heldSinceTick >= FIELD_CAMPAIGN_HOLD_TICKS
                and quorumArrived
                and TableGetn(campaign.fieldTokens) > 0
                and readinessReady
            then
                campaign.lastSecuredAnchorKey = campaign.anchorKey
                campaign.lastSecuredAnchorPosition = CopyPosition(campaign.anchorPosition)
                local nextCluster = NextPressureCluster(controller, campaign)
                if nextCluster then
                    ESCALATION.RouteStage(
                        controller,
                        observation,
                        campaign,
                        ESCALATION.RouteCandidateFromCluster(nextCluster)
                    )
                else
                    local assaultCandidate =
                        ESCALATION.RouteAssaultCandidate(controller)
                    if assaultCandidate then
                        ESCALATION.RouteStage(
                            controller,
                            observation,
                            campaign,
                            assaultCandidate
                        )
                    end
                end
                return
            end
        else
            campaign.heldSinceTick = nil
            if campaign.state == 'holding' then campaign.state = 'active' end
        end
    end
    if campaign.state == 'active' or campaign.state == 'holding' then
        local unordered = {}
        for _, token in ipairs(campaign.fieldTokens) do
            if campaign.orderedTokens[token] ~= true then TableInsert(unordered, token) end
        end
        if TableGetn(unordered) > 0 then
            CampaignSetPending(campaign, 'reinforce', unordered)
        end
    elseif (campaign.state == 'awaiting_order'
            or campaign.state == 'early_awaiting_order')
        and TableGetn(campaign.fieldTokens) > 0
        and campaign.pendingMode == nil
    then
        CampaignSetPending(campaign, 'activate', campaign.fieldTokens)
    end
end

local function CampaignExpectedPosition(controller, campaign, mode)
    if mode == 'recall' then return CopyPosition(controller.basePosition) end
    if mode == 'rollback' then
        return CopyPosition(campaign.lastSecuredAnchorPosition
            or controller.basePosition)
    end
    return CopyPosition(campaign.desiredAnchorPosition or campaign.anchorPosition)
end

local function EmergencyRecallStagesLive(controller, campaign, recordByToken)
    if campaign.pendingEmergencyReason ~= 'home_reserve' then return true end
    local stagedField = campaign.pendingRecallFieldTokens
    local stagedHome = campaign.pendingRecallHomeTokens
    local stagedFieldSet, stagedHomeSet = CohortTokenSets(
        stagedField,
        stagedHome
    )
    local currentFieldSet, currentHomeSet = CohortTokenSets(
        campaign.fieldTokens,
        campaign.homeTokens
    )
    if not stagedFieldSet or not currentFieldSet
        or TableGetn(stagedField) + TableGetn(stagedHome)
            ~= TableGetn(campaign.fieldTokens) + TableGetn(campaign.homeTokens)
    then
        return false
    end
    for token, _ in pairs(currentFieldSet) do
        if stagedFieldSet[token] ~= true and stagedHomeSet[token] ~= true then
            return false
        end
    end
    for token, _ in pairs(currentHomeSet) do
        if stagedHomeSet[token] ~= true then return false end
    end
    for token, _ in pairs(stagedFieldSet) do
        if currentFieldSet[token] ~= true then return false end
    end
    for token, _ in pairs(stagedHomeSet) do
        if currentFieldSet[token] ~= true and currentHomeSet[token] ~= true then
            return false
        end
    end
    for _, token in ipairs(stagedField) do
        local record = recordByToken[token]
        if not record
            or not COMBAT_ROLES[record.role]
            or record.complete ~= true
            or not LiveOwnedActor(controller, token, record, record.role)
        then
            return false
        end
    end
    for _, token in ipairs(stagedHome) do
        local record = recordByToken[token]
        if not record
            or not COMBAT_ROLES[record.role]
            or record.complete ~= true
            or not LiveOwnedActor(controller, token, record, record.role)
        then
            return false
        end
    end
    return true
end

ESCALATION.RouteIssueCached = function(actors, route, release)
    local clearOk = pcall(function() IssueClearCommands(actors) end)
    if not clearOk then
        return false, release == true and 'release_clear' or 'clear'
    end
    if release == true then
        local releaseOk = pcall(function()
            IssueAggressiveMove(actors, route.sourcePosition)
        end)
        if not releaseOk then
            local cleanupOk = pcall(function() IssueClearCommands(actors) end)
            return false, cleanupOk
                and 'release_aggressive'
                or 'release_aggressive_cleanup'
        end
        return true
    end
    local waypointCount = TableGetn(route.waypoints or {})
    if waypointCount == 0 then return false end
    for index = 1, waypointCount - 1 do
        local moveOk = pcall(function()
            IssueMove(actors, route.waypoints[index])
        end)
        if not moveOk then
            local cleanupOk = pcall(function() IssueClearCommands(actors) end)
            return false, cleanupOk
                and 'move_' .. tostring(index)
                or 'move_' .. tostring(index) .. '_cleanup'
        end
    end
    local aggressiveOk = pcall(function()
        IssueAggressiveMove(actors, route.waypoints[waypointCount])
    end)
    if not aggressiveOk then
        local cleanupOk = pcall(function() IssueClearCommands(actors) end)
        return false, cleanupOk and 'aggressive' or 'aggressive_cleanup'
    end
    return true
end

ESCALATION.ExecuteRoute = function(
    controller,
    intent,
    recordByToken,
    usedActors,
    observation
)
    local campaign = controller.fieldCampaign
    local route = campaign and campaign.routeAttempt or nil
    local mode = intent and intent.mode or nil
    local expectedState = mode == 'route_probe' and 'staged'
        or (mode == 'route_commit' and 'proven'
            or (mode == 'route_release' and 'releasing' or nil))
    local sealedFingerprint = type(route) == 'table'
        and ESCALATION.RouteFingerprint(route)
        or nil
    if controller.fieldCampaignEnabled ~= true
        or type(route) ~= 'table'
        or type(route.source) ~= 'table'
        or sealedFingerprint == nil
        or sealedFingerprint ~= route.routeFingerprint
        or expectedState == nil
        or route.state ~= expectedState
        or campaign.pendingMode ~= mode
        or type(intent.actorTokens) ~= 'table'
        or type(intent.routeEpoch) ~= 'number'
        or intent.routeEpoch ~= route.epoch
        or type(intent.routeKey) ~= 'string'
        or intent.routeKey ~= route.routeKey
        or type(intent.routeFingerprint) ~= 'string'
        or intent.routeFingerprint ~= route.routeFingerprint
        or type(intent.routeSourceKey) ~= 'string'
        or intent.routeSourceKey ~= route.sourceAnchorKey
    then
        return false
    end
    local release = mode == 'route_release'
    local expectedKind = release and route.source.kind or route.candidateKind
    local expectedCluster = release
        and route.source.clusterKey
        or route.candidateClusterKey
    local expectedObjective = release
        and route.source.anchorKey
        or route.candidateAnchorKey
    local expectedPosition = release
        and route.source.anchorPosition
        or route.candidateAnchorPosition
    if intent.campaignKind ~= expectedKind
        or intent.clusterKey ~= expectedCluster
        or intent.objectiveKey ~= expectedObjective
        or not IsCampaignPosition(intent.position)
        or DistanceSquared(intent.position, expectedPosition) > 0.01
    then
        return false
    end
    if not release
        and (type(observation) ~= 'table'
            or type(observation.macro) ~= 'table'
            or observation.macro.campaignReady ~= true
            or not ESCALATION.RouteSourceAuthoritative(campaign, route)
            or not ESCALATION.RouteCandidateLive(controller, route))
    then
        return false
    end
    local tokens = {}
    local seen = {}
    for _, token in ipairs(intent.actorTokens) do
        if type(token) ~= 'string' or seen[token] then return false end
        seen[token] = true
        TableInsert(tokens, token)
    end
    table.sort(tokens)
    local expected = CopyArray(campaign.pendingTokens)
    table.sort(expected)
    if TableGetn(tokens) == 0 or not SameArray(tokens, expected) then return false end
    if mode == 'route_probe' and not SameArray(tokens, route.probeTokens) then
        return false
    elseif mode == 'route_commit' then
        local bulk = ESCALATION.RouteBulkTokens(
            controller,
            observation,
            campaign,
            route
        )
        if not SameArray(tokens, bulk) then return false end
        local _, liveCount, atDestination = ESCALATION.RouteProbeMetrics(
            controller,
            observation,
            route
        )
        if liveCount < route.probeQuorum
            or atDestination < route.probeQuorum
        then
            return false
        end
    elseif mode == 'route_release'
        and not SameArray(tokens, route.releaseTokens)
    then
        return false
    end
    local actors = {}
    for _, token in ipairs(tokens) do
        local record = recordByToken[token]
        if usedActors[token]
            or not CampaignFieldContains(campaign, token)
            or controller.pending[token]
            or controller.waveAssignments[token]
            or not record
            or not COMBAT_ROLES[record.role]
            or record.complete ~= true
        then
            return false
        end
        local actor = LiveOwnedActor(controller, token, record, record.role)
        if not actor then return false end
        if mode == 'route_probe' then
            local livePosition = CopyPosition(
                SafeCall(nil, actor.GetPosition, actor)
            )
            if not livePosition
                or Distance(livePosition, route.source.anchorPosition)
                    > FIELD_CAMPAIGN_ANCHOR_RADIUS
            then
                return false
            end
        end
        TableInsert(actors, actor)
    end
    local tick = CurrentTick(controller)
    local issued, issueFailure = ESCALATION.RouteIssueCached(
        actors,
        route,
        release
    )
    if not issued then
        local previousFailure = route.lastFailure
        if mode == 'route_commit'
            and type(issueFailure) == 'string'
            and string.sub(issueFailure, -8) == '_cleanup'
        then
            local releaseSet = BuildTokenSet(route.probeTokens) or {}
            local releaseTokens = CopyArray(route.probeTokens)
            for _, token in ipairs(tokens) do
                if not releaseSet[token] then
                    releaseSet[token] = true
                    TableInsert(releaseTokens, token)
                end
            end
            table.sort(releaseTokens)
            route.cleanupTokens = releaseTokens
            route.releaseTokens = nil
            route.routeFingerprint = ESCALATION.RouteFingerprint(route)
                or 'invalid'
            controller.routeCleanupOwnership = {
                routeKey = route.routeKey,
                epoch = route.epoch,
                tokens = CopyArray(releaseTokens),
                routeFingerprint = route.routeFingerprint,
            }
        end
        route.dispatchFailureTick = route.dispatchFailureTick or tick
        route.lastFailureTick = tick
        route.lastFailure = tostring(issueFailure or 'command_failed')
        if previousFailure ~= route.lastFailure then
            Emit(controller, 'campaign_route_dispatch_failed', {
                route = route.routeKey or 'none',
                epoch = tonumber(route.epoch) or -1,
                fingerprint = route.routeFingerprint or 'none',
                mode = tostring(mode or 'none'),
                reason = route.lastFailure,
                age = math.max(0, tick - (tonumber(route.stagedTick) or tick)),
            })
        end
        return false
    end
    route.dispatchFailureTick = nil
    for _, token in ipairs(tokens) do
        usedActors[token] = true
        campaign.orderedTokens[token] = true
    end
    if mode == 'route_probe' then
        route.state = 'probing'
        route.issuedTick = tick
        route.lastProgressTick = tick
        local _, _, atDestination, distance = ESCALATION.RouteProbeMetrics(
            controller,
            observation,
            route
        )
        route.atDestination = atDestination
        route.bestDistance = distance
        campaign.routeProbeOrders = (tonumber(campaign.routeProbeOrders) or 0) + 1
        campaign.pendingMode = nil
        campaign.pendingTokens = {}
        Emit(controller, 'campaign_route_probe', {
            route = route.routeKey,
            epoch = route.epoch,
            fingerprint = route.routeFingerprint,
            source = route.sourceAnchorKey,
            destination = route.candidateAnchorKey,
            waypoints = TableGetn(route.waypoints or {}),
            route_length = tonumber(route.routeLength) or -1,
            units = TableGetn(tokens),
            quorum = route.probeQuorum,
        })
        return true
    end
    if mode == 'route_commit' then
        local previousCluster = campaign.clusterKey
        local rollback = {
            epoch = route.epoch,
            routeKey = route.routeKey,
            routeFingerprint = route.routeFingerprint,
            blockKey = route.blockKey,
            source = route.source,
            sourcePosition = CopyPosition(route.sourcePosition),
            committedTick = tick,
        }
        campaign.kind = route.candidateKind
        campaign.clusterKey = route.candidateClusterKey
        campaign.memberKeys = CopyArray(route.candidateMemberKeys)
        campaign.anchorKey = route.candidateAnchorKey
        campaign.anchorPosition = CopyPosition(route.candidateAnchorPosition)
        campaign.anchorTargetDistanceSquared =
            route.candidateAnchorTargetDistanceSquared
        campaign.objectiveKey = campaign.anchorKey
        campaign.objectivePosition = CopyPosition(campaign.anchorPosition)
        campaign.objectiveReason = campaign.kind
        campaign.state = 'active'
        campaign.fullFieldOrders = campaign.fullFieldOrders + 1
        campaign.routeBulkOrders = (tonumber(campaign.routeBulkOrders) or 0) + 1
        campaign.missionIssuedTick = tick
        campaign.lastProgressTick = tick
        campaign.bestDistance = 1000000000000
        campaign.bestAtAnchor = 0
        campaign.progressCohortSize = -1
        campaign.recoveryWindows = 0
        campaign.lastRecoveryAttemptTick = tick - FIELD_CAMPAIGN_STUCK_TICKS
        campaign.heldSinceTick = nil
        campaign.routeRollback = rollback
        local ownership = controller.routeCleanupOwnership
        if type(ownership) == 'table'
            and ownership.routeKey == route.routeKey
            and ownership.epoch == route.epoch
        then
            controller.routeCleanupOwnership = nil
        end
        campaign.routeAttempt = nil
        campaign.pendingMode = nil
        campaign.pendingTokens = {}
        ClearDesiredCampaignObjective(campaign)
        if campaign.kind == 'strategic_assault' then
            campaign.assaultEvents = campaign.assaultEvents + 1
            Emit(controller, 'campaign_assault', {
                from = previousCluster or 'none',
                target = campaign.anchorKey,
            })
        else
            campaign.transitionEvents = campaign.transitionEvents + 1
            Emit(controller, 'campaign_transition', {
                from = previousCluster or 'none',
                cluster = campaign.clusterKey,
                objective = campaign.anchorKey,
            })
        end
        Emit(controller, 'campaign_route_committed', {
            route = route.routeKey,
            epoch = route.epoch,
            fingerprint = route.routeFingerprint,
            source = route.sourceAnchorKey,
            destination = route.candidateAnchorKey,
            waypoints = TableGetn(route.waypoints or {}),
            route_length = tonumber(route.routeLength) or -1,
            cluster = campaign.clusterKey,
            objective = campaign.anchorKey,
            units = TableGetn(tokens),
        })
        return true
    end
    ESCALATION.RouteFinalizeRelease(controller, campaign, route, 'ordered')
    return true
end

local function ExecuteFieldCampaign(
    controller,
    intent,
    recordByToken,
    usedActors,
    observation
)
    local campaign = controller.fieldCampaign
    if intent
        and (intent.mode == 'route_probe'
            or intent.mode == 'route_commit'
            or intent.mode == 'route_release')
    then
        return ESCALATION.ExecuteRoute(
            controller,
            intent,
            recordByToken,
            usedActors,
            observation
        )
    end
    local allowedModes = {
        activate = true,
        reinforce = true,
        transition = true,
        assault = true,
        recover = true,
        recall = true,
        resume = true,
        rollback = true,
    }
    local expectedKind = campaign
        and (campaign.desiredKind or campaign.kind)
        or nil
    local expectedCluster = campaign
        and (campaign.desiredClusterKey or campaign.clusterKey)
        or nil
    local expectedAnchorKey = campaign
        and (campaign.desiredAnchorKey or campaign.anchorKey)
        or nil
    if controller.fieldCampaignEnabled ~= true
        or controller.legacyFrontierRetirementPending == true
        or controller.frontierMission ~= nil
        or not campaign
        or type(intent.mode) ~= 'string'
        or allowedModes[intent.mode] ~= true
        or intent.mode ~= campaign.pendingMode
        or type(intent.campaignKind) ~= 'string'
        or intent.campaignKind ~= expectedKind
        or type(intent.campaignSerial) ~= 'number'
        or intent.campaignSerial ~= campaign.serial
        or type(intent.clusterKey) ~= 'string'
        or intent.clusterKey ~= expectedCluster
        or type(intent.objectiveKey) ~= 'string'
        or intent.objectiveKey ~= expectedAnchorKey
        or type(intent.actorTokens) ~= 'table'
    then
        return false
    end
    if (intent.mode == 'activate'
            or intent.mode == 'transition'
            or intent.mode == 'assault'
            or intent.mode == 'resume')
        and (type(observation) ~= 'table'
            or type(observation.macro) ~= 'table'
            or observation.macro.campaignReady ~= true)
    then
        return false
    end
    if intent.mode == 'resume'
        and campaign.lastRollbackTick ~= nil
        and CurrentTick(controller) - (tonumber(campaign.lastRollbackTick)
            or CurrentTick(controller))
            < ESCALATION.CAMPAIGN_ROLLBACK_COOLDOWN_TICKS
    then
        return false
    end
    local tokens = {}
    local seen = {}
    for _, token in ipairs(intent.actorTokens or {}) do
        if type(token) ~= 'string' or seen[token] then return false end
        seen[token] = true
        TableInsert(tokens, token)
    end
    table.sort(tokens)
    local expected = CopyArray(campaign.pendingTokens)
    table.sort(expected)
    if not SameArray(tokens, expected) or TableGetn(tokens) == 0 then return false end
    local stagedResume = intent.mode == 'resume'
        and campaign.state == 'rebuilding'
        and type(campaign.pendingResumeFieldTokens) == 'table'
        and type(campaign.pendingResumeHomeTokens) == 'table'
    local stagedFieldSet = nil
    local stagedHomeSet = nil
    if stagedResume then
        stagedFieldSet, stagedHomeSet = CohortTokenSets(
            campaign.pendingResumeFieldTokens,
            campaign.pendingResumeHomeTokens
        )
        local combatRecords = CampaignCombatRecords(observation.units)
        if not stagedFieldSet
            or not SameArray(tokens, campaign.pendingResumeFieldTokens)
            or TableGetn(campaign.pendingResumeFieldTokens)
                + TableGetn(campaign.pendingResumeHomeTokens)
                ~= TableGetn(combatRecords)
        then
            return false
        end
        for _, record in ipairs(combatRecords) do
            local fieldMember = stagedFieldSet[record.token] == true
            local homeMember = stagedHomeSet[record.token] == true
            if fieldMember == homeMember
                or not LiveOwnedActor(
                    controller,
                    record.token,
                    record,
                    record.role
                )
            then
                return false
            end
        end
    end
    local expectedPosition = CampaignExpectedPosition(controller, campaign, intent.mode)
    if not expectedPosition
        or not IsCampaignPosition(intent.position)
        or DistanceSquared(expectedPosition, intent.position) > 0.01
        or (intent.mode == 'recall'
            and not EmergencyRecallStagesLive(
                controller,
                campaign,
                recordByToken
            ))
    then
        return false
    end

    local actors = {}
    for _, token in ipairs(tokens) do
        local record = recordByToken[token]
        if usedActors[token]
            or (not stagedResume
                and not CampaignFieldContains(campaign, token))
            or (stagedResume and stagedFieldSet[token] ~= true)
            or controller.pending[token]
            or controller.waveAssignments[token]
            or not record
            or not COMBAT_ROLES[record.role]
            or record.complete ~= true
        then
            return false
        end
        local actor = LiveOwnedActor(controller, token, record, record.role)
        if not actor then return false end
        TableInsert(actors, actor)
    end

    if intent.mode ~= 'recall' and intent.mode ~= 'rollback' then
        if expectedKind == 'strategic_assault' then
            local graph = BuildPressureGraph(controller)
            if not StrategicTargetValid(controller)
                or not graph
                or expectedAnchorKey ~= 'target:' .. graph.targetName
                or DistanceSquared(expectedPosition, graph.targetPosition) > 0.01
            then
                return false
            end
        elseif expectedKind ~= 'pressure_front'
            or not PressureAnchorLive(
                controller,
                expectedAnchorKey,
                expectedPosition
            )
        then
            return false
        end
    end

    local aggressivePosition = nil
    if intent.mode ~= 'recall' and intent.mode ~= 'rollback' then
        local terrainOk = false
        terrainOk, aggressivePosition = pcall(TerrainPosition, expectedPosition)
        local height = terrainOk
            and aggressivePosition
            and aggressivePosition[2]
            or nil
        if not terrainOk
            or not IsCampaignPosition(aggressivePosition)
            or type(height) ~= 'number'
            or height ~= height
            or math.abs(height) > 10000000
        then
            return false
        end
    end

    if intent.mode ~= 'reinforce' then
        local clearOk = pcall(function() IssueClearCommands(actors) end)
        if not clearOk then return false end
    end
    local orderOk = false
    if intent.mode == 'recall' or intent.mode == 'rollback' then
        orderOk = pcall(function() IssueMove(actors, expectedPosition) end)
    else
        orderOk = pcall(function()
            IssueAggressiveMove(actors, aggressivePosition)
        end)
    end
    if not orderOk then
        if intent.mode ~= 'reinforce' then
            pcall(function() IssueClearCommands(actors) end)
        end
        return false
    end

    if stagedResume then
        if not CommitCampaignCohorts(
            campaign,
            campaign.pendingResumeFieldTokens,
            campaign.pendingResumeHomeTokens
        ) then
            return false
        end
        campaign.fullCohorts = campaign.pendingResumeFull == true
        campaign.orderedTokens = {}
    end

    local tick = CurrentTick(controller)
    for _, token in ipairs(tokens) do
        usedActors[token] = true
        campaign.orderedTokens[token] = true
    end
    local mode = intent.mode
    if mode == 'activate' then
        campaign.state = 'active'
        campaign.fullFieldOrders = campaign.fullFieldOrders + 1
        campaign.missionIssuedTick = tick
        campaign.lastProgressTick = tick
        campaign.bestDistance = tonumber(campaign.forwardDistance) or -1
        campaign.bestAtAnchor = tonumber(campaign.fieldAtAnchor) or 0
        campaign.progressCohortSize = TableGetn(campaign.fieldTokens)
    elseif mode == 'reinforce' then
        campaign.reinforcementOrders = campaign.reinforcementOrders + 1
        if TableGetn(campaign.fieldTokens) > (tonumber(campaign.attritionBaseline) or 0) then
            campaign.attritionBaseline = TableGetn(campaign.fieldTokens)
            campaign.attritionWindowTick = tick
            campaign.attritionLost = 0
            campaign.attritionWindow = 0
        end
    elseif mode == 'transition' then
        local previousCluster = campaign.clusterKey
        campaign.kind = campaign.desiredKind
        campaign.clusterKey = campaign.desiredClusterKey
        campaign.memberKeys = CopyArray(campaign.desiredMemberKeys)
        campaign.anchorKey = campaign.desiredAnchorKey
        campaign.anchorPosition = CopyPosition(campaign.desiredAnchorPosition)
        campaign.anchorTargetDistanceSquared = campaign.desiredAnchorTargetDistanceSquared
        campaign.objectiveKey = campaign.anchorKey
        campaign.objectivePosition = CopyPosition(campaign.anchorPosition)
        campaign.objectiveReason = 'pressure_front'
        ClearDesiredCampaignObjective(campaign)
        campaign.awaitingReason = nil
        campaign.state = 'active'
        campaign.fullFieldOrders = campaign.fullFieldOrders + 1
        campaign.missionIssuedTick = tick
        campaign.lastProgressTick = tick
        campaign.bestDistance = 1000000000000
        campaign.bestAtAnchor = 0
        campaign.progressCohortSize = -1
        campaign.recoveryWindows = 0
        campaign.lastRecoveryAttemptTick = tick - FIELD_CAMPAIGN_STUCK_TICKS
        campaign.heldSinceTick = nil
        campaign.transitionEvents = campaign.transitionEvents + 1
        Emit(controller, 'campaign_transition', {
            from = previousCluster or 'none',
            cluster = campaign.clusterKey,
            objective = campaign.anchorKey,
        })
    elseif mode == 'assault' then
        local previousCluster = campaign.clusterKey
        campaign.kind = 'strategic_assault'
        campaign.clusterKey = campaign.desiredClusterKey
        campaign.memberKeys = {}
        campaign.anchorKey = campaign.desiredAnchorKey
        campaign.anchorPosition = CopyPosition(campaign.desiredAnchorPosition)
        campaign.anchorTargetDistanceSquared = 0
        campaign.objectiveKey = campaign.anchorKey
        campaign.objectivePosition = CopyPosition(campaign.anchorPosition)
        campaign.objectiveReason = 'strategic_assault'
        ClearDesiredCampaignObjective(campaign)
        campaign.state = 'active'
        campaign.fullFieldOrders = campaign.fullFieldOrders + 1
        campaign.missionIssuedTick = tick
        campaign.lastProgressTick = tick
        campaign.bestDistance = 1000000000000
        campaign.bestAtAnchor = 0
        campaign.progressCohortSize = -1
        campaign.recoveryWindows = 0
        campaign.lastRecoveryAttemptTick = tick - FIELD_CAMPAIGN_STUCK_TICKS
        campaign.heldSinceTick = nil
        campaign.assaultEvents = campaign.assaultEvents + 1
        Emit(controller, 'campaign_assault', {
            from = previousCluster or 'none',
            target = campaign.anchorKey,
        })
    elseif mode == 'recover' then
        campaign.recoveryOrders = campaign.recoveryOrders + 1
        campaign.recoveryWindows = (tonumber(campaign.recoveryWindows) or 0) + 1
        campaign.fullFieldOrders = campaign.fullFieldOrders + 1
        campaign.lastRecoveryAttemptTick = tick
    elseif mode == 'recall' then
        local emergencyReason = campaign.pendingEmergencyReason or 'acu_health'
        if emergencyReason == 'home_reserve' then
            if not CommitCampaignCohorts(
                campaign,
                campaign.pendingRecallFieldTokens,
                campaign.pendingRecallHomeTokens
            ) then
                return false
            end
            campaign.fullCohorts = false
            campaign.orderedTokens = {}
        end
        campaign.state = 'recalled'
        campaign.emergency = true
        campaign.emergencyReason = emergencyReason
        campaign.healthySinceTick = nil
        campaign.modeSwitches = campaign.modeSwitches + 1
        campaign.pendingEmergencyReason = nil
        campaign.pendingRecallFieldTokens = nil
        campaign.pendingRecallHomeTokens = nil
    elseif mode == 'resume' then
        campaign.state = 'active'
        campaign.emergency = false
        campaign.emergencyReason = nil
        campaign.healthySinceTick = nil
        campaign.modeSwitches = campaign.modeSwitches + 1
        campaign.fullFieldOrders = campaign.fullFieldOrders + 1
        campaign.missionIssuedTick = tick
        campaign.lastProgressTick = tick
        campaign.bestDistance = 1000000000000
        campaign.bestAtAnchor = 0
        campaign.progressCohortSize = -1
        campaign.recoveryWindows = 0
        campaign.attritionBaseline = TableGetn(campaign.fieldTokens)
        campaign.attritionWindowTick = tick
        campaign.attritionLost = 0
        campaign.attritionWindow = 0
        campaign.pendingResumeFieldTokens = nil
        campaign.pendingResumeHomeTokens = nil
        campaign.pendingResumeFull = nil
    elseif mode == 'rollback' then
        campaign.state = 'rebuilding'
        campaign.rollbackReason = campaign.pendingRollbackReason or 'unknown'
        campaign.pendingRollbackReason = nil
        campaign.rollbackOrders = (tonumber(campaign.rollbackOrders) or 0) + 1
        campaign.lastRollbackTick = tick
    else
        return false
    end
    campaign.pendingMode = nil
    campaign.pendingTokens = {}
    Emit(controller, 'campaign_order', {
        command = mode,
        campaign_kind = campaign.kind,
        cluster = campaign.clusterKey,
        objective = campaign.anchorKey,
        units = TableGetn(tokens),
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
        and Reachable('Land', controller.basePosition, controller.targetPosition)
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
        reclaimReservations = {},
        foundationReservations = {},
        reclaimCandidates = {},
        reclaimRefs = {},
        reclaimFreshness = {},
        blockedSites = {},
        rallied = {},
        waveAssignments = {},
        frontierAssignments = {},
        frontierMission = nil,
        legacyFrontierRetirementPending = false,
        fieldCampaignEnabled = true,
        fieldCampaign = nil,
        fieldCampaignSerial = 0,
        routeCleanupOwnership = nil,
        airAssignments = {},
        airScreenCount = 0,
        factoryTarget = 2,
        economyLedger = { samples = {}, lastTick = nil, lastStats = nil },
        economyCommitmentLeases = {},
        allocatorDeniedRequest = 'none',
        allocatorDeniedReason = 'none',
        upgradeState = 'none',
        lastPlacementProbeCount = 0,
        lastPlacementCapacity = 0,
        placementFootprintSpecs = {},
        mexHistory = {},
        ownedMexCount = 0,
        lostMexCount = 0,
        rebuiltMexCount = 0,
        selectedFrontierCluster = nil,
        selectedFrontierSites = nil,
        selectedFrontierSite = nil,
        frontierOwned = 0,
        frontierTotal = 0,
        rallyPosition = nil,
        massSurplusSinceTick = nil,
        massSurplusTicks = 0,
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
        lastReclaimQueryTick = -RECLAIM_QUERY_INTERVAL_TICKS,
        lastErrorTick = -REORDER_COOLDOWN_TICKS,
        crossMapOffenseEnabled = false,
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
    local economy = {
        energyTrend = SafeCall(nil, controller.brain.GetEconomyTrend, controller.brain, 'ENERGY'),
        energyStoredRatio = SafeCall(nil, controller.brain.GetEconomyStoredRatio, controller.brain, 'ENERGY'),
        energyIncome = SafeCall(nil, controller.brain.GetEconomyIncome, controller.brain, 'ENERGY'),
        energyUsage = SafeCall(nil, controller.brain.GetEconomyUsage, controller.brain, 'ENERGY'),
        massTrend = SafeCall(nil, controller.brain.GetEconomyTrend, controller.brain, 'MASS'),
        massStoredRatio = SafeCall(nil, controller.brain.GetEconomyStoredRatio, controller.brain, 'MASS'),
        massIncome = SafeCall(nil, controller.brain.GetEconomyIncome, controller.brain, 'MASS'),
        massUsage = SafeCall(nil, controller.brain.GetEconomyUsage, controller.brain, 'MASS'),
    }
    economy.energyRequested = SafeCall(nil,
        controller.brain.GetEconomyRequested, controller.brain, 'ENERGY')
    economy.massRequested = SafeCall(nil,
        controller.brain.GetEconomyRequested, controller.brain, 'MASS')
    ESCALATION.UpdateEconomyLedger(controller, economy)
    UpdateMassSurplus(controller, economy)
    local sites = {
        mass = SiteSnapshot(controller, controller.markers.mass, units),
        hydro = SiteSnapshot(controller, controller.markers.hydro, units),
    }
    UpdateMexHistory(controller, sites.mass)
    UpdateFrontier(controller, sites.mass)
    controller.currentSites = sites
    local foundations = FoundationSnapshot(controller, units)
    controller.currentFoundations = foundations
    for _, unit in ipairs(units) do
        unit.nearRally = DistanceSquared(unit.position, controller.rallyPosition)
            <= STAGING_RADIUS * STAGING_RADIUS
        if unit.role == 'land_factory' then
            unit.needsRally = controller.rallied[unit.token] ~= true
        end
    end
    local reclaim = RefreshReclaim(controller, units, sites.mass)
    local observation = {
        tick = CurrentTick(controller),
        basePosition = CopyPosition(controller.basePosition),
        stagingPosition = CopyPosition(controller.stagingPosition),
        rallyPosition = CopyPosition(controller.rallyPosition),
        targetPosition = CopyPosition(controller.targetPosition),
        targetPath = controller.targetPath,
        economy = economy,
        units = units,
        enemyContact = NormalizeEnemyContact(controller, enemies, units),
        sites = sites,
        foundations = foundations,
        reclaim = reclaim,
        placements = PlacementSnapshot(controller, units),
        pending = PendingArray(controller),
        state = StateSnapshot(controller),
    }
    observation.macro = MacroSnapshot(controller, units, economy)
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
    for token, _ in pairs(controller.airAssignments or {}) do
        local record = records[token]
        if not record or record.role ~= 'interceptor' or record.complete ~= true then
            controller.airAssignments[token] = nil
        end
    end
    controller.airScreenCount = CountArray(controller.airAssignments)
    for _, token in ipairs(SortedKeys(controller.pending)) do
        local operation = controller.pending[token]
        local record = records[token]
        local elapsed = tick - operation.issuedTick
        if OperationCompleted(controller, operation, observation, record) then
            ReleaseOperation(controller, token, nil)
        elseif operation.kind == 'factory_upgrade' and not record then
            local target = operation.upgradeTargetToken
                and records[operation.upgradeTargetToken]
                or nil
            if not target or target.role ~= operation.upgradeRole then
                ReleaseOperation(controller, token, 'actor_missing')
            elseif tick >= (tonumber(operation.deadlineTick)
                    or (operation.issuedTick + OPERATION_TIMEOUT_TICKS))
            then
                ReleaseOperation(controller, token, 'timeout')
            elseif tonumber(target.fractionComplete)
                and tonumber(target.fractionComplete)
                    > (tonumber(operation.lastFraction) or 0) + 0.001
            then
                operation.lastFraction = tonumber(target.fractionComplete)
                operation.lastProgressTick = tick
            end
        elseif not record then
            ReleaseOperation(controller, token, 'actor_missing')
        elseif operation.phase == 'cancelling' then
            local actor = LiveOwnedActor(controller, token, record, record.role)
            if not actor then
                ReleaseOperation(controller, token, 'actor_missing')
            elseif operation.kind == 'factory_upgrade' then
                if SafeCall(false, actor.IsUnitState, actor, 'Upgrading') ~= true then
                    if record.idle == true
                        and tick > (tonumber(operation.cancelRequestedTick) or tick)
                    then
                        ReleaseOperation(
                            controller,
                            token,
                            operation.cancelReason or 'timeout'
                        )
                    end
                elseif ESCALATION.UpgradeCancellationMatches(operation, actor) then
                    RequestOperationCancellation(
                        controller,
                        operation,
                        record,
                        operation.cancelReason or 'timeout'
                    )
                end
            elseif record.idle == true
                and tick > (tonumber(operation.cancelRequestedTick) or tick)
            then
                ReleaseOperation(controller, token, operation.cancelReason or 'timeout')
            else
                RequestOperationCancellation(
                    controller,
                    operation,
                    record,
                    operation.cancelReason or 'timeout'
                )
            end
        elseif operation.kind == 'assist_structure'
            and (not operation.targetToken or not records[operation.targetToken])
        then
            ReleaseOperation(controller, token, 'target_missing')
        elseif operation.kind == 'factory_upgrade'
            and operation.accepted == true
            and not ESCALATION.UpgradeInProgress(controller, operation, record)
        then
            local actor = LiveOwnedActor(
                controller,
                token,
                record,
                'land_factory'
            )
            if actor
                and SafeCall(false, actor.IsUnitState, actor, 'Upgrading') == true
            then
                if ESCALATION.UpgradeCancellationMatches(operation, actor) then
                    RequestOperationCancellation(
                        controller,
                        operation,
                        record,
                        'target_missing'
                    )
                end
            else
                ReleaseOperation(controller, token, 'rejected')
            end
        else
            OperationProgress(controller, operation, observation, record)
            if operation.kind == 'factory_upgrade'
                and record.idle == true
                and (operation.accepted == true or elapsed > REJECT_TICKS)
            then
                ReleaseOperation(controller, token, 'rejected')
            elseif StructureOperation(operation)
                and operation.accepted == true
                and record.idle == true
                and (tonumber(operation.lastFraction) or 0) <= 0
            then
                ReleaseOperation(controller, token, 'rejected')
            elseif operation.kind == 'reclaim'
                and operation.accepted == true
                and record.idle == true
            then
                ReleaseOperation(controller, token, 'rejected')
            elseif tick >= (tonumber(operation.deadlineTick) or (operation.issuedTick + OPERATION_TIMEOUT_TICKS)) then
                if StructureOperation(operation)
                    or operation.kind == 'reclaim'
                    or operation.kind == 'factory_upgrade'
                then
                    if record.idle == true then
                        ReleaseOperation(controller, token, 'timeout')
                    elseif not RequestOperationCancellation(
                        controller,
                        operation,
                        record,
                        'timeout'
                    ) then
                        local actor = LiveOwnedActor(controller, token, record, record.role)
                        if not actor then
                            ReleaseOperation(controller, token, 'actor_missing')
                        end
                    end
                else
                    ReleaseOperation(controller, token, 'timeout')
                end
            elseif elapsed >= VERIFY_TICKS then
                if operation.kind == 'factory_upgrade' then
                    if ESCALATION.UpgradeAccepted(controller, operation, record) then
                        operation.accepted = true
                    end
                elseif record.busy then
                    operation.accepted = true
                end
                if not operation.accepted and elapsed > REJECT_TICKS then
                    ReleaseOperation(controller, token, 'rejected')
                elseif StructureOperation(operation)
                    and operation.phase == 'building'
                    and tick - (tonumber(operation.lastProgressTick) or operation.issuedTick)
                        > BUILD_STALL_TICKS
                then
                    if record.idle == true then
                        ReleaseOperation(controller, token, 'stalled')
                    elseif not RequestOperationCancellation(
                        controller,
                        operation,
                        record,
                        'stalled'
                    ) then
                        local actor = LiveOwnedActor(controller, token, record, record.role)
                        if not actor then
                            ReleaseOperation(controller, token, 'actor_missing')
                        end
                    end
                elseif operation.kind == 'factory_upgrade'
                    and operation.accepted == true
                    and operation.phase == 'building'
                    and tick - (tonumber(operation.lastProgressTick)
                        or operation.issuedTick) > BUILD_STALL_TICKS
                then
                    if record.idle == true then
                        ReleaseOperation(controller, token, 'stalled')
                    elseif not RequestOperationCancellation(
                        controller,
                        operation,
                        record,
                        'stalled'
                    ) then
                        local actor = LiveOwnedActor(
                            controller,
                            token,
                            record,
                            record.role
                        )
                        if not actor then
                            ReleaseOperation(controller, token, 'actor_missing')
                        end
                    end
                elseif not StructureOperation(operation)
                    and operation.kind ~= 'factory_upgrade'
                    and elapsed > OPERATION_TIMEOUT_TICKS
                then
                    ReleaseOperation(controller, token, 'timeout')
                end
            end
        end
    end

    for _, collection in pairs(observation.sites or {}) do
        for _, site in ipairs(collection or {}) do
            site.reserved = controller.reservations[site.key] ~= nil
            site.buildable = not SiteIsBlocked(controller, site.key)
        end
    end
    RefreshFoundationReservations(controller, observation.foundations)
    controller.currentFoundations = observation.foundations or {}

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

    if controller.fieldCampaignEnabled == true then
        controller.legacyFrontierRetirementPending = false
        if controller.frontierMission
            and not ClearFrontierMission(controller)
        then
            controller.legacyFrontierRetirementPending = true
        elseif not controller.frontierMission then
            for token in pairs(controller.frontierAssignments) do
                controller.frontierAssignments[token] = nil
            end
        end
    elseif controller.frontierMission then
        local mission = controller.frontierMission
        local engineer = records[mission.engineerToken]
        local operation = controller.pending[mission.engineerToken]
        if not engineer
            or engineer.role ~= 'engineer'
            or not operation
            or operation.reason ~= 'frontier_expansion'
            or (mission.clusterKey
                and controller.selectedFrontierCluster
                and mission.clusterKey ~= controller.selectedFrontierCluster)
        then
            ClearFrontierMission(controller)
        else
            local survivors = {}
            for _, token in ipairs(mission.escortTokens or {}) do
                if records[token] and controller.unitRefs[token] then
                    TableInsert(survivors, token)
                else
                    controller.frontierAssignments[token] = nil
                end
            end
            mission.escortTokens = survivors
            if TableGetn(survivors) == 0 then
                controller.frontierMission = nil
            end
        end
    end

    UpdateFieldCampaign(controller, observation)

    observation.pending = PendingArray(controller)
    observation.state = StateSnapshot(controller)
    observation.macro = MacroSnapshot(controller, observation.units, observation.economy)
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
        if intent.kind == 'field_campaign'
            and controller.fieldCampaignEnabled == true
        then
            ExecuteFieldCampaign(
                controller,
                intent,
                records,
                usedActors,
                observation
            )
        elseif intent.kind == 'air_screen' then
            ESCALATION.ExecuteAirScreen(
                controller,
                intent,
                records,
                usedActors,
                observation
            )
        elseif intent.kind == 'frontier_screen'
            and (controller.fieldCampaignEnabled ~= true
                or controller.fieldCampaign == nil)
        then
            ExecuteFrontierScreen(controller, intent, records, usedActors)
        elseif intent.kind == 'mobilize_commander'
            and controller.crossMapOffenseEnabled == true
            and controller.fieldCampaignEnabled ~= true
        then
            ExecuteCommanderMobilization(controller, intent, records, usedActors)
            if type(intent.acuToken) == 'string' then
                usedActors[intent.acuToken] = true
            end
            for _, token in ipairs(intent.actorTokens or {}) do
                if type(token) == 'string' then usedActors[token] = true end
            end
        elseif intent.kind == 'commander_push'
            and controller.crossMapOffenseEnabled == true
            and controller.fieldCampaignEnabled ~= true
        then
            ExecuteCommanderPush(controller, intent, records, usedActors)
            if type(intent.acuToken) == 'string' then
                usedActors[intent.acuToken] = true
            end
            for _, token in ipairs(intent.actorTokens or {}) do
                if type(token) == 'string' then usedActors[token] = true end
            end
        elseif intent.kind == 'reinforce_commander'
            and controller.crossMapOffenseEnabled == true
            and controller.fieldCampaignEnabled ~= true
        then
            ExecuteCommanderReinforcement(controller, intent, records, usedActors)
            if type(intent.acuToken) == 'string' then
                usedActors[intent.acuToken] = true
            end
            for _, token in ipairs(intent.actorTokens or {}) do
                if type(token) == 'string' then usedActors[token] = true end
            end
        elseif (intent.kind == 'attack_wave'
            and controller.crossMapOffenseEnabled == true
            and controller.fieldCampaignEnabled ~= true)
            or intent.kind == 'defend_wave'
            or intent.kind == 'regroup_wave'
        then
            ExecuteCombatGroup(controller, intent, records, usedActors)
        elseif intent.actorToken and not usedActors[intent.actorToken] then
            local record = records[intent.actorToken]
            if record then
                local issued = false
                if intent.kind == 'build_structure' then
                    issued = ExecuteStructure(controller, intent, record)
                elseif intent.kind == 'assist_structure' then
                    issued = ExecuteAssistStructure(controller, intent, record, records)
                elseif intent.kind == 'factory_build' then
                    issued = ExecuteFactoryProduction(controller, intent, record)
                elseif intent.kind == 'factory_upgrade' then
                    issued = ESCALATION.ExecuteUpgrade(controller, intent, record)
                elseif intent.kind == 'rally' then
                    issued = ExecuteRally(controller, intent, record)
                elseif intent.kind == 'reclaim' then
                    issued = ExecuteReclaim(controller, intent, record)
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
        local completedMex = 0
        local completedFactories = 0
        local completedEngineers = 0
        local completedPgen = 0
        local completedHydro = 0
        local completedAa = 0
        local buildingMex = 0
        local buildingFactories = 0
        local buildingEngineers = 0
        local buildingPgen = 0
        local buildingHydro = 0
        local buildingCombat = 0
        local buildingAa = 0
        local assignedMinTargetDistance = -1
        local assignedMaxTargetDistance = -1
        for _, unit in ipairs(observation.units) do
            if unit.role == 'acu' then
                acu = unit
            elseif COMBAT_ROLES[unit.role] and unit.complete == true then
                combatTotal = combatTotal + 1
                if ESCALATION.antiAirRoles[unit.role] then
                    completedAa = completedAa + 1
                end
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
            elseif COMBAT_ROLES[unit.role] then
                buildingCombat = buildingCombat + 1
                if ESCALATION.antiAirRoles[unit.role] then
                    buildingAa = buildingAa + 1
                end
            end
        end
        for _, unit in ipairs(observation.units) do
            if unit.complete == true then
                if unit.role == 'mass_extractor' then completedMex = completedMex + 1 end
                if unit.role == 'land_factory'
                    or unit.role == 'land_factory_t2'
                    or unit.role == 'air_factory'
                then
                    completedFactories = completedFactories + 1
                end
                if unit.role == 'engineer' then completedEngineers = completedEngineers + 1 end
                if unit.role == 'power_generator' then completedPgen = completedPgen + 1 end
                if unit.role == 'hydrocarbon' then completedHydro = completedHydro + 1 end
            else
                if unit.role == 'mass_extractor' then buildingMex = buildingMex + 1 end
                if unit.role == 'land_factory'
                    or unit.role == 'land_factory_t2'
                    or unit.role == 'air_factory'
                then
                    buildingFactories = buildingFactories + 1
                end
                if unit.role == 'engineer' then buildingEngineers = buildingEngineers + 1 end
                if unit.role == 'power_generator' then buildingPgen = buildingPgen + 1 end
                if unit.role == 'hydrocarbon' then buildingHydro = buildingHydro + 1 end
            end
        end
        local oldestActor = 'none'
        local oldestKind = 'none'
        local oldestPhase = 'none'
        local oldestAge = -1
        local oldestDistance = -1
        local oldestFraction = -1
        local oldestProgressTick = -1
        local oldestDeadline = -1
        local oldestIssued = nil
        for _, token in ipairs(SortedKeys(controller.pending)) do
            local operation = controller.pending[token]
            local issued = tonumber(operation.issuedTick) or tick
            if oldestIssued == nil or issued < oldestIssued then
                oldestIssued = issued
                oldestActor = token
                oldestKind = tostring(operation.kind or 'none')
                oldestPhase = tostring(operation.phase or 'unknown')
                oldestAge = math.max(0, tick - issued)
                oldestDistance = tonumber(operation.lastDistance) or -1
                oldestFraction = tonumber(operation.lastFraction) or -1
                oldestProgressTick = tonumber(operation.lastProgressTick) or -1
                oldestDeadline = tonumber(operation.deadlineTick) or -1
            end
        end
        local firstIntent = intents[1] or {}
        local placements = observation.placements or {}
        local sites = observation.sites or {}
        local acuPosition = acu and acu.position or {}
        local economy = observation.economy or {}
        local macro = observation.macro or {}
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
            first_intent_reason = tostring(firstIntent.reason or 'none'),
            completed_mex = completedMex,
            completed_factories = completedFactories,
            completed_engineers = completedEngineers,
            completed_pgen = completedPgen,
            completed_hydro = completedHydro,
            completed_combat = combatTotal,
            completed_aa = completedAa,
            building_mex = buildingMex,
            building_factories = buildingFactories,
            building_engineers = buildingEngineers,
            building_pgen = buildingPgen,
            building_hydro = buildingHydro,
            building_combat = buildingCombat,
            building_aa = buildingAa,
            mass_income_per_tick = tonumber(economy.massIncome) or 0,
            mass_usage_per_tick = tonumber(economy.massUsage) or 0,
            mass_requested_per_tick = tonumber(economy.massRequested) or 0,
            mass_trend_per_tick = tonumber(economy.massTrend) or 0,
            mass_stored_ratio = tonumber(economy.massStoredRatio) or 0,
            unused_mass_per_tick = tonumber(economy.unusedMass) or 0,
            rebuild_jobs = tonumber(macro.activeRebuildJobs) or 0,
            frontier_jobs = tonumber(macro.activeFrontierJobs) or 0,
            reclaim_jobs = tonumber(macro.activeReclaimJobs) or 0,
            owned_mex = tonumber(macro.ownedMexCount) or 0,
            lost_mex = tonumber(macro.lostMexCount) or 0,
            rebuilt_mex = tonumber(macro.rebuiltMexCount) or 0,
            frontier_cluster = tostring(macro.selectedFrontierCluster or 'none'),
            frontier_site = tostring(macro.selectedFrontierSite or 'none'),
            frontier_progress = tonumber(macro.frontierProgress) or -1,
            frontier_screen = tonumber(macro.frontierScreenCount) or 0,
            home_reserve = tonumber(macro.homeReserveCount) or 0,
            campaign_state = tostring(macro.campaignState or 'idle'),
            campaign_kind = tostring(macro.campaignKind or 'none'),
            campaign_cluster = tostring(macro.campaignCluster or 'none'),
            campaign_objective = tostring(macro.campaignObjective or 'none'),
            stable_anchor_key = tostring(macro.campaignAnchorKey or 'none'),
            stable_anchor_x = tonumber(macro.campaignAnchorX) or -1,
            stable_anchor_z = tonumber(macro.campaignAnchorZ) or -1,
            field_units = tonumber(macro.fieldUnits) or 0,
            field_aa = tonumber(macro.fieldAa) or 0,
            field_at_anchor = tonumber(macro.fieldAtAnchor) or 0,
            field_arrival_quorum = tonumber(macro.campaignArrivalQuorum) or 0,
            forward_distance = tonumber(macro.campaignForwardDistance) or -1,
            home_units = tonumber(macro.homeUnits) or 0,
            home_aa = tonumber(macro.homeAa) or 0,
            mission_age = tonumber(macro.campaignMissionAge) or -1,
            last_campaign_progress_tick = tonumber(
                macro.campaignLastProgressTick
            ) or -1,
            full_field_orders = tonumber(macro.campaignFullFieldOrders) or 0,
            reinforcement_orders = tonumber(
                macro.campaignReinforcementOrders
            ) or 0,
            recovery_orders = tonumber(macro.campaignRecoveryOrders) or 0,
            mode_switches = tonumber(macro.campaignModeSwitches) or 0,
            campaign_emergency = macro.campaignEmergency == true,
            route_state = tostring(macro.campaignRouteState or 'none'),
            route_source = tostring(macro.campaignRouteSource or 'none'),
            route_destination = tostring(
                macro.campaignRouteDestination or 'none'
            ),
            route_probe_units = tonumber(macro.campaignRouteProbeUnits) or 0,
            route_probe_quorum = tonumber(macro.campaignRouteProbeQuorum) or 0,
            route_at_destination = tonumber(
                macro.campaignRouteAtDestination
            ) or 0,
            route_age = tonumber(macro.campaignRouteAge) or -1,
            route_last_progress_tick = tonumber(
                macro.campaignRouteLastProgressTick
            ) or -1,
            route_epoch = tonumber(macro.campaignRouteEpoch) or -1,
            route_key = tostring(macro.campaignRouteKey or 'none'),
            route_fingerprint = tostring(
                macro.campaignRouteFingerprint or 'none'
            ),
            route_waypoints = tonumber(macro.campaignRouteWaypointCount) or 0,
            route_length = tonumber(macro.campaignRouteLength) or -1,
            route_progress_age = tonumber(
                macro.campaignRouteProgressAge
            ) or -1,
            route_release_age = tonumber(
                macro.campaignRouteReleaseAge
            ) or -1,
            route_last_failure = tostring(
                macro.campaignRouteLastFailure or 'none'
            ),
            route_blocked = tonumber(macro.campaignRouteBlockedCount) or 0,
            engineer_demand = tonumber(macro.engineerDemand) or 0,
            factory_demand = tonumber(macro.factoryDemand) or 0,
            economy_stage = tostring(macro.economyStage or 'opening'),
            factory_target = tonumber(macro.factoryTarget) or 0,
            recurring_mass_income_per_tick = tonumber(
                macro.recurringMassIncome) or 0,
            recurring_energy_income_per_tick = tonumber(
                macro.recurringEnergyIncome) or 0,
            rolling_mass_requested_per_tick = tonumber(
                macro.rollingMassRequested) or 0,
            rolling_energy_requested_per_tick = tonumber(
                macro.rollingEnergyRequested) or 0,
            rolling_mass_usage_per_tick = tonumber(
                macro.rollingMassUsage) or 0,
            rolling_energy_usage_per_tick = tonumber(
                macro.rollingEnergyUsage) or 0,
            rolling_mass_stored_ratio = tonumber(
                macro.rollingMassStoredRatio) or 0,
            rolling_energy_stored_ratio = tonumber(
                macro.rollingEnergyStoredRatio) or 0,
            rolling_mass_trend_per_tick = tonumber(
                macro.rollingMassTrend) or 0,
            rolling_energy_trend_per_tick = tonumber(
                macro.rollingEnergyTrend) or 0,
            mass_demand_satisfaction = tonumber(
                macro.massDemandSatisfaction) or 0,
            energy_demand_satisfaction = tonumber(
                macro.energyDemandSatisfaction) or 0,
            active_committed_mass_per_tick = tonumber(
                macro.activeCommittedMassDrain) or 0,
            active_committed_energy_per_tick = tonumber(
                macro.activeCommittedEnergyDrain) or 0,
            committed_mass_expansion_per_tick = tonumber(
                macro.committedMassExpansion) or 0,
            committed_energy_expansion_per_tick = tonumber(
                macro.committedEnergyExpansion) or 0,
            committed_mass_energy_per_tick = tonumber(
                macro.committedMassEnergy) or 0,
            committed_energy_energy_per_tick = tonumber(
                macro.committedEnergyEnergy) or 0,
            committed_mass_engineer_per_tick = tonumber(
                macro.committedMassEngineer) or 0,
            committed_energy_engineer_per_tick = tonumber(
                macro.committedEnergyEngineer) or 0,
            committed_mass_factory_per_tick = tonumber(
                macro.committedMassFactory) or 0,
            committed_energy_factory_per_tick = tonumber(
                macro.committedEnergyFactory) or 0,
            committed_mass_air_per_tick = tonumber(
                macro.committedMassAir) or 0,
            committed_energy_air_per_tick = tonumber(
                macro.committedEnergyAir) or 0,
            committed_mass_tech_per_tick = tonumber(
                macro.committedMassTech) or 0,
            committed_energy_tech_per_tick = tonumber(
                macro.committedEnergyTech) or 0,
            committed_mass_construction_per_tick = tonumber(
                macro.committedMassConstruction) or 0,
            committed_energy_construction_per_tick = tonumber(
                macro.committedEnergyConstruction) or 0,
            one_time_mass_reserve = tonumber(macro.oneTimeMassReserve) or 0,
            one_time_energy_reserve = tonumber(macro.oneTimeEnergyReserve) or 0,
            reclaim_windfall_mass = tonumber(macro.reclaimedMassDelta) or 0,
            allocator_denied_request = tostring(
                macro.allocatorDeniedRequest or 'none'),
            allocator_denied_reason = tostring(
                macro.allocatorDeniedReason or 'none'),
            expansion_opportunities = tonumber(
                macro.expansionOpportunityCount) or 0,
            expansion_scheduled = tonumber(
                macro.expansionScheduledCount) or 0,
            engineer_target = tonumber(macro.engineerTarget) or 0,
            factory_funded = tonumber(macro.factoryFundedCount) or 0,
            factory_idle = tonumber(macro.factoryIdleCount) or 0,
            tech_eta_ticks = tonumber(macro.techEtaTicks) or -1,
            tech_admission = tostring(macro.techAdmission or 'none'),
            land_t1_completed = tonumber(macro.completedLandT1Factories) or 0,
            land_t1_building = tonumber(macro.buildingLandT1Factories) or 0,
            air_t1_completed = tonumber(macro.completedAirT1Factories) or 0,
            air_t1_building = tonumber(macro.buildingAirT1Factories) or 0,
            land_t2_completed = tonumber(macro.completedLandT2Factories) or 0,
            land_t2_building = tonumber(macro.buildingLandT2Factories) or 0,
            placement_capacity = tonumber(macro.placementCapacity) or 0,
            placement_probes = tonumber(macro.placementProbeCount) or 0,
            upgrade_state = tostring(macro.upgradeState or 'none'),
            air_screen = tonumber(macro.airScreenCount) or 0,
            reclaim_candidate_value = tonumber(macro.reclaimValue) or -1,
            campaign_ready = macro.campaignReady == true,
            campaign_readiness_blockers = tostring(
                macro.campaignReadinessBlocker or 'none'
            ),
            rollback_reason = tostring(macro.rollbackReason or 'none'),
            field_attrition_lost = tonumber(macro.fieldAttritionLost) or 0,
            field_attrition_window = tonumber(macro.fieldAttritionWindow) or 0,
            reclaim_target = tostring(macro.reclaimTarget or 'none'),
            reclaim_value = tonumber(macro.reclaimValue) or -1,
            oldest_job_actor = oldestActor,
            oldest_job_kind = oldestKind,
            oldest_job_phase = oldestPhase,
            oldest_job_age = oldestAge,
            oldest_job_remaining_distance = oldestDistance,
            oldest_job_fraction = oldestFraction,
            oldest_job_last_progress_tick = oldestProgressTick,
            oldest_job_deadline = oldestDeadline,
            mass_produced_total = SafeArmyStat(
                controller.brain,
                'Economy_TotalProduced_Mass'
            ),
            mass_consumed_total = SafeArmyStat(
                controller.brain,
                'Economy_TotalConsumed_Mass'
            ),
            mass_reclaimed_total = SafeArmyStat(
                controller.brain,
                'Economy_Reclaimed_Mass'
            ),
            mass_excess_total = SafeArmyStat(
                controller.brain,
                'Economy_AccumExcess_Mass'
            ),
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
