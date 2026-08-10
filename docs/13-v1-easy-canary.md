# V1 Easy canary result

Date: **2026-08-10**

## Result

Overmind4 defeated the stock non-cheating FAF Easy AI in the first pinned
competitive setup. The reporting-fixed confirmation run received the official
`victory 10`; Easy received `defeat -10` after losing its ACU.

After one swapped-spawn holdout exposed a mobilization defect, commit
`63948454d973d460e826352c1978b5289d8f2233` fixed that behavior and won both
declared Open Palms orientations/seeds. This is 2/2 diagnostic matches for the
final candidate, not a statistical win-rate claim.

This is a narrow capability result, not a robust win-rate claim. It establishes
that the fully custom controller can complete a legal UEF opening, sustain T1
production, concentrate a force, merge reinforcements into a commander-led
push, and finish one stock opponent without inheriting stock AI decisions.

## Pinned match

| Field | Value |
|---|---|
| Run | `om4-20260810T165306Z-9f3d903f` |
| Overmind4 commit | `33914a3eb76dbaff24de77b95e1d87699be329e3` |
| Strategy commit | `f3418c157fee4089b9f0394f65ec4904c5c7eb1b` |
| FAF | build 3836, `602185eb0753d205080313cc294d5665b49681cb` |
| Map | `SCMP_007` Open Palms v3 |
| Map SHA-256 | `A2FA5C8996CACB2D1AEF7DCCB00C55845891512B78301B6097716434BC52358E` |
| Seed | `7777` |
| Slot 1 | Overmind4, UEF, team 1 |
| Slot 2 | FAF Easy, UEF, team 2 |
| Sim mods | Overmind4 only |
| Unit cap | 1000 |
| Requested speed | 25x |
| Limits | 1800 sim seconds, 600 wall seconds |

Retained local evidence is under
`artifacts/runs/om4-20260810T165306Z-9f3d903f/`: manifest, isolated final
preferences, game log, replay, JSON report, and Markdown report.

## Outcome and efficiency

| Metric | Overmind4 | FAF Easy |
|---|---:|---:|
| Official result | victory 10 | defeat -10 |
| Score | 10,213 | 6,683 |
| Units built | 116 | 141 |
| Current units | 73 | 72 |
| Kills | 66 | 42 |
| Units lost | 45 | 73 |
| Mass received | 10,381 | 14,955 |
| T2 units built | 0 | 1 |
| Air units built | 0 | 19 |
| Air units killed | 17 | 0 |
| ACU kills/losses | 1 / 0 | 0 / 1 |

The official Overmind result arrived at **647.60 sim seconds** (10:47.6).
Wall time was **33.53 seconds**, for an achieved **19.32x** simulation rate.
Overmind4 won despite receiving substantially less mass, so this match was won
through force use rather than an economic lead.

## Causal behavior timeline

| Sim time | Event |
|---:|---|
| 326.8s | ACU ordered from the home opening to the staging point |
| 394.3s | Commander push launched with 36 combat escorts |
| 586.0s | 27 new combat units ordered to reinforce/guard the active commander |
| 639.1s | ACU retreat triggered at the 0.75 safety threshold |
| 642.1s | Easy recorded `defeat -10` after its ACU died |
| 647.6s | Overmind4 recorded `victory 10` |

The same configuration had already produced the same official victory and
unit/stat totals immediately before the reporting fix. The confirmation run
therefore proves reproducibility for this deterministic manifest, not
independence across seeds or spawns.

## First holdout: swapped-spawn loss

After the confirmation win, one predeclared next experiment swapped the spawns
and changed to unseen seed `7778`. Run
`om4-20260810T165728Z-1cf83dad` ended in an official Overmind
`defeat -10` at **1776 sim seconds**. The clean result, replay, and log are under
`artifacts/runs/om4-20260810T165728Z-1cf83dad/`.

This is a real strategy failure, not a runner failure. At tick 3979, both the
winning and losing runs had 64 total units, 39 combat units, a full-health ACU,
and a valid target path. The winner had already launched 36 assigned escorts at
tick 3943. In the holdout, an incoming raid redirected the unassigned combat
force and made the full-health ACU retreat while staging.

The holdout then accumulated **7 staging attempts, 8 pre-push retreats, and 80
pre-push defense orders**. Its first combined push was delayed until tick 9901
with 87 units, 595.8 sim seconds later than the winner. By the end, Easy had
built 85 T2 and 3 T3 units while Overmind4 remained entirely T1.

The dominant defect is therefore not opening throughput, concentration count,
target selection, or path availability. The ready cohort has no persistent
ownership while the ACU stages, so local defense repeatedly steals the offense
and resets release.

## Transactional mobilization result

The coarse replacement binds the attack-ready cohort before staging:

1. clear the exact eligible cohort;
2. order the cohort to guard the exact ACU;
3. move the ACU to staging;
4. commit mobilization/cohort ownership only if all three commands succeed;
5. let only unassigned reserves answer contact;
6. transition the owned survivors into the push, while retaining the 0.75 ACU
   retreat boundary.

The change was developed from 17 focused RED failures. After implementation,
124 policy/controller tests and 369 full tests passed, including transaction
failure, oversized cohort, exact boundary, recycled/dead actor, malformed
position, all-escort-loss rearm, recovery, and LuaPlus/static contracts.

| Final-candidate run | Orientation/seed | Mobilize | Push | Result |
|---|---|---:|---:|---|
| `om4-20260810T172553Z-8c7caf5d` | OM4 slot 2, seed 7778 | tick 3313, 24 | tick 3970, 24 | victory at 656.18s |
| `om4-20260810T172703Z-2b89e778` | OM4 slot 1, seed 7777 | tick 3268, 24 | tick 3952, 24 | victory at 702.08s |

In the formerly losing orientation, the old code did not push until tick 9901.
The new code mobilized at the same original readiness point (tick 3313), kept
the 24 escorts owned through contact, pushed at tick 3970, merged 30
reinforcements at tick 4978, and killed Easy before its late-game tech advantage
formed. This directly supports the causal hypothesis rather than merely showing
a different terminal result.

The final-candidate artifacts are retained at:

- `artifacts/runs/om4-20260810T172553Z-8c7caf5d/`;
- `artifacts/runs/om4-20260810T172703Z-2b89e778/`.

## Preserved stock warning

After Easy's defeat result, stock FAF `lua/platoon.lua:1528` logged a
`GetLocationCoords` nil-method error while cleaning up an Easy platoon. The
Overmind brain then emitted its matching terminal victory, FAF emitted the
official Overmind victory, and valid `JsonStats` followed.

The runner records this as `warnings: ["lua-error"]` while retaining the
official win. It does not generally ignore Lua errors: errors before startup
completion, errors without matching terminal/official results, conflicting or
duplicate results, desyncs, termination failures, and preferences cleanup
failures still fail closed.

## Reproduce

From the mod root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\run-one.ps1 `
  -Map SCMP_007 -Seed 7777 -Speed 25 -SimTime 1800 -WallTime 600
```

The runner creates a unique artifact directory and isolated preferences file.
It validates pinned FAF hashes and the map fingerprint before launch.

## Claim boundary and next gate

Proven:

- fully custom Overmind decisions beat FAF Easy in both declared UEF/Open Palms
  spawn orientations (seeds 7777 and 7778);
- the opening, concentration, commander push, reinforcement, and retreat paths
  all executed in the live engine;
- lifecycle, official result, log, replay, statistics, and cleanup were
  captured by the isolated runner.

Not yet proven:

- additional unseen seeds, other factions, maps, reclaim layouts, or victory
  settings;
- reliable win rate against Easy;
- the `medium` personality configuration;
- T2/T3, naval, transport, or general scouting/endgame competence;
- any competitiveness against M28.

The next promotion step is a tiny predeclared Easy holdout gate, then the stock
`medium` personality if it stays positive. Long-game tech/economy remains the
largest known fallback gap if an early commander push does not finish. Full
batches remain a milestone tool, not the daily strategy-development loop.
