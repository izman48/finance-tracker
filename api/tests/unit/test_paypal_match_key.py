"""PayPal descriptors with changing reference codes (T-10-9).

Two real shapes (structure from the owner's data, values invented):

- Card account: "PAYPAL *SPOTIFY*P12A3B4 01234567890". The 7-character
  reference glued on with a second "*" changes every month; the trailing
  number is constant (and shared by every PayPal merchant on that account).
  The reference has fewer than six digits, so the general normaliser keeps it
  (it can't tell it from "MONZO123"), and every month gets its own key. Only
  that glued reference is dropped: the merchant after "PAYPAL *" always stays,
  digits and all ("O2", "7DIGITAL").
- Current account: "PAYPAL *NETFLIX ON 30 SEP BCC". The bank's "ON dd MON"
  date phrase changes every month. It is dropped from every descriptor: it is
  a date, never part of a name.

Over-merging hides money (sec): different merchants paid through PayPal keep
separate keys, and any PayPal descriptor without the glued reference keys
exactly as before. Descriptors are invented, with the same structure as real
ones.
"""
import pytest

from app.services.analytics.commitments import _match_key

PHONE = "01234567890"
SPOTIFY = [f"PAYPAL *SPOTIFY*P12A3B4 {PHONE}", f"PAYPAL *SPOTIFY*P11CD20 {PHONE}", f"PAYPAL *SPOTIFY*P10EF35 {PHONE}"]
NETFLIX = ["PAYPAL *NETFLIX ON 30 SEP BCC", "PAYPAL *NETFLIX ON 30 AUG BCC", "PAYPAL *NETFLIX ON 1 OCT BCC"]


def _key(desc: str) -> str:
    return _match_key("expense", desc)


def test_spotify_through_paypal_keys_identically_across_references():
    assert {_key(d) for d in SPOTIFY} == {"expense:paypal spotify"}


def test_netflix_with_a_date_phrase_keys_identically_across_months():
    assert {_key(d) for d in NETFLIX} == {"expense:paypal netflix bcc"}


def test_shapes_we_have_not_seen_key_as_before():
    # Narrow on purpose (eng-a, lead on #178): only the glued "*REF" goes.
    assert _key("PAYPAL *SPOTIFY P1A2B3C") == "expense:paypal spotify p1a2b3c"
    assert _key("PP*NETFLIX 7Z3K9Q") == "expense:pp netflix 7z3k9q"


def test_merchants_sharing_the_trailing_number_keep_separate_keys():
    steam = _key(f"PAYPAL *STEAM GAMES {PHONE}")
    patreon = _key(f"PAYPAL *PATREON MEMBERS {PHONE}")
    assert steam == "expense:paypal steam games"
    # Patreon already matches as a commitment: its key must not change.
    assert patreon == "expense:paypal patreon members"
    assert len({steam, patreon, _key(SPOTIFY[0])}) == 3


@pytest.mark.parametrize("desc, key", [
    ("TESCO STORES ON 3 OCT BCC", "expense:tesco stores bcc"),
    ("GYM LTD ON 28 FEB", "expense:gym ltd"),
    # Only a day and a month name after ON is a date phrase.
    ("MAY FAIR CAFE", "expense:may fair cafe"),
    ("SHOP ON 12 MAIN ST", "expense:shop on 12 main st"),
])
def test_the_on_dd_mon_date_phrase_is_dropped_everywhere(desc, key):
    assert _key(desc) == key


def test_different_merchants_through_paypal_keep_separate_keys():
    assert _key(SPOTIFY[0]) != _key(NETFLIX[0])
    assert _key("PAYPAL *SPOTIFY*P1A2B3C") != _key("PAYPAL *SPOTIFYUK*P1A2B3C")


@pytest.mark.parametrize("group", [
    # eng-a's over-merge cases on #178: merchants whose names carry digits.
    ["PAYPAL *O2 UK", "PAYPAL *7DIGITAL UK", "PAYPAL *4OD UK"],
    ["PAYPAL *1PASSWORD LTD", "PAYPAL *O2 LTD"],
    ["PAYPAL *A2B TAXIS", "PAYPAL *B2B SERVICES"],
    ["PAYPAL *O2*P1A2B3C", "PAYPAL *7DIGITAL*P1A2B3C", "PAYPAL *4OD*P1A2B3C"],
])
def test_merchants_with_digits_in_their_names_stay_distinct(group):
    keys = [_key(d) for d in group]
    assert len(set(keys)) == len(keys), keys
    assert all(k != "expense:paypal" for k in keys)


def test_a_glued_reference_after_a_two_word_merchant_is_dropped():
    assert _key("PAYPAL *STEAM GAMES*P1A2B3C") == _key("PAYPAL *STEAM GAMES*K9Z8Y7X") == "expense:paypal steam games"


@pytest.mark.parametrize("bare", [
    "PAYPAL 1A2B3C4D",
    "PAYPAL *9Z8Y7X6W",
    "PAYPAL PAYMENT A1B2C3",
    "PAYPAL EUROPE S A R L ET CIE S C A 1A2B3C",
    "PP*7Z3K9Q",
])
def test_a_paypal_descriptor_with_no_merchant_left_keeps_its_reference(bare):
    key = _key(bare)
    assert key not in {"expense:paypal", "expense:paypal payment"}
    assert key != _key(SPOTIFY[0])
    # Exactly the key the general normaliser gave it before this change.
    assert key == "expense:" + " ".join(bare.upper().replace("*", " ").split()).lower()


def test_two_bare_paypal_payments_with_different_references_stay_apart():
    assert _key("PAYPAL 1A2B3C4D") != _key("PAYPAL 9Z8Y7X6W")


@pytest.mark.parametrize("desc, key", [
    # The existing cases (#63, #68) give the same keys as before. (The one
    # change outside PayPal is the "ON dd MON" date phrase, tested above.)
    ("O2 UK", "expense:o2 uk"),
    ("MONZO123", "expense:monzo123"),
    ("RENT 1606LANDMARKE FT", "expense:rent 1606landmarke ft"),
    ("EE LIMITED Q42181371737681503 DDR", "expense:ee limited ddr"),
    ("COMMUNITYFIBRE LTD A1539913 DDR", "expense:communityfibre ltd ddr"),
    ("PP UTILITIES 12AB", "expense:pp utilities 12ab"),
    # PayPal withdrawals (income) and transfers key as before.
    ("TRANSFER FROM PAYPAL 12345", "expense:transfer from paypal"),
    # A merchant whose own name mentions PayPal-like text elsewhere is untouched.
    ("SPOTIFY P1A2B3C", "expense:spotify p1a2b3c"),
])
def test_descriptors_outside_paypal_key_as_before(desc, key):
    assert _key(desc) == key
