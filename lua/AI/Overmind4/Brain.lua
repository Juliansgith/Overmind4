local StandardBrain = import('/lua/aibrain.lua').AIBrain
local Telemetry = import('/mods/overmind4/lua/AI/Overmind4/Telemetry.lua').Telemetry
local Controller = import('/mods/overmind4/lua/AI/Overmind4/Controller.lua').Controller

local function StopController(brain, reason)
    if brain.Overmind4Controller then
        Controller.Stop(brain.Overmind4Controller, reason)
    end
end

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

        if not self.Overmind4Controller then
            self.Overmind4Controller = Controller.Create(self)
            self.Overmind4ControllerThread = self:ForkThread(
                Controller.Run,
                self.Overmind4Controller
            )
        end

        Telemetry.EmitLifecycleOnce(self, 'begin_session', { army = self.Army })
    end,

    OnVictory = function(self)
        StopController(self, 'victory')
        StandardBrain.OnVictory(self)
        Telemetry.EmitLifecycleOnce(self, 'terminal', {
            army = self.Army,
            result = 'victory',
        })
    end,

    OnDefeat = function(self)
        StopController(self, 'defeat')
        StandardBrain.OnDefeat(self)
        Telemetry.EmitLifecycleOnce(self, 'terminal', {
            army = self.Army,
            result = 'defeat',
        })
    end,

    OnDraw = function(self)
        StopController(self, 'draw')
        StandardBrain.OnDraw(self)
        Telemetry.EmitLifecycleOnce(self, 'terminal', {
            army = self.Army,
            result = 'draw',
        })
    end,

    OnDestroy = function(self)
        StopController(self, 'destroyed')
        StandardBrain.OnDestroy(self)
        Telemetry.EmitLifecycleOnce(self, 'destroyed', { army = self.Army })
    end,
}
