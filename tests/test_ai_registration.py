from __future__ import annotations

from conftest import execute, lua_sequence, runtime, source


def test_custom_ai_export_has_current_v2_shape() -> None:
    lua = execute("lua/AI/CustomAIs_v2/Overmind4.lua")
    exported = lua.globals().AI

    assert lua.eval("type(AI)") == "table"
    assert exported.Name == "Overmind4"
    assert exported.Version == "1"
    assert lua.eval("type(AI.AIList)") == "table"
    assert lua.eval("type(AI.CheatAIList)") == "table"


def test_exactly_one_fair_personality_and_no_cheat_personality() -> None:
    lua = execute("lua/AI/CustomAIs_v2/Overmind4.lua")
    exported = lua.globals().AI

    fair = lua_sequence(exported.AIList)
    cheating = lua_sequence(exported.CheatAIList)

    assert len(fair) == 1
    assert cheating == []
    assert fair[0].key == "overmind4"
    assert fair[0].name == "AI: Overmind4"


def test_fair_personality_has_no_cheat_or_omni_multipliers() -> None:
    lua = execute("lua/AI/CustomAIs_v2/Overmind4.lua")
    personality = lua.globals().AI.AIList[1]

    assert personality.rating == 200
    assert personality.ratingCheatMultiplier == 0.0
    assert personality.ratingBuildMultiplier == 0.0
    assert personality.ratingOmniBonus == 0.0
    assert "cheat" not in personality.key.lower()
    assert not personality.name.lower().startswith("aix")


def test_index_hook_registers_the_imported_class_table_without_calling_it() -> None:
    lua = runtime()
    lua.execute(
        """
        keyToBrain = { existing = { marker = 'preserved' } }
        importedClass = { classMarker = 'overmind4' }
        setmetatable(importedClass, {
            __call = function()
                error('the class table must not be invoked during registration')
            end,
        })
        importedModule = { NewAIBrain = importedClass }
        """
    )
    imported_paths: list[str] = []

    def importer(path: str):
        imported_paths.append(path)
        return lua.globals().importedModule

    lua.globals().import_ = importer
    lua.globals()["import"] = importer
    lua.execute(source("hook/lua/aibrains/index.lua"))

    assert imported_paths == ["/mods/overmind4/lua/AI/Overmind4/Brain.lua"]
    assert lua.eval("rawequal(keyToBrain.overmind4, importedClass)") is True
    assert lua.globals().keyToBrain.existing.marker == "preserved"


def test_index_hook_can_extend_an_empty_registration_table() -> None:
    lua = runtime()
    lua.execute("keyToBrain = nil; importedClass = {}; importedModule = { NewAIBrain = importedClass }")
    lua.globals()["import"] = lambda _path: lua.globals().importedModule

    lua.execute(source("hook/lua/aibrains/index.lua"))

    assert lua.eval("type(keyToBrain)") == "table"
    assert lua.eval("rawequal(keyToBrain.overmind4, importedClass)") is True
