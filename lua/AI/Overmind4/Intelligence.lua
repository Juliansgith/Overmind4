local function Copy(value)
    if type(value) ~= 'table' then return value end
    local result = {}
    for key, item in pairs(value) do result[key] = Copy(item) end
    return result
end

local function Count(items)
    if type(items) ~= 'table' then return 0 end
    return table.getn(items)
end

local function Number(value, fallback)
    if type(value) ~= 'number' or value ~= value or value > 1000000000000 or value < -1000000000000 then
        return fallback
    end
    return value
end

local function SortByKey(items, keyName)
    table.sort(items, function(a, b)
        return tostring(a[keyName] or '') < tostring(b[keyName] or '')
    end)
end

local function DistanceSquared(a, b)
    if type(a) ~= 'table' or type(b) ~= 'table' then return 1000000000000 end
    local dx = (Number(a[1], 0) or 0) - (Number(b[1], 0) or 0)
    local dz = (Number(a[3], 0) or 0) - (Number(b[3], 0) or 0)
    return dx * dx + dz * dz
end

local MAX_SCOUT_OBJECTIVES = 32
local MAX_MEMORY_CONTACTS = 64
local RADAR_COALESCE_DISTANCE_SQUARED = 64 * 64

local function ExactTokens(expected, observed)
    if Count(expected) ~= Count(observed) then return false end
    local found = {}
    for _, token in ipairs(observed or {}) do
        if found[token] then return false end
        found[token] = true
    end
    for _, token in ipairs(expected or {}) do
        if not found[token] then return false end
    end
    return true
end

local function Release(mission, reason)
    mission.state = 'released'
    mission.failureReason = reason
    mission.retryable = true
    mission.released = true
    mission.retryCount = (Number(mission.retryCount, 0) or 0) + 1
    return mission
end

Intelligence = {}

Intelligence.PlanRadar = function(regions, coverage)
    local covered = {}
    for _, item in ipairs(coverage or {}) do
        if item.role == 'radar' and type(item.regionKey) == 'string' then
            if item.live == true then
                covered[item.regionKey] = true
            elseif covered[item.regionKey] == nil then
                covered[item.regionKey] = false
            end
        end
    end
    local ordered = {}
    for _, region in ipairs(regions or {}) do table.insert(ordered, region) end
    SortByKey(ordered, 'key')
    local intents = {}
    for _, region in ipairs(ordered) do
        if (region.state == 'secured' or region.state == 'establishing')
            and covered[region.key] ~= true
        then
            table.insert(intents, {
                kind = 'build_structure',
                buildRole = 'radar',
                regionKey = region.key,
                position = Copy(region.position),
                reason = covered[region.key] == false
                    and 'restore_region_radar' or 'establish_region_radar',
            })
        end
    end
    return intents
end

Intelligence.PlanScoutRoute = function(snapshot)
    snapshot = snapshot or {}
    local tick = Number(snapshot.tick, 0) or 0
    local covered = snapshot.lastCoveredTicks or {}
    local objectives = {}
    for _, objective in ipairs(snapshot.objectives or {}) do
        if objective.public == true and type(objective.key) == 'string'
            and type(objective.position) == 'table'
        then
            table.insert(objectives, objective)
        end
    end
    SortByKey(objectives, 'key')
    local ranked = {}
    for _, objective in ipairs(objectives) do
        local last = Number(covered[objective.key], 0) or 0
        table.insert(ranked, {
            objective = objective,
            age = math.max(0, tick - last),
        })
    end
    table.sort(ranked, function(a, b)
        if a.age == b.age then
            return tostring(a.objective.key) < tostring(b.objective.key)
        end
        return a.age > b.age
    end)
    objectives = {}
    local index = 1
    while index <= Count(ranked) and index <= MAX_SCOUT_OBJECTIVES do
        table.insert(objectives, ranked[index].objective)
        index = index + 1
    end
    SortByKey(objectives, 'key')
    local result = { objectiveKeys = {}, waypoints = {}, coverageAgeTicks = {} }
    local nextAge = -1
    for _, objective in ipairs(objectives) do
        local last = Number(covered[objective.key], 0) or 0
        local age = math.max(0, tick - last)
        table.insert(result.objectiveKeys, objective.key)
        table.insert(result.waypoints, Copy(objective.position))
        result.coverageAgeTicks[objective.key] = age
        if age > nextAge then
            nextAge = age
            result.nextObjectiveKey = objective.key
        end
    end
    return result
end

Intelligence.UpdateMemory = function(previous, observation)
    previous = previous or {}
    observation = observation or {}
    local tick = Number(observation.tick, 0) or 0
    local contacts = {}
    for token, contact in pairs(previous.contacts or {}) do
        local seenTick = Number(contact.lastSeenTick, -1000000) or -1000000
        if tick - seenTick < 600 then
            contacts[token] = Copy(contact)
            contacts[token].current = false
            contacts[token].currentlyVisual = false
        end
    end
    local observations = Copy(observation.observations or {})
    table.sort(observations, function(a, b)
        local aSource = tostring(a.source or '')
        local bSource = tostring(b.source or '')
        if aSource == bSource then return tostring(a.token or '') < tostring(b.token or '') end
        return aSource < bSource
    end)
    local radarClaims = {}
    for _, contact in ipairs(observations) do
        if type(contact.token) == 'string' and contact.current == true
            and (contact.source == 'vision' or contact.source == 'radar')
        then
            local memoryToken = contact.token
            if contact.source == 'radar' and type(contact.position) == 'table' then
                local bestToken = nil
                local bestDistance = nil
                for token, existing in pairs(contacts) do
                    local distance = DistanceSquared(existing.position, contact.position)
                    if existing.source == 'radar' and not radarClaims[token]
                        and distance <= RADAR_COALESCE_DISTANCE_SQUARED
                        and (bestDistance == nil or distance < bestDistance
                            or (distance == bestDistance and token < bestToken))
                    then
                        bestToken = token
                        bestDistance = distance
                    end
                end
                if bestToken then memoryToken = bestToken end
                radarClaims[memoryToken] = true
            end
            contacts[memoryToken] = {
                token = memoryToken,
                role = contact.source == 'radar' and 'unknown_mobile' or contact.role,
                position = Copy(contact.position),
                source = contact.source,
                currentlyVisual = contact.source == 'vision',
                current = true,
                lastSeenTick = tick,
            }
        end
    end
    local ranked = {}
    for token, contact in pairs(contacts) do
        table.insert(ranked, { token = token, contact = contact })
    end
    table.sort(ranked, function(a, b)
        local aTick = Number(a.contact.lastSeenTick, -1000000) or -1000000
        local bTick = Number(b.contact.lastSeenTick, -1000000) or -1000000
        if aTick ~= bTick then return aTick > bTick end
        local aVisual = a.contact.source == 'vision'
        local bVisual = b.contact.source == 'vision'
        if aVisual ~= bVisual then return aVisual end
        return a.token < b.token
    end)
    contacts = {}
    local index = 1
    while index <= Count(ranked) and index <= MAX_MEMORY_CONTACTS do
        contacts[ranked[index].token] = ranked[index].contact
        index = index + 1
    end
    return {
        epoch = (Number(previous.epoch, 0) or 0) + 1,
        contacts = contacts,
        threat = Copy(observation.threat or previous.threat or {}),
        expansionSafety = Copy(observation.expansionSafety or previous.expansionSafety or {}),
    }
end

Intelligence.PlanAir = function(snapshot)
    snapshot = snapshot or {}
    local completed = snapshot.completed or {}
    local needs = snapshot.needs or {}
    local totals = {
        air_scout = Number(completed.air_scout, 0) or 0,
        interceptor = Number(completed.interceptor, 0) or 0,
        bomber = Number(completed.bomber, 0) or 0,
        transport = Number(completed.transport, 0) or 0,
    }
    for _, pending in ipairs(snapshot.pending or {}) do
        local role = pending.buildRole or pending.role
        if totals[role] ~= nil then totals[role] = totals[role] + 1 end
    end
    local factories = {}
    for _, factory in ipairs(snapshot.factories or {}) do
        if type(factory.token) == 'string' and factory.idle ~= false then
            table.insert(factories, factory)
        end
    end
    SortByKey(factories, 'token')
    local slots = math.max(0, Number(snapshot.fundedSlots, 0) or 0)
    slots = math.min(slots, Count(factories))
    local orders = {}
    for index = 1, slots do
        local role = nil
        if totals.air_scout < 1 and needs.scoutCoverageStale ~= false then
            role = 'air_scout'
        elseif totals.interceptor < 4 then
            role = 'interceptor'
        elseif totals.bomber < 1 and needs.visibleRaidTarget == true then
            role = 'bomber'
        elseif totals.transport < 1 and needs.remoteSafeExpansion == true then
            role = 'transport'
        else
            if totals.bomber < 1 then
                role = 'bomber'
            else
                local threat = Number(needs.airThreatCount, nil)
                if threat == nil then threat = needs.airThreat == true and 1 or 0 end
                local interceptorTarget = math.min(12, 4 + math.max(0, threat) * 2)
                if totals.interceptor < interceptorTarget then
                    role = 'interceptor'
                elseif needs.visibleRaidTarget == true
                    and totals.bomber * 4 < totals.interceptor
                then
                    role = 'bomber'
                else
                    role = 'interceptor'
                end
            end
        end
        local factory = factories[index]
        if factory then
            table.insert(orders, {
                kind = 'factory_build',
                actorToken = factory.token,
                buildRole = role,
            })
            totals[role] = totals[role] + 1
        end
    end
    return { orders = orders }
end

Intelligence.SelectBomberTarget = function(observations)
    local engineers = {}
    local extractors = {}
    for _, target in ipairs(observations or {}) do
        if target.currentlyVisual == true and target.live ~= false and type(target.token) == 'string' then
            if target.role == 'engineer' then
                table.insert(engineers, target)
            elseif target.role == 'mass_extractor' or target.role == 'mass_extractor_t2'
                or target.role == 'mass_extractor_t3'
            then
                table.insert(extractors, target)
            end
        end
    end
    SortByKey(engineers, 'token')
    SortByKey(extractors, 'token')
    local selected = engineers[1] or extractors[1]
    if not selected then return nil end
    return {
        targetToken = selected.token,
        targetRole = selected.role,
        position = Copy(selected.position),
    }
end

Intelligence.ValidateBomberIntent = function(intent, live)
    intent = intent or {}
    live = live or {}
    local bomber = nil
    local target = nil
    for _, unit in ipairs(live.ownUnits or {}) do
        if unit.token == (intent.bomberToken or intent.actorToken) then bomber = unit end
    end
    for _, contact in ipairs(live.observations or {}) do
        if contact.token == intent.targetToken then target = contact end
    end
    local valid = bomber ~= nil and bomber.role == 'bomber' and bomber.live == true
        and bomber.owned == true and bomber.idle ~= false and target ~= nil
        and target.live ~= false and target.currentlyVisual == true
        and (intent.targetRole == nil or target.role == intent.targetRole)
    return { valid = valid, reason = valid and 'live_visual_target' or 'stale_or_invalid' }
end

Intelligence.PlanTransport = function(snapshot)
    snapshot = snapshot or {}
    local engineer = snapshot.engineer or {}
    local transport = snapshot.transport or {}
    local site = snapshot.site or {}
    local base = {
        mode = 'hold',
        siteKey = site.key,
        retryable = true,
    }
    if engineer.live ~= true or engineer.owned ~= true or type(engineer.token) ~= 'string'
        or site.safe ~= true or site.reachable ~= true
        or (Number(site.profitMass, 0) or 0) <= 0 or type(site.position) ~= 'table'
    then
        return base
    end
    if (Number(site.landEtaTicks, 1000000000000) or 1000000000000) <= 1200 then
        base.mode = 'walk'
        base.actorToken = engineer.token
        base.position = Copy(site.position)
        return base
    end
    if transport.live == true and transport.owned == true and transport.idle == true
        and type(transport.token) == 'string'
    then
        base.mode = 'airlift'
        base.retryable = false
        base.missionId = 'airlift:' .. tostring(site.key or engineer.token)
        base.state = 'planned'
        base.transportToken = transport.token
        base.cargoTokens = { engineer.token }
        base.dropPosition = Copy(site.position)
        base.dropTolerance = Number(site.dropTolerance, 20) or 20
        base.retryCount = 0
    end
    return base
end

Intelligence.AdvanceTransport = function(mission, event)
    local result = Copy(mission or {})
    if result.released == nil then result.released = false end
    event = event or {}
    local kind = event.kind
    local tick = Number(event.tick, 0) or 0
    if kind == 'transport_dead' or kind == 'transport_captured'
        or kind == 'cargo_dead' or kind == 'cargo_captured'
    then
        return Release(result, kind)
    end
    if kind == 'load_ordered' and result.state == 'planned' then
        result.state = 'loading'
        result.deadlineTick = tick + 400
    elseif kind == 'observed' then
        if event.transportToken ~= result.transportToken then
            return Release(result, 'transport_generation_mismatch')
        end
        if result.deadlineTick and tick > result.deadlineTick then
            return Release(result, 'mission_timeout')
        end
        if result.state == 'loading' then
            if not ExactTokens(result.cargoTokens or {}, event.attachedCargoTokens or {}) then
                if Count(event.attachedCargoTokens or {}) > 0 then
                    return Release(result, 'wrong_cargo')
                end
            else
                result.state = 'loaded'
                result.deadlineTick = tick + 1200
            end
        elseif result.state == 'loaded' or result.state == 'flying' then
            if not ExactTokens(result.cargoTokens or {}, event.attachedCargoTokens or {}) then
                local reason = Count(event.attachedCargoTokens or {}) == 0
                    and 'cargo_missing' or 'wrong_cargo'
                return Release(result, reason)
            end
        elseif result.state == 'unloading' then
            local attached = event.attachedCargoTokens or {}
            if Count(attached) == 0 then
                local arrived = true
                for _, token in ipairs(result.cargoTokens or {}) do
                    local position = (event.cargoPositions or {})[token]
                    if not position or DistanceSquared(position, result.dropPosition)
                        > (Number(result.dropTolerance, 20) or 20) ^ 2
                    then
                        arrived = false
                    end
                end
                if arrived then
                    result.state = 'completed'
                    result.released = true
                    result.retryable = false
                end
            elseif not ExactTokens(result.cargoTokens or {}, attached) then
                return Release(result, 'wrong_cargo')
            end
        end
    elseif kind == 'unload_ordered' and (result.state == 'loaded' or result.state == 'flying') then
        result.state = 'unloading'
        result.deadlineTick = tick + 400
    elseif kind == 'departed' and result.state == 'loaded' then
        result.state = 'flying'
    elseif kind == 'timeout' then
        return Release(result, 'mission_timeout')
    end
    return result
end
