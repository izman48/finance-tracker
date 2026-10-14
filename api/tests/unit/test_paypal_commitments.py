"""PayPal subscriptions are detected once, and rules keyed under the old
normaliser are never suggested again (T-10-9, the two-part change).

Changing the normaliser changes keys. `match_key` is DEK-encrypted, so it can't
be fixed by a data migration; `sync_suggestions` heals detected rules from
their label and dedupes on keys re-computed from manual rules' stored keys and
labels. These tests seed rules exactly as the old normaliser stored them.
Synthetic descriptors and amounts.
"""
from datetime import timedelta
from decimal import Decimal

from app.models import CommitmentRule, Transaction
from app.services import analytics_service as svc
from app.services.analytics.commitments import commitment_match_keys, transaction_match_key
from tests.clock import TODAY
from tests.unit.test_analytics_service import _account, _tx_desc, _user

PHONE = "01234567890"
MONTHS = [TODAY - timedelta(days=d) for d in (75, 45, 15)]
SPOTIFY = [f"PAYPAL *SPOTIFY*P{n}A3B4 {PHONE}" for n in (12, 11, 10)]
NETFLIX = [f"PAYPAL *NETFLIX ON {d.day} {d.strftime('%b').upper()} BCC" for d in MONTHS]


def _world(db):
    user = _user(db)
    card = _account(db, user, atype="CREDIT_CARD", name="Card")
    current = _account(db, user, name="Current")
    for when, spotify, netflix in zip(MONTHS, SPOTIFY, NETFLIX):
        _tx_desc(db, card, "11.99", when, description=spotify)
        _tx_desc(db, current, "10.99", when, description=netflix)
    return user, card, current


def _rule(db, user, label, key, source="manual", status="confirmed", amount="11.99"):
    rule = CommitmentRule(
        user_id=user.id, direction="expense", label=label, amount=Decimal(amount), cadence="monthly",
        next_date=TODAY + timedelta(days=15), source=source, status=status, match_key=key,
    )
    db.add(rule)
    db.commit()
    return rule


def _suggested(db, user) -> list[CommitmentRule]:
    return db.query(CommitmentRule).filter(
        CommitmentRule.user_id == user.id, CommitmentRule.status == "suggested",
    ).all()


def test_spotify_and_netflix_through_paypal_are_each_detected_once(db_session):
    user, _, _ = _world(db_session)
    found = {c["match_key"]: c for c in svc.detect_recurring(db_session, user)}
    assert set(found) == {"expense:paypal spotify", "expense:paypal netflix bcc"}
    assert found["expense:paypal spotify"]["amount"] == Decimal("11.99")
    assert found["expense:paypal netflix bcc"]["amount"] == Decimal("10.99")


def test_bare_paypal_payments_with_changing_references_are_never_merged(db_session):
    user = _user(db_session)
    current = _account(db_session, user, name="Current")
    for when, ref in zip(MONTHS, ("1A2B3C", "4D5E6F", "7G8H9J")):
        _tx_desc(db_session, current, "25.00", when, description=f"PAYPAL {ref}")
    assert svc.detect_recurring(db_session, user) == []


def test_a_manual_rule_added_from_one_paypal_payment_is_not_suggested_again(db_session):
    user, _, _ = _world(db_session)
    # Added from the first month's payment under the old normaliser, then
    # renamed by the user: neither the label nor the old key equals the new key.
    _rule(db_session, user, "Spotify", "expense:paypal spotify p12a3b4")
    _rule(db_session, user, "Netflix", f"expense:paypal netflix on {MONTHS[0].day} {MONTHS[0].strftime('%b').lower()} bcc",
          amount="10.99")

    svc.sync_suggestions(db_session, user)

    assert _suggested(db_session, user) == []


def test_a_dismissed_detected_rule_under_an_old_key_stays_dismissed(db_session):
    user, _, _ = _world(db_session)
    dismissed = _rule(db_session, user, SPOTIFY[0], "expense:paypal spotify p12a3b4", source="detected",
                      status="dismissed")

    svc.sync_suggestions(db_session, user)

    assert [r.match_key for r in _suggested(db_session, user)] == ["expense:paypal netflix bcc"]
    db_session.refresh(dismissed)
    assert dismissed.status == "dismissed"
    assert dismissed.match_key == "expense:paypal spotify"  # healed from its label


def test_a_confirmed_paypal_rule_matches_every_months_payment(db_session):
    user, card, _ = _world(db_session)
    _rule(db_session, user, "Spotify", "expense:paypal spotify p12a3b4")
    keys = commitment_match_keys(db_session, user)
    payments = db_session.query(Transaction).filter(Transaction.account_id == card.id).all()
    assert len(payments) == 3
    assert all(transaction_match_key(t) in keys for t in payments)
