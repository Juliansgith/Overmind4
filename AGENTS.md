# Overmind4 Development Workflow

The primary validation surface is a real FAF match against Adaptive. Optimize
for fast live feedback, not speculative test coverage.

## Match-first iteration

- Launch a 600-sim-second canary within 10 minutes of each meaningful AI change.
- Diagnose the single dominant failure from the match artifact, fix that cause,
  and immediately run the next match.
- Prefer observable gameplay results over mocked confidence. A green unit test
  suite does not prove that the AI builds, expands, fights, or wins.
- If diagnosis is uncertain, add narrow telemetry and rerun the match instead of
  building a large speculative implementation or test matrix.

## Targeted TDD only

- Before a bug fix, write the smallest regression test that reproduces the
  concrete failure seen in a real match.
- Run only the directly affected test or test file, normally with
  `-q --tb=short --maxfail=1`.
- Do not create broad permutation, property, red-team, or exhaustive edge-case
  suites before the gameplay behavior has been validated live.
- Add broader regression coverage only after the live fix demonstrably improves
  the match and the behavior is worth preserving.
- Do not run the full repository suite between match iterations. Run it once
  before final promotion or release.

## Time and context budget

- Target one complete diagnose-test-fix-match loop every 10-15 minutes.
- Do not start repeated spec-review or quality-review loops between canaries.
- Use subagents only for short, bounded work that directly accelerates the next
  match; do not use multiple agents to generate large speculative test suites.
- Query only the relevant telemetry fields and fatal log lines. Do not dump full
  logs or full passing-test output into context.
- Stop expanding scope when a safe match can provide the next useful fact.

## Promotion

- Use targeted tests during development to protect already validated behavior.
- Use the full suite, independent review, multi-seed runs, and the complete
  5/10/20/40 km matrix only when a candidate has first shown strong live results.
- The promotion goal remains reliable wins against FAF Adaptive across all map
  sizes; development-process completeness is not a substitute for that result.
