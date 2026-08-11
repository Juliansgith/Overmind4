-- Simulation-state installer for observer-only Overmind4 benchmark telemetry.
-- The launcher only places validated configuration in ScenarioInfo.Options;
-- all simulation APIs stay in this hook and the observer module it imports.

local PreviousBeginSession = BeginSession

local function BenchmarkConfiguration()
    local options = ScenarioInfo and ScenarioInfo.Options or nil
    if type(options) ~= 'table' then return nil end

    local runId = options.Overmind4BenchmarkRunId
    local armyOne = tonumber(options.Overmind4BenchmarkArmyOne)
    local armyTwo = tonumber(options.Overmind4BenchmarkArmyTwo)
    local validArmies = armyOne and armyTwo
        and armyOne == math.floor(armyOne)
        and armyTwo == math.floor(armyTwo)
        and armyOne >= 1 and armyOne <= 16
        and armyTwo >= 1 and armyTwo <= 16
        and armyOne ~= armyTwo
    if type(runId) ~= 'string' or runId == '' or not validArmies then
        return nil
    end
    return runId, armyOne, armyTwo
end

local function StartBenchmarkObserver(runId, armyOne, armyTwo)
    ForkThread(function()
        local Overmind4Benchmark = import(
            '/lua/Overmind4Benchmark.lua'
        ).Overmind4Benchmark
        local observer = Overmind4Benchmark.Create(runId, { armyOne, armyTwo }, LOG)
        while true do
            Overmind4Benchmark.Step(observer, GetGameTick())
            WaitTicks(30)
        end
    end)
end

function BeginSession()
    local result = PreviousBeginSession()
    local runId, armyOne, armyTwo = BenchmarkConfiguration()
    if runId then
        StartBenchmarkObserver(runId, armyOne, armyTwo)
    end
    return result
end
