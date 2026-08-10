from __future__ import annotations

import re
from pathlib import Path

from conftest import ROOT, source


RUNTIME_MODULES = {
    "Brain.lua",
    "Telemetry.lua",
    "Catalog.lua",
    "Policy.lua",
    "Controller.lua",
}

FORBIDDEN_TEXT = (
    "ArmyBrains",
    "GetArmyBrain",
    "GetCurrentEnemy",
    "GetUnitsInRect",
    "GetEntitiesInRect",
    "GetBlueprintStat",
    "BuilderManager",
    "FactoryManager",
    "Platoon",
    "StrategyManager",
    "ExecutePlan",
    "CreateResourceBuildingNearest",
    "CreateUnitNearSpot",
    "GiveResource",
    "TakeResource",
)

ALLOWED_ISSUES = {
    "IssueBuildMobile",
    "IssueBuildFactory",
    "IssueFactoryRallyPoint",
    "IssueAggressiveMove",
    "IssueGuard",
    "IssueMove",
    "IssueReclaim",
    "IssueClearCommands",
}


def test_runtime_module_budget_is_exactly_three_new_modules() -> None:
    module_dir = ROOT / "lua" / "AI" / "Overmind4"
    assert {path.name for path in module_dir.glob("*.lua")} == RUNTIME_MODULES


def test_no_stock_decision_imports_managers_platoons_or_forbidden_intel_apis() -> None:
    combined = "\n".join(source(f"lua/AI/Overmind4/{name}") for name in sorted(RUNTIME_MODULES))
    lowered = combined.lower()
    assert "/lua/aibrains/base-ai.lua" not in lowered
    assert "/lua/aibrains/medium-ai.lua" not in lowered
    assert "/lua/ai/" not in lowered.replace("/lua/ai/overmind4/", "")
    for forbidden in FORBIDDEN_TEXT:
        assert re.search(rf"\b{re.escape(forbidden)}\b", combined) is None


def test_only_reviewed_low_level_order_surface_is_used() -> None:
    controller = source("lua/AI/Overmind4/Controller.lua")
    used = set(re.findall(r"\b(Issue[A-Za-z0-9_]+)\s*\(", controller))
    assert used <= ALLOWED_ISSUES
    assert re.search(r"IssueBuildMobile\s*\([^\n]+,[^\n]+,[^\n]+,[^\n]+\)", controller)


def test_policy_has_no_imports_engine_globals_or_side_effect_surface() -> None:
    policy = source("lua/AI/Overmind4/Policy.lua")
    assert "import(" not in policy
    for symbol in (
        "categories.",
        "GetGameTick",
        "GetTerrainHeight",
        "GetSurfaceHeight",
        "GetListOfUnits",
        "GetUnitsAroundPoint",
        "Issue",
        "LOG(",
        "WARN(",
    ):
        assert symbol not in policy


def test_controller_has_exact_engine_observation_calls() -> None:
    controller = source("lua/AI/Overmind4/Controller.lua")
    assert re.search(r"GetListOfUnits\s*\(\s*categories\.ALLUNITS\s*,\s*false\s*,\s*false\s*\)", controller)
    assert re.search(r"GetUnitsAroundPoint\s*\(\s*categories\.MOBILE\s*,[^\n]+,[^\n]+,\s*'Enemy'\s*\)", controller)


def test_reclaim_observation_is_bounded_to_live_owned_engineer_vision_rectangles() -> None:
    controller = source("lua/AI/Overmind4/Controller.lua")
    assert "GetReclaimablesInRect" in controller
    assert re.search(r"GetReclaimablesInRect\s*\(\s*rectangle\s*\)", controller)
    assert "RECLAIM_QUERY_RADIUS" in controller
    assert "MAX_RECLAIM_QUERY_ENGINEERS" in controller
    assert "MAX_RECLAIM_CANDIDATES" in controller
    assert "IsProp" in controller
    assert "GetEntitiesInRect" not in controller
    assert "GetUnitsInRect" not in controller


def test_controller_varargs_use_installed_luaplus_50_arg_semantics() -> None:
    controller = source("lua/AI/Overmind4/Controller.lua")
    assert "pcall(fn, ...)" not in controller
    assert "pcall(fn, unpack(arg))" in controller


def test_runtime_avoids_lua51_length_operator_in_installed_luaplus_50() -> None:
    for relative in (
        "lua/AI/Overmind4/Policy.lua",
        "lua/AI/Overmind4/Controller.lua",
    ):
        executable = "\n".join(
            line.split("--", 1)[0]
            for line in source(relative).splitlines()
        )
        assert re.search(r"#\s*[A-Za-z_{(]", executable) is None, relative


def test_runtime_does_not_use_missing_game_math_huge() -> None:
    for relative in (
        "lua/AI/Overmind4/Policy.lua",
        "lua/AI/Overmind4/Controller.lua",
    ):
        assert "math.huge" not in source(relative), relative
