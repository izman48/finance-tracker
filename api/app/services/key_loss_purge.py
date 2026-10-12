"""What a password reset without the recovery code must delete.

Without the recovery code the user's data-encryption key is gone, so every row
encrypted under it is unreadable: loading one raises InvalidToken (a 500).
Everything the user owns under that key is deleted, along with the rule packs
(their rules are encrypted, so a surviving pack is an empty shell; a shared
pack's public link stops working, which is the fail-closed choice). The user
row and OAuth clients stay; the user's MCP grants are revoked.

All deletes are bulk statements so undecryptable rows are never loaded. Child
tables are deleted explicitly, children first, rather than relying on database
cascades, so the result is the same on every backend. Nothing here commits:
the caller's transaction makes the purge, new key and new password atomic.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Account,
    AccountSetting,
    Asset,
    AssetFlow,
    AssetValuation,
    AuditEntry,
    BankConnection,
    Budget,
    CategoryRule,
    CommitmentRule,
    OAuthAuthorizationCode,
    OAuthGrant,
    PlannedItem,
    RepaymentScheduleItem,
    RulePack,
    Transaction,
    WriteIdempotency,
)

# Delete order matters: each model comes before anything it references.
_OWNED_BY_USER = (
    WriteIdempotency,
    Budget,
    AuditEntry,
    CategoryRule,
    RulePack,
    CommitmentRule,
    PlannedItem,
    RepaymentScheduleItem,
    AccountSetting,
)


def purge_data_under_lost_key(db: Session, user_id: uuid.UUID) -> None:
    """Delete everything encrypted under the user's lost key and revoke MCP access."""
    for model in _OWNED_BY_USER:
        _delete(db, model, model.user_id == user_id)

    user_assets = select(Asset.id).where(Asset.user_id == user_id)
    _delete(db, AssetValuation, AssetValuation.asset_id.in_(user_assets))
    _delete(db, AssetFlow, AssetFlow.asset_id.in_(user_assets))
    _delete(db, Asset, Asset.user_id == user_id)

    user_accounts = select(Account.id).where(Account.user_id == user_id)
    _delete(db, Transaction, Transaction.account_id.in_(user_accounts))
    _delete(db, Account, Account.user_id == user_id)
    _delete(db, BankConnection, BankConnection.user_id == user_id)

    _revoke_mcp_access(db, user_id)


def _delete(db: Session, model, condition) -> None:
    db.query(model).filter(condition).delete(synchronize_session=False)


def _revoke_mcp_access(db: Session, user_id: uuid.UUID) -> None:
    """Grants and pending codes carry the old key; none may be used again."""
    db.query(OAuthGrant).filter(
        OAuthGrant.user_id == user_id, OAuthGrant.revoked_at.is_(None)
    ).update({OAuthGrant.revoked_at: datetime.now(timezone.utc)}, synchronize_session=False)
    _delete(db, OAuthAuthorizationCode, OAuthAuthorizationCode.user_id == user_id)
