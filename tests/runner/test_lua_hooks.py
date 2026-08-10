from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lupa.lua51 import LuaError, LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "tools" / "autorun" / "schook" / "lua" / "SinglePlayerLaunch.lua"
RESULT_HOOK = ROOT / "tools" / "autorun" / "schook" / "lua" / "ui" / "game" / "gameresult.lua"
UID = "0d46fbb2-beeb-4bde-b3c6-8bac28232a4b"


def _runtime(args: dict[str, str]) -> tuple[LuaRuntime, list[str], list[Any]]:
    lua = LuaRuntime(unpack_returned_tuples=True)
    logs: list[str] = []
    launched: list[Any] = []
    loaded_maps: list[str] = []

    scenario = lua.table_from(
        {
            "type": "skirmish",
            "Configurations": lua.table_from(
                {
                    "standard": lua.table_from(
                        {
                            "teams": lua.table_from(
                                [
                                    lua.table_from(
                                        {
                                            "name": "FFA",
                                            "armies": lua.table_from(
                                                ["ARMY_1", "ARMY_2", "ARMY_3", "ARMY_4"]
                                            ),
                                        }
                                    )
                                ]
                            )
                        }
                    )
                }
            ),
        }
    )

    def get_arg(name: str, _: int) -> Any:
        value = args.get(name)
        return lua.table_from([value]) if value is not None else None

    def default_options(name: str) -> Any:
        return lua.table_from({"PlayerName": name, "Team": 1})

    mods_by_uid = lua.table_from(
        {
            UID: lua.table_from(
                {"uid": UID, "name": "Overmind4 AI", "ui_only": False}
            )
        }
    )
    mods = lua.table_from(
        {
            "AllMods": lambda: mods_by_uid,
            "GetGameMods": lambda selected: lua.table_from([mods_by_uid[UID]])
            if selected[UID]
            else lua.table_from([]),
        }
    )
    map_utils = lua.table_from(
        {
            "LoadScenario": lambda name: (loaded_maps.append(name), scenario)[1],
            "GetExtraArmies": lambda _: lua.table_from(["EXTRA_CIV"]),
        }
    )
    prefs = lua.table_from(
        {
            "GetFromCurrentProfile": lambda _: "Harness",
            "SetToCurrentProfile": lambda *_: None,
        }
    )
    lobby = lua.table_from({"GetDefaultPlayerOptions": default_options})
    colors = lua.table_from(
        {"GameColors": lua.table_from({"PlayerColors": lua.table_from(list(range(1, 17)))})}
    )

    def importer(path: str) -> Any:
        normalized = path.lower()
        if normalized == "/lua/ui/maputil.lua":
            return map_utils
        if normalized == "/lua/mods.lua":
            return mods
        if normalized == "/lua/ui/lobby/lobbycomm.lua":
            return lobby
        if normalized == "/lua/gamecolors.lua":
            return colors
        if normalized == "/lua/user/prefs.lua":
            return prefs
        raise AssertionError(f"unexpected import: {path}")

    lua.globals().import_ = importer
    lua.execute("import = import_")
    lua.globals().LOG = lambda line: logs.append(str(line))
    lua.globals().WARN = lambda line: logs.append(str(line))
    lua.globals().HasCommandLineArg = lambda name: name in args
    lua.globals().GetCommandLineArg = get_arg
    lua.globals().FixupMapName = lambda name: f"/maps/{name}/{name}_scenario.lua"
    lua.globals().VerifyScenarioConfiguration = lambda _: None
    lua.globals().LaunchSinglePlayerSession = lambda session: launched.append(session)
    lua.globals().ForkThread = lambda callback: lua.globals().__setitem__("harness_thread", callback)
    lua.globals().WorldIsPlaying = lambda: True
    lua.globals().GetGameTimeSeconds = lambda: int(args.get("/maxtime", "1800"))
    lua.globals().SetGameSpeed = lambda speed: lua.globals().__setitem__("set_speed", speed)
    lua.globals().SessionEndGame = lambda: lua.globals().__setitem__("ended", True)
    lua.globals().math.mod = lambda left, right: left % right
    lua.globals().table.getn = lambda value: len(value)
    lua.globals().loaded_maps = loaded_maps
    return lua, logs, launched


def _valid_args(**overrides: str) -> dict[str, str]:
    values = {
        "/om4runid": "run-1",
        "/aitest": "1:overmind4:1:1,2:easy:1:2",
        "/seed": "7777",
        "/speed": "25",
        "/maxtime": "1800",
    }
    values.update(overrides)
    return values


def test_single_player_hook_is_narrow_and_not_a_wholesale_source_copy() -> None:
    source = HOOK.read_text(encoding="utf-8")

    assert len(source.splitlines()) < 300
    assert source.count("function StartCommandLineSession") == 1
    assert "SetupCampaignSession" not in source
    assert "SetupBotSession" not in source
    assert "GetRandomName" not in source
    assert "FixupMapName(mapName)" in source
    assert "VerifyScenarioConfiguration(scenario)" in source


def test_hook_executes_under_lua51_and_builds_fair_isolated_two_ai_session() -> None:
    lua, logs, launched = _runtime(_valid_args())
    lua.execute(HOOK.read_text(encoding="utf-8"))

    lua.globals().StartCommandLineSession("SCMP_007", False)

    assert len(launched) == 1
    session = launched[0]
    assert session.createReplay is True
    assert session.RandomSeed == 7777
    assert session.teamInfo[1].AIPersonality == "overmind4"
    assert session.teamInfo[2].AIPersonality == "easy"
    assert session.teamInfo[1].Human is False
    assert session.teamInfo[2].Human is False
    assert session.teamInfo[1].Team == 1
    assert session.teamInfo[2].Team == 2
    assert session.teamInfo[1].PlayerName != session.teamInfo[2].PlayerName
    assert session.teamInfo[1].PlayerColor != session.teamInfo[2].PlayerColor
    assert session.scenarioInfo.Options.FogOfWar == "explored"
    assert session.scenarioInfo.Options.CheatsEnabled == "false"
    assert session.scenarioInfo.Options.Victory == "demoralization"
    assert session.scenarioInfo.Options.TeamSpawn == "fixed"
    assert session.scenarioInfo.Options.UnitCap == "1000"
    assert len(session.scenarioMods) == 1
    assert session.scenarioMods[1].uid == UID
    civilian_names = [session.teamInfo[index].ArmyName for index in range(5, 8)]
    assert civilian_names == ["EXTRA_CIV", "ARMY_17", "NEUTRAL_CIVILIAN"]
    assert lua.globals().loaded_maps == ["/maps/SCMP_007/SCMP_007_scenario.lua"]
    assert any("OM4HARNESS|v=1|kind=start|" in line for line in logs)


def test_speed_is_set_only_by_world_thread_and_sim_timeout_ends_session() -> None:
    lua, logs, _ = _runtime(_valid_args())
    lua.execute(HOOK.read_text(encoding="utf-8"))
    lua.globals().StartCommandLineSession("SCMP_007", False)

    assert lua.globals().set_speed is None
    lua.globals().harness_thread()

    assert lua.globals().set_speed == 25
    assert lua.globals().ended is True
    assert any("|kind=speed|" in line for line in logs)
    assert any("|kind=timeout|" in line for line in logs)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("/om4runid", "../unsafe"),
        ("/aitest", "1:overmind4:1:1"),
        ("/aitest", "1:overmind4:1:1,1:easy:1:2"),
        ("/aitest", "0:overmind4:1:1,2:easy:1:2"),
        ("/aitest", "1:../../evil:1:1,2:easy:1:2"),
        ("/aitest", "1:overmind4:0:1,2:easy:1:2"),
        ("/aitest", "1:overmind4:1:0,2:easy:1:2"),
        ("/aitest", "1:overmind4:1:1,2:easy:1:1"),
        ("/seed", "not-a-number"),
        ("/speed", "0"),
        ("/speed", "101"),
        ("/maxtime", "0"),
    ],
)
def test_hook_rejects_malformed_or_out_of_range_arguments(name: str, value: str) -> None:
    lua, logs, _ = _runtime(_valid_args(**{name: value}))
    lua.execute(HOOK.read_text(encoding="utf-8"))

    with pytest.raises(LuaError):
        lua.globals().StartCommandLineSession("SCMP_007", False)

    assert any("OM4HARNESS|v=1|kind=failure|" in line for line in logs)


def test_hook_rejects_missing_required_argument() -> None:
    args = _valid_args()
    del args["/seed"]
    lua, logs, _ = _runtime(args)
    lua.execute(HOOK.read_text(encoding="utf-8"))

    with pytest.raises(LuaError):
        lua.globals().StartCommandLineSession("SCMP_007", False)

    assert any("reason=missing_arg" in line for line in logs)


def test_hook_fails_clearly_when_overmind4_mod_is_unavailable() -> None:
    lua, logs, _ = _runtime(_valid_args())
    empty = lua.table_from({})
    lua.globals().import_("/lua/mods.lua").AllMods = lambda: empty
    lua.execute(HOOK.read_text(encoding="utf-8"))

    with pytest.raises(LuaError):
        lua.globals().StartCommandLineSession("SCMP_007", False)

    assert any("reason=mod_unavailable" in line for line in logs)


def test_result_hook_logs_official_result_and_preserves_original_call() -> None:
    lua = LuaRuntime(unpack_returned_tuples=True)
    logs: list[str] = []
    calls: list[tuple[int, str]] = []
    lua.globals().LOG = lambda line: logs.append(str(line))
    lua.globals().DoGameResult = lambda army, result: calls.append((army, result)) or "kept"
    lua.globals().GetGameTimeSeconds = lambda: 321
    lua.globals().GetCommandLineArg = lambda name, _: lua.table_from(["run-1"])
    lua.execute(RESULT_HOOK.read_text(encoding="utf-8"))

    returned = lua.globals().DoGameResult(1, "victory 10")

    assert returned == "kept"
    assert calls == [(1, "victory 10")]
    assert logs == [
        "OM4HARNESS|v=1|kind=result|run=run-1|army=1|result=victory 10|sim=321"
    ]

