local BUCKETS = { 'home', 'garrison', 'field', 'response', 'raider', 'unassigned' }
local COMBAT_ROLES = {
    anti_air = true, artillery = true, lab = true, scout = true, tank = true,
    t2_anti_air = true, t2_direct_fire = true, t3_direct_fire = true,
}

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

local function Eligible(unit)
    if type(unit) ~= 'table' or type(unit.token) ~= 'string' then return false end
    if unit.live ~= true or unit.owned ~= true or unit.complete ~= true then return false end
    return COMBAT_ROLES[unit.role] == true
end

local function IsAntiAir(unit)
    return unit.role == 'anti_air' or unit.role == 't2_anti_air'
end

local function EmptyAssignments()
    local result = {}
    for _, bucket in ipairs(BUCKETS) do result[bucket] = {} end
    return result
end

local function RemovePrefix(items, count)
    local selected = {}
    for index = 1, count do
        if Count(items) == 0 then break end
        table.insert(selected, table.remove(items, 1))
    end
    return selected
end

local function Append(target, source)
    for _, value in ipairs(source or {}) do table.insert(target, value) end
end

local function Ratios(assignments, total)
    local result = {}
    for _, bucket in ipairs(BUCKETS) do
        result[bucket] = total > 0 and Count(assignments[bucket]) / total or 0
    end
    return result
end

ForceDirector = {}

ForceDirector.Assign = function(snapshot)
    snapshot = snapshot or {}
    local units = {}
    local byToken = {}
    for _, unit in ipairs(snapshot.units or {}) do
        if Eligible(unit) then
            table.insert(units, unit)
            byToken[unit.token] = unit
        end
    end
    table.sort(units, function(a, b) return a.token < b.token end)
    local total = Count(units)
    local homeTarget = math.floor(total * 0.25)
    local garrisonTarget = math.floor(total * 0.15)
    local responseTarget = math.floor(total * 0.15)
    local raiderTarget = math.floor(total * 0.05)
    if total > 0 and homeTarget == 0 then homeTarget = 1 end
    local activeRegions = {}
    for _, region in ipairs(snapshot.regions or {}) do
        if region.requiresGarrison == true
            and (region.state == 'establishing' or region.state == 'secured'
                or region.state == 'contested' or region.state == 'retake')
        then
            table.insert(activeRegions, region)
        end
    end
    table.sort(activeRegions, function(a, b)
        local aBootstrap = Count(a.bootstrapEscortTokens) > 0
        local bBootstrap = Count(b.bootstrapEscortTokens) > 0
        if aBootstrap ~= bBootstrap then return aBootstrap end
        return tostring(a.key) < tostring(b.key)
    end)
    local maxRegionCount = math.floor(math.max(4, total * 0.20) / 4)
    while Count(activeRegions) > maxRegionCount do table.remove(activeRegions) end
    local minimumGarrison = Count(activeRegions) * 4
    if garrisonTarget < minimumGarrison then garrisonTarget = math.min(total, minimumGarrison) end
    local assignments = EmptyAssignments()
    local remaining = {}
    for _, unit in ipairs(units) do table.insert(remaining, unit) end

    local aa = {}
    for _, unit in ipairs(remaining) do
        if IsAntiAir(unit) then table.insert(aa, unit) end
    end
    local claimed = {}
    local bootstrapHasAntiAir = {}
    for index, region in ipairs(activeRegions) do
        local bootstrap = Copy(region.bootstrapEscortTokens or {})
        table.sort(bootstrap)
        for _, token in ipairs(bootstrap) do
            local unit = byToken[token]
            if unit and not claimed[token] then
                table.insert(assignments.garrison, token)
                claimed[token] = true
                if IsAntiAir(unit) then bootstrapHasAntiAir[index] = true end
            end
        end
    end
    for index, region in ipairs(activeRegions) do
        if region.requiresAntiAir == true and bootstrapHasAntiAir[index] ~= true then
            for _, unit in ipairs(aa) do
                if not claimed[unit.token] then
                    table.insert(assignments.garrison, unit.token)
                    claimed[unit.token] = true
                    break
                end
            end
        end
    end
    local filtered = {}
    for _, unit in ipairs(remaining) do
        if not claimed[unit.token] then table.insert(filtered, unit) end
    end
    remaining = filtered
    while Count(assignments.garrison) < garrisonTarget and Count(remaining) > 0 do
        table.insert(assignments.garrison, table.remove(remaining, 1).token)
    end

    local rebuilding = (snapshot.campaign or {}).state == 'rebuilding'
    local previousField = {}
    if rebuilding and type(snapshot.previousAssignments) == 'table' then
        for _, token in ipairs(snapshot.previousAssignments.field or {}) do previousField[token] = true end
    end
    if rebuilding and type(snapshot.previousAssignments) == 'table' then
        local oldFieldUnits = {}
        local nonField = {}
        for _, unit in ipairs(remaining) do
            if previousField[unit.token] then table.insert(oldFieldUnits, unit) else table.insert(nonField, unit) end
        end
        local homeCandidates = nonField
        local needed = math.max(0, homeTarget - Count(homeCandidates))
        Append(homeCandidates, RemovePrefix(oldFieldUnits, needed))
        for _, unit in ipairs(RemovePrefix(homeCandidates, homeTarget)) do
            table.insert(assignments.home, unit.token)
        end
        local responseCandidates = homeCandidates
        needed = math.max(0, responseTarget - Count(responseCandidates))
        Append(responseCandidates, RemovePrefix(oldFieldUnits, needed))
        for _, unit in ipairs(RemovePrefix(responseCandidates, responseTarget)) do
            table.insert(assignments.response, unit.token)
        end
        while Count(responseCandidates) > 0 do
            table.insert(assignments.garrison, table.remove(responseCandidates, 1).token)
        end
        local maxField = math.floor(total * 0.60)
        for _, unit in ipairs(RemovePrefix(oldFieldUnits, maxField)) do
            table.insert(assignments.field, unit.token)
        end
        while Count(oldFieldUnits) > 0 do
            table.insert(assignments.unassigned, table.remove(oldFieldUnits, 1).token)
        end
    else
        local picked = RemovePrefix(remaining, homeTarget)
        for _, unit in ipairs(picked) do table.insert(assignments.home, unit.token) end
        picked = RemovePrefix(remaining, responseTarget)
        for _, unit in ipairs(picked) do table.insert(assignments.response, unit.token) end
        picked = RemovePrefix(remaining, raiderTarget)
        for _, unit in ipairs(picked) do table.insert(assignments.raider, unit.token) end
        local maxField = math.floor(total * math.min(0.60, (snapshot.campaign or {}).maxOwnedRatio or 0.60))
        if maxField < 0 then maxField = 0 end
        picked = RemovePrefix(remaining, math.min(maxField, Count(remaining)))
        for _, unit in ipairs(picked) do table.insert(assignments.field, unit.token) end
        while Count(remaining) > 0 do table.insert(assignments.unassigned, table.remove(remaining, 1).token) end
    end

    for _, bucket in ipairs(BUCKETS) do table.sort(assignments[bucket]) end
    local ownership = {}
    for _, bucket in ipairs(BUCKETS) do
        for _, token in ipairs(assignments[bucket]) do ownership[token] = bucket end
    end
    local regionAssignments = {}
    local regionClaimed = {}
    for _, region in ipairs(activeRegions) do
        local tokens = {}
        local antiAirCount = 0
        local bootstrap = Copy(region.bootstrapEscortTokens or {})
        table.sort(bootstrap)
        for _, token in ipairs(bootstrap) do
            if not regionClaimed[token] and ownership[token] == 'garrison' then
                table.insert(tokens, token)
                regionClaimed[token] = true
                if IsAntiAir(byToken[token] or {}) then
                    antiAirCount = antiAirCount + 1
                end
            end
        end
        if region.requiresAntiAir == true and antiAirCount == 0 then
            for _, token in ipairs(assignments.garrison) do
                if not regionClaimed[token] and IsAntiAir(byToken[token] or {}) then
                    table.insert(tokens, token)
                    regionClaimed[token] = true
                    antiAirCount = 1
                    break
                end
            end
        end
        for _, token in ipairs(assignments.garrison) do
            if Count(tokens) >= 4 then break end
            if not regionClaimed[token] then
                table.insert(tokens, token)
                regionClaimed[token] = true
                if IsAntiAir(byToken[token] or {}) then
                    antiAirCount = antiAirCount + 1
                end
            end
        end
        table.sort(tokens)
        regionAssignments[region.key] = {
            actorTokens = tokens,
            antiAirCount = antiAirCount,
            ready = Count(tokens) >= 4 and (region.requiresAntiAir ~= true or antiAirCount >= 1),
        }
    end
    return {
        epoch = (snapshot.epoch or snapshot.tick or 0) + 1,
        assignments = assignments,
        ownershipByToken = ownership,
        regionAssignments = regionAssignments,
        ratios = Ratios(assignments, total),
        intents = {},
    }
end

ForceDirector.HandleHomeBreach = function(snapshot, plan)
    local result = Copy(plan or {})
    if not (snapshot.home or {}).breached then return result end
    local assignments = result.assignments or EmptyAssignments()
    local homeCount = Count(assignments.home)
    local required = math.max(0, (snapshot.home.requiredDefenders or homeCount) - homeCount)
    local responders = Copy(assignments.response or {})
    local needed = math.max(0, required - Count(responders))
    for index = 1, needed do
        local token = table.remove(assignments.field, 1)
        if not token then break end
        table.insert(responders, token)
    end
    assignments.response = responders
    result.assignments = assignments
    result.ownershipByToken = result.ownershipByToken or {}
    for _, token in ipairs(responders) do result.ownershipByToken[token] = 'response' end
    result.responseIntent = {
        kind = 'home_response',
        actorTokens = Copy(responders),
        position = Copy(snapshot.home.position),
        priority = 'immediate_home_breach',
    }
    result.ratios = Ratios(assignments, Count(snapshot.units or {}))
    return result
end

ForceDirector.Reconcile = function(plan, observation)
    plan = plan or {}
    observation = observation or {}
    local live = {}
    for _, unit in ipairs(observation.units or {}) do
        if Eligible(unit) then live[unit.token] = true end
    end
    local assignments = EmptyAssignments()
    local ownership = {}
    for _, bucket in ipairs(BUCKETS) do
        for _, token in ipairs((plan.assignments or {})[bucket] or {}) do
            if live[token] then
                table.insert(assignments[bucket], token)
                ownership[token] = bucket
            end
        end
    end
    local result = Copy(plan)
    result.epoch = (plan.epoch or 0) + 1
    result.assignments = assignments
    result.ownershipByToken = ownership
    result.ratios = Ratios(assignments, Count(observation.units or {}))
    return result
end
