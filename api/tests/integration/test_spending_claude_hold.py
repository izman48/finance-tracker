"""Spending and budgets use the intersection while a Claude bill change is unkept (T-20-1b).

Owner decision 2 (2026-11-02): while Claude's change to a bill is unkept, a
payment counts as the bill's in Spending and budgets only if *both* the
current and the before-Claude version match it. So a change that widens
matching (a cut from GBP 50 to GBP 10 starts taking GBP 5-15 purchases for
the bill) can't hide spending, and one that narrows it (a raise, a
dismissal) shows the payment as spending at once. Planned matching uses the
union (T-20-1a), so the same payment can be spending here and still the
bill's for planned matching: the two views differ on purpose, each on its
own safe side. Synthetic merchant and amounts (public repo).
"""
from datetime import timedelta
from decimal import Decimal

from app.models import CommitmentRule, PlannedItem, User
from app.services import analytics_service as svc
from app.services.budget_spend import budget_spend
from tests.clock import TODAY
from tests.integration.test_claude_income_parity import World as ParityWorld
from tests.integration.test_oauth import _bearer
from tests.integration.test_transactions_endpoint import _account, _tx

DAY = TODAY - timedelta(days=2)
START = TODAY - timedelta(days=10)


class World(ParityWorld):
    """A GBP 50 gym bill, its GBP 50 payment and a GBP 12 one-off (a drink)
    under the same descriptor, plus a GBP 50 planned item the payment could
    settle and a salary credit."""

    def __init__(self, client, db, status="confirmed"):
        super().__init__(client, db, "spendhold@example.com")
        self.as_user(lambda: self._seed(status))

    def _seed(self, status):
        db, uid = self.db, self.user.id
        current = _account(db, uid, name="Main", balance="500")
        _tx(db, current, "50.00", DAY, merchant="GYM", category="Fitness")
        _tx(db, current, "12.00", DAY, merchant="GYM", category="Fitness")
        _tx(db, current, "2000.00", DAY, ttype="credit", merchant="SALARY")
        rules = [
            CommitmentRule(user_id=uid, direction="expense", label="Gym", amount=Decimal("50.00"),
                           cadence="monthly", next_date=TODAY + timedelta(days=20), source="manual", status=status),
            CommitmentRule(user_id=uid, direction="income", label="Salary", amount=Decimal("2000.00"),
                           cadence="monthly", next_date=TODAY + timedelta(days=10), source="manual",
                           status="confirmed"),
        ]
        db.add_all(rules)
        db.add(PlannedItem(user_id=uid, name="Kit", direction="expense", kind="one_off",
                           start_date=TODAY - timedelta(days=1), amount=Decimal("50.00")))
        db.commit()
        self.bill, self.salary = (r.id for r in rules)

    def claude_dismiss(self, cid):
        self.n += 1
        res = self.client.post(f"/api/v1/planning/commitments/{cid}/dismiss", headers=_bearer(self.mcp),
                               json={"dry_run": False, "idempotency_key": f"spendhold-dismiss-{self.n:04d}"})
        assert res.status_code == 200, res.text

    def tags(self, **params) -> dict:
        res = self.client.get("/api/v1/banking/transactions", params=params, headers=_bearer(self.web))
        assert res.status_code == 200, res.text
        return {Decimal(str(i["amount"])): i["is_commitment"] for i in res.json()["items"]}

    def searched(self) -> dict:
        res = self.client.post("/api/v1/banking/transactions/search", json={"query": "gym"}, headers=_bearer(self.web))
        assert res.status_code == 200, res.text
        return {Decimal(str(i["amount"])): i["is_commitment"] for i in res.json()["items"]}

    def svc(self, fn, **kw):
        user = self.db.get(User, self.user.id)
        return self.as_user(lambda: fn(self.db, user, **kw))

    def budget(self) -> Decimal:
        return self.svc(budget_spend, start=START, end=TODAY).by_category.get("Fitness", Decimal(0))

    def purchases(self) -> Decimal:
        s = self.svc(svc.get_spending, period="custom", frm=START, to=TODAY, lens="purchases",
                     exclude_commitments=True)
        return s["paid_from_cash"]

    def composition(self) -> Decimal:
        return self.svc(svc.get_spending, period="custom", frm=START, to=TODAY)["composition"]["commitments"]

    def trend_total(self) -> Decimal:
        trend = self.svc(svc.get_spending_trend, months=2, exclude_commitments=True)  # DAY may be last month
        return sum((Decimal(str(m["total"])) for m in trend["months"]), Decimal(0))

    def planned_settled(self) -> bool:
        rows = self.client.get("/api/v1/analytics/planned-items", headers=_bearer(self.web)).json()
        return rows[0]["matched_transaction_id"] is not None


def _spending_view(w):
    """What each Spending surface says about the GBP 50 and GBP 12 payments."""
    return {
        "list": w.tags(), "search": w.searched(), "budget": w.budget(), "purchases": w.purchases(),
        "composition": w.composition(), "trend": w.trend_total(),
    }


# Only the GBP 50 payment is the bill's: the drink is spending everywhere.
BASELINE = {
    "list": {Decimal("50.00"): True, Decimal("12.00"): False, Decimal("2000.00"): True},
    "search": {Decimal("50.00"): True, Decimal("12.00"): False},
    "budget": Decimal("12.00"), "purchases": Decimal("12.00"),
    "composition": Decimal("50.00"), "trend": Decimal("12.00"),
}
# Neither payment is the bill's: both count as spending.
BOTH_SPENDING = {
    "list": {Decimal("50.00"): False, Decimal("12.00"): False, Decimal("2000.00"): True},
    "search": {Decimal("50.00"): False, Decimal("12.00"): False},
    "budget": Decimal("62.00"), "purchases": Decimal("62.00"),
    "composition": Decimal(0), "trend": Decimal("62.00"),
}


def test_the_baseline(client, db_session):
    w = World(client, db_session)
    assert _spending_view(w) == BASELINE
    assert not w.planned_settled()


def test_a_pending_raise_shows_the_payment_as_spending_but_still_holds_planned_matching(client, db_session):
    """sec's "one Spending view" probe: GBP 200 +/- 25% no longer takes the
    GBP 50 payment, so Spending counts it at once; planned matching (union)
    still treats it as the bill's, so the planned item stays unsettled."""
    w = World(client, db_session)
    w.claude_update(w.bill, amount="200.00")
    assert _spending_view(w) == BOTH_SPENDING
    assert w.tags(exclude_commitments="true").keys() == {Decimal("50.00"), Decimal("12.00")}
    assert not w.planned_settled()


def test_a_pending_cut_hides_no_spending(client, db_session):
    """sec's widening case: cut to GBP 10, the bill as it is now takes the
    GBP 12 drink (GBP 5-15). The before-Claude GBP 50 doesn't, so it stays
    spending; the GBP 50 payment no longer fits GBP 10, so it is spending too."""
    w = World(client, db_session)
    w.claude_update(w.bill, amount="10.00")
    assert _spending_view(w) == BOTH_SPENDING


def test_a_kept_cut_uses_the_new_amount(client, db_session):
    """The user agreed: the GBP 12 drink is now the bill's, the GBP 50 isn't."""
    w = World(client, db_session)
    assert w.keep(w.claude_update(w.bill, amount="10.00")).status_code == 200
    view = _spending_view(w)
    assert view["list"] == {Decimal("50.00"): False, Decimal("12.00"): True, Decimal("2000.00"): True}
    assert view["budget"] == Decimal("50.00")


def test_a_pending_dismissal_shows_the_payment_as_spending(client, db_session):
    w = World(client, db_session)
    w.claude_dismiss(w.bill)
    assert _spending_view(w) == BOTH_SPENDING
    assert not w.planned_settled()


def test_a_bill_claude_confirmed_is_not_the_payments_until_the_user_says_so(client, db_session):
    """Confirming widens matching (nothing was the bill's before), so the
    payment stays spending while that change is Claude's alone."""
    w = World(client, db_session, status="suggested")
    w.claude_update(w.bill, status="confirmed")
    assert _spending_view(w)["budget"] == Decimal("62.00")
    w.client.patch(f"/api/v1/analytics/commitments/{w.bill}", json={"status": "confirmed"}, headers=_bearer(w.web))
    assert _spending_view(w)["budget"] == Decimal("12.00")


def test_undoing_a_raise_is_the_same_as_no_change(client, db_session):
    w = World(client, db_session)
    audit_id = w.claude_update(w.bill, amount="200.00")
    assert w.client.post(f"/api/v1/audit/{audit_id}/undo", headers=_bearer(w.web)).status_code == 200
    assert _spending_view(w) == BASELINE


def test_a_hand_set_amount_ends_the_intersection(client, db_session):
    w = World(client, db_session)
    w.claude_update(w.bill, amount="10.00")
    w.client.patch(f"/api/v1/analytics/commitments/{w.bill}", json={"amount": "10.00"}, headers=_bearer(w.web))
    assert _spending_view(w)["budget"] == Decimal("50.00")  # the drink is the bill's, by the user's choice


def test_an_income_change_is_unchanged(client, db_session):
    """Incomes use the current view (as on main): a lowered salary applies
    at once, so the GBP 2,000 credit is no longer the salary's."""
    w = World(client, db_session)
    w.claude_update(w.salary, amount="1000.00")
    assert w.tags()[Decimal("2000.00")] is False
