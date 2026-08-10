# API and source index

This is the quick lookup map. The linked commit is authoritative for installed
build 3836 unless marked otherwise.

## Local source of truth

| Item | Location |
|---|---|
| Active FAF init | `C:\ProgramData\FAForever\bin\init.lua` |
| Active current Lua | `C:\ProgramData\FAForever\gamedata\lua.nx2` |
| Installed build metadata | `C:\ProgramData\FAForever\fa_path.lua` |
| Exact public source | [`FAForever/fa@602185e`](https://github.com/FAForever/fa/tree/602185eb0753d205080313cc294d5665b49681cb) |
| Richer current annotations/docs | [`FAForever/fa@b14d712`](https://github.com/FAForever/fa/tree/b14d712426fbf2a461e036bd9981c849d51d4b54) |

Do not substitute:

- Steam's `lua.scd`;
- an overlapping `schook.nx2`;
- an old `faforever.faf`;
- current `develop` behavior without diffing;
- an old AI wiki archive path.

The runtime source is distributed as an archive; source extraction is for
read-only reference. The public `deploy/faf` commit is easier to search and
line-link.

## Runtime and mod loading

| Question | Source |
|---|---|
| Which Lua contexts exist? | [`docs/development-start-here/lua-contexts.md`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/docs/development-start-here/lua-contexts.md) |
| Which Lua dialect/restrictions? | [`lua-syntax.md`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/docs/development-start-here/lua-syntax.md) |
| How are FAF archives/mod folders mounted? | [`init_faf.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/init_faf.lua), installed `bin\init.lua` |
| Mod metadata format? | [`lua/MODS.LUA`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/MODS.LUA) |
| Enabled mod sorting/hooks? | [`lua/MODS.LUA`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/MODS.LUA) |
| Custom AI lobby discovery? | [`lua/ui/lobby/aitypes.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/ui/lobby/aitypes.lua) |
| Personality -> brain class? | [`lua/aibrains/index.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/aibrains/index.lua) |
| Army creation/session order? | [`lua/simInit.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/simInit.lua) |
| Brain class/callback implementation? | [`lua/aibrain.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/aibrain.lua) |
| Lobby options? | [`lua/ui/lobby/lobby.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/ui/lobby/lobby.lua) |
| Tooltips? | [`lua/ui/game/tooltip.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/ui/game/tooltip.lua) |

## Engine declaration surfaces

Files under `engine/` are annotated declarations for native engine methods.
They are the best signature index, not the implementation.

| Surface | Source |
|---|---|
| Global sim queries/orders | [`engine/Sim.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim.lua) |
| Core threads/time/random/categories | [`engine/Core.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Core.lua) |
| Brain methods | [`engine/Sim/CAiBrain.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/CAiBrain.lua) |
| Entity methods | [`engine/Sim/Entity.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/Entity.lua) |
| Unit methods | [`engine/Sim/Unit.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/Unit.lua) |
| Platoon methods | [`engine/Sim/CPlatoon.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/CPlatoon.lua) |
| Recon blips | [`engine/Sim/ReconBlip.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/ReconBlip.lua) |
| Navigator methods | [`engine/Sim/CAiNavigatorImpl.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/CAiNavigatorImpl.lua) |
| Weapon methods | [`engine/Sim/UnitWeapon.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/UnitWeapon.lua) |
| Unit blueprint schema | [`engine/Core/Blueprints/UnitBlueprint.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Core/Blueprints/UnitBlueprint.lua) |
| Engine enums | [`engine/Enums.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Enums.lua) |

## Brain quick reference

### Identity and opponent

- `GetArmyIndex`
- `GetArmyStartPos`
- `GetFactionIndex`
- `GetPersonality`
- `GetCurrentEnemy`
- `SetCurrentEnemy`
- `GetNoRushTicks`
- `GetMapWaterRatio`
- `IsOpponentAIRunning`

### Units and platoons

- `GetCurrentUnits`
- `GetListOfUnits` — **ignores intel; own units only in fair AI**; deployed
  annotation also marks `requireBuilt` apparently nonfunctional
- `GetUnitsAroundPoint` — takes intel into account
- `GetNumUnitsAroundPoint`
- `FindUnit`, `FindUnitToUpgrade`, `FindUpgradeBP`
- `MakePlatoon`, `AssignUnitsToPlatoon`, `BuildPlatoon`
- `GetPlatoonsList`, `GetPlatoonUniquelyNamed`
- `DisbandPlatoon`, `PlatoonExists`
- available factory/current-building helpers

### Economy and statistics

- `GetEconomyIncome`
- `GetEconomyRequested`
- `GetEconomyStored`
- `GetEconomyStoredRatio`
- `GetEconomyTrend`
- `GetEconomyUsage`
- `GetArmyStat`, `GetBlueprintStat`
- current units/unit counts

Methods such as `GiveResource`, `TakeResource`, `GiveStorage`, `SetArmyStat`, and
resource-sharing setters are scenario/cheat/control surfaces, not legitimate
normal-AI economy actions. Do not call them in Overmind4's fair personality.

### Threat

- `GetThreatAtPosition`
- `GetThreatBetweenPositions`
- `GetThreatsAroundPosition`
- `GetHighestThreatPosition`
- `AssignThreatAtPosition`
- attack-vector helpers

Enemy threat fog semantics: **Needs engine test**.

### Building

- `CanBuildStructureAt`
- `FindPlaceToBuild`
- `DecideWhatToBuild`
- `BuildStructure`
- `BuildUnit`
- `CanBuildPlatoon`

Creation methods such as `CreateUnitNearSpot`/`CreateResourceBuildingNearest`
are scenario/cheat primitives and forbidden for the normal AI.

The same rule applies to global destructive/cheat helpers such as
`SallyShears`, direct entity/unit setters, and debug spawn/take-control commands:
their presence in simulation code does not make them legal AI actions.

## Entity/unit quick reference

### Safe observations

- life/progress: `BeenDestroyed`, `GetFractionComplete`, `IsBeingBuilt`;
- type/identity: `GetBlueprint`, `GetUnitId`, `GetEntityId`, `GetArmy`,
  `GetAIBrain`;
- geometry: `GetPosition`, `GetPositionXYZ`, `GetHeading`, `GetOrientation`,
  `GetVelocity`;
- health: `GetHealth`, `GetMaxHealth`, shield ratio;
- orders/work: `GetCommandQueue`, `GetFocusUnit`, `GetTargetEntity`,
  `GetWorkProgress`, `GetNumBuildOrders`;
- movement: `GetCurrentLayer`, `GetCurrentMoveLocation`, `GetNavigator`,
  `CanPathTo`, `CanPathToRect`, `IsMoving`, `IsIdleState`;
- capabilities: `CanBuild`, command/toggle caps, weapon methods;
- economy: build rate, consumption/production, resource consumed;
- logistics: guards, cargo, transport space, fuel, rally;
- weapons/silos: weapon count/access, nuke/tactical ammo;
- generic `IsUnitState`.

### Direct mutation warning

Entity/unit declarations also expose setters for health, position, production,
speed, build rate, ammo, intel, validity, stun, collision, and many other
properties. Those exist for game/scenario/unit implementation. Calling them to
improve the AI would be cheating and can break simulation invariants. A normal
AI observes unit state and acts through legal orders/capabilities.

## Complete group-order list for build 3836

From
[`engine/Sim.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim.lua#L743-L1021):

```text
IssueAggressiveMove
IssueAttack
IssueBuildFactory
IssueBuildMobile
IssueBuildAllMobile
IssueCapture
IssueClearCommands
IssueClearFactoryCommands
IssueDestroySelf
IssueDive
IssueFactoryAssist
IssueFactoryRallyPoint
IssueFerry
IssueFormAggressiveMove
IssueFormAttack
IssueFormMove
IssueFormPatrol
IssueGuard
IssueKillSelf
IssueMove
IssueMoveOffFactory
IssueNuke
IssueOverCharge
IssuePatrol
IssuePause
IssueReclaim
IssueRepair
IssueSacrifice
IssueScript
IssueSiloBuildNuke
IssueSiloBuildTactical
IssueStop
IssueTactical
IssueTeleport
IssueTeleportToBeacon
IssueTransportLoad
IssueTransportUnload
IssueTransportUnloadSpecific
IssueUpgrade
```

The annotations note that the alternative-location table parameter of
`IssueBuildMobile`/`IssueBuildAllMobile` appears not to work properly.

`IsCommandDone(SimCommand)` in the same engine file is the corresponding
completion query. Its basic signature is declared, but command rejection,
cancellation, and destroyed-owner behavior still need in-engine adapter tests.

FAF-only single-unit optimized wrappers in
[`lua/SimHooks.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/SimHooks.lua):

- `IssueToUnitMove`;
- `IssueToUnitMoveOffFactory`;
- `IssueToUnitClearCommands`;
- `IssueToUnitStop`.

All four are explicitly annotated as incompatible with the Steam game version.
Validate them in the installed FAF engine and hide them behind the command
adapter.

## Global simulation quick reference

Common observations:

- `GetGameTick`, game-time functions;
- `GetArmyBrain`, `GetEntityById`;
- `GetUnitsInRect`, `GetEntitiesInRect`, `GetReclaimablesInRect`;
- `GetTerrainHeight`, `GetSurfaceHeight`, `GetMapSize`;
- blueprint lookup;
- ally/enemy relationship helpers.

Global rectangle queries do not promise a fair filtered enemy view. Ban them
from enemy observation. Use them only behind a reviewed adapter for own,
neutral, public, or debug purposes.

## Time, threads, random, and categories

From `engine/Core.lua` and `lua/simInit.lua`:

- `ForkThread`, `KillThread`;
- `WaitTicks`, `WaitSeconds`;
- `GetGameTimeSeconds`;
- deterministic `Random`;
- category parsing/filtering/containment/list helpers.

Profile-only wall time is declared in `engine/Sim.lua`; never branch on it.

## Navigation and spatial data

| Surface | Source |
|---|---|
| Modern nav | [`lua/sim/NavUtils.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/sim/NavUtils.lua) |
| Nav layers/generator | [`lua/shared/NavGenerator.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/shared/NavGenerator.lua) |
| Map markers | [`lua/sim/MarkerUtilities.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/sim/MarkerUtilities.lua) |
| Legacy safe paths/graphs | [`lua/AI/aiattackutilities.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/aiattackutilities.lua) |
| Reclaim grid | [`lua/AI/GridReclaim.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/GridReclaim.lua) |
| Recon grid | [`lua/AI/GridRecon.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/GridRecon.lua) |
| Presence grid | [`lua/AI/GridPresence.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/GridPresence.lua) |
| Assignment grid | [`lua/AI/GridBrain.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/GridBrain.lua) |
| Deposit grid | [`lua/AI/GridDeposits.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/GridDeposits.lua) |

Nav layers: `Land`, `Water`, `Amphibious`, `Hover`, `Air`.

Core `NavUtils` calls:

```text
IsGenerated / Generate
CanPathTo / CanPathToCell
DetailedPathTo / PathTo / PathToWithThreatThreshold
GetLabel / GetTerrainLabel / GetLabelMetadata / IMAP label helpers
positions/cells in radius
DirectionsFrom / threat-filtered directions
RandomDirectionFrom / RetreatDirectionFrom / DirectionTo
IsInPlayableArea / IsInBuildableArea
```

## Events and triggers

| Surface | Source |
|---|---|
| Brain unit/intel/lifecycle events | [`lua/aibrain.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/aibrain.lua) |
| Scenario triggers | [`lua/scenariotriggers.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/scenariotriggers.lua) |
| Scenario helpers | [`lua/ScenarioFramework.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/ScenarioFramework.lua) |
| Lua unit callbacks | [`lua/sim/Unit.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/sim/Unit.lua) |

Prefer brain-forwarded events. Add unit hooks only for a demonstrated missing
event.

## UI/simulation communication

| Direction | Source | Rule |
|---|---|---|
| UI -> sim | [`engine/User.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/User.lua), [`lua/SimCallbacks.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/SimCallbacks.lua) | Validate every argument and ownership |
| Sim -> UI | [`lua/SimSync.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/SimSync.lua), [`lua/UserSync.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/UserSync.lua) | Filter by focus army; transient/rate-limited |

AI decisions and normal orders need neither path; they stay simulation-side.

## Debugging/testing

| Need | Source |
|---|---|
| Development source mount | [`lua-setup.md`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/docs/development-start-here/lua-setup.md) |
| Lua debugger | [`lua-debugger.md`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/docs/development-start-here/lua-debugger.md) |
| Key actions | [`lua/keymap/debugKeyActions.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/keymap/debugKeyActions.lua) |
| Profiler | [`lua/ui/game/Profiler.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/ui/game/Profiler.lua), [`lua/sim/Profiler.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/sim/Profiler.lua) |
| Syntax/unit/blueprint tests | [`tests`](https://github.com/FAForever/fa/tree/602185eb0753d205080313cc294d5665b49681cb/tests) |
| Console command catalog | [FAF wiki](https://wiki.faforever.com/en/Development/Console_Commands) |
| Interactive mod loop | [FAF wiki](https://wiki.faforever.com/en/Development/Modding/Mod-test-loop) |
| Crash tracing | [FADeepProbe](https://github.com/FAForever/FADeepProbe) |
| Historical match automation | [FAF-AI-Autorun@7a948025](https://github.com/HardlySoftly/FAF-AI-Autorun/tree/7a9480250f8201980c89721c73b6e6ed3ffb52e2) |

The Lua debugger is functional only in a source-mounted local development
environment, not in FAF Client game types.

## Reference AI source index

| Project | High-value paths |
|---|---|
| M28 | `M28Brain`, `M28Events`, `M28Overseer`, `M28Map`, `M28Economy`, `M28Factory`, `M28Orders`, `M28Micro`, `M28Profiler` |
| RNGAI | `rng-ai.lua`, `BuilderFramework`, `StateMachines`, `IntelManagement`, `FlowAI/framework/mapping`, `AIBuilders` |
| Uveso | `aiarchetype-managerloader`, `AIMarkerGenerator`, `AITargetManager`, builder directories |
| Mini27 | `mod_info`, custom AI list, brain index hook, `M27Brain`, `M27Map`, unit/sim hooks |
| Secondary/history | AI-Swarm, DilliDalli, MicroAI, Sorian-Edit, LOUD, and FAF-AI-Autorun pins are cataloged in the AI study |

Use the exact pins and licensing rules in
[the AI study](09-existing-ai-study.md).

## How to verify a new API assumption

1. Search the exact `deploy/faf` source for declaration and current callers.
2. Read the engine annotation plus the Lua wrapper/caller.
3. Check whether it is sim, UI, initialization, or blueprint context.
4. Identify intel, cheat, deterministic, ownership, and lifecycle implications.
5. Write a failing mock contract test.
6. Write a controlled in-engine test for undocumented semantics.
7. Log source commit and observed result.
8. Only then expose it through a narrow adapter.
