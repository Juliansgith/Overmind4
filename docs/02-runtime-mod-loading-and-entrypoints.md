# Runtime, mod loading, and AI entry points

## The execution model

Evidence: **Verified 3836** and
[official Lua-context documentation](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/docs/development-start-here/lua-contexts.md).

FAF runs five isolated Lua contexts:

1. initialization;
2. blueprint loading;
3. main-menu/lobby UI;
4. session UI;
5. session simulation.

Overmind4's brain belongs in the **session simulation** context. All peers run
the same simulation and AI code in lockstep. The brain reads simulation objects
and submits orders locally through engine APIs; commands are not sent to a
separate AI server.

The context boundary is strict:

```text
Session UI context --validated SimCallback--> Session simulation context
Session UI context <--filtered Sync/UserSync-- Session simulation context

                         Overmind4 brain
                         observations |
                                      v
                    pure policy -> order adapter -> Issue*
```

The simulation sandbox does not expose general arbitrary-host `io`, `os`,
native package loading, sockets, HTTP, or subprocess calls. It can load
whitelisted/mounted game and mod resources through FAF's virtual APIs such as
`import`, `doscript`, `DiskFindFiles`, and limited file-info facilities; that is
not arbitrary host filesystem access or a writable external IPC channel. The
[Lua runtime documentation](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/docs/development-start-here/lua-syntax.md)
describes LuaPlus 5.0.1 build 1081 and the context restrictions.

Consequences:

- an external Python/LLM/RL process cannot be the live controller of a normal
  vault-distributable AI;
- an external harness may launch the graphical executable, choose scenarios,
  accelerate games, parse logs, and aggregate results;
- offline training may produce constants, lookup data, rules, or a compact
  deterministic model loaded with the mod;
- any experimental memory-patching or injected IPC would be outside the normal
  FAF mod model, unsafe for multiplayer, and out of scope.

## Lua dialect and portable policy code

FAF uses LuaPlus rather than modern stock Lua. It supports nonstandard features
such as `!=`, `continue`, bitwise operators, and table preallocation syntax.
Existing game code uses these extensions.

For Overmind4:

- engine adapters may use the deployed dialect where required;
- pure decision modules should use a conservative Lua 5.0-compatible subset so
  they can run under a small external test harness;
- do not assume Lua 5.1+ library functions, integer semantics, metamethod
  behavior, module loaders, or standard filesystem APIs;
- syntax validation must use FAF's Lua compiler/container, not just a modern
  desktop `lua.exe`.

## Current mod discovery

Evidence: **Verified 3836** in
[`init_faf.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/init_faf.lua)
and [`lua/MODS.LUA`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/MODS.LUA).

FAF scans unpacked mod folders for `mod_info.lua` and mounts **every valid mod
directory** at `/mods/<folder-name-lowercased>`. Mounting only makes its
namespace addressable; enabled/active simulation-mod selection and dependency
ordering are a separate `MODS.LUA`/game-options stage. Only active sim mods
contribute their hooks and custom-AI discovery. The physical Windows directory
is not the import path.

The current mod-format fields are documented in
[`lua/MODS.LUA`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/MODS.LUA):

| Field | Guidance |
|---|---|
| `name` | Human-facing mod name |
| `uid` | Globally unique release identifier |
| `version` | Integer version |
| `description`, `author`, `url` | Metadata |
| `selectable`, `enabled` | Usually `true` for a vault mod |
| `ui_only` | Must be `false` for an AI simulation mod |
| `requires` | Hard dependencies by UID |
| `conflicts` | Mutually incompatible UIDs |
| `before`, `after` | Ordering constraints, used sparingly |

FAF's format guidance says a published new version should get a new UID. Before
the first release, choose and document the release/version policy explicitly so
benchmark manifests can distinguish builds.

Dependency cycles can make deterministic mod ordering impossible. Avoid
ordering constraints unless the mod truly hooks the same symbol as another mod.

## Minimal future layout

This is a research target, not code created by this phase:

```text
Overmind4/
  mod_info.lua
  hook/
    lua/
      aibrains/
        index.lua
  lua/
    AI/
      CustomAIs_v2/
        Overmind4AI.lua
      LobbyTooltips/
        tooltips.lua
      LobbyOptions/
        lobbyoptions.lua            # optional
      Overmind4/
        Brain.lua
        ...
  tests/
    unit/
    contracts/
    engine/
  docs/
```

The first production files must only be added after contract tests fail for
their absence and expected exports.

## AI list discovery

Evidence: **Verified 3836** in
[`lua/ui/lobby/aitypes.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/ui/lobby/aitypes.lua).

For every active simulation mod, the lobby scans
`/lua/AI/CustomAIs_v2/*.lua`, imports the module's top-level `AI` table, then
reads:

- `AI.AIList` for fair/non-cheat personalities;
- `AI.CheatAIList` for AIX/cheating personalities.

Each entry includes a unique `key`, a human-facing `name`, and lobby rating
metadata. Overmind4's fair personality should exist only in `AIList`. Do not
create a cheat variant until there is a specific test reason; it makes baseline
selection errors more likely.

Conceptual outer shape:

```lua
AI = {
    Name = 'AI: Overmind4',
    Version = '1',
    AIList = {
        -- personality entries
    },
    CheatAIList = {},
}
```

A minimal registration shape can be studied in
[Mini27's custom AI data](https://github.com/maudlin27/Mini27AI/blob/74dec9b15747bbfa2007da74f5569709b97bc451/lua/AI/CustomAIs_v2/M27AIData.lua).

The exact personality key becomes the contract joining three surfaces:

```text
CustomAIs_v2 entry key
        ==
hook/lua/aibrains/index.lua keyToBrain key
        ==
scenario/lobby AIPersonality value
```

A typo or capitalization mismatch can show an AI in the lobby but fail during
brain construction.

## Brain-class registration

Evidence: **Verified 3836** in
[`lua/simInit.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/simInit.lua)
and
[`lua/aibrains/index.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/aibrains/index.lua).

When FAF creates an army brain, it imports `/lua/aibrains/index.lua`, looks up
the army's personality key in `keyToBrain`, and applies the selected class to
the engine brain. A normal user mod extends that index through:

`hook/lua/aibrains/index.lua`

Conceptual shape:

```lua
local Overmind4Brain = import('/mods/overmind4/lua/AI/Overmind4/Brain.lua')

keyToBrain = keyToBrain or {}
keyToBrain.overmind4 = Overmind4Brain.NewAIBrain
```

The exact code belongs to the implementation phase and needs a failing contract
test first. Despite its name, `NewAIBrain` in this established pattern is the
`Class(StandardBrain) { ... }` class table, not a constructor invocation.
`OnCreateArmyBrain` also supports a `{ modulePath, exportedClassName }`
reference pair and then applies the resolved class table as the brain metatable.

## Hook semantics

FAF hooks are not monkey-patches loaded after a module. On first import, files
at the matching `/hook/...` path are concatenated with the original module.
See the
[official setup/hooking explanation](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/setup/setup-english.md).

Rules:

- use `/hook` for a normal user mod;
- do not follow old AI-wiki advice to install a user AI through `/schook`;
- keep hook-local names inside `do ... end` when collision is possible;
- preserve and call the previous function/class when extending behavior;
- deliberately document any full replacement;
- assume another mod may hook the same file;
- never rely on arbitrary active-mod order when dependencies do not enforce it.

Blueprint files and supported AI builder/template directories are loaded through
separate mechanisms and usually do not need hook files.

## Optional AI mod directories

When a custom AI mod is detected, `BeginSessionAI` can import its:

- `lua/AI/PlatoonTemplates`;
- `lua/AI/AIBuilders`;
- `lua/AI/AIBaseTemplates`.

The lobby/UI can also load:

- `lua/AI/LobbyTooltips/tooltips.lua`;
- `lua/AI/LobbyOptions/lobbyoptions.lua`;
- localization strings through the normal localization system.

Overmind4 should not create builder/base-template directories merely because
the loader supports them. A clean custom controller can reuse stable engine
utilities without adopting the stock builder-manager architecture.

## Brain lifecycle

The primary Lua class is
[`lua/aibrain.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/aibrain.lua),
which extends `moho.aibrain_methods`.

Important lifecycle sequence:

| Callback | Safe responsibilities |
|---|---|
| `OnCreateAI(planName)` | Initialize plain tables/config, call the parent, install callbacks; initial units/resources may not exist |
| `CreateBrainShared(planName)` | Shared brain setup used by the base implementation |
| `OnBeginSession()` | Initial units, props, map resources, and scenario state now exist; initialize world/map/nav and start the scheduler |
| Unit/intel callbacks | Append normalized events; keep callback work small |
| `OnVictory`, `OnDefeat`, `OnDraw` | Emit result once, stop accepting work |
| `OnDestroy` | Destroy triggers/threads and release retained references |

Use `self:ForkThread(...)`, not bare `ForkThread(...)`, for brain-owned threads.
The brain method adds the thread handle to its `Trash`, allowing defeat and
destruction to clean it up.

Persistent loops must yield. `WaitTicks` is effectively
`coroutine.yield`; `WaitSeconds` converts seconds to simulation ticks in
[`lua/simInit.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/simInit.lua).

## Stock Easy and Normal benchmark detail

The deployed
[`lua/aibrains/index.lua`](https://github.com/FAForever/fa/blob/602185eb0753d205080313cc294d5665b49681cb/lua/aibrains/index.lua)
maps both:

- `easy` -> `/lua/aibrains/medium-ai.lua`;
- `medium` -> `/lua/aibrains/medium-ai.lua`.

The lobby displays different labels/ratings, and other code can still inspect
the personality string, so run both keys. However, do not interpret wins over
them as progress across two independently implemented stock brain tiers.

The interim goal should be written as:

> Beat the deployed stock `medium-ai.lua` brain through both `easy` and
> `medium` personality keys under the pinned benchmark matrix.

## Registration test contract

Before writing the files above, create failing tests that prove:

- `mod_info.lua` exists, parses, is a simulation mod, and exposes required
  metadata with a valid UID/version;
- exactly one fair Overmind4 key appears in `AIList`;
- no accidental entry appears in `CheatAIList`;
- the key is lowercase, stable, and identical in the brain-index hook;
- the registered value is a class table or supported module/export reference
  accepted by `OnCreateArmyBrain`;
- the brain derives from the expected standard brain;
- parent lifecycle methods are called in the intended order;
- no world query is made in `OnCreateAI`;
- the scheduler starts once in `OnBeginSession`;
- defeat/destroy stops and cleans all owned threads;
- a missing optional tooltip/options file does not break simulation loading;
- two active AI mods can extend `keyToBrain` without overwriting one another.

Then implement only the smallest loading brain that emits a structured
lifecycle log. Strategy belongs in later red-green-refactor slices.
