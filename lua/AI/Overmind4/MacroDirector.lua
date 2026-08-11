local LANE_ORDER = {
    'energy_recovery',
    'mex_rebuild',
    'reclaim',
    'engineers',
    'land_production',
    'air_production',
    'factory_growth',
    'tech',
}

local LANE_RANK = {
    energy_recovery = 1,
    mex_rebuild = 2,
    reclaim = 3,
    engineers = 4,
    land_production = 5,
    air_production = 6,
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
            local recurringFits = recurringMass >= massDrain and recurringEnergy >= energyDrain
            local bankFits = bankMass >= massCost and bankEnergy >= energyCost
            local optionalBlocked = plan.stalled and request.optional == true
            if (recurringFits or bankFits) and not optionalBlocked then
                lane.admitted = true
                lane.admittedCount = lane.admittedCount + 1
                committedMass = committedMass + massDrain
                committedEnergy = committedEnergy + energyDrain
                if recurringFits then
                    recurringMass = recurringMass - massDrain
                    recurringEnergy = recurringEnergy - energyDrain
                else
                    bankMass = bankMass - massCost
                    bankEnergy = bankEnergy - energyCost
                end
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

    if plan.lanes.mex_rebuild.admitted == true
        or plan.lanes.mex_rebuild.preserved == true
    then
        plan.fundedExpansionSlots = Clamp(Ceil(builderJobs / 3), 0, 4)
    end
    plan.engineerTarget = Clamp(2 + Ceil(builderJobs / 3) + Ceil(constructionBacklog / 4), 1, 32)
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

local function AvailableEngineers(engineers)
    local result = {}
    for _, engineer in ipairs(engineers or {}) do
        if type(engineer.token) == 'string' and engineer.available == true
            and engineer.live ~= false and engineer.owned ~= false
        then
            table.insert(result, engineer)
        end
    end
    SortByKey(result, 'token')
    return result
end

local function EligibleSites(snapshot)
    local regions = IndexBy(snapshot.regions or {}, 'key')
    local result = {}
    for _, site in ipairs(snapshot.sites or {}) do
        if type(site.key) == 'string' and site.reachable ~= false
            and site.buildable ~= false and site.reserved ~= true
            and site.owned ~= true and RegionEligible(regions[site.regionKey])
        then
            table.insert(result, site)
        end
    end
    table.sort(result, function(a, b)
        if (a.lost == true) ~= (b.lost == true) then return a.lost == true end
        if (a.value or 0) ~= (b.value or 0) then return (a.value or 0) > (b.value or 0) end
        return tostring(a.key) < tostring(b.key)
    end)
    return result
end

local function EscortTokens(escorts, claimed)
    local aa = {}
    local land = {}
    for _, escort in ipairs(escorts or {}) do
        if escort.available == true and escort.live ~= false and escort.owned ~= false
            and type(escort.token) == 'string' and not (claimed or {})[escort.token]
        then
            if escort.role == 'anti_air' or escort.role == 't2_anti_air' then
                table.insert(aa, escort.token)
            else
                table.insert(land, escort.token)
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

MacroDirector.PlanExpansion = function(snapshot)
    snapshot = snapshot or {}
    local result = { jobs = {}, denials = {} }
    local slots = Clamp(Number(snapshot.fundedExpansionSlots, 0) or 0, 0, 4)
    local engineers = AvailableEngineers(snapshot.engineers)
    local sites = EligibleSites(snapshot)
    local usedEngineers = {}
    local usedSites = {}
    local usedRegions = {}
    local usedEscorts = {}
    for slot = 1, slots do
        local best = nil
        for _, site in ipairs(sites) do
            if not usedSites[site.key] and not usedRegions[site.regionKey or site.key] then
                for _, engineer in ipairs(engineers) do
                    if not usedEngineers[engineer.token] then
                        local distance = Distance(engineer.position, site.position)
                        local candidate = {
                            engineer = engineer,
                            site = site,
                            distance = distance,
                        }
                        if not best
                            or (site.lost == true and best.site.lost ~= true)
                            or ((site.lost == true) == (best.site.lost == true)
                                and (distance < best.distance
                                    or (distance == best.distance
                                        and (tostring(site.key) < tostring(best.site.key)
                                            or (site.key == best.site.key
                                                and engineer.token < best.engineer.token)))))
                        then
                            best = candidate
                        end
                    end
                end
            end
        end
        if not best then break end
        local controlledRadius = Number(snapshot.controlledRadius, nil)
        local remote = controlledRadius ~= nil and best.distance > controlledRadius
        local escorts = nil
        if remote then
            escorts = EscortTokens(snapshot.escorts, usedEscorts)
            if not escorts then
                local regionKey = best.site.regionKey or best.site.key
                table.insert(result.denials, {
                    id = 'mex:' .. tostring(regionKey) .. ':' .. tostring(best.site.key),
                    actorToken = best.engineer.token,
                    siteKey = best.site.key,
                    regionKey = regionKey,
                    reason = 'escort_not_ready',
                })
                usedSites[best.site.key] = true
            end
        end
        if not remote or escorts then
            local regionKey = best.site.regionKey or best.site.key
            local kind = best.site.lost == true and 'rebuild_mex' or 'build_mex'
            local job = {
                id = 'mex:' .. tostring(regionKey) .. ':' .. tostring(best.site.key),
                kind = kind,
                actorToken = best.engineer.token,
                targetKey = best.site.key,
                siteKey = best.site.key,
                regionKey = regionKey,
                position = Copy(best.site.position),
                estimatedTravelTicks = Ceil(best.distance * 3),
                requiresEscort = remote,
            }
            if escorts then job.escortTokens = escorts end
            table.insert(result.jobs, job)
            usedEngineers[best.engineer.token] = true
            usedSites[best.site.key] = true
            usedRegions[regionKey] = true
            for _, token in ipairs(escorts or {}) do usedEscorts[token] = true end
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

MacroDirector.UpdateJobLedger = function(ledger, snapshot)
    ledger = ledger or {}
    snapshot = snapshot or {}
    local tick = Number(snapshot.tick, 0) or 0
    local result = {
        epoch = (Number(ledger.epoch, 0) or 0) + 1,
        jobs = Copy(ledger.jobs or {}),
        releasedActorTokens = {},
    }
    for _, incoming in ipairs(snapshot.newJobs or {}) do
        if type(incoming.id) == 'string' and not IsActiveJob(result.jobs[incoming.id]) then
            local job = Copy(incoming)
            job.phase = job.phase or 'travelling'
            job.lastProgressTick = tick
            job.retryCount = Number(job.retryCount, 0) or 0
            job.deadlineTick = tick + math.max(500, Number(job.estimatedTravelTicks, 0) or 0)
            result.jobs[job.id] = job
        end
    end

    local actors = IndexBy(snapshot.actors or {}, 'token')
    local targets = IndexBy(snapshot.targets or {}, 'key')
    local claimed = {}
    for _, job in pairs(result.jobs) do
        if IsActiveJob(job) and job.actorToken then claimed[job.actorToken] = true end
    end

    local ids = {}
    for id in pairs(result.jobs) do table.insert(ids, id) end
    table.sort(ids)
    for _, id in ipairs(ids) do
        local job = result.jobs[id]
        if IsActiveJob(job) then
            local actor = actors[job.actorToken]
            local target = targets[job.targetKey]
            if target and target.completed == true then
                job.phase = 'completed'
                job.failureReason = nil
                if job.actorToken then table.insert(result.releasedActorTokens, job.actorToken) end
            elseif target and target.live == false then
                ReleaseJob(job, result, 'target_gone')
            elseif ExistingMexEngineerInvalid(actor) then
                local oldToken = job.actorToken
                local actorLineage = ActorLineage(job)
                if actorLineage then job.actorLineage = actorLineage end
                if oldToken then
                    claimed[oldToken] = nil
                    table.insert(result.releasedActorTokens, oldToken)
                end
                local replacement = actorLineage and NearestReplacement(
                    snapshot.actors or {}, target, claimed, oldToken, actorLineage
                ) or nil
                job.retryCount = (Number(job.retryCount, 0) or 0) + 1
                if replacement then
                    job.actorToken = replacement.token
                    actorLineage[TokenIdentity(replacement.token)] = replacement.token
                    job.actorLineage = actorLineage
                    job.ordered = nil
                    job.orderedActorToken = nil
                    job.orderedAttempt = nil
                    claimed[replacement.token] = true
                    job.phase = 'travelling'
                    job.failureReason = nil
                    job.lastProgressTick = tick
                    job.remainingDistance = Distance(replacement.position, target and target.position)
                    job.deadlineTick = tick + math.max(500, Ceil(job.remainingDistance * 3))
                else
                    job.phase = 'retryable'
                    job.failureReason = 'actor_unavailable'
                    job.ordered = nil
                    job.orderedActorToken = nil
                    job.orderedAttempt = nil
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
        remainingT1ProductionLanes = Count(factories),
        t2ProductionRoles = { 't2_direct_fire', 't2_anti_air' },
        mexUpgradeSiteKeys = {},
        mexUpgradeRolesBySite = {},
        t3Action = 'hold',
    }
    if not snapshot.t2HqComplete and healthy and funded then
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
        and (Number(snapshot.t2MobileCount, 0) or 0) >= 35
    then
        plan.t3Action = 'admit'
        plan.t3UpgradeRole = 'land_factory_t3'
        plan.t3ProductionRole = 't3_direct_fire'
    end
    if snapshot.t2HqComplete and healthy and funded
        and (Number(snapshot.activeMexUpgrades, 0) or 0) == 0
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
        local selected = plan.t3Action == 'admit' and t2Mex[1] or nil
        selected = selected or t1Mex[1]
        if selected then
            table.insert(plan.mexUpgradeSiteKeys, selected.key)
            plan.mexUpgradeRolesBySite[selected.key] = selected.tier == 2
                and 'mass_extractor_t3' or 'mass_extractor_t2'
        end
    end
    return plan
end
