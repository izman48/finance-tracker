"""Commitments inside their budget category (T-24-3a; sec's T-24-3 criteria).

A commitment's payment counts in its category's budget when that category
has an active budget, only once it is paid. Its instalments still to come
this cycle are `coming_up`: taken from the held scheduled outflows the
forecast uses, never added to `spent`, `over_by` or the status. With no
budget on its category it stays under "Not counted here" as before.
Synthetic merchants and amounts only.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import CommitmentRule
from tests.clock import TODAY
from tests.integration.test_budgets_api import World
from tests.integration.test_oauth import _bearer
from tests.integration.test_transactions_endpoint import _tx

KIT = "MEAL KIT CO"


def _weekly(w, label=KIT, amount="16.00", category="Eating out", paid_days_ago=(5, 12, 19), next_in=2):
    """A weekly commitment and its payments (category as the bank gave it)."""
    def make():
        for days in paid_days_ago:
            _tx(w.db, w.current, amount, TODAY - timedelta(days=days), merchant=label, category=category)
        rule = CommitmentRule(user_id=w.user.id, direction="expense", label=label, amount=Decimal(amount),
                              cadence="weekly", next_date=TODAY + timedelta(days=next_in),
                              source="manual", status="confirmed")
        w.db.add(rule)
        w.db.commit()
        return rule.id
    return w.as_user(make)


def _budgets(w) -> dict:
    return w.client.get("/api/v1/budgets", headers=_bearer(w.web)).json()


def _row(w, category="Eating out"):
    body = _budgets(w)
    return body, next(b for b in body["budgets"] if b["category"] == category)


def _due(first: date, end: date, step=7) -> list[date]:
    out, d = [], first
    while d <= end:
        out.append(d)
        d += timedelta(days=step)
    return out


@pytest.fixture
def w(client, db_session):
    world = World(client, db_session)
    world.history()  # Eating out £40 this cycle; rent £950 (category Rent), next due in 5 days
    return world


def test_paid_instalments_count_and_the_rest_are_coming_up(w):
    kit = _weekly(w)
    w.create("Eating out", 150)
    body, row = _row(w)
    end = date.fromisoformat(body["cycle"]["end"])
    due = _due(TODAY + timedelta(days=2), end)
    assert Decimal(row["spent"]) == Decimal("88.00")  # £40 purchases + 3 x £16 paid
    coming = row["coming_up"]
    assert Decimal(coming["amount"]) == Decimal("16.00") * len(due)
    assert (coming["commitment_count"], coming["instalment_count"]) == (1, len(due))
    assert [(i["commitment_id"], i["label"], i["due_date"], Decimal(i["amount"])) for i in coming["items"]] == [
        (str(kit), KIT, d.isoformat(), Decimal("16.00")) for d in due]
    # Coming up is a hint: spent, over_by and status are as if it weren't there.
    assert Decimal(row["over_by"]) == 0 and row["status"] != "over"
    assert Decimal(body["not_counted"]["commitments"]) == Decimal("950.00")  # rent: no budget


def test_with_no_budget_on_its_category_a_commitment_stays_not_counted(w):
    _weekly(w)
    w.create("Groceries", 300)
    body, row = _row(w, "Groceries")
    assert Decimal(body["not_counted"]["commitments"]) == Decimal("998.00")  # rent + 3 x £16, as today
    assert Decimal(row["coming_up"]["amount"]) == 0 and row["coming_up"]["items"] == []
    assert Decimal(body["other_spending"]) == Decimal("160.00")  # Eating out £40 + Shopping £120, no kit


def test_a_paused_budget_counts_no_commitment(w):
    _weekly(w)
    budget_id = w.create("Eating out", 150).json()["id"]
    w.patch(budget_id, paused=True)
    body, row = _row(w)
    assert Decimal(row["spent"]) == Decimal("40.00") and row["coming_up"]["items"] == []
    assert Decimal(body["not_counted"]["commitments"]) == Decimal("998.00")


def test_over_by_payday_adds_coming_up_but_over_by_does_not(w):
    _weekly(w)
    w.create("Eating out", 90)
    _, row = _row(w)
    coming = Decimal(row["coming_up"]["amount"])
    assert Decimal(row["over_by"]) == 0
    assert Decimal(row["over_by_payday"]) == max(Decimal(0), Decimal("88.00") + coming - 90)


def test_spent_exactly_at_the_limit_is_budget_used(w):
    _weekly(w)
    w.create("Eating out", 88)
    _, row = _row(w)
    assert row["status"] == "budget_used"
    w.create("Groceries", 300)
    assert _row(w, "Groceries")[1]["status"] != "budget_used"


def test_a_due_date_after_payday_or_a_zero_amount_rule_adds_nothing(w):
    """B-34: a key-only £0 rule's payments count in the budget, and it
    invents nothing coming up; a bill due after payday isn't coming up."""
    _weekly(w, label="VEG BOX", amount="0.00", paid_days_ago=(3,))
    w.as_user(lambda: _tx(w.db, w.current, "9.00", TODAY - timedelta(days=3), merchant="VEG BOX",
                          category="Eating out"))
    _weekly(w, label="SUPPER CLUB", amount="30.00", paid_days_ago=(), next_in=45)
    w.create("Eating out", 150)
    _, row = _row(w)
    assert Decimal(row["spent"]) == Decimal("49.00")  # £40 + the £9 VEG BOX payment
    assert row["coming_up"]["items"] == []


def test_items_are_capped_at_five_and_counted_in_full(w):
    for n in range(3):
        _weekly(w, label=f"LUNCH CLUB {chr(65 + n)}", amount="5.00", paid_days_ago=(4,), next_in=1)
    w.create("Eating out", 150)
    body, row = _row(w)
    end = date.fromisoformat(body["cycle"]["end"])
    due = _due(TODAY + timedelta(days=1), end)
    coming = row["coming_up"]
    assert (coming["commitment_count"], coming["instalment_count"]) == (3, 3 * len(due))
    assert len(coming["items"]) == min(5, 3 * len(due))
    assert Decimal(coming["amount"]) == Decimal("5.00") * 3 * len(due)
    assert [i["due_date"] for i in coming["items"]] == sorted(i["due_date"] for i in coming["items"])


def test_another_users_commitments_never_appear(client, db_session):
    a = World(client, db_session, email="a@example.com")
    a.history()
    b = World(client, db_session, email="b@example.com")
    b.history()
    _weekly(b)
    mine = _weekly(a, amount="7.00")
    a.create("Eating out", 150)
    _, row = _row(a)
    assert {i["commitment_id"] for i in row["coming_up"]["items"]} == {str(mine)}
    assert Decimal(row["spent"]) == Decimal("61.00")  # £40 + 3 x £7


def test_a_budget_can_be_set_on_a_category_that_is_mostly_commitments(w):
    """The covered-category block is lifted; safe to spend and the forecast
    don't move when it is."""
    def figures():
        s = w.client.get("/api/v1/analytics/summary", headers=_bearer(w.web)).json()
        f = w.client.get("/api/v1/analytics/forecast", headers=_bearer(w.web)).json()
        return s["safe_to_spend"], s["savable"], f["end_balance"], f["min_balance"]
    before = figures()
    assert w.create("Rent", 1000).status_code == 201
    _, row = _row(w, "Rent")
    assert Decimal(row["spent"]) == Decimal("950.00")
    assert Decimal(row["coming_up"]["amount"]) == Decimal("950.00")
    assert figures() == before


# --- the held view: coming up is what the forecast schedules (sec) -----------

@pytest.fixture
def bill(client, db_session):
    """Salary in 10 days (payday), a £300 phone bill due in 5, paid last
    month under category Phone, and a £400 Phone budget."""
    from tests.integration.test_no_claude_raise import World as BillWorld
    from tests.integration.test_transactions_endpoint import _account

    world = BillWorld(client, db_session, email="coming-up@example.com")
    world.as_user(lambda: _tx(db_session, _account(db_session, world.user.id, name="Current", balance="900"),
                              "300.00", TODAY - timedelta(days=25), merchant="Phone bill", category="Phone"))
    r = client.post("/api/v1/budgets", json={"category": "Phone", "limit_pounds": 400}, headers=_bearer(world.web))
    assert r.status_code == 201, r.text
    return world


def _forecast_bill(w) -> list[tuple[str, Decimal]]:
    f = w.client.get("/api/v1/analytics/forecast", headers=_bearer(w.web)).json()
    end = _budgets(w)["cycle"]["end"]
    return [(p["date"], -Decimal(str(e["amount"]))) for p in f["timeline"] for e in p["events"]
            if e.get("commitment_id") == str(w.bill) and p["date"] <= end]


def _coming(w) -> list[tuple[str, Decimal]]:
    _, row = _row(w, "Phone")
    return [(i["due_date"], Decimal(i["amount"])) for i in row["coming_up"]["items"]]


def test_coming_up_is_the_forecasts_instalments(bill):
    assert _coming(bill) == _forecast_bill(bill) == [((TODAY + timedelta(days=5)).isoformat(), Decimal("300.00"))]


@pytest.mark.parametrize("change", ["cut", "dismiss", "raise"])
def test_a_pending_claude_change_never_lowers_coming_up(bill, change):
    before = _coming(bill)
    if change == "dismiss":
        bill.claude_dismiss(bill.bill)
    else:
        bill.claude_update(bill.bill, amount="100.00" if change == "cut" else "350.00")
    held = _coming(bill)
    assert held == _forecast_bill(bill)
    assert sum(a for _, a in held) >= sum(a for _, a in before)


def test_a_bill_claude_confirms_without_a_keep_moves_no_spending_out(client, db_session, bill):
    """B-26 not made worse: in a budgeted category a commitment's payment
    counts either way, so Claude confirming one hides nothing."""
    def suggested():
        from tests.integration.test_transactions_endpoint import _account
        _tx(db_session, _account(db_session, bill.user.id, name="Second", balance="10"), "45.00",
            TODAY - timedelta(days=2), merchant="TOP UP CO", category="Phone")
        rule = CommitmentRule(user_id=bill.user.id, direction="expense", label="TOP UP CO", amount=Decimal("45"),
                              cadence="monthly", next_date=TODAY + timedelta(days=28), source="detected",
                              status="suggested")
        db_session.add(rule)
        db_session.commit()
        return rule.id
    rule_id = bill.as_user(suggested)
    spent = _row(bill, "Phone")[1]["spent"]
    bill.claude_update(rule_id, status="confirmed")
    assert _row(bill, "Phone")[1]["spent"] == spent == "45.00"


def test_a_bill_linked_to_a_loan_or_holding_adds_nothing_coming_up(bill, db_session):
    """B-34: a linked rule's payments are key-only matches; nothing is
    invented for it, though the forecast still schedules it."""
    import uuid

    from app.models import CommitmentLink

    db_session.add(CommitmentLink(user_id=bill.user.id, commitment_id=bill.bill, asset_id=uuid.uuid4(),
                                  role="contribution", commitment_created=False, created_on=TODAY))
    db_session.commit()
    assert _coming(bill) == [] and _forecast_bill(bill) != []


def test_a_bill_the_forecast_drops_for_its_card_repayment_is_not_coming_up(bill, db_session):
    """sec: a card-tied bill the larger card repayment replaces (`_card_ties`)."""
    from app.models import Account, AccountSetting, BankConnection

    def card_tie():
        conn = BankConnection(user_id=bill.user.id, provider_id="ob-amex", provider_name="AMEX",
                              access_token="t", refresh_token="r")
        db_session.add(conn)
        db_session.flush()
        card = Account(user_id=bill.user.id, bank_connection_id=conn.id, external_id="amex-coming-up",
                       provider_name="AMEX", account_type="CREDIT_CARD", display_name="Card",
                       current_balance=Decimal("1500.00"))
        db_session.add(card)
        db_session.flush()
        db_session.add(AccountSetting(user_id=bill.user.id, account_id=card.id, role="credit",
                                      repayment_strategy="full_balance", repayment_cadence="monthly",
                                      repayment_day=(TODAY + timedelta(days=7)).day))  # after the bill, before payday
        rule = db_session.get(CommitmentRule, bill.bill)
        rule.card_account_id, rule.card_link_source = card.id, "user"
        db_session.commit()
    bill.as_user(card_tie)
    assert _forecast_bill(bill) == [] and _coming(bill) == []


def test_suggest_measures_a_commitment_the_way_the_budget_counts_it(w):
    """eng-b on #294: Suggest and Past cycles must agree on a cycle's spend,
    so a category's paid commitments are in its suggested figures too."""
    def last_cycles():
        rows = w.suggest().json()["suggestions"]
        return [Decimal(c["spent"]) for c in next(s for s in rows if s["category"] == "Eating out")["last_cycles"]]
    before = last_cycles()
    _weekly(w, amount="5.00", paid_days_ago=(26, 33, 40))  # three instalments in the last complete cycle
    after = last_cycles()
    assert after[-1] == before[-1] + Decimal("15.00")
    assert after[:-1] == before[:-1]


# --- pace with commitments (lead, 2026-11-13; sec on #298) ---------------------
# pace_spent = placed + max(0, limit - placed) x the share of the cycle gone.
# Coming up plays no part: an instalment only due never moves the status. "Placed" is the commitment payments that sit on the line at their
# real dates: per commitment, at most its amount x its instalments due so far
# this cycle, judged by the before-Claude version while a Claude change is
# unkept, and never more than the budget's spent.

def _share(body) -> Decimal:
    c = body["cycle"]
    return Decimal(c["days_total"] - c["days_left"]) / Decimal(c["days_total"])


def _pace(body, limit, placed) -> Decimal:
    flexible = max(Decimal(0), Decimal(limit) - Decimal(placed))
    return (Decimal(placed) + flexible * _share(body)).quantize(Decimal("0.01"))


def _rent_due_when_paid(w):
    """The fixture's rent, due on the day it was paid (5 days ago), next in a month."""
    def move():
        [rule] = [r for r in w.db.query(CommitmentRule).filter(CommitmentRule.user_id == w.user.id)
                  if r.label == "LANDLORD RENT"]  # label is encrypted: compared in Python
        rule.next_date = TODAY - timedelta(days=5) + timedelta(days=30)
        w.db.commit()
    w.as_user(move)


def _planning_token(w) -> str:
    from tests.integration.test_oauth import READ, _connect

    return _connect(w.client, scopes=(READ, "finance:planning.write"), email="budgets@example.com")[2]["access_token"]


def _claude_update(w, token, rule_id, n, **fields):
    r = w.client.post(f"/api/v1/planning/commitments/{rule_id}/update", headers=_bearer(token),
                      json={**fields, "dry_run": False, "idempotency_key": f"pace-claude-{n:04d}"})
    assert r.status_code == 200, r.text


def test_with_no_commitments_pace_is_todays_even_spread(w):
    w.create("Groceries", 300)
    body, row = _row(w, "Groceries")
    assert Decimal(row["pace_spent"]) == (Decimal(300) * _share(body)).quantize(Decimal("0.01"))


def test_rent_paid_early_in_the_cycle_is_not_ahead_of_pace(w):
    """Should not count as ahead: rent paid on its due date sits on the line."""
    _rent_due_when_paid(w)
    w.create("Rent", 1100)
    body, row = _row(w, "Rent")
    assert Decimal(row["pace_spent"]) == _pace(body, 1100, "950.00")
    assert row["status"] in ("under_pace", "on_pace")


def test_rent_plus_heavy_day_to_day_spending_is_ahead_of_pace(w):
    """Should count as ahead: the flexible part runs ahead even with rent placed."""
    _rent_due_when_paid(w)
    # £1,040 of the £1,050 flexible part spent with about two thirds of the cycle gone.
    w.as_user(lambda: _tx(w.db, w.current, "1040.00", TODAY - timedelta(days=1), merchant="HOME STORE",
                          category="Rent"))
    w.create("Rent", 2000)
    _, row = _row(w, "Rent")
    assert Decimal(row["spent"]) == Decimal("1990.00")
    assert row["status"] == "ahead_of_pace"


def test_pace_never_sits_below_the_placed_commitments(w):
    """Placed beyond the limit floors the flexible part at £0."""
    _weekly(w)  # 3 x £16 paid on their due dates
    w.create("Eating out", 40)
    _, row = _row(w)
    assert Decimal(row["pace_spent"]) == Decimal("48.00")


def test_an_instalment_only_due_never_changes_pace_or_status(w):
    """eng-b on #298, owner settled item 1: coming up is a hint only."""
    w.create("Eating out", 200)
    before = _row(w)[1]
    _weekly(w, label="SUPPER CLUB", amount="30.00", paid_days_ago=(40,), next_in=2)  # paid last cycle only
    after = _row(w)[1]
    assert Decimal(after["coming_up"]["amount"]) > 0
    assert (after["pace_spent"], after["status"]) == (before["pace_spent"], before["status"])


def test_a_one_off_under_a_commitments_descriptor_is_not_placed(w):
    """sec's probe: a £600 one-off under a £10 weekly descriptor is
    discretionary spending, so Shopping stays ahead of pace."""
    _weekly(w, label="GADGET STORE", amount="10.00", category="Shopping", paid_days_ago=(3, 10, 17), next_in=4)
    w.as_user(lambda: _tx(w.db, w.current, "600.00", TODAY - timedelta(days=3), merchant="GADGET STORE",
                          category="Shopping"))
    w.create("Shopping", 800)
    body, row = _row(w, "Shopping")
    assert Decimal(row["spent"]) == Decimal("750.00")  # £120 + 3 x £10 + £600
    assert Decimal(row["pace_spent"]) == _pace(body, 800, "30.00")
    assert row["status"] == "ahead_of_pace"


def test_an_unkept_claude_confirm_leaves_pace_as_it_was(w):
    def suggested():
        _tx(w.db, w.current, "90.00", TODAY - timedelta(days=2), merchant="CORNER CAFE", category="Eating out")
        rule = CommitmentRule(user_id=w.user.id, direction="expense", label="CORNER CAFE", amount=Decimal("90"),
                              cadence="monthly", next_date=TODAY - timedelta(days=2) + timedelta(days=30),
                              source="detected", status="suggested")
        w.db.add(rule)
        w.db.commit()
        return rule.id
    rule_id = w.as_user(suggested)
    w.create("Eating out", 200)
    before = _row(w)[1]["pace_spent"]
    _claude_update(w, _planning_token(w), rule_id, 1, status="confirmed")
    assert _row(w)[1]["pace_spent"] == before


def test_an_unkept_claude_rename_leaves_pace_as_it_was(w):
    # Three instalments due so far but only one paid: under the old name it
    # places £16; under the new one the £60 cafe payment would place up to £48.
    kit = _weekly(w, paid_days_ago=(5,), next_in=30)
    w.as_user(lambda: _tx(w.db, w.current, "60.00", TODAY - timedelta(days=1), merchant="CORNER CAFE",
                          category="Eating out"))
    w.create("Eating out", 300)
    before = _row(w)[1]["pace_spent"]
    _claude_update(w, _planning_token(w), kit, 1, label="CORNER CAFE")
    assert _row(w)[1]["pace_spent"] == before


def test_friends_paying_back_never_open_pace_headroom(w):
    """sec nit: placed is never more than the budget's spent (net of marks)."""
    from app.services.budget_spend import BudgetSpend
    from app.services.budget_pace import placed_by_category

    spend = BudgetSpend(by_category={"Rent": Decimal("400.00")})
    placed = {"Rent": Decimal("950.00")}
    assert placed_by_category(spend, placed) == {"Rent": Decimal("400.00")}


# --- the "will go over" nudge (T-24-5c; spec "Will go over" nudge) ------------

def _nudges(w) -> list[dict]:
    r = w.client.get("/api/v1/analytics/nudges", headers=_bearer(w.web))
    assert r.status_code == 200, r.text
    return [n for n in r.json() if n.get("title", "") and n["title"].endswith("will go over")]


def _money(v) -> str:
    d = Decimal(v)
    return f"£{d:,.0f}" if d == d.to_integral_value() else f"£{d:,.2f}"


def test_will_go_over_fires_with_the_spec_copy_and_a_raise_to_the_next_50(w):
    _weekly(w)  # £88 spent; meal kit instalments still to come
    w.create("Eating out", 100)
    _, row = _row(w)
    coming, opb = Decimal(row["coming_up"]["amount"]), Decimal(row["over_by_payday"])
    assert opb > 0 and Decimal(row["spent"]) < 100
    [nudge] = _nudges(w)
    assert nudge["title"] == "Eating out will go over"
    assert nudge["body"] == (f"£12 left, but {KIT} has {_money(coming)} still to come before payday. "
                             f"Raise the budget or expect to be {_money(opb)} over.")
    total = Decimal("88.00") + coming
    assert nudge["cta"] == {"label": f"Raise to £{-(-int(total) // 50) * 50}", "budget_id": row["id"],
                            "new_limit_pounds": -(-int(total) // 50) * 50}
    assert nudge["detail"].startswith("Spent £88 of £100 this pay cycle, from ")
    assert f"Coming up: {KIT} {_money(coming)} (" in nudge["detail"] and nudge["detail"].endswith(f"{_money(total)} in all.")
    assert nudge["id"].startswith("budget-") and nudge["rank"] == 10


def test_two_commitments_name_the_largest_and_count_the_others(w):
    _weekly(w)
    _weekly(w, label="SUPPER CLUB", amount="30.00", paid_days_ago=(40,), next_in=3)
    w.create("Eating out", 100)
    [nudge] = _nudges(w)
    assert nudge["body"].startswith("£12 left, but SUPPER CLUB and 1 other have ")


@pytest.mark.parametrize("limit", ["exactly", "already_over"])
def test_no_will_go_over_when_it_would_land_on_the_limit_or_is_already_over(w, limit):
    _weekly(w)
    if limit == "exactly":
        w.create("Eating out", 150)
        _, row = _row(w)
        w.patch(row["id"], limit_pounds=int(Decimal("88.00") + Decimal(row["coming_up"]["amount"])))
    else:
        w.create("Eating out", 80)
    assert _nudges(w) == []


def test_will_go_over_fires_once_and_stays_dismissed(w):
    _weekly(w)
    w.create("Eating out", 100)
    [first] = _nudges(w)
    [again] = _nudges(w)
    assert again["id"] == first["id"]
    nudge_id = first["id"].removeprefix("budget-")
    assert w.client.post(f"/api/v1/budgets/nudges/{nudge_id}/dismiss", headers=_bearer(w.web)).status_code < 300
    assert _nudges(w) == []


def test_the_kind_fits_the_stored_column():
    from app.models import BudgetNudge
    from app.services.budgets import OVER_SOON

    assert len(OVER_SOON) <= BudgetNudge.__table__.c.kind.type.length


def test_no_raise_is_offered_past_the_largest_limit_allowed(w):
    """sec on #302: never offer a raise the server would refuse."""
    from app.schemas.budgets import BUDGET_LIMIT_MAX

    _weekly(w)
    w.as_user(lambda: _tx(w.db, w.current, "99900.00", TODAY - timedelta(days=1), merchant="BANQUET HALL",
                          category="Eating out"))
    w.create("Eating out", BUDGET_LIMIT_MAX)
    _, row = _row(w)
    assert Decimal(row["spent"]) < BUDGET_LIMIT_MAX < Decimal(row["spent"]) + Decimal(row["coming_up"]["amount"])
    [nudge] = _nudges(w)
    assert nudge["cta"] is None
    assert "Raise the budget or expect to be" in nudge["body"]
