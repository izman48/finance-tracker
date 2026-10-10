"""How fresh each bank connection's data is (T-08-11).

Reads stored data only: no TrueLayer call, so a caller (Claude included)
can't spend the provider's rate limit or trigger syncs through it. It never
loads the token columns either: whether a refresh token exists is asked in
SQL, so tokens aren't decrypted on this read path.

Unknown is never reported as fine. A connection is stale when it has never
synced, last synced over 48 h ago, or its consent is known to have lapsed.
Consent is "expired" only when we know it: sync drops the refresh token
once TrueLayer rejects it. Otherwise it is "unknown", because the consent
expiry isn't stored (`token_expires_at` is the access token's, which
refreshes hourly, not the consent's).
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Account, BankConnection

STALE_AFTER = timedelta(hours=48)


@dataclass(frozen=True)
class ConnectionFreshness:
    last_synced_at: datetime | None
    consent: str  # expired | unknown
    stale: bool


def freshness(db: Session, user_id: uuid.UUID) -> dict[uuid.UUID, ConnectionFreshness]:
    """{connection id: freshness} for the user's connections."""
    now = datetime.now(timezone.utc)
    rows = db.query(
        BankConnection.id, BankConnection.last_synced_at, BankConnection.refresh_token.is_(None)
    ).filter(BankConnection.user_id == user_id)
    out = {}
    for conn_id, synced, consent_lapsed in rows:
        consent = "expired" if consent_lapsed else "unknown"
        out[conn_id] = ConnectionFreshness(synced, consent, _stale(synced, consent, now))
    return out


def _stale(synced: datetime | None, consent: str, now: datetime) -> bool:
    if synced is None or consent == "expired":
        return True
    if synced.tzinfo is None:  # SQLite drops the zone; stored as UTC
        synced = synced.replace(tzinfo=timezone.utc)
    return now - synced > STALE_AFTER


def sync_status(db: Session, user_id: uuid.UUID) -> list[dict]:
    """The allow-listed view of each connection: nothing else leaves here."""
    fresh = freshness(db, user_id)
    names = dict(
        db.query(BankConnection.id, BankConnection.provider_name).filter(BankConnection.user_id == user_id)
    )
    accounts = (
        db.query(Account.bank_connection_id, Account.display_name, Account.balance_updated_at)
        .filter(Account.user_id == user_id)
        .all()
    )
    return [
        {
            "connection_id": conn_id,
            "provider": names[conn_id],
            "last_synced_at": f.last_synced_at,
            "consent": f.consent,
            "stale": f.stale,
            "accounts": [
                {"display_name": name, "balance_updated_at": updated}
                for owner, name, updated in accounts if owner == conn_id
            ],
        }
        for conn_id, f in fresh.items()
    ]
