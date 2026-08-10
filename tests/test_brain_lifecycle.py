from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from conftest import runtime, source


ISSUE_COMMANDS = (
    "IssueAggressiveMove",
    "IssueAttack",
    "IssueBuildFactory",
    "IssueBuildMobile",
    "IssueClearCommands",
    "IssueFactoryRallyPoint",
    "IssueFormAttack",
    "IssueFormMove",
    "IssueGuard",
    "IssueMove",
    "IssuePatrol",
    "IssueReclaim",
    "IssueRepair",
    "IssueStop",
)

FORBIDDEN_MANAGER_CALLS = (
    "InitializeSkirmishSystems",
    "InitializeBuilderManagers",
    "AddBuilderManagers",
    "ExecutePlan",
    "CreateStrategyManager",
    "CreatePlatoonFormManager",
)

WORLD_QUERIES = (
    "GetArmyBrain",
    "GetGameTick",
    "GetMapSize",
    "GetReclaimablesInRect",
    "GetUnitsInRect",
)


@dataclass
class BrainHarness:
    lua: Any
    brain_class: Any
    standard_brain: Any
    imports: list[str]
    logs: list[str]
    forbidden_calls: list[str]

    def brain(self):
        brain = self.lua.table()
        self.lua.globals()["__new_brain"] = brain
        self.lua.execute("setmetatable(__new_brain, NewAIBrain)")
        return brain


def make_harness() -> BrainHarness:
    lua = runtime()
    lua.execute(
        """
        function Class(parent)
            return function(definition)
                definition.__index = definition
                setmetatable(definition, { __index = parent })
                return definition
            end
        end

        StandardBrain = {
            SkirmishSystems = 'parent-default',
            OnCreateAI = function(self, planName)
                self.ParentCreateCalls = (self.ParentCreateCalls or 0) + 1
                self.ParentPlanName = planName
                self.BrainType = 'AI'
                self.Army = 7
                self.SkirmishSystems = true
            end,
            OnBeginSession = function(self)
                self.ParentBeginCalls = (self.ParentBeginCalls or 0) + 1
            end,
            OnVictory = function(self)
                self.ParentVictoryCalls = (self.ParentVictoryCalls or 0) + 1
                self.Status = 'Victory'
            end,
            OnDefeat = function(self)
                self.ParentDefeatCalls = (self.ParentDefeatCalls or 0) + 1
                self.Status = 'Defeat'
            end,
            OnDraw = function(self)
                self.ParentDrawCalls = (self.ParentDrawCalls or 0) + 1
                self.Status = 'Draw'
            end,
            OnDestroy = function(self)
                self.ParentDestroyCalls = (self.ParentDestroyCalls or 0) + 1
                self.Destroyed = true
            end,
        }
        StandardBrain.__index = StandardBrain
        setmetatable(StandardBrain, {})
        """
    )

    logs: list[str] = []
    forbidden_calls: list[str] = []
    lua.globals().LOG = logs.append

    def forbidden(name: str):
        def record(*_args: object):
            forbidden_calls.append(name)
            raise AssertionError(f"forbidden skeleton call: {name}")

        return record

    for name in ISSUE_COMMANDS + FORBIDDEN_MANAGER_CALLS + WORLD_QUERIES:
        lua.globals()[name] = forbidden(name)

    lua.execute(source("lua/AI/Overmind4/Telemetry.lua"))
    telemetry_module = lua.table_from({"Telemetry": lua.globals().Telemetry})
    standard_module = lua.table_from({"AIBrain": lua.globals().StandardBrain})
    imports: list[str] = []

    def importer(path: str):
        imports.append(path)
        if path == "/lua/aibrain.lua":
            return standard_module
        if path == "/mods/overmind4/lua/AI/Overmind4/Telemetry.lua":
            return telemetry_module
        raise AssertionError(f"unexpected import: {path}")

    lua.globals()["import"] = importer
    lua.execute(source("lua/AI/Overmind4/Brain.lua"))

    return BrainHarness(
        lua=lua,
        brain_class=lua.globals().NewAIBrain,
        standard_brain=lua.globals().StandardBrain,
        imports=imports,
        logs=logs,
        forbidden_calls=forbidden_calls,
    )


def test_brain_derives_directly_from_standard_aibrain() -> None:
    harness = make_harness()

    assert harness.lua.eval("type(NewAIBrain)") == "table"
    assert harness.lua.eval("getmetatable(NewAIBrain).__index == StandardBrain") is True
    assert harness.imports == [
        "/lua/aibrain.lua",
        "/mods/overmind4/lua/AI/Overmind4/Telemetry.lua",
    ]


def test_class_and_instance_explicitly_disable_skirmish_systems() -> None:
    harness = make_harness()
    brain = harness.brain()

    assert harness.brain_class.SkirmishSystems is False
    brain.OnCreateAI(brain, "test-plan")
    assert brain.SkirmishSystems is False


def test_on_create_delegates_to_parent_before_marking_and_logging() -> None:
    harness = make_harness()
    brain = harness.brain()
    snapshots: list[tuple[int | None, bool | None]] = []

    def logger(line: str):
        snapshots.append((brain.ParentCreateCalls, brain.Overmind4))
        harness.logs.append(line)

    harness.lua.globals().LOG = logger
    brain.OnCreateAI(brain, "alpha")

    assert brain.ParentCreateCalls == 1
    assert brain.ParentPlanName == "alpha"
    assert brain.BrainType == "AI"
    assert brain.Overmind4 is True
    assert snapshots == [(1, True)]
    assert harness.logs == [
        "OM4|v=1|kind=lifecycle|army=7|event=created|plan=alpha"
    ]


def test_overmind_marker_is_isolated_to_initialized_instances() -> None:
    harness = make_harness()
    marked = harness.brain()
    untouched = harness.brain()

    marked.OnCreateAI(marked, "alpha")

    assert marked.Overmind4 is True
    assert untouched.Overmind4 is None
    assert harness.standard_brain.Overmind4 is None
    assert harness.lua.globals().Overmind4 is None


def test_begin_session_delegates_and_emits_only_once() -> None:
    harness = make_harness()
    brain = harness.brain()
    brain.OnCreateAI(brain, "alpha")

    brain.OnBeginSession(brain)
    brain.OnBeginSession(brain)

    assert brain.ParentBeginCalls == 2
    begin_lines = [line for line in harness.logs if "event=begin_session" in line]
    assert begin_lines == ["OM4|v=1|kind=lifecycle|event=begin_session"]


def test_create_lifecycle_telemetry_is_idempotent() -> None:
    harness = make_harness()
    brain = harness.brain()

    brain.OnCreateAI(brain, "alpha")
    brain.OnCreateAI(brain, "alpha")

    assert brain.ParentCreateCalls == 2
    created_lines = [line for line in harness.logs if "event=created" in line]
    assert created_lines == [
        "OM4|v=1|kind=lifecycle|army=7|event=created|plan=alpha"
    ]


def test_terminal_callbacks_delegate_but_emit_only_one_terminal_record() -> None:
    harness = make_harness()
    brain = harness.brain()
    brain.OnCreateAI(brain, "alpha")

    brain.OnVictory(brain)
    brain.OnVictory(brain)
    brain.OnDefeat(brain)
    brain.OnDraw(brain)

    assert brain.ParentVictoryCalls == 2
    assert brain.ParentDefeatCalls == 1
    assert brain.ParentDrawCalls == 1
    terminal_lines = [line for line in harness.logs if "event=terminal" in line]
    assert terminal_lines == [
        "OM4|v=1|kind=lifecycle|event=terminal|result=victory"
    ]


def test_each_terminal_result_is_reported_when_it_is_the_first_result() -> None:
    expected = {
        "OnVictory": "victory",
        "OnDefeat": "defeat",
        "OnDraw": "draw",
    }

    for callback, result in expected.items():
        harness = make_harness()
        brain = harness.brain()
        brain.OnCreateAI(brain, "alpha")

        getattr(brain, callback)(brain)

        assert harness.logs[-1] == (
            f"OM4|v=1|kind=lifecycle|event=terminal|result={result}"
        )


def test_destroy_delegates_and_emits_once() -> None:
    harness = make_harness()
    brain = harness.brain()
    brain.OnCreateAI(brain, "alpha")

    brain.OnDestroy(brain)
    brain.OnDestroy(brain)

    assert brain.ParentDestroyCalls == 2
    assert brain.Destroyed is True
    destroy_lines = [line for line in harness.logs if "event=destroyed" in line]
    assert destroy_lines == ["OM4|v=1|kind=lifecycle|event=destroyed"]


def test_lifecycle_never_issues_orders_queries_world_or_initializes_managers() -> None:
    harness = make_harness()
    brain = harness.brain()

    brain.OnCreateAI(brain, "alpha")
    brain.OnBeginSession(brain)
    brain.OnVictory(brain)
    brain.OnDestroy(brain)

    assert harness.forbidden_calls == []


def test_sources_do_not_import_stock_decision_brains_or_call_issue_apis() -> None:
    brain_source = source("lua/AI/Overmind4/Brain.lua")
    all_source = "\n".join(
        (
            brain_source,
            source("hook/lua/aibrains/index.lua"),
            source("lua/AI/Overmind4/Telemetry.lua"),
        )
    )

    assert "/lua/aibrain.lua" in brain_source
    assert "/lua/aibrains/base-ai.lua" not in all_source.lower()
    assert "/lua/aibrains/medium-ai.lua" not in all_source.lower()
    assert re.search(r"\bIssue[A-Za-z0-9_]*\s*\(", all_source) is None
    for forbidden in FORBIDDEN_MANAGER_CALLS:
        assert forbidden not in all_source
