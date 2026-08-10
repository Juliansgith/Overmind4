from __future__ import annotations

import re

from conftest import PRODUCTION_LUA, ROOT, execute, lua_sequence, production_path, runtime, source


EXPECTED_UID = "0d46fbb2-beeb-4bde-b3c6-8bac28232a4b"


def test_every_required_production_lua_file_exists() -> None:
    for relative in PRODUCTION_LUA:
        production_path(relative)


def test_every_production_lua_file_compiles_in_conservative_lua() -> None:
    discovered = sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*.lua")
        if "tests" not in path.parts
    )
    assert discovered, "no production Lua files were found"

    lua = runtime()
    for relative in discovered:
        wrapped = "return function()\n" + source(relative) + "\nend"
        lua.execute(wrapped)


def test_mod_metadata_identifies_a_selectable_simulation_mod() -> None:
    lua = execute("mod_info.lua")
    metadata = lua.globals()

    assert metadata.name == "Overmind4 AI"
    assert metadata.uid == EXPECTED_UID
    assert metadata.version == 1
    assert isinstance(metadata.description, str) and metadata.description.strip()
    assert isinstance(metadata.author, str) and metadata.author.strip()
    assert metadata.selectable is True
    assert metadata.enabled is True
    assert metadata.ui_only is False
    assert metadata.exclusive is False


def test_mod_uid_is_a_stable_lowercase_uuid() -> None:
    lua = execute("mod_info.lua")
    uid = lua.globals().uid

    assert uid == EXPECTED_UID
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        uid,
    )


def test_mod_declares_no_dependencies_or_conflicts() -> None:
    lua = execute("mod_info.lua")
    metadata = lua.globals()

    assert lua_sequence(metadata.requires) == []
    assert lua_sequence(metadata.conflicts) == []
