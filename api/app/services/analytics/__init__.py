"""Cashflow analytics: the engine behind safe-to-spend, forecast, spending,
and net worth.

Split by domain; this __init__ re-exports the public surface (plus the few
underscore helpers that routers/tests rely on) so callers can treat the
package as one module. `app.services.analytics_service` remains a
compatibility shim over this package.
"""
from .cadence import (  # noqa: F401
    _cadence_from_interval,
    _step,
    _step_back,
    commitment_occurrences,
)
from .commitments import (  # noqa: F401
    _match_key,
    commitment_from_transaction,
    commitment_match_keys,
    convert_transaction_to_plan,
    detect_recurring,
    last_payday,
    merchant_match_key,
    next_payday,
    sync_suggestions,
    transaction_match_key,
)
from .common import (  # noqa: F401
    _add_months,
    _d,
    _load,
    _today,
    default_role,
    resolve_roles,
)
from .forecast import get_forecast  # noqa: F401
from .net_worth import assets_total, net_worth_history  # noqa: F401
from .planned import installment_amount, planned_events  # noqa: F401
from .repayments import (  # noqa: F401
    next_repayment_date,
    repayment_amount,
    repayment_events,
)
from .spending import (  # noqa: F401
    _month_key,
    financed_transaction_ids,
    get_spending,
    get_spending_trend,
    spending_transactions,
)
from .summary import get_summary  # noqa: F401

__all__ = [
    # cadence
    "_cadence_from_interval",
    "_step",
    "_step_back",
    "commitment_occurrences",
    # commitments
    "_match_key",
    "commitment_from_transaction",
    "commitment_match_keys",
    "convert_transaction_to_plan",
    "detect_recurring",
    "last_payday",
    "merchant_match_key",
    "next_payday",
    "sync_suggestions",
    "transaction_match_key",
    # common
    "_add_months",
    "_d",
    "_load",
    "_today",
    "default_role",
    "resolve_roles",
    # forecast
    "get_forecast",
    # net worth
    "assets_total",
    "net_worth_history",
    # planned
    "installment_amount",
    "planned_events",
    # repayments
    "next_repayment_date",
    "repayment_amount",
    "repayment_events",
    # spending
    "_month_key",
    "financed_transaction_ids",
    "get_spending",
    "get_spending_trend",
    "spending_transactions",
    # summary
    "get_summary",
]
