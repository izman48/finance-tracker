"""Shared rule packs and user regexes (T-12-10b part 2; sec T-12-10b; lead
decision on #248).

- Regex rules run on RE2 (`google-re2`), a linear-time engine, so no pattern
  can backtrack: a structural check was whack-a-mole (eng-a and sec-1 found
  bypasses). The bypass fixtures below are pinned with a time budget.
- Patterns RE2 can't compile (back-references, look-arounds, conditional
  groups) are refused where they are written and on import; a stored one is
  skipped when rules load, logging a count only.
- New share codes carry 120 bits (`token_urlsafe(15)`, the column's 20
  characters), so guessing one fails, and lookups are limited per user.
- Import re-runs `validate_pattern` on every snapshot rule (another user's
  text): one refused pattern refuses the whole import; nothing is written.

Synthetic patterns only.
"""
import json
import logging
import time
import uuid

import pytest

from app.core import rate_limit
from app.models import CategoryRule, RulePack, Transaction
from app.services import categorization
from tests.integration.test_oauth import _bearer, _web_login

API = "/api/v1"

# ReDoS shapes, including the bypasses of the old structural check, each with
# an input that makes a backtracking engine take exponential time.
BYPASSES = [
    ("(a+)+$", "a" * 40 + "!"),
    ("(.*)*X", "a" * 40),
    ("(\\w+)*@", "a" * 40),
    ("(a|aa)+$", "a" * 40 + "!"),
    ("(\\w+\\s?){12}x", "a" * 31),
    ("(a{1,30}){1,30}$", "a" * 60 + "!"),
    ("(.*a){12}$", "a" * 40 + "!"),
]
UNSUPPORTED = ["(a)\\1", "(?=AMZN)AMZN", "(?<!X)TESCO", "(?(1)a|b)"]
FINE = ["TESCO", "^AMZN.*MKTP", "(COFFEE|TEA) SHOP", "\\d{4} CARD", "[A-Z]+ LTD"]


def _tx(description):
    return Transaction(account_id=uuid.uuid4(), external_id="x", transaction_type="debit", amount=1,
                       description=description, merchant_name=None)


@pytest.mark.parametrize("pattern,attack", BYPASSES)
def test_redos_shapes_match_in_linear_time(pattern, attack):
    assert categorization.validate_pattern(pattern, "regex") is None
    rule = CategoryRule(pattern=pattern, match_type="regex", match_field="any", category="X")
    started = time.perf_counter()
    for _ in range(20):
        categorization._rule_matches(rule, _tx(attack))
    assert time.perf_counter() - started < 0.2


@pytest.mark.parametrize("pattern", UNSUPPORTED)
def test_patterns_the_engine_cannot_run_are_refused(pattern):
    assert categorization.validate_pattern(pattern, "regex") == categorization.UNSUPPORTED_REGEX


@pytest.mark.parametrize("pattern", FINE)
def test_ordinary_regexes_still_pass_and_match_case_insensitively(pattern):
    assert categorization.validate_pattern(pattern, "regex") is None


def test_matching_is_case_insensitive_as_before():
    rule = CategoryRule(pattern="^amzn.*mktp", match_type="regex", match_field="any", category="X")
    assert categorization._rule_matches(rule, _tx("AMZN MKTP UK"))


def test_a_contains_pattern_is_never_judged_as_a_regex():
    assert categorization.validate_pattern("(a)\\1", "contains") is None


def test_a_stored_rule_the_engine_cannot_run_is_skipped_with_a_count_only(client, db_session, caplog):
    token = _web_login(client, "stored-rx@example.com")
    from tests.integration.test_reset_purge import _dek
    from app.core import user_crypto
    from app.models import User
    user = db_session.query(User).filter(User.email == "stored-rx@example.com").one()
    ctx = user_crypto.current_dek.set(_dek(token))
    try:
        db_session.add_all([
            CategoryRule(user_id=user.id, pattern="SECRETSHOP(?=X)", match_type="regex", category="Groceries"),
            CategoryRule(user_id=user.id, pattern="TESCO", match_type="contains", category="Groceries"),
        ])
        db_session.commit()
        caplog.set_level(logging.INFO)
        rules = categorization.active_rules(db_session, user.id)
    finally:
        user_crypto.current_dek.reset(ctx)
    assert [r.pattern for r in rules] == ["TESCO"]
    assert "skipped 1 stored regex rule" in caplog.text.lower()
    assert "SECRETSHOP" not in caplog.text


def _share(client, owner, patterns):
    body = {"name": "Shared", "rules": [{"pattern": p, "category": "Groceries"} for p in patterns]}
    pack_id = client.post(f"{API}/rules/packs/bulk", json=body, headers=owner).json()["pack_id"]
    return client.post(f"{API}/rules/packs/{pack_id}/share", headers=owner).json()["share_code"]


def test_new_share_codes_carry_120_bits_and_fit_the_column(client):
    owner = _bearer(_web_login(client, "share-owner@example.com"))
    assert len(_share(client, owner, ["TESCO"])) == 20  # token_urlsafe(15): 120 bits; String(20)


def test_import_refuses_a_snapshot_with_a_pattern_the_engine_cannot_run(client, db_session):
    owner = _bearer(_web_login(client, "share-owner2@example.com"))
    code = _share(client, owner, ["TESCO"])
    # A tampered snapshot (as if written before the check, or by hand).
    pack = db_session.query(RulePack).filter(RulePack.share_code == code).one()
    pack.share_snapshot = json.dumps([
        {"pattern": "TESCO", "match_type": "contains", "match_field": "any", "category": "Groceries", "enabled": True},
        {"pattern": "(a)\\1", "match_type": "regex", "match_field": "any", "category": "Groceries", "enabled": True},
    ])
    db_session.commit()
    importer = _bearer(_web_login(client, "share-importer@example.com"))
    packs_before, rules_before = db_session.query(RulePack).count(), db_session.query(CategoryRule).count()
    res = client.post(f"{API}/rules/import", json={"share_code": code}, headers=importer)
    assert res.status_code == 400
    assert categorization.UNSUPPORTED_REGEX in res.json()["detail"]
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


def test_the_rules_list_says_which_stored_rules_cannot_run(client, db_session):
    # Lead / sec-1 on #248: say so on the Rules page instead of quietly not matching.
    token = _web_login(client, "cant-run@example.com")
    from tests.integration.test_reset_purge import _dek
    from app.core import user_crypto
    from app.models import User
    user = db_session.query(User).filter(User.email == "cant-run@example.com").one()
    ctx = user_crypto.current_dek.set(_dek(token))
    try:
        db_session.add_all([
            CategoryRule(user_id=user.id, pattern="SHOP(?=X)", match_type="regex", category="Groceries"),
            CategoryRule(user_id=user.id, pattern="^AMZN.*MKTP", match_type="regex", category="Shopping"),
            CategoryRule(user_id=user.id, pattern="(a)\\1", match_type="contains", category="Other"),
        ])
        db_session.commit()
    finally:
        user_crypto.current_dek.reset(ctx)
    rules = {r["pattern"]: r for r in client.get(f"{API}/rules", headers=_bearer(token)).json()["personal"]}
    assert rules["SHOP(?=X)"]["cant_run"] == categorization.CANT_RUN_REASON
    assert rules["^AMZN.*MKTP"]["cant_run"] is None
    assert rules["(a)\\1"]["cant_run"] is None  # a contains rule is plain text
