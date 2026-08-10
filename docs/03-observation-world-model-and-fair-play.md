# Observation, world model, and fair play

Overmind4 should be a strong **normal** AI, not an omniscient or resource-cheat
AI. Fairness is easiest to preserve when it is an adapter contract: policy code
never receives raw engine access to queries that can bypass intel.

## Observation policy

Evidence: **Engineering recommendation**, backed by the
[brain API annotations](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/CAiBrain.lua).

Classify every input before exposing it:

| Provenance | Examples | Policy access |
|---|---|---|
| Own state | Own units, queues, economy, upgrades, unit cap | Current and exact |
| Allied shared state | Allied units/intel legitimately shared by FAF | Current as exposed by the engine |
| Public scenario state | Map size, playable rectangle, lobby teams/options, known spawn geometry | Current; record assumptions |
| Current enemy intel | Unit/blip seen now on visual/radar/sonar/omni | Current, with sensor quality |
| Remembered enemy intel | Last seen position/type/health and observation tick | Explicitly stale and uncertainty-weighted |
| Inference | Expected army composition, likely expansion, path-based estimate | Marked as prediction, never fact |
| Omniscient sim state | Opponent brain unit list, global enemy rectangle scans | Forbidden in fair personality |
| Debug-only state | Full-map Sync overlays, profiler internals | Never feeds decisions |

Policy modules depend on `WorldView`, not on a raw `AIBrain`. The adapter is the
only code allowed to call engine queries. A test should fail if a policy module
imports `simInit`, reads `ArmyBrains`, or calls a global rectangle query.

## Brain identity and army state

The signatures exist in deployed
[`engine/Sim/CAiBrain.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/CAiBrain.lua).
The intel distinction is stated explicitly in the richer
[`develop` annotation](https://github.com/FAForever/fa/blob/b14d712426fbf2a461e036bd9981c849d51d4b54/engine/Sim/CAiBrain.lua#L330-L430).
Adopt it as the safe design boundary and retain a build-3836 engine regression
test so a future native-engine change cannot silently weaken fairness.

Useful identity and scenario-facing methods include:

- `GetArmyIndex()`;
- `GetArmyStartPos()`;
- `GetFactionIndex()`;
- `GetPersonality()`;
- `GetCurrentEnemy()` / `SetCurrentEnemy()`;
- `IsDefeated()`;
- `GetArmyStat()` and `GetBlueprintStat()`;
- map-water and army/unit-count helpers.

Do not retain another army's brain merely because `GetArmyBrain` or global
`ArmyBrains` makes it possible. For team logic, define an explicit shared-data
contract and test that it reveals no more than allied intel/game rules permit.

## Unit enumeration and the critical intel distinction

Two similarly named APIs have different fairness behavior:

- `brain:GetListOfUnits(category, needToBeIdle, requireBuilt)` **ignores intel**;
- `brain:GetUnitsAroundPoint(category, position, radius, alliance)` **takes
  intel into account**.

Therefore:

- use `GetListOfUnits` to reconcile **own** units only;
- use `GetUnitsAroundPoint(..., 'Enemy')` or normalized recon blips for enemy
  observations;
- never call the opponent's `GetListOfUnits`;
- never use `GetUnitsInRect`/`GetEntitiesInRect` to enumerate hidden enemies;
- test the fog boundary with an enemy that moves out of radar and visual range.

The annotation only promises that enumeration takes intel into account. It does
**not** promise that every method on a returned enemy `Unit` reference redacts
information according to sensor quality. Never pass those raw references into
the general safe-observation path: a radar/sonar-only contact must be normalized
as a blip/sensor track unless engine tests prove which blueprint, health, order,
weapon, and completion fields are legitimate.

`GetNumUnitsAroundPoint` can be useful for local counts, but its exact category,
alliance, and intel behavior should be exercised alongside
`GetUnitsAroundPoint` before it is trusted as an independent fair input.

The deployed annotation marks `GetListOfUnits`'s `requireBuilt` argument as
apparently nonfunctional. Filter construction state explicitly in the adapter
and test both complete and incomplete units.

## Entity and unit APIs

Annotated engine surfaces:

- [`engine/Sim/Entity.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/Entity.lua)
- [`engine/Sim/Unit.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/Unit.lua)
- [`lua/sim/Unit.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/sim/Unit.lua)

Common entity observations:

- lifetime: `BeenDestroyed()`, `GetFractionComplete()`;
- identity/ownership: `GetEntityId()`, `GetArmy()`, `GetAIBrain()`;
- type: `GetBlueprint()`;
- geometry: `GetPosition()`, `GetOrientation()`, heading/XYZ helpers;
- durability: `GetHealth()`, `GetMaxHealth()`.

Common unit observations:

- construction/pathing: `CanBuild()`, `CanPathTo()`;
- work and economy: consumption, production, work progress, focus unit;
- movement: current layer/location, navigator, velocity, moving/idle state;
- orders: `GetCommandQueue()`, target/focus/guarded unit and guards;
- cargo/transport state;
- shield ratio/state;
- silo ammunition;
- weapons and weapon count;
- generic `IsUnitState(...)`.

Safety rules:

- the public source does not promise that an entity ID is permanently unique or
  never reused after destruction; treat it as valid only with a live,
  current-observation record;
- never call a method before testing that a userdata/object is non-nil and not
  destroyed;
- distinguish under-construction, paused, captured, transferred, attached,
  transported, and completed units;
- callbacks may arrive while another manager still holds an old reference;
- normalize engine userdata into plain immutable records before strategic code
  consumes it;
- use a generation/observation token in caches so possible ID reuse cannot
  inherit a previous unit's intent or memory; verify actual reuse behavior with
  an engine test.

## Categories and blueprints

FAF categories are engine bitsets, not ordinary Lua sets:

- `+` means union;
- `*` means intersection;
- `-` means exclusion.

Useful helpers declared in
[`engine/Core.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Core.lua):

- `EntityCategoryContains`;
- `EntityCategoryFilterDown`;
- `EntityCategoryGetUnitList`;
- `ParseEntityCategory`.

Unit blueprints expose a `CategoriesHash` and detailed economy, defense, intel,
physics, movement, weapon, wreckage, transport, and construction fields. The
annotated schema begins at
[`engine/Core/Blueprints/UnitBlueprint.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Core/Blueprints/UnitBlueprint.lua).
`GetUnitBlueprintByName` and blueprint tables are declared in
[`engine/Sim.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim.lua).

Cache normalized blueprint-derived facts once:

- faction and tech level;
- layer and movement capabilities;
- buildable categories and build rates;
- mass/energy/build-time costs;
- upkeep and production;
- weapon arcs, target restrictions, range, damage, projectile behavior;
- health, shield, regeneration, stealth/cloak;
- transport class/capacity;
- strategic roles inferred from categories and fields.

Do not hardcode only four faction unit IDs throughout policy. Put faction/unit
resolution behind a tested catalog adapter and retain category/blueprint
fallback behavior for mod compatibility.

## Economy observations

Brain methods include:

- `GetEconomyIncome(resource)`;
- `GetEconomyRequested(resource)`;
- `GetEconomyStored(resource)`;
- `GetEconomyStoredRatio(resource)`;
- `GetEconomyTrend(resource)`;
- `GetEconomyUsage(resource)`;
- current unit and unit-cap/count helpers.

The annotations describe income as per tick and trend with a scale where `0.1`
corresponds to one displayed unit per second. Existing FAF helpers often
normalize these values. Overmind4 should have one `EconomyAdapter` that exposes
clearly named units, for example `massIncomePerSecond`, and an in-engine test
that compares the adapter to the UI/known controlled production.

Raw economy values are observations; reservations, forecasts, and affordability
are project logic. Keep those layers separate.

## Recon blips and enemy memory

The blip surface is declared in
[`engine/Sim/ReconBlip.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/Sim/ReconBlip.lua):

- `GetBlueprint()`;
- `GetSource()`;
- `IsKnownFake()`;
- `IsMaybeDead()`;
- `IsOnOmni()`;
- `IsOnRadar()`;
- `IsOnSonar()`;
- `IsSeenEver()`;
- `IsSeenNow()`.

The annotation marks `IsKnownFake()` deprecated and says it does not appear to
function. It cannot be the foundation of spoof detection.

Do not hand raw blips to policy. Normalize them into:

```text
trackId
observedBlueprintId or unknown
lastPosition
firstSeenTick / lastSeenTick
sensor: visual | omni | radar | sonar | inferred
currentlyVisible
maybeDead / knownFake
confidence
```

`GetSource()` is annotated to return the underlying `Unit` even for jamming/
spoofing blips. Prohibit it in the fair observation adapter until controlled
fog, stealth, counter-intelligence, and destroyed-unit tests establish a safe
contract; policy should consume normalized sensor evidence instead.

Enemy memory must decay:

- exact current visual/omni observations can have high confidence;
- radar/sonar contacts have less type certainty;
- a lost mobile contact gets an expanding positional uncertainty region;
- a lost structure can remain likely at its last position but not guaranteed;
- `maybeDead` and fake contacts must not be converted into known live units;
- old health, order, target, and upgrade observations are not current facts.

## Threat APIs

Brain threat methods include:

- `GetThreatAtPosition`;
- `GetThreatBetweenPositions`;
- `GetThreatsAroundPosition`;
- `GetHighestThreatPosition`.

Threat types cover overall, structures, land, air, naval, artillery,
experimental, commander, anti-air, anti-surface, anti-sub, economy, and related
layers.

Signatures are **Verified 3836**; exact current-versus-remembered intel semantics
are **Needs engine test**. Threat values must not become the back door around
the fair observation contract. Until tests prove the intended semantics:

- use threats for own/allied state freely;
- label enemy-derived threat as engine-estimated;
- compare threat queries with visible units across fog transitions;
- never combine a threat hotspot with an omniscient query to reconstruct hidden
  units;
- provide a policy fallback based only on normalized tracks.

## Global world and map queries

`engine/Sim.lua` exposes:

- `GetArmyBrain`;
- `GetEntityById`;
- `GetEntitiesInRect`;
- `GetUnitsInRect`;
- `GetReclaimablesInRect`;
- `GetTerrainHeight`;
- `GetSurfaceHeight`;
- `GetMapSize`;
- `GetGameTick`.

The global rectangle/entity functions operate in the simulation and should be
considered omniscient unless a specific API contract says otherwise. Appropriate
uses include own-object lookup, neutral props/reclaim after a fairness test, or
debug tooling. They are forbidden for hidden enemy discovery.

Map/scenario data commonly comes from:

- `ScenarioInfo.size`;
- `ScenarioInfo.MapData.PlayableRect`;
- full-map bounds as fallback;
- map markers/resource deposits;
- terrain and surface height.

Normalize coordinates to `{x, y, z}` records. Never mix a build API's legacy
`{x, z, 0}` convention with world vectors without an adapter.

## Reclaim and resource observation

`GetReclaimablesInRect`, `GridReclaim`, marker utilities, and map resource
callbacks expose props/wreckage and deposits. Signatures are known, but fog
semantics for enemy-created wrecks and hidden props need a controlled engine
test. The normal AI should not infer unseen battles from newly created wrecks
unless the game legitimately reveals those props.

Resource deposits are normally public map facts once the scenario is
initialized. Adaptive/generated maps may create them dynamically; record the
creation events or initialize after `OnBeginSession`, not during `OnCreateAI`.

## Events supplied to the brain

[`lua/aibrain.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/aibrain.lua)
forwards many events:

- unit creation, start/stop/fail/progress of construction, completion;
- destruction, killed, reclaimed, and capture-state callbacks;
- health change;
- reclaim and repair;
- pause/unpause;
- transport attach/detach/load;
- teleport;
- shield state;
- nuke, tactical missile, silo, work, sacrifice;
- consumption and production changes.

It explicitly does not forward every possible unit event, including raw
`OnDamage` and all layer/motion changes. Attach unit callbacks or hook unit code
only for a proven missing requirement.

Gift/transfer is another distinct gap: the brain has no general
`OnUnitGiven` forwarding callback. `Unit.OnGiven`/
`AddOnGivenCallback` and `ScenarioTriggers.CreateUnitGivenTrigger` expose that
surface. Test both the old and new unit/army references before integrating it.

[`lua/scenariotriggers.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/scenariotriggers.lua)
adds area, threat, timer, statistics, intel, veterancy, distance, build, damage,
death, reclaim, capture, and transport triggers.

Best practice:

- callbacks append a small normalized event to a brain-local queue;
- a scheduled reconciler processes/coalesces events deterministically;
- periodic low-frequency own-unit/economy reconciliation repairs missed or
  reordered state;
- callbacks never run expensive global planning or issue unrelated commands;
- trigger and callback handles are registered with cleanup ownership.

## Simulation-to-UI and UI-to-simulation

UI-to-sim commands use
[`SimCallback`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/engine/User.lua)
and named handlers in
[`lua/SimCallbacks.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/SimCallbacks.lua).
The source explicitly requires validating every UI-originating argument against
cheats/exploits and supplies ownership/secure-unit helpers.

Sim-to-UI data is written to `Sync` via
[`lua/SimSync.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/SimSync.lua)
and received through
[`lua/UserSync.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/UserSync.lua).
Custom Sync fields are generally transient and reset after transfer.

For Overmind4:

- decisions and commands stay entirely sim-side;
- `Sync` is optional diagnostic visualization, not a primary telemetry channel;
- filter debug data for the focus army so a player cannot see hidden state;
- never modify FAF rating/result channels such as `GameResult`, `StatsToSend`,
  `JsonStats`, or `GpgNetSend`;
- rate-limit and size-limit Sync payloads because they cost serialization,
  copying, and simulation/UI processing.

## Proposed world-model contract

The first useful model can remain small:

```text
WorldSnapshot
  tick
  map: bounds, movement components, known deposits, expansion candidates
  self:
    economy, unit cap, tech state
    unitsByStableKey
    production queues and owned intentions
  allies:
    public/shared observations
  enemy:
    current tracks
    stale tracks with confidence and lastSeenTick
  objectives:
    bases, deposits, contested zones
  eventsSincePreviousSnapshot
```

Every snapshot should be a deterministic projection with:

- stable ordering;
- no raw engine objects crossing into pure policy;
- explicit unknown values instead of invented defaults;
- observation timestamps;
- provenance/sensor quality;
- no stale reference mutation after publication.

## Mandatory fairness and observation tests

Write these failing tests before the observation adapter:

- own enumeration includes built and under-construction units as configured;
- enemy hidden outside all intel is absent;
- enemy visible now is present with the right sensor provenance;
- contact lost to fog becomes stale memory rather than remaining current;
- destroyed visible contact is removed/marked dead;
- `maybeDead` and fake blips are not counted as confirmed live combat value;
- radar-only contact does not reveal a forbidden exact blueprint;
- radar/sonar-only returned objects do not leak exact health, orders, weapons,
  completion, or other unobserved fields;
- stealth, cloak, radar stealth, sonar stealth, and omni transitions;
- enemy captured/transferred between armies changes ownership correctly;
- entity ID reuse cannot inherit an old target/order/memory record;
- nil/destroyed unit during callback/reconciliation is harmless;
- incomplete unit value and capability are represented separately;
- threat queries do not reveal a hidden controlled test force;
- reclaim queries do not reveal unseen enemy activity;
- malformed/missing playable rectangle and markers have safe fallbacks;
- economy unit conversion matches a controlled in-engine setup;
- current snapshot ordering is identical across repeat runs/seeds;
- policy code cannot import or call forbidden omniscient surfaces;
- debug Sync contains no hidden enemy data for a human focus army.
