local IdByRole = {
    acu = 'uel0001',
    engineer = 'uel0105',
    land_factory = 'ueb0101',
    air_factory = 'ueb0102',
    land_factory_t2 = 'ueb0201',
    power_generator = 'ueb1101',
    hydrocarbon = 'ueb1102',
    mass_extractor = 'ueb1103',
    scout = 'uel0101',
    artillery = 'uel0103',
    anti_air = 'uel0104',
    lab = 'uel0106',
    tank = 'uel0201',
    air_scout = 'uea0101',
    interceptor = 'uea0102',
    bomber = 'uea0103',
    transport = 'uea0107',
    t2_direct_fire = 'uel0202',
    t2_anti_air = 'uel0205',
    radar = 'ueb3101',
    point_defense = 'ueb2101',
    static_anti_air = 'ueb2104',
    mass_extractor_t2 = 'ueb1202',
    mass_extractor_t3 = 'ueb1302',
    land_factory_t3 = 'ueb0301',
    t3_direct_fire = 'uel0303',
}

local RoleById = {}
for role, blueprintId in pairs(IdByRole) do
    RoleById[blueprintId] = role
end

local FamilyByRole = {
    mass_extractor = 'mass_extractor',
    mass_extractor_t2 = 'mass_extractor',
    mass_extractor_t3 = 'mass_extractor',
    land_factory = 'land_factory',
    land_factory_t2 = 'land_factory',
    land_factory_t3 = 'land_factory',
}

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

Catalog.FamilyForRole = function(role)
    return FamilyByRole[role] or role
end

Catalog.FamilyForId = function(blueprintId)
    local role = Catalog.RoleFor(blueprintId)
    return role and Catalog.FamilyForRole(role) or nil
end

Catalog.IsRoleFamily = function(role, family)
    return Catalog.FamilyForRole(role) == family
end
