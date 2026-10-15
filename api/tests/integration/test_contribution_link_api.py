"""An investment's monthly contribution as a linked commitment (T-11-3c;
ADR-002 sections 3-4; sec T-11-3; owner D2 and D4).

`PUT /assets/{id}/contribution` opts in (or edits), `DELETE` opts out. The
server sets every link field; the user picks any existing bill it takes over
(never automatic, even with one match). Once linked, the bill counts once:
in safe-to-spend and the forecast as a scheduled outflow, in the holding as
its contribution (never also the legacy `monthly_contribution`), and net
worth does not drop on the payment day. Synthetic: £500 a month into an ISA.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import Asset, AssetValuation, CommitmentLink, CommitmentRule
from app.services.analytics.common import _add_months
from tests.clock import TODAY
from tests.integration.test_commitment_links import Links
from tests.integration.test_linked_commitment_guards import API, _bearer
from tests.integration.test_transactions_endpoint import _account

NEXT = TODAY + timedelta(days=10)
BODY = {"amount": "500.00", "next_date": NEXT.isoformat()}


class World(Links):
    def put(self, holding, token=None, **body):
        return self.client.put(f"{API}/assets/{holding}/contribution", json={**BODY, **body},
                               headers=_bearer(token or self.web))

    def opt_out(self, asset_id, token=None):
        return self.client.delete(f"{API}/assets/{asset_id}/contribution", headers=_bearer(token or self.web))

    def bills(self):
        self.db.expire_all()
        with self.as_user():
            rules = self.db.query(CommitmentRule).filter(CommitmentRule.user_id == self.user.id).all()
            return {r.id: (r.label, r.amount, r.status, r.next_date) for r in rules}

    def asset_row(self, asset_id):
        self.db.expire_all()
        with self.as_user():
            a = self.db.get(Asset, asset_id)
            return a.monthly_contribution, [(v.valued_at, v.value) for v in a.valuations]

    def net_worth(self):
        return Decimal(self.summary()["net_worth"])


@pytest.fixture
def world(client, db_session):
    return World(client, db_session, email="contribution-link@example.com")


@pytest.fixture
def bob(client, db_session):
    return World(client, db_session, email="contribution-link-bob@example.com")


# --------------------------------------------------------------------------- #
# Opting in (rules 1, 2, D2)
# --------------------------------------------------------------------------- #
def test_opting_in_with_no_matching_bill_creates_a_confirmed_monthly_one(world):
    isa = world.asset()
    res = world.put(isa)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["link_result"] == "created"
    bill = uuid.UUID(body["linked_commitment"]["id"])
    assert world.bills() == {bill: ("Example ISA contribution", Decimal("500.00"), "confirmed", NEXT)}
    rule = world.rule(bill)
    assert (rule.cadence, rule.direction) == ("monthly", "expense")
    (link,) = world.rows()
    assert (link.asset_id, link.role, link.commitment_created, link.created_on) == (isa, "contribution", True, TODAY)


def test_one_matching_bill_is_never_taken_over_without_the_users_choice(world):
    existing = world.commitment(label="ISA DD", amount="500.00")
    isa = world.asset()
    before = world.bills()
    res = world.put(isa)
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "choose_commitment"
    assert [c["id"] for c in detail["candidates"]] == [str(existing)]
    assert world.bills() == before and world.rows() == []


def test_choosing_the_bill_takes_it_over_and_says_which(world):
    existing = world.commitment(label="ISA DD", amount="500.00", status="suggested")
    isa = world.asset()
    body = world.put(isa, commitment_choice=str(existing)).json()
    assert body["link_result"] == "linked"
    assert body["linked_commitment"] == {"id": str(existing), "label": "ISA DD"}
    assert world.rule(existing).status == "confirmed"
    (link,) = world.rows()
    assert link.commitment_created is False


def test_a_bill_named_after_the_holding_is_a_candidate_whatever_its_amount(world):
    # ux A7: monthly, and the same amount or a label containing the name.
    named = world.commitment(label="Example ISA top-up", amount="350.00")
    world.commitment(label="Gym", amount="350.00")
    res = world.put(world.asset())
    assert res.status_code == 409
    assert [c["id"] for c in res.json()["detail"]["candidates"]] == [str(named)]


def test_the_bill_is_paid_from_the_chosen_account(world):
    with world.as_user():
        current = _account(world.db, world.user.id, name="Current").id
    bill = uuid.UUID(world.put(world.asset(), pay_from_account_id=str(current)).json()["linked_commitment"]["id"])
    assert world.rule(bill).account_id == current


def test_choosing_new_creates_one_even_when_a_bill_matches(world):
    world.commitment(label="ISA DD", amount="500.00")
    assert world.put(world.asset(), commitment_choice="new").json()["link_result"] == "created"
    assert len(world.bills()) == 2


def test_a_choice_that_is_not_a_candidate_writes_nothing(world, bob):
    isa = world.asset()
    other_amount = world.commitment(label="Gym", amount="30.00")
    dismissed = world.commitment(label="Old ISA", amount="500.00", status="dismissed")
    card_bill = world.commitment(label="CARD DD", amount="500.00")
    with world.as_user():
        world.db.get(CommitmentRule, card_bill).card_account_id = world.amex_card()
        world.db.commit()
    loan_bill = world.linked_bill()
    bobs = bob.commitment(label="Bob ISA", amount="500.00")
    before = world.bills()
    for choice in (other_amount, dismissed, card_bill, loan_bill, bobs, uuid.UUID(int=7), "not-an-id"):
        res = world.put(isa, commitment_choice=str(choice))
        assert res.status_code in (409, 422), choice
        assert world.bills() == before
    assert [r for r in world.rows() if r.asset_id is not None] == []


@pytest.mark.parametrize("asset_type", ["property", "savings", "loan", "other"])
def test_only_investment_kinds_take_a_contribution(world, asset_type):
    asset = world.asset(asset_type=asset_type, value="-100.00" if asset_type == "loan" else "1000.00")
    assert world.put(asset).status_code == 422
    assert world.bills() == {}


@pytest.mark.parametrize("field,value", [
    ("user_id", "00000000-0000-0000-0000-000000000001"), ("role", "repayment"),
    ("commitment_created", True), ("created_on", "2020-01-01"), ("id", "00000000-0000-0000-0000-000000000002"),
    ("asset_id", "00000000-0000-0000-0000-000000000003"), ("cadence", "weekly"),
])
def test_server_set_fields_are_refused(world, field, value):
    res = world.put(world.asset(), **{field: value})
    assert res.status_code == 422
    assert world.bills() == {}


@pytest.mark.parametrize("change", [
    {"amount": "0"}, {"amount": "-1.00"}, {"amount": "10000000.01"}, {"amount": "1.005"},
    {"next_date": (TODAY - timedelta(days=1)).isoformat()},
    {"next_date": (TODAY + timedelta(days=367)).isoformat()},
])
def test_out_of_bounds_terms_are_422(world, change):
    assert world.put(world.asset(), **change).status_code == 422
    assert world.bills() == {}


def test_the_largest_amount_is_accepted(world):
    assert world.put(world.asset(), amount="10000000.00").status_code == 200


def test_another_users_holding_is_404_and_nothing_is_written(world, bob):
    isa = world.asset()
    assert bob.put(isa).status_code == 404
    world.put(isa)
    before = world.bills()
    assert bob.opt_out(isa).status_code == 404
    assert world.bills() == before and len(world.rows()) == 1


def test_linking_replaces_the_legacy_monthly_contribution(world):
    res = world.client.post(f"{API}/assets", json={"name": "Example ISA", "asset_type": "isa", "value": "1000.00",
                                                   "monthly_contribution": "300.00"}, headers=_bearer(world.web))
    isa = uuid.UUID(res.json()["id"])
    world.put(isa)
    assert world.asset_row(isa)[0] is None


def test_the_asset_list_says_what_it_is_linked_to_and_its_terms(world):
    with world.as_user():
        current = _account(world.db, world.user.id, name="Current").id
    isa = world.asset()
    bill = world.put(isa, pay_from_account_id=str(current)).json()["linked_commitment"]
    (row,) = world.client.get(f"{API}/assets", headers=_bearer(world.web)).json()
    assert row["linked_commitment"] == {**bill, "amount": "500.00", "next_date": NEXT.isoformat(),
                                        "pay_from_account_id": str(current), "created": True}


def test_the_asset_list_says_when_the_bill_was_the_users_own(world):
    # The untick confirm (#221) says the bill stays when the user had it.
    existing = world.commitment(label="ISA DD", amount="500.00")
    isa = world.asset()
    world.put(isa, commitment_choice=str(existing))
    (row,) = world.client.get(f"{API}/assets", headers=_bearer(world.web)).json()
    assert row["linked_commitment"]["created"] is False


def test_the_link_service_imports_on_its_own():
    # eng-b on #210: a circular import made `import holding_links` fail first.
    import subprocess
    import sys
    from pathlib import Path
    api = Path(__file__).resolve().parents[2]
    for module in ("app.services.holding_links",):
        r = subprocess.run([sys.executable, "-c", f"import {module}"], cwd=api, capture_output=True, text=True)
        assert r.returncode == 0, (module, r.stderr[-500:])


# --------------------------------------------------------------------------- #
# Editing and opting out (rules 3, 4)
# --------------------------------------------------------------------------- #
def test_editing_the_contribution_updates_the_same_bill(world):
    isa = world.asset()
    bill = uuid.UUID(world.put(isa).json()["linked_commitment"]["id"])
    later = NEXT + timedelta(days=3)
    assert world.put(isa, amount="650.00", next_date=later.isoformat()).status_code == 200
    assert world.bills() == {bill: ("Example ISA contribution", Decimal("650.00"), "confirmed", later)}


def test_a_linked_holding_refuses_a_legacy_contribution_or_a_kind_without_one(world):
    isa = world.asset()
    world.put(isa)
    for change in ({"monthly_contribution": "100.00"}, {"asset_type": "property"}):
        res = world.client.patch(f"{API}/assets/{isa}", json=change, headers=_bearer(world.web))
        assert res.status_code == 409, change
    assert world.asset_row(isa)[0] is None


def test_opting_out_deletes_a_bill_the_link_created(world):
    isa = world.asset()
    world.put(isa)
    assert world.opt_out(isa).status_code == 200
    assert world.bills() == {} and world.rows() == []


def test_opting_out_keeps_the_contribution_on_the_investment(world):
    # ux: "The monthly contribution stays on the investment."
    isa = world.asset()
    world.put(isa, amount="650.00")
    world.opt_out(isa)
    assert world.asset_row(isa)[0] == Decimal("650.00")


def test_opting_out_keeps_a_bill_the_user_already_had(world):
    existing = world.commitment(label="ISA DD", amount="500.00")
    isa = world.asset()
    world.put(isa, commitment_choice=str(existing))
    assert world.opt_out(isa).status_code == 200
    assert list(world.bills()) == [existing] and world.rows() == []
    assert world.patch(existing, amount="510.00").status_code == 200  # the guard lifted


def test_opting_out_keeps_net_worth_by_writing_todays_value(world):
    isa = world.asset(value="1000.00")
    world.put(isa)
    _backdate(world, isa, valued=TODAY - timedelta(days=20), linked=TODAY - timedelta(days=20),
              next_date=_add_months(TODAY - timedelta(days=5), 1))
    worth = world.net_worth()
    assert world.opt_out(isa).status_code == 200
    assert world.net_worth() == worth
    assert world.asset_row(isa)[1][-1] == (TODAY, Decimal("1500.00"))


def test_opting_out_of_an_unlinked_holding_is_404(world):
    assert world.opt_out(world.asset()).status_code == 404


# --------------------------------------------------------------------------- #
# Counted once
# --------------------------------------------------------------------------- #
def _backdate(world, isa, valued, linked, next_date):
    """Move the valuation and the link start into the past, and the bill's
    next date to the given day, so one payment has already gone."""
    with world.as_user():
        (valuation,) = world.db.query(AssetValuation).filter(AssetValuation.asset_id == isa).all()
        valuation.valued_at = valued
        world.db.query(CommitmentLink).filter(CommitmentLink.asset_id == isa).one().created_on = linked
        bill = world.db.query(CommitmentLink.commitment_id).filter(CommitmentLink.asset_id == isa).scalar()
        world.db.get(CommitmentRule, bill).next_date = next_date
        world.db.commit()


def test_safe_to_spend_drops_by_the_contribution_and_the_forecast_shows_it(world):
    with world.as_user():
        _account(world.db, world.user.id, name="Current", balance="5000")
    before = world.summary()
    world.put(world.asset())
    after = world.summary()
    assert Decimal(before["safe_to_spend"]) - Decimal(after["safe_to_spend"]) == Decimal("500.00")
    f = world.client.get(f"{API}/analytics/forecast?horizon=90", headers=_bearer(world.web)).json()
    days = [p["date"] for p in f["timeline"] for e in p["events"] if e["label"] == "Example ISA contribution"]
    assert days[0] == NEXT.isoformat() and len(days) == 3


def test_net_worth_does_not_drop_on_the_payment_day(world):
    isa = world.asset(value="1000.00")
    world.put(isa)
    paid_on = TODAY - timedelta(days=5)
    _backdate(world, isa, valued=TODAY - timedelta(days=20), linked=TODAY - timedelta(days=20),
              next_date=_add_months(paid_on, 1))
    # The bank paid £500 five days ago; the ISA holds it until re-valued.
    assert Decimal(world.summary()["net_worth"]) == Decimal("1500.00")
    position = world.client.get(f"{API}/analytics/net-worth-position", headers=_bearer(world.web)).json()
    assert Decimal(str(position["net_worth"])) == Decimal("1500.00")


def test_payments_count_even_when_the_bills_next_date_is_stale(world):
    # eng-b on #210: next_date only rolls forward on a commitments read or a
    # skip. A stale one in the past must still give every payment since.
    isa = world.asset(value="1000.00")
    world.put(isa)
    _backdate(world, isa, valued=TODAY - timedelta(days=80), linked=TODAY - timedelta(days=80),
              next_date=TODAY - timedelta(days=70))
    # Payments 70, ~40 and ~10 days ago, all within 90 days of the valuation.
    assert Decimal(world.summary()["net_worth"]) == Decimal("2500.00")


def test_the_asset_list_gives_value_today_with_payments_since(world):
    # eng-b's rows show the same value today as net worth (not the last entry).
    isa = world.asset(value="1000.00")
    world.put(isa)
    _backdate(world, isa, valued=TODAY - timedelta(days=20), linked=TODAY - timedelta(days=20),
              next_date=_add_months(TODAY - timedelta(days=5), 1))
    (row,) = world.client.get(f"{API}/assets", headers=_bearer(world.web)).json()
    assert row["value_today"] == "1500.00"
    assert Decimal(row["value_today"]) == Decimal(world.summary()["net_worth"])


def test_an_unlinked_assets_value_today_is_its_latest_value(world):
    world.asset(value="1000.00")
    (row,) = world.client.get(f"{API}/assets", headers=_bearer(world.web)).json()
    assert row["value_today"] == "1000.00"


def test_a_payment_before_the_link_started_is_not_counted(world):
    isa = world.asset(value="1000.00")
    world.put(isa)
    _backdate(world, isa, valued=TODAY - timedelta(days=20), linked=TODAY - timedelta(days=2),
              next_date=_add_months(TODAY - timedelta(days=5), 1))
    assert Decimal(world.summary()["net_worth"]) == Decimal("1000.00")


def test_payments_are_not_assumed_once_the_bill_is_not_confirmed(world):
    isa = world.asset(value="1000.00")
    bill = uuid.UUID(world.put(isa).json()["linked_commitment"]["id"])
    _backdate(world, isa, valued=TODAY - timedelta(days=20), linked=TODAY - timedelta(days=20),
              next_date=_add_months(TODAY - timedelta(days=5), 1))
    with world.as_user():
        world.db.get(CommitmentRule, bill).status = "suggested"
        world.db.commit()
    assert Decimal(world.summary()["net_worth"]) == Decimal("1000.00")


def test_the_projection_takes_the_contribution_from_the_bill_once(world):
    res = world.client.post(f"{API}/assets", json={"name": "Example ISA", "asset_type": "isa", "value": "1000.00",
                                                   "assumed_growth_pct": "5", "monthly_contribution": "300.00"},
                            headers=_bearer(world.web))
    isa = uuid.UUID(res.json()["id"])
    with world.as_user():
        _account(world.db, world.user.id, name="Current", balance="5000")
    world.put(isa)
    p = world.client.get(f"{API}/analytics/net-worth-projection?annual_growth_pct=5",
                         headers=_bearer(world.web)).json()
    (assumption,) = p["asset_assumptions"]
    assert Decimal(str(assumption["monthly_contribution"])) == Decimal("500.00")  # the bill, not £300 or £800


def test_linking_is_net_worth_neutral_in_the_projection(world):
    # Same growth for the ISA and the swept surplus: moving £500 a month from
    # surplus (the bill) into the ISA (its contribution) changes no total.
    with world.as_user():
        _account(world.db, world.user.id, name="Current", balance="5000")
        world.commitment(label="Salary", amount="3000.00", direction="income")
    res = world.client.post(f"{API}/assets", json={"name": "Example ISA", "asset_type": "isa", "value": "1000.00",
                                                   "assumed_growth_pct": "5"}, headers=_bearer(world.web))
    isa = uuid.UUID(res.json()["id"])
    url = f"{API}/analytics/net-worth-projection?annual_growth_pct=5&spending_source=none"
    before = world.client.get(url, headers=_bearer(world.web)).json()["timeline"]
    world.put(isa)
    after = world.client.get(url, headers=_bearer(world.web)).json()["timeline"]
    assert [Decimal(str(p["value"])) for p in after[:13]] == [Decimal(str(p["value"])) for p in before[:13]]
    assert Decimal(str(after[1]["assets"])) - Decimal(str(before[1]["assets"])) == Decimal("500.00")


def test_linking_adds_nothing_to_average_spending_or_the_budget_line(world):
    with world.as_user():
        _account(world.db, world.user.id, name="Current", balance="5000")
    url = f"{API}/analytics/net-worth-projection?annual_growth_pct=5"
    before = world.client.get(url, headers=_bearer(world.web)).json()["contribution_basis"]
    world.put(world.asset())
    after = world.client.get(url, headers=_bearer(world.web)).json()["contribution_basis"]
    assert after["avg_spending_monthly"] == before["avg_spending_monthly"]
    assert after.get("budgets_monthly") == before.get("budgets_monthly")
    assert Decimal(str(after["bills_monthly"])) - Decimal(str(before["bills_monthly"])) == Decimal("500.00")


def test_deleting_the_linked_bill_shows_not_linked_and_stops_the_outflow(world, db_session):
    isa = world.asset()
    bill = uuid.UUID(world.put(isa).json()["linked_commitment"]["id"])
    with world.as_user():
        db_session.query(CommitmentLink).filter(CommitmentLink.commitment_id == bill).delete()
        db_session.delete(db_session.get(CommitmentRule, bill))  # as the FK cascade would
        db_session.commit()
    (row,) = world.client.get(f"{API}/assets", headers=_bearer(world.web)).json()
    assert row["linked_commitment"] is None
    f = world.client.get(f"{API}/analytics/forecast?horizon=90", headers=_bearer(world.web)).json()
    assert not any(e["label"] == "Example ISA contribution" for p in f["timeline"] for e in p["events"])

