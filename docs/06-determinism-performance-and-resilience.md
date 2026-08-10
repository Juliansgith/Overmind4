# Determinism, performance, and resilience

FAF is a deterministic lockstep simulation: every peer executes the same
simulation and AI code. A slow AI slows the game for everyone; a nondeterministic
AI can desynchronize the match.

## Determinism contract

Evidence: **Verified 3836** in
[`engine/Core.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Core.lua),
[`engine/Sim.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim.lua),
and
[`lua/simInit.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/simInit.lua).

Simulation decisions may use:

- `GetGameTick()`;
- `GetGameTimeSeconds()`;
- `WaitTicks()` / `WaitSeconds()`;
- FAF's deterministic `Random`;
- deterministic state derived from the pinned scenario/simulation.

Simulation decisions must not use:

- wall-clock or profiler time;
- `os`, `io`, unversioned host-filesystem state, environment variables, or
  machine name (pinned read-only resources shipped inside the mounted mod are
  ordinary code/data inputs);
- sockets, HTTP, external process/RL/LLM output;
- UI focus army, camera, selection, input timing, window state;
- unordered arrival from an external service;
- local-only debug settings;
- ordinary OS/library random generators.

`GetSystemTimeSecondsOnlyForProfileUse()` is explicitly for profiling. It may
measure cost but must never choose a build, target, route, priority, or random
branch.

All players need identical simulation mods. The
[official setup guide](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/setup/setup-english.md)
warns that one-sided simulation changes lead to desync.

## Stable ordering

Lua table/hash iteration order should not decide behavior. Even where one
specific version happens to iterate consistently on one machine, it is not a
good decision contract.

Before ranking or allocating:

1. collect candidates into an array;
2. normalize all fields;
3. compute scores without side effects;
4. sort with a complete comparator;
5. include a stable final tie-break such as project stable key/blueprint ID/
   quantized position;
6. consume a deterministic RNG value only when randomness is an explicit policy
   choice, and record the reason.

Never use pointer/userdata string representations or mutable table addresses as
tie-breaks. Quantize floating comparisons at a documented boundary if tiny
engine differences could change ordering.

## Coroutine and thread discipline

Every persistent coroutine must yield. A runaway loop freezes the simulation.

Use `brain:ForkThread` for brain-owned lifecycle work so the thread is added to
the brain's cleanup trash. Avoid one forever-thread per unit. Each extra thread
creates:

- scheduling overhead;
- hidden ordering/cadence;
- retained references after unit death;
- harder cancellation;
- harder deterministic unit testing;
- scattered CPU work.

Callbacks should enqueue work, not fork arbitrary permanent threads.

## One deterministic scheduler

Evidence: **Engineering recommendation**, informed by M28/RNGAI behavior.

One brain scheduler should own periodic work:

```text
every tick:
  drain bounded urgent events
  execute accepted due order work

staggered fast cadence:
  ACU safety, weapon opportunity, stuck/invalid command checks

medium cadence:
  economy sample, factory refill, tactical reassessment, scout assignment

slow cadence:
  own-unit reconciliation, strategy/expansion, composition, stale-memory decay

rare cadence:
  full invariants, aggregate telemetry, expensive recovery reconciliation
```

Each scheduled job declares:

- deterministic cadence and phase offset;
- priority;
- maximum items/work units per run;
- dirty/event triggers;
- continuation cursor if work spans ticks;
- cancellation/defeat behavior;
- profiling counter.

Do not make branch outcomes depend on a wall-time budget ("stop when 2 ms has
passed"). Wall time may trigger a diagnostic warning, but deterministic work
limits must be item/tick based.

## Performance model

All AI brains execute on all peers. Costs scale with:

- number of AI armies;
- units, tracks, deposits, cells, zones, goals, and managers;
- query radius/full-map scan frequency;
- target pair comparisons;
- path searches;
- command volume;
- log/`repr`/Sync volume.

High-risk patterns:

- scanning the full army or map every tick;
- querying every enemy candidate separately for every friendly unit (`O(n²)`);
- recomputing category expressions or blueprint stats in hot loops;
- pathfinding for each unit instead of grouped/strategic paths;
- sorting unchanged large candidate sets;
- repeatedly serializing deep engine tables;
- issuing identical orders each reassessment;
- full-resolution map preprocessing when a coarser topology is sufficient;
- synchronous setup that delays match start without progress/limits;
- many monitor threads waking at the same tick.

Preferred patterns:

- event-fed indexes plus bounded periodic reconciliation;
- spatial grids/zones and candidate prefiltering;
- cached blueprint facts, category expressions, nav labels, and path distances;
- dirty flags and generation numbers;
- grouped force decisions;
- staggered phases between managers and brains;
- bounded priority queues;
- incremental updates;
- order fingerprinting/deduplication;
- low-frequency aggregate logging.

## Suggested work budgets

Initial budgets are hypotheses and need profiler-backed tuning:

| Work | Initial approach |
|---|---|
| Unit callbacks | Constant-time normalize/enqueue |
| Urgent events | Bounded count per tick, preserve deterministic queue order |
| Economy sample | Every 10 ticks; rolling window |
| ACU risk | Fast cadence around active danger, slower otherwise |
| Factory refill | At most a small number of factories per tick |
| Tactical groups | Stagger groups by stable key |
| Strategy | Seconds, or dirty-triggered with cooldown |
| Own-unit reconciliation | Chunk over many ticks |
| Enemy memory decay | Bucket by expiry tick |
| Path generation | Startup once; routes on demand/cache |
| Aggregate telemetry | 10–30 seconds plus terminal result |

Do not enshrine these numbers until match/profiler evidence supports them. Make
cadences versioned config and write them to result metadata.

## Profiling without changing decisions

Use two dimensions:

- deterministic work counts: candidates visited, paths requested, orders
  proposed/issued, events processed, queue depth;
- wall-clock diagnostic samples through FAF's profiling-only timer.

The first is replay-comparable and can enforce algorithmic budgets. The second
locates actual hot functions on a test machine but may never alter behavior.

Record:

- total and max work per scheduler tick;
- per-manager calls/items;
- slowest functions/sections;
- path query count/cache hit rate;
- full/partial scans;
- command volume/suppression;
- log and Sync volume;
- live tracked objects/events/leases/reservations;
- simulation slowdown or tick wall-time percentiles in offline profiling.

Profile before optimizing. A complex custom spatial structure is not an
improvement unless it reduces measured cost without hurting decisions.

## Memory and retained state

Common leaks:

- dead unit objects held in manager tables;
- event closures retaining a brain/unit;
- old track history with no expiry;
- completed intentions/leases/reservations never removed;
- path cache with unbounded arbitrary endpoints;
- debug traces retained for the entire match;
- threads surviving defeat;
- state written as miscellaneous fields across engine unit objects.

Use module-owned tables with:

- stable keys plus generation;
- explicit insert/update/remove ownership;
- bounded histories/ring buffers;
- expiry buckets;
- cache size/age policy;
- terminal cleanup;
- periodic invariant counts.

State on raw brain/unit objects should be limited to unavoidable integration
markers and namespaced to avoid conflicts.

## Resilience rules

Every engine-facing operation can lose a race with simulation state:

- unit/target dies between observation and action;
- builder is captured, transported, paused, or assigned elsewhere;
- path endpoint becomes invalid;
- factory queue changes;
- build site becomes occupied;
- economy collapses;
- scenario has missing markers/options;
- opponent is defeated or changes;
- event is duplicated or observed after reconciliation;
- modded blueprint lacks an assumed field/category;
- match ends while work is queued.

Policy:

- nil/empty/error results are ordinary inputs;
- validate again at side-effect boundary;
- callbacks and transactions are idempotent;
- every reservation/lease has timeout and terminal release;
- recovery is bounded and cannot retry forever each tick;
- degraded behavior is explicit (alternate goal, regroup, safe idle), not crash;
- assertions classify impossible internal states and emit compact evidence;
- defeat/destroy closes the scheduler and order gateway first.

## Invariants

Cheap continuous invariants:

- one active lease per unit;
- one terminal state per intention;
- reserved resources/unit cap are nonnegative;
- no reservation belongs to a completed/canceled intent;
- owned live unit appears in at most one operational role;
- no command targets a known destroyed entity;
- policy snapshot contains no raw engine userdata;
- all enemy facts have provenance and observation tick;
- scheduler queue and per-tick work remain bounded.

Slower reconciliation invariants:

- live own-unit model matches a fair own-unit enumeration;
- factories/engineers with no role are explainable;
- all leases/reservations refer to live current-generation owners;
- map/nav components and goal assignments remain consistent;
- stale tracks expire/decay;
- terminal telemetry emitted exactly once.

In debug/test builds, invariant failure should mark the match failed even if the
AI later wins.

## Compatibility

Initial competitive baselines should target unmodified FAF units/maps. Still,
avoid unnecessary incompatibility:

- derive facts from categories/blueprints instead of hardcoded IDs;
- handle absent optional blueprint fields;
- namespace all globals/hooks/state;
- minimize hooks;
- do not replace stock/global functions for unrelated armies;
- preserve wrapped behavior for non-Overmind brains;
- declare actual dependencies/conflicts;
- test two AI mods active together;
- keep debug UI optional and non-simulation-critical.

Only claim unit-mod compatibility after a separate matrix proves it.

## Determinism/performance test gates

- same fixed input snapshot produces byte-equivalent normalized decisions;
- shuffled raw input enumeration produces the same sorted decision;
- ties resolve identically;
- fixed deterministic RNG stream is consumed in the same count/order;
- wall/profile timer changes do not change any decision;
- UI focus/camera/debug settings do not change decisions;
- repeated fixed scenario produces matching checksums/replay progression;
- no policy import/access to OS/IO/UI/global opponent brain;
- all persistent threads yield and are brain-owned;
- defeat cleans scheduler, callbacks, triggers, leases, and reservations;
- high-unit-count synthetic fixtures stay under algorithmic item budgets;
- path/blueprint/category caches are bounded and have expected hit rates;
- duplicate callback/order storms remain idempotent and bounded;
- logging/Sync disabled versus enabled yields identical simulation decisions;
- two and more AI brains use staggered work and remain deterministic.
