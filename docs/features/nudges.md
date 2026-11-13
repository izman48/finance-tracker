# Nudges

Short, dismissible facts on the Cashflow tab, each showing its arithmetic
and source: cash drag on savings at a curated rate, FSCS exposure per banking
licence, duplicate confirmed commitments, and budget nudges (from
[budgets.md](budgets.md)).

## Code

**API**: `GET /api/v1/analytics/nudges` (`CurrentUser`). Budget nudges are
dismissed with `POST /api/v1/budgets/nudges/{nudge_id}/dismiss`; other nudges
are dismissed in the browser only. Reading nudges may write `budget_nudges`
rows.

**"Will go over" (T-24-5c):** kind `over_soon`, fired once per budget and
cycle (the `budget_nudges` unique key) the first time spent is under the
limit but spent plus coming up passes it. It's shown only while that holds
and stays gone once dismissed. Its `title`, body and tip are built when
shown from current figures; the row stores none of them. `cta` offers
"Raise to £N", the next multiple of £50 at or above spent plus coming up.
The app applies it through the normal `PATCH /api/v1/budgets/{budget_id}`, hides
the nudge and announces it in a polite live region. A failure leaves the
limit and the nudge as they were, with an alert.

**Tables**: none of its own.

**Services**: `services/analytics/nudges.py`,
`services/reference/uk_reference.py` (FSCS limit, best easy-access rate,
shared-licence brands: constants changed only in code),
`services/budgets.budget_nudges`.

**UI**: `NudgeFeed`, `NudgeRow` on `/dashboard`.

**Tests**: `api/tests/unit/test_nudges.py`;
`api/tests/integration/test_nudges_endpoint.py`,
`test_budget_home_nudges.py`; UI `NudgeRow.test.tsx`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | none. |
| 2 Purge | Inputs purged. |
| 3 Deletion | Inputs cascade. |
| 4 Demo mode | Served (`nudgesResponse`), budget nudges by the API rule (`sampleBudgetNudges`), including "will go over" for the sample Subscriptions budget. Raise is a write, so demo blocks it. |
| 5 Ownership | n/a. |
| 6 Scopes | Web only. |
| 7 Claude tools | none. |
| 8 Audit | n/a. |
| 9 Bank sync | Computed on read. |
| 10 Home | Not on Home. Owned by Cashflow. |
| 11 UI routes | `/dashboard`. |
| 12 Tests | listed above. |
| 13 Docs | Reference values need a periodic check (gap: FSCS limit). |
