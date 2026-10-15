## What changed

Before:

After:

## Touchpoints

Walk the checklist in `docs/features/README.md` for every feature this PR
touches. Tick what you handled; strike through what doesn't apply.

- [ ] Feature doc in `docs/features/` updated (routes, tables, UI, tools, touchpoints)
- [ ] Migration is additive with a working `downgrade()`
- [ ] Key-loss purge (`services/key_loss_purge.py`) and account-deletion cascade cover new tables
- [ ] Demo mode: any change to what a screen shows updates the sample account (`ui/src/lib/sampleAccount.ts`) in this PR, derived fields (e.g. `budget_projection`) and nudges included; new reads are served by `sampleResponse`. A new `KNOWN_DEMO_GAPS` entry needs the owner's OK
- [ ] Account ids go through `core/ownership.py`
- [ ] Auth dependency is the narrowest that works (web-only by default)
- [ ] Claude tools: annotations, `test_tool_annotations.py`, `api/mcp/README.md`; writes go through `run_write` with `TARGETS`
- [ ] Home card / owning tab, nav and `visual-check.mjs` updated if a page changed
- [ ] Tests written first; `docs/known-gaps.md` updated if this fixes or finds a gap
