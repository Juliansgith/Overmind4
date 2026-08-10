local COMBAT_ROLES = {
    anti_air = true,
    artillery = true,
    lab = true,
    tank = true,
}

local ATTACK_COMBAT = 24
local ATTACK_ARTILLERY = 4
local ACU_RETREAT_HEALTH_RATIO = 0.55
local COMMANDER_PUSH_HEALTH_RATIO = 0.75
local LOW_ENERGY_STORED_RATIO = 0.35
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

local function CountRoles(units, pending)
    local counts = {}
    for _, unit in ipairs(units) do
        if unit.role and unit.complete == true then
            counts[unit.role] = (counts[unit.role] or 0) + 1
        end
    end
    for _, operation in ipairs(pending or {}) do
        if operation.buildRole then
            counts[operation.buildRole] = (counts[operation.buildRole] or 0) + 1
        end
    end
    return counts
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

local function ReservePlacement(snapshot, role, index, virtualPlacements)
    local placements = snapshot.placements or {}
    local candidates = placements[role] or {}
    local count = TableGetn(candidates)
    local first = tonumber(index) or 1
    if first < 1 or first > count then first = 1 end
    for candidateIndex = first, count do
        local position = candidates[candidateIndex]
        local key = PlacementKey(position)
        if key and not virtualPlacements[key] then
            virtualPlacements[key] = true
            return position
        end
    end
    for candidateIndex = 1, first - 1 do
        local position = candidates[candidateIndex]
        local key = PlacementKey(position)
        if key and not virtualPlacements[key] then
            virtualPlacements[key] = true
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

local function FirstFrontierSite(sites, virtualReserved, selectedKey)
    if type(selectedKey) == 'string' then
        for _, site in ipairs(sites or {}) do
            if site.key == selectedKey
                and site.frontierSelected == true
                and site.lost ~= true
                and SiteIsAvailable(site, virtualReserved, false)
            then
                return site
            end
        end
    end
    for _, site in ipairs(SortSites(sites)) do
        if site.frontierSelected == true
            and site.lost ~= true
            and SiteIsAvailable(site, virtualReserved, false)
        then
            return site
        end
    end
    return nil
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
    if CanBuild(acu, 'mass_extractor') then
        local lost = FirstLostSite(massSites, virtualReserved, true)
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
        local site = FirstAvailableSite(massSites, virtualReserved, true)
        if site then
            virtualReserved[site.key] = true
            return BuildAtSite(acu, 'mass_extractor', site, 12, 'opening_mass')
        end
        return nil
    end

    if (counts.land_factory or 0) < 2 and CanBuild(acu, 'land_factory') then
        return BuildAtPlacement(acu, 'land_factory', ReservePlacement(snapshot, 'land_factory', 2, virtualPlacements), 13, 'opening_second_factory')
    end
    return nil
end

local function EngineerDecisions(snapshot, units, counts, virtualReserved, virtualPlacements, pendingActors, underContact, allowPlacement, intents)
    local engineers = {}
    for _, unit in ipairs(units) do
        if unit.role == 'engineer'
            and unit.complete == true
            and unit.idle == true
            and not pendingActors[unit.token]
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
    local plannedReclaim = false
    local constructionPlanned = false
    local reclaimCandidates = CopyArray(snapshot.reclaim or {})
    table.sort(reclaimCandidates, function(a, b)
        local av = tonumber(a.mass) or -1
        local bv = tonumber(b.mass) or -1
        if av == bv then return tostring(a.key or '') < tostring(b.key or '') end
        return av > bv
    end)
    local virtualReclaim = {}
    for _, operation in ipairs(snapshot.pending or {}) do
        if operation.targetKey then virtualReclaim[operation.targetKey] = true end
    end
    local placementIndex = {
        power_generator = (counts.power_generator or 0) + 1,
        land_factory = (counts.land_factory or 0) + 1,
    }

    for _, engineer in ipairs(engineers) do
        local intent = nil
        if not underContact and CanBuild(engineer, 'mass_extractor') then
            local site = FirstLostSite(massSites, virtualReserved, false)
            if site then
                virtualReserved[site.key] = true
                counts.mass_extractor = (counts.mass_extractor or 0) + 1
                intent = BuildAtSite(engineer, 'mass_extractor', site, 18, 'rebuild_mex')
            end
        end

        if not intent
            and not lostOutstanding
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
            and not lostOutstanding
            and not underContact
            and (counts.hydrocarbon or 0) < 1
            and CanBuild(engineer, 'hydrocarbon')
        then
            local site = FirstAvailableSite(hydroSites, virtualReserved, false)
            if site then
                virtualReserved[site.key] = true
                counts.hydrocarbon = (counts.hydrocarbon or 0) + 1
                intent = BuildAtSite(engineer, 'hydrocarbon', site, 20, 'first_hydro')
            end
        end

        if not intent
            and not lostOutstanding
            and not underContact
            and not plannedFactory
            and allowPlacement
            and CanBuild(engineer, 'land_factory')
        then
            local currentFactories = counts.land_factory or 0
            local factoryDemand = macro and (tonumber(macro.factoryDemand) or currentFactories) or 3
            local sustained = not macro
                or (tonumber(macro.massSurplusTicks) or 0) >= 300
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
                    counts.land_factory = currentFactories + 1
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
            and not lostOutstanding
            and not underContact
            and CanBuild(engineer, 'mass_extractor')
        then
            local site = macro
                and FirstFrontierSite(
                    massSites,
                    virtualReserved,
                    macro.selectedFrontierSite
                )
                or FirstAvailableSite(massSites, virtualReserved, false)
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
            end
        end

        if not intent
            and macro
            and not lostOutstanding
            and not underContact
            and not plannedReclaim
            and not constructionPlanned
            and (tonumber(macro.constructionBacklog) or 0) <= 0
        then
            for _, candidate in ipairs(reclaimCandidates) do
                if type(candidate.key) == 'string'
                    and IsUsablePosition(candidate.position)
                    and candidate.reserved ~= true
                    and not virtualReclaim[candidate.key]
                    and (tonumber(candidate.mass) or 0) > 0
                then
                    plannedReclaim = true
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
    local rallyPosition = macro and macro.rallyPosition
        or snapshot.rallyPosition
        or snapshot.basePosition
    for _, factory in ipairs(units) do
        if factory.role == 'land_factory'
            and factory.complete == true
            and factory.idle == true
            and not pendingActors[factory.token]
        then
            if factory.needsRally == true then
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
                if not plannedEngineer
                    and not massStalled
                    and (counts.engineer or 0) < engineerDemand
                    and CanBuild(factory, 'engineer')
                then
                    role = 'engineer'
                    reason = macro and 'construction_capacity' or reason
                    plannedEngineer = true
                elseif (counts.scout or 0) < 1 and CanBuild(factory, 'scout') then
                    role = 'scout'
                else
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
    local screenHasAntiAir = false
    for _, unit in ipairs(units or {}) do
        if unit.token == engineerToken
            and unit.role == 'engineer'
            and unit.complete == true
        then
            engineer = unit
        elseif COMBAT_ROLES[unit.role]
            and unit.complete == true
            and unit.assignedToWave ~= true
            and not pendingActors[unit.token]
        then
            TableInsert(available, unit)
            if unit.role == 'anti_air' then TableInsert(antiAir, unit) end
        elseif unit.frontierEscort == true and unit.role == 'anti_air' then
            screenHasAntiAir = true
        end
    end
    local screenTarget = math.min(4, currentScreen + TableGetn(available) - 4)
    local screenSize = screenTarget - currentScreen
    if screenSize <= 0
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
    AddIntent(intents, {
        kind = 'frontier_screen',
        engineerToken = engineerToken,
        actorTokens = ActorTokens(selected),
        clusterKey = clusterKey or tostring(macro.selectedFrontierCluster or 'none'),
        priority = 24,
        reason = 'secure_frontier',
    })
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
            and (unit.nearRally == false
                or (unit.nearRally == nil and unit.nearStaging == false))
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

    local counts = CountRoles(units, pending)
    local virtualReserved = {}
    local virtualPlacements = {}
    for _, operation in ipairs(pending) do
        if operation.siteKey then
            virtualReserved[operation.siteKey] = true
        end
        if type(operation.placementKey) == 'string' then
            virtualPlacements[operation.placementKey] = true
        end
    end

    local intents = {}
    for _, intent in ipairs(safety or {}) do
        AddIntent(intents, intent)
    end
    local underContact = snapshot.enemyContact ~= nil
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
    if not underContact and not emergency and not commanderRecovery then
        FrontierScreenDecision(snapshot, units, pendingActors, intents)
    end
    FactoryDecisions(snapshot, units, counts, pendingActors, intents)
    if not underContact and not emergency and not commanderRecovery then
        RegroupDecision(snapshot, units, intents)
    end
    return SortIntents(intents)
end
