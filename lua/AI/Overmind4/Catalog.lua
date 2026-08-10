local IdByRole = {
    acu = 'uel0001',
    engineer = 'uel0105',
    land_factory = 'ueb0101',
    power_generator = 'ueb1101',
    hydrocarbon = 'ueb1102',
    mass_extractor = 'ueb1103',
    scout = 'uel0101',
    artillery = 'uel0103',
    anti_air = 'uel0104',
    lab = 'uel0106',
    tank = 'uel0201',
}

local RoleById = {}
for role, blueprintId in pairs(IdByRole) do
    RoleById[blueprintId] = role
end
RoleById.ueb1202 = 'mass_extractor'
RoleById.ueb1302 = 'mass_extractor'

Catalog = {}

Catalog.IdFor = function(role)
    return IdByRole[role]
end

Catalog.RoleFor = function(blueprintId)
    if type(blueprintId) ~= 'string' then
        return nil
    end

    return RoleById[string.lower(blueprintId)]
end
