"""What the commitment row needs to keep Claude's change (T-08-20 UI, ux spec 9.1).

The row's Keep button keeps every pending change Claude made to that
income, so the commitments list says which audit rows those are
(`keep_audit_ids`, oldest first).
"""
from tests.integration.test_claude_income_parity import World


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
