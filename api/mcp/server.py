"""Finance Tracker MCP server.

A thin, read-only Model Context Protocol server that exposes your cashflow data
(safe-to-spend, forecast, spending, commitments, savings goals, transactions) as
tools so an MCP client (e.g. Claude) can analyse it conversationally.

It is fully decoupled from the app — it just calls the running REST API — so it
has no dependency on the backend's internals or pinned versions.

Config (env vars):
  FINANCE_API_URL   default http://localhost:8000/api/v1
  FINANCE_EMAIL     your app login email   (required)
  FINANCE_PASSWORD  your app login password (required)

Run:  python server.py        (stdio transport)
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

API = os.environ.get("FINANCE_API_URL", "http://localhost:8000/api/v1").rstrip("/")
EMAIL = os.environ.get("FINANCE_EMAIL", "")
PASSWORD = os.environ.get("FINANCE_PASSWORD", "")

mcp = FastMCP("finance-tracker")
_token: dict = {"value": None}


def _login() -> None:
    r = httpx.post(
        f"{API}/auth/login",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    _token["value"] = r.json()["access_token"]


def _get(path: str, params: dict | None = None):
    """GET an API endpoint, logging in (and retrying once on 401) as needed."""
    if not _token["value"]:
        _login()
    for attempt in (1, 2):
        r = httpx.get(
            f"{API}{path}",
            params=params,
            headers={"Authorization": f"Bearer {_token['value']}"},
            timeout=60,
        )
        if r.status_code == 401 and attempt == 1:
            _login()
            continue
        r.raise_for_status()
        return r.json()


@mcp.tool()
def cashflow_summary() -> dict:
    """Current cashflow: safe-to-spend, available cash, overdraft cushion, credit owed, net worth, next card repayments, and per-account roles."""
    return _get("/analytics/summary")


@mcp.tool()
def forecast(horizon: str = "90") -> dict:
    """Balance projection over a horizon (payday | 30 | 90 | 180 | 365 days). Returns the daily running-balance timeline, the lowest point, end balance, any £0/overdraft breaches, and the dated income/expense/repayment/planned events."""
    return _get("/analytics/forecast", {"horizon": horizon})


@mcp.tool()
def spending(period: str = "since_payday") -> dict:
    """Spending breakdown for a period (since_payday | this_month | last_30). Splits credit-vs-cash and lists categories and top merchants. Internal transfers and card repayments are excluded."""
    return _get("/analytics/spending", {"period": period})


@mcp.tool()
def spending_trend(months: int = 6) -> dict:
    """Real spending per calendar month over the last N months (1-24), with the same noise-filtering — use this to spot which month was especially heavy."""
    return _get("/analytics/spending/trend", {"months": months})


@mcp.tool()
def commitments() -> list:
    """Recurring income and expenses (detected suggestions + confirmed), with amount, cadence and next date."""
    return _get("/analytics/commitments")


@mcp.tool()
def accounts() -> list:
    """Connected bank accounts with balances, types and provider names."""
    return _get("/banking/accounts")


@mcp.tool()
def recent_transactions(page: int = 1, page_size: int = 100) -> dict:
    """A page of transactions (most recent first), for ad-hoc analysis. page_size up to 100."""
    return _get("/banking/transactions", {"page": page, "page_size": min(page_size, 100)})


if __name__ == "__main__":
    mcp.run()
