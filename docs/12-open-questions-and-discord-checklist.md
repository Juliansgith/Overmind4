# Open questions and Discord checklist

Public and installed sources are sufficient to begin Overmind4. Discord access
is not currently needed. The remaining gaps should first be answered by small
controlled engine tests; ask Discord where community knowledge or private
tooling can save substantial work.

## Priority 1: engine behavior tests

### Fairness/intel

- Do each `GetThreat*` method include only current/remembered legitimate intel,
  and how do results change after visual/radar/sonar/omni loss?
- Does `GetNumUnitsAroundPoint` exactly match the intel filtering of
  `GetUnitsAroundPoint` for every alliance argument?
- Can `ReconBlip:GetSource()` reveal a hidden real unit, exact blueprint, or
  spoof source that policy should not know?
- What exact information remains on radar/sonar/fake/maybe-dead blips?
- Do `GetReclaimablesInRect`/`GridReclaim` reveal wrecks created outside intel?
- Do marker/resource deposit APIs reveal only public scenario facts on adaptive
  maps?
- Are enemy start positions always public in supported lobby modes, including
  random spawn/FFA scenarios?

### Command semantics

- Exact delayed-application/queue behavior for every `IssueBuild*` form.
- Return/status lifecycle and failure behavior of `SimCommand`.
- Whether declared group orders ignore/die on nil, mixed-owner, dead, attached,
  or captured units.
- Exact coordinate shape for `BuildStructure`, `IssueBuildMobile`, tactical/
  nuke, rally, ferry, unload, and teleport calls.
- Stability/performance of FAF-only `IssueToUnit*` wrappers.
- Whether navigator `SetGoal` is an appropriate safe optimization without queue
  clearing, and its completion/stuck semantics.
- Ordering of clear/stop/new command in the same tick.
- Factory queue behavior during upgrade/pause/capture.

### Lifecycle/events

- Exact callback order for build failure, destruction, reclaim, capture,
  transfer, transport, pause, and defeat races.
- Which callbacks can duplicate or arrive after `BeenDestroyed`.
- Entity ID reuse timing and reliable generation detection.
- `OnVictory`/`OnDefeat`/`OnDraw`/`OnDestroy` ordering across victory modes.
- Cleanup behavior of `brain:ForkThread` and registered triggers.
- Best supported hook/callback for dynamically generated deposits.

### Economy/map

- Confirm per-tick/per-second scale of every economy method in controlled
  scenarios.
- Reproduce/fix `GridDeposits` hydro registration and deposit-type filter.
- Nav generation timing/cost/error shapes across old, generated, and malformed
  maps.
- Whether threat-aware pathing uses fair threat information.
- Supported fallback when `ScenarioInfo.MapData.PlayableRect` or markers are
  absent.

Each answer becomes a version-pinned engine test, not only a prose note.

## Priority 2: automation research

No supported current true-headless runner was found. Before building a large
launcher, ask:

1. Is there a maintained private/community successor to
   [FAF-AI-Autorun](https://github.com/HardlySoftly/FAF-AI-Autorun)?
2. Which current AI authors use unattended AI-v-AI batch matches?
3. Is there a build-3836-compatible init/scenario hook for arbitrary AI slots,
   fixed factions/teams/spawns, max sim time, exit-on-result, and result logs?
4. Is parallel multi-instance execution considered reliable, and what profile/
   port/data isolation is required?
5. What acceleration ceiling preserves representative AI scheduling/pathing and
   avoids false timeouts?
6. Is there a community standard machine-readable match result schema?
7. How are generated-map seeds and map content hashes pinned?
8. Are replay checksums/desync signals accessible in a stable log/API?
9. Which command-line switches are current engine switches versus custom
   autorun hooks?
10. Are there tournament scripts or benchmark map/seed corpora available?

## Priority 3: benchmark definition

Ask competitive AI authors/modders:

- Which M28 non-cheat personality/version/options are considered the fair
  reference?
- Which maps expose land, naval, island, expansion, reclaim, transport, and
  performance weaknesses without being pathological?
- What match count/pairing practice is considered credible?
- Which draws/timeouts/victory modes are standard?
- Are AI-versus-AI games normally run with fixed or random faction/spawn?
- What does the community mean operationally by Easy, Normal, and M28 wins?
- Which CPU/sim-speed measurements are accepted?
- Are any maps/options known to be broken for all AIs and excluded?
- Which team/FFA/shared-army scenarios matter?

Record answers as campaign manifests and rationale. Do not replace an explicit
project benchmark with anecdotes.

## Priority 4: licensing/permission

If actual code reuse is desired:

- ask RNGAI's author for an explicit license or written permission;
- ask Uveso before any reuse, noting file-level no-copy notices;
- clarify M28's additional-file restrictions and whether intended Overmind4
  distribution is compatible with CC BY-NC-SA;
- confirm expectations for attribution when borrowing Mini27 MIT bootstrap
  fragments;
- choose Overmind4's own license before accepting third-party contributions.

Until then, follow the independent-reimplementation process in
[the AI study](09-existing-ai-study.md).

## Questions already answered

Do not spend Discord time re-asking these unless a new FAF build changes them:

- A custom AI can be registered from a normal active simulation mod through
  `CustomAIs_v2` plus a `/hook/lua/aibrains/index.lua` key.
- User mods use `/hook`; old `/schook` setup is not required for build 3836.
- AI decisions run in deterministic simulation Lua.
- There is no supported live socket/Python/LLM channel in a normal AI mod.
- Brain `OnCreateAI` is too early for initial units/resources; use
  `OnBeginSession`.
- Use `brain:ForkThread` for owned thread cleanup.
- `GetListOfUnits` ignores intel; do not use it for enemies.
- `GetUnitsAroundPoint` takes intel into account.
- Direct `Issue*` functions are available.
- Easy and Normal both route to `medium-ai.lua` in deployed build 3836.
- Current local baseline has three unrelated enabled sim mods and must be
  cleaned.

## Suggested engine experiment pack

Build this only under TDD:

```text
engine-tests/
  lifecycle/
  intel/
    visual-radar-sonar-omni
    stealth-cloak-spoof
    threat-fog
    reclaim-fog
  commands/
    queue-and-delay
    coordinate-contracts
    destroyed-captured-transported
  economy/
    units-and-events
  map/
    nav-errors
    deposits-adaptive
    malformed-markers
  determinism/
    repeated-fixed-scenario
  interoperability/
    two-ai-mod-hooks
```

Each scenario:

- pins game/map/mod hashes;
- emits start/assertion/terminal structured records;
- uses no human/debug intervention;
- times out deterministically;
- retains a replay;
- documents whether the finding is fair-AI production behavior or debug-only.

## When Discord becomes necessary

Request Discord access only when at least one of these is true:

- three controlled tests still cannot distinguish engine behavior;
- a maintained automation tool is known to exist only there;
- benchmark consensus is needed before a large campaign;
- explicit author permission/license clarification is required;
- a reproducible engine bug needs maintainer confirmation.

Prepare a compact question with:

- FAF build/commit;
- minimal mod/scenario;
- expected versus observed result;
- relevant source links;
- log excerpt without secrets;
- replay if safe;
- tests already performed.

## Research maintenance

Reopen this research when:

- FAF client/game build changes;
- a relevant engine annotation/API changes;
- M28/RNGAI benchmark version changes;
- automation tooling appears;
- an engine test contradicts a current claim;
- project scope adds multiplayer teams, FFA, generated maps, or unit mods.

Update the evidence label and source lock; retain old benchmark results with
their original versions.
