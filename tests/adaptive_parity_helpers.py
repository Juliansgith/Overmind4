from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lupa.lua51 import LuaError

from conftest import ROOT, runtime


DIRECTOR_ROOT = ROOT / "lua" / "AI" / "Overmind4"


def lua_value(lua: Any, value: Any) -> Any:
    if isinstance(value, dict):
        table = lua.table()
        for key, item in value.items():
            table[key] = lua_value(lua, item)
        return table
    if isinstance(value, (list, tuple)):
        table = lua.table()
        for index, item in enumerate(value, 1):
            table[index] = lua_value(lua, item)
        return table
    return value


def plain(value: Any) -> Any:
    if hasattr(value, "items"):
        keys = list(value.keys())
        if keys and all(isinstance(key, int) for key in keys):
            return [plain(value[index]) for index in sorted(keys)]
        return {key: plain(item) for key, item in value.items()}
    return value


def director_path(filename: str) -> Path:
    return DIRECTOR_ROOT / filename


def director_present(filename: str) -> bool:
    return director_path(filename).is_file()


def load_director(filename: str, global_name: str) -> tuple[Any, Any]:
    path = director_path(filename)
    if not path.is_file():
        pytest.skip(f"{filename} is not implemented yet")
    lua = runtime()
    try:
        lua.execute(path.read_text(encoding="utf-8"))
    except LuaError as error:
        pytest.fail(f"{filename} failed to execute as Lua: {error}")
    module = lua.globals()[global_name]
    assert module is not None, f"{filename} must export global {global_name}"
    return lua, module


def invoke(filename: str, global_name: str, method: str, *arguments: Any) -> Any:
    lua, module = load_director(filename, global_name)
    function = module[method]
    assert function is not None, f"{global_name}.{method} must be public"
    converted = [lua_value(lua, argument) for argument in arguments]
    return plain(function(*converted))


def intent_by_id(plan: dict[str, Any], lane_id: str) -> dict[str, Any]:
    lanes = plan.get("lanes", {})
    assert isinstance(lanes, dict), "plan.lanes must be keyed by stable lane id"
    lane = lanes.get(lane_id)
    assert isinstance(lane, dict), f"missing persistent lane {lane_id}"
    return lane
