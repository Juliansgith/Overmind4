local ReservedFields = {
    kind = true,
    v = true,
}

local function EscapeScalar(value, fieldName)
    local valueType = type(value)
    local text

    if valueType == 'boolean' then
        text = value and 'true' or 'false'
    elseif valueType == 'number' or valueType == 'string' then
        text = tostring(value)
    else
        error("telemetry field '" .. tostring(fieldName) .. "' must be scalar")
    end

    text = string.gsub(text, '\\', '\\\\')
    text = string.gsub(text, '\r', '\\r')
    text = string.gsub(text, '\n', '\\n')
    text = string.gsub(text, '\t', '\\t')
    text = string.gsub(text, '|', '\\p')
    text = string.gsub(text, '=', '\\e')

    return text
end

Telemetry = {
    SchemaVersion = 1,
}

Telemetry.Format = function(kind, fields)
    local names = {}
    fields = fields or {}

    for name, _ in pairs(fields) do
        if type(name) ~= 'string' then
            error('telemetry field names must be strings')
        end

        if not ReservedFields[name] then
            table.insert(names, name)
        end
    end

    table.sort(names)

    local parts = {
        'OM4',
        'v=' .. tostring(Telemetry.SchemaVersion),
        'kind=' .. EscapeScalar(kind, 'kind'),
    }

    for _, name in ipairs(names) do
        table.insert(parts, name .. '=' .. EscapeScalar(fields[name], name))
    end

    return table.concat(parts, '|')
end

Telemetry.Emit = function(kind, fields, logger)
    local line = Telemetry.Format(kind, fields)
    local sink = logger or LOG

    if sink then
        sink(line)
    end

    return line
end


Telemetry.EmitLifecycleOnce = function(brain, event, fields, logger)
    local emitted = brain.Overmind4TelemetryEmitted
    if not emitted then
        emitted = {}
        brain.Overmind4TelemetryEmitted = emitted
    end

    if emitted[event] then
        return nil
    end

    emitted[event] = true

    local lifecycleFields = {}
    for name, value in pairs(fields or {}) do
        if name ~= 'event' then
            lifecycleFields[name] = value
        end
    end
    lifecycleFields.event = event

    return Telemetry.Emit('lifecycle', lifecycleFields, logger)
end
