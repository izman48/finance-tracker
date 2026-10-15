# Categorisation and rules

Turns transactions into categories. Provider data gives a safe start
(Transfers, Income); user rules (pattern → category, optional "counts as")
do the rest. Rules are grouped in packs that can be switched off, shared by
link and imported. Hand-categorising a transaction learns a rule. Claude can
create a whole pack in one call.

## Code

**API** (`api/app/routers/rules.py`):

| Route | Auth |
|---|---|
| `GET /api/v1/rules` | `CurrentUserOrMcpRead` |
| `POST /api/v1/rules` | `CurrentUser` (does not auto-apply) |
| `PATCH /api/v1/rules/{rule_id}` | `CurrentUser` |
| `DELETE /api/v1/rules/{rule_id}` | `CurrentUser` |
| `POST /api/v1/rules/preview` | `CurrentUserOrMcpRead`; per-user limit (`rules-preview`, T-12-10b) |
| `GET /api/v1/rules/impact` | `CurrentUserOrMcpRead` (shadowed and dead rules, gaps); per-user limit (`rules-impact`) |
| `POST /api/v1/rules/apply` | `CurrentUser` |
| `POST /api/v1/rules/packs` | `CurrentUser` |
| `POST /api/v1/rules/packs/bulk` | `CurrentUserOrMcpRulesWrite` (up to 200 rules, validated first) |
| `PATCH /api/v1/rules/packs/{pack_id}` | `CurrentUser` |
| `DELETE /api/v1/rules/packs/{pack_id}` | `CurrentUser` |
| `POST /api/v1/rules/packs/{pack_id}/share` | `CurrentUser` (plaintext `share_snapshot`) |
| `DELETE /api/v1/rules/packs/{pack_id}/share` | `CurrentUser` |
| `GET /api/v1/rules/shared/{share_code}` | `CurrentUser` (any user) |
| `POST /api/v1/rules/import` | `CurrentUser` (re-encrypted under the importer's key) |

**Tables**: `rule_packs` (plaintext, including the share snapshot),
`category_rules` (encrypted `pattern`).

**Services**: `services/categorization.py`: `category_from_provider`,
`validate_pattern`, precedence (own beats imported; exact beats contains
beats regex; longer beats shorter), `apply_rules` (respects per-field locks),
`learn_and_apply`.

**UI**: `/rules` (`RulesPage`, user menu), `AddRuleModal` (also from
Spending), `ImportRulePackModal`, `/r/:code` (`ImportSharedPage`).

**MCP**: `rules`, `rule_impact`, `preview_rule`, `create_rule_pack`.

**Tests**: `api/tests/integration/test_rules_bulk.py`,
`test_rules_impact.py`, `test_user_encryption.py`, `test_oauth.py`;
`api/tests/unit/test_rule_engine.py`, `test_provider_category.py`,
`test_category_backfill_migration.py`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `rule_packs`, `category_rules`. |
| 2 Purge | Yes, both (kills share links). |
| 3 Deletion | Cascade from `users`. |
| 4 Demo mode | `/rules` served empty. **Gap**: `/rules/shared/:param` in `KNOWN_DEMO_GAPS`. |
| 5 Ownership | n/a; packs and rules checked by owner. |
| 6 Scopes | Reads `finance:read`; bulk pack `finance:rules.write`; everything else web only. |
| 7 Claude tools | listed above. |
| 8 Audit | **Gap**: `create_rule_pack` is not in `TARGETS`, so it has no Changes entry or undo. |
| 9 Bank sync | `apply_rules` runs on every new transaction. |
| 10 Home | n/a. |
| 11 UI routes | `/rules`, `/r/:code`. |
| 12 Tests | listed above. |
| 13 Docs | `api/mcp/README.md` rules policy. |
