from app.routers.health import router as health_router
from app.routers.auth import router as auth_router
from app.routers.banking import router as banking_router
from app.routers.analytics import router as analytics_router
from app.routers.rules import router as rules_router
from app.routers.assets import router as assets_router
from app.routers.liabilities import router as liabilities_router
from app.routers.holdings import router as holdings_router
from app.routers.oauth import router as oauth_router, well_known_router
from app.routers.audit import router as audit_router
from app.routers.planning import router as planning_router
from app.routers.commitment_writes import router as commitment_writes_router
from app.routers.budgets import router as budgets_router
from app.routers.budget_writes import router as budget_writes_router
from app.routers.rule_writes import router as rule_writes_router
from app.routers.card_statements import router as card_statements_router
from app.routers.card_plans import router as card_plans_router
from app.routers.holdings_list import router as holdings_list_router

__all__ = [
    "health_router",
    "auth_router",
    "banking_router",
    "analytics_router",
    "rules_router",
    "assets_router",
    "liabilities_router",
    "holdings_router",
    "oauth_router",
    "well_known_router",
    "audit_router",
    "planning_router",
    "commitment_writes_router",
    "budgets_router",
    "budget_writes_router",
    "rule_writes_router",
    "holdings_list_router",
    "card_statements_router",
    "card_plans_router",
]
