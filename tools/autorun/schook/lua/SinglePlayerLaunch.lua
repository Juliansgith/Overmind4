-- Overmind4 FAF 3836 autorun hook.
-- This file intentionally replaces only the command-line session entry point.

local Prefs = import('/lua/user/prefs.lua')
local MapUtils = import('/lua/ui/maputil.lua')
local Mods = import('/lua/mods.lua')
local Lobby = import('/lua/ui/lobby/lobbycomm.lua')
local GameColors = import('/lua/gamecolors.lua').GameColors

local ModUid = '0d46fbb2-beeb-4bde-b3c6-8bac28232a4b'

local function Safe(value)
    local text = tostring(value or 'unknown')
    text = string.gsub(text, '|', '/')
    text = string.gsub(text, '[\r\n]', ' ')
    return text
end

local function Marker(kind, runId, fields)
    local parts = {
        'OM4HARNESS',
        'v=1',
        'kind=' .. Safe(kind),
        'run=' .. Safe(runId),
    }
    for index = 1, table.getn(fields or {}) do
        table.insert(parts, fields[index])
    end
    LOG(table.concat(parts, '|'))
end

local function Fail(runId, reason, detail)
    Marker('failure', runId, {
        'reason=' .. Safe(reason),
        'detail=' .. Safe(detail),
    })
    error('Overmind4 autorun refused session: ' .. tostring(reason) .. ': ' .. tostring(detail))
end

local function RequiredArg(name, runId)
    local values = GetCommandLineArg(name, 1)
    if not values or values[1] == nil or tostring(values[1]) == '' then
        Fail(runId, 'missing_arg', name)
    end
    return tostring(values[1])
end

local function SafeIdentifier(value)
    if string.len(value) < 1 or string.len(value) > 64 then
        return false
    end
    return string.find(value, '^[A-Za-z0-9][A-Za-z0-9_-]*$') ~= nil
end

local function IntegerInRange(value, minimum, maximum, field, runId)
    local number = tonumber(value)
    if not number or number ~= math.floor(number) or number < minimum or number > maximum then
        Fail(runId, 'invalid_arg', field)
    end
    return number
end

local function ParseAiSpecs(text, runId)
    if string.sub(text, 1, 1) == ',' or string.sub(text, -1) == ',' or string.find(text, ',,', 1, true) then
        Fail(runId, 'invalid_aitest', 'empty AI spec')
    end

    local specs = {}
    for chunk in string.gmatch(text, '[^,]+') do
        local slotText, key, factionText, teamText = string.match(
            chunk,
            '^([^:]+):([^:]+):([^:]+):([^:]+)$'
        )
        if not slotText then
            Fail(runId, 'invalid_aitest', 'expected slot:key:faction:team')
        end
        if not SafeIdentifier(key) then
            Fail(runId, 'invalid_aitest', 'unsafe AI key')
        end
        table.insert(specs, {
            Spawn = IntegerInRange(slotText, 1, 16, 'AI slot', runId),
            AIPersonality = key,
            Faction = IntegerInRange(factionText, 1, 4, 'AI faction', runId),
            Team = IntegerInRange(teamText, 1, 16, 'AI team', runId),
        })
    end

    if table.getn(specs) ~= 2 then
        Fail(runId, 'invalid_aitest', 'exactly two AI specs are required')
    end
    if specs[1].Spawn == specs[2].Spawn then
        Fail(runId, 'invalid_aitest', 'AI slots must be distinct')
    end
    if specs[1].Team == specs[2].Team then
        Fail(runId, 'invalid_aitest', 'AI teams must be opposed')
    end
    return specs
end

local function ExactOvermind4Mods(runId)
    local available = Mods.AllMods()
    local mod = available and available[ModUid]
    if not mod or mod.ui_only then
        Fail(runId, 'mod_unavailable', ModUid)
    end

    local selected = { [ModUid] = true }
    local resolved = Mods.GetGameMods(selected)
    if table.getn(resolved) ~= 1 or resolved[1].uid ~= ModUid then
        Fail(runId, 'mod_isolation_failed', 'resolved sim-mod list was not exactly Overmind4')
    end
    return resolved
end

local function AddCivilian(teamInfo, index, armyName)
    local options = Lobby.GetDefaultPlayerOptions('Civilian')
    options.PlayerName = 'Civilian-' .. tostring(index)
    options.Civilian = true
    options.ArmyName = armyName
    options.Human = false
    teamInfo[index] = options
end

local function StartSpeedAndTimeoutThread(runId, speed, maxGameTime)
    ForkThread(function()
        while not WorldIsPlaying() do
            coroutine.yield(1)
        end

        SetGameSpeed(speed)
        Marker('speed', runId, {
            'requested=' .. tostring(speed),
            'sim=' .. tostring(GetGameTimeSeconds()),
        })

        while GetGameTimeSeconds() < maxGameTime do
            coroutine.yield(10)
        end
        Marker('timeout', runId, { 'sim=' .. tostring(GetGameTimeSeconds()) })
        SessionEndGame()
    end)
end

function StartCommandLineSession(mapName, isPerfTest)
    local runId = RequiredArg('/om4runid', 'unknown')
    if not SafeIdentifier(runId) then
        Fail('unknown', 'invalid_run_id', runId)
    end
    if not mapName or mapName == '' then
        Fail(runId, 'missing_map', '/map')
    end

    local seed = IntegerInRange(RequiredArg('/seed', runId), 0, 2147483647, 'seed', runId)
    local speed = IntegerInRange(RequiredArg('/speed', runId), 1, 100, 'speed', runId)
    local maxGameTime = IntegerInRange(
        RequiredArg('/maxtime', runId),
        1,
        86400,
        'maxtime',
        runId
    )
    local unitCap = IntegerInRange(
        RequiredArg('/unitcap', runId),
        1,
        10000,
        'unitcap',
        runId
    )
    local aiText = RequiredArg('/aitest', runId)
    local specs = ParseAiSpecs(aiText, runId)

    -- Retain FAF 3836's map fixup and loader, including versioned-map handling.
    local fixedMapName = FixupMapName(mapName)
    local scenario = MapUtils.LoadScenario(fixedMapName)
    if not scenario then
        Fail(runId, 'map_load_failed', fixedMapName)
    end
    if scenario.type == 'campaign' then
        Fail(runId, 'campaign_not_supported', fixedMapName)
    end
    VerifyScenarioConfiguration(scenario)

    local armies = scenario.Configurations.standard.teams[1].armies
    local armyCount = table.getn(armies)
    local colorCount = table.getn(GameColors.PlayerColors)
    local sessionInfo = {
        playerName = Prefs.GetFromCurrentProfile('Name') or 'Overmind4 Harness',
        createReplay = true,
        scenarioInfo = scenario,
        teamInfo = {},
        scenarioMods = ExactOvermind4Mods(runId),
        RandomSeed = seed,
    }

    for index = 1, 2 do
        local spec = specs[index]
        if spec.Spawn > armyCount then
            Fail(runId, 'invalid_aitest', 'AI slot is unavailable on this map')
        end
        local options = Lobby.GetDefaultPlayerOptions(sessionInfo.playerName)
        options.AIPersonality = spec.AIPersonality
        options.Faction = spec.Faction
        options.Team = spec.Team
        options.PlayerName = 'OM4-' .. tostring(spec.Spawn) .. '-' .. spec.AIPersonality
        options.Human = false
        options.ArmyName = armies[spec.Spawn]
        options.PlayerColor = math.mod(spec.Spawn - 1, colorCount) + 1
        options.ArmyColor = options.PlayerColor
        sessionInfo.teamInfo[spec.Spawn] = options
    end

    local nextIndex = armyCount + 1
    local extras = MapUtils.GetExtraArmies(scenario)
    if extras then
        local extraNames = {}
        for _, armyName in pairs(extras) do
            table.insert(extraNames, armyName)
        end
        table.sort(extraNames)
        for index = 1, table.getn(extraNames) do
            AddCivilian(sessionInfo.teamInfo, nextIndex, extraNames[index])
            nextIndex = nextIndex + 1
        end
    end
    AddCivilian(sessionInfo.teamInfo, nextIndex, 'ARMY_17')
    nextIndex = nextIndex + 1
    AddCivilian(sessionInfo.teamInfo, nextIndex, 'NEUTRAL_CIVILIAN')

    scenario.Options = {
        FogOfWar = 'explored',
        NoRushOption = 'Off',
        PrebuiltUnits = 'Off',
        Difficulty = 2,
        DoNotShareUnitCap = true,
        Timeouts = -1,
        GameSpeed = 'normal',
        UnitCap = tostring(unitCap),
        Victory = 'demoralization',
        CheatsEnabled = 'false',
        CivilianAlliance = 'enemy',
        TeamShareOverflow = 'enabled',
        TeamSpawn = 'fixed',
        AllowObservers = true,
        AIThreatDisplay = 'threatOff',
    }

    Prefs.SetToCurrentProfile('LoadingFaction', specs[1].Faction)
    Marker('start', runId, {
        'map=' .. Safe(mapName),
        'seed=' .. tostring(seed),
        'speed=' .. tostring(speed),
        'maxtime=' .. tostring(maxGameTime),
        'ais=' .. Safe(aiText),
    })
    StartSpeedAndTimeoutThread(runId, speed, maxGameTime)
    LaunchSinglePlayerSession(sessionInfo)
end
