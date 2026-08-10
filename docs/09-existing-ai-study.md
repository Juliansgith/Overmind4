# Existing AI study and licensing

This is an architecture study, not permission to copy. Repository visibility is
not a license.

## Pinned snapshots

Research snapshot: **2026-08-10**.

| Project | Pinned snapshot | Primary value | Reuse status |
|---|---|---|---|
| Installed FAF build 3836 | [`FAForever/fa@602185e`](https://github.com/FAForever/fa/tree/602185eb0753d205080313cc294d5665b49681cb) | Exact installed engine integration and stock brain/framework/utilities | Interface/reference; repository contains game-derived material and no simple permissive root license was established |
| M28AI v315 | [`e56ed873`](https://github.com/maudlin27/M28AI/tree/e56ed8734d0cef15d228be42d962a28cadc94578) | Mature direct-control AI, command discipline, map model, profiler | [CC BY-NC-SA 4.0](https://github.com/maudlin27/M28AI/blob/e56ed8734d0cef15d228be42d962a28cadc94578/LICENSE), with additional-file caveats |
| RNGAI v236 | [`8d41d06e`](https://github.com/relent0r/RNGAI/tree/8d41d06ef2cf4c2303fd87b7cc7086900089c504) | Hybrid builder/state-machine architecture, zones/intel/allocation | No license found; study only unless permission is obtained |
| AI-Uveso v116 | [`d9507cc7`](https://github.com/Uveso/AI-Uveso/tree/d9507cc717ea0eaeb25be695a042c6b79fc9583d) | Builder ecosystem, map/heat/scout grids, unit-mod compatibility | No root license; at least one file explicitly forbids copying |
| Mini27AI v2 | [`74dec9b1`](https://github.com/maudlin27/Mini27AI/tree/74dec9b15747bbfa2007da74f5569709b97bc451) | Minimal modern registration/bootstrap example | [MIT](https://github.com/maudlin27/Mini27AI/blob/74dec9b15747bbfa2007da74f5569709b97bc451/LICENSE); permissively reusable if its copyright/license notice is retained |
| M27AI | [`b6f1a441`](https://github.com/maudlin27/M27AI/tree/b6f1a44160b9d7ae38bd3570bc0de5ba487c0f0b) | Earlier mature procedural AI and M28 lineage context | [GPL-3.0](https://github.com/maudlin27/M27AI/blob/b6f1a44160b9d7ae38bd3570bc0de5ba487c0f0b/LICENSE); copied/derived code would carry GPL obligations |
| Local Overmind3 | Unversioned installed source release | Local experiments, module split, smoke inventory | Unknown provenance/license; ideas and tests only |

For M28, copied code would require attribution, noncommercial use, and
share-alike distribution under its license, and some files warn of additional
restrictions. Unless the project deliberately selects those constraints,
implement the learned concepts independently.

RNGAI and Uveso are public but no general permission to copy was found. Uveso's
[`AIMarkerGenerator.lua`](https://github.com/Uveso/AI-Uveso/blob/d9507cc717ea0eaeb25be695a042c6b79fc9583d/lua/AI/AIMarkerGenerator.lua)
contains an explicit no-copy notice. Do not port code or line-by-line
translations.

## Architecture comparison

| Dimension | Stock FAF | M28 | RNGAI | Uveso | Mini27 |
|---|---|---|---|---|---|
| Macro control | Builder/task frameworks | Direct procedural controller | Custom builders plus adaptive allocator | Large stock-derived builder catalog | Minimal hardcoded behavior |
| Unit execution | Platoon plans/managers | Direct tracked orders/micro | Role state machines | Stock/custom platoon plans | Direct per-unit threads/orders |
| Map model | NavUtils, markers, grids | Extensive shared map/zone/pond model | FlowAI mapping + land/naval/air zone sets | Generated markers + heat maps | Basic nav/deposit capture |
| Intel | Stock threat/recon/grids | Events/team knowledge/custom state | Large IntelManager | Scout-age/target grids | Minimal nearest-known |
| Economy | Framework conditions/managers | Fast samples + slower reconciliation | Rolling window + adaptive allocation | Priority/economy manager threads | Very limited |
| Command ownership | Framework-dependent | Central tracked-order helpers for many commands, but not an exclusive gateway | Split across managers/state machines | Split across plans/managers | Small tracking wrapper |
| Profiling | FAF profiler/debug UIs | Strong custom per-function/tick profiling | Limited formal profiling found | Limited formal profiling found | None found |
| Automated tests | FAF utility/blueprint/syntax, not AI match suite | None found | None found | None found | None found |
| Module risk | Legacy/new-framework coexistence | Giant modules/global hooks | Giant brain/intel modules/many threads | Broad hooks/startup preprocessing | Too simplistic/per-unit threads |

## Stock FAF AI/framework

Use stock FAF as the source of truth for:

- brain lifecycle;
- engine annotations;
- categories and blueprints;
- current `NavUtils`, markers, grids;
- safe low-level building/platoon/order primitives;
- mod discovery and hooks;
- debug/test compiler infrastructure.

Do not assume its stock builder framework is the best long-term strategic
architecture. Current FAF contains both legacy builder code under `lua/AI` and
newer brain/task/manager work under `lua/aibrains`. Mixing both without an
explicit owner creates competing control.

The exact interim opponent is
[`medium-ai.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/aibrains/medium-ai.lua),
routed from both `easy` and `medium`.

## M28: mature direct control

M28 is the closest architectural reference to the long-term competitive goal:

- a custom
  [`M28Brain`](https://github.com/maudlin27/M28AI/blob/e56ed8734d0cef15d228be42d962a28cadc94578/lua/AI/M28Brain.lua)
  and event startup;
- stock skirmish/attack/platoon-build/base-monitor systems disabled for M28
  brains;
- an overseer that starts distinct economy, engineer, ACU, factory, pond,
  strategy, team, and related systems;
- one-time map analysis covering navmesh, mex/path groups, plateaus, zones,
  ponds/islands, and reclaim;
- event-driven detection and lifecycle integration;
- direct factory decisions rather than stock builder-table ownership;
- tracked orders with near-duplicate suppression and awareness of active micro;
- frequent cheap economy updates plus slower reconciliation;
- explicit separate AIx/Overwhelm resource/build multipliers;
- first-class per-function/tick/memory profiling.

Representative sources:

- [`M28Events.OnCreateBrain`](https://github.com/maudlin27/M28AI/blob/e56ed8734d0cef15d228be42d962a28cadc94578/lua/AI/M28Events.lua#L4094-L4185)
- [`M28Overseer.M28BrainCreated`](https://github.com/maudlin27/M28AI/blob/e56ed8734d0cef15d228be42d962a28cadc94578/lua/AI/M28Overseer.lua#L556-L692)
- [`M28Map.SetupMap`](https://github.com/maudlin27/M28AI/blob/e56ed8734d0cef15d228be42d962a28cadc94578/lua/AI/M28Map.lua#L8161-L8236)
- [`M28Orders.IssueTrackedMove`](https://github.com/maudlin27/M28AI/blob/e56ed8734d0cef15d228be42d962a28cadc94578/lua/AI/M28Orders.lua#L248-L301)
- [`M28Economy` reconciliation](https://github.com/maudlin27/M28AI/blob/e56ed8734d0cef15d228be42d962a28cadc94578/lua/AI/M28Economy.lua#L1249-L1293)
- [`M28Profiler`](https://github.com/maudlin27/M28AI/blob/e56ed8734d0cef15d228be42d962a28cadc94578/lua/AI/M28Profiler.lua)

Ideas to independently reproduce:

- evolve tracked-order helpers into one exclusive command gateway/ownership
  model;
- event callbacks plus staged/bounded reconciliation;
- shared map model and explicit team blackboard;
- CPU/micro budgets;
- profiling from the start;
- cheating only in labeled personalities;
- stuck/stale-command recovery.

Pitfalls not to reproduce:

- `M28Map.lua`, `M28Events.lua`, and `M28Overseer.lua` have grown into
  multi-thousand-line central modules;
- broad global hooks raise compatibility/coupling risk;
- state is often stored as string-keyed fields on brain/unit objects;
- many threads/manual waits make unit testing and scheduling harder;
- no conventional automated AI test suite/CI was found;
- its license may conflict with future distribution/commercial choices.

## RNGAI: builder allocation plus state-machine execution

RNGAI composes custom factory, engineer, and platoon managers with large intel,
structure, mapping, and adaptive-allocation systems.

Notable design:

- declarative eligible builders choose macro jobs;
- factories resolve builder categories/templates into buildable faction units;
- engineers form task platoons;
- role-specific state machines execute land, air, naval, scout, ACU, engineer,
  experimental, artillery, nuke, TML, and optics roles;
- FlowAI creates cached multi-layer connected components/zone sets;
- IntelManager owns scouting, zones, structure requests, strategic flags, and
  outcome statistics;
- economy uses a rolling window rather than one instantaneous sample;
- adaptive allocation balances production/economy/construction/assistance/
  threats/zones/saturation/strategy separately from AIx cheating.

Representative sources:

- [`rng-ai.lua`](https://github.com/relent0r/RNGAI/blob/8d41d06ef2cf4c2303fd87b7cc7086900089c504/lua/AI/rng-ai.lua)
- [`FactoryBuilderManager.AssignBuildOrder`](https://github.com/relent0r/RNGAI/blob/8d41d06ef2cf4c2303fd87b7cc7086900089c504/lua/AI/BuilderFramework/FactoryBuilderManager.lua#L488-L532)
- [`EngineerManager.AssignEngineerTask`](https://github.com/relent0r/RNGAI/blob/8d41d06ef2cf4c2303fd87b7cc7086900089c504/lua/AI/BuilderFramework/EngineerManager.lua#L654-L710)
- [`platoon-land-combat.lua`](https://github.com/relent0r/RNGAI/blob/8d41d06ef2cf4c2303fd87b7cc7086900089c504/lua/AI/StateMachines/platoon-land-combat.lua)
- [`IntelManager.lua`](https://github.com/relent0r/RNGAI/blob/8d41d06ef2cf4c2303fd87b7cc7086900089c504/lua/IntelManagement/IntelManager.lua)
- [`FlowAI Mapping.lua`](https://github.com/relent0r/RNGAI/blob/8d41d06ef2cf4c2303fd87b7cc7086900089c504/lua/FlowAI/framework/mapping/Mapping.lua)

Ideas to independently reproduce:

- explicit typed role state machines;
- zone models per movement/domain layer;
- rolling economy signals;
- a clear intel subsystem;
- outcome statistics feeding future allocation;
- data-driven tuning/configuration.

Pitfalls:

- central brain/intel files are thousands of lines;
- many forever-threads make CPU ownership implicit;
- state-machine selection uses long string dispatch;
- no comparable formal profiler/test CI was found;
- code cannot be reused without permission/license.

Use a registry of small state-machine modules and one scheduler instead.

## AI-Uveso: builder priority and heat maps

Uveso keeps a stock-derived builder architecture while adding:

- central priority facts/gates consumed by builders;
- economy controls that pause expensive systems during stalls;
- explicit separately named cheat/Overwhelm behavior;
- dense terrain/pathability preprocessing and generated expansion markers;
- per-brain threat/target/scouting-age grids;
- broad unit-mod/Nomads support and validation/debug tooling.

Representative sources:

- [`AI list`](https://github.com/Uveso/AI-Uveso/blob/d9507cc717ea0eaeb25be695a042c6b79fc9583d/lua/AI/CustomAIs_v2/UvesoAI.lua)
- [`PriorityManagerThread`](https://github.com/Uveso/AI-Uveso/blob/d9507cc717ea0eaeb25be695a042c6b79fc9583d/hook/lua/AI/aiarchetype-managerloader.lua#L931-L1115)
- [`AITargetManager.lua`](https://github.com/Uveso/AI-Uveso/blob/d9507cc717ea0eaeb25be695a042c6b79fc9583d/lua/AI/AITargetManager.lua)

Ideas:

- central priority facts rather than duplicating conditions;
- scouting age and remembered/ghost value;
- map validation and mod-compatible catalog behavior;
- separately labeled cheat variants.

Pitfalls:

- broad hooks and function replacement;
- expensive startup preprocessing;
- possible fairness risk if full-area enemy queries expose hidden units;
- coarse fixed threat constants under modded blueprints;
- periodic whole-army scans;
- no automated test suite found;
- no project-wide permission to copy was established;
- `AIMarkerGenerator.lua` explicitly prohibits copying, and other files must be
  treated as no-copy unless their own header/license or author permission grants
  reuse.

## Mini27: legally reusable bootstrap, not a strategy

Mini27 explicitly describes itself as a simplistic developer starting point.
Useful modern examples:

- [`mod_info.lua`](https://github.com/maudlin27/Mini27AI/blob/74dec9b15747bbfa2007da74f5569709b97bc451/mod_info.lua)
- [`CustomAIs_v2 data`](https://github.com/maudlin27/Mini27AI/blob/74dec9b15747bbfa2007da74f5569709b97bc451/lua/AI/CustomAIs_v2/M27AIData.lua)
- [`brain index hook`](https://github.com/maudlin27/Mini27AI/blob/74dec9b15747bbfa2007da74f5569709b97bc451/hook/lua/aibrains/index.lua)
- [`M27Brain`](https://github.com/maudlin27/Mini27AI/blob/74dec9b15747bbfa2007da74f5569709b97bc451/lua/AI/M27Brain.lua)
- [`adaptive deposit hook`](https://github.com/maudlin27/Mini27AI/blob/74dec9b15747bbfa2007da74f5569709b97bc451/hook/lua/simInit.lua)

It lacks the economy, workforce, production, intel, reassessment, air/naval, and
strategic systems needed for the interim goal. It also demonstrates patterns we
should replace: global unit hooks, threads started from callbacks, and direct
enemy start lookup through `ArmyBrains`.

Use only the minimum registration/bootstrap concepts needed, ideally
independently re-authored under tests even though the MIT license permits reuse.

## Local Overmind3

Local Overmind3 already explores a custom procedural structure and has many
in-game smoke modules. It reinforces that:

- the custom brain path is viable locally;
- disabling stock owners can prevent command fights;
- debug/invariant modules are worth having early.

It also shows why Overmind4 needs a clean rewrite:

- no source/version provenance;
- no conventional unit/contract test suite;
- unmanaged raw threads;
- cross-mod personality registration;
- large tuning/config surface before a reproducible match campaign.

Use its smoke scenario ideas as test requirements, never as an unreviewed code
base.

## Secondary and historical repositories surveyed

These were inspected to reduce the chance of overlooking an existing bootstrap,
framework, or automation pattern. They are not the primary architecture basis:

| Project | Snapshot | Why it remains secondary |
|---|---|---|
| [AI-Swarm](https://github.com/Azraeel/AI-Swarm/tree/037b536d9664c67459aa9cdceb08fd2ed1c2f4e7) | `037b536d`, 2022-04-03, [GPL-3.0](https://github.com/Azraeel/AI-Swarm/blob/037b536d9664c67459aa9cdceb08fd2ed1c2f4e7/LICENSE) | Older FAF AI/framework reference; GPL obligations and age make current FAF/M28/RNGAI more useful for architecture |
| [DilliDalli](https://github.com/HardlySoftly/DilliDalli/tree/279f6a7f3dfc3d98939dd29867d17c0e88ec2a8f) | `279f6a7f`, 2022-10-02, [Unlicense](https://github.com/HardlySoftly/DilliDalli/blob/279f6a7f3dfc3d98939dd29867d17c0e88ec2a8f/LICENSE) | Competitive 1v1/framework experiment and useful automation/profiling history, but stale against build 3836 |
| [MicroAI](https://github.com/HardlySoftly/MicroAI/tree/a8ab057c6cf00fa57edffcfc46e0bc7eda0ce843) | `a8ab057c`, 2018-10-14, [WTFPL v2](https://github.com/HardlySoftly/MicroAI/blob/a8ab057c6cf00fa57edffcfc46e0bc7eda0ce843/LICENSE.txt) | Very small historical AI example; its old loading/framework assumptions are less useful than Mini27 |
| [Sorian-Edit](https://github.com/UnsilentMarLo/Sorian-Edit/tree/d7ee22126f241c9b871769367a0bde4bfd63dd6e) | `d7ee2212`, 2024-02-10, no root license found | Legacy Sorian-derived builder behavior; concepts only without permission |
| [LOUD](https://github.com/LOUD-Project/Git-LOUD/tree/b11e572a384d20ce462e8e027260b304c8de018d) | `b11e572a`, 2026-08-01, no root license found | A separate full LOUD game/data-path ecosystem rather than a current FAF vault AI mod; potentially useful for large-scale performance study, not drop-in code |
| [FAF-AI-Autorun](https://github.com/HardlySoftly/FAF-AI-Autorun/tree/7a9480250f8201980c89721c73b6e6ed3ffb52e2) | `7a948025`, 2022-01-16, [Unlicense](https://github.com/HardlySoftly/FAF-AI-Autorun/blob/7a9480250f8201980c89721c73b6e6ed3ffb52e2/LICENSE) | Best public historical batch-harness seed, but its init/archive/switch injection must be ported and tested against 3836 |

The
[official custom-AI catalog](https://wiki.faforever.com/en/Development/AI/Custom-AIs)
is useful for discovery, but repository source, commit history, and installed
behavior take precedence over catalog descriptions.

## Chosen direction

Overmind4 should combine, through independent implementation:

- Mini27's minimal registration surface;
- M28's event-driven command discipline, recovery, map sharing, and profiling;
- RNGAI's explicit role/state/zone separation and rolling allocation signals;
- Uveso's validation/scouting-age/mod-awareness lessons;
- FAF's stable low-level engine, nav, category, blueprint, grid, and debug APIs.

Avoid:

- inheriting stock managers and then fighting them;
- giant god modules;
- arbitrary forever-threads;
- scattered state on engine objects;
- unbounded global hooks/scans;
- hidden intel shortcuts;
- mixing cheat multipliers into the benchmark personality;
- copying code without an explicit compatible license.

## Independent-reimplementation practice

For every feature inspired by another AI:

1. record the high-level behavior/problem, not source text;
2. write an Overmind4 contract and failing tests;
3. design an independent data model/interface;
4. implement without the reference open beside line-by-line work;
5. retain attribution where a concept/source materially informed research;
6. run license review before copying even small nontrivial fragments.

Keep a future `THIRD_PARTY.md` for any actual incorporated code/assets, including
commit, file, license, modifications, and required notices.
