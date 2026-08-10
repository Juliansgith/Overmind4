# Debugging, telemetry, and the development loop

## Installed launch path

The last client launch recorded on 2026-06-05 used:

```text
C:\ProgramData\FAForever\bin\ForgedAlliance.exe
  /init init.lua
  /nobugreport
  /log <Roaming FAF logs>\game_<id>.log
  /gpgnet ...
  /savereplay ...
```

The recorded working directory is `C:\ProgramData\FAForever\bin`. Use the
client or first reconfirm its command line; do not launch the Steam executable
and assume it represents FAF.

The last inspected command came from a 2026-06-05 `client.log`, while the Steam
installation had newer file timestamps. Reconfirm the actual launch after a
client/game update.

## Source-development launch

FAF's
[development environment guide](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/docs/development-start-here/lua-setup.md)
uses a source-mounted launch similar to:

```text
ForgedAlliance.exe
  /init init_local_development.lua
  /EnableDiskWatch
  /showlog
  /log local-development.log
  /nomovie
```

`/debug` can enable the Lua debugger **only in a source-mounted local
development environment**. The
[AI-modding wiki](https://wiki.faforever.com/en/Development/AI/AI-Modding)
has mod-oriented launch examples, but its `/schook` and archive guidance is
partly historical. Prefer current build-3836 mount/hook behavior.

For the earliest iteration, using the installed FAF deployment and ordinary mod
folder is lower setup cost. Move to a source-mounted development tree when:

- source stepping/hot reload becomes important;
- engine/framework changes must be tested;
- automated scenario hooks need a controlled init;
- exact source and binary provenance can still be pinned.

## Logs

Observed directory:

`C:\Users\DEV - PCOM\AppData\Roaming\Forged Alliance Forever\logs`

Useful simulation log functions:

- `LOG`;
- `WARN`;
- `SPEW`;
- `repr` for small controlled structures.

F9 opens the log window. The console command surface also includes `LOG`,
`SimLog`, and `SimWarn`.

Avoid deep `repr` on brains, units, blueprints, or world tables. It is expensive,
huge, and may recurse through engine objects. Log flat, versioned records.

### Proposed structured line format

```text
OM4|v=1|kind=match_start|tick=0|faf=3836|om4=<hash>|map=<uid>|seed=<seed>|...
OM4|v=1|kind=metric|tick=600|mass_income_ps=...|orders_issued=...|...
OM4|v=1|kind=invariant|tick=721|name=one_lease_per_unit|ok=0|detail=...
OM4|v=1|kind=match_end|tick=...|result=win|reason=victory|errors=0|...
```

Requirements:

- one physical line per record;
- fixed prefix and schema version;
- escaped/whitelisted scalar values;
- stable field names/order where practical;
- match/config fingerprint on start/end;
- terminal record exactly once from victory/defeat/draw/timeout;
- rate-limited periodic metrics;
- no download URLs, GPGNet credentials, HMAC parameters, personal/session data,
  or chat contents.

The FAF logs can contain signed URLs and player/session information. Redact
before publishing a full log.

## Getting data out

Preferred order:

1. structured simulation log lines;
2. replay plus pinned configuration;
3. optional small filtered `Sync` diagnostics to an in-game UI;
4. post-match external parsing/aggregation.

`Sync` is transferred every simulation beat and custom fields are transient.
Use it for overlays/inspectors, not bulk telemetry. UI listeners can register
through `AddOnSyncCallback`/hashed variants in
[`lua/UserSync.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/UserSync.lua).

Never alter `GameResult`, `StatsToSend`, `JsonStats`, or `GpgNetSend`. The FAF
source treats result/stat manipulation as rating/game manipulation. Overmind4
emits its own namespaced record and reads official result state without
rewriting it.

## Lua debugger

The
[official debugger guide](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/docs/development-start-here/lua-debugger.md)
explicitly says the debugger is not functional in any FAF Client game type. In
a local development environment it documents:

- Alt+F9;
- `SC_LuaDebugger`;
- `/debug`.

Do not expect Alt+F9, `SC_LuaDebugger`, or `/debug` to work in an ordinary
client-launched FAF match. In the source-mounted local environment, breakpoints
make the game effectively unplayable until removed. Inspect small state; do not
mutate decision variables and then use that replay as benchmark evidence.

## Console and debug hotkeys

The
[console command reference](https://wiki.faforever.com/en/Development/Console_Commands)
and deployed key maps expose a broad surface. Useful local-only commands/groups:

- `~`: console;
- `CON_ListCommands`;
- `SimLua` / `UI_Lua`;
- F9 log window;
- Alt+F2 entity creation/take-control cheat dialog;
- `ShowStats`, `ShowArmyStats`, `ren_ShowNetworkStats`;
- navigation/path/IMAP/recon debug commands;
- AI debug windows for bases, platoons, economy, reclaim, recon, and presence;
- `WLD_SingleStep`, `WLD_AdvanceBeat`, and accelerated simulation commands;
- select/debug-unit commands.

The exact command names and cheat requirements can change; use
`CON_ListCommands` and the pinned `lua/keymap` source.

Any command that creates/takes units, changes speed/cheats, exposes full intel,
or mutates simulation invalidates a competitive result. Keep diagnostic and
benchmark profiles separate.

## Profiling

Current profiler sources:

- [`lua/ui/game/Profiler.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/ui/game/Profiler.lua)
- [`lua/sim/Profiler.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/sim/Profiler.lua)
- [`lua/shared/Profiler.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/shared/Profiler.lua)
- [`lua/keymap/debugKeyActions.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/keymap/debugKeyActions.lua)

The installed UI requires `CheatsEnabled == "true"` for the profiler. It uses
debug hooks and synchronizes data frequently, so it adds overhead. The key
description explicitly warns that profiler abuse is bannable.

Use only:

- offline/local games;
- isolated performance investigations;
- a clean baseline and a second run without profiler overhead;
- profiling time as diagnostics, never decision input.

M28's
[`M28Profiler.lua`](https://github.com/maudlin27/M28AI/blob/e56ed8734d0cef15d228be42d962a28cadc94578/lua/AI/M28Profiler.lua)
is useful inspiration for per-function/per-tick accounting, but its license
precludes casual copying and Overmind4 should design an independent minimal
profiler.

## Hot reload

`/EnableDiskWatch` and development source mounts shorten the edit/test loop.
However, hot reload is not clean process isolation:

- an imported module may remain cached;
- existing class instances retain old metatables/closures;
- upvalues retain prior code/state;
- existing threads keep running the old body;
- hooks may only concatenate on first import;
- blueprint changes often require full session restart.

Use hot reload for exploratory local debugging. Restart the match/process for
any regression or benchmark claim.

The wiki's
[mod test loop](https://wiki.faforever.com/en/Development/Modding/Mod-test-loop)
describes interactive reload techniques; it is not a substitute for automated
fresh-process tests.

## Replays

Observed:

- FAF `.fafreplay` store: `C:\ProgramData\FAForever\replays`;
- local engine last replay:
  `C:\Users\DEV - PCOM\Documents\My Games\Gas Powered Games\Supreme Commander Forged Alliance\replays\sep\LastGame.SCFAReplay`;
- documented transient FAF engine replay-conversion path (not present at the
  2026-08-10 inspection):
  `C:\ProgramData\FAForever\cache\temp.scfareplay`.

A `.fafreplay` has JSON metadata followed by an encoded payload; an
`.SCFAReplay`/`.scfareplay` is the engine replay. Do not build a parser by
assuming this observed framing is a stable public API.

The
[official setup guide](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/setup/setup-english.md)
describes launching a replay through the client, obtaining
`temp.scfareplay`, and checking out the matching deploy branch.

Replays store deterministic inputs, not portable save states. Playback needs
matching:

- FAF game source/build;
- map and version;
- every simulation mod and version;
- relevant lobby/scenario configuration.

Retain the structured result log alongside the replay because replay playback
alone is an expensive way to extract batch metrics.

## Crash analysis

[FADeepProbe](https://github.com/FAForever/FADeepProbe) is the FAF community tool
for deeper crash traces. First distinguish:

- ordinary Lua traceback in game log;
- invariant/test failure;
- desync/checksum failure;
- engine crash;
- automation/launcher failure;
- timeout/hung simulation.

Never count a crash, desync, missing terminal record, or harness timeout as a
draw that disappears from win-rate statistics.

## Match automation status

No current installed autorun directory/harness was found. Current public FAF
source has a `/map` single-player launch path, but it is oriented around a human
slot plus rush AIs and is not a documented arbitrary AI-v-AI batch runner.

Historical reference:

[HardlySoftly/FAF-AI-Autorun@7a948025](https://github.com/HardlySoftly/FAF-AI-Autorun/tree/7a9480250f8201980c89721c73b6e6ed3ffb52e2)

It used a custom init/autorun archive, graphical instances, result-log parsing,
and options such as:

```text
/nobugreport /nosound /exitongameover
/init init_autorun.lua
/map <scenario>
/log <file>
/maxtime <seconds>
/aitest <slot>:<personality>:<faction>:<team>
```

The repository is old (last active around 2022), and current build 3836 does
not expose those AI-test switches by itself. Use it only as a design seed. A
new/ported harness must be developed under tests and verified against the exact
current init, launch, result, timeout, cleanup, and replay behavior.

No supported public true-headless/dedicated simulation runner was found. Likely
automation is graphical executable control, custom scenario/init hooks,
acceleration, structured logs, and optionally several isolated instances.

## Local tooling gap

At research time, Git, Python, VS Code, PowerShell 5, and `tar` are available.
No Lua/LuaJIT, StyLua, Selene, or Lua Language Server is on `PATH`.

FAF's dialect is nonstandard, so installing an arbitrary latest Lua is not
enough. Prefer:

- FAF's official Lua compiler/container for syntax;
- the bundled `luft` framework or a compatible conservative pure-Lua runner;
- the
  [FA Lua VS Code extension](https://github.com/FAForever/fa-lua-vscode-extension/releases)
  for language tooling;
- adapters/mocks that keep pure policy modules portable.

Tool bootstrap belongs to the next TDD phase and should be version-pinned.

## Daily development loop

1. Choose one behavior and write extensive failing unit/contract tests.
2. Run them and verify failure is for the intended missing behavior.
3. Add the smallest production change.
4. Run unit/syntax/contract tests.
5. Refactor while green.
6. Run a fresh-process fixed in-engine scenario.
7. Check structured logs, errors, invariants, deterministic work metrics.
8. Retain replay/result for changed decision behavior.
9. Run the relevant regression batch.
10. Only then update benchmark history.
