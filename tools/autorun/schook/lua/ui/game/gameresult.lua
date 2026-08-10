-- Preserve FAF's official result handling and add one machine-readable marker.
local PreviousDoGameResult = DoGameResult
local TerminalLogged = {}

local function Safe(value)
    local text = tostring(value or 'unknown')
    text = string.gsub(text, '|', '/')
    text = string.gsub(text, '[\r\n]', ' ')
    return text
end

function DoGameResult(armyIndex, result)
    local separator = string.find(result, ' ', 1, true)
    local resultKind = separator and string.sub(result, 1, separator - 1) or result
    local terminal = resultKind == 'victory' or resultKind == 'defeat' or resultKind == 'draw'
    if terminal and not TerminalLogged[armyIndex] then
        TerminalLogged[armyIndex] = true
        local values = GetCommandLineArg('/om4runid', 1)
        local runId = values and values[1] or 'unknown'
        local sim = GetGameTimeSeconds and GetGameTimeSeconds() or -1
        LOG(
            'OM4HARNESS|v=1|kind=result|run=' .. Safe(runId)
            .. '|army=' .. Safe(armyIndex)
            .. '|result=' .. Safe(result)
            .. '|sim=' .. Safe(sim)
        )
    end
    return PreviousDoGameResult(armyIndex, result)
end
