"""Finance Tracker MCP server.

A thin Model Context Protocol server that exposes your cashflow data
(safe-to-spend, forecast, spending, commitments, savings goals, transactions,
categorization rules) as tools so an MCP client (e.g. Claude) can analyse it
conversationally.

Read-only with ONE deliberate exception: create_rule_pack, which creates a new
rule pack and backfills. It is additive — it cannot edit or delete an existing
pack or rule, and it never overwrites a category the user set by hand — so the
worst case is a pack the user deletes in the app. Nothing else here writes, and
nothing else should: editing and deleting stay where the user sees the diff.
Remotely it additionally needs the `finance:rules.write` scope.

It is fully decoupled from the app — it just calls the REST API — so it has no
dependency on the backend's internals or pinned versions.

Config (env vars) — see config.py:
  MCP_TRANSPORT     stdio (default) | http
  FINANCE_API_URL   default http://localhost:8000/api/v1
  stdio:  FINANCE_EMAIL, FINANCE_PASSWORD   your app login
  http:   MCP_PUBLIC_URL (https://your.domain), MCP_HOST, MCP_PORT (8001)

Run:  python server.py
"""
import os
import sys

import httpx
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from api_client import ApiClient, PasswordCredentials, RequestBearerCredentials
from auth import SCOPE_READ, SCOPE_RULES_WRITE, TokenInfoVerifier
from config import ConfigError, Settings


def create_server(settings: Settings, api_transport: httpx.AsyncBaseTransport | None = None) -> FastMCP:
    """Build the server for the configured transport. `api_transport` lets tests fake the API."""
    if settings.transport == "http":
        credentials = RequestBearerCredentials()
        mcp = FastMCP(
            "finance-tracker",
            host=settings.host,
            port=settings.port,
            # Tools are stateless, so no session affinity is needed behind a proxy.
            stateless_http=True,
            json_response=True,
            token_verifier=TokenInfoVerifier(settings.api_url, settings.resource_url, api_transport),
            auth=AuthSettings(
                issuer_url=settings.public_url,
                resource_server_url=settings.resource_url,
                required_scopes=[SCOPE_READ],
            ),
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[settings.public_host],
                allowed_origins=[settings.public_url],
            ),
        )
    else:
        credentials = PasswordCredentials(settings.api_url, settings.email, settings.password)
        mcp = FastMCP("finance-tracker")

    api = ApiClient(settings.api_url, credentials, api_transport)

    @mcp.tool()
    async def cashflow_summary() -> dict:
        """Current cashflow: safe-to-spend, available cash, overdraft cushion, credit owed, net worth, next card repayments, and per-account roles."""
        return await api.get("/analytics/summary")

    @mcp.tool()
    async def forecast(horizon: str = "90") -> dict:
        """Balance projection over a horizon (payday | 30 | 90 | 180 | 365 days). Returns the daily running-balance timeline, the lowest point, end balance, any £0/overdraft breaches, and the dated income/expense/repayment/planned events."""
        return await api.get("/analytics/forecast", {"horizon": horizon})

    @mcp.tool()
    async def spending(period: str = "since_payday", frm: str = "", to: str = "", lens: str = "money_out") -> dict:
        """Spending breakdown by category and merchant for a period (since_payday | this_month | last_30), or for ANY date range by passing frm and to as YYYY-MM-DD.

        lens matters and the two are NOT comparable to each other:
        - 'money_out' (default): cash that left spending accounts, reconciling to a bank statement — includes the card bill on the day it's paid, not the purchases that built it. `composition` names what's inside (transfers/card_repayments/commitments/other).
        - 'purchases': spend booked when it happened — card purchases + cash purchases, excluding transfers and card repayments so a purchase is never double-counted with its later repayment. This is what spending_trend uses, so use 'purchases' when comparing a custom range against spending_trend's monthly totals — mixing lenses gives numbers that look wrong because they answer different questions, not because anything is broken.

        Use the date range for long-run questions the fixed periods can't answer — what a specific expensive month actually went on, or how one year compares with the next."""
        params = {"lens": lens}
        if frm and to:
            params.update(period="custom", frm=frm, to=to)
        else:
            params["period"] = period
        return await api.get("/analytics/spending", params)

    @mcp.tool()
    async def spending_trend(months: int = 6) -> dict:
        """Real spending per calendar month over the last N months (1-24), with the same noise-filtering — use this to spot which month was especially heavy."""
        return await api.get("/analytics/spending/trend", {"months": months})

    @mcp.tool()
    async def commitments() -> list:
        """Recurring income and expenses (detected suggestions + confirmed), with amount, cadence and next date."""
        return await api.get("/analytics/commitments")

    @mcp.tool()
    async def accounts() -> list:
        """Connected bank accounts with balances, types and provider names."""
        return await api.get("/banking/accounts")

    @mcp.tool()
    async def recent_transactions(page: int = 1, page_size: int = 100) -> dict:
        """A page of transactions (most recent first), for ad-hoc analysis. page_size up to 100."""
        return await api.get("/banking/transactions", {"page": page, "page_size": min(page_size, 100)})

    @mcp.tool()
    async def rules() -> dict:
        """Categorization rules: every rule pack with its rules, plus pack-less personal rules. Each rule has a pattern, match_type (exact|contains|regex), match_field (any|merchant|description), the category it assigns, and an optional counts_as (spending|transfer|card_payment) that reclassifies the transaction as noise."""
        return await api.get("/rules")

    @mcp.tool()
    async def rule_impact() -> dict:
        """What the existing rules actually do, and where the gaps are. Per rule: `matched` (transactions it matches) vs `effective` (transactions whose category it actually decides) with amounts — a rule can match many and decide none because a higher-precedence rule wins first, flagged as `shadowed`; `dead` means it matches nothing. Also returns `gaps`: the merchants no rule categorizes, ranked by total value — the best candidates for a new rule."""
        return await api.get("/rules/impact")

    @mcp.tool()
    async def preview_rule(
        pattern: str,
        match_type: str = "contains",
        match_field: str = "any",
    ) -> dict:
        """Dry-run a rule you're considering before proposing it: how many transactions the pattern would match, out of how many total, with up to 5 samples. Changes nothing. match_type is exact|contains|regex, match_field is any|merchant|description."""
        return await api.post(
            "/rules/preview",
            {"pattern": pattern, "match_type": match_type, "match_field": match_field},
        )

    @mcp.tool()
    async def create_rule_pack(
        name: str,
        rules: list[dict],
        description: str = "",
        apply: bool = True,
    ) -> dict:
        """Create a NEW rule pack with all its rules in one go, then backfill history. This is the only tool here that writes.

        Each entry in `rules` is {"pattern", "category", "match_type"?, "match_field"?, "counts_as"?}: match_type is exact|contains|regex (default contains), match_field is any|merchant|description (default any), counts_as is spending|transfer|card_payment and reclassifies the transaction as noise so it leaves the spending figures.

        Additive only — it creates a new pack and can never edit or delete an existing one, so the worst case is a pack the user removes in the app, which cascades to its rules. Categories the user set by hand are never overwritten. Every pattern is validated before anything is written, so one bad regex fails the whole request rather than leaving half a pack behind. Preview patterns with preview_rule first, and show the user what you intend to create before calling this."""
        credentials.require_scope(SCOPE_RULES_WRITE)
        return await api.post(
            "/rules/packs/bulk",
            {"name": name, "description": description or None, "rules": rules, "apply": apply},
        )

    return mcp


def main() -> None:
    try:
        settings = Settings.from_env(os.environ)
    except ConfigError as e:
        sys.exit(f"finance-tracker MCP: {e}")
    server = create_server(settings)
    server.run("streamable-http" if settings.transport == "http" else "stdio")


if __name__ == "__main__":
    main()
