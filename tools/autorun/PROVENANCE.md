# Autorun provenance

This is a fresh implementation for the pinned FAF 3836 deployment. Its
single-process lifecycle, completion checks, retained artifacts, and concise
reports were informed by the user's local
`development-tools/tools/run_match_batch.ps1`. No Overmind3-specific parser or
strategy code was copied.

The command-line session-hook approach was also informed by the MIT-licensed
[`HardlySoftly/FAF-AI-Autorun`](https://github.com/HardlySoftly/FAF-AI-Autorun)
at historical commit `7a9480250f8201980c89721c73b6e6ed3ffb52e2`. This
hook is a fresh implementation against FAF build 3836 source commit
`602185eb0753d205080313cc294d5665b49681cb`; it does not copy that project's
stale `SinglePlayerLaunch.lua` override.

