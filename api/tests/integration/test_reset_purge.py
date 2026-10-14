"""A password reset without the recovery code loses the user's key, so it must
purge every row encrypted under it (T-08-17).

Coverage is driven by `Base.metadata`: any table with a UserEncrypted* column
must be seeded here and must be empty for the user after the reset, so a new
encrypted table fails these tests until the purge handles it.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from jose import jwt
from sqlalchemy import Column, ForeignKey, MetaData, Table, Uuid, func, select

from app.core import user_crypto
from app.core.config import get_settings
from app.core.database import Base
from app.core.encryption import UserEncryptedDecimal, UserEncryptedString, UserEncryptedToken
from app.core.security import create_password_reset_token
from app.models import (
    Account,
    AccountSetting,
    Asset,
    AssetFlow,
    AssetValuation,
    AuditEntry,
    BankConnection,
    Budget,
    BudgetChange,
    BudgetCycleSnapshot,
    CardStatement,
    CategoryRule,
    CommitmentRule,
    Liability,
    OAuthClient,
    OAuthGrant,
    PlannedItem,
    RepaymentScheduleItem,
    RulePack,
    Transaction,
    User,
    WriteIdempotency,
)
from app.services.key_loss_purge import purge_data_under_lost_key
from tests.integration.test_oauth import (
    READ,
    WRITE,
    _approve,
    _authorize_params,
    _code_from,
    _exchange,
    _pkce,
    _refresh,
    _register_client,
)

API = "/api/v1"
PASSWORD = "securepassword123"
NEW_PASSWORD = "afterreset12345"
VICTIM = "victim@example.com"
BYSTANDER = "bystander@example.com"
ENCRYPTED_TYPES = (UserEncryptedString, UserEncryptedDecimal, UserEncryptedToken)
KNOWN_ENCRYPTED_TABLES = {
    "accounts", "asset_flows", "asset_valuations", "assets", "audit_entries",
    "bank_connections", "budget_changes", "budget_cycle_snapshots", "budgets", "card_statements", "category_rules",
    "commitment_rules", "liabilities", "planned_items",
    "repayment_schedule_items", "transactions",
}


def encrypted_tables(metadata: MetaData) -> list[Table]:
    """Every table holding at least one column encrypted with a user's DEK."""
    return [
        t for t in metadata.sorted_tables
        if any(isinstance(c.type, ENCRYPTED_TYPES) for c in t.columns)
    ]


def row_counts(db, tables) -> dict[str, int]:
    return {t.name: db.execute(select(func.count()).select_from(t)).scalar() for t in tables}


def tables_with_extra_rows(db, tables, expected: dict[str, int]) -> list[str]:
    """Tables holding more rows than expected: rows a purge left behind."""
    return [name for name, n in row_counts(db, tables).items() if n > expected.get(name, 0)]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _login(client, email, password=PASSWORD) -> str:
    res = client.post(f"{API}/auth/login", data={"username": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _signup(client, email) -> str:
    assert client.post(f"{API}/auth/register", json={"email": email, "password": PASSWORD}).status_code == 201
    return _login(client, email)


def _dek(token) -> bytes:
    payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    return user_crypto.unwrap_session_dek(payload["dk"])


def _user(db, email) -> User:
    return db.query(User).filter(User.email == email).one()


def _seed_everything(db, user_id, dek) -> None:
    """One row in every table that holds data encrypted under this user's key."""
    ctx = user_crypto.current_dek.set(dek)
    try:
        conn = BankConnection(
            user_id=user_id, provider_id="ob-bank", provider_name="Bank",
            access_token="access", refresh_token="refresh",
        )
        db.add(conn)
        db.flush()
        account = Account(
            user_id=user_id, bank_connection_id=conn.id, external_id=f"acc-{uuid.uuid4()}",
            provider_name="Bank", account_type="TRANSACTION", display_name="Current",
            current_balance=Decimal("500"),
        )
        asset = Asset(user_id=user_id, name="ISA", asset_type="isa")
        pack = RulePack(user_id=user_id, name="Mine")
        db.add_all([account, asset, pack])
        db.flush()
        tx = Transaction(
            account_id=account.id, external_id=f"tx-{uuid.uuid4()}", transaction_type="debit",
            amount=Decimal("9.99"), description="COFFEE", transaction_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        audit = AuditEntry(
            user_id=user_id, kind="write", tool="add_planned_event", target_kind="planned_event",
            target_id=uuid.uuid4(), target_label="Holiday", changes="[]",
        )
        db.add_all([tx, audit])
        db.flush()
        db.add_all([
            AccountSetting(user_id=user_id, account_id=account.id),
            RepaymentScheduleItem(user_id=user_id, account_id=account.id, due_date=date(2026, 11, 1), amount=Decimal("20")),
            CardStatement(user_id=user_id, account_id=account.id, statement_date=date(2026, 10, 3),
                          due_date=date(2026, 10, 31), statement_balance=Decimal("5000"), minimum_due=Decimal("150")),
            AssetValuation(asset_id=asset.id, value=Decimal("1000"), valued_at=date(2026, 10, 1)),
            AssetFlow(asset_id=asset.id, amount=Decimal("50"), flow_date=date(2026, 10, 1)),
            CategoryRule(user_id=user_id, pack_id=pack.id, pattern="TESCO", category="Groceries"),
            Budget(user_id=user_id, category="Groceries", limit_pounds=Decimal("300")),
            rent := CommitmentRule(
                id=uuid.uuid4(), user_id=user_id, direction="expense", label="Rent", amount=Decimal("950"),
                cadence="monthly", next_date=date(2026, 11, 1), source="manual", status="confirmed",
                account_id=account.id,
            ),
            PlannedItem(
                user_id=user_id, name="Holiday", kind="one_off", start_date=date(2026, 12, 1),
                amount=Decimal("600"), account_id=account.id, source_transaction_id=tx.id,
            ),
            WriteIdempotency(user_id=user_id, key="k-1", request_hash="h", audit_id=audit.id),
            Liability(
                user_id=user_id, kind="loan", lender="Example Bank", balance=Decimal("9000"),
                balance_as_of=date(2026, 10, 1), apr=Decimal("11"), payment=Decimal("200"),
                start_date=date(2026, 11, 1),
                # Linked, so the purge must delete liabilities before commitments.
                linked_commitment_id=rent.id,
            ),
        ])
        db.flush()
        budget = db.query(Budget).filter(Budget.user_id == user_id).one()
        db.add_all([
            BudgetChange(user_id=user_id, budget_id=budget.id, effective_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                         limit_pounds=Decimal("300"), paused=False, active=True),
            BudgetCycleSnapshot(user_id=user_id, budget_id=budget.id, cycle_start=date(2026, 9, 1),
                                cycle_end=date(2026, 9, 30), limit_pounds=Decimal("300"), spent=Decimal("250"),
                                paused=False),
        ])
        db.commit()
    finally:
        user_crypto.current_dek.reset(ctx)


def _reset(client, db, email=VICTIM):
    return client.post(
        f"{API}/auth/reset-password",
        json={"token": create_password_reset_token(_user(db, email)), "new_password": NEW_PASSWORD},
    )


def _connect_mcp(client, web_token, scopes=(READ, WRITE)) -> tuple[str, dict]:
    client_id = _register_client(client).json()["client_id"]
    verifier, challenge = _pkce()
    approved = _approve(client, web_token, _authorize_params(client_id, challenge), scopes)
    assert approved.status_code == 200, approved.text
    tokens = _exchange(client, _code_from(approved.json()["redirect_to"]), client_id, verifier)
    assert tokens.status_code == 200, tokens.text
    return client_id, tokens.json()


@pytest.fixture
def two_seeded_users(client, db_session):
    """A victim who resets and a bystander whose data must survive it."""
    for email in (VICTIM, BYSTANDER):
        token = _signup(client, email)
        _seed_everything(db_session, _user(db_session, email).id, _dek(token))


# --------------------------------------------------------------------------- #
# Which tables count
# --------------------------------------------------------------------------- #
def test_the_encrypted_table_list_comes_from_metadata_and_covers_the_known_tables():
    names = {t.name for t in encrypted_tables(Base.metadata)}
    assert KNOWN_ENCRYPTED_TABLES <= names
    # A new encrypted table must be seeded above (and purged) before this passes.
    assert names == KNOWN_ENCRYPTED_TABLES


def test_the_check_catches_an_encrypted_table_the_purge_misses(db_session):
    """Self-test: a dummy model with an encrypted column survives the purge,
    and the leftover-row check reports it."""
    dummy_metadata = MetaData()
    Table("users", dummy_metadata, Column("id", Uuid, primary_key=True))
    dummy = Table(
        "dummy_secrets", dummy_metadata,
        Column("id", Uuid, primary_key=True),
        Column("user_id", Uuid, ForeignKey("users.id")),
        Column("secret", UserEncryptedString),
    )
    user = User(email="dummy@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    dummy.create(db_session.connection())
    try:
        db_session.execute(dummy.insert().values(id=uuid.uuid4(), user_id=user.id, secret="hidden"))

        purge_data_under_lost_key(db_session, user.id)

        assert [t.name for t in encrypted_tables(dummy_metadata)] == ["dummy_secrets"]
        assert tables_with_extra_rows(db_session, encrypted_tables(dummy_metadata), {}) == ["dummy_secrets"]
    finally:
        dummy.drop(db_session.connection())


# --------------------------------------------------------------------------- #
# The purge
# --------------------------------------------------------------------------- #
def test_reset_leaves_none_of_the_users_rows_in_any_encrypted_table(client, db_session, two_seeded_users):
    tables = encrypted_tables(Base.metadata)
    assert set(row_counts(db_session, tables).values()) == {2}  # both users, every table

    assert _reset(client, db_session).status_code == 200

    db_session.expire_all()
    # Row counts, so tables without a user_id (transactions, asset_*) are covered too:
    # exactly the bystander's row is left in each.
    assert row_counts(db_session, tables) == {t.name: 1 for t in tables}
    victim = _user(db_session, VICTIM)
    for model in (RulePack, AccountSetting, WriteIdempotency):
        assert db_session.query(model).filter(model.user_id == victim.id).count() == 0, model
        assert db_session.query(model).count() == 1, model
    assert victim.email == VICTIM  # the user row stays


def test_bystander_data_is_still_readable_after_another_users_reset(client, db_session, two_seeded_users):
    assert _reset(client, db_session).status_code == 200
    headers = _bearer(_login(client, BYSTANDER))
    assert len(client.get(f"{API}/analytics/commitments", headers=headers).json()) == 1
    assert client.get(f"{API}/rules", headers=headers).json()["packs"][0]["rules"][0]["pattern"] == "TESCO"


def test_reset_message_says_exactly_what_was_cleared(client, db_session):
    _signup(client, VICTIM)
    res = _reset(client, db_session)
    assert res.status_code == 200
    assert res.json()["message"] == (
        "Password updated. We deleted your bank data, commitments, planned events, rules "
        "(shared rule pack links no longer work), assets, debts and the history of changes made by "
        "Claude, and disconnected Claude (MCP) access. Reconnect your bank to start again, "
        "and reconnect Claude if you use it."
    )
    assert res.json()["recovery_code"]


# --------------------------------------------------------------------------- #
# After the reset
# --------------------------------------------------------------------------- #
WEB_READ_ROUTES = [
    "/analytics/summary",
    "/analytics/forecast",
    "/analytics/net-worth-projection",
    "/analytics/commitments",
    "/analytics/planned-items",
    "/analytics/spending",
    "/analytics/spending/trend",
    "/analytics/spending/transactions",
    "/analytics/net-worth-position",
    "/analytics/net-worth-history",
    "/analytics/net-worth-decomposition",
    "/analytics/nudges",
    "/banking/accounts",
    "/banking/transactions",
    "/banking/transactions/facets",
    "/banking/sync-status",
    "/banking/status",
    "/assets",
    "/liabilities",
    "/rules",
    "/rules/impact",
    "/audit",
    "/planning/planned-events",
    "/auth/me",
]
MCP_READ_ROUTES = [
    "/analytics/summary",
    "/analytics/forecast",
    "/analytics/commitments",
    "/analytics/spending",
    "/analytics/spending/trend",
    "/banking/accounts",
    "/banking/sync-status",
    "/banking/transactions",
    "/planning/planned-events",
    "/rules",
    "/rules/impact",
]


def test_every_web_and_mcp_read_route_returns_200_after_reset(client, db_session, two_seeded_users):
    assert _reset(client, db_session).status_code == 200
    web = _login(client, VICTIM, NEW_PASSWORD)
    _, mcp = _connect_mcp(client, web, scopes=[READ])

    failures = {}
    for caller, token, paths in (("web", web, WEB_READ_ROUTES), ("mcp", mcp["access_token"], MCP_READ_ROUTES)):
        for path in paths:
            res = client.get(f"{API}{path}", headers=_bearer(token))
            if res.status_code != 200:
                failures[f"{caller} GET {path}"] = res.status_code
        search = client.post(f"{API}/banking/transactions/search", json={"query": "coffee"}, headers=_bearer(token))
        if search.status_code != 200:
            failures[f"{caller} POST /banking/transactions/search"] = search.status_code
    assert failures == {}


def test_safe_to_spend_is_zero_after_reset(client, db_session, two_seeded_users):
    assert _reset(client, db_session).status_code == 200
    summary = client.get(f"{API}/analytics/summary", headers=_bearer(_login(client, VICTIM, NEW_PASSWORD)))
    assert summary.status_code == 200
    assert Decimal(summary.json()["safe_to_spend"]) == 0


def test_reset_revokes_existing_mcp_grants(client, db_session):
    web = _signup(client, VICTIM)
    client_id, tokens = _connect_mcp(client, web)

    assert _reset(client, db_session).status_code == 200

    db_session.expire_all()
    grants = db_session.query(OAuthGrant).filter(OAuthGrant.user_id == _user(db_session, VICTIM).id).all()
    assert grants and all(g.revoked_at is not None for g in grants)
    assert db_session.query(OAuthClient).count() == 1  # the client registration stays
    refreshed = _refresh(client, tokens["refresh_token"], client_id)
    assert refreshed.status_code == 400 and refreshed.json()["error"] == "invalid_grant"
    assert client.get(f"{API}/rules", headers=_bearer(tokens["access_token"])).status_code == 401


def test_a_failed_reset_purges_nothing_and_keeps_the_old_password(client, db_session, two_seeded_users, monkeypatch):
    """Purge, new key and new password are one transaction."""
    tables = encrypted_tables(Base.metadata)
    before = row_counts(db_session, tables)

    def fail(_password):
        raise RuntimeError("injected failure after the purge")

    monkeypatch.setattr("app.routers.auth.get_password_hash", fail)
    with pytest.raises(RuntimeError):
        _reset(client, db_session)
    # The test client shares db_session with the request, so the purge's
    # uncommitted deletes are still pending here. In production get_db closes
    # the session, which rolls them back; rolling back does the same. If the
    # purge had committed, the counts below would show it.
    db_session.rollback()
    monkeypatch.undo()

    assert row_counts(db_session, tables) == before
    old = _login(client, VICTIM, PASSWORD)
    commitments = client.get(f"{API}/analytics/commitments", headers=_bearer(old))
    assert commitments.status_code == 200 and len(commitments.json()) == 1


def test_statements_of_a_purged_card_are_404_not_500_after_reset(client, db_session, two_seeded_users):
    """The card and its statements are purged together, so reading them is a
    plain not-found, never an undecryptable row."""
    victim_id = _user(db_session, VICTIM).id
    card_id = db_session.query(CardStatement.account_id).filter(CardStatement.user_id == victim_id).scalar()
    assert _reset(client, db_session).status_code == 200

    res = client.get(f"{API}/analytics/accounts/{card_id}/statements",
                     headers=_bearer(_login(client, VICTIM, NEW_PASSWORD)))

    assert res.status_code == 404
