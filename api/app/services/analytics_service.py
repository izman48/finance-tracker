"""Compatibility shim: the analytics engine now lives in `app.services.analytics`.

Existing imports (`from app.services import analytics_service`) keep working;
new code should import from the package modules directly, e.g.
`from app.services.analytics import spending`.
"""
from app.services.analytics import *  # noqa: F401,F403
