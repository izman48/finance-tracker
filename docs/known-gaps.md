# Known gaps

Found while writing `docs/features/` (October 2026) by reading the code;
items marked *(inferred)* were not reproduced. Fix one, delete its line, and
update the feature doc's touchpoints. Security-relevant items are marked 🔒.

## Missed touchpoints (the "budgets in demo mode" class)

- `test_reset_purge.py` only guards tables with encrypted columns;
  `budget_nudges` is purged but not seeded or checked.
- Claude's `create_rule_pack` isn't in `planning_writes.TARGETS`: no Changes
  entry, no undo.

- A credit card that owes money with no repayment set up is left out of the
  forecast, safe to spend and Coming up. The UI says so and links to its
  settings (T-10-12), but nothing is projected for it (owner D8: a notice, no
  fallback payment). See [features/accounts.md](features/accounts.md).

- 🔒 Ending a bank connection at TrueLayer (delete-account, disconnect) uses
  the documented `DELETE {auth}/api/delete`, refreshing once on 401, but it is
  **unverified** against the TrueLayer sandbox: nobody has yet checked that
  the old refresh token then fails with `invalid_grant` (T-12-10a, sec-2 on
  #244).

## Validation and safety

- 🔒 No tests for the `reset-password` or `oauth/register` throttles.
- 🔒 Shared rule-pack codes (`token_urlsafe(6)`) are not rate limited on
  preview or import; import doesn't re-run `validate_pattern`.
- 🔒 The main site has no Content-Security-Policy (only extra static sites
  set one).
- No UI or API to list or revoke connected Claude clients.
- Health returns 200 when the database is down, so the deploy smoke test
  can't catch it.

## Behaviour

- Sharing a rule pack drops `counts_as`. The rules UI can't edit a rule's
  pattern, category or counts_as.
- `bankingAPI.disconnectBank` and `assetsAPI.removeValuation` exist but
  nothing calls them; no UI calls `DELETE /assets/{id}/flows/{id}`;
  `GET /analytics/spending/transactions` is unused.
- `visual-check.mjs` skips `/changes`, `/`, `/forgot-password`,
  `/reset-password`, `/r/:code`, `/callback`.

## Stale docs and copy

- `api/mcp/README.md` calls the server read-only, lists 19 of 24 tools and
  omits `finance:budgets.write`. The `create_rule_pack` docstring and the
  landing page's `AiAssistantSection` say the rule pack is the only write.
- Reset-password copy (`routers/auth.py`, `ResetPasswordPage`) omits budgets
  from what a reset without a recovery code deletes.
- `README.md`: token lifetime (30 min vs 7 days), test command, no mention of
  per-user encryption, Claude, budgets, Wealth, rules or demo mode.
- `QUICKSTART.md`: test credentials that nothing creates, old navigation.
- `TRUELAYER_GUIDE.md`: hard-coded sandbox client id, old `/banking/status`
  shape. `REDESIGN_PLAN.md`: "three tabs", unticked shipped items,
  instrument pricing that was dropped. `DEPLOY.md` architecture omits `mcp`.
- `.env.example` lacks `FRONTEND_URL` and `SMTP_*`; its `ENCRYPTION_KEY`
  comment says "bank tokens" only.
- `CurrentUserOrMcpSync` is defined but unused; `POST /banking/sync` uses
  `scoped_caller(SCOPE_SYNC)` directly.
