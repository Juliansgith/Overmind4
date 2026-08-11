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

local PLACEMENT_FOUNDATION_ROLES = {
    land_factory = true,
    power_generator = true,
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

local function ArrayContains(values, wanted)
    for _, value in ipairs(values or {}) do
        if value == wanted then return true end
    end
    return false
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
    for _, index in ipairs({ 1, 3 }) do
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
            engineerReachable = marker.engineerReachable ~= false and marker.reachable == true,
            landReachable = marker.landReachable ~= false and marker.reachable == true,
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
        if PLACEMENT_FOUNDATION_ROLES[unit.role] == true
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

local function UpdateMassSurplus(controller, economy)
    local income = tonumber(economy.massIncome) or 0
    local requested = tonumber(economy.massRequested) or tonumber(economy.massUsage) or 0
    local trend = tonumber(economy.massTrend) or 0
    local stored = tonumber(economy.massStoredRatio) or 0
    local unused = math.max(0, income - requested)
    economy.unusedMass = unused
    local healthy = requested <= income
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

local function MacroSnapshot(controller, units)
    local rebuildJobs = 0
    local frontierJobs = 0
    local reclaimJobs = 0
    local structureJobs = 0
    local constructionWork = {}
    local factoryWork = {}
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
        if foundation.role == 'land_factory' then factoryWork[key] = true end
    end
    for _, operation in pairs(controller.pending or {}) do
        if StructureOperation(operation) then
            structureJobs = structureJobs + 1
            if operation.reason == 'rebuild_mex' then rebuildJobs = rebuildJobs + 1 end
            if operation.reason == 'frontier_expansion' then frontierJobs = frontierJobs + 1 end
            local key = StructureWorkKey(controller, operation)
            constructionWork[key] = true
            if operation.buildRole == 'land_factory' then factoryWork[key] = true end
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
    local engineerDemand = math.max(2, 2 + math.floor((constructionBacklog + 1) / 2))
    local factories = CountRole(units, 'land_factory') + CountArray(factoryWork)
    local factoryDemand = math.max(2, factories)
    if controller.massSurplusTicks >= MASS_SURPLUS_TICKS then
        factoryDemand = factoryDemand + 1
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
    local campaignState = campaign and campaign.state or 'idle'
    local campaignCluster = campaign and campaign.clusterKey or 'none'
    local campaignObjective = campaign and campaign.objectiveKey or 'none'
    local fieldTokens = campaign
        and type(campaign.fieldTokens) == 'table'
        and CopyArray(campaign.fieldTokens)
        or {}
    local homeTokens = campaign
        and type(campaign.homeTokens) == 'table'
        and CopyArray(campaign.homeTokens)
        or {}
    local fieldAa = 0
    local homeAa = 0
    local fieldAtAnchor = 0
    local objectivePosition = campaign and campaign.objectivePosition or nil
    for _, unit in ipairs(units or {}) do
        if unit.complete == true and COMBAT_ROLES[unit.role] then
            if CampaignFieldContains(campaign, unit.token) then
                if unit.role == 'anti_air' then fieldAa = fieldAa + 1 end
                if objectivePosition
                    and Distance(unit.position, objectivePosition)
                        <= FIELD_CAMPAIGN_ANCHOR_RADIUS
                then
                    fieldAtAnchor = fieldAtAnchor + 1
                end
            elseif CampaignHomeContains(campaign, unit.token)
                and unit.role == 'anti_air'
            then
                homeAa = homeAa + 1
            end
        end
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
        engineerDemand = engineerDemand,
        factoryDemand = factoryDemand,
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
        campaignCluster = campaignCluster,
        campaignObjective = campaignObjective,
        campaignMemberKeys = campaign and CopyArray(campaign.memberKeys) or {},
        fieldTokens = fieldTokens,
        homeTokens = homeTokens,
        fieldUnits = TableGetn(fieldTokens),
        fieldAa = fieldAa,
        fieldAtAnchor = fieldAtAnchor,
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
        campaignModeSwitches = campaign
            and (tonumber(campaign.modeSwitches) or 0)
            or 0,
        campaignEmergency = campaign and campaign.emergency == true or false,
        campaignIntentMode = campaign
            and controller.legacyFrontierRetirementPending ~= true
            and campaign.pendingMode
            or 'none',
        campaignIntentTokens = campaign
            and controller.legacyFrontierRetirementPending ~= true
            and CopyArray(campaign.pendingTokens)
            or {},
        campaignIntentEngineer = campaign
            and (campaign.desiredEngineerToken or campaign.engineerToken)
            or 'none',
        campaignIntentCluster = campaign
            and (campaign.desiredClusterKey or campaign.clusterKey)
            or 'none',
        campaignIntentObjective = campaign
            and (campaign.desiredObjectiveKey or campaign.objectiveKey)
            or 'none',
        campaignIntentPosition = campaign
            and CopyPosition(campaign.desiredObjectivePosition
                or campaign.objectivePosition)
            or nil,
        campaignSerial = campaign and campaign.serial or -1,
    }
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
    elseif intent.kind == 'factory_build' then
        phase = 'building'
    end
    local operation = {
        actorToken = intent.actorToken,
        kind = intent.kind,
        buildRole = intent.buildRole,
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
    if intent.buildRole == 'land_factory'
        and intent.reason == 'production_saturation'
    then
        controller.massSurplusSinceTick = nil
        controller.massSurplusTicks = 0
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
        if not existingMission or recordByToken[tokens[1]].role ~= 'anti_air' then
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
            if record.role == 'anti_air' then screenHasAntiAir = true end
            if token == displacedToken then
                if record.role == 'anti_air' then return false end
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
        if record.role == 'anti_air' then antiAir = antiAir + 1 end
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
        if record.role == 'anti_air'
            and TableGetn(field) < fieldTarget
            and TableGetn(field) < fieldAaTarget
        then
            selected[record.token] = true
            TableInsert(field, record.token)
        end
    end
    for _, record in ipairs(records) do
        if TableGetn(field) < fieldTarget
            and record.role ~= 'anti_air'
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
        if selected[record.token] and record.role == 'anti_air' then
            fieldAa = fieldAa + 1
        end
    end
    for _, record in ipairs(records) do
        if TableGetn(field) < fieldTarget
            and fieldAa < fieldAaTarget
            and record.role == 'anti_air'
            and not selected[record.token]
        then
            selected[record.token] = true
            TableInsert(field, record.token)
            fieldAa = fieldAa + 1
        end
    end
    for _, record in ipairs(records) do
        if TableGetn(field) < fieldTarget
            and record.role ~= 'anti_air'
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

local function CampaignMemberKeys(controller, clusterKey, siteKey)
    local members = {}
    for _, site in ipairs((controller.currentSites and controller.currentSites.mass) or {}) do
        if site.key == siteKey or site.clusterKey == clusterKey then
            TableInsert(members, site.key)
        end
    end
    if TableGetn(members) == 0 and type(siteKey) == 'string' then
        TableInsert(members, siteKey)
    end
    table.sort(members)
    return members
end

local function CampaignSite(controller, siteKey)
    for _, site in ipairs((controller.currentSites and controller.currentSites.mass) or {}) do
        if site.key == siteKey then return site end
    end
    return nil
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
        if operation.reason == 'rebuild_mex'
            and ValidCampaignOperation(controller, observation, operation)
        then
            return operation
        end
    end
    for _, token in ipairs(SortedKeys(controller.pending)) do
        local operation = controller.pending[token]
        if operation.reason == 'frontier_expansion'
            and ValidCampaignOperation(controller, observation, operation)
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

local function StartFieldCampaign(controller, observation, operation)
    local records = CampaignCombatRecords(observation.units)
    local field, home, full = InitialCampaignCohorts(records)
    controller.fieldCampaignSerial = (tonumber(controller.fieldCampaignSerial) or 0) + 1
    local tick = CurrentTick(controller)
    local record = CampaignOperationRecord(observation, operation)
    local clusterKey = operation.clusterKey
        or controller.selectedFrontierCluster
        or operation.siteKey
    -- Factories may still carry the legacy frontier rally ledger when the
    -- secured campaign doctrine first takes ownership.  Force one base-rally
    -- reconciliation under the new doctrine.
    controller.rallied = {}
    local campaign = {
        serial = controller.fieldCampaignSerial,
        state = full and 'awaiting_order' or 'early_awaiting_order',
        clusterKey = tostring(clusterKey),
        objectiveKey = operation.siteKey,
        objectivePosition = CopyPosition(operation.position),
        objectiveReason = operation.reason,
        engineerToken = operation.actorToken,
        engineerRole = record.role,
        memberKeys = CampaignMemberKeys(controller, clusterKey, operation.siteKey),
        fieldTokens = field,
        homeTokens = home,
        fieldTokenSet = BuildTokenSet(field),
        homeTokenSet = BuildTokenSet(home),
        orderedTokens = {},
        fullCohorts = full,
        startedTick = tick,
        lastProgressTick = tick,
        bestDistance = Distance(record.position, operation.position),
        lastRecoveryAttemptTick = tick - FIELD_CAMPAIGN_STUCK_TICKS,
        heldSinceTick = nil,
        healthySinceTick = nil,
        emergency = false,
        emergencyReason = nil,
        fullFieldOrders = 0,
        reinforcementOrders = 0,
        recoveryOrders = 0,
        modeSwitches = 0,
    }
    controller.fieldCampaign = campaign
    if TableGetn(field) > 0 then CampaignSetPending(campaign, 'activate', field) end
    Emit(controller, 'campaign_started', {
        cluster = campaign.clusterKey,
        objective = campaign.objectiveKey,
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

local function CampaignPruneAndFill(campaign, units, allowRecalledUpgrade)
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
        and (campaign.state ~= 'recalled' or allowRecalledUpgrade == true)
    then
        local fieldSet = {}
        local fieldAa = 0
        for _, token in ipairs(field) do
            fieldSet[token] = true
            if byToken[token].role == 'anti_air' then fieldAa = fieldAa + 1 end
        end
        for _, record in ipairs(records) do
            if TableGetn(field) < fieldTarget
                and fieldAa < fieldAaTarget
                and record.role == 'anti_air'
                and not fieldSet[record.token]
            then
                fieldSet[record.token] = true
                TableInsert(field, record.token)
                fieldAa = fieldAa + 1
            end
        end
        for _, record in ipairs(records) do
            if TableGetn(field) < fieldTarget
                and record.role ~= 'anti_air'
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
        campaign.orderedTokens = {}
        for _, token in ipairs(field) do assigned[token] = true end
        for _, record in ipairs(records) do
            if not assigned[record.token] then
                assigned[record.token] = true
                TableInsert(home, record.token)
            end
        end
        campaign.fullCohorts = true
        if previousPendingMode == 'activate'
            or previousPendingMode == 'retarget'
            or previousPendingMode == 'transition'
            or previousPendingMode == 'recover'
            or previousPendingMode == 'recall'
            or previousPendingMode == 'resume'
        then
            CampaignSetPending(campaign, previousPendingMode, field)
        elseif previousState == 'active'
            or previousState == 'awaiting_order'
            or previousState == 'early_awaiting_order'
        then
            campaign.state = 'awaiting_order'
            CampaignSetPending(campaign, 'activate', field)
        end
    else
        local fieldAa = 0
        for _, token in ipairs(field) do
            if byToken[token].role == 'anti_air' then fieldAa = fieldAa + 1 end
        end
        for _, record in ipairs(records) do
            if not assigned[record.token] then
                local fieldDeficit = fieldTarget - TableGetn(field)
                local homeDeficit = (TableGetn(records) - fieldTarget) - TableGetn(home)
                local chooseField = false
                if campaign.state ~= 'recalled'
                    and record.role == 'anti_air'
                    and fieldDeficit > 0
                    and fieldAa < fieldAaTarget
                then
                    chooseField = true
                elseif campaign.state ~= 'recalled'
                    and fieldDeficit > homeDeficit
                then
                    chooseField = true
                end
                if chooseField then
                    TableInsert(field, record.token)
                    if record.role == 'anti_air' then fieldAa = fieldAa + 1 end
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
        or campaign.pendingMode == 'retarget'
        or campaign.pendingMode == 'transition'
        or campaign.pendingMode == 'recover'
        or campaign.pendingMode == 'recall'
        or campaign.pendingMode == 'resume'
    then
        CampaignSetPending(campaign, campaign.pendingMode, field)
    elseif campaign.pendingMode == 'reinforce' then
        local unordered = {}
        for _, token in ipairs(field) do
            if campaign.orderedTokens[token] ~= true then TableInsert(unordered, token) end
        end
        CampaignSetPending(campaign, 'reinforce', unordered)
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

local function RelevantCampaignOperation(controller, observation, campaign)
    for _, token in ipairs(SortedKeys(controller.pending)) do
        local operation = controller.pending[token]
        if operation.reason == 'rebuild_mex'
            and ArrayContains(campaign.memberKeys, operation.siteKey)
            and ValidCampaignOperation(controller, observation, operation)
        then
            return operation
        end
    end
    for _, token in ipairs(SortedKeys(controller.pending)) do
        local operation = controller.pending[token]
        if operation.reason == 'rebuild_mex'
            and ValidCampaignOperation(controller, observation, operation)
        then
            return operation
        end
    end
    for _, token in ipairs(SortedKeys(controller.pending)) do
        local operation = controller.pending[token]
        if ValidCampaignOperation(controller, observation, operation)
            and (operation.siteKey == campaign.objectiveKey
                or (operation.reason == 'frontier_expansion'
                    and (operation.clusterKey == campaign.clusterKey
                        or ArrayContains(campaign.memberKeys, operation.siteKey))))
        then
            return operation
        end
    end
    return nil
end

local function CampaignClusterComplete(controller, campaign)
    if TableGetn(campaign.memberKeys or {}) == 0 then return false end
    for _, siteKey in ipairs(campaign.memberKeys) do
        local site = CampaignSite(controller, siteKey)
        if not site or site.complete ~= true then return false end
    end
    return true
end

local function CampaignTargetInvalid(controller, siteKey, position)
    return not CampaignSiteSupportsPosition(controller, siteKey, position)
end

local function CampaignObjectiveInvalid(controller, campaign)
    return CampaignTargetInvalid(
        controller,
        campaign.objectiveKey,
        campaign.objectivePosition
    )
end

local function AwaitCampaignObjective(controller, campaign, reason)
    if campaign.state == 'awaiting_objective' then return end
    campaign.state = 'awaiting_objective'
    campaign.pendingMode = nil
    campaign.pendingTokens = {}
    campaign.heldSinceTick = nil
    campaign.awaitingReason = reason or 'unknown'
    Emit(controller,
        reason == 'cluster_held' and 'campaign_held' or 'campaign_objective_released',
        {
            cluster = campaign.clusterKey or 'none',
            objective = campaign.objectiveKey or 'none',
            reason = reason or 'unknown',
        }
    )
end

local function SetDesiredCampaignObjective(controller, observation, campaign, operation)
    local record = CampaignOperationRecord(observation, operation)
    if not record then return false end
    local clusterKey = operation.clusterKey
        or controller.selectedFrontierCluster
        or operation.siteKey
    campaign.desiredObjectiveKey = operation.siteKey
    campaign.desiredObjectivePosition = CopyPosition(operation.position)
    campaign.desiredObjectiveReason = operation.reason
    campaign.desiredEngineerToken = operation.actorToken
    campaign.desiredEngineerRole = record.role
    campaign.desiredClusterKey = tostring(clusterKey)
    campaign.desiredMemberKeys = CampaignMemberKeys(
        controller,
        clusterKey,
        operation.siteKey
    )
    return true
end

local function ClearDesiredCampaignObjective(campaign)
    campaign.desiredObjectiveKey = nil
    campaign.desiredObjectivePosition = nil
    campaign.desiredObjectiveReason = nil
    campaign.desiredEngineerToken = nil
    campaign.desiredEngineerRole = nil
    campaign.desiredClusterKey = nil
    campaign.desiredMemberKeys = nil
    campaign.desiredReplacesCampaign = nil
end

local function PendingCampaignOperationValid(controller, campaign)
    local mode = campaign.pendingMode
    if mode ~= 'activate'
        and mode ~= 'retarget'
        and mode ~= 'transition'
        and mode ~= 'recover'
        and mode ~= 'resume'
    then
        return true
    end
    local token = campaign.desiredEngineerToken or campaign.engineerToken
    local siteKey = campaign.desiredObjectiveKey or campaign.objectiveKey
    local reason = campaign.desiredObjectiveReason or campaign.objectiveReason
    local position = campaign.desiredObjectivePosition or campaign.objectivePosition
    local operation = token and controller.pending[token] or nil
    return StructureOperation(operation)
        and operation.actorToken == token
        and operation.siteKey == siteKey
        and operation.buildRole == 'mass_extractor'
        and operation.reason == reason
        and IsCampaignPosition(operation.position)
        and IsCampaignPosition(position)
        and DistanceSquared(operation.position, position) <= 0.01
        and CampaignSiteSupportsPosition(controller, siteKey, position)
        and operation.phase ~= 'cancelling'
        and operation.cancelReason == nil
end

local function AdoptCampaignOperation(controller, observation, campaign, operation)
    local record = CampaignOperationRecord(observation, operation)
    if not record then return false end
    local clusterKey = operation.clusterKey
        or controller.selectedFrontierCluster
        or operation.siteKey
    campaign.clusterKey = tostring(clusterKey)
    campaign.memberKeys = CampaignMemberKeys(
        controller,
        clusterKey,
        operation.siteKey
    )
    campaign.objectiveKey = operation.siteKey
    campaign.objectivePosition = CopyPosition(operation.position)
    campaign.objectiveReason = operation.reason
    campaign.engineerToken = operation.actorToken
    campaign.engineerRole = record.role
    ClearDesiredCampaignObjective(campaign)
    return true
end

local function UpdateCampaignProgress(controller, observation, campaign, operation)
    if not operation then return end
    local operationProgressTick = tonumber(operation.lastProgressTick)
    if operationProgressTick
        and operationProgressTick > (tonumber(campaign.lastProgressTick) or -1)
    then
        campaign.lastProgressTick = operationProgressTick
    end
    local record = CampaignOperationRecord(observation, operation)
    if not record then return end
    local distance = Distance(record.position, operation.position)
    if distance + 2 < (tonumber(campaign.bestDistance) or 1000000000000) then
        campaign.bestDistance = distance
        campaign.lastProgressTick = CurrentTick(controller)
    end
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
        if candidate then StartFieldCampaign(controller, observation, candidate) end
        campaign = controller.fieldCampaign
        ApplyCampaignFlags(controller, campaign, observation.units)
        return
    end

    local tick = CurrentTick(controller)
    local health = CampaignAcuHealth(observation)
    local immediateContact = observation.enemyContact ~= nil
        and observation.enemyContact.immediate == true
    CampaignPruneAndFill(campaign, observation.units, false)
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
        and health ~= nil
        and health >= FIELD_CAMPAIGN_RESUME_HEALTH
        and reserveSafe
        and campaign.healthySinceTick ~= nil
        and tick - campaign.healthySinceTick >= FIELD_CAMPAIGN_RESUME_TICKS
    if allowRecalledUpgrade then
        CampaignPruneAndFill(campaign, observation.units, true)
    end
    ApplyCampaignFlags(controller, campaign, observation.units)
    if immediateContact
        and TableGetn(campaign.homeTokens) < HOME_RESERVE_MIN
        and TableGetn(campaign.fieldTokens) > 0
    then
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
    if campaign.state == 'recalled' then
        if campaign.pendingMode == 'resume' then
            campaign.pendingMode = nil
            campaign.pendingTokens = {}
        end
        ClearDesiredCampaignObjective(campaign)
        local currentObjectiveInvalid = CampaignObjectiveInvalid(
            controller,
            campaign
        )
        local resumeOperation = nil
        if currentObjectiveInvalid then
            resumeOperation = CampaignCandidate(controller, observation)
        else
            resumeOperation = RelevantCampaignOperation(
                controller,
                observation,
                campaign
            )
        end
        if resumeOperation
            and (resumeOperation.siteKey ~= campaign.objectiveKey
                or resumeOperation.actorToken ~= campaign.engineerToken
                or resumeOperation.reason ~= campaign.objectiveReason
                or not IsCampaignPosition(resumeOperation.position)
                or DistanceSquared(
                    resumeOperation.position,
                    campaign.objectivePosition
                ) > 0.01)
        then
            local desired = SetDesiredCampaignObjective(
                controller,
                observation,
                campaign,
                resumeOperation
            )
            if desired then
                campaign.desiredReplacesCampaign = currentObjectiveInvalid == true
            end
        end
        local resumeToken = campaign.desiredEngineerToken or campaign.engineerToken
        local resumeRole = campaign.desiredEngineerRole or campaign.engineerRole
        local resumeSiteKey = campaign.desiredObjectiveKey or campaign.objectiveKey
        local resumePosition = campaign.desiredObjectivePosition
            or campaign.objectivePosition
        local resumeObjectiveInvalid = CampaignTargetInvalid(
            controller,
            resumeSiteKey,
            resumePosition
        )
        local resumeRecord = nil
        for _, record in ipairs(observation.units or {}) do
            if record.token == resumeToken
                and record.role == resumeRole
                and record.complete == true
            then
                resumeRecord = record
                break
            end
        end
        if health
            and health >= FIELD_CAMPAIGN_RESUME_HEALTH
            and reserveSafe
        then
            if campaign.healthySinceTick == nil then campaign.healthySinceTick = tick end
            if tick - campaign.healthySinceTick >= FIELD_CAMPAIGN_RESUME_TICKS
                and TableGetn(campaign.fieldTokens) > 0
                and resumeOperation ~= nil
                and resumeRecord ~= nil
                and not resumeObjectiveInvalid
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
    if health and health < FIELD_CAMPAIGN_RECALL_HEALTH
        and TableGetn(campaign.fieldTokens) > 0
    then
        campaign.pendingEmergencyReason = 'acu_health'
        campaign.pendingRecallFieldTokens = nil
        campaign.pendingRecallHomeTokens = nil
        CampaignSetPending(campaign, 'recall', campaign.fieldTokens)
        return
    end
    if campaign.state == 'awaiting_objective' then
        campaign.pendingMode = nil
        campaign.pendingTokens = {}
        ClearDesiredCampaignObjective(campaign)
        local candidate = CampaignCandidate(controller, observation)
        if candidate
            and SetDesiredCampaignObjective(
                controller,
                observation,
                campaign,
                candidate
            )
        then
            CampaignSetPending(campaign, 'transition', campaign.fieldTokens)
        end
        return
    end
    if not PendingCampaignOperationValid(controller, campaign) then
        local failedMode = campaign.pendingMode
        campaign.pendingMode = nil
        campaign.pendingTokens = {}
        ClearDesiredCampaignObjective(campaign)
        if failedMode == 'activate' then
            local replacement = CampaignCandidate(controller, observation)
            if replacement
                and AdoptCampaignOperation(
                    controller,
                    observation,
                    campaign,
                    replacement
                )
            then
                CampaignSetPending(campaign, 'activate', campaign.fieldTokens)
                return
            end
            AwaitCampaignObjective(controller, campaign, 'operation_missing')
            return
        elseif failedMode == 'transition' then
            AwaitCampaignObjective(controller, campaign, 'operation_missing')
            return
        end
    end
    if CampaignObjectiveInvalid(controller, campaign) then
        AwaitCampaignObjective(controller, campaign, 'objective_invalid')
        return
    end

    if CampaignClusterComplete(controller, campaign) then
        if campaign.heldSinceTick == nil then campaign.heldSinceTick = tick end
        campaign.state = 'holding'
        campaign.pendingMode = nil
        campaign.pendingTokens = {}
        if tick - campaign.heldSinceTick >= FIELD_CAMPAIGN_HOLD_TICKS then
            AwaitCampaignObjective(controller, campaign, 'cluster_held')
        end
        return
    end
    campaign.heldSinceTick = nil
    if campaign.state == 'holding' then campaign.state = 'active' end

    local operation = RelevantCampaignOperation(controller, observation, campaign)
    UpdateCampaignProgress(controller, observation, campaign, operation)
    if campaign.pendingMode == 'activate'
        or campaign.pendingMode == 'retarget'
        or campaign.pendingMode == 'recover'
    then
        return
    end
    if operation
        and (operation.siteKey ~= campaign.objectiveKey
            or operation.actorToken ~= campaign.engineerToken)
    then
        if SetDesiredCampaignObjective(
            controller,
            observation,
            campaign,
            operation
        ) then
            CampaignSetPending(campaign, 'retarget', campaign.fieldTokens)
        end
        return
    end
    if operation
        and campaign.state == 'active'
        and tick - (tonumber(campaign.lastProgressTick) or tick)
            >= FIELD_CAMPAIGN_STUCK_TICKS
        and tick - (tonumber(campaign.lastRecoveryAttemptTick) or -1000000)
            >= FIELD_CAMPAIGN_STUCK_TICKS
        and TableGetn(campaign.fieldTokens) > 0
    then
        CampaignSetPending(campaign, 'recover', campaign.fieldTokens)
        return
    end
    if campaign.state == 'active' then
        local unordered = {}
        for _, token in ipairs(campaign.fieldTokens) do
            if campaign.orderedTokens[token] ~= true then TableInsert(unordered, token) end
        end
        if TableGetn(unordered) > 0 then
            CampaignSetPending(campaign, 'reinforce', unordered)
        end
    elseif operation
        and TableGetn(campaign.fieldTokens) > 0
        and campaign.pendingMode == nil
    then
        CampaignSetPending(campaign, 'activate', campaign.fieldTokens)
    end
end

local function CampaignExpectedPosition(controller, campaign, mode)
    if mode == 'recall' then return CopyPosition(controller.basePosition) end
    return CopyPosition(campaign.desiredObjectivePosition or campaign.objectivePosition)
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

local function ExecuteFieldCampaign(controller, intent, recordByToken, usedActors)
    local campaign = controller.fieldCampaign
    if controller.fieldCampaignEnabled ~= true
        or controller.legacyFrontierRetirementPending == true
        or controller.frontierMission ~= nil
        or not campaign
        or type(intent.mode) ~= 'string'
        or intent.mode ~= campaign.pendingMode
        or type(intent.campaignSerial) ~= 'number'
        or intent.campaignSerial ~= campaign.serial
        or type(intent.clusterKey) ~= 'string'
        or intent.clusterKey
            ~= (campaign.desiredClusterKey or campaign.clusterKey)
        or type(intent.objectiveKey) ~= 'string'
        or intent.objectiveKey
            ~= (campaign.desiredObjectiveKey or campaign.objectiveKey)
        or type(intent.actorTokens) ~= 'table'
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
        TableInsert(actors, actor)
    end

    local guard = nil
    if intent.mode ~= 'recall' then
        local guardToken = campaign.desiredEngineerToken or campaign.engineerToken
        local guardRole = campaign.desiredEngineerRole or campaign.engineerRole
        if intent.engineerToken ~= guardToken then return false end
        guard = LiveOwnedActor(
            controller,
            guardToken,
            recordByToken[guardToken],
            guardRole
        )
        if not guard then return false end
        local operation = controller.pending[guardToken]
        local expectedKey = campaign.desiredObjectiveKey
            or campaign.objectiveKey
        local expectedReason = campaign.desiredObjectiveReason
            or campaign.objectiveReason
        if not StructureOperation(operation)
            or operation.actorToken ~= guardToken
            or operation.siteKey ~= expectedKey
            or operation.buildRole ~= 'mass_extractor'
            or operation.reason ~= expectedReason
            or not IsCampaignPosition(operation.position)
            or DistanceSquared(operation.position, expectedPosition) > 0.01
            or not CampaignSiteSupportsPosition(
                controller,
                expectedKey,
                expectedPosition
            )
            or operation.phase == 'cancelling'
            or operation.cancelReason ~= nil
        then
            return false
        end
    end

    local clearOk = pcall(function() IssueClearCommands(actors) end)
    if not clearOk then return false end
    local orderOk = false
    if intent.mode == 'recall' then
        orderOk = pcall(function() IssueMove(actors, expectedPosition) end)
    else
        orderOk = pcall(function() IssueGuard(actors, guard) end)
    end
    if not orderOk then
        pcall(function() IssueClearCommands(actors) end)
        return false
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
    elseif mode == 'reinforce' then
        campaign.reinforcementOrders = campaign.reinforcementOrders + 1
    elseif mode == 'retarget' then
        campaign.objectiveKey = campaign.desiredObjectiveKey
        campaign.objectivePosition = CopyPosition(campaign.desiredObjectivePosition)
        campaign.objectiveReason = campaign.desiredObjectiveReason
        campaign.engineerToken = campaign.desiredEngineerToken
        campaign.engineerRole = campaign.desiredEngineerRole
        campaign.desiredObjectiveKey = nil
        campaign.desiredObjectivePosition = nil
        campaign.desiredObjectiveReason = nil
        campaign.desiredEngineerToken = nil
        campaign.desiredEngineerRole = nil
        campaign.desiredClusterKey = nil
        campaign.desiredMemberKeys = nil
        campaign.state = 'active'
        campaign.fullFieldOrders = campaign.fullFieldOrders + 1
        campaign.missionIssuedTick = tick
        campaign.lastProgressTick = tick
        campaign.bestDistance = 1000000000000
    elseif mode == 'transition' then
        local previousCluster = campaign.clusterKey
        campaign.clusterKey = campaign.desiredClusterKey
        campaign.memberKeys = CopyArray(campaign.desiredMemberKeys)
        campaign.objectiveKey = campaign.desiredObjectiveKey
        campaign.objectivePosition = CopyPosition(campaign.desiredObjectivePosition)
        campaign.objectiveReason = campaign.desiredObjectiveReason
        campaign.engineerToken = campaign.desiredEngineerToken
        campaign.engineerRole = campaign.desiredEngineerRole
        campaign.desiredObjectiveKey = nil
        campaign.desiredObjectivePosition = nil
        campaign.desiredObjectiveReason = nil
        campaign.desiredEngineerToken = nil
        campaign.desiredEngineerRole = nil
        campaign.desiredClusterKey = nil
        campaign.desiredMemberKeys = nil
        campaign.awaitingReason = nil
        campaign.state = 'active'
        campaign.fullFieldOrders = campaign.fullFieldOrders + 1
        campaign.missionIssuedTick = tick
        campaign.lastProgressTick = tick
        campaign.bestDistance = 1000000000000
        Emit(controller, 'campaign_transition', {
            from = previousCluster or 'none',
            cluster = campaign.clusterKey,
            objective = campaign.objectiveKey,
        })
    elseif mode == 'recover' then
        campaign.recoveryOrders = campaign.recoveryOrders + 1
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
        if campaign.desiredObjectiveKey then
            if campaign.desiredReplacesCampaign == true
                or (campaign.desiredObjectiveReason == 'frontier_expansion'
                and campaign.desiredClusterKey
                )
            then
                campaign.clusterKey = campaign.desiredClusterKey
                campaign.memberKeys = CopyArray(campaign.desiredMemberKeys)
            end
            campaign.objectiveKey = campaign.desiredObjectiveKey
            campaign.objectivePosition = CopyPosition(campaign.desiredObjectivePosition)
            campaign.objectiveReason = campaign.desiredObjectiveReason
            campaign.engineerToken = campaign.desiredEngineerToken
            campaign.engineerRole = campaign.desiredEngineerRole
            ClearDesiredCampaignObjective(campaign)
        end
        campaign.state = 'active'
        campaign.emergency = false
        campaign.emergencyReason = nil
        campaign.healthySinceTick = nil
        campaign.modeSwitches = campaign.modeSwitches + 1
        campaign.fullFieldOrders = campaign.fullFieldOrders + 1
        campaign.missionIssuedTick = tick
        campaign.lastProgressTick = tick
    else
        return false
    end
    campaign.pendingMode = nil
    campaign.pendingTokens = {}
    Emit(controller, 'campaign_order', {
        command = mode,
        cluster = campaign.clusterKey,
        objective = campaign.objectiveKey,
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
        energyTrend = SafeCall(0, controller.brain.GetEconomyTrend, controller.brain, 'ENERGY'),
        energyStoredRatio = SafeCall(0, controller.brain.GetEconomyStoredRatio, controller.brain, 'ENERGY'),
        energyIncome = SafeCall(0, controller.brain.GetEconomyIncome, controller.brain, 'ENERGY'),
        energyUsage = SafeCall(0, controller.brain.GetEconomyUsage, controller.brain, 'ENERGY'),
        massTrend = SafeCall(0, controller.brain.GetEconomyTrend, controller.brain, 'MASS'),
        massStoredRatio = SafeCall(0, controller.brain.GetEconomyStoredRatio, controller.brain, 'MASS'),
        massIncome = SafeCall(0, controller.brain.GetEconomyIncome, controller.brain, 'MASS'),
        massUsage = SafeCall(0, controller.brain.GetEconomyUsage, controller.brain, 'MASS'),
    }
    economy.massRequested = SafeCall(economy.massUsage,
        controller.brain.GetEconomyRequested, controller.brain, 'MASS')
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
        placements = PlacementSnapshot(controller),
        pending = PendingArray(controller),
        state = StateSnapshot(controller),
    }
    observation.macro = MacroSnapshot(controller, units)
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
        if OperationCompleted(controller, operation, observation, record) then
            ReleaseOperation(controller, token, nil)
        elseif not record then
            ReleaseOperation(controller, token, 'actor_missing')
        elseif operation.phase == 'cancelling' then
            local actor = LiveOwnedActor(controller, token, record, record.role)
            if not actor then
                ReleaseOperation(controller, token, 'actor_missing')
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
        else
            OperationProgress(controller, operation, observation, record)
            if StructureOperation(operation)
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
                if StructureOperation(operation) or operation.kind == 'reclaim' then
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
                if record.busy then operation.accepted = true end
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
                elseif not StructureOperation(operation)
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
    observation.macro = MacroSnapshot(controller, observation.units)
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
            ExecuteFieldCampaign(controller, intent, records, usedActors)
        elseif intent.kind == 'frontier_screen'
            and controller.fieldCampaignEnabled ~= true
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
                if unit.role == 'anti_air' then completedAa = completedAa + 1 end
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
                if unit.role == 'anti_air' then buildingAa = buildingAa + 1 end
            end
        end
        for _, unit in ipairs(observation.units) do
            if unit.complete == true then
                if unit.role == 'mass_extractor' then completedMex = completedMex + 1 end
                if unit.role == 'land_factory' then completedFactories = completedFactories + 1 end
                if unit.role == 'engineer' then completedEngineers = completedEngineers + 1 end
                if unit.role == 'power_generator' then completedPgen = completedPgen + 1 end
                if unit.role == 'hydrocarbon' then completedHydro = completedHydro + 1 end
            else
                if unit.role == 'mass_extractor' then buildingMex = buildingMex + 1 end
                if unit.role == 'land_factory' then buildingFactories = buildingFactories + 1 end
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
            campaign_cluster = tostring(macro.campaignCluster or 'none'),
            campaign_objective = tostring(macro.campaignObjective or 'none'),
            field_units = tonumber(macro.fieldUnits) or 0,
            field_aa = tonumber(macro.fieldAa) or 0,
            field_at_anchor = tonumber(macro.fieldAtAnchor) or 0,
            home_units = tonumber(macro.homeUnits) or 0,
            home_aa = tonumber(macro.homeAa) or 0,
            mission_age = tonumber(macro.campaignMissionAge) or -1,
            last_campaign_progress_tick = tonumber(
                macro.campaignLastProgressTick
            ) or -1,
            full_field_orders = tonumber(macro.campaignFullFieldOrders) or 0,
            mode_switches = tonumber(macro.campaignModeSwitches) or 0,
            campaign_emergency = macro.campaignEmergency == true,
            engineer_demand = tonumber(macro.engineerDemand) or 0,
            factory_demand = tonumber(macro.factoryDemand) or 0,
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
