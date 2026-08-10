# Navigation, economy, and combat surfaces

## Modern navigation

Evidence: **Verified 3836** in
[`lua/sim/NavUtils.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/sim/NavUtils.lua)
and
[`lua/shared/NavGenerator.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/shared/NavGenerator.lua).

Navigation layers:

- `Land`
- `Water`
- `Amphibious`
- `Hover`
- `Air`

Main API:

- lifecycle: `IsGenerated`, `Generate`;
- reachability: `CanPathTo`, `CanPathToCell`;
- routes: `DetailedPathTo`, `PathTo`, `PathToWithThreatThreshold`;
- topology: `GetLabel`, `GetTerrainLabel`, label/IMAP helpers,
  `GetLabelMetadata`;
- sampling: positions in radius/cells;
- direction: `DirectionsFrom`, threat-filtered directions,
  `RandomDirectionFrom`, `RetreatDirectionFrom`, `DirectionTo`;
- bounds: `IsInPlayableArea`, `IsInBuildableArea`.

`Generate()` is idempotent. Stock medium initialization generates navigation
before expansion/rally/naval marker and grid setup. Overmind4 should verify it
exists once in `OnBeginSession`, then cache stable topology.

`PathTo` returns path positions, a count or error, and optionally length.
Handle every documented failure as normal data:

- `NotGenerated`;
- `InvalidLayer`;
- `SystemError`;
- generic `OutsideMap`;
- origin/destination outside map;
- origin/destination unpathable;
- `Unpathable`;
- threat-aware `NoResults`;
- threat-aware `TooMuchThreat`.

Normal path calls return positions, count-or-error, and optional length.
`PathToWithThreatThreshold` additionally returns the over-threshold threat
locations and their count as fourth/fifth values.

No-path is not an exception. It can mean choose air, request transport, build
naval/amphibious forces, select a different objective, or wait for a safer
route.

## Navigation adapter rules

- Convert unit blueprint/layer state into one explicit nav layer.
- Cache component/label membership for stable positions.
- Cache strategic paths, not per-unit exact movement forever.
- Invalidate or re-evaluate when endpoints, threat policy, layer, map bounds, or
  important obstructions change.
- Never path every unit every tick.
- Use stable path tie-breaks.
- Validate path waypoints against the playable area.
- Keep "geometrically connected" distinct from "currently safe".
- Treat threat-aware paths as **Needs engine test** until enemy-threat intel
  fairness is proven.
- Have a stuck detector based on movement progress over ticks, with sufficient
  grace for formation and factory egress.

Legacy functions such as `PlatoonGenerateSafePathTo` and path-graph helpers in
[`lua/AI/aiattackutilities.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/aiattackutilities.lua)
remain useful compatibility references, but depend more heavily on map markers.
Prefer generated terrain navigation for new core logic.

## Map and marker surfaces

Map bounds come from the playable rectangle when provided, otherwise full
scenario/map size. Terrain and water surface come from `GetTerrainHeight` and
`GetSurfaceHeight`.

[`lua/sim/MarkerUtilities.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/sim/MarkerUtilities.lua)
provides cached:

- marker lookup and markers by type;
- marker chains;
- mass/hydro/resource marker data;
- generated expansion areas;
- generated rally points;
- naval-area helpers.

Maps can have missing, malformed, stale, or unconventional markers. Markers are
candidates/hints, never the only source of topology truth.

Initial milestone map model:

```text
MapModel
  playable bounds
  nav components by layer
  own start
  revealed/public opponent starts
  unknown opponent-start regions or priors kept explicitly uncertain
  mass and hydro deposits
  buildable expansion candidates
  chokepoint/front approximations
  water ratio and naval relevance
  rally points by component
```

## FAF spatial grids

Current reusable modules:

- [`GridReclaim.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/GridReclaim.lua):
  reclaim update, filtering, maximum/sorted candidates in radius;
- [`GridRecon.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/GridRecon.lua):
  recon cells and intel-change integration;
- [`GridPresence.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/GridPresence.lua):
  inferred allied/hostile/contested presence;
- [`GridBrain.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/GridBrain.lua):
  scout/reclaim assignment accounting;
- [`GridDeposits.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/AI/GridDeposits.lua):
  deposit registration/query.

Reuse through project adapters, not by exposing these mutable objects throughout
policy.

### GridDeposits warning

Evidence: **Verified 3836 source review; Needs engine regression**.

The deployed `GridDeposits.Setup` appears to:

- pass hydrocarbon deposits to `RegisterExtractorDeposit`;
- use a filter shaped like `if not deposit.Type == depositType`, whose
  precedence does not express the likely intended inequality.

Do not rely on hydro registration or type filtering without a local adapter and
tests. Prefer a corrected local registry fed from scenario deposit creation if
the upstream behavior proves wrong. Report a minimal reproduction upstream
rather than silently coupling core strategy to the defect.

Adaptive/generated resource layouts can create deposits after static scenario
data is read. Capture the legitimate simulation creation path or initialize the
registry at the correct lifecycle boundary. Mini27's
[`hook/lua/simInit.lua`](https://github.com/maudlin27/Mini27AI/blob/74dec9b15747bbfa2007da74f5569709b97bc451/hook/lua/simInit.lua)
is a reference for intercepting resource creation, but a less invasive shared
registry is preferable.

## Economy model

The engine supplies current measurements; Overmind4 must supply forecasts and
commitment discipline.

Normalize:

- mass/energy income per second;
- requested/usage per second;
- trend per second;
- stored amount and ratio;
- unit-cap used/limit/headroom;
- active build power and committed future drains;
- paused/stalled production;
- reclaim expected value and travel cost.

One economy ledger owns:

```text
available now
committed ongoing drain
accepted one-time reservations
candidate reservations
safety buffers
predicted income changes
unit-cap reservations
```

Managers request budgets; they do not independently decide that the same mass
is available. Reservation state is released on every terminal path.

### Stall policy

Mass and energy stalls are different:

- mild mass deficit can be efficient when build power is converting all income;
- energy stall can disable radar, shields, production, and commander abilities;
- storage overflow wastes income/reclaim;
- a severe stall can make adding more build power actively harmful.

Use hysteresis and forecast windows, not one-tick thresholds. Track duration and
depth of stalls, not just whether trend is negative at a sample.

### Expansion and extractor policy

An expansion decision combines:

- deposit count/value;
- build/travel/reclaim opportunity cost;
- reachability and transport needs;
- defensive exposure from fair intel;
- distance to production and front;
- expected retention time;
- tech/upgrades of existing extractors;
- unit-cap and engineer availability;
- lost alternative work.

Reserve builders and economy before issuing. If an expansion cannot be held,
cheap denial/raid/scout objectives may be better than a full base.

## Production model

Build composition should be derived from roles and observed needs, then resolved
through faction-valid blueprints:

- economic constructors/engineers;
- scouts and intel;
- land line units and raiders;
- mobile/static anti-air;
- artillery/range/breakthrough;
- naval and anti-naval roles;
- air intercept, scout, strike, transport;
- defense and strategic weapons;
- commander upgrades;
- experimental/endgame transitions.

Avoid a fixed build list that ignores reachability and enemy composition. Avoid
an unconstrained reactive system that changes factory queues on every contact.
Use goals, minimum commitments, response ceilings, and queue hysteresis.

The first stock-medium milestone can deliberately restrict scope:

- one small standard land map;
- one faction initially;
- no unit mods;
- normal victory;
- ordinary T1/T2 economy, land, scout, engineer, anti-air, and ACU behavior;
- no transports/navy/strategic weapons until tests/gates pass.

Then expand across factions and map classes rather than pretending the first
opener generalizes.

## Combat observations and target evaluation

Blueprint/unit/weapon surfaces expose:

- health, shield, regeneration, veterancy-related state;
- weapon count, range, damage fields, fire restrictions, target layers;
- position, velocity, heading, current layer;
- command/target/focus state;
- movement and pathing capability;
- transport/cargo state;
- cloak/stealth/intel capabilities;
- construction/completion fraction.

Normalize a combat value model and test it against edge cases. It need not
perfectly simulate every projectile initially, but it must not compare:

- incomplete unit at full completed value;
- anti-air damage as ground damage;
- torpedo weapons against land targets;
- strategic weapon nominal damage as ordinary DPS;
- transport/civilian utility as line-combat power;
- stale contact as a confirmed unit at an exact point.

Target scoring should include:

- legal target and weapon layer;
- expected damage/time to engage;
- target value and tactical role;
- overkill and already assigned damage;
- route/exposure/retreat;
- allied concentration;
- strategic objective value;
- confidence/age of enemy observation;
- switching cost and command hysteresis.

## Force allocation

Separate strategic allocation from micro:

1. Strategy creates goals: defend, raid, expand, scout, attack, escort, deny.
2. Force allocator assigns available units and minimum required strength.
3. Tactical controller selects formation/approach/retreat within that goal.
4. Micro proposes short-lived high-priority actions.
5. Order broker resolves them and preserves goal ownership.

Micro cannot permanently steal units from a goal. Strategy cannot overwrite an
emergency dodge or commander retreat every scheduler cycle.

## Commander safety

The ACU is both production/economy and the usual assassination loss condition.
Model:

- current/max health and shield;
- observed incoming DPS/range;
- pathable retreat corridors;
- nearby allied support;
- enemy overcharge/snipe/air threat estimates;
- energy required for overcharge/upgrades;
- build/upgrade commitment and cancellation cost;
- teleport capability;
- game victory mode.

Commander behavior needs conservative emergency overrides and explicit tests.
A single clever attack does not compensate for occasional avoidable ACU losses
in a reliability benchmark.

## Scouting and intel investment

The fair AI must actively buy information:

- choose cells/expansions/routes whose uncertainty matters to a decision;
- assign scouts without duplicate coverage;
- account for scout survival and travel time;
- maintain radar/sonar coverage;
- revisit stale high-value areas;
- react to lost intel without treating absence as proof;
- connect observation age to strategic confidence.

`GridRecon`/`GridBrain` can inform coverage and assignment, but the decision
value of information belongs in Overmind4's policy.

## Map-class expansion

Roadmap categories:

1. small connected land;
2. large connected land;
3. chokepoint/limited land components;
4. mixed land-water;
5. naval-dominant;
6. islands requiring air/transport/navy;
7. adaptive/generated resources;
8. team/shared-army;
9. FFA/multiple enemies;
10. unit restrictions and supported unit mods.

Each category gets dedicated fixtures and acceptance results. Never treat
`CanPathTo == false` as a rare edge; it is a core strategic input.

## Mandatory navigation/economy/combat tests

- nav not generated and duplicate generate call;
- every nav layer and invalid layer;
- start/destination outside bounds;
- unpathable, no result, and excessive-threat return shapes;
- same component, separate islands, water crossing, amphibious/hover differences;
- missing/malformed markers and playable rectangle;
- generated resource deposit after initialization;
- mass versus hydro registration/filtering;
- zero income/storage, full storage, negative trend, scale conversion;
- mass stall, energy stall, overflow, economy shock, reclaim windfall;
- duplicate reservation and every release path;
- builder can build but cannot reach site; site reachable but not buildable;
- factory paused, upgrading, destroyed, captured, queue full, unit cap full;
- all factions resolve every required role or return explicit unsupported;
- hidden/stale/fake enemy tracks influence decisions only at allowed confidence;
- weapon cannot target layer; no ammo; shielded target; incomplete target;
- target switch hysteresis and overkill suppression;
- retreat with no safe direction and retreat across invalid component;
- commander upgrade interrupted by lethal threat;
- scout assignment avoids duplicates and revisits stale cells;
- identical snapshot yields identical allocation, path choice, and orders;
- high unit count respects per-tick work budget;
- policy remains safe when every optional query returns nil/empty/error.
