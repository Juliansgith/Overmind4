# Overmind4 AI research handbook

Research snapshot: **2026-08-10**

This directory is the technical foundation for Overmind4, a non-cheating
Forged Alliance Forever simulation AI. The immediate target is to defeat FAF's
standard Easy/Normal opponent reliably. The long-term target is a deliberately
defined, version-pinned benchmark against M28 rather than the literally
unbounded phrase "all situations".

No AI implementation has been started yet. That is intentional: the next phase
must begin with failing tests for the smallest registration and brain-lifecycle
slice, then add only enough production code to pass them.

## What we know now

- The installed game is FAF game build **3836**, backed by
  [`FAForever/fa@602185e`](https://github.com/FAForever/fa/tree/602185eb0753d205080313cc294d5665b49681cb).
- A distributable AI runs as Lua inside FAF's deterministic simulation. It can
  inspect simulation state and call the `Issue*` APIs directly.
- The simulation sandbox can load mounted game/mod resources through FAF's
  virtual resource APIs, but has no general arbitrary-host `io`/`os`, process,
  socket, HTTP, Python, LLM, or writable external reinforcement-learning
  control channel. External tools can launch matches and read result logs, but
  decisions themselves must be in-process and deterministic.
- A normal/fair AI must respect fog of war. In particular,
  `GetListOfUnits` ignores intel and therefore must not be used to enumerate
  enemy armies; `GetUnitsAroundPoint` does respect intel.
- In the deployed build, both lobby personality keys `easy` and `medium` select
  `lua/aibrains/medium-ai.lua`. They remain separate registration/benchmark
  cases, but they are not two distinct stock brain classes.
- The strongest long-term design is a custom brain with a pure decision core,
  thin FAF adapters, event-fed state, one scheduler, one economy reservation
  ledger, and one order arbiter.
- Public sources are sufficient to begin. Discord access is not currently a
  blocker; it will be most valuable for undocumented threat/intel behavior and
  community match-automation tooling.

## Reading order

1. [Source lock and local environment](01-source-lock-and-local-environment.md)
2. [Runtime, mod loading, and AI entry points](02-runtime-mod-loading-and-entrypoints.md)
3. [Observation, world model, and fair play](03-observation-world-model-and-fair-play.md)
4. [Orders, production, and unit control](04-orders-production-and-control.md)
5. [Navigation, economy, and combat surfaces](05-navigation-economy-and-combat.md)
6. [Determinism, performance, and resilience](06-determinism-performance-and-resilience.md)
7. [Debugging, telemetry, and the development loop](07-debugging-telemetry-and-development.md)
8. [TDD, match automation, and benchmarks](08-testing-and-benchmarking.md)
9. [Existing AI study and licensing](09-existing-ai-study.md)
10. [Recommended architecture and roadmap](10-architecture-and-roadmap.md)
11. [API and source index](11-api-and-source-index.md)
12. [Open questions and Discord checklist](12-open-questions-and-discord-checklist.md)

## Evidence labels

Every important assertion should be read with one of these evidence levels:

| Label | Meaning |
|---|---|
| **Verified 3836** | Confirmed in the installed files and/or the exact deployed FAF commit |
| **Current upstream** | Confirmed in a pinned public repository snapshot, but not necessarily installed |
| **Community guidance** | Documented by the FAF wiki or established project practice |
| **Engineering recommendation** | A project design decision derived from the evidence |
| **Needs engine test** | The public declarations or behavior are incomplete/ambiguous |

The annotated files under FAF's `engine/` directory document the callable
surface, not the C++ engine implementation. A declared method can still be
deprecated, incomplete, or behave differently at an edge. Any behavior used as
a correctness, fairness, or determinism boundary needs an in-engine regression
test.

## Project principles

1. **Test first.** For every feature, write an extensive failing test set before
   implementation. A test that passed before the change does not prove the new
   behavior.
2. **Fair by construction.** Observation adapters expose only information the
   AI is allowed to know. Policy code cannot reach global omniscient queries.
3. **Deterministic by construction.** Simulation decisions use ticks and FAF's
   deterministic RNG, never wall time or external state.
4. **One owner per side effect.** Managers propose intentions; only the order
   arbiter issues commands, and only the economy ledger commits resources.
5. **Measure before optimizing.** Establish tick-cost and match baselines, then
   optimize the measured bottleneck.
6. **Pin every result.** A win rate without the game, AI, mod, map, seed, spawn,
   faction, and lobby-option versions is not a reproducible result.
7. **Independent implementation by default.** Study other AIs, but do not copy
   code whose license is absent or incompatible.

## Scope of this research

Covered:

- mod discovery, hook mechanics, custom AI registration, and brain lifecycle;
- game-state, economy, intel, blueprint, map, threat, navigation, and event APIs;
- direct unit, factory, platoon, build, transport, tactical, and strategic orders;
- deterministic simulation constraints and UI/simulation communication;
- logging, debugging, profiling, replays, test frameworks, and automation options;
- architecture, performance, robustness, licensing, and milestone benchmarks.

Not yet proven:

- exact fog-of-war semantics of every threat and reclaim query;
- stability of all FAF-only single-unit `IssueToUnit*` wrappers;
- a current supported true-headless match runner;
- replay binary parsing as a stable result API;
- a canonical community definition of "beats M28 in all situations".

Those gaps have explicit test or Discord questions in
[the open-questions document](12-open-questions-and-discord-checklist.md).
