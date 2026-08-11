-- Observer-only benchmark telemetry for the Overmind4 development harness.
-- It never publishes state to either AI brain and never issues simulation orders.

local CHECKPOINT_TICKS = 300
local METRIC_NAMES = {
    'air_bomber', 'air_factory_t1', 'air_factory_t2', 'air_factory_t3',
    'air_interceptor', 'air_other', 'air_scout', 'air_transport',
    'army_count_field', 'army_count_garrison', 'army_count_home',
    'army_count_raider', 'army_count_response', 'army_count_unassigned',
    'army_mass_field', 'army_mass_garrison', 'army_mass_home',
    'army_mass_raider', 'army_mass_response', 'army_mass_unassigned',
    'energy_excess', 'energy_income', 'energy_reclaim', 'energy_spent',
    'energy_stored', 'engineers_alive', 'engineers_built', 'engineers_lost',
    'factory_full_bank_idle_ticks', 'factory_idle', 'factory_utilization',
    'land_factory_t1', 'land_factory_t2', 'land_factory_t3', 'mass_excess',
    'mass_income', 'mass_killed', 'mass_lost', 'mass_reclaim', 'mass_spent',
    'mass_stored', 'mex_built', 'mex_lost', 'mex_rebuilt', 'mex_survival',
    'mex_t1', 'mex_t2', 'mex_t3', 'mobile_t2', 'mobile_t3',
}
local FORCE_BUCKETS = { 'home', 'garrison', 'field', 'response', 'raider' }

local function ParsedNumber(value)
    local parsed = tonumber(value)
    if not parsed or parsed ~= parsed or parsed < 0 then return nil end
    return parsed
end

local function Number(value)
    return ParsedNumber(value) or 0
end

local function IntegrityFailure(failures, reason)
    failures[reason] = true
end

local function Safe(value)
    local text = tostring(value or 'unknown')
    text = string.gsub(text, '|', '/')
    text = string.gsub(text, '[\r\n]', ' ')
    return text
end

local function Blueprint(unit, failures)
    local ok, blueprint = pcall(function() return unit:GetBlueprint() end)
    if ok and type(blueprint) == 'table' then return blueprint end
    IntegrityFailure(failures, 'unit-blueprint-api-failed')
    return {}
end

local function Has(blueprint, category)
    local hash = blueprint.CategoriesHash or {}
    return hash[category] == true
end

local function CompleteOwned(unit, army, failures)
    if not unit or unit.Dead then return false end
    local destroyedOk, destroyed = pcall(function() return unit:BeenDestroyed() end)
    if not destroyedOk then
        IntegrityFailure(failures, 'unit-destroyed-api-failed')
        return false
    end
    if destroyed then return false end
    local armyOk, owner = pcall(function() return unit:GetArmy() end)
    if not armyOk then
        IntegrityFailure(failures, 'unit-army-api-failed')
        return false
    end
    if owner ~= army then return false end
    local fractionOk, fraction = pcall(function() return unit:GetFractionComplete() end)
    local parsedFraction = fractionOk and ParsedNumber(fraction) or nil
    if parsedFraction == nil then
        IntegrityFailure(failures, 'unit-completion-api-failed')
        return false
    end
    return parsedFraction >= 1
end

local function UnitToken(brain, unit, failures)
    if type(unit.Overmind4Token) == 'string' then return unit.Overmind4Token end
    local idOk, id = pcall(function() return unit:GetEntityId() end)
    if not idOk or not id then
        IntegrityFailure(failures, 'unit-entity-api-failed')
        return nil
    end
    local generation = 0
    local entry = (brain.Overmind4EntityGenerations or {})[id]
    if type(entry) == 'table' and entry.reference == unit then
        generation = math.floor(Number(entry.generation))
    end
    return tostring(id) .. ':' .. tostring(generation)
end

local function SiteKey(unit, failures)
    local ok, position = pcall(function() return unit:GetPosition() end)
    local x = ok and type(position) == 'table' and ParsedNumber(position[1]) or nil
    local z = ok and type(position) == 'table'
        and ParsedNumber(position[3] or position[2]) or nil
    if x == nil or z == nil then
        IntegrityFailure(failures, 'unit-position-api-failed')
        return nil
    end
    return string.format('%.1f:%.1f', x, z)
end

local function Economy(brain, method, resource, failures)
    local ok, value = pcall(function() return brain[method](brain, resource) end)
    local parsed = ok and ParsedNumber(value) or nil
    if parsed == nil then
        IntegrityFailure(failures, 'economy-api-failed')
        return 0
    end
    return parsed
end

local function ArmyStat(brain, name, failures)
    local ok, value = pcall(function() return brain:GetArmyStat(name, 0) end)
    if not ok then
        IntegrityFailure(failures, 'army-stat-api-failed')
        return 0
    end
    if type(value) == 'table' then value = value.Value end
    local parsed = ParsedNumber(value)
    if parsed == nil then
        IntegrityFailure(failures, 'army-stat-api-failed')
        return 0
    end
    return parsed
end

local function BlueprintStat(brain, name, category, failures)
    local ok, value = pcall(function() return brain:GetBlueprintStat(name, category) end)
    local parsed = ok and ParsedNumber(value) or nil
    if parsed == nil then
        IntegrityFailure(failures, 'blueprint-stat-api-failed')
        return 0
    end
    return parsed
end

local function Tier(blueprint)
    if Has(blueprint, 'TECH3') then return 3 end
    if Has(blueprint, 'TECH2') then return 2 end
    return 1
end

local function EmptyMetrics()
    local metrics = {}
    for _, name in ipairs(METRIC_NAMES) do metrics[name] = 0 end
    return metrics
end

local function ForceOwners(brain)
    local owners = {}
    local assignments = ((brain.Overmind4ForcePlan or {}).assignments or {})
    for _, bucket in ipairs(FORCE_BUCKETS) do
        for _, token in ipairs(assignments[bucket] or {}) do
            if type(token) == 'string' and owners[token] == nil then
                owners[token] = bucket
            end
        end
    end
    return owners
end

local function Emit(observer, tick, army, metrics)
    local parts = {
        'OM4BENCH', 'v=1', 'kind=checkpoint', 'run=' .. Safe(observer.runId),
        'tick=' .. tostring(tick), 'army=' .. tostring(army),
    }
    for _, name in ipairs(METRIC_NAMES) do
        table.insert(parts, name .. '=' .. tostring(Number(metrics[name])))
    end
    observer.logger(table.concat(parts, '|'))
end

local function EmitIntegrity(observer, tick, army, reason)
    observer.logger(table.concat({
        'OM4BENCH', 'v=1', 'kind=integrity',
        'run=' .. Safe(observer.runId), 'tick=' .. tostring(tick),
        'army=' .. tostring(army), 'reason=' .. Safe(reason),
        'source=observer',
    }, '|'))
end

Overmind4Benchmark = {}

function Overmind4Benchmark.Create(runId, armySlots, logger)
    local slots = {}
    for _, army in ipairs(armySlots or {}) do table.insert(slots, army) end
    return {
        runId = runId,
        armySlots = slots,
        logger = logger or LOG,
        lastTick = 0,
        armies = {},
    }
end

function Overmind4Benchmark.SampleArmy(observer, brain, army, tick)
    local metrics = EmptyMetrics()
    local integrityFailures = {}
    local state = observer.armies[army] or {
        activeMexSites = {},
        knownMexSites = {},
        mexRebuilt = 0,
        fullBankIdleTicks = 0,
        lastTick = tick,
    }
    observer.armies[army] = state

    if brain.Overmind4 == true
        and (type(brain.Overmind4ForcePlan) ~= 'table'
            or type(brain.Overmind4EntityGenerations) ~= 'table')
    then
        IntegrityFailure(integrityFailures, 'force-plan-unavailable')
    end

    metrics.mass_income = Economy(
        brain, 'GetEconomyIncome', 'MASS', integrityFailures
    ) * 10
    metrics.energy_income = Economy(
        brain, 'GetEconomyIncome', 'ENERGY', integrityFailures
    ) * 10
    metrics.mass_stored = Economy(
        brain, 'GetEconomyStored', 'MASS', integrityFailures
    )
    metrics.energy_stored = Economy(
        brain, 'GetEconomyStored', 'ENERGY', integrityFailures
    )
    metrics.mass_spent = ArmyStat(
        brain, 'Economy_TotalConsumed_Mass', integrityFailures
    )
    metrics.energy_spent = ArmyStat(
        brain, 'Economy_TotalConsumed_Energy', integrityFailures
    )
    metrics.mass_reclaim = ArmyStat(
        brain, 'Economy_Reclaimed_Mass', integrityFailures
    )
    metrics.energy_reclaim = ArmyStat(
        brain, 'Economy_Reclaimed_Energy', integrityFailures
    )
    metrics.mass_excess = ArmyStat(
        brain, 'Economy_AccumExcess_Mass', integrityFailures
    )
    metrics.energy_excess = ArmyStat(
        brain, 'Economy_AccumExcess_Energy', integrityFailures
    )
    metrics.mass_killed = ArmyStat(
        brain, 'Enemies_MassValue_Destroyed', integrityFailures
    )
    metrics.mass_lost = ArmyStat(
        brain, 'Units_MassValue_Lost', integrityFailures
    )

    local engineerHistory = BlueprintStat(
        brain, 'Units_History', categories.ENGINEER, integrityFailures
    )
    local commanderHistory = BlueprintStat(
        brain, 'Units_History', categories.COMMAND, integrityFailures
    )
    local engineerKills = BlueprintStat(
        brain, 'Units_Killed', categories.ENGINEER, integrityFailures
    )
    local commanderKills = BlueprintStat(
        brain, 'Units_Killed', categories.COMMAND, integrityFailures
    )
    metrics.engineers_built = math.max(0, engineerHistory - commanderHistory)
    metrics.engineers_lost = math.max(0, engineerKills - commanderKills)
    metrics.mex_built = BlueprintStat(
        brain, 'Units_History', categories.MASSEXTRACTION, integrityFailures
    )
    metrics.mex_lost = BlueprintStat(
        brain, 'Units_Killed', categories.MASSEXTRACTION, integrityFailures
    )

    local owners = ForceOwners(brain)
    local activeSites = {}
    local factoryCount = 0
    local idleFactories = 0
    local unitsOk, units = pcall(function()
        return brain:GetListOfUnits(categories.ALLUNITS, false, false)
    end)
    if not unitsOk or type(units) ~= 'table' then
        IntegrityFailure(integrityFailures, 'unit-list-api-failed')
        units = {}
    end
    for _, unit in ipairs(units) do
        if CompleteOwned(unit, army, integrityFailures) then
            local blueprint = Blueprint(unit, integrityFailures)
            local mass = Number((blueprint.Economy or {}).BuildCostMass)
            local tier = Tier(blueprint)
            local mobile = Has(blueprint, 'MOBILE')
            local air = Has(blueprint, 'AIR')
            local land = Has(blueprint, 'LAND')
            local engineer = Has(blueprint, 'ENGINEER')
            local commander = Has(blueprint, 'COMMAND')

            if engineer and not commander then
                metrics.engineers_alive = metrics.engineers_alive + 1
            end
            if Has(blueprint, 'MASSEXTRACTION') then
                metrics['mex_t' .. tostring(tier)] = metrics['mex_t' .. tostring(tier)] + 1
                local site = SiteKey(unit, integrityFailures)
                if site then activeSites[site] = true end
            end
            if Has(blueprint, 'FACTORY') then
                local layer = air and 'air' or (land and 'land' or nil)
                if layer then
                    local name = layer .. '_factory_t' .. tostring(tier)
                    metrics[name] = metrics[name] + 1
                    factoryCount = factoryCount + 1
                    local idleOk, idle = pcall(function() return unit:IsIdleState() end)
                    if not idleOk then
                        IntegrityFailure(
                            integrityFailures, 'factory-idle-api-failed'
                        )
                    elseif idle then
                        idleFactories = idleFactories + 1
                    end
                end
            end
            if mobile and air and not engineer and not commander then
                if Has(blueprint, 'SCOUT') then
                    metrics.air_scout = metrics.air_scout + 1
                elseif Has(blueprint, 'TRANSPORTATION') then
                    metrics.air_transport = metrics.air_transport + 1
                elseif Has(blueprint, 'BOMBER') then
                    metrics.air_bomber = metrics.air_bomber + 1
                elseif Has(blueprint, 'ANTIAIR') then
                    metrics.air_interceptor = metrics.air_interceptor + 1
                else
                    metrics.air_other = metrics.air_other + 1
                end
            end
            if mobile and land and not engineer and not commander then
                if tier == 2 then metrics.mobile_t2 = metrics.mobile_t2 + 1 end
                if tier == 3 then metrics.mobile_t3 = metrics.mobile_t3 + 1 end
                local token = UnitToken(brain, unit, integrityFailures)
                local bucket = token and owners[token] or 'unassigned'
                metrics['army_count_' .. bucket] = metrics['army_count_' .. bucket] + 1
                metrics['army_mass_' .. bucket] = metrics['army_mass_' .. bucket] + mass
            end
        end
    end

    for site, _ in pairs(activeSites) do
        if state.knownMexSites[site] and not state.activeMexSites[site] then
            state.mexRebuilt = state.mexRebuilt + 1
        end
        state.knownMexSites[site] = true
    end
    state.activeMexSites = activeSites
    metrics.mex_rebuilt = state.mexRebuilt
    local mexAlive = metrics.mex_t1 + metrics.mex_t2 + metrics.mex_t3
    metrics.mex_survival = metrics.mex_built > 0 and mexAlive / metrics.mex_built or 0

    metrics.factory_idle = idleFactories
    metrics.factory_utilization = factoryCount > 0
        and (factoryCount - idleFactories) / factoryCount or 0
    local fullMass = Economy(
        brain, 'GetEconomyStoredRatio', 'MASS', integrityFailures
    ) >= 0.95
    local fullEnergy = Economy(
        brain, 'GetEconomyStoredRatio', 'ENERGY', integrityFailures
    ) >= 0.95
    if fullMass and fullEnergy and idleFactories > 0 then
        state.fullBankIdleTicks = state.fullBankIdleTicks
            + math.max(0, tick - state.lastTick) * idleFactories
    end
    state.lastTick = tick
    metrics.factory_full_bank_idle_ticks = state.fullBankIdleTicks

    local reasons = {}
    for reason, _ in pairs(integrityFailures) do table.insert(reasons, reason) end
    table.sort(reasons)
    for _, reason in ipairs(reasons) do
        EmitIntegrity(observer, tick, army, reason)
    end
    Emit(observer, tick, army, metrics)
    return metrics
end

function Overmind4Benchmark.Step(observer, tick)
    tick = math.floor(Number(tick))
    local checkpoint = math.floor(tick / CHECKPOINT_TICKS) * CHECKPOINT_TICKS
    if checkpoint < CHECKPOINT_TICKS or checkpoint <= observer.lastTick then
        return false
    end
    observer.lastTick = checkpoint
    for _, army in ipairs(observer.armySlots) do
        local brainOk, brain = pcall(function() return GetArmyBrain(army) end)
        if not brainOk or not brain then
            EmitIntegrity(
                observer, checkpoint, army, 'army-brain-unavailable'
            )
        else
            local sampleOk = pcall(function()
                Overmind4Benchmark.SampleArmy(observer, brain, army, checkpoint)
            end)
            if not sampleOk then
                EmitIntegrity(observer, checkpoint, army, 'sample-api-failed')
            end
        end
    end
    return true
end

return { Overmind4Benchmark = Overmind4Benchmark }
