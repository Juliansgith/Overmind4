-- Preserve FAF's official result handling and add one machine-readable marker.
local PreviousDoGameResult = DoGameResult

local function Safe(value)
    local text = tostring(value or 'unknown')
    text = string.gsub(text, '|', '/')
    text = string.gsub(text, '[\r\n]', ' ')
    return text
end

function DoGameResult(armyIndex, result)
    local values = GetCommandLineArg('/om4runid', 1)
    local runId = values and values[1] or 'unknown'
    local sim = GetGameTimeSeconds and GetGameTimeSeconds() or -1
    LOG(
        'OM4HARNESS|v=1|kind=result|run=' .. Safe(runId)
        .. '|army=' .. Safe(armyIndex)
        .. '|result=' .. Safe(result)
        .. '|sim=' .. Safe(sim)
    )
    return PreviousDoGameResult(armyIndex, result)
end

