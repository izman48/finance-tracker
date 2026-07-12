from app.routers.health import router as health_router
from app.routers.auth import router as auth_router
from app.routers.banking import router as banking_router
from app.routers.analytics import router as analytics_router
from app.routers.rules import router as rules_router
from app.routers.assets import router as assets_router
from app.routers.instruments import router as instruments_router

__all__ = [
    "health_router",
    "auth_router",
    "banking_router",
    "analytics_router",
    "rules_router",
    "assets_router",
    "instruments_router",
]
