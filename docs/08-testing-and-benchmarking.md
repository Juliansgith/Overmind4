# TDD, match automation, and benchmarks

The project instruction is absolute: write extensive tests, including unhappy
paths, **before** implementation code.

## Current implementation status

The registration, minimal brain, isolated single-match runner, and narrow UEF
land controller have now been implemented test-first. The first pinned live
competitive canary is documented in
[the v1 Easy result](13-v1-easy-canary.md). It is one reproducible scenario, not
a win-rate or robustness claim.

## Red-green-refactor protocol

For every behavior:

1. **Red:** write the happy-path, boundary, failure, cleanup, and determinism
   tests first.
2. Run the tests and confirm they fail because the behavior is missing/wrong,
   not because the test cannot load.
3. **Green:** implement only enough behavior to pass.
4. Run the focused tests and the relevant wider suite.
5. **Refactor:** improve names/design with all tests green.
6. Run an in-engine test if the behavior crosses an engine boundary.
7. Preserve a regression fixture for every discovered bug.

If code was written before its test, remove/revert that code and restart the
slice test-first. A mock-only green result never establishes engine semantics.

## Test pyramid

### 1. Static and registration contracts

Fast checks:

- expected files/exports and unique personality key;
- mod metadata/UID/version/dependency rules;
- hook composition does not overwrite existing keys;
- no forbidden omniscient imports in policy;
- all `Issue*` calls isolated to the command adapter;
- no OS/IO/UI/profile-time dependency in decision modules;
- configuration/schema validation;
- documentation/source-lock consistency.

### 2. Pure deterministic Lua unit tests

Use fake ports for:

- clock/tick and deterministic RNG;
- brain/economy;
- unit/entity/blueprint catalog;
- observation/recon;
- map/navigation/path errors;
- command gateway;
- logging/metrics.

Pure modules cover:

- normalization, stable keys/order and observation decay;
- economy forecast/reservation;
- role/blueprint selection;
- build-site and expansion scoring;
- goal/resource/force allocation;
- state machines;
- target/retreat scoring;
- command ownership, dedupe, timeout and recovery;
- scheduler cadence/work limits;
- metrics/result aggregation.

### 3. Engine contract and fixed-scenario tests

The game executable verifies behavior mocks cannot:

- custom AI appears and creates correct class;
- lifecycle and thread cleanup order;
- exact economy unit scaling;
- fog behavior of unit/blip/threat/reclaim queries;
- event timing/order and duplicate callbacks;
- position/build/queue semantics;
- nav return shapes and path layers;
- delayed command application;
- Sync filtering;
- deterministic replay/checksum;
- mod interoperability.

Make each scenario self-checking with structured pass/fail records and a hard
timeout. A missing terminal record is failure.

### 4. Replay regression

Version-pinned replays detect:

- Lua errors/desync;
- deterministic divergence;
- changed strategic decisions;
- performance/work-count regressions;
- compatibility with selected historical scenarios.

A replay does not exercise new live decision branches if recorded commands or
setup bypass them; classify what each replay actually validates.

### 5. Match batches

Fresh-process AI-v-AI games measure outcome and robustness across a controlled
matrix. They are slower and noisier than unit tests, so they validate rather
than replace the lower layers.

## Official FAF test assets

FAF itself uses:

- [`tests/run-syntax-test.sh`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/tests/run-syntax-test.sh);
- [`tests/run-utility-tests.sh`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/tests/run-utility-tests.sh);
- [`tests/run-blueprint-tests.sh`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/tests/run-blueprint-tests.sh);
- the bundled
  [`luft` package](https://github.com/FAForever/fa/tree/602185eb0753d205080313cc294d5665b49681cb/tests/packages);
- `faforever/lua:v5.0-1` in its CI workflow.

Reuse the compatible compiler/framework/container where practical. Do not
declare modern Lua 5.4 syntax success sufficient for FAF.

FAF's pinned `run-syntax-test.sh` is itself not dialect-complete: it skips files
using LuaPlus table-preallocation syntax because the `lua-lang` compiler does
not support that syntax. A green syntax script is valuable but not final proof
that every file will parse in the game; keep pure modules conservative and run
fresh-process engine loading tests.

## Future test layout

```text
tests/
  contracts/
    mod_metadata_spec.lua
    registration_spec.lua
    dependency_boundaries_spec.lua
  unit/
    core/
    world/
    economy/
    map/
    strategy/
    production/
    combat/
    orders/
    telemetry/
  fixtures/
    blueprints/
    maps/
    snapshots/
    events/
  engine/
    scenarios/
    assertions/
  determinism/
  harness/
```

Tests should not import production through a secret alternative path that the
game never uses. Test import mapping itself as a contract.

## Minimum extensive unit matrix

### Lifecycle and state

- repeated start, event, defeat, draw, destroy;
- callback before initialization and after terminal state;
- duplicate/out-of-order event;
- nil/dead/captured/transferred unit and a defensive possible-ID-reuse fixture;
- all retained resources cleaned.

### Observation/fairness

- visual/radar/sonar/omni/stealth/cloak/fake/stale/dead contact;
- hidden enemy absent;
- confidence/position uncertainty decay;
- opponent unit list/global rectangle forbidden;
- threat and reclaim fog regression;
- debug output filtered.

### Economy/production

- zero/full storage, negative/positive/zero trend;
- mass stall, energy stall, overflow, shock, windfall;
- reservation collision, cancellation, timeout, failure;
- paused/destroyed/captured/upgrading factory;
- unit cap boundary;
- all factions and unsupported blueprint role.

### Map/navigation

- missing/bad markers and bounds;
- connected land, separate islands, water/hover/amphibious/air;
- every path error;
- adaptive deposits;
- no expansion, unreachable expansion, unsafe expansion;
- cache invalidation/bounds.

### Strategy/combat

- no enemy, multiple enemies, ally, FFA;
- stale/uncertain composition;
- legal/illegal weapon layer;
- overkill, retreat, reinforcement, target switch hysteresis;
- commander lethal/nonlethal risk;
- no safe objective;
- tie ordering.

### Commands

- empty/mixed unit list;
- stale target;
- append/replace/preserve;
- delayed application;
- duplicate suppression;
- contention/preemption/epoch;
- build/transport/special-weapon failure phases;
- stop issuing after defeat.

### Scheduler/performance

- jobs staggered;
- bounded event storm;
- high-unit fixture;
- dirty versus periodic work;
- deterministic continuation cursor;
- wall-time variation cannot alter output;
- cache/history remain bounded.

## First implementation sequence

Each item is its own red-green-refactor slice:

1. test runner/compiler bootstrap;
2. mod metadata contract;
3. AI-list and index-hook contract;
4. minimal brain lifecycle and structured terminal log;
5. scheduler with defeat cleanup and work counters;
6. fair own-unit/economy snapshot;
7. minimal map/nav/deposit model;
8. order gateway with move/build/dedupe;
9. one tested faction opener on one pinned land map;
10. factory/engineer recovery;
11. scouting and fair enemy tracks;
12. grouped land attack/retreat;
13. repeatable stock-medium match harness;
14. expand matrix only after the narrow gate is green.

## Automation architecture

Because no supported public headless runner was found, split automation into
testable parts:

```text
Manifest generator
  -> isolated run directory/profile
  -> graphical FAF launcher/custom init
  -> fixed scenario + AI slot configuration
  -> hard sim/wall timeout and process cleanup
  -> structured log/replay collector
  -> result validator
  -> aggregate report/statistics
```

The launcher must not decide that process exit zero equals game success.
Validation requires:

- matching start and terminal records;
- expected build/config fingerprint;
- no unresolved Lua error, desync, crash, invariant failure;
- result/reason and game tick;
- replay/log present;
- timeout policy applied;
- process and temporary profile cleaned.

A diagnostic can be retained as a warning only when a valid startup lifecycle,
matching Overmind terminal result, matching official result, and completed
result payload prove the match finished. This exception exists for the observed
stock Easy platoon cleanup error after its own defeat. Startup errors,
uncorroborated errors, result conflicts, malformed results, desyncs, and runner
cleanup failures remain hard failures.

Historical
[FAF-AI-Autorun@7a948025](https://github.com/HardlySoftly/FAF-AI-Autorun/tree/7a9480250f8201980c89721c73b6e6ed3ffb52e2)
is an implementation reference only. Port behavior test-first against build
3836; do not assume `/aitest`, `/maxtime`, or `/exitongameover` exist in current
FAF without its custom init/hooks.

## Match manifest

Every run needs a machine-readable manifest:

```text
runId
campaignId
FAF commit/build/executable hash
Overmind4 commit/content/config hash
opponent repository commit/personality/cheat flag
map UID/version/content hash
seed
spawn assignment
factions and teams
victory condition
unit cap/restrictions
game speed
lobby/scenario options
sim time limit
wall time limit
active sim mods in load order
expected telemetry schema
```

Do not infer these later from a filename.

## Match metrics

Outcome:

- win/loss/draw;
- crash/desync/timeout/invariant failure;
- game tick/time and termination reason.

Economy:

- mass/energy income, storage, trend;
- stall depth/duration and overflow;
- reclaim gathered;
- spend/production efficiency;
- factory/engineer idle time;
- tech timing.

Map/control:

- mex share and retention;
- expansions built/lost;
- scout coverage/observation age;
- reachable component control.

Military:

- completed unit value by role/domain;
- kills/losses and trade value;
- army value over time;
- ACU health/risk events;
- attack/retreat outcomes.

Control/performance:

- intentions/orders/suppression/clears/retries;
- lease contention;
- scheduler work and queue depth;
- paths/cache hits;
- decision/profiler cost;
- Lua errors and invariant failures.

## Paired experimental design

RTS spawns, faction matchups, and map geometry can dominate a small sample.
Use paired runs:

- same map/seed/options;
- swap the two spawn positions;
- swap factions where the question is not faction-specific;
- interleave A/B mod versions to reduce machine/update drift;
- retain all runs, including crashes/timeouts.

When tuning a change, compare old versus candidate on the same manifest set.
Do not promote based on matches chosen after seeing results.

## Statistics

Always report numerator/denominator and failure policy, not only percentage.
For binary robust-win analysis, report a Wilson confidence interval. Draws can
also be represented as half points for score, but keep raw W/L/D and operational
failures visible.

Suggested policies:

- crash, desync, uncorroborated Lua error, missing result, or harness timeout:
  automatic operational failure and non-win;
- a post-startup Lua diagnostic with a fully corroborated terminal result:
  retain as an explicit warning and count the official result; never erase the
  diagnostic or its log;
- deliberate simulation time-limit draw: raw draw, included in score policy;
- opponent crash proven unrelated to Overmind: retain and label; rerun the pair,
  do not silently delete;
- manual/intervened/debug match: excluded from competitive sample but retained
  as diagnostic.

Predeclare:

- sample size/matrix;
- success threshold;
- confidence level;
- draw/failure scoring;
- stop rule;
- exact versions.

## Interim stock-AI gates

Easy and Normal both route to the deployed `medium-ai.lua`, so use both keys as
configuration coverage and one implementation-level opponent.

### Gate A: load

- appears in lobby;
- creates correct brain;
- no Lua error/desync;
- lifecycle terminal record and cleanup.

### Gate B: action smoke

For at least 10–20 simulated minutes:

- does not idle permanently;
- builds legal economy/production;
- creates scouts/combat units;
- issues bounded commands;
- survives ordinary missing/no-path conditions;
- no invariant/performance failure.

### Gate C: narrow competitive

One pinned small land map and one faction:

- paired spawns/seeds;
- no cheats/unrelated mods;
- at least a predeclared 20–40 game exploratory set;
- zero operational failures;
- positive, repeatable win rate against `medium-ai.lua`.

### Gate D: robust stock-medium

All four factions across a declared small/medium land-map set:

- at least 40 paired games, preferably more;
- target at least 70% raw wins initially;
- promotion-quality target at least 80% with Wilson lower confidence bound above
  50%;
- no crash/desync/invariant failure;
- performance within declared budget.

These numbers are project gates, not claims of community canon. Increase sample
size if the confidence interval is too wide.

## Long-term M28 campaign

Pin M28 repository version and select its non-cheat `AIList` personality, not
AIx/Overwhelm. "All situations" becomes a versioned corpus:

- all factions and asymmetric faction pairs;
- 5/10/20/40 km sizes;
- open, chokepoint, mixed, naval, island, generated-resource maps;
- low/normal/high reclaim;
- spawn swaps and fixed seeds;
- 1v1, teams, FFA/multiple enemies;
- standard victory variants/unit caps;
- explicitly supported unit/map mods;
- time limits and performance budgets.

Promotion requires paired A/B results against the previous Overmind, not just
some wins against M28. Diagnose losses into:

- economy;
- map control;
- information/scouting;
- composition/production;
- strategic mission selection;
- tactical execution/micro;
- commander safety;
- path/transport failure;
- CPU/scheduler failure.

The corpus and thresholds must evolve when M28 or FAF changes; old results stay
attached to their source lock.

## Regression rule

Every field bug found in logs/replays produces:

1. smallest pure or engine fixture that reproduces it;
2. failing test;
3. minimal fix;
4. focused and wider suite;
5. retained match/replay reference;
6. addition to the relevant campaign if it represents a general scenario.

No tactical improvement is accepted if it introduces fairness, determinism,
operational, or performance regressions.
