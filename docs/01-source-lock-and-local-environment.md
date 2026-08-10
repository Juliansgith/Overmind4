# Source lock and local environment

This document records the exact machine and source state used for the research.
It prevents future debugging against the wrong executable or the wrong FAF
branch.

## Installed deployment

Evidence: **Verified 3836**, inspected 2026-08-10.

| Item | Installed value |
|---|---|
| FAF client | `2026.4.1` |
| FAF game version | `3836` |
| Active game executable | `C:\ProgramData\FAForever\bin\ForgedAlliance.exe` |
| Executable product/file version | `1.5.0.1` |
| Executable SHA-256 | `A6ACF849803F7F38FBAA612B77C910BDE239F6B5A4FF8F8786F719E2AEC0F09D` |
| Active Lua archive | `C:\ProgramData\FAForever\gamedata\lua.nx2` |
| Lua archive entries | 1,539 |
| Lua archive SHA-256 | `CEBDED703E649DCE0B7CE6B82E8E19843C08DD91EA488B3637E0985B9D51F9CA` |
| Base Steam installation | `C:\Program Files (x86)\Steam\steamapps\common\Supreme Commander Forged Alliance` |
| Mod vault | `C:\Users\DEV - PCOM\Documents\My Games\Gas Powered Games\Supreme Commander Forged Alliance\mods` |
| Overmind4 | Empty at research start; no Git metadata and no `mod_info.lua` |

`C:\ProgramData\FAForever\fa_path.lua` records `GameType = "faf"`,
`GameVersion = "3836"`, and the client/custom-vault paths. The last launch
recorded in the current `client.log` (2026-06-05) invokes the ProgramData
executable with `/init
init.lua`, `/log`, and `/savereplay`; it does **not** launch Steam's stock
`SupremeCommander.exe`.

The active `init.lua` mounts `lua.nx2`, rejects the Steam `lua.scd` from the
runtime search path, and has the old `schook.nx2` line commented out. This is
why inspection of the Steam Lua archive or an old wiki recipe can disagree with
the game that actually runs.

## Matching source snapshot

The exact source lock for deployed game build 3836 is:

| Repository | Branch | Commit | Role |
|---|---|---|---|
| FAForever/fa | `deploy/faf` | [`602185eb0753d205080313cc294d5665b49681cb`](https://github.com/FAForever/fa/tree/602185eb0753d205080313cc294d5665b49681cb) | Authoritative for installed behavior |
| FAForever/fa | `develop` | [`b14d712426fbf2a461e036bd9981c849d51d4b54`](https://github.com/FAForever/fa/tree/b14d712426fbf2a461e036bd9981c849d51d4b54) | Newer annotations/docs; verify before using behavior |

The deployed commit is dated 2026-05-16 and contains the build-3836 release
notes. All behavioral claims in this handbook prefer `602185e`; `develop` is
used when it provides richer documentation and the relevant surface is stable.

When the FAF client updates, do not silently reuse this research lock:

1. read `fa_path.lua`;
2. hash the active executable and Lua archive;
3. identify the matching `deploy/faf` commit/release notes;
4. diff the files listed in [the source index](11-api-and-source-index.md);
5. rerun registration, fairness, determinism, and order-semantics tests;
6. record a new snapshot rather than overwriting old benchmark provenance.

## Local data and diagnostic paths

| Data | Path |
|---|---|
| Game preferences | `C:\Users\DEV - PCOM\AppData\Local\Gas Powered Games\Supreme Commander Forged Alliance\Game.prefs` |
| FAF client preferences | `C:\Users\DEV - PCOM\AppData\Roaming\Forged Alliance Forever\client.prefs` |
| FAF client/game logs | `C:\Users\DEV - PCOM\AppData\Roaming\Forged Alliance Forever\logs` |
| FAF-managed replays | `C:\ProgramData\FAForever\replays` |
| Local engine `LastGame` replay | `C:\Users\DEV - PCOM\Documents\My Games\Gas Powered Games\Supreme Commander Forged Alliance\replays\sep\LastGame.SCFAReplay` |
| Documented transient FAF replay-conversion path | `C:\ProgramData\FAForever\cache\temp.scfareplay` |

The local `LastGame` file dated 2026-05-18 is not the newest retained FAF
replay; the ProgramData store contains a newer 2026-06-05 replay. The transient
`temp.scfareplay` file did not exist at inspection time. Replay filenames,
capitalization, and presence vary by launch/conversion flow.

## Baseline contamination found

At the 2026-08-10 inspection, `Game.prefs` had these simulation mods enabled:

- Smart Tactical Missiles;
- Total Mayhem;
- UnitCap x4.

They must be disabled for stock-vs-Overmind benchmarks. Simulation mods can
change blueprints, categories, unit availability, economy, projectile behavior,
or the unit cap even when they seem unrelated to AI.

Use a named clean profile or snapshot the relevant preferences before every
automated batch. A valid baseline records:

- only Overmind4, plus the opponent mod when the opponent is mod-provided, as
  active simulation mods; stock Easy/Normal needs no opponent mod;
- no UI mod that mutates or injects simulation commands;
- standard unit restrictions unless the scenario explicitly tests them;
- cheats off and the non-cheat AI personality selected;
- exact victory mode, unit cap, game speed, map version, and lobby options.

## Locally available maps and debug state

The custom map vault currently contains:

- `choke_point_40km.v0001` (four files, 58,058,488 bytes);
- `serenity_reef_5v5.v0008` (four files, 15,161,466 bytes).

Neither is an obvious narrow first 1v1 land baseline. The Steam map tree has 61
folders/345 files and should be filtered to a pinned small standard map during
the first engine-test phase. FAF's map generator is under
`C:\ProgramData\FAForever\map_generator`.

At inspection time:

- `Game.prefs` had `enable_debug_facilities = true`;
- `client.prefs` had `runFAWithDebugger = false`;
- no FAF/game process was running.

These are mutable workstation facts, not benchmark requirements. Cheats and
profiling still need a separate offline test configuration.

## Local Overmind3 prior art

An installed source-form `Overmind3` mod contains roughly 230 files and is
useful as historical local evidence, but it has no Git metadata, release
provenance, documentation, or tools directory. Its strongest reusable ideas are
conceptual:

- a very small three-surface registration boundary (`mod_info.lua`, custom-AI
  list, and brain-index hook);
- one custom brain rather than stock managers issuing competing orders;
- separation across Core, World, Economy, Strategy, Military, Tactical,
  Execution, Recovery, Data, Debug, and Config;
- many in-engine smoke checks around world state, economy, factories, power,
  mass, reclaim, storage, opening behavior, and platoons.

Do not transplant it wholesale. Known design debts to avoid in Overmind4:

- raw global `ForkThread` where `brain:ForkThread` would provide lifecycle
  cleanup;
- registering another mod's AI personality keys from within this mod;
- a large tuning surface before repeatable regression gates exist;
- modules that combine observation, decision, and command side effects;
- in-engine smoke tests whose pass/fail results are not connected to an
  installed external runner or CI gate and need harness extraction.

Overmind3 should be treated like an untracked, provenance-unverified experiment,
not an authoritative dependency or benchmark. It declares its own version/build
data, but there is no repository/release history to authenticate it.

## Clean baseline checklist

Before claiming any match result:

- [ ] FAF executable/source commit matches the recorded lock.
- [ ] Overmind4 commit or content hash is recorded.
- [ ] Opponent AI commit/version is recorded.
- [ ] All unrelated simulation mods are disabled.
- [ ] Map UID/version and scenario options are recorded.
- [ ] Seed, spawn assignment, factions, teams, and personalities are recorded.
- [ ] Cheats, shared armies, prebuilt units, and restrictions are recorded.
- [ ] Victory condition, unit cap, game speed, and time limit are recorded.
- [ ] The game log has no Lua errors, desyncs, or invariant failures.
- [ ] Replay and structured result log are retained.

## Useful read-only verification commands

These PowerShell examples inspect state; they do not launch or modify FAF:

```powershell
Get-Content 'C:\ProgramData\FAForever\fa_path.lua'
Get-FileHash 'C:\ProgramData\FAForever\bin\ForgedAlliance.exe' -Algorithm SHA256
Get-FileHash 'C:\ProgramData\FAForever\gamedata\lua.nx2' -Algorithm SHA256
Get-ChildItem "$env:APPDATA\Forged Alliance Forever\logs" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 10 Name, Length, LastWriteTime
```

Do not automate by assuming a Steam executable path. Resolve the current FAF
launch command and active archive after every update.
