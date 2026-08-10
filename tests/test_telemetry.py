from __future__ import annotations

import pytest
from lupa.lua51 import LuaError

from conftest import execute, runtime


def load_telemetry():
    lua = execute("lua/AI/Overmind4/Telemetry.lua", runtime())
    return lua, lua.globals().Telemetry


def test_format_is_versioned_deterministic_and_sorts_field_names() -> None:
    lua, telemetry = load_telemetry()
    first = lua.table()
    first["z"] = True
    first["a"] = "first"
    second = lua.table()
    second["a"] = "first"
    second["z"] = True

    assert telemetry.Format("metric", first) == "OM4|v=1|kind=metric|a=first|z=true"
    assert telemetry.Format("metric", second) == telemetry.Format("metric", first)


def test_format_escapes_delimiters_backslashes_and_control_characters() -> None:
    lua, telemetry = load_telemetry()
    fields = lua.table_from({"message": "a|b=c\nnext\r\\tab\tend"})

    line = telemetry.Format("life|cycle", fields)

    assert line == "OM4|v=1|kind=life\\pcycle|message=a\\pb\\ec\\nnext\\r\\\\tab\\tend"
    assert "\n" not in line
    assert "\r" not in line
    assert len(line.splitlines()) == 1


def test_format_preserves_false_and_numeric_scalars() -> None:
    lua, telemetry = load_telemetry()
    fields = lua.table_from({"enabled": False, "count": 0, "ratio": 1.5})

    assert telemetry.Format("metric", fields) == (
        "OM4|v=1|kind=metric|count=0|enabled=false|ratio=1.5"
    )


@pytest.mark.parametrize("bad_value", [object(), {"nested": "table"}])
def test_format_rejects_non_scalar_field_values(bad_value: object) -> None:
    lua, telemetry = load_telemetry()
    value = lua.table_from(bad_value) if isinstance(bad_value, dict) else bad_value
    fields = lua.table_from({"bad": value})

    with pytest.raises((LuaError, TypeError), match="scalar"):
        telemetry.Format("metric", fields)


def test_format_rejects_non_string_field_names() -> None:
    lua, telemetry = load_telemetry()
    fields = lua.table()
    fields[3] = "value"

    with pytest.raises(LuaError, match="field names must be strings"):
        telemetry.Format("metric", fields)


def test_reserved_fields_cannot_override_prefix_or_kind() -> None:
    lua, telemetry = load_telemetry()
    fields = lua.table_from({"v": 999, "kind": "spoofed", "event": "created"})

    assert telemetry.Format("lifecycle", fields) == (
        "OM4|v=1|kind=lifecycle|event=created"
    )


def test_emit_uses_explicit_logger_once_and_returns_the_same_line() -> None:
    lua, telemetry = load_telemetry()
    captured: list[str] = []

    line = telemetry.Emit("metric", lua.table_from({"tick": 10}), captured.append)

    assert line == "OM4|v=1|kind=metric|tick=10"
    assert captured == [line]


def test_emit_prefers_explicit_logger_over_global_logger() -> None:
    lua, telemetry = load_telemetry()
    global_lines: list[str] = []
    explicit_lines: list[str] = []
    lua.globals().LOG = global_lines.append

    telemetry.Emit("metric", lua.table(), explicit_lines.append)

    assert explicit_lines == ["OM4|v=1|kind=metric"]
    assert global_lines == []


def test_emit_is_safe_when_the_optional_logger_and_global_log_are_missing() -> None:
    lua, telemetry = load_telemetry()
    lua.globals().LOG = None

    assert telemetry.Emit("lifecycle", lua.table()) == "OM4|v=1|kind=lifecycle"


def test_lifecycle_emission_is_once_per_event_per_brain_without_mutating_fields() -> None:
    lua, telemetry = load_telemetry()
    first_brain = lua.table()
    second_brain = lua.table()
    fields = lua.table_from({"army": 2, "event": "spoofed"})
    lines: list[str] = []

    first = telemetry.EmitLifecycleOnce(first_brain, "created", fields, lines.append)
    duplicate = telemetry.EmitLifecycleOnce(first_brain, "created", fields, lines.append)
    other_brain = telemetry.EmitLifecycleOnce(second_brain, "created", fields, lines.append)

    assert first == "OM4|v=1|kind=lifecycle|army=2|event=created"
    assert duplicate is None
    assert other_brain == first
    assert lines == [first, first]
    assert fields.event == "spoofed"
