"""Card bill parts through the routes (T-12-7a part 2; sec-1 on #242).

The summary's `next_repayments` and the forecast's repayment events carry
`projected` (and the summary `parts`) over HTTP, and Claude-facing key sets
are pinned by exact equality. Synthetic fixture: statement £5,000, current
balance £6,000, so £1,000 spent since is projected.
"""
from tests.integration.test_card_statements_api import API, STATEMENT
from tests.integration.test_statement_strategy_api import alice  # noqa: F401 (fixture)


def test_the_summary_sends_projected_and_parts_with_exact_keys(alice):  # noqa: F811
    alice.add()
    reps = alice.client.get(f"{API}/analytics/summary", headers=alice.headers).json()["next_repayments"]
    for r in reps:
        assert set(r) == {"account_id", "label", "amount", "due_date", "projected", "parts"}
        for part in r["parts"]:
            assert set(part) == {"kind", "amount"}
    assert [(r["projected"], [p["kind"] for p in r["parts"]]) for r in reps] == [
        (False, ["statement"]), (True, ["spent_since"]),
    ]
    assert reps[0]["due_date"] == STATEMENT["due_date"]


def test_the_forecast_route_marks_the_projected_bill(alice):  # noqa: F811
    alice.add()
    f = alice.client.get(f"{API}/analytics/forecast?horizon=80", headers=alice.headers).json()
    events = [e for p in f["timeline"] for e in p["events"] if e["kind"] == "repayment"]
    assert [e["projected"] for e in events] == [False, True]
    assert all(set(e) == {"label", "amount", "kind", "commitment_id", "projected"} for e in events)
