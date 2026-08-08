"""Finance Tracker MCP server.

A thin, read-only Model Context Protocol server that exposes your cashflow data
(safe-to-spend, forecast, spending, commitments, savings goals, transactions,
categorization rules) as tools so an MCP client (e.g. Claude) can analyse it
conversationally.

Read-only with ONE deliberate exception: create_rule_pack, which creates a new
rule pack and backfills. It is additive — it cannot edit or delete an existing
pack or rule, and it never overwrites a category the user set by hand — so the
worst case is a pack the user deletes in the app. Nothing else here writes, and
nothing else should: editing and deleting stay where the user sees the diff.

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


def _post(path: str, payload: dict):
    """POST an API endpoint. Used ONLY for dry-run reads whose inputs are too
    awkward for a query string (/rules/preview). Every tool here must leave the
    user's data unchanged — do not reach for this to add a mutating tool."""
    if not _token["value"]:
        _login()
    for attempt in (1, 2):
        r = httpx.post(
            f"{API}{path}",
            json=payload,
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


@mcp.tool()
def rules() -> dict:
    """Categorization rules: every rule pack with its rules, plus pack-less personal rules. Each rule has a pattern, match_type (exact|contains|regex), match_field (any|merchant|description), the category it assigns, and an optional counts_as (spending|transfer|card_payment) that reclassifies the transaction as noise."""
    return _get("/rules")


@mcp.tool()
def rule_impact() -> dict:
    """What the existing rules actually do, and where the gaps are. Per rule: `matched` (transactions it matches) vs `effective` (transactions whose category it actually decides) with amounts — a rule can match many and decide none because a higher-precedence rule wins first, flagged as `shadowed`; `dead` means it matches nothing. Also returns `gaps`: the merchants no rule categorizes, ranked by total value — the best candidates for a new rule."""
    return _get("/rules/impact")


@mcp.tool()
def preview_rule(
    pattern: str,
    match_type: str = "contains",
    match_field: str = "any",
) -> dict:
    """Dry-run a rule you're considering before proposing it: how many transactions the pattern would match, out of how many total, with up to 5 samples. Changes nothing. match_type is exact|contains|regex, match_field is any|merchant|description."""
    return _post(
        "/rules/preview",
        {"pattern": pattern, "match_type": match_type, "match_field": match_field},
    )


@mcp.tool()
def create_rule_pack(
    name: str,
    rules: list[dict],
    description: str = "",
    apply: bool = True,
) -> dict:
    """Create a NEW rule pack with all its rules in one go, then backfill history. This is the only tool here that writes.

    Each entry in `rules` is {"pattern", "category", "match_type"?, "match_field"?, "counts_as"?}: match_type is exact|contains|regex (default contains), match_field is any|merchant|description (default any), counts_as is spending|transfer|card_payment and reclassifies the transaction as noise so it leaves the spending figures.

    Additive only — it creates a new pack and can never edit or delete an existing one, so the worst case is a pack the user removes in the app, which cascades to its rules. Categories the user set by hand are never overwritten. Every pattern is validated before anything is written, so one bad regex fails the whole request rather than leaving half a pack behind. Preview patterns with preview_rule first, and show the user what you intend to create before calling this."""
    return _post(
        "/rules/packs/bulk",
        {"name": name, "description": description or None, "rules": rules, "apply": apply},
    )


if __name__ == "__main__":
    mcp.run()
