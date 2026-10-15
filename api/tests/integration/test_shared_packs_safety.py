"""Shared rule packs (T-12-10b part 2; sec T-12-10b).

- New share codes carry 120 bits (`token_urlsafe(15)`, the column's 20
  characters), so guessing one fails.
- Looking codes up (preview and import) is limited per user.
- Import re-runs `validate_pattern` on every rule of the snapshot: the
  snapshot was written by another user, so it is untrusted input. A pattern
  over the length cap, an invalid regex, or a catastrophic one (nested
  quantifiers, the ReDoS shape) refuses the whole import; nothing is written.
- `validate_pattern` refuses catastrophic regexes everywhere it runs.

Synthetic patterns only.
"""
import json
import time

import pytest

from app.core import rate_limit
from app.models import CategoryRule, RulePack
from app.services import categorization
from tests.integration.test_oauth import _bearer, _web_login

API = "/api/v1"

# The ReDoS fixture: nested quantifiers backtrack exponentially on a near miss.
CATASTROPHIC = ["(a+)+$", "(.*)*X", "(\\w+)*@", "([a-z]+)+\\d", "(a|aa)+$", "(x+x+)+y"]
FINE = ["TESCO", "^AMZN.*MKTP", "(COFFEE|TEA) SHOP", "\\d{4} CARD", "[A-Z]+ LTD"]


@pytest.mark.parametrize("pattern", CATASTROPHIC)
def test_catastrophic_regexes_are_refused(pattern):
    assert categorization.validate_pattern(pattern, "regex") == "Pattern could take too long to match (nested repetition)"


@pytest.mark.parametrize("pattern", FINE)
def test_ordinary_regexes_still_pass(pattern):
    assert categorization.validate_pattern(pattern, "regex") is None


def test_a_contains_pattern_is_never_judged_as_a_regex():
    assert categorization.validate_pattern("(a+)+", "contains") is None


def test_the_check_reads_the_parsed_pattern_and_is_fast():
    started = time.perf_counter()
    for p in CATASTROPHIC * 50:
        categorization.validate_pattern(p, "regex")
    assert time.perf_counter() - started < 0.5


def _share(client, owner, patterns):
    body = {"name": "Shared", "rules": [{"pattern": p, "category": "Groceries"} for p in patterns]}
    pack_id = client.post(f"{API}/rules/packs/bulk", json=body, headers=owner).json()["pack_id"]
    return client.post(f"{API}/rules/packs/{pack_id}/share", headers=owner).json()["share_code"]


def test_new_share_codes_carry_120_bits_and_fit_the_column(client):
    owner = _bearer(_web_login(client, "share-owner@example.com"))
    assert len(_share(client, owner, ["TESCO"])) == 20  # token_urlsafe(15): 120 bits; String(20)


def test_import_refuses_a_snapshot_with_a_catastrophic_pattern_and_writes_nothing(client, db_session):
    owner = _bearer(_web_login(client, "share-owner2@example.com"))
    code = _share(client, owner, ["TESCO"])
    # A tampered snapshot (as if written before the check, or by hand).
    pack = db_session.query(RulePack).filter(RulePack.share_code == code).one()
    pack.share_snapshot = json.dumps([
        {"pattern": "TESCO", "match_type": "contains", "match_field": "any", "category": "Groceries", "enabled": True},
        {"pattern": "(a+)+$", "match_type": "regex", "match_field": "any", "category": "Groceries", "enabled": True},
    ])
    db_session.commit()
    importer = _bearer(_web_login(client, "share-importer@example.com"))
    packs_before, rules_before = db_session.query(RulePack).count(), db_session.query(CategoryRule).count()
    res = client.post(f"{API}/rules/import", json={"share_code": code}, headers=importer)
    assert res.status_code == 400
    assert "nested repetition" in res.json()["detail"]
    assert (db_session.query(RulePack).count(), db_session.query(CategoryRule).count()) == (packs_before, rules_before)


def test_import_refuses_an_overlong_pattern(client, db_session):
    owner = _bearer(_web_login(client, "share-owner3@example.com"))
    code = _share(client, owner, ["TESCO"])
    pack = db_session.query(RulePack).filter(RulePack.share_code == code).one()
    pack.share_snapshot = json.dumps([{"pattern": "A" * 201, "match_type": "contains", "match_field": "any",
                                        "category": "Groceries", "enabled": True}])
    db_session.commit()
    importer = _bearer(_web_login(client, "share-importer3@example.com"))
    assert client.post(f"{API}/rules/import", json={"share_code": code}, headers=importer).status_code == 400


def test_a_clean_import_still_works(client):
    owner = _bearer(_web_login(client, "share-owner4@example.com"))
    code = _share(client, owner, ["TESCO", "^AMZN.*MKTP"])
    importer = _bearer(_web_login(client, "share-importer4@example.com"))
    assert client.post(f"{API}/rules/import", json={"share_code": code}, headers=importer).status_code == 201


def test_code_lookups_are_limited_per_user(client, monkeypatch):
    monkeypatch.setitem(rate_limit.LIMITS, "shared-lookup", (2, 60))
    alice = _bearer(_web_login(client, "guess-alice@example.com"))
    bob = _bearer(_web_login(client, "guess-bob@example.com"))
    codes = [client.get(f"{API}/rules/shared/nope{n}", headers=alice).status_code for n in range(2)]
    assert codes == [404, 404]
    assert client.get(f"{API}/rules/shared/nope3", headers=alice).status_code == 429
    assert client.post(f"{API}/rules/import", json={"share_code": "nope4"}, headers=alice).status_code == 429
    assert client.get(f"{API}/rules/shared/nope5", headers=bob).status_code == 404
