# One-match development runner

The daily loop runs one fresh-process Overmind4-versus-stock-Easy match at
25x requested simulation speed. Begin with a no-write preflight:

```powershell
.\tools\run-one.ps1 -DryRun
```

Then launch the pinned match explicitly:

```powershell
.\tools\run-one.ps1 -Map SCMP_007 -Seed 7777 -Speed 25
```

The runner refuses to start if the inspected FAF 3836 executable, `init.lua`,
or `lua.nx2` has changed. A real run creates a unique directory beneath
`artifacts/runs` containing its immutable manifest, exact log, replay, JSON
result, and short Markdown result. It never searches for the newest log and
terminates only the process tree it launched.

Use `-OurSlot 2 -OpponentSlot 1` to swap spawn orientation. Run `Get-Help
.\tools\run-one.ps1 -Detailed` or inspect the parameter block for the remaining
map, AI, faction, team, simulated-time, wall-time, and output controls.

