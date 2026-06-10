"""Periodic background sync of all bank connections.

Runs as its own container (see docker-compose.prod.yml `sync` service) so the
API workers never compete to schedule it:

    python -m app.tasks.background_sync

Every SYNC_INTERVAL_HOURS it refreshes accounts/balances and pulls the recent
transaction window for every connection that can sync (has a refresh token, or
a still-valid access token). Failures are logged per-connection and never stop
the loop.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from app.core.database import get_session_local
from app.models import BankConnection
from app.services.truelayer import truelayer_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("background_sync")

SYNC_INTERVAL_HOURS = float(os.environ.get("SYNC_INTERVAL_HOURS", "6"))
# Overlap window: re-fetching a few days is cheap and dedupes on external_id.
SYNC_WINDOW_DAYS = int(os.environ.get("SYNC_WINDOW_DAYS", "7"))


async def sync_connection(connection_id) -> None:
    db = get_session_local()()
    try:
        conn = db.query(BankConnection).filter(BankConnection.id == connection_id).first()
        if not conn:
            return
        token_alive = conn.token_expires_at and conn.token_expires_at > datetime.now(timezone.utc)
        if not conn.refresh_token and not token_alive:
            logger.info(f"Skipping {conn.provider_name} ({conn.id}): needs reconnection")
            return
        await truelayer_service.sync_accounts(conn, db)
        count = await truelayer_service.sync_transactions(conn, db, days=SYNC_WINDOW_DAYS)
        logger.info(f"Synced {conn.provider_name} ({conn.id}): {count} new transactions")
    except Exception:
        logger.exception(f"Sync failed for connection {connection_id}")
    finally:
        db.close()


async def sync_all() -> None:
    db = get_session_local()()
    try:
        ids = [row[0] for row in db.query(BankConnection.id).all()]
    finally:
        db.close()
    logger.info(f"Background sync starting for {len(ids)} connection(s)")
    for cid in ids:
        await sync_connection(cid)
    logger.info("Background sync pass complete")


async def main() -> None:
    interval = timedelta(hours=SYNC_INTERVAL_HOURS)
    logger.info(f"Background sync worker up; interval {interval}")
    while True:
        await sync_all()
        await asyncio.sleep(interval.total_seconds())


if __name__ == "__main__":
    asyncio.run(main())
