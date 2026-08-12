local LANE_ORDER = {
    'energy_recovery',
    'mex_rebuild',
    'reclaim',
    'land_production',
    'air_production',
    'engineers',
    'factory_growth',
    'tech',
}

local LANE_RANK = {
    energy_recovery = 1,
    mex_rebuild = 2,
    reclaim = 3,
    land_production = 4,
    air_production = 5,
    engineers = 6,
    factory_growth = 7,
    tech = 8,
}

local function Copy(value)
    if type(value) ~= 'table' then return value end
    local result = {}
    for key, item in pairs(value) do result[key] = Copy(item) end
    return result
end

local function Number(value, fallback)
    if type(value) ~= 'number' or value ~= value or value < 0 or value > 1000000000000 then
        return fallback
    end
    return value
end

local function SignedNumber(value, fallback)
    if type(value) ~= 'number' or value ~= value
        or value < -1000000000000 or value > 1000000000000
    then
        return fallback
    end
    return value
end

local function Count(items)
    if type(items) ~= 'table' then return 0 end
    return table.getn(items)
end

local function Clamp(value, low, high)
    if value < low then return low end
    if value > high then return high end
    return value
end

local function Ceil(value)
    local whole = math.floor(value)
    if value > whole then return whole + 1 end
    return whole
end

local function DistanceSquared(a, b)
    if type(a) ~= 'table' or type(b) ~= 'table' then return 1000000000000 end
    local dx = (Number(a[1], 0) or 0) - (Number(b[1], 0) or 0)
    local dz = (Number(a[3], 0) or 0) - (Number(b[3], 0) or 0)
    return dx * dx + dz * dz
end

local function Distance(a, b)
    return math.sqrt(DistanceSquared(a, b))
end

local function SortByKey(items, keyName)
    table.sort(items, function(a, b)
        return tostring(a[keyName] or '') < tostring(b[keyName] or '')
    end)
end

local function IndexBy(items, keyName)
    local result = {}
    for _, item in ipairs(items or {}) do
        if type(item) == 'table' and item[keyName] ~= nil then
            result[item[keyName]] = item
        end
    end
    return result
end

local function IsActiveJob(job)
    return job and job.phase ~= 'completed' and job.phase ~= 'retryable'
        and job.phase ~= 'cancelled'
end

MacroDirector = {}

MacroDirector.BuildPortfolio = function(snapshot)
    snapshot = snapshot or {}
    local economy = snapshot.economy or {}
    local requiredFields = {
        'massIncome', 'energyIncome', 'massRequested', 'energyRequested',
        'massStored', 'energyStored',
    }
    local valid = economy.valid ~= false
    for _, field in ipairs(requiredFields) do
        if Number(economy[field], nil) == nil then valid = false end
    end
    if SignedNumber(economy.massTrend, nil) == nil
        or SignedNumber(economy.energyTrend, nil) == nil
    then
        valid = false
    end

    local plan = {
        valid = valid,
        epoch = Number(snapshot.epoch, Number(snapshot.tick, 0)) or 0,
        lanes = {},
        availableRecurringMass = 0,
        availableRecurringEnergy = 0,
        committedMassDrain = 0,
        committedEnergyDrain = 0,
        fundedExpansionSlots = 0,
        grants = {},
        fundingLedger = {
            recurringMass = 0,
            recurringEnergy = 0,
            bankMass = 0,
            bankEnergy = 0,
        },
        engineerTarget = 1,
        landFactoryTarget = 1,
        airFactoryTarget = 1,
        factoryTarget = 2,
        stalled = false,
        intents = {},
    }
    for _, laneId in ipairs(LANE_ORDER) do
        plan.lanes[laneId] = {
            id = laneId,
            admitted = false,
            admittedCount = 0,
            preserved = false,
        }
    end
    if not valid then return plan end

    local recurringMass = math.max(0, economy.massIncome - economy.massRequested)
    local recurringEnergy = math.max(0, economy.energyIncome - economy.energyRequested)
    local bankMass = economy.massStored
    local bankEnergy = economy.energyStored
    local committedMass = 0
    local committedEnergy = 0
    local requestedIncludesCommitments = economy.commitmentsIncludedInRequested == true
    plan.stalled = economy.massTrend < 0 or economy.energyTrend < 0

    for _, commitment in ipairs(snapshot.commitments or {}) do
        local massDrain = Number(commitment.massDrain, 0) or 0
        local energyDrain = Number(commitment.energyDrain, 0) or 0
        committedMass = committedMass + massDrain
        committedEnergy = committedEnergy + energyDrain
        if not requestedIncludesCommitments then
            recurringMass = math.max(0, recurringMass - massDrain)
            recurringEnergy = math.max(0, recurringEnergy - energyDrain)
        end
        local lane = plan.lanes[commitment.lane]
        if lane then
            lane.admitted = true
            lane.admittedCount = lane.admittedCount + 1
        end
    end

    local requests = Copy(snapshot.requests or {})
    table.sort(requests, function(a, b)
        local aRank = LANE_RANK[a.lane] or 1000
        local bRank = LANE_RANK[b.lane] or 1000
        if aRank == bRank then return tostring(a.id or '') < tostring(b.id or '') end
        return aRank < bRank
    end)
    for _, request in ipairs(requests) do
        local lane = plan.lanes[request.lane]
        if lane then
            local massDrain = Number(request.massDrain, 0) or 0
            local energyDrain = Number(request.energyDrain, 0) or 0
            local massCost = Number(request.massCost, 0) or 0
            local energyCost = Number(request.energyCost, 0) or 0
            local durationTicks = Number(request.durationTicks, 0) or 0
            local recurringFits = recurringMass >= massDrain and recurringEnergy >= energyDrain
            local bankFits = bankMass >= massCost and bankEnergy >= energyCost
            local hybridMassBank = math.min(bankMass, massCost)
            local hybridEnergyBank = math.min(bankEnergy, energyCost)
            local hybridMassRate = durationTicks > 0
                and math.max(0, massCost - hybridMassBank) / durationTicks or 0
            local hybridEnergyRate = durationTicks > 0
                and math.max(0, energyCost - hybridEnergyBank) / durationTicks or 0
            local hybridFits = request.allowHybrid == true and durationTicks > 0
                and recurringMass >= hybridMassRate
                and recurringEnergy >= hybridEnergyRate
            local optionalBlocked = plan.stalled and request.optional == true
            if (recurringFits or bankFits or hybridFits) and not optionalBlocked then
                local source = recurringFits and 'recurring'
                    or bankFits and 'bank' or 'hybrid'
                lane.admitted = true
                lane.admittedCount = lane.admittedCount + 1
                committedMass = committedMass + massDrain
                committedEnergy = committedEnergy + energyDrain
                if recurringFits then
                    recurringMass = recurringMass - massDrain
                    recurringEnergy = recurringEnergy - energyDrain
                elseif bankFits then
                    bankMass = bankMass - massCost
                    bankEnergy = bankEnergy - energyCost
                else
                    bankMass = bankMass - hybridMassBank
                    bankEnergy = bankEnergy - hybridEnergyBank
                    recurringMass = recurringMass - hybridMassRate
                    recurringEnergy = recurringEnergy - hybridEnergyRate
                end
                table.insert(plan.grants, {
                    requestId = request.id,
                    lane = request.lane,
                    source = source,
                    massDrain = massDrain,
                    energyDrain = energyDrain,
                    massCost = massCost,
                    energyCost = energyCost,
                    durationTicks = Number(request.durationTicks, 0) or 0,
                })
            end
            if request.required == true and request.lane == 'land_production' then
                lane.preserved = true
            end
        end
    end

    local opportunities = snapshot.opportunities or {}
    local builderJobs = Number(opportunities.fundableBuilderJobs, 0) or 0
    local constructionBacklog = Number(opportunities.constructionBacklog, 0) or 0
    local landBacklog = Number(opportunities.landProductionBacklog, 0) or 0
    local airBacklog = Number(opportunities.airProductionBacklog, 0) or 0
    local reclaimJobs = Number(opportunities.reclaimJobs, 0) or 0
    local lostMex = Number(opportunities.lostMex, 0) or 0

    if reclaimJobs > plan.lanes.reclaim.admittedCount then
        plan.lanes.reclaim.admitted = true
        plan.lanes.reclaim.admittedCount = math.max(1, math.min(4, reclaimJobs))
    end
    if lostMex > 0 and plan.lanes.mex_rebuild.admittedCount == 0 then
        plan.lanes.mex_rebuild.preserved = true
    end

    local fundedMex = 0
    for _, grant in ipairs(plan.grants) do
        if grant.lane == 'mex_rebuild' then fundedMex = fundedMex + 1 end
    end
    plan.fundedExpansionSlots = Clamp(fundedMex, 0, 4)
    local counts = snapshot.counts or {}
    local completedMex = (Number(counts.mexT1, 0) or 0)
        + (Number(counts.mexT2, 0) or 0)
        + (Number(counts.mexT3, 0) or 0)
    plan.engineerTarget = Clamp(math.max(
        4 + completedMex,
        2 + plan.fundedExpansionSlots
    ), 4, 20)
    plan.landFactoryTarget = Clamp(1 + Ceil(landBacklog / 3), 1, 12)
    plan.airFactoryTarget = Clamp(1 + Ceil(airBacklog / 3), 1, 4)
    plan.factoryTarget = Clamp(plan.landFactoryTarget + plan.airFactoryTarget, 1, 16)
    if plan.factoryTarget < plan.landFactoryTarget + plan.airFactoryTarget then
        plan.landFactoryTarget = math.max(1, plan.factoryTarget - plan.airFactoryTarget)
    end
    plan.availableRecurringMass = math.max(0, economy.massIncome - economy.massRequested)
    plan.availableRecurringEnergy = math.max(0, economy.energyIncome - economy.energyRequested)
    plan.committedMassDrain = committedMass
    plan.committedEnergyDrain = committedEnergy
    plan.fundingLedger = {
        recurringMass = recurringMass,
        recurringEnergy = recurringEnergy,
        bankMass = bankMass,
        bankEnergy = bankEnergy,
    }
    return plan
end

MacroDirector.ClusterRegions = function(sites, options)
    local radius = Number((options or {}).radius, 64) or 64
    local ordered = {}
    for _, site in ipairs(sites or {}) do table.insert(ordered, Copy(site)) end
    SortByKey(ordered, 'key')
    local regions = {}
    for _, site in ipairs(ordered) do
        local selected = nil
        for _, region in ipairs(regions) do
            for _, member in ipairs(region.members) do
                if DistanceSquared(site.position, member.position) <= radius * radius then
                    selected = region
                    break
                end
            end
            if selected then break end
        end
        if not selected then
            selected = {
                key = 'region:' .. tostring(site.key or ''),
                state = 'planned',
                memberKeys = {},
                members = {},
                position = { 0, 0, 0 },
                radius = radius,
            }
            table.insert(regions, selected)
        end
        table.insert(selected.members, site)
        table.insert(selected.memberKeys, site.key)
    end
    for _, region in ipairs(regions) do
        local x = 0
        local y = 0
        local z = 0
        for _, site in ipairs(region.members) do
            x = x + (site.position[1] or 0)
            y = y + (site.position[2] or 0)
            z = z + (site.position[3] or 0)
        end
        local count = Count(region.members)
        if count > 0 then region.position = { x / count, y / count, z / count } end
        region.members = nil
    end
    return regions
end

MacroDirector.AdvanceRegion = function(region, event)
    local result = Copy(region or {})
    event = event or {}
    local kind = event.event
    local tick = Number(event.tick, 0) or 0
    if kind == 'package_ordered' then
        result.state = 'establishing'
    elseif kind == 'package_complete' then
        result.state = 'secured'
        result.productionAnchor = true
        result.reclaimAnchor = true
        result.suspendedUntilTick = 0
        result.bootstrapEscortTokens = nil
    elseif kind == 'enemy_pressure' then
        result.state = 'contested'
    elseif kind == 'package_lost' then
        local first = Number(result.firstLossTick, tick) or tick
        if tick - first > 1800 then
            result.lossCount = 1
            result.firstLossTick = tick
        else
            result.lossCount = (Number(result.lossCount, 0) or 0) + 1
            result.firstLossTick = first
        end
        if result.lossCount >= 3 then
            result.state = 'suspended'
            result.suspendedUntilTick = tick + 1800
        else
            result.state = 'lost'
        end
        result.productionAnchor = false
        result.reclaimAnchor = false
        result.bootstrapEscortTokens = nil
    elseif kind == 'retake_funded' then
        result.state = 'retake'
    elseif kind == 'suspension_expired' and tick >= (result.suspendedUntilTick or 0) then
        result.state = 'retake'
    end
    result.lastEventTick = tick
    return result
end

local function RegionEligible(region)
    if not region then return true end
    if region.connected == false then return false end
    return region.state ~= 'suspended'
end

local function NormalizedPosition(position)
    if type(position) ~= 'table' then return nil end
    local x = Number(position[1], nil)
    local z = Number(position[3], nil)
    if x == nil or z == nil then return nil end
    return { x, SignedNumber(position[2], 0) or 0, z }
end

local function SamePosition(left, right)
    if not left or not right then return left == right end
    return left[1] == right[1] and left[2] == right[2] and left[3] == right[3]
end

local function EngineerRecord(engineer)
    local position = NormalizedPosition(engineer.position)
    local eligible = engineer.available == true and engineer.complete ~= false
        and engineer.live ~= false and engineer.owned ~= false
    return {
        token = engineer.token,
        position = position,
        eligible = eligible and position ~= nil,
    }
end

local function SameEngineerRecord(left, right)
    return left.eligible == right.eligible
        and SamePosition(left.position, right.position)
end

local function AvailableEngineers(engineers)
    local byToken = {}
    local conflicted = {}
    local result = {}
    for _, engineer in ipairs(engineers or {}) do
        if type(engineer) == 'table' and type(engineer.token) == 'string'
            and engineer.token ~= ''
        then
            local normalized = EngineerRecord(engineer)
            local existing = byToken[engineer.token]
            if existing and not SameEngineerRecord(existing, normalized) then
                conflicted[engineer.token] = true
            elseif not existing then
                byToken[engineer.token] = normalized
            end
        end
    end
    for token, engineer in pairs(byToken) do
        if not conflicted[token] and engineer.eligible then
            table.insert(result, engineer)
        end
    end
    SortByKey(result, 'token')
    return result
end

local function RegionEligibility(regions)
    local result = {}
    local conflicted = {}
    for _, region in ipairs(regions or {}) do
        if type(region) == 'table' and type(region.key) == 'string' then
            local eligible = RegionEligible(region)
            if result[region.key] ~= nil and result[region.key] ~= eligible then
                conflicted[region.key] = true
            else
                result[region.key] = eligible
            end
        end
    end
    for key in pairs(conflicted) do result[key] = false end
    return result
end

local function SiteRecord(site, regionEligibility)
    local regionKey = type(site.regionKey) == 'string'
        and site.regionKey or site.key
    local position = NormalizedPosition(site.position)
    local regionEligible = regionEligibility[regionKey]
    if regionEligible == nil then regionEligible = true end
    local eligible = site.reachable ~= false and site.buildable ~= false
        and site.reserved ~= true and site.owned ~= true and regionEligible
    return {
        key = site.key,
        regionKey = regionKey,
        position = position,
        lost = site.lost == true,
        value = Number(site.value, 0) or 0,
        eligible = eligible and position ~= nil,
    }
end

local function SameSiteRecord(left, right)
    return left.regionKey == right.regionKey
        and left.lost == right.lost
        and left.value == right.value
        and left.eligible == right.eligible
        and SamePosition(left.position, right.position)
end

local function EligibleSites(snapshot)
    local regionEligibility = RegionEligibility(snapshot.regions)
    local byKey = {}
    local conflicted = {}
    local result = {}
    for _, site in ipairs(snapshot.sites or {}) do
        if type(site) == 'table' and type(site.key) == 'string'
            and site.key ~= ''
        then
            local normalized = SiteRecord(site, regionEligibility)
            local existing = byKey[site.key]
            if existing and not SameSiteRecord(existing, normalized) then
                conflicted[site.key] = true
            elseif not existing then
                byKey[site.key] = normalized
            end
        end
    end
    for key, site in pairs(byKey) do
        if not conflicted[key] and site.eligible then table.insert(result, site) end
    end
    table.sort(result, function(a, b)
        if (a.lost == true) ~= (b.lost == true) then return a.lost == true end
        if (a.value or 0) ~= (b.value or 0) then return (a.value or 0) > (b.value or 0) end
        return tostring(a.key) < tostring(b.key)
    end)
    return result
end

local function EscortTokens(escorts, claimed)
    local seen = {}
    local conflicted = {}
    local aa = {}
    local land = {}
    for _, escort in ipairs(escorts or {}) do
        if type(escort) == 'table' and type(escort.token) == 'string'
            and escort.token ~= ''
        then
            local eligible = escort.available == true and escort.complete ~= false
                and escort.live ~= false and escort.owned ~= false
            local role = (escort.role == 'anti_air' or escort.role == 't2_anti_air')
                and 'anti_air' or 'land'
            local existing = seen[escort.token]
            if existing and (existing.eligible ~= eligible or existing.role ~= role) then
                conflicted[escort.token] = true
            elseif not existing then
                seen[escort.token] = { eligible = eligible, role = role }
            end
        end
    end
    for token, escort in pairs(seen) do
        if escort.eligible and not conflicted[token] and not (claimed or {})[token] then
            if escort.role == 'anti_air' then
                table.insert(aa, token)
            else
                table.insert(land, token)
            end
        end
    end
    table.sort(aa)
    table.sort(land)
    if Count(aa) == 0 or Count(land) == 0 then return nil end
    local result = { aa[1], land[1] }
    table.sort(result)
    return result
end

local function MatchCostZero()
    return { 0, 0, 0, 0 }
end

local function MatchCostAddAssignment(left, assignment)
    return {
        left[1] + (assignment.site.lost == true and 0 or 1),
        left[2] + (assignment.remote == true and 1 or 0),
        left[3] - (Number(assignment.site.value, 0) or 0),
        left[4] + assignment.distance,
    }
end

local function MatchCostAdd(left, right)
    return {
        left[1] + right[1], left[2] + right[2],
        left[3] + right[3], left[4] + right[4],
    }
end

local function MatchCostNegate(cost)
    return { -cost[1], -cost[2], -cost[3], -cost[4] }
end

local function MatchCostLess(left, right)
    if not right then return true end
    for index = 1, 4 do
        if left[index] ~= right[index] then
            return left[index] < right[index]
        end
    end
    return false
end

local function AssignmentPreferred(left, right)
    if not right then return true end
    if (left.site.lost == true) ~= (right.site.lost == true) then
        return left.site.lost == true
    end
    if left.remote ~= right.remote then return left.remote ~= true end
    local leftValue = Number(left.site.value, 0) or 0
    local rightValue = Number(right.site.value, 0) or 0
    if leftValue ~= rightValue then return leftValue > rightValue end
    if left.distance ~= right.distance then return left.distance < right.distance end
    if tostring(left.regionKey) ~= tostring(right.regionKey) then
        return tostring(left.regionKey) < tostring(right.regionKey)
    end
    if tostring(left.site.key) ~= tostring(right.site.key) then
        return tostring(left.site.key) < tostring(right.site.key)
    end
    return left.engineer.token < right.engineer.token
end

local function ExpansionCandidates(engineers, sites, blockedBySite, controlledRadius,
    remoteOnly)
    local result = {}
    for engineerIndex, engineer in ipairs(engineers) do
        local byRegion = {}
        for _, site in ipairs(sites) do
            local blockedActors = type(blockedBySite[site.key]) == 'table'
                and blockedBySite[site.key] or {}
            if blockedActors[engineer.token] ~= true then
                local distance = Distance(engineer.position, site.position)
                local regionKey = site.regionKey or site.key
                local candidate = {
                    engineer = engineer,
                    engineerIndex = engineerIndex,
                    site = site,
                    regionKey = regionKey,
                    distance = distance,
                    remote = controlledRadius ~= nil and distance > controlledRadius,
                }
                local regionCandidates = byRegion[regionKey]
                if not regionCandidates then
                    regionCandidates = {}
                    byRegion[regionKey] = regionCandidates
                end
                local classKey = candidate.remote and 'remote' or 'local'
                if (not remoteOnly or candidate.remote == true)
                    and AssignmentPreferred(candidate, regionCandidates[classKey])
                then
                    regionCandidates[classKey] = candidate
                end
            end
        end
        local regionKeys = {}
        for regionKey in pairs(byRegion) do table.insert(regionKeys, regionKey) end
        table.sort(regionKeys, function(a, b) return tostring(a) < tostring(b) end)
        for _, regionKey in ipairs(regionKeys) do
            if byRegion[regionKey]['local'] then
                table.insert(result, byRegion[regionKey]['local'])
            end
            if byRegion[regionKey].remote then
                table.insert(result, byRegion[regionKey].remote)
            end
        end
    end
    return result
end

local function CandidateClass(candidate)
    return candidate.remote and 'remote' or 'local'
end

local function CandidateGroups(candidates, keyName)
    local result = {}
    for _, candidate in ipairs(candidates) do
        local identity = tostring(candidate[keyName])
        local key = tostring(string.len(identity)) .. ':' .. identity
            .. ':' .. CandidateClass(candidate)
        if not result[key] then result[key] = {} end
        table.insert(result[key], candidate)
    end
    return result
end

local function KeepBestCandidatesPerGroup(candidates, keyName, limit)
    local result = {}
    local groups = CandidateGroups(candidates, keyName)
    local keys = {}
    for key in pairs(groups) do table.insert(keys, key) end
    table.sort(keys)
    for _, key in ipairs(keys) do
        table.sort(groups[key], AssignmentPreferred)
        for index = 1, math.min(limit, Count(groups[key])) do
            table.insert(result, groups[key][index])
        end
    end
    return result
end

local function BoundedExpansionCandidates(candidates, slots)
    -- A size-K matching cannot need an edge below the K best same-class
    -- choices at either endpoint: at most K-1 better endpoints can be occupied.
    local byEngineer = KeepBestCandidatesPerGroup(
        candidates, 'engineerIndex', slots
    )
    local byRegion = KeepBestCandidatesPerGroup(byEngineer, 'regionKey', slots)
    table.sort(byRegion, AssignmentPreferred)
    return byRegion
end

local function PlanSignature(assignments)
    local parts = {}
    for _, assignment in ipairs(assignments or {}) do
        table.insert(parts, tostring(assignment.regionKey) .. ':'
            .. tostring(assignment.site.key) .. ':'
            .. tostring(assignment.engineer.token))
    end
    table.sort(parts)
    return table.concat(parts, '|')
end

local function StatePreferred(left, right)
    if not right then return true end
    if left.count ~= right.count then return left.count > right.count end
    if MatchCostLess(left.cost, right.cost) then return true end
    if MatchCostLess(right.cost, left.cost) then return false end
    return left.signature < right.signature
end

local function CopyIndexSet(source)
    local result = {}
    for index in pairs(source or {}) do result[index] = true end
    return result
end

local function StateKey(used, size, remoteCount)
    local parts = {}
    for index = 1, size do
        if used[index] then table.insert(parts, tostring(index)) end
    end
    return table.concat(parts, ',') .. ':' .. tostring(remoteCount)
end

local function ExtendedState(state, candidate, usedIndex, usedSize)
    local assignments = {}
    for _, assignment in ipairs(state.assignments) do
        table.insert(assignments, assignment)
    end
    table.insert(assignments, candidate)
    local used = CopyIndexSet(state.used)
    used[usedIndex] = true
    return {
        assignments = assignments,
        used = used,
        count = state.count + 1,
        remoteCount = state.remoteCount + (candidate.remote and 1 or 0),
        cost = MatchCostAddAssignment(state.cost, candidate),
        signature = PlanSignature(assignments),
        key = StateKey(
            used, usedSize,
            state.remoteCount + (candidate.remote and 1 or 0)
        ),
    }
end

local function StorePreferredState(statesByKey, state)
    if StatePreferred(state, statesByKey[state.key]) then
        statesByKey[state.key] = state
    end
end

local function SortedStates(statesByKey)
    local keys = {}
    for key in pairs(statesByKey) do table.insert(keys, key) end
    table.sort(keys)
    local result = {}
    for _, key in ipairs(keys) do table.insert(result, statesByKey[key]) end
    return result
end

local function AddMatchEdge(graph, fromNode, toNode, cost, assignment)
    local forwardIndex = Count(graph[fromNode]) + 1
    local reverseIndex = Count(graph[toNode]) + 1
    local forward = {
        to = toNode, reverse = reverseIndex, capacity = 1,
        cost = cost, assignment = assignment,
    }
    local reverse = {
        to = fromNode, reverse = forwardIndex, capacity = 0,
        cost = MatchCostNegate(cost),
    }
    table.insert(graph[fromNode], forward)
    table.insert(graph[toNode], reverse)
    return forward
end

local function MinimumCostCandidatePlan(engineers, candidates, slots)
    local regionSet = {}
    for _, candidate in ipairs(candidates) do regionSet[candidate.regionKey] = true end
    local regionKeys = {}
    for regionKey in pairs(regionSet) do table.insert(regionKeys, regionKey) end
    table.sort(regionKeys, function(a, b) return tostring(a) < tostring(b) end)
    local regionIndex = {}
    for index, regionKey in ipairs(regionKeys) do regionIndex[regionKey] = index end

    local sourceNode = 1
    local engineerStart = 2
    local regionStart = engineerStart + Count(engineers)
    local sinkNode = regionStart + Count(regionKeys)
    local graph = {}
    for node = 1, sinkNode do graph[node] = {} end
    for engineerIndex = 1, Count(engineers) do
        AddMatchEdge(
            graph, sourceNode, engineerStart + engineerIndex - 1,
            MatchCostZero(), nil
        )
    end
    local assignmentEdges = {}
    for _, candidate in ipairs(candidates) do
        local edge = AddMatchEdge(
            graph,
            engineerStart + candidate.engineerIndex - 1,
            regionStart + regionIndex[candidate.regionKey] - 1,
            MatchCostAddAssignment(MatchCostZero(), candidate),
            candidate
        )
        table.insert(assignmentEdges, edge)
    end
    for index = 1, Count(regionKeys) do
        AddMatchEdge(
            graph, regionStart + index - 1, sinkNode, MatchCostZero(), nil
        )
    end

    for _ = 1, slots do
        local distance = {}
        local previousNode = {}
        local previousEdge = {}
        distance[sourceNode] = MatchCostZero()
        for _ = 1, sinkNode - 1 do
            local changed = false
            for fromNode = 1, sinkNode do
                if distance[fromNode] then
                    for edgeIndex, edge in ipairs(graph[fromNode]) do
                        if edge.capacity > 0 then
                            local alternate = MatchCostAdd(
                                distance[fromNode], edge.cost
                            )
                            if MatchCostLess(alternate, distance[edge.to]) then
                                distance[edge.to] = alternate
                                previousNode[edge.to] = fromNode
                                previousEdge[edge.to] = edgeIndex
                                changed = true
                            end
                        end
                    end
                end
            end
            if not changed then break end
        end
        if not distance[sinkNode] then break end
        local node = sinkNode
        while node ~= sourceNode do
            local fromNode = previousNode[node]
            local edge = graph[fromNode][previousEdge[node]]
            edge.capacity = edge.capacity - 1
            graph[node][edge.reverse].capacity =
                graph[node][edge.reverse].capacity + 1
            node = fromNode
        end
    end

    local result = {}
    for _, edge in ipairs(assignmentEdges) do
        if edge.capacity == 0 then table.insert(result, edge.assignment) end
    end
    table.sort(result, AssignmentPreferred)
    return result
end

local function CandidateRemoteCount(candidates)
    local remote = 0
    local localCount = 0
    for _, candidate in ipairs(candidates) do
        if candidate.remote then remote = remote + 1 else localCount = localCount + 1 end
    end
    return remote, localCount
end

local function AssignmentRemoteCount(assignments)
    local result = 0
    for _, assignment in ipairs(assignments or {}) do
        if assignment.remote then result = result + 1 end
    end
    return result
end

local function BoundedExpansionPlan(engineers, sites, blockedBySite, slots,
    controlledRadius, remoteLimit, remoteOnly)
    if slots <= 0 then return {} end
    local candidates = ExpansionCandidates(
        engineers, sites, blockedBySite, controlledRadius, remoteOnly
    )
    candidates = BoundedExpansionCandidates(candidates, slots)
    local remoteCandidates, localCandidates = CandidateRemoteCount(candidates)
    if remoteLimit <= 0 then
        local filtered = {}
        for _, candidate in ipairs(candidates) do
            if not candidate.remote then table.insert(filtered, candidate) end
        end
        return MinimumCostCandidatePlan(engineers, filtered, slots)
    end
    if localCandidates == 0 then
        return MinimumCostCandidatePlan(
            engineers, candidates, math.min(slots, remoteLimit)
        )
    end
    local unconstrained = MinimumCostCandidatePlan(engineers, candidates, slots)
    if remoteCandidates == 0 or remoteLimit >= slots
        or AssignmentRemoteCount(unconstrained) <= remoteLimit
    then
        return unconstrained
    end
    local regionSet = {}
    for _, candidate in ipairs(candidates) do
        regionSet[candidate.regionKey] = true
    end
    local regionKeys = {}
    for regionKey in pairs(regionSet) do table.insert(regionKeys, regionKey) end
    table.sort(regionKeys, function(a, b) return tostring(a) < tostring(b) end)
    local regionIndex = {}
    for index, regionKey in ipairs(regionKeys) do regionIndex[regionKey] = index end
    local trackEngineers = Count(engineers) <= Count(regionKeys)
    local groupCount = trackEngineers and Count(regionKeys) or Count(engineers)
    local usedSize = trackEngineers and Count(engineers) or Count(regionKeys)
    local groups = {}
    for index = 1, groupCount do groups[index] = {} end
    for _, candidate in ipairs(candidates) do
        candidate.regionIndex = regionIndex[candidate.regionKey]
        local groupIndex = trackEngineers
            and candidate.regionIndex or candidate.engineerIndex
        table.insert(groups[groupIndex], candidate)
    end
    for _, group in ipairs(groups) do table.sort(group, AssignmentPreferred) end

    local initial = {
        assignments = {}, used = {}, count = 0, remoteCount = 0,
        cost = MatchCostZero(), signature = '', key = ':0',
    }
    local states = { initial }
    for _, group in ipairs(groups) do
        local nextByKey = {}
        for _, state in ipairs(states) do
            StorePreferredState(nextByKey, state)
            if state.count < slots then
                for _, candidate in ipairs(group) do
                    local usedIndex = trackEngineers
                        and candidate.engineerIndex or candidate.regionIndex
                    local nextRemote = state.remoteCount
                        + (candidate.remote and 1 or 0)
                    if not state.used[usedIndex] and nextRemote <= remoteLimit then
                        StorePreferredState(
                            nextByKey,
                            ExtendedState(state, candidate, usedIndex, usedSize)
                        )
                    end
                end
            end
        end
        states = SortedStates(nextByKey)
    end

    local best = nil
    for _, state in ipairs(states) do
        if StatePreferred(state, best) then best = state end
    end
    local result = best and best.assignments or {}
    table.sort(result, AssignmentPreferred)
    return result
end

local function ExpansionEscortPairs(escorts, slots)
    local result = {}
    local claimed = {}
    for _ = 1, slots do
        local tokens = EscortTokens(escorts, claimed)
        if not tokens then break end
        table.insert(result, tokens)
        for _, token in ipairs(tokens) do claimed[token] = true end
    end
    return result
end

MacroDirector.PlanExpansion = function(snapshot)
    snapshot = snapshot or {}
    local result = { jobs = {}, denials = {} }
    local slots = Clamp(Number(snapshot.fundedExpansionSlots, 0) or 0, 0, 4)
    local engineers = AvailableEngineers(snapshot.engineers)
    local sites = EligibleSites(snapshot)
    local blockedBySite = type(snapshot.blockedActorTokensBySite) == 'table'
        and snapshot.blockedActorTokensBySite or {}
    local controlledRadius = Number(snapshot.controlledRadius, nil)
    local escortPairs = ExpansionEscortPairs(snapshot.escorts, slots)
    local unconstrained = BoundedExpansionPlan(
        engineers, sites, blockedBySite, slots, controlledRadius, slots, false
    )
    local selected = BoundedExpansionPlan(
        engineers, sites, blockedBySite, slots, controlledRadius,
        Count(escortPairs), false
    )
    local maximumFlow = Count(unconstrained)

    local remoteIndex = 0
    local selectedRegions = {}
    for _, assignment in ipairs(selected) do
        local site = assignment.site
        local regionKey = assignment.regionKey
        local job = {
            id = 'mex:' .. tostring(regionKey) .. ':' .. tostring(site.key),
            kind = site.lost == true and 'rebuild_mex' or 'build_mex',
            actorToken = assignment.engineer.token,
            targetKey = site.key,
            siteKey = site.key,
            regionKey = regionKey,
            position = Copy(site.position),
            estimatedTravelTicks = Ceil(assignment.distance * 3),
            requiresEscort = assignment.remote,
        }
        if assignment.remote then
            remoteIndex = remoteIndex + 1
            job.escortTokens = Copy(escortPairs[remoteIndex])
        end
        table.insert(result.jobs, job)
        selectedRegions[regionKey] = true
    end

    if maximumFlow > Count(selected) then
        local deniedLimit = maximumFlow - Count(selected)
        local remainingSites = {}
        for _, site in ipairs(sites) do
            if not selectedRegions[site.regionKey or site.key] then
                table.insert(remainingSites, site)
            end
        end
        local deniedPlan = BoundedExpansionPlan(
            engineers, remainingSites, blockedBySite, deniedLimit,
            controlledRadius, deniedLimit, true
        )
        for _, assignment in ipairs(deniedPlan) do
            if assignment.remote == true and Count(result.denials) < deniedLimit then
                table.insert(result.denials, {
                    id = 'mex:' .. tostring(assignment.regionKey)
                        .. ':' .. tostring(assignment.site.key),
                    actorToken = assignment.engineer.token,
                    siteKey = assignment.site.key,
                    regionKey = assignment.regionKey,
                    reason = 'escort_not_ready',
                })
            end
        end
        local unresolved = deniedLimit - Count(result.denials)
        if unresolved > 0 then
            table.insert(result.denials, {
                id = 'expansion:escort-capacity',
                reason = 'escort_capacity_limited',
                blockedCount = unresolved,
            })
        end
    end
    return result
end

MacroDirector.PlanRegionPackage = function(region, snapshot)
    return {
        regionKey = region and region.key or nil,
        requiredRoles = { 'radar', 'static_anti_air', 'point_defense', 'land_factory' },
        garrisonMinimum = 4,
        garrisonAntiAirMinimum = 1,
        persistent = true,
    }
end

MacroDirector.PlanReclaim = function(snapshot)
    snapshot = snapshot or {}
    local regions = {}
    local engineers = AvailableEngineers(snapshot.engineers)
    local candidates = {}
    for _, region in ipairs(snapshot.regions or {}) do
        if region.state == 'secured' or region.reclaimAnchor == true then
            table.insert(regions, region)
        end
    end
    for _, candidate in ipairs(snapshot.candidates or {}) do
        if type(candidate.key) == 'string' and candidate.visible == true and candidate.live == true then
            table.insert(candidates, candidate)
        end
    end
    SortByKey(regions, 'key')
    table.sort(candidates, function(a, b)
        if (a.mass or 0) ~= (b.mass or 0) then return (a.mass or 0) > (b.mass or 0) end
        return a.key < b.key
    end)
    local jobs = {}
    local usedEngineers = {}
    local usedCandidates = {}
    for _, region in ipairs(regions) do
        local radius = Number(region.radius, 80) or 80
        local selectedCandidate = nil
        for _, candidate in ipairs(candidates) do
            if not usedCandidates[candidate.key]
                and DistanceSquared(candidate.position, region.position) <= radius * radius
            then
                selectedCandidate = candidate
                break
            end
        end
        if selectedCandidate then
            local selectedEngineer = nil
            local selectedDistance = nil
            for _, engineer in ipairs(engineers) do
                if not usedEngineers[engineer.token]
                    and DistanceSquared(engineer.position, region.position) <= radius * radius
                then
                    local distance = DistanceSquared(engineer.position, selectedCandidate.position)
                    if selectedDistance == nil or distance < selectedDistance
                        or (distance == selectedDistance and engineer.token < selectedEngineer.token)
                    then
                        selectedEngineer = engineer
                        selectedDistance = distance
                    end
                end
            end
            if selectedEngineer then
                table.insert(jobs, {
                    id = 'reclaim:' .. tostring(selectedCandidate.key),
                    kind = 'reclaim',
                    actorToken = selectedEngineer.token,
                    targetKey = selectedCandidate.key,
                    regionKey = region.key,
                    position = Copy(selectedCandidate.position),
                    requiresLiveVisionRevalidation = true,
                })
                usedEngineers[selectedEngineer.token] = true
                usedCandidates[selectedCandidate.key] = true
            end
        end
    end
    return { jobs = jobs }
end

local function ReleaseJob(job, result, reason)
    job.phase = 'retryable'
    job.failureReason = reason
    job.retryCount = (Number(job.retryCount, 0) or 0) + 1
    job.ordered = nil
    job.orderedActorToken = nil
    job.orderedAttempt = nil
    if job.actorToken then table.insert(result.releasedActorTokens, job.actorToken) end
end

local function TokenIdentity(token)
    if type(token) ~= 'string' then return nil end
    return string.match(token, '^(.*):[^:]+$') or token
end

local function ExactGenerationToken(token)
    return type(token) == 'string'
        and string.match(token, '^.+:%d+$') ~= nil
end

local function ActorLineage(job)
    if type(job) ~= 'table' or not ExactGenerationToken(job.actorToken) then
        return nil
    end
    local currentIdentity = TokenIdentity(job.actorToken)
    local lineage = {}
    if job.actorLineage ~= nil then
        if type(job.actorLineage) ~= 'table' then return nil end
        for identity, token in pairs(job.actorLineage) do
            if type(identity) ~= 'string' or identity == ''
                or not ExactGenerationToken(token) or TokenIdentity(token) ~= identity
            then
                return nil
            end
            lineage[identity] = token
        end
    end
    if lineage[currentIdentity] and lineage[currentIdentity] ~= job.actorToken then
        return nil
    end
    lineage[currentIdentity] = job.actorToken
    return lineage
end

local function ValidPosition(position)
    return type(position) == 'table'
        and SignedNumber(position[1], nil) ~= nil
        and SignedNumber(position[2], nil) ~= nil
        and SignedNumber(position[3], nil) ~= nil
end

local function CanReplaceMexEngineer(actor, replacedToken, actorLineage)
    if type(actor) ~= 'table' or not ExactGenerationToken(actor.token)
        or not ValidPosition(actor.position)
    then
        return false
    end
    if actor.available ~= true or actor.live ~= true or actor.owned ~= true
        or actor.complete ~= true
        or (actor.role ~= 'engineer' and actor.roleFamily ~= 'engineer')
        or type(actor.canBuild) ~= 'table'
        or actor.canBuild.mass_extractor ~= true
    then
        return false
    end
    local identity = TokenIdentity(actor.token)
    return identity ~= TokenIdentity(replacedToken)
        and not (actorLineage and actorLineage[identity]
            and actorLineage[identity] ~= actor.token)
end

local function ExistingMexEngineerInvalid(actor)
    if not actor or actor.live ~= true or actor.owned ~= true then return true end
    if not ExactGenerationToken(actor.token) or not ValidPosition(actor.position) then
        return true
    end
    if actor.complete ~= nil and actor.complete ~= true then return true end
    if actor.role ~= nil and actor.role ~= 'engineer'
        and actor.roleFamily ~= 'engineer'
    then
        return true
    end
    if actor.canBuild ~= nil
        and (type(actor.canBuild) ~= 'table'
            or actor.canBuild.mass_extractor ~= true)
    then
        return true
    end
    return false
end

local function NearestReplacement(actors, target, claimed, replacedToken, actorLineage)
    local best = nil
    local bestDistance = nil
    for _, actor in ipairs(actors or {}) do
        if CanReplaceMexEngineer(actor, replacedToken, actorLineage)
            and not claimed[actor.token]
        then
            local distance = DistanceSquared(actor.position, target and target.position)
            if bestDistance == nil or distance < bestDistance
                or (distance == bestDistance and actor.token < best.token)
            then
                best = actor
                bestDistance = distance
            end
        end
    end
    return best
end

local function ClearJobOrder(job)
    job.ordered = nil
    job.orderedActorToken = nil
    job.orderedAttempt = nil
end

local function AssignJobReplacement(job, replacement, target, tick, actorLineage)
    job.actorToken = replacement.token
    actorLineage[TokenIdentity(replacement.token)] = replacement.token
    job.actorLineage = actorLineage
    ClearJobOrder(job)
    job.phase = 'travelling'
    job.failureReason = nil
    job.lastProgressTick = tick
    job.remainingDistance = Distance(replacement.position, target and target.position)
    job.deadlineTick = tick + math.max(500, Ceil(job.remainingDistance * 3))
end

local function ResolveActorClaim(job, actors, target, claimed, tick, reason)
    local oldToken = job.actorToken
    local actorLineage = ActorLineage(job)
    local replacement = actorLineage and NearestReplacement(
        actors, target, claimed, oldToken, actorLineage
    ) or nil
    if replacement then
        AssignJobReplacement(job, replacement, target, tick, actorLineage)
        claimed[replacement.token] = job.id
        return true
    end
    job.phase = 'retryable'
    job.failureReason = reason
    job.retryCount = (Number(job.retryCount, 0) or 0) + 1
    ClearJobOrder(job)
    return false
end

MacroDirector.UpdateJobLedger = function(ledger, snapshot)
    ledger = ledger or {}
    snapshot = snapshot or {}
    local tick = Number(snapshot.tick, 0) or 0
    local result = {
        epoch = (Number(ledger.epoch, 0) or 0) + 1,
        jobs = Copy(ledger.jobs or {}),
        releasedActorTokens = {},
    }
    local actors = IndexBy(snapshot.actors or {}, 'token')
    local targets = IndexBy(snapshot.targets or {}, 'key')
    local claimed = {}

    local existingIds = {}
    for id in pairs(result.jobs) do table.insert(existingIds, id) end
    table.sort(existingIds)
    for _, id in ipairs(existingIds) do
        local job = result.jobs[id]
        if IsActiveJob(job) and ExactGenerationToken(job.actorToken) then
            if claimed[job.actorToken] then
                ResolveActorClaim(
                    job, snapshot.actors or {}, targets[job.targetKey], claimed,
                    tick, 'actor_already_claimed'
                )
            else
                claimed[job.actorToken] = id
            end
        end
    end

    local incomingJobs = {}
    for _, incoming in ipairs(snapshot.newJobs or {}) do
        if type(incoming) == 'table' and type(incoming.id) == 'string' then
            table.insert(incomingJobs, incoming)
        end
    end
    SortByKey(incomingJobs, 'id')
    for _, incoming in ipairs(incomingJobs) do
        if not IsActiveJob(result.jobs[incoming.id]) then
            local job = Copy(incoming)
            job.phase = job.phase or 'travelling'
            job.lastProgressTick = tick
            job.retryCount = Number(job.retryCount, 0) or 0
            job.deadlineTick = tick + math.max(500, Number(job.estimatedTravelTicks, 0) or 0)
            if ExactGenerationToken(job.actorToken) and claimed[job.actorToken] then
                ResolveActorClaim(
                    job, snapshot.actors or {}, targets[job.targetKey], claimed,
                    tick, 'actor_already_claimed'
                )
            elseif ExactGenerationToken(job.actorToken) then
                claimed[job.actorToken] = job.id
            end
            result.jobs[job.id] = job
        end
    end

    local ids = {}
    for id in pairs(result.jobs) do table.insert(ids, id) end
    table.sort(ids)
    for _, id in ipairs(ids) do
        local job = result.jobs[id]
        local active = IsActiveJob(job)
        local target = targets[job.targetKey]
        if job.phase ~= 'completed' and target and target.completed == true then
            job.phase = 'completed'
            job.failureReason = nil
            if active and job.actorToken then
                table.insert(result.releasedActorTokens, job.actorToken)
                if claimed[job.actorToken] == id then claimed[job.actorToken] = nil end
            end
        elseif active then
            local actor = actors[job.actorToken]
            if target and target.live == false then
                ReleaseJob(job, result, 'target_gone')
                if claimed[job.actorToken] == id then claimed[job.actorToken] = nil end
            elseif ExistingMexEngineerInvalid(actor) then
                local oldToken = job.actorToken
                local actorLineage = ActorLineage(job)
                if actorLineage then job.actorLineage = actorLineage end
                if oldToken then
                    if claimed[oldToken] == id then claimed[oldToken] = nil end
                    table.insert(result.releasedActorTokens, oldToken)
                end
                local replacement = actorLineage and NearestReplacement(
                    snapshot.actors or {}, target, claimed, oldToken, actorLineage
                ) or nil
                job.retryCount = (Number(job.retryCount, 0) or 0) + 1
                if replacement then
                    AssignJobReplacement(job, replacement, target, tick, actorLineage)
                    claimed[replacement.token] = id
                else
                    job.phase = 'retryable'
                    job.failureReason = 'actor_unavailable'
                    ClearJobOrder(job)
                end
            elseif job.phase == 'building' then
                local progressed = false
                if target and Number(target.fractionComplete, nil) ~= nil
                    and target.fractionComplete > (Number(job.lastFraction, -1) or -1)
                then
                    job.lastFraction = target.fractionComplete
                    progressed = true
                end
                if target and Number(target.workProgress, nil) ~= nil
                    and target.workProgress > (Number(job.lastWorkProgress, -1) or -1)
                then
                    job.lastWorkProgress = target.workProgress
                    progressed = true
                end
                if progressed then
                    job.lastProgressTick = tick
                    job.deadlineTick = tick + 400
                elseif tick >= (Number(job.deadlineTick, tick) or tick) then
                    ReleaseJob(job, result, 'construction_stalled')
                    if claimed[job.actorToken] == id then claimed[job.actorToken] = nil end
                end
            else
                local distance = Distance(actor.position, target and target.position)
                if job.remainingDistance == nil or distance + 0.01 < job.remainingDistance then
                    local firstMeasurement = job.remainingDistance == nil
                    job.remainingDistance = distance
                    job.lastProgressTick = tick
                    local refreshedDeadline = tick + math.max(300, Ceil(distance * 3))
                    if firstMeasurement then
                        job.deadlineTick = math.max(job.deadlineTick or 0, refreshedDeadline)
                    else
                        job.deadlineTick = math.max(job.deadlineTick or 0, refreshedDeadline)
                    end
                elseif tick >= (Number(job.deadlineTick, tick) or tick) then
                    ReleaseJob(job, result, 'travel_stalled')
                    if claimed[job.actorToken] == id then claimed[job.actorToken] = nil end
                end
            end
        end
    end
    table.sort(result.releasedActorTokens)
    return result
end

MacroDirector.PlanTech = function(snapshot)
    snapshot = snapshot or {}
    local healthy = snapshot.economyHealthy == true
    local funded = snapshot.techFunded == true
    local factories = {}
    local idleFactories = {}
    for _, factory in ipairs(snapshot.landFactories or {}) do
        if factory.tier == 1 and type(factory.token) == 'string'
            and factory.live ~= false and factory.owned ~= false
            and factory.complete ~= false and factory.functioning ~= false
            and factory.upgrading ~= true
        then
            table.insert(factories, factory)
            if factory.idle == true then table.insert(idleFactories, factory) end
        end
    end
    SortByKey(factories, 'token')
    SortByKey(idleFactories, 'token')
    local plan = {
        hqAction = 'hold',
        hqDenialReason = 'not_funded_or_healthy',
        supportAction = 'hold',
        supportDenialReason = 'not_funded_or_healthy',
        remainingT1ProductionLanes = Count(factories),
        t2ProductionRoles = { 't2_direct_fire', 't2_anti_air' },
        mexUpgradeSiteKeys = {},
        mexUpgradeRolesBySite = {},
        t3Action = 'hold',
    }
    local t2MexCount = 0
    for _, extractor in ipairs(snapshot.mex or {}) do
        if extractor.tier == 2 or extractor.tier == 3 then
            t2MexCount = t2MexCount + 1
        end
    end
    if not snapshot.t2HqComplete and t2MexCount >= 2 and healthy and funded then
        if Count(factories) >= 2 and Count(idleFactories) >= 1 then
            plan.hqAction = 'start_t2'
            plan.hqSourceToken = idleFactories[1].token
            plan.remainingT1ProductionLanes = Count(factories) - 1
            plan.hqDenialReason = nil
        elseif Count(factories) >= 2 then
            plan.hqDenialReason = 'no_idle_t1_lane'
        else
            plan.hqDenialReason = 'preserve_final_t1_lane'
        end
    end
    if snapshot.t2HqComplete and healthy and funded
        and (Number(snapshot.t2SupportFactoryCount, 0) or 0) < 1
    then
        if Count(factories) >= 2 and Count(idleFactories) >= 1 then
            plan.supportAction = 'start_t2_support'
            plan.supportSourceToken = idleFactories[1].token
            plan.supportUpgradeRole = 'land_factory_t2_support'
            plan.remainingT1ProductionLanes = Count(factories) - 1
            plan.supportDenialReason = nil
        elseif Count(factories) >= 2 then
            plan.supportDenialReason = 'no_idle_t1_lane'
        else
            plan.supportDenialReason = 'preserve_final_t1_lane'
        end
    elseif snapshot.t2HqComplete and (Number(snapshot.t2SupportFactoryCount, 0) or 0) >= 1 then
        plan.supportDenialReason = 'support_lane_complete'
    end
    if snapshot.t2HqComplete and healthy and funded
        and (Number(snapshot.t2MobileCount, 0) or 0) >= 35
    then
        plan.t3Action = 'admit'
        plan.t3UpgradeRole = 'land_factory_t3'
        plan.t3ProductionRole = 't3_direct_fire'
    end
    if healthy and funded
        and (Number(snapshot.activeMexUpgrades, 0) or 0) == 0
        and (snapshot.t2HqComplete or t2MexCount < 2)
    then
        local t1Mex = {}
        local t2Mex = {}
        for _, extractor in ipairs(snapshot.mex or {}) do
            if extractor.tier == 1 and extractor.upgrading ~= true and type(extractor.key) == 'string' then
                table.insert(t1Mex, extractor)
            elseif extractor.tier == 2 and extractor.upgrading ~= true
                and type(extractor.key) == 'string'
            then
                table.insert(t2Mex, extractor)
            end
        end
        SortByKey(t1Mex, 'key')
        SortByKey(t2Mex, 'key')
        local selected = snapshot.t2HqComplete
            and plan.t3Action == 'admit' and t2Mex[1] or nil
        selected = selected or t1Mex[1]
        if selected then
            table.insert(plan.mexUpgradeSiteKeys, selected.key)
            plan.mexUpgradeRolesBySite[selected.key] = selected.tier == 2
                and 'mass_extractor_t3' or 'mass_extractor_t2'
        end
    end
    return plan
end
