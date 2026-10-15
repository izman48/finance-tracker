"""One link set for every holding (ADR-002 section 3, T-11-3b; sec items 1-2).

`commitment_links` holds one row per linked commitment, for loans and for
holdings, with UNIQUE(commitment_id): a bill is linked to at most one thing
of any kind, whatever the race. Loans keep `liabilities.linked_commitment_id`
as the value Sprint 10 code reads, and write a matching row in the same
transaction. `linked_commitment_ids()` is the union, so every guard covers
both. Synthetic figures only.
"""
import uuid
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import CommitmentLink, Liability
from app.services.linked_commitments import linked_commitment_ids, linked_commitments
from tests.integration.test_linked_commitment_guards import API, World, _bearer


class Links(World):
    def asset(self, name="Example ISA", asset_type="isa", value="1000.00") -> uuid.UUID:
        res = self.client.post(f"{API}/assets", json={"name": name, "asset_type": asset_type, "value": value},
                               headers=_bearer(self.web))
        assert res.status_code == 201, res.text
        return uuid.UUID(res.json()["id"])

    def contribution(self, asset_id=None, label="Example ISA contribution", amount="500.00") -> uuid.UUID:
        """A holding link written directly (the link API is T-11-3c)."""
        bill = self.commitment(label=label, amount=amount)
        self.link(bill, asset_id or self.asset(), created=True)
        return bill

    def link(self, bill, asset_id, created=False):
        with self.as_user():
            self.db.add(CommitmentLink(user_id=self.user.id, commitment_id=bill, asset_id=asset_id,
                                       role="contribution", commitment_created=created, created_on=date(2026, 10, 1)))
            self.db.commit()

    def loan_bill(self, liability_id) -> uuid.UUID:
        """The loan's link as Sprint 10 code reads it (plaintext column)."""
        self.db.expire_all()
        return self.db.query(Liability.linked_commitment_id).filter(
            Liability.id == uuid.UUID(str(liability_id))).scalar()

    def rows(self):
        self.db.expire_all()
        return self.db.query(CommitmentLink).filter(CommitmentLink.user_id == self.user.id).all()

    def liabilities(self):
        self.db.expire_all()
        with self.as_user():
            rows = self.db.query(Liability).filter(Liability.user_id == self.user.id).all()
            return [(x.id, x.linked_commitment_id, x.commitment_created) for x in rows]


@pytest.fixture
def links(client, db_session):
    return Links(client, db_session, email="links@example.com")


def _agree(links):
    """The loan column and the link rows describe the same links."""
    column = {x for x in links.liabilities() if x[1] is not None}
    rows = {(r.liability_id, r.commitment_id, r.commitment_created) for r in links.rows()
            if r.liability_id is not None}
    assert column == rows
    assert all(r.role == "repayment" for r in links.rows() if r.liability_id is not None)


# --------------------------------------------------------------------------- #
# Loans write a matching row
# --------------------------------------------------------------------------- #
def test_linking_a_loan_writes_a_matching_row(links):
    links.loan()
    (row,) = links.rows()
    assert row.role == "repayment" and row.commitment_created is True and row.asset_id is None
    _agree(links)


def test_a_taken_over_bill_is_recorded_as_not_created(links):
    links.commitment(label="LOAN DD", amount="200.00")
    links.loan()
    (row,) = links.rows()
    assert row.commitment_created is False
    _agree(links)


def test_opting_out_and_back_in_keeps_the_rows_in_step(links):
    loan = links.loan()
    res = links.client.patch(f"{API}/liabilities/{loan['id']}", json={"opted_out": True, "payment": None},
                             headers=_bearer(links.web))
    assert res.status_code == 200, res.text
    assert links.rows() == []
    _agree(links)
    res = links.client.patch(f"{API}/liabilities/{loan['id']}", json={"opted_out": False, "payment": "200.00"},
                             headers=_bearer(links.web))
    assert res.status_code == 200, res.text
    assert len(links.rows()) == 1
    _agree(links)


def test_deleting_a_loan_removes_its_row_and_keeps_the_bill(links):
    loan = links.loan()
    bill = uuid.UUID(loan["linked_commitment"]["id"])
    assert links.client.delete(f"{API}/liabilities/{loan['id']}", headers=_bearer(links.web)).status_code == 204
    assert links.rows() == []
    assert links.rule(bill) is not None
    assert bill not in linked_commitment_ids(links.db, links.user.id)


# --------------------------------------------------------------------------- #
# One link per commitment, across kinds
# --------------------------------------------------------------------------- #
def test_the_union_holds_loan_and_holding_links(links):
    loan_bill = links.linked_bill()
    isa_bill = links.contribution()
    owners = linked_commitments(links.db, links.user.id)
    assert set(owners) == {loan_bill, isa_bill}
    assert owners[loan_bill].kind == "liability" and owners[isa_bill].kind == "holding"
    assert linked_commitment_ids(links.db, links.user.id) == {loan_bill, isa_bill}


def test_a_loans_bill_cannot_also_be_linked_to_a_holding(links):
    loan_bill = links.linked_bill()
    asset_id = links.asset()
    with links.as_user():
        links.db.add(CommitmentLink(user_id=links.user.id, commitment_id=loan_bill, asset_id=asset_id,
                                    role="contribution", commitment_created=False, created_on=date(2026, 10, 1)))
        with pytest.raises(IntegrityError):
            links.db.commit()
        links.db.rollback()


def test_a_loan_never_takes_over_a_holdings_contribution(links):
    links.contribution(amount="200.00", label="LOAN DD")  # same amount and cadence as the loan
    assert links.loan()["link_result"] == "created"


def test_a_racing_loan_link_of_a_holdings_bill_is_a_409(links, monkeypatch):
    links.contribution(amount="200.00", label="LOAN DD")
    # The candidate list was computed before the holding link landed.
    from app.services import liability_links
    monkeypatch.setattr(liability_links, "_linked_ids", lambda db, user_id: set())
    res = links.client.post(f"{API}/liabilities", json={**_loan_body(), "lender": "Second"},
                            headers=_bearer(links.web))
    assert res.status_code == 409
    assert links.liabilities() == []


def _loan_body():
    from tests.integration.test_linked_commitment_guards import LOAN
    return dict(LOAN)


@pytest.mark.parametrize("owners", ["both", "none"])
def test_a_link_has_exactly_one_owner(links, owners):
    bill = links.commitment(label="Gym", amount="30.00")
    asset_id = links.asset()
    liability_id = uuid.UUID(links.loan()["id"]) if owners == "both" else None
    with links.as_user():
        links.db.add(CommitmentLink(user_id=links.user.id, commitment_id=bill,
                                    asset_id=asset_id if owners == "both" else None, liability_id=liability_id,
                                    role="contribution", commitment_created=False, created_on=date(2026, 10, 1)))
        with pytest.raises(IntegrityError):
            links.db.commit()
        links.db.rollback()


# --------------------------------------------------------------------------- #
# Deleting the holding lifts the guard (D4)
# --------------------------------------------------------------------------- #
def test_deleting_the_holding_keeps_the_bill_and_lifts_the_guard(links):
    asset_id = links.asset()
    bill = links.contribution(asset_id)
    assert links.patch(bill, amount="600.00").status_code == 409
    assert links.client.delete(f"{API}/assets/{asset_id}", headers=_bearer(links.web)).status_code == 200
    assert links.rows() == []
    assert links.patch(bill, amount="600.00").status_code == 200
    assert links.dismiss(bill, dry_run=False).status_code == 200


# --------------------------------------------------------------------------- #
# Purge and account deletion, foreign keys on (sec T-11-1, purge block)
# --------------------------------------------------------------------------- #
READS = ("/analytics/summary", "/analytics/forecast?horizon=90", "/analytics/net-worth-history",
         "/analytics/net-worth-position", "/analytics/net-worth-projection", "/analytics/commitments",
         "/assets", "/liabilities")


@pytest.fixture
def foreign_keys_on(db_session):
    db_session.commit()
    connection = db_session.connection()
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1  # the control is on
    yield
    db_session.rollback()
    db_session.connection().exec_driver_sql("PRAGMA foreign_keys=OFF")


def test_a_key_loss_purge_with_linked_holdings_finishes_and_every_read_is_200(links, client, db_session,
                                                                             foreign_keys_on):
    from app.services.key_loss_purge import purge_data_under_lost_key
    bystander = Links(client, db_session, email="links-bystander@example.com")
    bystander.contribution()
    links.loan()
    links.contribution()

    purge_data_under_lost_key(db_session, links.user.id)
    db_session.commit()

    assert links.rows() == []
    assert len(bystander.rows()) == 1
    for path in READS:
        assert links.client.get(f"{API}{path}", headers=_bearer(links.web)).status_code == 200, path


def test_deleting_the_account_removes_its_links_and_keeps_other_users(links, client, db_session, foreign_keys_on):
    from tests.integration.test_oauth import PASSWORD
    bystander = Links(client, db_session, email="links-bystander@example.com")
    bystander.contribution()
    links.loan()
    links.contribution()
    res = client.post(f"{API}/auth/delete-account", json={"password": PASSWORD}, headers=_bearer(links.web))
    assert res.status_code == 200, res.text
    owners = {r.user_id for r in db_session.query(CommitmentLink)}
    assert owners == {bystander.user.id}
