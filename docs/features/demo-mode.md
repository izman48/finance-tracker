# Demo mode ("Anonymize numbers")

A switch in the user menu that replaces the user's real data with a fixed,
self-contained sample account (fake banks, merchants and figures) so the app
can be shown or screenshotted. It is a privacy convenience, not a security
feature. While it is on, the real API is never contacted for reads and every
write is blocked with a toast.

## How it works

- `ui/src/lib/anonymize.ts`: on/off flag in `sessionStorage` (`anon.on`);
  toggling reloads the page so every view refetches.
- `ui/src/services/api.ts`: the axios request interceptor. When on, every
  non-GET (except login and register) is cancelled and fires
  `anonymize:blocked`; every GET gets a local adapter returning
  `sampleResponse(url, params)`.
- `ui/src/lib/sampleAccount.ts`: one authored ledger that every sample view
  is computed from, so figures reconcile. Unknown paths return `{}`.
- `ui/src/components/AnonymizeListener.tsx`: the "Turn off anonymized view
  to make changes" toast. `ui/src/hooks/useAnonymize.ts`.
- Toggle: user menu "Anonymize numbers" / "Show real numbers", and the
  "Anonymized" header chip (`components/Layout.tsx`).

## Adding a feature: make it demoable

`ui/src/lib/sampleCoverage.test.ts` reads every `api.get` in
`services/api.ts` and fails unless its path is either served by
`sampleResponse` or listed in one of two ledgers in `sampleAccount.ts`:

- `UNSAMPLED_BY_DESIGN`: reads that must not be faked (they start real
  flows), with the reason.
- `KNOWN_DEMO_GAPS`: reads that should be sampled but aren't yet, with what
  breaks.

So for a new read endpoint:

1. Add sample data derived from the sample ledger (never hand-typed totals
   that can disagree with it) and route the path in `sampleResponse`.
2. Add a reconciliation test in `sampleAccount.test.ts` when the figure is
   a sum of other figures.
3. If the feature adds fields to an existing response (like budgets adding
   `budget_projection` to the forecast), add them to that sample response
   too. The coverage test can't see missing fields.
4. A read that is a POST (like `POST /api/v1/budgets/suggest`) is blocked in demo
   mode; prefer GET for reads.

Fixing a gap: serve it, then delete its `KNOWN_DEMO_GAPS` line. The test then
insists it stays served.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | none (UI only). |
| 2 Purge | n/a. |
| 3 Deletion | n/a. |
| 4 Demo mode | This feature. Current gaps: `/budgets`, `/budgets/history`, `/banking/sync-status`, `/analytics/accounts/:param/repayments`, `/rules/shared/:param`. |
| 5 Ownership | n/a. |
| 6 Scopes | n/a. |
| 7 Claude tools | none. |
| 8 Audit | n/a. |
| 9 Bank sync | Sync POSTs are blocked; login while on still tries one (gap). |
| 10 Home | Home is fully served. |
| 11 UI routes | none of its own. |
| 12 Tests | `ui/src/lib/sampleCoverage.test.ts`, `ui/src/lib/sampleAccount.test.ts`. |
| 13 Docs | `REDESIGN_PLAN.md` has the history. |
