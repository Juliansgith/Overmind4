do
    local Overmind4Brain = import('/mods/overmind4/lua/AI/Overmind4/Brain.lua')

    keyToBrain = keyToBrain or {}
    keyToBrain['overmind4'] = Overmind4Brain.NewAIBrain
end
