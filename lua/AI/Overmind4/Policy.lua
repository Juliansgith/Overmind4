local COMBAT_ROLES = {
    anti_air = true,
    artillery = true,
    lab = true,
    tank = true,
    t2_anti_air = true,
    t2_direct_fire = true,
}

local ATTACK_COMBAT = 24
local ATTACK_ARTILLERY = 4
local ACU_RETREAT_HEALTH_RATIO = 0.55
local COMMANDER_PUSH_HEALTH_RATIO = 0.75
local LOW_ENERGY_STORED_RATIO = 0.35
local MIN_RECOVERY_ENGINEERS = 1
local CONTROLLED_RECLAIM_RADIUS = 10
local MAX_ACTIVE_RECLAIM_JOBS = 4
local TableGetn = table.getn
local TableInsert = table.insert

local function CopyArray(values)
    local copy = {}
    for index, value in ipairs(values or {}) do
        copy[index] = value
    end
    return copy
end

local function SortRecords(records)
    local sorted = CopyArray(records)
    table.sort(sorted, function(a, b)
        local aToken = tostring(a.token or '')
        local bToken = tostring(b.token or '')
        if aToken == bToken then
            return tostring(a.role or '') < tostring(b.role or '')
        end
        return aToken < bToken
    end)
    return sorted
end

local function SortSites(sites)
    local sorted = CopyArray(sites)
    table.sort(sorted, function(a, b)
        local aDistance = tonumber(a.distance) or 1000000000
        local bDistance = tonumber(b.distance) or 1000000000
        if aDistance == bDistance then
            local aName = tostring(a.name or a.key or '')
            local bName = tostring(b.name or b.key or '')
            if aName == bName then
                return tostring(a.key or '') < tostring(b.key or '')
            end
            return aName < bName
        end
        return aDistance < bDistance
    end)
    return sorted
end

local function CanBuild(unit, role)
    return unit and unit.canBuild and unit.canBuild[role] == true
end

local function IsUsablePosition(position)
    return type(position) == 'table'
        and type(position[1]) == 'number'
        and type(position[3]) == 'number'
end

local function FiniteNumber(value)
    return type(value) == 'number'
        and value == value
        and math.abs(value) <= 1000000000
end

local function PositionDistanceSquared(a, b)
    if not IsUsablePosition(a) or not IsUsablePosition(b) then
        return 1000000000000
    end
    local dx = a[1] - b[1]
    local dz = a[3] - b[3]
    return dx * dx + dz * dz
end

local function ReclaimVisibleToEngineer(candidate, engineer)
    if engineer.visionEnabled == false then return false end
    local radius = math.min(
        CONTROLLED_RECLAIM_RADIUS,
        tonumber(engineer.visionRadius) or CONTROLLED_RECLAIM_RADIUS,
        tonumber(candidate.visionRadius) or CONTROLLED_RECLAIM_RADIUS
    )
    return radius > 0
        and PositionDistanceSquared(candidate.position, engineer.position)
            <= radius * radius
end

local function PendingMatchesFoundation(operation, foundations)
    for _, foundation in ipairs(foundations or {}) do
        if operation.buildRole == foundation.role
            and ((operation.targetToken
                    and operation.targetToken == foundation.targetToken)
                or (operation.placementKey
                    and operation.placementKey == foundation.placementKey)
                or (IsUsablePosition(operation.position)
                    and PositionDistanceSquared(operation.position, foundation.position) <= 4))
        then
            return true
        end
    end
    return false
end

local function CountRoles(units, pending, foundations)
    local counts = {}
    local completeRolesByToken = {}
    for _, unit in ipairs(units) do
        if unit.role and unit.complete == true then
            counts[unit.role] = (counts[unit.role] or 0) + 1
            if type(unit.token) == 'string' then
                completeRolesByToken[unit.token] = unit.role
            end
        end
    end
    for _, foundation in ipairs(foundations or {}) do
        if foundation.role and type(foundation.targetToken) == 'string' then
            counts[foundation.role] = (counts[foundation.role] or 0) + 1
        end
    end
    for _, operation in ipairs(pending or {}) do
        if operation.buildRole
            and not PendingMatchesFoundation(operation, foundations)
        then
            counts[operation.buildRole] = (counts[operation.buildRole] or 0) + 1
        end
    end
    local adjustedUpgradeSources = {}
    for _, operation in ipairs(pending or {}) do
        local token = operation.actorToken
        local sourceRole = token and completeRolesByToken[token] or nil
        if operation.kind == 'factory_upgrade'
            and sourceRole
            and not adjustedUpgradeSources[token]
        then
            counts[sourceRole] = math.max(0, (counts[sourceRole] or 0) - 1)
            adjustedUpgradeSources[token] = true
        end
    end
    return counts
end

local function SortFoundations(foundations)
    local sorted = CopyArray(foundations)
    table.sort(sorted, function(a, b)
        local ar = tostring(a.role or '')
        local br = tostring(b.role or '')
        if ar == br then return tostring(a.targetToken or '') < tostring(b.targetToken or '') end
        return ar < br
    end)
    return sorted
end

local function PendingActors(pending)
    local actors = {}
    for _, operation in ipairs(pending or {}) do
        if operation.actorToken then
            actors[operation.actorToken] = true
        end
    end
    return actors
end

local function AddIntent(intents, intent)
    TableInsert(intents, intent)
end

local function QuantizedCoordinate(value)
    value = value * 1000
    if value >= 0 then
        return math.floor(value + 0.5)
    end
    return math.ceil(value - 0.5)
end

local function PlacementKey(position)
    if not IsUsablePosition(position) then return nil end
    return 'Placement:'
        .. tostring(QuantizedCoordinate(position[1])) .. ':'
        .. tostring(QuantizedCoordinate(position[3]))
end

local function PlacementRect(role, position)
    if not IsUsablePosition(position) then return nil end
    local size = nil
    if role == 'air_factory'
        or role == 'land_factory'
        or role == 'land_factory_t2'
    then
        size = 8
    elseif role == 'hydrocarbon' then
        size = 6
    elseif role == 'mass_extractor' or role == 'power_generator' then
        size = 2
    end
    if not size then return nil end
    local half = size * 0.5
    return {
        position[1] - half,
        position[3] - half,
        position[1] + half,
        position[3] + half,
    }
end

local function PlacementRectsOverlap(left, right)
    return type(left) == 'table'
        and type(right) == 'table'
        and left[1] < right[3]
        and right[1] < left[3]
        and left[2] < right[4]
        and right[2] < left[4]
end

local function PlacementAvailable(role, position, virtualPlacements)
    local key = PlacementKey(position)
    local rect = PlacementRect(role, position)
    if not key or not rect or virtualPlacements.keys[key] then return false end
    for _, occupied in ipairs(virtualPlacements.rects) do
        if PlacementRectsOverlap(rect, occupied) then return false end
    end
    return true, key, rect
end

local function AddPlacementReservation(role, position, virtualPlacements)
    local available, key, rect = PlacementAvailable(role, position, virtualPlacements)
    if not available then return false end
    virtualPlacements.keys[key] = true
    TableInsert(virtualPlacements.rects, rect)
    return true
end

local function ReserveSitePlacement(role, site, virtualPlacements)
    if type(site) ~= 'table' or not IsUsablePosition(site.position) then
        return false
    end
    virtualPlacements.siteKeys = virtualPlacements.siteKeys or {}
    if type(site.key) == 'string'
        and virtualPlacements.siteKeys[site.key] == true
    then
        return true
    end
    if not AddPlacementReservation(role, site.position, virtualPlacements) then
        return false
    end
    if type(site.key) == 'string' then
        virtualPlacements.siteKeys[site.key] = true
    end
    return true
end

local function ReservePlacement(snapshot, role, index, virtualPlacements)
    local placements = snapshot.placements or {}
    local candidates = placements[role] or {}
    local count = TableGetn(candidates)
    local first = tonumber(index) or 1
    if first < 1 or first > count then first = 1 end
    for candidateIndex = first, count do
        local position = candidates[candidateIndex]
        if AddPlacementReservation(role, position, virtualPlacements) then
            return position
        end
    end
    for candidateIndex = 1, first - 1 do
        local position = candidates[candidateIndex]
        if AddPlacementReservation(role, position, virtualPlacements) then
            return position
        end
    end
    return nil
end

local function SiteIsClaimed(site, virtualReserved)
    return site.occupied == true
        or site.reserved == true
        or (site.key and virtualReserved[site.key] == true)
end

local function SiteIsAvailable(site, virtualReserved, localOnly)
    if type(site) ~= 'table'
        or not site.key
        or not IsUsablePosition(site.position)
        or site.reachable ~= true
        or site.buildable == false
        or site.reserved == true
        or (site.key and virtualReserved[site.key] == true)
    then
        return false
    end
    if site.occupied == true
        and not (site.complete ~= true and type(site.targetToken) == 'string')
    then
        return false
    end
    if localOnly and site.localSite ~= true then
        return false
    end
    return true
end

local function FirstAvailableSite(sites, virtualReserved, localOnly)
    for _, site in ipairs(SortSites(sites)) do
        if SiteIsAvailable(site, virtualReserved, localOnly) then
            return site
        end
    end
    return nil
end

local function FirstLostSite(sites, virtualReserved, localOnly)
    for _, site in ipairs(SortSites(sites)) do
        if site.lost == true
            and SiteIsAvailable(site, virtualReserved, localOnly)
        then
            return site
        end
    end
    return nil
end

local function SiteSupportsLandCampaign(site)
    return type(site) == 'table'
        and site.engineerReachable == true
        and site.landReachable == true
end

local function FirstFrontierSite(sites, virtualReserved, selectedKey, requireLand)
    if type(selectedKey) == 'string' then
        for _, site in ipairs(sites or {}) do
            if site.key == selectedKey
                and site.frontierSelected == true
                and site.lost ~= true
                and (requireLand ~= true or SiteSupportsLandCampaign(site))
                and SiteIsAvailable(site, virtualReserved, false)
            then
                return site
            end
        end
    end
    for _, site in ipairs(SortSites(sites)) do
        if site.frontierSelected == true
            and site.lost ~= true
            and (requireLand ~= true or SiteSupportsLandCampaign(site))
            and SiteIsAvailable(site, virtualReserved, false)
        then
            return site
        end
    end
    return nil
end

local function KeyInArray(values, wanted)
    for _, value in ipairs(values or {}) do
        if value == wanted then return true end
    end
    return false
end

local function FirstCampaignSite(sites, virtualReserved, memberKeys, lostOnly)
    for _, site in ipairs(SortSites(sites)) do
        if KeyInArray(memberKeys, site.key)
            and (not lostOnly or site.lost == true)
            and site.complete ~= true
            and SiteSupportsLandCampaign(site)
            and SiteIsAvailable(site, virtualReserved, false)
        then
            return site
        end
    end
    return nil
end

local function FirstCampaignLostSite(sites, virtualReserved)
    for _, site in ipairs(SortSites(sites)) do
        if site.lost == true
            and SiteSupportsLandCampaign(site)
            and SiteIsAvailable(site, virtualReserved, false)
        then
            return site
        end
    end
    return nil
end

local function CampaignSiteByKey(sites, siteKey)
    for _, site in ipairs(sites or {}) do
        if site.key == siteKey then return site end
    end
    return nil
end

local function CampaignHasConnectedJob(snapshot, macro, massSites)
    for _, operation in ipairs(snapshot.pending or {}) do
        if operation.kind == 'build_structure'
                or operation.kind == 'assist_structure'
        then
            local site = CampaignSiteByKey(massSites, operation.siteKey)
            if SiteSupportsLandCampaign(site)
                and (KeyInArray(macro.campaignMemberKeys, operation.siteKey)
                or (operation.reason == 'frontier_expansion'
                    and operation.clusterKey == macro.campaignCluster))
            then
                return true
            end
        end
    end
    for _, site in ipairs(massSites or {}) do
        if site.occupied == true
            and site.complete ~= true
            and type(site.targetToken) == 'string'
            and KeyInArray(macro.campaignMemberKeys, site.key)
            and SiteSupportsLandCampaign(site)
        then
            return true
        end
    end
    return false
end

local function HasLostMex(sites)
    for _, site in ipairs(sites or {}) do
        if site.lost == true and site.complete ~= true then return true end
    end
    return false
end

local function CountClaimedLocalSites(sites, virtualReserved)
    local count = 0
    for _, site in ipairs(sites or {}) do
        if site.localSite == true and SiteIsClaimed(site, virtualReserved) then
            count = count + 1
        end
    end
    return count
end

local function BuildAtSite(actor, role, site, priority, reason)
    local speed = tonumber(actor and actor.moveSpeed) or 1.9
    if speed <= 0 then speed = 1.9 end
    local distance = math.sqrt(PositionDistanceSquared(
        actor and actor.position,
        site and site.position
    ))
    local travelTicks = distance / speed * 10
    local buildTicks = role == 'mass_extractor' and 120
        or (role == 'hydrocarbon' and 800 or 0)
    local paybackTicks = role == 'mass_extractor' and 180 or 0
    return {
        kind = site.occupied == true and site.complete ~= true
            and type(site.targetToken) == 'string'
            and 'assist_structure'
            or 'build_structure',
        actorToken = actor.token,
        buildRole = role,
        siteKey = site.key,
        clusterKey = site.clusterKey,
        targetToken = site.targetToken,
        position = site.position,
        priority = priority,
        reason = reason,
        estimatedTravelTicks = travelTicks,
        estimatedBuildTicks = buildTicks,
        estimatedPaybackTicks = paybackTicks,
        estimatedRoiTicks = travelTicks + buildTicks + paybackTicks,
    }
end

local function BuildAtPlacement(actor, role, position, priority, reason)
    if not position then
        return nil
    end
    return {
        kind = 'build_structure',
        actorToken = actor.token,
        buildRole = role,
        placementKey = PlacementKey(position),
        position = position,
        priority = priority,
        reason = reason,
    }
end

local function FirstOrphanFoundation(snapshot, engineer, virtualFoundations)
    for _, foundation in ipairs(SortFoundations(snapshot.foundations or {})) do
        if type(foundation.targetToken) == 'string'
            and type(foundation.role) == 'string'
            and IsUsablePosition(foundation.position)
            and foundation.reserved ~= true
            and not virtualFoundations[foundation.targetToken]
            and CanBuild(engineer, foundation.role)
        then
            return foundation
        end
    end
    return nil
end

local function AssistFoundation(actor, foundation)
    return {
        kind = 'assist_structure',
        actorToken = actor.token,
        buildRole = foundation.role,
        targetToken = foundation.targetToken,
        placementKey = foundation.placementKey,
        position = foundation.position,
        priority = 18,
        reason = 'finish_orphan',
    }
end

local function CombatUnits(units)
    local combat = {}
    local artillery = 0
    for _, unit in ipairs(units) do
        if COMBAT_ROLES[unit.role]
            and unit.complete == true
            and unit.availableForWave == true
        then
            TableInsert(combat, unit)
            if unit.role == 'artillery' then
                artillery = artillery + 1
            end
        end
    end
    return combat, artillery
end

local function DefensiveCombatUnits(units, excluded)
    local combat = {}
    for _, unit in ipairs(units) do
        if COMBAT_ROLES[unit.role]
            and unit.complete == true
            and unit.assignedToWave ~= true
            and unit.fieldCohort ~= true
            and not (excluded and excluded[unit.token])
        then
            TableInsert(combat, unit)
        end
    end
    return combat
end

local function ActorTokens(units)
    local tokens = {}
    for _, unit in ipairs(units) do
        TableInsert(tokens, unit.token)
    end
    table.sort(tokens)
    return tokens
end

local function FindAcu(units)
    local acu = nil
    for _, unit in ipairs(units) do
        if unit.role == 'acu' and unit.complete == true then
            acu = unit
            break
        end
    end
    return acu
end

local function DoctrineState(snapshot)
    local state = snapshot.state
    if type(state) ~= 'table' or type(state.initialWaveSent) ~= 'boolean' then
        return nil
    end
    for _, field in ipairs({
        'commanderPushActive',
        'commanderMobilizing',
        'commanderRetreating',
    }) do
        if state[field] ~= nil and type(state[field]) ~= 'boolean' then
            return nil
        end
    end
    return state
end

local function InitialMobilization(snapshot, units, pendingActors, state)
    if not state
        or state.initialWaveSent == true
        or state.commanderPushActive == true
        or state.commanderMobilizing == true
        or state.commanderRetreating == true
        or snapshot.targetPath ~= true
        or not IsUsablePosition(snapshot.stagingPosition)
        or not IsUsablePosition(snapshot.targetPosition)
    then
        return nil, nil
    end
    local combat, artillery = CombatUnits(units)
    if TableGetn(combat) < ATTACK_COMBAT or artillery < ATTACK_ARTILLERY then
        return nil, nil
    end
    local acu = FindAcu(units)
    local health = acu and tonumber(acu.healthRatio) or nil
    if not acu
        or not health
        or health < COMMANDER_PUSH_HEALTH_RATIO
        or acu.idle ~= true
        or acu.nearStaging ~= false
        or pendingActors[acu.token]
    then
        return nil, nil
    end
    return acu, combat
end

local function SafetyDecision(snapshot, units, state, mobilizingCombat)
    local acu = FindAcu(units)

    local contact = snapshot.enemyContact
    local commanderRecovery = state and state.commanderRetreating == true
    local commanderMobilizing = state and state.commanderMobilizing == true
    local commanderSafety = state and (
        state.commanderPushActive == true
        or commanderMobilizing
    )
    local health = acu and tonumber(acu.healthRatio) or nil
    local healthEmergency = false
    if commanderRecovery then
        healthEmergency = acu ~= nil
    elseif commanderSafety then
        healthEmergency = acu and (
            not health or health < COMMANDER_PUSH_HEALTH_RATIO
        )
    elseif health then
        healthEmergency = health < ACU_RETREAT_HEALTH_RATIO
    end
    local assembling = mobilizingCombat ~= nil
    local emergency = acu and (
        healthEmergency
        or (
            contact
            and contact.immediate == true
            and not commanderMobilizing
            and not assembling
        )
    )
    local excluded = nil
    if mobilizingCombat then
        excluded = {}
        for _, unit in ipairs(mobilizingCombat) do
            excluded[unit.token] = true
        end
    elseif state
        and state.commanderPushActive == true
        and acu
        and health
        and health >= COMMANDER_PUSH_HEALTH_RATIO
        and not (contact and contact.immediate == true)
    then
        excluded = {}
        for _, unit in ipairs(units) do
            if COMBAT_ROLES[unit.role]
                and unit.complete == true
                and unit.assignedToWave ~= true
                and unit.nearStaging == true
            then
                excluded[unit.token] = true
            end
        end
    end
    local combat = DefensiveCombatUnits(units, excluded)

    if emergency then
        local intents = {
            {
                kind = 'retreat',
                actorToken = acu.token,
                position = snapshot.basePosition,
                priority = 1,
                reason = 'acu_safety',
            },
        }
        if contact and IsUsablePosition(contact.position) and TableGetn(combat) > 0 then
            AddIntent(intents, {
                kind = 'defend_wave',
                actorTokens = ActorTokens(combat),
                position = contact.position,
                priority = 2,
                reason = 'immediate_contact',
            })
        end
        return intents, true
    end

    if contact and IsUsablePosition(contact.position) then
        local intents = {}
        if TableGetn(combat) > 0 then
            AddIntent(intents, {
                kind = 'defend_wave',
                actorTokens = ActorTokens(combat),
                position = contact.position,
                priority = 2,
                reason = 'base_contact',
            })
        end
        return intents, false
    end

    return nil, false
end

local function AcuOpening(snapshot, units, counts, virtualReserved, virtualPlacements, pendingActors)
    local acu = nil
    for _, unit in ipairs(units) do
        if unit.role == 'acu' then
            acu = unit
            break
        end
    end
    if not acu or acu.complete ~= true or acu.idle ~= true or pendingActors[acu.token] then
        return nil
    end

    local massSites = ((snapshot.sites or {}).mass) or {}
    local macro = type(snapshot.macro) == 'table' and snapshot.macro or nil
    local campaignActive = macro
        and macro.campaignEnabled == true
        and macro.campaignState ~= 'idle'
    local connectedCampaignJob = campaignActive
        and CampaignHasConnectedJob(snapshot, macro, massSites)
        or false
    local function FirstOpeningMassSite(lostOnly)
        for _, site in ipairs(SortSites(massSites)) do
            local connected = connectedCampaignJob
                and KeyInArray(macro.campaignMemberKeys, site.key)
                and SiteSupportsLandCampaign(site)
            if (not lostOnly or site.lost == true)
                and not connected
                and SiteIsAvailable(site, virtualReserved, true)
                and ReserveSitePlacement(
                    'mass_extractor',
                    site,
                    virtualPlacements
                )
            then
                return site
            end
        end
        return nil
    end
    if CanBuild(acu, 'mass_extractor') then
        local lost = FirstOpeningMassSite(true)
        if lost then
            virtualReserved[lost.key] = true
            return BuildAtSite(acu, 'mass_extractor', lost, 9, 'rebuild_mex')
        end
    end

    if (counts.land_factory or 0) < 1 and CanBuild(acu, 'land_factory') then
        return BuildAtPlacement(acu, 'land_factory', ReservePlacement(snapshot, 'land_factory', 1, virtualPlacements), 10, 'opening_factory')
    end
    if (counts.land_factory or 0) < 1 then
        return nil
    end

    local powerCount = counts.power_generator or 0
    if powerCount < 2 and CanBuild(acu, 'power_generator') then
        return BuildAtPlacement(acu, 'power_generator', ReservePlacement(snapshot, 'power_generator', powerCount + 1, virtualPlacements), 11, 'opening_power')
    end
    if powerCount < 2 then
        return nil
    end

    if CountClaimedLocalSites(massSites, virtualReserved) < 4 and CanBuild(acu, 'mass_extractor') then
        local site = FirstOpeningMassSite(false)
        if site then
            virtualReserved[site.key] = true
            return BuildAtSite(acu, 'mass_extractor', site, 12, 'opening_mass')
        end
        return nil
    end

    if CountClaimedLocalSites(massSites, virtualReserved) >= 4
        and powerCount < 4 and CanBuild(acu, 'power_generator')
    then
        local position = ReservePlacement(
            snapshot, 'power_generator', powerCount + 1, virtualPlacements
        )
        if position then
            return BuildAtPlacement(
                acu,
                'power_generator',
                position,
                12,
                'opening_air_power'
            )
        end
    end

    if (counts.land_factory or 0) < 2 and CanBuild(acu, 'land_factory') then
        return BuildAtPlacement(acu, 'land_factory', ReservePlacement(snapshot, 'land_factory', 2, virtualPlacements), 13, 'opening_second_factory')
    end
    if (counts.air_factory or 0) < 1 and CanBuild(acu, 'air_factory') then
        return BuildAtPlacement(
            acu,
            'air_factory',
            ReservePlacement(snapshot, 'air_factory', 1, virtualPlacements),
            3,
            'opening_air_factory'
        )
    end
    return nil
end

local function EngineerDecisions(snapshot, units, counts, virtualReserved, virtualPlacements, pendingActors, underContact, allowPlacement, intents)
    local engineers = {}
    local reclaimPatrolActive = false
    local reclaimPatrolAcu = nil
    for _, unit in ipairs(units) do
        if unit.reclaimPatrolAssigned == true then
            reclaimPatrolActive = true
        end
        if unit.role == 'acu'
            and unit.complete == true
            and unit.idle == true
            and not pendingActors[unit.token]
            and unit.reclaimPatrolAssigned ~= true
        then
            reclaimPatrolAcu = unit
        end
        if unit.role == 'engineer'
            and unit.complete == true
            and unit.idle == true
            and not pendingActors[unit.token]
            and unit.reclaimPatrolAssigned ~= true
        then
            TableInsert(engineers, unit)
        end
    end

    local sites = snapshot.sites or {}
    local hydroSites = sites.hydro or {}
    local massSites = sites.mass or {}
    local economy = snapshot.economy or {}
    local macro = type(snapshot.macro) == 'table' and snapshot.macro or nil
    local lowEnergy = (tonumber(economy.energyTrend) or 0) < 0
        and (tonumber(economy.energyStoredRatio) or 0) < LOW_ENERGY_STORED_RATIO
    local massIncome = tonumber(economy.massIncome) or 0
    local massRequested = tonumber(economy.massRequested)
        or tonumber(economy.massUsage)
        or 0
    local massStalled = massRequested > massIncome
        or (tonumber(economy.massTrend) or 0) < 0
        or (tonumber(economy.massStoredRatio) or 0) < 0.1
    local lostOutstanding = HasLostMex(massSites)
    local plannedPower = false
    local plannedFactory = false
    local plannedAirFactory = false
    local constructionPlanned = false
    local reclaimCandidates = CopyArray(snapshot.reclaim or {})
    table.sort(reclaimCandidates, function(a, b)
        local av = tonumber(a.mass) or -1
        local bv = tonumber(b.mass) or -1
        if av == bv then return tostring(a.key or '') < tostring(b.key or '') end
        return av > bv
    end)
    local virtualReclaim = {}
    local virtualFoundations = {}
    local activeReclaimJobs = 0
    for _, operation in ipairs(snapshot.pending or {}) do
        if operation.targetKey then virtualReclaim[operation.targetKey] = true end
        if operation.targetToken then virtualFoundations[operation.targetToken] = true end
        if operation.kind == 'reclaim' then
            activeReclaimJobs = activeReclaimJobs + 1
        end
        if operation.buildRole == 'power_generator' then
            plannedPower = true
        end
    end
    if macro then
        activeReclaimJobs = math.max(
            activeReclaimJobs,
            tonumber(macro.activeReclaimJobs) or 0
        )
    end
    local placementIndex = {
        power_generator = (counts.power_generator or 0) + 1,
        land_factory = (counts.land_factory or 0) + 1,
        air_factory = (counts.air_factory or 0) + 1,
    }
    local campaignActive = macro
        and macro.campaignEnabled == true
        and macro.campaignState ~= 'idle'
    local campaignJobPlanned = campaignActive
        and CampaignHasConnectedJob(snapshot, macro, massSites)
        or false
    for _, planned in ipairs(intents or {}) do
        if planned.siteKey and planned.buildRole then
            local plannedSite = CampaignSiteByKey(massSites, planned.siteKey)
            if not plannedSite then
                for _, site in ipairs(hydroSites) do
                    if site.key == planned.siteKey then plannedSite = site break end
                end
            end
            if plannedSite then
                ReserveSitePlacement(
                    planned.buildRole,
                    plannedSite,
                    virtualPlacements
                )
            end
        end
    end
    if campaignActive and not campaignJobPlanned then
        for _, planned in ipairs(intents or {}) do
            local site = CampaignSiteByKey(massSites, planned.siteKey)
            if (planned.kind == 'build_structure'
                    or planned.kind == 'assist_structure')
                and planned.buildRole == 'mass_extractor'
                and KeyInArray(macro.campaignMemberKeys, planned.siteKey)
                and SiteSupportsLandCampaign(site)
            then
                campaignJobPlanned = true
                break
            end
        end
    end
    local assignedEngineers = {}
    local expansionBudget = TableGetn(engineers)
    if macro and macro.allocatorEnabled == true then
        local expansionMassBudget = tonumber(
            macro.expansionRecurringMassBudget)
            or tonumber(macro.availableRecurringMass)
            or 0
        local expansionEnergyBudget = tonumber(
            macro.expansionRecurringEnergyBudget)
            or tonumber(macro.availableRecurringEnergy)
            or 0
        expansionBudget = math.min(
            math.floor(expansionMassBudget / 0.3 + 0.00001),
            math.floor(expansionEnergyBudget / 3 + 0.00001)
        )
        if expansionBudget < 1
            and (tonumber(macro.oneTimeMassReserve) or 0) >= 36
            and (tonumber(macro.oneTimeEnergyReserve) or 0) >= 360
        then
            expansionBudget = 1
        end
    end
    local remainingMexSlots = math.max(0, expansionBudget)
    local function AssignMexPairs(assignments, lostOnly, reservedActor)
        if remainingMexSlots <= 0 then return 0 end
        local pairs = {}
        for _, site in ipairs(massSites or {}) do
            local matchesKind = lostOnly and site.lost == true
                or (not lostOnly and site.lost ~= true)
            local connectedCampaignSite = campaignActive
                and KeyInArray(macro.campaignMemberKeys, site.key)
                and SiteSupportsLandCampaign(site)
            if matchesKind
                and SiteIsAvailable(site, virtualReserved, false)
                and (not connectedCampaignSite or not campaignJobPlanned)
            then
                for _, engineer in ipairs(engineers) do
                    if not assignedEngineers[engineer.token]
                        and engineer.token ~= reservedActor
                        and IsUsablePosition(engineer.position)
                        and CanBuild(engineer, 'mass_extractor')
                    then
                        local distance = PositionDistanceSquared(
                            engineer.position,
                            site.position
                        )
                        local speed = tonumber(engineer.moveSpeed) or 1.9
                        if not FiniteNumber(speed) or speed <= 0 then speed = 1.9 end
                        TableInsert(pairs, {
                            engineer = engineer,
                            site = site,
                            distance = distance,
                            roi = math.sqrt(distance) / speed * 10 + 300,
                        })
                    end
                end
            end
        end
        table.sort(pairs, function(a, b)
            if a.distance ~= b.distance then return a.distance < b.distance end
            if a.roi ~= b.roi then return a.roi < b.roi end
            local aSite = tostring(a.site.key or '')
            local bSite = tostring(b.site.key or '')
            if aSite ~= bSite then return aSite < bSite end
            return tostring(a.engineer.token or '')
                < tostring(b.engineer.token or '')
        end)
        local assigned = 0
        local chosenSites = {}
        for _, pair in ipairs(pairs) do
            local site = pair.site
            local engineer = pair.engineer
            local connectedCampaignSite = campaignActive
                and KeyInArray(macro.campaignMemberKeys, site.key)
                and SiteSupportsLandCampaign(site)
            if assigned < remainingMexSlots
                and not assignedEngineers[engineer.token]
                and not chosenSites[site.key]
                and SiteIsAvailable(site, virtualReserved, false)
                and (not connectedCampaignSite or not campaignJobPlanned)
                and ReserveSitePlacement(
                    'mass_extractor', site, virtualPlacements
                )
            then
                assignments[engineer.token] = site
                assignedEngineers[engineer.token] = true
                chosenSites[site.key] = true
                virtualReserved[site.key] = true
                assigned = assigned + 1
                if connectedCampaignSite then campaignJobPlanned = true end
            end
        end
        remainingMexSlots = remainingMexSlots - assigned
        return assigned
    end
    local lostAssignments = {}
    AssignMexPairs(lostAssignments, true, nil)
    lostOutstanding = false
    for _, site in ipairs(SortSites(massSites)) do
        local cappedCampaignSite = campaignActive
            and campaignJobPlanned
            and KeyInArray(macro.campaignMemberKeys, site.key)
            and SiteSupportsLandCampaign(site)
        if site.lost == true
            and SiteIsAvailable(site, virtualReserved, false)
            and not cappedCampaignSite
        then
            lostOutstanding = true
            break
        end
    end

    local foundationAssignments = {}
    local hydroAssignments = {}
    for _, foundation in ipairs(SortFoundations(snapshot.foundations or {})) do
        if type(foundation.targetToken) == 'string'
            and type(foundation.role) == 'string'
            and IsUsablePosition(foundation.position)
            and foundation.reserved ~= true
            and not virtualFoundations[foundation.targetToken]
        then
            local best = nil
            local bestDistance = nil
            for _, engineer in ipairs(engineers) do
                if not assignedEngineers[engineer.token]
                    and engineer.campaignEngineer ~= true
                    and CanBuild(engineer, foundation.role)
                then
                    local distance = PositionDistanceSquared(
                        engineer.position,
                        foundation.position
                    )
                    if not best
                        or distance < bestDistance
                        or (distance == bestDistance
                            and tostring(engineer.token) < tostring(best.token))
                    then
                        best = engineer
                        bestDistance = distance
                    end
                end
            end
            if best then
                foundationAssignments[best.token] = foundation
                assignedEngineers[best.token] = true
                virtualFoundations[foundation.targetToken] = true
            end
        end
    end

    local factoryTarget = macro and (tonumber(macro.factoryTarget)
        or tonumber(macro.factoryDemand)) or 2
    local placementAssignments = {}
    local reclaimPatrolAssignments = {}
    local function AssignPlacement(role, index, priority, reason)
        local hasBuilder = false
        for _, engineer in ipairs(engineers) do
            if not assignedEngineers[engineer.token]
                and engineer.campaignEngineer ~= true
                and CanBuild(engineer, role)
            then
                hasBuilder = true
                break
            end
        end
        if not hasBuilder then return false end
        local position = ReservePlacement(
            snapshot,
            role,
            index,
            virtualPlacements
        )
        if not position then return false end
        local best = nil
        local bestDistance = nil
        for _, engineer in ipairs(engineers) do
            if not assignedEngineers[engineer.token]
                and engineer.campaignEngineer ~= true
                and CanBuild(engineer, role)
            then
                local distance = PositionDistanceSquared(
                    engineer.position,
                    position
                )
                if not best
                    or distance < bestDistance
                    or (distance == bestDistance
                        and tostring(engineer.token) < tostring(best.token))
                then
                    best = engineer
                    bestDistance = distance
                end
            end
        end
        if not best then return false end
        placementAssignments[best.token] = BuildAtPlacement(
            best,
            role,
            position,
            priority,
            reason
        )
        assignedEngineers[best.token] = true
        return true
    end

    -- Required energy recovery owns its builder before speculative expansion
    -- lanes are assigned.  The allocator may later deny either request, but
    -- an unfunded/remote mex must never strand the power-recovery actor.
    if not underContact and allowPlacement and lowEnergy then
        if AssignPlacement(
            'power_generator',
            placementIndex.power_generator,
            19,
            'energy_recovery'
        ) then
            plannedPower = true
            placementIndex.power_generator = placementIndex.power_generator + 1
            counts.power_generator = (counts.power_generator or 0) + 1
        end
    end

    local completedMex = 0
    local completedLand = 0
    local completedHydro = 0
    local completedFactories = 0
    for _, unit in ipairs(units or {}) do
        if unit.complete == true then
            if (unit.roleFamily or unit.role) == 'mass_extractor' then
                completedMex = completedMex + 1
            end
            if unit.role == 'land_factory' or unit.role == 'land_factory_t2' then
                completedLand = completedLand + 1
            end
            if unit.role == 'land_factory'
                or unit.role == 'land_factory_t2'
                or unit.role == 'land_factory_t2_support'
                or unit.role == 'land_factory_t3'
                or unit.role == 'air_factory'
            then
                completedFactories = completedFactories + 1
            end
            if unit.role == 'hydrocarbon' then completedHydro = completedHydro + 1 end
        end
    end
    if not underContact and (counts.hydrocarbon or 0) < 1 then
        local site = FirstAvailableSite(hydroSites, virtualReserved, false)
        local best = nil
        local bestDistance = nil
        if site then
            for _, engineer in ipairs(engineers) do
                if not assignedEngineers[engineer.token]
                    and engineer.campaignEngineer ~= true
                    and CanBuild(engineer, 'hydrocarbon')
                then
                    local distance = PositionDistanceSquared(
                        engineer.position,
                        site.position
                    )
                    if not best
                        or distance < bestDistance
                        or (distance == bestDistance
                            and tostring(engineer.token) < tostring(best.token))
                    then
                        best = engineer
                        bestDistance = distance
                    end
                end
            end
        end
        if best and ReserveSitePlacement(
            'hydrocarbon',
            site,
            virtualPlacements
        ) then
            hydroAssignments[best.token] = site
            assignedEngineers[best.token] = true
            virtualReserved[site.key] = true
        end
    end
    if not underContact
        and (counts.air_factory or 0) < 1
        and completedMex >= 6
        and completedLand >= 2
        and completedHydro >= 1
        and FiniteNumber(economy.energyTrend)
        and FiniteNumber(economy.energyStoredRatio)
        and tonumber(economy.energyTrend) >= 0
        and tonumber(economy.energyStoredRatio) >= 0.5
    then
        if AssignPlacement(
            'air_factory',
            placementIndex.air_factory,
            20,
            'first_air_factory'
        ) then
            plannedAirFactory = true
            placementIndex.air_factory = placementIndex.air_factory + 1
            counts.air_factory = 1
        end
    end
    local currentFactories = (counts.land_factory or 0)
        + (counts.land_factory_t2 or 0)
        + (counts.air_factory or 0)
    local factoryDemand = macro and (tonumber(macro.factoryDemand) or currentFactories)
        or 3
    local sustainedFactory = not macro
        or (tonumber(macro.massSurplusTicks) or 0) >= 300
        or (tonumber(macro.factoryTarget) or 0) > currentFactories
    if not underContact
        and currentFactories >= 2
        and currentFactories < factoryDemand
        and (macro or (counts.mass_extractor or 0) >= 6)
        and sustainedFactory
        and not massStalled
    then
        if AssignPlacement(
            'land_factory',
            placementIndex.land_factory,
            21,
            macro and 'production_saturation' or 'third_factory'
        ) then
            plannedFactory = true
            placementIndex.land_factory = placementIndex.land_factory + 1
            counts.land_factory = (counts.land_factory or 0) + 1
        end
    end

    local adjacencyPowerTarget = math.min(10,
        math.max(4, completedFactories * 2))
    if not underContact
        and completedMex >= 6
        and (counts.power_generator or 0) < adjacencyPowerTarget
        and not plannedPower
    then
        local assignedPower = AssignPlacement(
            'power_generator',
            placementIndex.power_generator,
            19,
            'factory_adjacency_power'
        )
        if not assignedPower
            and reclaimPatrolAcu
            and CanBuild(reclaimPatrolAcu, 'power_generator')
        then
            local acuClaimed = false
            for _, existing in ipairs(intents or {}) do
                if existing.actorToken == reclaimPatrolAcu.token then
                    acuClaimed = true
                    break
                end
            end
            if not acuClaimed then
                local position = ReservePlacement(
                    snapshot,
                    'power_generator',
                    placementIndex.power_generator,
                    virtualPlacements
                )
                if position then
                    AddIntent(intents, BuildAtPlacement(
                        reclaimPatrolAcu,
                        'power_generator',
                        position,
                        19,
                        'factory_adjacency_power'
                    ))
                    reclaimPatrolAcu = nil
                    assignedPower = true
                end
            end
        end
        if assignedPower then
            plannedPower = true
            placementIndex.power_generator = placementIndex.power_generator + 1
            counts.power_generator = (counts.power_generator or 0) + 1
        end
    end

    if not underContact
        and (not reclaimPatrolActive or reclaimPatrolAcu ~= nil)
        and activeReclaimJobs == 0
        and completedMex >= 4
        and (TableGetn(engineers) >= 4 or reclaimPatrolAcu ~= nil)
    then
        local siteKeys = {}
        local waypoints = {}
        for _, site in ipairs(SortSites(massSites)) do
            if site.complete == true
                and site.localSite == true
                and type(site.key) == 'string'
                and IsUsablePosition(site.position)
                and TableGetn(siteKeys) < 4
            then
                TableInsert(siteKeys, site.key)
                TableInsert(waypoints, {
                    site.position[1],
                    site.position[2],
                    site.position[3],
                })
            end
        end
        if TableGetn(siteKeys) >= 2 then
            local best = nil
            local bestDistance = nil
            if reclaimPatrolAcu then
                local claimed = false
                for _, existing in ipairs(intents) do
                    if existing.actorToken == reclaimPatrolAcu.token then
                        claimed = true
                        break
                    end
                end
                if not claimed then best = reclaimPatrolAcu end
            end
            if not best and TableGetn(engineers) >= 4 then
                for _, engineer in ipairs(engineers) do
                    if not assignedEngineers[engineer.token]
                        and engineer.campaignEngineer ~= true
                        and IsUsablePosition(engineer.position)
                    then
                        local distance = PositionDistanceSquared(
                            engineer.position,
                            snapshot.basePosition
                        )
                        if not best
                            or distance < bestDistance
                            or (distance == bestDistance
                                and tostring(engineer.token) < tostring(best.token))
                        then
                            best = engineer
                            bestDistance = distance
                        end
                    end
                end
            end
            if best then
                assignedEngineers[best.token] = true
                reclaimPatrolAssignments[best.token] = {
                    siteKeys = siteKeys,
                    waypoints = waypoints,
                }
                if best.role == 'acu' then
                    AddIntent(intents, {
                        kind = 'reclaim_patrol',
                        actorToken = best.token,
                        siteKeys = siteKeys,
                        waypoints = waypoints,
                        priority = 49,
                        reason = 'home_reclaim_patrol',
                    })
                end
            end
        end
    end

    -- Once required energy and the first strategic production milestone have
    -- had a chance to reserve their nearest home builder, the secured campaign
    -- may use every remaining engineer for distinct expansion opportunities.
    local expansionAssignments = {}
    local reservedReclaimActor = nil
    if macro and macro.allocatorEnabled == true then
        for _, candidate in ipairs(reclaimCandidates) do
            for _, engineer in ipairs(engineers) do
                if not assignedEngineers[engineer.token]
                    and candidate.observerToken == engineer.token
                    and ReclaimVisibleToEngineer(candidate, engineer)
                then
                    reservedReclaimActor = engineer.token
                    break
                end
            end
            if reservedReclaimActor then break end
        end
        AssignMexPairs(expansionAssignments, false, reservedReclaimActor)
        if TableGetn(engineers) == 1
            and remainingMexSlots > 0
            and reservedReclaimActor
        then
            AssignMexPairs(expansionAssignments, false, nil)
        end
    end

    for _, engineer in ipairs(engineers) do
        local intent = nil
        local campaignActor = campaignActive
            and engineer.campaignEngineer == true
        local reserveCampaignActor = false
        if not underContact and CanBuild(engineer, 'mass_extractor') then
            local lost = lostAssignments[engineer.token]
            if lost then
                counts.mass_extractor = (counts.mass_extractor or 0) + 1
                intent = BuildAtSite(engineer, 'mass_extractor', lost, 18, 'rebuild_mex')
                if campaignActive
                    and KeyInArray(macro.campaignMemberKeys, lost.key)
                    and SiteSupportsLandCampaign(lost)
                then
                    intent.clusterKey = macro.campaignCluster
                    campaignJobPlanned = true
                end
            end
        end
        if not intent and foundationAssignments[engineer.token] then
            intent = AssistFoundation(
                engineer,
                foundationAssignments[engineer.token]
            )
        end
        if not intent and hydroAssignments[engineer.token] then
            counts.hydrocarbon = (counts.hydrocarbon or 0) + 1
            intent = BuildAtSite(
                engineer,
                'hydrocarbon',
                hydroAssignments[engineer.token],
                20,
                'first_hydro'
            )
        end
        if not intent and placementAssignments[engineer.token] then
            intent = placementAssignments[engineer.token]
        end
        if not intent and reclaimPatrolAssignments[engineer.token] then
            local patrol = reclaimPatrolAssignments[engineer.token]
            intent = {
                kind = 'reclaim_patrol',
                actorToken = engineer.token,
                siteKeys = patrol.siteKeys,
                waypoints = patrol.waypoints,
                priority = 49,
                reason = 'home_reclaim_patrol',
            }
        end
        if not intent and expansionAssignments[engineer.token] then
            local assignedSite = expansionAssignments[engineer.token]
            counts.mass_extractor = (counts.mass_extractor or 0) + 1
            intent = BuildAtSite(
                engineer,
                'mass_extractor',
                assignedSite,
                22,
                'frontier_expansion'
            )
            if campaignActive
                and KeyInArray(macro.campaignMemberKeys, assignedSite.key)
                and SiteSupportsLandCampaign(assignedSite)
            then
                intent.clusterKey = macro.campaignCluster
            elseif campaignActive then
                intent.clusterKey = nil
            end
        end
        if not intent and campaignActive
            and not campaignJobPlanned
            and not underContact
            and CanBuild(engineer, 'mass_extractor')
        then
            local cachedLost = FirstCampaignSite(
                massSites,
                virtualReserved,
                macro.campaignMemberKeys,
                true
            )
            if cachedLost and ReserveSitePlacement(
                'mass_extractor',
                cachedLost,
                virtualPlacements
            ) then
                virtualReserved[cachedLost.key] = true
                counts.mass_extractor = (counts.mass_extractor or 0) + 1
                intent = BuildAtSite(
                    engineer,
                    'mass_extractor',
                    cachedLost,
                    18,
                    'rebuild_mex'
                )
                intent.clusterKey = macro.campaignCluster
                campaignJobPlanned = true
            end
        end
        if not intent
            and campaignActor
            and not campaignJobPlanned
            and not underContact
            and CanBuild(engineer, 'mass_extractor')
        then
            local lost = FirstCampaignLostSite(massSites, virtualReserved)
            if lost and ReserveSitePlacement(
                'mass_extractor',
                lost,
                virtualPlacements
            ) then
                virtualReserved[lost.key] = true
                counts.mass_extractor = (counts.mass_extractor or 0) + 1
                intent = BuildAtSite(
                    engineer,
                    'mass_extractor',
                    lost,
                    18,
                    'rebuild_mex'
                )
                intent.clusterKey = macro.campaignCluster
                campaignJobPlanned = true
            end
        end
        if not intent
            and campaignActive
            and not campaignJobPlanned
            and (macro.campaignState == 'active'
                or macro.campaignState == 'awaiting_order'
                or macro.campaignState == 'early_awaiting_order'
                or macro.campaignState == 'recalled')
            and not underContact
            and CanBuild(engineer, 'mass_extractor')
        then
            local cached = FirstCampaignSite(
                massSites,
                virtualReserved,
                macro.campaignMemberKeys,
                false
            )
            if cached and ReserveSitePlacement(
                'mass_extractor',
                cached,
                virtualPlacements
            ) then
                virtualReserved[cached.key] = true
                counts.mass_extractor = (counts.mass_extractor or 0) + 1
                intent = BuildAtSite(
                    engineer,
                    'mass_extractor',
                    cached,
                    22,
                    'frontier_expansion'
                )
                intent.clusterKey = macro.campaignCluster
                campaignJobPlanned = true
            end
        end
        if not intent
            and campaignActor
            and not campaignJobPlanned
            and macro.campaignState == 'awaiting_objective'
            and not underContact
            and CanBuild(engineer, 'mass_extractor')
        then
            local nextSite = FirstFrontierSite(
                massSites,
                virtualReserved,
                macro.selectedFrontierSite,
                true
            )
            if nextSite and ReserveSitePlacement(
                'mass_extractor',
                nextSite,
                virtualPlacements
            ) then
                virtualReserved[nextSite.key] = true
                counts.mass_extractor = (counts.mass_extractor or 0) + 1
                intent = BuildAtSite(
                    engineer,
                    'mass_extractor',
                    nextSite,
                    22,
                    'frontier_expansion'
                )
                campaignJobPlanned = true
            end
        end
        if campaignActor and not intent
            and not (macro and macro.allocatorEnabled == true)
        then
            reserveCampaignActor = true
        end

        if not intent
            and not reserveCampaignActor
            and not underContact
            and CanBuild(engineer, 'mass_extractor')
        then
            local site = FirstLostSite(massSites, virtualReserved, false)
            if site
                and campaignActive
                and campaignJobPlanned
                and KeyInArray(macro.campaignMemberKeys, site.key)
                and SiteSupportsLandCampaign(site)
            then
                site = nil
                for _, candidate in ipairs(SortSites(massSites)) do
                    if candidate.lost == true
                        and SiteIsAvailable(candidate, virtualReserved, false)
                        and not (KeyInArray(
                                macro.campaignMemberKeys,
                                candidate.key
                            ) and SiteSupportsLandCampaign(candidate))
                    then
                        site = candidate
                        break
                    end
                end
            end
            if site and ReserveSitePlacement(
                'mass_extractor',
                site,
                virtualPlacements
            ) then
                virtualReserved[site.key] = true
                counts.mass_extractor = (counts.mass_extractor or 0) + 1
                intent = BuildAtSite(engineer, 'mass_extractor', site, 18, 'rebuild_mex')
                if campaignActive
                    and KeyInArray(macro.campaignMemberKeys, site.key)
                    and SiteSupportsLandCampaign(site)
                then
                    intent.clusterKey = macro.campaignCluster
                    campaignJobPlanned = true
                end
            end
        end


        if not intent and not reserveCampaignActor and not underContact then
            local foundation = FirstOrphanFoundation(
                snapshot,
                engineer,
                virtualFoundations
            )
            if foundation then
                virtualFoundations[foundation.targetToken] = true
                intent = AssistFoundation(engineer, foundation)
            end
        end

        if not intent
            and not reserveCampaignActor
            and (not lostOutstanding or (macro and macro.allocatorEnabled == true))
            and lowEnergy
            and allowPlacement
            and not plannedPower
            and CanBuild(engineer, 'power_generator')
        then
            local position = ReservePlacement(snapshot, 'power_generator', placementIndex.power_generator, virtualPlacements)
            if position then
                plannedPower = true
                placementIndex.power_generator = placementIndex.power_generator + 1
                counts.power_generator = (counts.power_generator or 0) + 1
                intent = BuildAtPlacement(engineer, 'power_generator', position, 19, 'energy_recovery')
            end
        end

        if not intent
            and not reserveCampaignActor
            and (not lostOutstanding or (macro and macro.allocatorEnabled == true))
            and not underContact
            and (counts.hydrocarbon or 0) < 1
            and CanBuild(engineer, 'hydrocarbon')
        then
            local site = FirstAvailableSite(hydroSites, virtualReserved, false)
            if site and ReserveSitePlacement(
                'hydrocarbon',
                site,
                virtualPlacements
            ) then
                virtualReserved[site.key] = true
                counts.hydrocarbon = (counts.hydrocarbon or 0) + 1
                intent = BuildAtSite(engineer, 'hydrocarbon', site, 20, 'first_hydro')
            end
        end

        if not intent
            and not reserveCampaignActor
            and not underContact
            and not plannedFactory
            and CanBuild(engineer, 'land_factory')
        then
            local currentFactories = (counts.land_factory or 0)
                + (counts.land_factory_t2 or 0)
                + (counts.air_factory or 0)
            local factoryDemand = macro and (tonumber(macro.factoryDemand) or currentFactories) or 3
            local sustained = not macro
                or (tonumber(macro.massSurplusTicks) or 0) >= 300
                or (tonumber(macro.factoryTarget) or 0) > currentFactories
            if currentFactories >= 2
                and currentFactories < factoryDemand
                and (macro or (counts.mass_extractor or 0) >= 6)
                and sustained
                and not massStalled
            then
                local position = ReservePlacement(snapshot, 'land_factory', placementIndex.land_factory, virtualPlacements)
                if position then
                    plannedFactory = true
                    placementIndex.land_factory = placementIndex.land_factory + 1
                    counts.land_factory = (counts.land_factory or 0) + 1
                    intent = BuildAtPlacement(
                        engineer,
                        'land_factory',
                        position,
                        21,
                        macro and 'production_saturation' or 'third_factory'
                    )
                end
            end
        end

        if not intent
            and not reserveCampaignActor
            and not underContact
            and not plannedAirFactory
            and (counts.air_factory or 0) < 1
            and completedMex >= 6
            and completedLand >= 2
            and completedHydro >= 1
            and FiniteNumber(economy.energyTrend)
            and FiniteNumber(economy.energyStoredRatio)
            and tonumber(economy.energyTrend) >= 0
            and tonumber(economy.energyStoredRatio) >= 0.5
            and CanBuild(engineer, 'air_factory')
        then
            local position = ReservePlacement(
                snapshot,
                'air_factory',
                placementIndex.air_factory,
                virtualPlacements
            )
            if position then
                plannedAirFactory = true
                counts.air_factory = 1
                intent = BuildAtPlacement(
                    engineer,
                    'air_factory',
                    position,
                    20,
                    'first_air_factory'
                )
            end
        end

        if not intent
            and not reserveCampaignActor
            and (not lostOutstanding or (macro and macro.allocatorEnabled == true))
            and not underContact
            and CanBuild(engineer, 'mass_extractor')
        then
            local site = nil
            if campaignActive then
                if not campaignJobPlanned
                    and macro.campaignState == 'awaiting_objective'
                then
                    site = FirstFrontierSite(
                        massSites,
                        virtualReserved,
                        macro.selectedFrontierSite,
                        true
                    )
                elseif not campaignJobPlanned
                    and macro.campaignState == 'active'
                then
                    site = FirstCampaignSite(
                        massSites,
                        virtualReserved,
                        macro.campaignMemberKeys,
                        false
                    )
                elseif campaignJobPlanned then
                    for _, candidate in ipairs(SortSites(massSites)) do
                        if (macro.allocatorEnabled == true
                                or candidate.frontierSelected == true)
                            and candidate.lost ~= true
                            and not KeyInArray(
                                macro.campaignMemberKeys,
                                candidate.key
                            )
                            and SiteIsAvailable(
                                candidate,
                                virtualReserved,
                                false
                            )
                        then
                            site = candidate
                            break
                        end
                    end
                end
            elseif macro then
                site = FirstFrontierSite(
                    massSites,
                    virtualReserved,
                    macro.selectedFrontierSite
                )
            else
                site = FirstAvailableSite(massSites, virtualReserved, false)
            end
            if site and not ReserveSitePlacement(
                'mass_extractor',
                site,
                virtualPlacements
            ) then
                site = nil
            end
            if not site then
                for _, candidate in ipairs(SortSites(massSites)) do
                    local frontierAllowed = not macro
                        or macro.allocatorEnabled == true
                        or (candidate.frontierSelected == true
                            and candidate.lost ~= true)
                    local campaignAllowed = not campaignActive
                        or not campaignJobPlanned
                        or not KeyInArray(
                            macro.campaignMemberKeys,
                            candidate.key
                        )
                    if frontierAllowed
                        and campaignAllowed
                        and SiteIsAvailable(candidate, virtualReserved, false)
                        and ReserveSitePlacement(
                            'mass_extractor',
                            candidate,
                            virtualPlacements
                        )
                    then
                        site = candidate
                        break
                    end
                end
            end
            if site then
                virtualReserved[site.key] = true
                counts.mass_extractor = (counts.mass_extractor or 0) + 1
                intent = BuildAtSite(
                    engineer,
                    'mass_extractor',
                    site,
                    22,
                    macro and 'frontier_expansion' or 'mass_expansion'
                )
                if campaignActive
                    and not campaignJobPlanned
                    and KeyInArray(macro.campaignMemberKeys, site.key)
                    and SiteSupportsLandCampaign(site)
                then
                    intent.clusterKey = macro.campaignCluster
                    campaignJobPlanned = true
                elseif campaignActive then
                    intent.clusterKey = nil
                end
            end
        end

        if not intent
            and not reserveCampaignActor
            and macro
            and not underContact
            and activeReclaimJobs < MAX_ACTIVE_RECLAIM_JOBS
        then
            for _, candidate in ipairs(reclaimCandidates) do
                if type(candidate.key) == 'string'
                    and IsUsablePosition(candidate.position)
                    and candidate.reserved ~= true
                    and not virtualReclaim[candidate.key]
                    and (tonumber(candidate.mass) or 0) > 0
                    and ReclaimVisibleToEngineer(candidate, engineer)
                then
                    activeReclaimJobs = activeReclaimJobs + 1
                    virtualReclaim[candidate.key] = true
                    intent = {
                        kind = 'reclaim',
                        actorToken = engineer.token,
                        targetKey = candidate.key,
                        targetValue = candidate.mass,
                        priority = 50,
                        reason = 'controlled_reclaim',
                    }
                    break
                end
            end
        end

        if intent then
            if intent.kind == 'build_structure' or intent.kind == 'assist_structure' then
                constructionPlanned = true
            end
            AddIntent(intents, intent)
        end
    end
end

local function NextCombatRole(counts)
    local tanks = counts.tank or 0
    local artillery = counts.artillery or 0
    local antiAir = counts.anti_air or 0
    local combat = tanks + artillery + antiAir + (counts.lab or 0)

    if artillery * 5 < tanks then
        return 'artillery'
    end
    if combat >= 10 and antiAir * 12 < combat then
        return 'anti_air'
    end
    return 'tank'
end

local function FactoryDecisions(snapshot, units, counts, pendingActors, intents)
    local macro = type(snapshot.macro) == 'table' and snapshot.macro or nil
    local economy = snapshot.economy or {}
    local engineerDemand = macro and (tonumber(macro.engineerDemand) or 2) or 3
    local massIncome = tonumber(economy.massIncome) or 0
    local massRequested = tonumber(economy.massRequested)
        or tonumber(economy.massUsage)
        or 0
    local massStalled = massRequested > massIncome
        or (tonumber(economy.massTrend) or 0) < 0
        or (tonumber(economy.massStoredRatio) or 0) < 0.1
    local plannedEngineer = false
    local plannedEngineerCount = 0
    local protectedCombatOutstanding = false
    local plannedAirScreen = false
    local plannedAirScout = false
    for _, operation in ipairs(snapshot.pending or {}) do
        if operation.kind == 'factory_build'
            and (operation.buildRole == 'tank'
                or operation.buildRole == 'artillery'
                or operation.buildRole == 'anti_air'
                or operation.buildRole == 'lab')
        then
            protectedCombatOutstanding = true
        elseif operation.kind == 'factory_build'
            and operation.buildRole == 'engineer'
        then
            plannedEngineer = true
            plannedEngineerCount = plannedEngineerCount + 1
        elseif operation.kind == 'factory_build'
            and operation.buildRole == 'interceptor'
        then
            plannedAirScreen = true
        elseif operation.kind == 'factory_build'
            and operation.buildRole == 'air_scout'
        then
            plannedAirScout = true
        end
    end
    local completedEngineers = 0
    for _, unit in ipairs(units or {}) do
        if unit.role == 'engineer' and unit.complete == true then
            completedEngineers = completedEngineers + 1
        end
    end
    local recoveryMode = completedEngineers < MIN_RECOVERY_ENGINEERS
    local recoveryOutstanding = (counts.engineer or 0) >= MIN_RECOVERY_ENGINEERS
    local plannedAllocatorCombat = protectedCombatOutstanding
    local plannedUpgrade = false
    local completedMex = 0
    local completedLand = 0
    local completedAir = 0
    local completedAirScout = 0
    for _, unit in ipairs(units or {}) do
        if unit.complete == true then
            if (unit.roleFamily or unit.role) == 'mass_extractor' then
                completedMex = completedMex + 1
            end
            if unit.role == 'land_factory' then completedLand = completedLand + 1 end
            if unit.role == 'air_factory' then completedAir = completedAir + 1 end
            if unit.role == 'air_scout' then completedAirScout = completedAirScout + 1 end
        end
    end
    local protectLandCombat = macro
        and macro.allocatorEnabled == true
        and completedLand >= 1
        and (completedEngineers >= MIN_RECOVERY_ENGINEERS
            or (completedLand >= 2 and completedEngineers >= 1))
    local massStored = tonumber(economy.massStoredRatio)
    local energyStored = tonumber(economy.energyStoredRatio)
    local massTrend = tonumber(economy.massTrend)
    local energyTrend = tonumber(economy.energyTrend)
    local massIncome = tonumber(economy.massIncome)
    local massRequested = tonumber(economy.massRequested)
    local energyIncome = tonumber(economy.energyIncome)
    local energyRequested = tonumber(economy.energyRequested)
    local energyUsage = tonumber(economy.energyUsage)
    local t2Ready = FiniteNumber(massStored)
        and FiniteNumber(energyStored)
        and FiniteNumber(massTrend)
        and FiniteNumber(energyTrend)
        and FiniteNumber(economy.massIncome)
        and FiniteNumber(economy.massRequested)
        and FiniteNumber(economy.energyIncome)
        and FiniteNumber(economy.energyRequested)
        and FiniteNumber(economy.energyUsage)
        and massIncome >= 0
        and massRequested >= 0
        and massRequested <= massIncome
        and energyIncome >= 0
        and energyRequested >= 0
        and energyRequested <= energyIncome
        and energyUsage >= 0
        and completedMex >= 10
        and completedLand >= 3
        and completedAir >= 1
        and (counts.land_factory_t2 or 0) < 1
        and massStored >= 0.5
        and energyStored >= 0.5
        and massTrend >= 0
        and energyTrend >= 0
    if macro and macro.allocatorEnabled == true then
        t2Ready = macro.economyLedgerValid == true
            and macro.techAdmission == 'admitted'
    end
    local rallyPosition = macro and macro.rallyPosition
        or snapshot.rallyPosition
        or snapshot.basePosition
    for _, factory in ipairs(units) do
        if factory.role == 'air_factory'
            and factory.complete == true
            and factory.idle == true
            and not pendingActors[factory.token]
        then
            if completedAirScout < 1
                and not plannedAirScout
                and CanBuild(factory, 'air_scout')
            then
                AddIntent(intents, {
                    kind = 'factory_build',
                    actorToken = factory.token,
                    buildRole = 'air_scout',
                    priority = 24,
                    reason = 'initial_frontier_air_scout',
                })
                plannedAirScout = true
            elseif completedAirScout >= 1
                and not plannedAirScreen
                and (counts.interceptor or 0) < 4
                and CanBuild(factory, 'interceptor')
            then
                AddIntent(intents, {
                    kind = 'factory_build',
                    actorToken = factory.token,
                    buildRole = 'interceptor',
                    priority = 31,
                    reason = 'persistent_air_screen',
                })
                counts.interceptor = (counts.interceptor or 0) + 1
                plannedAirScreen = true
            end
        elseif factory.role == 'land_factory_t2'
            and factory.complete == true
            and factory.idle == true
            and not pendingActors[factory.token]
        then
            local t2Combat = (counts.t2_direct_fire or 0) + (counts.t2_anti_air or 0)
            local role = 't2_direct_fire'
            if t2Combat >= 4 and (counts.t2_anti_air or 0) * 5 < t2Combat then
                role = 't2_anti_air'
            end
            if CanBuild(factory, role) then
                AddIntent(intents, {
                    kind = 'factory_build',
                    actorToken = factory.token,
                    buildRole = role,
                    priority = 31,
                    reason = 'continuous_t2_ground_production',
                })
                counts[role] = (counts[role] or 0) + 1
            end
        elseif factory.role == 'land_factory'
            and factory.complete == true
            and factory.idle == true
            and not pendingActors[factory.token]
        then
            if t2Ready
                and not plannedUpgrade
                and CanBuild(factory, 'land_factory_t2')
            then
                AddIntent(intents, {
                    kind = 'factory_upgrade',
                    actorToken = factory.token,
                    upgradeRole = 'land_factory_t2',
                    priority = 23,
                    reason = 'first_t2_land_hq',
                })
                plannedUpgrade = true
                counts.land_factory_t2 = 1
            elseif factory.needsRally == true then
                AddIntent(intents, {
                    kind = 'rally',
                    actorToken = factory.token,
                    position = rallyPosition,
                    priority = 30,
                    reason = 'controlled_rally',
                })
            else
                local role = nil
                local reason = 'continuous_land_production'
                if recoveryMode
                    and not plannedEngineer
                    and not recoveryOutstanding
                    and CanBuild(factory, 'engineer')
                then
                    role = 'engineer'
                    reason = 'recovery_engineer_floor'
                    plannedEngineer = true
                    plannedEngineerCount = plannedEngineerCount + 1
                    recoveryOutstanding = true
                elseif protectLandCombat
                    and not plannedAllocatorCombat
                then
                    local candidate = NextCombatRole(counts)
                    if CanBuild(factory, candidate) then
                        role = candidate
                        plannedAllocatorCombat = true
                    elseif CanBuild(factory, 'tank') then
                        role = 'tank'
                        plannedAllocatorCombat = true
                    end
                elseif not recoveryMode
                    and plannedEngineerCount < 2
                    and macro
                    and macro.allocatorEnabled == true
                    and (macro.unlockingEngineerNeeded == true
                        or (protectLandCombat
                            and completedLand >= 2
                            and completedEngineers < engineerDemand))
                    and (counts.engineer or 0) < engineerDemand
                    and CanBuild(factory, 'engineer')
                then
                    role = 'engineer'
                    reason = 'unlock_profitable_expansion'
                    plannedEngineer = true
                    plannedEngineerCount = plannedEngineerCount + 1
                elseif not recoveryMode
                    and plannedEngineerCount < 2
                    and not massStalled
                    and (counts.engineer or 0) < engineerDemand
                    and CanBuild(factory, 'engineer')
                then
                    role = 'engineer'
                    reason = macro and 'construction_capacity' or reason
                    plannedEngineer = true
                    plannedEngineerCount = plannedEngineerCount + 1
                elseif not recoveryMode
                    and (counts.scout or 0) < 1
                    and CanBuild(factory, 'scout')
                then
                    role = 'scout'
                elseif not recoveryMode then
                    local candidate = NextCombatRole(counts)
                    if CanBuild(factory, candidate) then
                        role = candidate
                    elseif CanBuild(factory, 'tank') then
                        role = 'tank'
                    end
                end

                if role then
                    AddIntent(intents, {
                        kind = 'factory_build',
                        actorToken = factory.token,
                        buildRole = role,
                        priority = 31,
                        reason = reason,
                    })
                    counts[role] = (counts[role] or 0) + 1
                end
            end
        end
    end
    local patrol = {}
    for _, unit in ipairs(units or {}) do
        if unit.role == 'interceptor'
            and unit.complete == true
            and unit.idle == true
            and unit.airAssigned ~= true
            and not pendingActors[unit.token]
        then
            TableInsert(patrol, unit.token)
        end
    end
    if TableGetn(patrol) > 0 and IsUsablePosition(snapshot.basePosition) then
        table.sort(patrol)
        AddIntent(intents, {
            kind = 'air_screen',
            actorTokens = patrol,
            position = snapshot.basePosition,
            priority = 32,
            reason = 'defensive_air_screen',
        })
    end
    local selectedSite = nil
    if macro
        and type(macro.selectedFrontierSite) == 'string'
        and macro.selectedFrontierSite ~= 'none'
    then
        for _, site in ipairs(((snapshot.sites or {}).mass) or {}) do
            if site.key == macro.selectedFrontierSite
                and IsUsablePosition(site.position)
                and IsUsablePosition(snapshot.basePosition)
                and PositionDistanceSquared(site.position, snapshot.basePosition) > 0.01
            then
                selectedSite = site
                break
            end
        end
    end
    if selectedSite then
        for _, unit in ipairs(units or {}) do
            if unit.role == 'air_scout'
                and unit.complete == true
                and unit.idle == true
                and unit.airScoutAssigned ~= true
                and not pendingActors[unit.token]
            then
                AddIntent(intents, {
                    kind = 'air_scout',
                    actorToken = unit.token,
                    siteKey = selectedSite.key,
                    position = selectedSite.position,
                    priority = 32,
                    reason = 'public_frontier_recon',
                })
                break
            end
        end
    end
end

local function AttackDecision(snapshot, units, pendingActors, state, intents)
    if snapshot.targetPath ~= true or not IsUsablePosition(snapshot.targetPosition) then
        return false
    end

    if state and state.commanderMobilizing == true then
        local acu = FindAcu(units)
        local health = acu and tonumber(acu.healthRatio) or nil
        if state.initialWaveSent == true
            or not acu
            or not health
            or health < COMMANDER_PUSH_HEALTH_RATIO
            or pendingActors[acu.token]
        then
            return true
        end
        if acu.idle ~= true or acu.nearStaging ~= true then
            return true
        end
        local escorts = {}
        for _, unit in ipairs(units) do
            if COMBAT_ROLES[unit.role]
                and unit.complete == true
                and unit.assignedToWave == true
                and unit.commanderEscort == true
            then
                TableInsert(escorts, unit)
            end
        end
        if TableGetn(escorts) > 0 then
            AddIntent(intents, {
                kind = 'commander_push',
                acuToken = acu.token,
                actorTokens = ActorTokens(escorts),
                position = snapshot.targetPosition,
                priority = 1,
                reason = 'acu_led_concentration',
            })
        end
        return true
    end

    if not state then
        return false
    end

    local combat, artillery = CombatUnits(units)

    if state.commanderPushActive == true then
        local acu = FindAcu(units)
        if acu then
            local health = tonumber(acu.healthRatio)
            if not health or health < COMMANDER_PUSH_HEALTH_RATIO then
                return false
            end
            if TableGetn(combat) > 0 then
                AddIntent(intents, {
                    kind = 'reinforce_commander',
                    acuToken = acu.token,
                    actorTokens = ActorTokens(combat),
                    position = snapshot.targetPosition,
                    priority = 40,
                    reason = 'reinforce_commander',
                })
            end
            return true
        end
    end

    if TableGetn(combat) < ATTACK_COMBAT or artillery < ATTACK_ARTILLERY then
        return false
    end

    if state.initialWaveSent ~= true then
        local acu = FindAcu(units)
        local health = acu and tonumber(acu.healthRatio) or nil
        if not acu
            or not health
            or health < COMMANDER_PUSH_HEALTH_RATIO
            or pendingActors[acu.token]
        then
            return false
        end
        if acu.idle ~= true then
            return true
        end
        if acu.nearStaging == false and IsUsablePosition(snapshot.stagingPosition) then
            AddIntent(intents, {
                kind = 'mobilize_commander',
                acuToken = acu.token,
                actorTokens = ActorTokens(combat),
                position = snapshot.stagingPosition,
                priority = 1,
                reason = 'assemble_commander',
            })
            return true
        end
        if acu.nearStaging ~= true then
            return true
        end
        AddIntent(intents, {
            kind = 'commander_push',
            acuToken = acu.token,
            actorTokens = ActorTokens(combat),
            position = snapshot.targetPosition,
            priority = 40,
            reason = 'acu_led_concentration',
        })
        return true
    end

    if state.commanderRetreating ~= true then
        AddIntent(intents, {
            kind = 'attack_wave',
            actorTokens = ActorTokens(combat),
            position = snapshot.targetPosition,
            priority = 40,
            reason = 'concentration_gate',
        })
    end
    return false
end

local function FrontierScreenDecision(snapshot, units, pendingActors, intents)
    local macro = type(snapshot.macro) == 'table' and snapshot.macro or nil
    if not macro then return end
    local currentScreen = math.max(0, tonumber(macro.frontierScreenCount) or 0)
    local engineerToken = nil
    local clusterKey = nil
    for _, operation in ipairs(snapshot.pending or {}) do
        if operation.reason == 'frontier_expansion'
            and type(operation.actorToken) == 'string'
        then
            engineerToken = operation.actorToken
            clusterKey = operation.clusterKey
            break
        end
    end
    if not engineerToken then
        for _, intent in ipairs(intents or {}) do
            if intent.reason == 'frontier_expansion'
                and type(intent.actorToken) == 'string'
            then
                engineerToken = intent.actorToken
                clusterKey = intent.clusterKey
                break
            end
        end
    end
    if not engineerToken then return end
    local engineer = nil
    local available = {}
    local antiAir = {}
    local frontierEscorts = {}
    local frontierNonAir = {}
    local screenHasAntiAir = false
    for _, unit in ipairs(units or {}) do
        if unit.token == engineerToken
            and unit.role == 'engineer'
            and unit.complete == true
        then
            engineer = unit
        elseif COMBAT_ROLES[unit.role] and unit.complete == true then
            if unit.frontierEscort == true then
                TableInsert(frontierEscorts, unit)
                if unit.role == 'anti_air' or unit.role == 't2_anti_air' then
                    screenHasAntiAir = true
                else
                    TableInsert(frontierNonAir, unit)
                end
            elseif unit.assignedToWave ~= true and not pendingActors[unit.token] then
                TableInsert(available, unit)
                if unit.role == 'anti_air' or unit.role == 't2_anti_air' then
                    TableInsert(antiAir, unit)
                end
            end
        end
    end
    local screenTarget = math.min(4, currentScreen + TableGetn(available) - 4)
    local screenSize = screenTarget - currentScreen
    local displacedToken = nil
    if screenSize <= 0
        and currentScreen >= 1
        and currentScreen <= 4
        and TableGetn(frontierEscorts) == currentScreen
        and not screenHasAntiAir
        and TableGetn(antiAir) > 0
        and TableGetn(available) >= 4
        and TableGetn(frontierNonAir) > 0
    then
        screenSize = 1
        displacedToken = frontierNonAir[1].token
    elseif screenSize <= 0
        and not screenHasAntiAir
        and TableGetn(antiAir) > 0
        and TableGetn(available) > 4
    then
        screenSize = 1
    end
    if not engineer or screenSize <= 0 then return end
    local selected = {}
    local selectedTokens = {}
    if TableGetn(antiAir) > 0 then
        TableInsert(selected, antiAir[1])
        selectedTokens[antiAir[1].token] = true
    end
    for _, unit in ipairs(available) do
        if TableGetn(selected) < screenSize and not selectedTokens[unit.token] then
            TableInsert(selected, unit)
            selectedTokens[unit.token] = true
        end
    end
    local intent = {
        kind = 'frontier_screen',
        engineerToken = engineerToken,
        actorTokens = ActorTokens(selected),
        clusterKey = clusterKey or tostring(macro.selectedFrontierCluster or 'none'),
        priority = 24,
        reason = 'secure_frontier',
    }
    if displacedToken then intent.displacedToken = displacedToken end
    AddIntent(intents, intent)
end

local function FieldCampaignDecision(snapshot, intents)
    local macro = type(snapshot.macro) == 'table' and snapshot.macro or nil
    if not macro or macro.campaignEnabled ~= true then return end
    local mode = macro.campaignIntentMode
    local allowed = {
        activate = true,
        reinforce = true,
        transition = true,
        assault = true,
        recover = true,
        recall = true,
        resume = true,
        rollback = true,
        route_probe = true,
        route_commit = true,
        route_release = true,
    }
    if type(mode) ~= 'string' or not allowed[mode] then return end
    local tokens = {}
    local seen = {}
    for _, token in ipairs(macro.campaignIntentTokens or {}) do
        if type(token) ~= 'string' or seen[token] then return end
        seen[token] = true
        TableInsert(tokens, token)
    end
    table.sort(tokens)
    if TableGetn(tokens) == 0 then return end
    local position = mode == 'recall'
        and snapshot.basePosition
        or macro.campaignIntentPosition
    if not IsUsablePosition(position) then return end
    local intent = {
        kind = 'field_campaign',
        mode = mode,
        actorTokens = tokens,
        position = position,
        campaignKind = macro.campaignIntentKind,
        campaignSerial = macro.campaignSerial,
        clusterKey = macro.campaignIntentCluster,
        objectiveKey = macro.campaignIntentObjective,
        priority = (mode == 'recall'
            or mode == 'rollback'
            or mode == 'route_release') and 1 or 24,
        reason = mode == 'rollback'
            and tostring(macro.campaignIntentRollbackReason or 'rollback')
            or (mode == 'assault'
                and 'strategic_assault_campaign'
                or 'pressure_front_campaign'),
    }
    if mode == 'route_probe'
        or mode == 'route_commit'
        or mode == 'route_release'
    then
        if type(macro.campaignRouteEpoch) ~= 'number'
            or type(macro.campaignRouteKey) ~= 'string'
            or type(macro.campaignRouteFingerprint) ~= 'string'
            or type(macro.campaignRouteSourceKey) ~= 'string'
        then
            return
        end
        intent.routeEpoch = macro.campaignRouteEpoch
        intent.routeKey = macro.campaignRouteKey
        intent.routeFingerprint = macro.campaignRouteFingerprint
        intent.routeSourceKey = macro.campaignRouteSourceKey
    end
    AddIntent(intents, intent)
end

local function RegroupDecision(snapshot, units, intents)
    local macro = type(snapshot.macro) == 'table' and snapshot.macro or nil
    local position = macro and macro.rallyPosition
        or snapshot.rallyPosition
        or snapshot.basePosition
    if not IsUsablePosition(position) then return end
    local regroup = {}
    for _, unit in ipairs(units) do
        if COMBAT_ROLES[unit.role]
            and unit.complete == true
            and unit.assignedToWave ~= true
            and unit.fieldCohort ~= true
            and ((unit.homeCohort == true and unit.nearHome == false)
                or (unit.homeCohort ~= true
                    and (unit.nearRally == false
                        or (unit.nearRally == nil and unit.nearStaging == false))))
        then
            TableInsert(regroup, unit)
        end
    end
    if TableGetn(regroup) > 0 then
        AddIntent(intents, {
            kind = 'regroup_wave',
            actorTokens = ActorTokens(regroup),
            position = position,
            priority = 35,
            reason = 'return_to_controlled_anchor',
        })
    end
end

local function IntentActorKey(intent)
    if intent.actorToken then
        return tostring(intent.actorToken)
    end
    local tokens = intent.actorTokens or {}
    return tostring(tokens[1] or '')
end

local function SortIntents(intents)
    table.sort(intents, function(a, b)
        local aPriority = tonumber(a.priority) or 1000
        local bPriority = tonumber(b.priority) or 1000
        if aPriority == bPriority then
            local aActor = IntentActorKey(a)
            local bActor = IntentActorKey(b)
            if aActor == bActor then
                return tostring(a.kind or '') < tostring(b.kind or '')
            end
            return aActor < bActor
        end
        return aPriority < bPriority
    end)
    return intents
end

Policy = {}

Policy.requestEconomy = {
    mass_extractor = { massDrain = 0.3, energyDrain = 3, massCost = 36, energyCost = 360, duration = 120 },
    power_generator = { massDrain = 0.3, energyDrain = 3, massCost = 75, energyCost = 750, duration = 250 },
    hydrocarbon = { massDrain = 0.2, energyDrain = 1, massCost = 160, energyCost = 800, duration = 800 },
    land_factory = { massDrain = 0.4, energyDrain = 3.5, massCost = 240, energyCost = 2100, duration = 600 },
    air_factory = { massDrain = 0.35, energyDrain = 4, massCost = 210, energyCost = 2400, duration = 600 },
    land_factory_t2 = { massDrain = 1.017391, energyDrain = 7.913043, massCost = 1170, energyCost = 9100, duration = 1150 },
    scout = { massDrain = 0.4, energyDrain = 2.666667, massCost = 12, energyCost = 80, duration = 30 },
    artillery = { massDrain = 0.36, energyDrain = 1.8, massCost = 36, energyCost = 180, duration = 100 },
    anti_air = { massDrain = 0.5, energyDrain = 2.5, massCost = 55, energyCost = 275, duration = 110 },
    engineer = { massDrain = 0.4, energyDrain = 2, massCost = 52, energyCost = 260, duration = 130 },
    lab = { massDrain = 0.5, energyDrain = 2, massCost = 30, energyCost = 120, duration = 60 },
    tank = { massDrain = 0.373333, energyDrain = 1.773333, massCost = 56, energyCost = 266, duration = 150 },
    interceptor = { massDrain = 0.2, energyDrain = 9, massCost = 50, energyCost = 2250, duration = 250 },
    air_scout = { massDrain = 0.4, energyDrain = 5.8, massCost = 40, energyCost = 580, duration = 100 },
    t2_direct_fire = { massDrain = 0.9, energyDrain = 4.5, massCost = 198, energyCost = 990, duration = 220 },
    t2_anti_air = { massDrain = 0.8, energyDrain = 4, massCost = 160, energyCost = 800, duration = 200 },
}
Policy.expansionPlanningTicks = 12000

Policy.ApplyAllocator = function(snapshot, intents)
    local macro = type(snapshot.macro) == 'table' and snapshot.macro or nil
    if not macro or macro.allocatorEnabled ~= true then return intents end
    local accepted = {}
    local availableMass = math.max(0,
        tonumber(macro.availableRecurringMass) or 0)
    local availableEnergy = math.max(0,
        tonumber(macro.availableRecurringEnergy) or 0)
    local bankMass = math.max(0, tonumber(macro.oneTimeMassReserve) or 0)
    local bankEnergy = math.max(0, tonumber(macro.oneTimeEnergyReserve) or 0)
    -- Blueprint cost/duration values are exact while legacy telemetry drains
    -- are serialized to six decimals.  One ten-thousandth per tick covers
    -- only that representation error; larger deficits remain unfunded.
    local fitTolerance = 0.0001
    local expansionMassCredit = math.max(0,
        (tonumber(macro.expansionRecurringMassBudget) or availableMass)
            - availableMass)
    local expansionEnergyCredit = math.max(0,
        (tonumber(macro.expansionRecurringEnergyBudget) or availableEnergy)
            - availableEnergy)
    local factorySlots = math.max(0,
        math.floor(tonumber(macro.factoryFundedCount) or 0))
    local factoryAccepted = 0
    local protectedCombatAccepted = false
    local overflowCombatAccepted = 0
    local sustainedCombatAccepted = 0
    local actors = {}
    local completedLandFactories = 0
    local completedEngineers = 0
    for _, unit in ipairs(snapshot.units or {}) do
        if type(unit.token) == 'string' then actors[unit.token] = unit end
        if unit.complete == true and unit.role == 'land_factory' then
            completedLandFactories = completedLandFactories + 1
        elseif unit.complete == true and unit.role == 'engineer' then
            completedEngineers = completedEngineers + 1
        end
    end
    local reserveLandCombat = completedLandFactories >= 1
        and (completedEngineers >= MIN_RECOVERY_ENGINEERS
            or (completedLandFactories >= 2 and completedEngineers >= 1))
    local overflowFactorySlots = 0
    local rollingMassStoredRatio = tonumber(macro.rollingMassStoredRatio)
    local rollingEnergyStoredRatio = tonumber(macro.rollingEnergyStoredRatio)
    if macro.economyLedgerValid == true
        and FiniteNumber(rollingMassStoredRatio)
        and FiniteNumber(rollingEnergyStoredRatio)
        and rollingMassStoredRatio >= 0.95
        and rollingEnergyStoredRatio >= 0.5
    then
        overflowFactorySlots = math.min(4, completedLandFactories)
    end
    local landCombatRoles = {
        anti_air = true,
        artillery = true,
        lab = true,
        tank = true,
    }
    local activeCombatLanes = 0
    for _, operation in ipairs(snapshot.pending or {}) do
        if operation.kind == 'factory_build'
            and landCombatRoles[operation.buildRole] == true
        then
            protectedCombatAccepted = true
            activeCombatLanes = activeCombatLanes + 1
        end
    end
    local sustainableCombatSlots = 0
    local recurringMassIncome = tonumber(macro.recurringMassIncome)
    local recurringEnergyIncome = tonumber(macro.recurringEnergyIncome)
    local tankBudget = Policy.requestEconomy.tank
    if macro.economyLedgerValid == true
        and FiniteNumber(recurringMassIncome)
        and FiniteNumber(recurringEnergyIncome)
        and recurringMassIncome >= 0
        and recurringEnergyIncome >= 0
    then
        sustainableCombatSlots = math.min(
            4,
            completedLandFactories,
            math.floor((recurringMassIncome + fitTolerance)
                / tankBudget.massDrain),
            math.floor((recurringEnergyIncome + fitTolerance)
                / tankBudget.energyDrain)
        )
    end
    local ordered = CopyArray(intents)
    local leadingExpansion = nil
    local hasLandCombatRequest = false
    local protectedCombatIntent = nil
    for _, intent in ipairs(ordered) do
        if intent.kind == 'factory_build'
            and landCombatRoles[intent.buildRole] == true
        then
            hasLandCombatRequest = true
            if reserveLandCombat
                and (not protectedCombatIntent
                    or IntentActorKey(intent)
                        < IntentActorKey(protectedCombatIntent))
            then
                protectedCombatIntent = intent
            end
        end
        if (intent.kind == 'build_structure'
                or intent.kind == 'assist_structure')
            and intent.buildRole == 'mass_extractor'
            and (intent.reason == 'frontier_expansion'
                or intent.reason == 'mass_expansion')
        then
            if not leadingExpansion
                or (tonumber(intent.estimatedRoiTicks) or 1000000000)
                    < (tonumber(leadingExpansion.estimatedRoiTicks)
                        or 1000000000)
                or ((tonumber(intent.estimatedRoiTicks) or 1000000000)
                        == (tonumber(leadingExpansion.estimatedRoiTicks)
                            or 1000000000)
                    and tostring(intent.siteKey or '')
                        < tostring(leadingExpansion.siteKey or ''))
                or ((tonumber(intent.estimatedRoiTicks) or 1000000000)
                        == (tonumber(leadingExpansion.estimatedRoiTicks)
                            or 1000000000)
                    and tostring(intent.siteKey or '')
                        == tostring(leadingExpansion.siteKey or '')
                    and IntentActorKey(intent)
                        < IntentActorKey(leadingExpansion))
            then
                leadingExpansion = intent
            end
        end
    end
    table.sort(ordered, function(a, b)
        local ap = tonumber(a.priority) or 1000
        local bp = tonumber(b.priority) or 1000
        if a.kind == 'factory_build'
            and a.reason == 'unlock_profitable_expansion'
        then ap = reserveLandCombat and 32 or 17 end
        if a.kind == 'factory_build'
            and a.reason == 'recovery_engineer_floor'
        then ap = 16 end
        if reserveLandCombat
            and a.kind == 'factory_build'
            and landCombatRoles[a.buildRole] == true
        then ap = 31 end
        if a.kind == 'factory_upgrade' then ap = 20.5 end
        if a.kind == 'factory_build'
            and a.reason == 'initial_frontier_air_scout'
        then ap = 20.75 end
        if reserveLandCombat and hasLandCombatRequest and leadingExpansion
            and a ~= leadingExpansion
            and (a.kind == 'build_structure'
                or a.kind == 'assist_structure')
            and a.buildRole == 'mass_extractor'
            and (a.reason == 'frontier_expansion'
                or a.reason == 'mass_expansion')
        then ap = 33 end
        if a.kind == 'factory_build'
            and a.reason == 'persistent_air_screen'
        then ap = 21 end
        if b.kind == 'factory_build'
            and b.reason == 'unlock_profitable_expansion'
        then bp = reserveLandCombat and 32 or 17 end
        if b.kind == 'factory_build'
            and b.reason == 'recovery_engineer_floor'
        then bp = 16 end
        if reserveLandCombat
            and b.kind == 'factory_build'
            and landCombatRoles[b.buildRole] == true
        then bp = 31 end
        if b.kind == 'factory_upgrade' then bp = 20.5 end
        if b.kind == 'factory_build'
            and b.reason == 'initial_frontier_air_scout'
        then bp = 20.75 end
        if reserveLandCombat and hasLandCombatRequest and leadingExpansion
            and b ~= leadingExpansion
            and (b.kind == 'build_structure'
                or b.kind == 'assist_structure')
            and b.buildRole == 'mass_extractor'
            and (b.reason == 'frontier_expansion'
                or b.reason == 'mass_expansion')
        then bp = 33 end
        if b.kind == 'factory_build'
            and b.reason == 'persistent_air_screen'
        then bp = 21 end
        if ap == bp then
            local aRoi = tonumber(a.estimatedRoiTicks) or 1000000000
            local bRoi = tonumber(b.estimatedRoiTicks) or 1000000000
            if aRoi ~= bRoi then return aRoi < bRoi end
            return IntentActorKey(a) < IntentActorKey(b)
        end
        return ap < bp
    end)
    for _, intent in ipairs(ordered) do
        local economic = intent.kind == 'build_structure'
            or intent.kind == 'assist_structure'
            or intent.kind == 'factory_build'
            or intent.kind == 'factory_upgrade'
        if not economic or intent.kind == 'reclaim' then
            TableInsert(accepted, intent)
        elseif macro.economyLedgerValid ~= true
            and macro.economyInputValid ~= true
        then
            -- Fail closed on malformed or first-sample economy. Safety,
            -- campaign movement, rally, and reclaim remain independent.
        else
            local role = intent.upgradeRole or intent.buildRole
            local request = Policy.requestEconomy[role]
            local allowed = request ~= nil
            local requestMassDrain = request and request.massDrain or 0
            local requestEnergyDrain = request and request.energyDrain or 0
            local requestDuration = request and request.duration or 0
            local structureRequest = intent.kind == 'build_structure'
                or intent.kind == 'assist_structure'
            local strategicHydro = structureRequest and role == 'hydrocarbon'
            local strategicPower = structureRequest
                and role == 'power_generator'
                and (intent.reason == 'factory_adjacency_power'
                    or intent.reason == 'opening_air_power')
            local protectedCombat = intent == protectedCombatIntent
            local protectedAirScreen = intent.kind == 'factory_build'
                and intent.reason == 'persistent_air_screen'
            local protectedAirScout = intent.kind == 'factory_build'
                and intent.reason == 'initial_frontier_air_scout'
            local concurrentUnlock = reserveLandCombat
                and completedLandFactories >= 2
                and completedEngineers
                    < math.max(MIN_RECOVERY_ENGINEERS,
                        math.floor(tonumber(macro.engineerTarget) or 0))
                and intent.kind == 'factory_build'
                and intent.reason == 'unlock_profitable_expansion'
            local overflowCombat = intent.kind == 'factory_build'
                and intent.reason == 'continuous_land_production'
                and landCombatRoles[intent.buildRole] == true
                and overflowCombatAccepted < overflowFactorySlots
            local sustainedCombat = intent.kind == 'factory_build'
                and intent.reason == 'continuous_land_production'
                and landCombatRoles[intent.buildRole] == true
                and activeCombatLanes + sustainedCombatAccepted
                    < sustainableCombatSlots
            local protectedFactoryLane = protectedCombat
                or protectedAirScreen
                or protectedAirScout
                or overflowCombat
                or sustainedCombat
                or (concurrentUnlock and protectedCombatAccepted)
            local protectedUsesBank = false
            if allowed and structureRequest then
                local actor = actors[intent.actorToken]
                local buildRate = actor and tonumber(actor.buildRate) or nil
                if not actor
                    or (actor.role ~= 'acu' and actor.role ~= 'engineer')
                    or not FiniteNumber(buildRate)
                    or buildRate <= 0
                then
                    allowed = false
                else
                    local scale = buildRate / 5
                    requestMassDrain = requestMassDrain * scale
                    requestEnergyDrain = requestEnergyDrain * scale
                    requestDuration = requestDuration / scale
                end
            end
            if role == 'mass_extractor'
                and tonumber(intent.estimatedRoiTicks)
                and tonumber(intent.estimatedRoiTicks)
                    > Policy.expansionPlanningTicks
            then
                allowed = false
            end
            if intent.kind == 'factory_upgrade'
                and macro.techAdmission ~= 'admitted'
            then
                allowed = false
            end
            if concurrentUnlock and not protectedCombatAccepted then
                allowed = false
            end
            if intent.kind == 'factory_build'
                and intent.reason ~= 'recovery_engineer_floor'
                and not protectedFactoryLane
                and factoryAccepted >= factorySlots
            then
                allowed = false
            end
            if allowed then
                local expansionRequest = structureRequest
                    and role == 'mass_extractor'
                local laneMass = availableMass
                    + (expansionRequest and expansionMassCredit or 0)
                local laneEnergy = availableEnergy
                    + (expansionRequest and expansionEnergyCredit or 0)
                local massGap = math.max(0,
                    request.massCost - laneMass * requestDuration)
                local energyGap = math.max(0,
                    request.energyCost - laneEnergy * requestDuration)
                local massFit = bankMass + fitTolerance >= massGap
                local energyFit = bankEnergy + fitTolerance >= energyGap
                if protectedFactoryLane then
                    if overflowCombat or sustainedCombat then
                        allowed = true
                    else
                        local recurringFit = availableMass + fitTolerance
                                >= requestMassDrain
                            and availableEnergy + fitTolerance
                                >= requestEnergyDrain
                        local bankFit = bankMass + fitTolerance >= request.massCost
                            and bankEnergy + fitTolerance >= request.energyCost
                        allowed = recurringFit or bankFit
                        protectedUsesBank = not recurringFit and bankFit
                    end
                elseif intent.kind == 'factory_build'
                    and intent.reason ~= 'recovery_engineer_floor'
                then
                    massFit = availableMass + fitTolerance >= requestMassDrain
                        and massFit
                    energyFit = availableEnergy + fitTolerance >= requestEnergyDrain
                        and energyFit
                elseif intent.kind == 'factory_upgrade' then
                    massFit = availableMass + fitTolerance >= requestMassDrain
                        and massFit
                    energyFit = availableEnergy + fitTolerance >= requestEnergyDrain
                        and energyFit
                end
                allowed = strategicHydro or strategicPower
                    or overflowCombat or sustainedCombat
                    or (massFit and energyFit)
            end
            if allowed then
                local expansionRequest = structureRequest
                    and role == 'mass_extractor'
                local laneMass = availableMass
                    + (expansionRequest and expansionMassCredit or 0)
                local laneEnergy = availableEnergy
                    + (expansionRequest and expansionEnergyCredit or 0)
                local massGap = math.max(0,
                    request.massCost - laneMass * requestDuration)
                local energyGap = math.max(0,
                    request.energyCost - laneEnergy * requestDuration)
                local massCreditUsed = expansionRequest
                    and math.min(expansionMassCredit, requestMassDrain)
                    or 0
                local energyCreditUsed = expansionRequest
                    and math.min(expansionEnergyCredit, requestEnergyDrain)
                    or 0
                expansionMassCredit = expansionMassCredit - massCreditUsed
                expansionEnergyCredit = expansionEnergyCredit - energyCreditUsed
                availableMass = math.max(0,
                    availableMass - (requestMassDrain - massCreditUsed))
                availableEnergy = math.max(0,
                    availableEnergy - (requestEnergyDrain - energyCreditUsed))
                if protectedUsesBank then
                    bankMass = math.max(0, bankMass - request.massCost)
                    bankEnergy = math.max(0, bankEnergy - request.energyCost)
                else
                    bankMass = math.max(0, bankMass - massGap)
                    bankEnergy = math.max(0, bankEnergy - energyGap)
                end
                if intent.kind == 'factory_build' then
                    factoryAccepted = factoryAccepted + 1
                end
                if overflowCombat then
                    overflowCombatAccepted = overflowCombatAccepted + 1
                end
                if sustainedCombat then
                    sustainedCombatAccepted = sustainedCombatAccepted + 1
                end
                if protectedCombat then protectedCombatAccepted = true end
                TableInsert(accepted, intent)
            end
        end
    end
    return accepted
end

Policy.Decide = function(snapshot)
    snapshot = snapshot or {}
    local units = SortRecords(snapshot.units or {})
    local state = DoctrineState(snapshot)
    local pending = snapshot.pending or {}
    local pendingActors = PendingActors(pending)
    local safety, emergency = SafetyDecision(
        snapshot,
        units,
        state,
        nil
    )

    local counts = CountRoles(units, pending, snapshot.foundations or {})
    local virtualReserved = {}
    local virtualPlacements = { keys = {}, rects = {}, siteKeys = {} }
    for _, operation in ipairs(pending) do
        if operation.siteKey then
            virtualReserved[operation.siteKey] = true
        end
        if type(operation.placementKey) == 'string' then
            virtualPlacements.keys[operation.placementKey] = true
        end
        local rect = PlacementRect(operation.buildRole, operation.position)
        if rect then TableInsert(virtualPlacements.rects, rect) end
    end
    for _, foundation in ipairs(snapshot.foundations or {}) do
        local key = PlacementKey(foundation.position)
        local rect = PlacementRect(foundation.role, foundation.position)
        if key then virtualPlacements.keys[key] = true end
        if rect then TableInsert(virtualPlacements.rects, rect) end
    end

    local intents = {}
    for _, intent in ipairs(safety or {}) do
        AddIntent(intents, intent)
    end
    local underContact = snapshot.enemyContact ~= nil
        and snapshot.enemyContact.immediate == true
    local commanderRecovery = state and state.commanderRetreating == true
    local commanderClaimsAcu = false
    local opening = nil
    if not emergency and not underContact and not commanderRecovery and not commanderClaimsAcu then
        opening = AcuOpening(snapshot, units, counts, virtualReserved, virtualPlacements, pendingActors)
    end
    if opening then
        AddIntent(intents, opening)
    end
    local localMass = CountClaimedLocalSites(((snapshot.sites or {}).mass) or {}, virtualReserved)
    local openingComplete = (counts.land_factory or 0) >= 2
        and (counts.power_generator or 0) >= 2
        and localMass >= 4
    if not emergency or commanderRecovery then
        EngineerDecisions(
            snapshot,
            units,
            counts,
            virtualReserved,
            virtualPlacements,
            pendingActors,
            underContact,
            openingComplete,
            intents
        )
    end
    FieldCampaignDecision(snapshot, intents)
    if not underContact
        and not emergency
        and not commanderRecovery
        and not (type(snapshot.macro) == 'table'
            and snapshot.macro.campaignEnabled == true
            and not (snapshot.macro.campaignKind == 'none'
                and snapshot.macro.campaignState == 'idle'))
    then
        FrontierScreenDecision(snapshot, units, pendingActors, intents)
        local screened = {}
        for _, intent in ipairs(intents) do
            if intent.kind == 'frontier_screen' then
                for _, token in ipairs(intent.actorTokens or {}) do screened[token] = true end
            end
        end
        if next(screened) then
            for _, intent in ipairs(intents) do
                if intent.kind == 'defend_wave' then
                    local retained = {}
                    for _, token in ipairs(intent.actorTokens or {}) do
                        if not screened[token] then TableInsert(retained, token) end
                    end
                    intent.actorTokens = retained
                end
            end
        end
    end
    FactoryDecisions(snapshot, units, counts, pendingActors, intents)
    if not underContact and not emergency and not commanderRecovery then
        RegroupDecision(snapshot, units, intents)
    end
    return SortIntents(Policy.ApplyAllocator(snapshot, intents))
end
