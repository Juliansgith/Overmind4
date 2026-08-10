# Orders, production, and unit control

FAF exposes direct simulation commands. The challenge is not finding an order
function; it is ensuring economy, strategy, tactical managers, and recovery
logic do not overwrite each other every few ticks.

## Direct order surface

Evidence: **Verified 3836** in
[`engine/Sim.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim.lua).

### Movement and formations

- `IssueMove`
- `IssueAggressiveMove`
- `IssuePatrol`
- `IssueFormMove`
- `IssueFormAggressiveMove`
- `IssueFormPatrol`
- `IssueMoveOffFactory`
- `IssueFactoryRallyPoint`

### Combat and weapons

- `IssueAttack`
- `IssueFormAttack`
- `IssueOverCharge`
- `IssueTactical`
- `IssueNuke`
- `IssueDive`
- `IssueDestroySelf`
- `IssueKillSelf`

### Construction and factories

- `IssueBuildMobile`
- `IssueBuildAllMobile`
- `IssueBuildFactory`
- `IssueUpgrade`
- `IssueSiloBuildNuke`
- `IssueSiloBuildTactical`
- `IssuePause`

### Engineer/support work

- `IssueGuard`
- `IssueFactoryAssist`
- `IssueRepair`
- `IssueReclaim`
- `IssueCapture`
- `IssueSacrifice`

### Transports and special movement

- `IssueTransportLoad`
- `IssueTransportUnload`
- `IssueTransportUnloadSpecific`
- `IssueFerry`
- `IssueTeleport`
- `IssueTeleportToBeacon`

### Queue/control primitives

- `IssueClearCommands`
- `IssueClearFactoryCommands`
- `IssueStop`
- `IssueScript`

Most group-order functions accept a unit table and return a `SimCommand` handle.
Exact target/position/formation parameters differ; consult the declaration at
the pinned source before wrapping each function.

Platoon-level commands and observations are declared in
[`engine/Sim/CPlatoon.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/CPlatoon.lua).
They include movement, attack, patrol, guard, target priorities, formation,
threat, transport/ferry, squads, plan changes, and command-status operations.
Legacy Lua platoon plans live in
[`lua/platoon.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/platoon.lua).

## Command timing and queue semantics

Important annotation details:

- additional orders generally append to the existing queue;
- `IssueClearCommands` applies immediately;
- `IssueClearFactoryCommands` clears non-build factory commands while explicitly
  preserving the build queue, allowing rally-point changes; it is not a factory
  production cancellation primitive;
- `IssuePause` is itself queued and may not apply immediately; the annotation's
  direct `Unit:SetPaused` alternative is an engine/scenario mutation, not a
  normal-AI shortcut;
- `IssueBuildFactory` can take one tick to apply;
- mobile construction orders can take at least three ticks to appear/apply;
- `IssueBuildMobile` assigns only the nearest unit in its supplied list, while
  `IssueBuildAllMobile` orders every supplied unit;
- the annotated alternative-build-location table for `IssueBuildMobile` and
  `IssueBuildAllMobile` appears not to function properly; do not depend on it
  without an engine test;
- `GetCommandQueue()` is an observation, not a proof that an order was accepted
  at the same tick it was issued;
- command completion can be checked through the returned command/platoon
  facilities such as `IsCommandDone`, where applicable.

Never implement:

```text
issue build -> inspect queue same tick -> queue absent -> issue build again
```

That creates command spam and can prevent progress. An issued intention needs a
pending grace window and explicit acceptance/timeout semantics.

FAF also contains efficient single-unit wrappers such as `IssueToUnitMove`,
`IssueToUnitMoveOffFactory`, `IssueToUnitClearCommands`, and `IssueToUnitStop`
in `lua/SimHooks.lua`. These are the four pinned wrappers; every one is
explicitly annotated as incompatible with the Steam game version. Treat each as
**Needs engine test**. Begin with declared group functions behind an adapter;
optimize only if profiling justifies it.

## Coordinate and target normalization

Order APIs are not perfectly uniform. For example:

- mobile build examples use a world vector `{x, terrainHeight, z}`;
- legacy `brain:BuildStructure` callers often use an `{x, z, 0}`-shaped build
  location;
- attack/aggressive-move accept `Unit | Vector | Prop | Blip`; tactical accepts
  `Unit | Vector`; guard accepts `Unit | Vector`; capture, repair, overcharge,
  factory-assist, and sacrifice take `Unit`; reclaim takes `ReclaimObject`;
- tactical/nuke orders can take positions;
- formation calls add formation/orientation parameters.

Use typed project records:

```text
WorldPosition { x, y, z }
BuildSite     { x, z, heading, templateContext }
EntityTarget { stableKey, observedEngineRef, observedTick }
```

Only the engine adapter converts these records to each command's expected
shape. Conversion must test terrain/surface height, playable bounds, destroyed
targets, and NaN/nil coordinates.

## Building and production APIs

Besides `IssueBuild*`, the brain surface offers:

- `CanBuildStructureAt`;
- `FindPlaceToBuild`;
- `BuildStructure`;
- `BuildUnit`;
- `DecideWhatToBuild`;
- unit-level `CanBuild`;
- unit/navigation `CanPathTo`.

The stock methods can be reused as low-level primitives, but Overmind4 should
own the decision, resource reservation, placement intent, and recovery state.
Do not run stock builder managers in parallel with a custom production
controller unless one explicitly delegates to the other.

A robust construction transaction:

1. policy proposes a need and deadline;
2. catalog resolves a faction-valid blueprint;
3. economy ledger estimates and reserves mass/energy/build power;
4. placement adapter generates valid candidates;
5. pathing checks that the builder can reach the work site;
6. arbiter leases the builder and submits one build intention;
7. event/queue reconciliation confirms start;
8. ledger converts reservation to committed spend;
9. completion/failure/cancel/capture/death releases all state;
10. recovery chooses retry, alternate builder/site, or goal abandonment.

Factory production uses the same transaction shape but distinguishes:

- queue append versus replacement;
- factory upgrade versus unit production;
- unit-cap headroom;
- assistance build power and economy;
- paused/stalled factories;
- factory destroyed/captured mid-queue;
- delayed application of factory commands.

## One order arbiter

Evidence: **Engineering recommendation**.

All managers produce **intentions**. Only one `OrderBroker` calls `Issue*`.

Suggested intention:

```text
Intent
  id
  createdTick / expiresTick
  owner                  strategic goal or manager
  priority
  unitStableKeys
  kind                   move, attack, build, reclaim, guard, ...
  target
  queueMode              replace | append | preserve
  preconditions
  completionCondition
  retryPolicy
  reason
```

Per-unit lease:

```text
Lease
  unitStableKey
  intentId
  owner
  epoch
  acquiredTick
  minimumHoldTicks
  interruptClass
```

The broker:

- validates ownership, life, completion, capability, pathing, and target;
- resolves overlapping unit sets deterministically;
- uses stable tie-break keys after priority;
- suppresses an intention identical to the current/pending one;
- distinguishes replace from append semantics;
- clears queues only when replacing incompatible work;
- records a pending window for delayed engine application;
- rate-limits retries;
- emits accepted, suppressed, rejected, timed-out, completed, and canceled
  telemetry;
- revokes leases on death, capture, attachment, defeat, or newer epoch;
- allows explicit emergency interrupts such as ACU survival.

No economy, scout, micro, recovery, or strategy module is allowed to call an
engine `Issue*` function directly. Enforce this with dependency/static contract
tests.

## Avoiding command thrash

Common failure modes:

- strategic attack sends a platoon north while micro sends units south;
- reclaim manager repeatedly interrupts a nearly completed build;
- factory manager clears an upgrade to append ordinary units;
- engineers guard each other in a cycle;
- every target-ranking tick reissues the same attack;
- a stale recovery action overwrites a newly assigned role;
- a captured unit retains the previous army's cached lease;
- duplicate events create two build reservations;
- a stuck detector fires before the engine's delayed command appears.

Controls:

- hysteresis: require a meaningful score improvement before switching;
- minimum lease durations, with documented emergency interrupt classes;
- intention fingerprints for deduplication;
- epoch numbers to invalidate old async work;
- cooldowns based on simulation ticks;
- completion/event-driven release rather than fixed sleeps where possible;
- periodic queue reconciliation;
- target validity checked at execution time, not only proposal time;
- deterministic stable ordering for simultaneous proposals.

## Platoons and force ownership

Platoons provide useful grouping, squad, formation, and command abstractions,
but they do not automatically solve ownership. Define:

- exactly one operational role per combat unit;
- whether a platoon is an engine object, a pure project grouping, or both;
- how units move between roles without receiving both old and new orders;
- how partial platoon losses affect intent;
- who owns transports, escorts, and transported cargo during an operation;
- whether the commander is ever attached to general-purpose formations;
- how a disband returns units to the unassigned pool.

The first milestone can avoid sophisticated platoon plans: group units by
reachable component and role, then have the broker issue deterministic group
commands. Introduce custom platoon plans only when tests demonstrate a need.

## Transport transaction

Transport logic needs explicit phases:

```text
requested -> transport_reserved -> cargo_reserved -> rendezvous
-> loading -> loaded -> en_route -> unloading -> released
```

Every phase needs:

- a timeout in ticks;
- destroyed/captured/detached handling;
- partial load/unload handling;
- capacity and transport-class validation;
- reachable pickup/drop zones;
- anti-air/threat policy using fair observations;
- lease handoff rules between transport and combat managers;
- a safe fallback if no transport is available.

Never leave cargo permanently leased after a failed load.

## Special weapons

Overcharge, tactical missiles, nukes, teleport, sacrifice, dive, and self-kill
orders need dedicated safety gates:

- capability/ammunition/energy availability;
- target still valid and legally observed;
- friendly-fire and commander-risk checks;
- minimum expected value;
- duplicate-fire suppression;
- projectile/travel-time prediction;
- intentional queue replacement;
- no use of hidden target position beyond legitimate memory/inference.

Do not put these into the first stock-medium milestone until basic production,
expansion, force allocation, and ordinary combat are stable.

## Command telemetry

At minimum record per match and by manager/order type:

- intentions proposed;
- orders accepted;
- duplicate orders suppressed;
- validation rejections by reason;
- queue clears;
- retries and timeouts;
- lease preemptions;
- stuck detections and recoveries;
- average ticks from proposal to engine confirmation;
- units with no role/order for longer than threshold;
- factory idle time and engineer idle time.

This is essential for distinguishing a bad strategic decision from command
contention or an engine-adapter bug.

## Mandatory order tests

Write failing tests before each adapter/broker feature:

- nil, destroyed, captured, incomplete, attached, and transported unit inputs;
- mixed-owner and mixed-capability unit lists;
- empty unit list and empty/invalid target;
- target destroyed between proposal and execution;
- position outside playable/buildable area;
- unit cannot path to build/move target;
- duplicate intent is suppressed without clearing queue;
- materially changed target replaces only when hysteresis is met;
- higher-priority emergency preempts; equal-priority ties are stable;
- old epoch cannot issue after reassignment;
- delayed build/factory command is not retried prematurely;
- timeout eventually retries or releases, with a strict maximum;
- append preserves compatible queue; replace clears exactly once;
- factory upgrade is not erased by production refill;
- build reservation releases on fail/death/capture/cancel/defeat;
- construction callback duplicated/out of order remains idempotent;
- transport full, partial load, destroyed transport, no pickup path, no drop path;
- guard/assist cycles are rejected;
- tactical/nuke order with no ammo or stale hidden target is rejected;
- all four factions resolve legal builders/products;
- command ordering and output are identical across repeated deterministic runs;
- broker stops issuing after defeat/destroy;
- no module outside the adapter imports or invokes `Issue*`.
