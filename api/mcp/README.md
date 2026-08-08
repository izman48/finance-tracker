# Finance Tracker — MCP server

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes your cashflow data as tools, so an MCP client (Claude Code, Claude Desktop)
can analyse it conversationally — "which month was worst?", "can I afford X?",
"what's driving my spending?".

It's a thin client over the running REST API, so it's **fully isolated** from the
backend's dependencies.

## Tools

| Tool | What it returns |
|------|-----------------|
| `cashflow_summary` | safe-to-spend, available cash, overdraft cushion, credit owed, net worth, next repayments |
| `forecast(horizon)` | balance projection timeline, lowest point, breaches, dated events |
| `spending(period)` | credit-vs-cash breakdown by category & merchant (noise filtered) |
| `spending_trend(months)` | real spending per month over the last N months |
| `commitments` | recurring income/expenses |
| `accounts` | balances, types, providers |
| `recent_transactions(page, page_size)` | a page of transactions |
| `rules` | every rule pack and personal rule: pattern, match type/field, category, `counts_as` |
| `rule_impact` | per rule, `matched` vs `effective` (+ amounts), `shadowed`/`dead` flags, and `gaps` — uncategorized merchants ranked by value |
| `preview_rule(pattern, match_type, match_field)` | dry-run a candidate rule: how many transactions it would match, with samples |
| `create_rule_pack(name, rules, description, apply)` | **the only write tool** — create a new pack with all its rules, then backfill |

### Rules: read, propose, and add — but never edit or delete

Everyone starts with zero rules, and building a useful set one rule at a time is
the reason most people never do it. So `create_rule_pack` can add a whole pack in
one request and backfill history.

It is **additive only**. It creates a *new* pack; it cannot edit or delete an
existing pack or rule, and it never overwrites a category you set by hand. The
worst case is a pack you didn't want — deleted in the app, taking its rules with
it. Every pattern is validated before anything is written, so one bad regex fails
the whole request rather than leaving half a pack behind.

Editing and deleting stay in the app, where you see the diff. That boundary is
the point: adding a pack is reversible in one action, whereas an agent quietly
rewriting existing rules is not.

`rule_impact` is the one to reach for when rules have accumulated. `matched`
counts transactions a rule hits; `effective` counts the ones whose category it
actually *decides*. Rules apply best-first, so a rule can match hundreds and
decide none — reported as `shadowed`, and safe to delete. `dead` means it
matches nothing at all.

## Setup

```bash
cd api/mcp
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The backend must be running (`docker compose up`) and you need an app account
(register one in the UI). The server authenticates with that account.

## Register with Claude Code

```bash
claude mcp add finance-tracker \
  --env FINANCE_EMAIL=you@example.com \
  --env FINANCE_PASSWORD='your-password' \
  -- /ABS/PATH/finance-tracker/api/mcp/.venv/bin/python \
     /ABS/PATH/finance-tracker/api/mcp/server.py
```

(Optionally add `--env FINANCE_API_URL=http://localhost:8000/api/v1`.) Restart the
session; the tools appear as `finance-tracker:*`.

## Register with Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "finance-tracker": {
      "command": "/ABS/PATH/finance-tracker/api/mcp/.venv/bin/python",
      "args": ["/ABS/PATH/finance-tracker/api/mcp/server.py"],
      "env": {
        "FINANCE_EMAIL": "you@example.com",
        "FINANCE_PASSWORD": "your-password"
      }
    }
  }
}
```

## Notes

- **Read-only apart from `create_rule_pack`** — nothing here can move money. The one
  write is additive and reversible by deleting the pack. `preview_rule` is a POST
  only because its input is awkward as a query string; it is a dry run and writes
  nothing. Keep new tools on the read side unless there's a reason as clear as
  this one.
- Your login credentials live in the MCP client config (kept locally).
- Tool results are sent to the LLM you're using — only connect it to a model you're
  comfortable sharing financial data with.
