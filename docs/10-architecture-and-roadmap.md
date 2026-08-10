# Recommended architecture and roadmap

## Decision

Build Overmind4 as a custom brain with selective reuse of stable FAF primitives.
Do not use the stock builder-manager stack as the primary controller. Each
Overmind brain owns one scheduler, one world model, one economy ledger, and one
command gateway. Only immutable session map data and an explicitly allied,
fairness-checked blackboard may be shared.

## High-level flow

```text
FAF lifecycle, unit/intel callbacks, bounded fair observation queries
                           |
                           v
             Engine adapters / event normalizer
                           |
                           v
                    Fair WorldModel
            +--------------+---------------+
            |              |               |
         MapModel      EconomyModel      EnemyMemory
            +--------------+---------------+
                           |
                           v
                Goals / strategic policy
                           |
                           v
        Resource allocator and production planner
            +--------------+---------------+
            |                              |
      Mission allocator              Build intentions
            |
      Role state machines / tactical controllers
            +--------------+---------------+
                           |
                           v
           Command gateway / leases / deduplication
                           |
                           v
                       FAF Issue*

All layers -> invariants + deterministic metrics -> structured result log
```

## Dependency rule

Dependencies point inward:

```text
Pure policy/data modules
    depend on project records/interfaces only

Application coordinators
    depend on pure policy + abstract ports

FAF adapters
    implement ports and contain engine globals/userdata/Issue*

Hooks/brain
    perform composition and lifecycle only
```

Forbidden:

- pure modules importing `/lua/simInit.lua`, `ArmyBrains`, UI modules, or hooks;
- a manager calling `Issue*` directly;
- policy retaining raw engine unit/blip/platoon userdata;
- UI/debug state feeding policy;
- circular imports between economy, strategy, missions, and micro.

Enforce this with contract tests.

## Proposed module ownership

Names are provisional; contracts matter more than folders.

```text
lua/AI/Overmind4/
  Brain.lua
  Bootstrap.lua
  Config/
    Schema.lua
    Defaults.lua
  Core/
    Scheduler.lua
    Stable.lua
    Events.lua
    Invariants.lua
  Ports/
    Clock.lua
    Random.lua
    Observation.lua
    Navigation.lua
    Commands.lua
    Telemetry.lua
  Adapters/FAF/
    BrainLifecycle.lua
    ObservationAdapter.lua
    BlueprintCatalog.lua
    NavigationAdapter.lua
    CommandAdapter.lua
    TelemetryAdapter.lua
  World/
    WorldModel.lua
    OwnForces.lua
    EnemyMemory.lua
    MapModel.lua
    ReconModel.lua
  Economy/
    EconomyModel.lua
    Forecast.lua
    Ledger.lua
    Reclaim.lua
  Strategy/
    Goals.lua
    GoalEvaluator.lua
    Expansion.lua
    Composition.lua
  Production/
    Roles.lua
    Catalog.lua
    FactoryPlanner.lua
    EngineerPlanner.lua
    BuildPlacement.lua
  Missions/
    Allocator.lua
    Mission.lua
    Defense.lua
    Attack.lua
    Raid.lua
    Scout.lua
    Transport.lua
  Tactics/
    StateMachineRegistry.lua
    Land.lua
    Air.lua
    Naval.lua
    Commander.lua
    Targeting.lua
    Retreat.lua
  Execution/
    Intent.lua
    Lease.lua
    OrderBroker.lua
    Recovery.lua
  Telemetry/
    Metrics.lua
    Result.lua
```

Do not create this entire tree up front. Add each module only when a failing
test and current behavior require it. This structure prevents future dumping
everything into a few giant files; it is not a scaffolding mandate.

## Brain and bootstrap

`Brain.lua` should:

- derive from the current standard `AIBrain`;
- call parent lifecycle methods intentionally;
- mark only its own brain;
- delegate composition to a small bootstrap;
- never contain strategy;
- emit terminal lifecycle/result state once;
- stop order intake before cleanup.

`Bootstrap.lua` constructs brain-local components and their ports. No global
mutable singleton should hold per-brain strategy. Shared immutable map analysis
may be cached with explicit ownership; team sharing requires a documented
blackboard keyed by a verified alliance group/session and cleanup after the final
owning brain. Verify `IsAlly` before sharing; no-team/FFA brains receive private
keys rather than sharing a raw lobby "no team" number.

## Core scheduler

One scheduler:

- accepts jobs with cadence, phase, priority, dirty flag, and deterministic item
  budget;
- drains normalized events;
- spreads units/factories/groups across ticks;
- exposes work counters;
- stops cleanly on terminal state;
- never chooses based on elapsed wall time.

Subsystems are state machines/callable jobs, not arbitrary hidden forever
threads. Short-lived engine operations can use owned coroutines when the
contract genuinely needs waits.

## World model

The world model is the fairness boundary:

- exact own/economy state;
- legitimate allied/public data;
- current enemy sensor tracks;
- timestamped/decaying memory and inference;
- stable plain records;
- event updates plus bounded reconciliation;
- explicit unknowns and provenance.

Strategy cannot call raw brain/global queries. Debug cannot add information to
the model. Enemy observation ports expose only legitimately detected
blip/sensor evidence converted to plain records. Do not perform a full-area
`GetUnitsAroundPoint(..., 'Enemy')` scan until a version-pinned engine test proves
its visibility filtering; normal adapters should use bounded observation/recon
updates.

## Map model

Startup:

- playable bounds and terrain/water summary;
- nav generation/components for all layers;
- deposits and expansion clusters;
- start/component relations;
- coarse zones/chokes/rally candidates;
- transport/naval requirements.

Runtime overlays:

- reclaim;
- ownership/presence;
- recon age;
- threats based on fair tracks;
- objective status.

Static topology should be immutable/cached only within a topology epoch keyed
by map version, playable rectangle, deposits, and relevant scenario options.
Invalidate/rebuild when the playable area or topology epoch changes, including
campaign/scripted maps. Runtime overlays have their own bounded update cadence.

## Economy and resource allocation

The economy model normalizes static blueprint attributes once and maintains
rolling dynamic signals/forecasts. Production, consumption, assistance, pause,
completion, capture, and upgrade state update through events plus bounded
reconciliation. One ledger reserves:

- mass;
- energy/build drain;
- engineer/factory capacity;
- unit-cap headroom.

Goals submit requests with value, deadline, minimum/maximum spend, dependencies,
and cancellation rules. A deterministic allocator accepts/rejects/defer requests.
No manager independently assumes the same stored mass.

## Strategy and goals

Use goal evaluation rather than a single monolithic plan:

- survive/commander safety;
- stabilize economy;
- acquire/retain map resources;
- maintain intel;
- defend critical assets;
- pressure/raid;
- grow production/tech;
- break defenses/end game.

Each goal has:

- current utility/urgency;
- evidence/provenance;
- prerequisites;
- resource request;
- completion/failure/expiry;
- hysteresis;
- explanation telemetry.

Strategy runs relatively slowly or on meaningful dirty events. It should not
micromanage units.

## Missions and role state machines

A mission turns a strategic goal into force requirements and spatial intent.
The allocator assigns units based on role, reachability, current lease, and
opportunity cost.

Role state machines have explicit states/transitions, for example:

```text
assemble -> approach -> engage -> pursue
              |           |
              v           v
           reroute      retreat -> recover -> reassess
```

Register state machines in data/tables, not long string `elseif` dispatch.
Every state declares:

- observation inputs;
- transition guards;
- proposed intentions;
- timeout/recovery;
- cleanup;
- telemetry.

## Command gateway

The gateway is the only FAF order side effect:

- per-unit leases and epochs;
- capability/ownership/liveness validation;
- deterministic conflict resolution;
- dedupe/hysteresis/cooldowns;
- append/replace semantics;
- delayed application windows;
- timeout/stuck recovery;
- terminal cleanup and metrics.

This is a core competitive feature, not plumbing. Strong strategy is useless if
managers erase one another's commands.

## Configuration

All tunables need:

- schema and bounds;
- defaults;
- stable keys;
- version;
- content/config hash in match results;
- test fixtures at min/max/invalid values;
- no arbitrary live UI mutation of simulation decisions during benchmarks.

Separate:

- behavior weights/cadences;
- debug/telemetry settings that provably do not change decisions;
- cheat multipliers/omni, if ever implemented, in a separately named personality.

Avoid hundreds of weights before evidence. Prefer a small interpretable policy
and add a parameter only with a measurable behavior/test.

## Offline learning/optimization

External ML/optimization can participate **between** games:

```text
match corpus -> feature/result extraction -> offline training/search
-> reviewed deterministic policy/data artifact -> tests -> pinned mod build
```

Suitable artifacts:

- opening selection table;
- composition/goal weights;
- compact deterministic decision tree;
- map classifier;
- opponent-model priors.

Requirements:

- inference runs entirely in simulation Lua;
- no external live calls;
- model/data file is versioned and hashed;
- input order/numeric behavior deterministic;
- fallback exists for unknown/malformed input;
- fairness features only;
- unit and match A/B tests prove benefit.

Do not start with learning. First build the trustworthy observation, action,
test, telemetry, and automation substrate.

## Roadmap

### Phase 0: toolchain and contracts

- version-pinned Lua syntax/test runner;
- mod/AI registration tests;
- minimal brain/lifecycle/structured log;
- fixed engine smoke scenario;
- no strategy.

Exit: clean load, correct class, deterministic lifecycle, terminal cleanup.

### Phase 1: narrow self-playing controller

- scheduler;
- own unit/economy model;
- map bounds/nav/deposits;
- economy ledger;
- one faction opener;
- factory/engineer order adapter;
- invariants/metrics.

Exit: 10–20 minutes of useful legal action without Lua error, permanent idle,
unreleased reservation, or command spam.

### Phase 2: fair land combat

- recon/scout coverage and enemy memory;
- grouped land missions;
- target/retreat/commander safety;
- factory composition response;
- command leases/recovery.

Exit: repeated narrow wins against pinned `medium-ai.lua`.

### Phase 3: stock-medium robustness

- all four factions;
- more land maps/sizes/reclaim conditions;
- air scouting/defense/strike;
- T2/T3 transitions and expansion defense;
- automated paired campaign.

Exit: robust gate in [testing and benchmarking](08-testing-and-benchmarking.md).

### Phase 4: topology breadth

- transports/islands;
- naval zones/production/combat;
- mixed maps;
- generated/adaptive deposits;
- larger maps and performance scaling.

Exit: declared map-class matrix with zero operational failures.

### Phase 5: competitive adaptation

- rolling composition/outcome signals;
- mission auction/resource allocation;
- artillery/TML/nuke/experimental response;
- advanced ACU risk;
- capped high-value micro;
- team blackboard and FFA enemy selection.

Exit: positive results against progressively stronger current community AIs.

### Phase 6: M28 campaign

- pin non-cheat M28;
- build adversarial corpus;
- loss classification and targeted red tests;
- paired A/B promotion;
- performance/fairness audit on every candidate.

Exit: success thresholds per declared corpus version.

### Phase 7: corpus expansion

- additional maps/options/team modes;
- supported map/unit mods;
- newly released FAF/M28 versions;
- optional offline-learned policy artifacts.

There is no permanent "all situations" finish line. There is an expanding,
versioned set of situations with reproducible evidence.

## First code change, precisely

The next task should not be "implement the AI". It should be:

1. add a pinned test runner;
2. write failing contract tests for mod metadata, one fair AI-list entry, one
   matching index-hook key, and minimal brain lifecycle;
3. verify the failures;
4. implement the smallest files that make those tests pass;
5. add an engine smoke test proving FAF creates/destroys the brain;
6. retain structured logs.

Only after this green slice should economy or strategy code exist.
