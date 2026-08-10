local COMBAT_ROLES = {
    anti_air = true,
    artillery = true,
    lab = true,
    tank = true,
}

local ATTACK_COMBAT = 24
local ATTACK_ARTILLERY = 4
local ACU_RETREAT_HEALTH_RATIO = 0.55
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
        if unit.role then
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
        or SiteIsClaimed(site, virtualReserved)
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
        kind = 'build_structure',
        actorToken = actor.token,
        buildRole = role,
        siteKey = site.key,
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

local function DefensiveCombatUnits(units)
    local combat = {}
    for _, unit in ipairs(units) do
        if COMBAT_ROLES[unit.role]
            and unit.complete == true
            and unit.assignedToWave ~= true
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

local function SafetyDecision(snapshot, units)
    local acu = nil
    for _, unit in ipairs(units) do
        if unit.role == 'acu' and unit.complete == true then
            acu = unit
            break
        end
    end

    local contact = snapshot.enemyContact
    local emergency = acu and (
        (tonumber(acu.healthRatio) or 1) < ACU_RETREAT_HEALTH_RATIO
        or (contact and contact.immediate == true)
    )
    local combat = DefensiveCombatUnits(units)

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

    local massSites = ((snapshot.sites or {}).mass) or {}
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
    local lowEnergy = (tonumber(economy.energyTrend) or 0) < 0
        and (tonumber(economy.energyStoredRatio) or 0) < LOW_ENERGY_STORED_RATIO
    local plannedPower = false
    local plannedFactory = false
    local placementIndex = {
        power_generator = (counts.power_generator or 0) + 1,
        land_factory = (counts.land_factory or 0) + 1,
    }

    for _, engineer in ipairs(engineers) do
        local intent = nil
        if not underContact
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
            and allowPlacement
            and lowEnergy
            and not plannedPower
            and CanBuild(engineer, 'power_generator')
        then
            local position = ReservePlacement(snapshot, 'power_generator', placementIndex.power_generator, virtualPlacements)
            if position then
                plannedPower = true
                placementIndex.power_generator = placementIndex.power_generator + 1
                counts.power_generator = (counts.power_generator or 0) + 1
                intent = BuildAtPlacement(engineer, 'power_generator', position, 21, 'energy_recovery')
            end
        end

        if not intent
            and not plannedFactory
            and allowPlacement
            and (counts.land_factory or 0) >= 2
            and (counts.land_factory or 0) < 3
            and (counts.mass_extractor or 0) >= 6
            and CanBuild(engineer, 'land_factory')
        then
            local position = ReservePlacement(snapshot, 'land_factory', placementIndex.land_factory, virtualPlacements)
            if position then
                plannedFactory = true
                placementIndex.land_factory = placementIndex.land_factory + 1
                counts.land_factory = (counts.land_factory or 0) + 1
                intent = BuildAtPlacement(engineer, 'land_factory', position, 22, 'third_factory')
            end
        end

        if not intent and not underContact and CanBuild(engineer, 'mass_extractor') then
            local site = FirstAvailableSite(massSites, virtualReserved, false)
            if site then
                virtualReserved[site.key] = true
                counts.mass_extractor = (counts.mass_extractor or 0) + 1
                intent = BuildAtSite(engineer, 'mass_extractor', site, 23, 'mass_expansion')
            end
        end

        if intent then
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
                    position = snapshot.stagingPosition,
                    priority = 30,
                    reason = 'common_staging',
                })
            else
                local role = nil
                if (counts.engineer or 0) < 3 and CanBuild(factory, 'engineer') then
                    role = 'engineer'
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
                        reason = 'continuous_land_production',
                    })
                    counts[role] = (counts[role] or 0) + 1
                end
            end
        end
    end
end

local function AttackDecision(snapshot, units, intents)
    if snapshot.targetPath ~= true or not IsUsablePosition(snapshot.targetPosition) then
        return
    end

    local combat, artillery = CombatUnits(units)
    if TableGetn(combat) >= ATTACK_COMBAT and artillery >= ATTACK_ARTILLERY then
        AddIntent(intents, {
            kind = 'attack_wave',
            actorTokens = ActorTokens(combat),
            position = snapshot.targetPosition,
            priority = 40,
            reason = 'concentration_gate',
        })
    end
end

local function RegroupDecision(snapshot, units, intents)
    if not IsUsablePosition(snapshot.stagingPosition) then return end
    local regroup = {}
    for _, unit in ipairs(units) do
        if COMBAT_ROLES[unit.role]
            and unit.complete == true
            and unit.assignedToWave ~= true
            and unit.nearStaging == false
        then
            TableInsert(regroup, unit)
        end
    end
    if TableGetn(regroup) > 0 then
        AddIntent(intents, {
            kind = 'regroup_wave',
            actorTokens = ActorTokens(regroup),
            position = snapshot.stagingPosition,
            priority = 35,
            reason = 'return_to_staging',
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
    local safety, emergency = SafetyDecision(snapshot, units)

    local pending = snapshot.pending or {}
    local counts = CountRoles(units, pending)
    local pendingActors = PendingActors(pending)
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
    local opening = nil
    if not emergency then
        opening = AcuOpening(snapshot, units, counts, virtualReserved, virtualPlacements, pendingActors)
    end
    if opening then
        AddIntent(intents, opening)
    end
    local underContact = snapshot.enemyContact ~= nil
    local localMass = CountClaimedLocalSites(((snapshot.sites or {}).mass) or {}, virtualReserved)
    local openingComplete = (counts.land_factory or 0) >= 2
        and (counts.power_generator or 0) >= 2
        and localMass >= 4
    EngineerDecisions(
        snapshot,
        units,
        counts,
        virtualReserved,
        virtualPlacements,
        pendingActors,
        underContact or emergency,
        openingComplete or emergency,
        intents
    )
    FactoryDecisions(snapshot, units, counts, pendingActors, intents)
    if not underContact and not emergency then
        RegroupDecision(snapshot, units, intents)
        AttackDecision(snapshot, units, intents)
    end
    return SortIntents(intents)
end
