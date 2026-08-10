from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lupa.lua51 import LuaError, LuaRuntime


ROOT = Path(__file__).resolve().parents[1]

PRODUCTION_LUA = (
    "mod_info.lua",
    "lua/AI/CustomAIs_v2/Overmind4.lua",
    "hook/lua/aibrains/index.lua",
    "lua/AI/Overmind4/Brain.lua",
    "lua/AI/Overmind4/Telemetry.lua",
    "lua/AI/Overmind4/Catalog.lua",
    "lua/AI/Overmind4/Policy.lua",
    "lua/AI/Overmind4/Controller.lua",
)


def production_path(relative: str) -> Path:
    path = ROOT / relative
    assert path.is_file(), f"required production Lua file is missing: {relative}"
    return path


def source(relative: str) -> str:
    return production_path(relative).read_text(encoding="utf-8")


def runtime() -> LuaRuntime:
    return LuaRuntime(unpack_returned_tuples=True)


def execute(relative: str, lua: LuaRuntime | None = None) -> LuaRuntime:
    lua = lua or runtime()
    try:
        lua.execute(source(relative))
    except LuaError as error:
        pytest.fail(f"{relative} failed to execute as Lua: {error}")
    return lua


def lua_sequence(table: Any) -> list[Any]:
    return [table[index] for index in range(1, len(table) + 1)]


@pytest.fixture
def lua_runtime() -> LuaRuntime:
    return runtime()
