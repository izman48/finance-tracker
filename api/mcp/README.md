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

- **Read-only** — it only ever GETs; it can't move money or change anything.
- Your login credentials live in the MCP client config (kept locally).
- Tool results are sent to the LLM you're using — only connect it to a model you're
  comfortable sharing financial data with.
