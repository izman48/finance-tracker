"""What the commitment row needs to keep Claude's change (T-08-20 UI, ux spec 9.1).

The row's Keep button keeps every pending change Claude made to that
income, so the commitments list says which audit rows those are
(`keep_audit_ids`, oldest first). And a rename is not keeping, even when it
is of a detected commitment (which #124 turns manual).
"""
from decimal import Decimal

from app.models import CommitmentRule
from tests.integration.test_claude_income_parity import API, World
from tests.integration.test_oauth import _bearer


def test_a_pending_raise_lists_its_audit_row(client, db_session):
    w = World(client, db_session)
    cid = w.income("1000.00")
    first = w.claude_update(cid, amount="1200.00")
    second = w.claude_update(cid, amount="1500.00")
    assert w.commitment(cid)["keep_audit_ids"] == [first, second]


def test_kept_and_unheld_changes_list_nothing_to_keep(client, db_session):
    w = World(client, db_session)
    raised, cut = w.income("1000.00"), w.income("1000.00")
    audit_id = w.claude_update(raised, amount="1500.00")
    w.claude_update(cut, amount="600.00")
    assert w.keep(audit_id).status_code == 200
    assert w.commitment(raised)["keep_audit_ids"] == []
    assert w.commitment(cut)["keep_audit_ids"] == []


def test_renaming_a_detected_income_does_not_settle_a_pending_raise(client, db_session):
    """KP14 on a detected commitment (a rename may make it manual, #124): nothing is kept."""
    w = World(client, db_session)
    cid = w.income("1000.00")
    w.as_user(lambda: _make_detected(w, cid))
    audit_id = w.claude_update(cid, amount="1500.00")
    res = client.patch(f"{API}/analytics/commitments/{cid}", json={"label": "Salary"}, headers=_bearer(w.web))
    assert res.status_code == 200, res.text
    row = w.commitment(cid)
    assert row["keep"] == "pending" and row["keep_audit_ids"] == [audit_id]
    assert w.savable() == Decimal("1500.00")


def _make_detected(w, cid):
    w.db.query(CommitmentRule).filter(CommitmentRule.id == cid).update({"source": "detected"})
    w.db.commit()
