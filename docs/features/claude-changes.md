# Claude's changes (write framework, audit, undo, keep)

Every write Claude makes goes through one safe path: dry run by default,
idempotent, rate limited, recorded in an encrypted append-only audit trail,
and shown on the "Changes made by Claude" page where the user can undo it.
Claude's changes to commitments and removals of planned expenses are held
(they don't affect safe to spend) until the user keeps them.

## Code

**Write framework**:

- `core/planning_write.py`: `PlanningWriter` (`finance:planning.write`),
  `BudgetsWriter` (`finance:budgets.write`) and `RulesEditor`
  (`finance:rules.edit`) return a `Caller` (user plus
  verified `grant_id`, `client_id`) and apply per-user limits (30 writes and
  120 dry runs per hour, in process). `dry_run` must be a JSON body field.
- `services/planning_writes.py`: `TARGETS` (`planned_event`, `commitment`,
  `budget`, `rule`, each with allow-listed fields), `run_write` (dry run in a
  savepoint; apply claims the idempotency key, writes, records an audit row), and a retry of an applied write with the same key and request replays the stored result, even where a route checks its target first (`replay_if_applied`, T-12-9c; a different request under the key is a 409),
  `run_batch`, `undo_write`, `claude_markers`, `key_in_use`.
- Routers using it: `routers/planning.py`, `routers/commitment_writes.py`,
  `routers/budget_writes.py`, `routers/rule_writes.py` (undoing a rule edit
  re-runs the rules over the user's history).

**Audit API** (`api/app/routers/audit.py`, web session only, must stay so):

- `GET /api/v1/audit` (newest first, cursor paged)
- `POST /api/v1/audit/{audit_id}/undo`
- `POST /api/v1/audit/{audit_id}/keep` (409 when there is nothing to keep)

**Tables**: `audit_entries` (encrypted `target_label`, `changes`;
`undone_at`, `kept_at`, `user_set_fields`), `write_idempotency` (24 h,
keyed request hash).

**Services**: `services/claude_keep.py` (keep states, held-back totals,
`record_user_edit`).

**UI**: `/changes` (`ChangesPage`, user menu "Changes made by Claude"),
`components/changes/ChangesView`, `ChangeList`, `ChangeRow`,
`UndoControls`, `KeepControls`, `ClaudeMarker` (also shown on budgets and
commitments), `lib/changes.ts`, `lib/keep.ts`.

**Tests**: `api/tests/integration/test_planning_writes.py`,
`test_planning_write_auth.py`, `test_audit_api.py` (route set is exactly
list, undo, keep), `test_keep_commitment_api.py`,
`test_planned_removal_hold.py`, `test_no_claude_raise.py`; UI tests next to
each `changes/` component, `changes.test.ts`, `keep.test.ts`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `audit_entries`, `write_idempotency`. |
| 2 Purge | Yes, both. |
| 3 Deletion | Cascade from `users`. |
| 4 Demo mode | `/audit` served as an empty list; undo and keep blocked. |
| 5 Ownership | Targets with account ids check them before `run_write`. |
| 6 Scopes | Audit routes web only; writes need the target's scope. |
| 7 Claude tools | Every write tool except `create_rule_pack` and `refresh_banks`. |
| 8 Audit | This feature. A new Claude-writable entity needs a `TARGETS` entry and Changes-page copy in `lib/changes.ts`. |
| 9 Bank sync | n/a. |
| 10 Home | n/a. |
| 11 UI routes | `/changes`. |
| 12 Tests | listed above. |
| 13 Docs | `CLAUDE.md` "Remote MCP / OAuth". |
