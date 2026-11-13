"""safe to spend's money out, itemised, and which credits paid an income
(T-24-4a): what Plan lists, from the code that already owns it. The
shared Plan world lives here. Synthetic data."""
from datetime import timedelta
from decimal import Decimal

from app.models import AccountSetting, CommitmentRule, PlannedItem
from app.services.analytics.late_income import income_credit_ids, income_payments
from app.services.analytics.planned_matching import planned_states
from app.services.analytics.summary import _money_out, money_out_items
from tests.clock import TODAY
from tests.integration.test_budget_commitments import _weekly
from tests.integration.test_budgets_api import API, World
from tests.integration.test_oauth import _bearer
from tests.integration.test_transactions_endpoint import _account, _tx

D = Decimal


def _rule(w, label, amount, direction, days, cadence="monthly"):
    def make():
        rule = CommitmentRule(user_id=w.user.id, direction=direction, label=label, amount=D(amount), cadence=cadence,
                              next_date=TODAY + timedelta(days=days), source="manual", status="confirmed")
        w.db.add(rule)
        w.db.commit()
        return rule.id
    return w.as_user(make)


def plan_world(client, db_session):
    world = World(client, db_session, email="plan@example.com")
    world.history()
    def salary_paid():
        _tx(db_session, world.current, "2500.00", TODAY - timedelta(days=20), ttype="credit", merchant="Salary")
        # The rule predates the payment, as a real one does (lateness skips
        # an income created after its expected date).
        rule = db_session.query(CommitmentRule).filter_by(user_id=world.user.id, is_payday=True).one()
        rule.created_at = rule.created_at - timedelta(days=60)
        db_session.commit()
    world.as_user(salary_paid)
    _weekly(world)
    assert world.create("Eating out", 150).status_code == 201
    assert world.create("Groceries", 300).status_code == 201

    def card():
        acc = _account(db_session, world.user.id, atype="CREDIT_CARD", name="Card", balance="600")
        db_session.add(AccountSetting(user_id=world.user.id, account_id=acc.id, role="credit",
                                      repayment_cadence="weekly", repayment_strategy="full_balance",
                                      repayment_anchor_date=TODAY + timedelta(days=3)))
        db_session.commit()
    world.as_user(card)
    r = client.post(f"{API}/analytics/planned-items", headers=_bearer(world.web), json={
        "name": "Sofa", "direction": "expense", "kind": "one_off", "amount": "300.00",
        "start_date": (TODAY + timedelta(days=6)).isoformat()})
    assert r.status_code in (200, 201), r.text
    return world



def test_money_out_items_list_each_source_and_add_up_to_safe_to_spends_figure(client, db_session):
    w = plan_world(client, db_session)

    def items():
        rules = w.db.query(CommitmentRule).filter_by(user_id=w.user.id, direction="expense", status="confirmed").all()
        planned = w.db.query(PlannedItem).filter_by(user_id=w.user.id).all()
        states = planned_states(w.db, w.user, planned, TODAY)
        end = TODAY + timedelta(days=9)
        return (money_out_items(w.db, w.user, rules, planned, states, TODAY, end),
                _money_out(w.db, w.user, rules, planned, states, TODAY, end))
    listed, total = w.as_user(items)
    assert {i["source"] for i in listed} == {"commitment", "card_repayment", "planned"}
    assert sum(i["amount"] for i in listed) == total
    assert ("planned", "Sofa", D("300.00")) in {(i["source"], i["label"], i["amount"]) for i in listed}


def test_income_payments_name_the_credit_that_paid_each_income(client, db_session):
    w = plan_world(client, db_session)
    _rule(w, "Bonus", "400", "income", -10)  # never came: late, so no credit
    paid = w.as_user(lambda: income_payments(w.db, w.user, TODAY))
    [(rule_id, credits)] = paid.items()
    assert [(c.amount, c.day) for c in credits] == [(D("2500.00"), TODAY - timedelta(days=20))]
    assert w.as_user(lambda: income_credit_ids(w.db, w.user, TODAY)) == {credits[0].id}
