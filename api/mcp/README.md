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

### Rules: read and propose, never write

An assistant can read your rules, measure what they actually do, and dry-run a
proposal — but creating, editing and deleting rules stays in the app, where you
see the diff before it applies. That's deliberate: rules rewrite history across
every matching transaction, so the blast radius of a bad one is large and not
obvious at the point of creation.

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

- **Read-only** — it can't move money or change anything. `preview_rule` is a POST
  only because its input is awkward as a query string; it is a dry run and writes
  nothing. Keep it that way when adding tools.
- Your login credentials live in the MCP client config (kept locally).
- Tool results are sent to the LLM you're using — only connect it to a model you're
  comfortable sharing financial data with.
