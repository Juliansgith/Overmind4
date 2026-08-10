local StandardBrain = import('/lua/aibrain.lua').AIBrain
local Telemetry = import('/mods/overmind4/lua/AI/Overmind4/Telemetry.lua').Telemetry

NewAIBrain = Class(StandardBrain) {
    SkirmishSystems = false,

    OnCreateAI = function(self, planName)
        StandardBrain.OnCreateAI(self, planName)

        self.Overmind4 = true
        self.SkirmishSystems = false

        Telemetry.EmitLifecycleOnce(self, 'created', {
            army = self.Army,
            plan = planName,
        })
    end,

    OnBeginSession = function(self)
        StandardBrain.OnBeginSession(self)
        Telemetry.EmitLifecycleOnce(self, 'begin_session', { army = self.Army })
    end,

    OnVictory = function(self)
        StandardBrain.OnVictory(self)
        Telemetry.EmitLifecycleOnce(self, 'terminal', {
            army = self.Army,
            result = 'victory',
        })
    end,

    OnDefeat = function(self)
        StandardBrain.OnDefeat(self)
        Telemetry.EmitLifecycleOnce(self, 'terminal', {
            army = self.Army,
            result = 'defeat',
        })
    end,

    OnDraw = function(self)
        StandardBrain.OnDraw(self)
        Telemetry.EmitLifecycleOnce(self, 'terminal', {
            army = self.Army,
            result = 'draw',
        })
    end,

    OnDestroy = function(self)
        StandardBrain.OnDestroy(self)
        Telemetry.EmitLifecycleOnce(self, 'destroyed', { army = self.Army })
    end,
}
