"""PayPal descriptors with changing reference codes (T-10-9).

Two real shapes (structure from the owner's data, values invented):

- Card account: "PAYPAL *SPOTIFY*P12A3B4 01234567890". The 7-character
  reference glued on with "*" changes every month; the trailing number is
  constant (and shared by every PayPal merchant on that account). The
  reference has fewer than six digits, so the general normaliser keeps it (it
  can't tell it from "MONZO123"), and every month gets its own key. Inside a
  PayPal descriptor, digit-bearing tokens are dropped.
- Current account: "PAYPAL *NETFLIX ON 30 SEP BCC". The bank's "ON dd MON"
  date phrase changes every month. It is dropped from every descriptor: it is
  a date, never part of a name.

Over-merging hides money (sec): different merchants paid through PayPal keep
separate keys, and a PayPal descriptor with no merchant name left (a bare
"PAYPAL" plus a reference, or only filler words) keys exactly as before, so it
never collapses into one shared "paypal" key. Descriptors are invented, with
the same structure as real ones.
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


def test_a_space_separated_reference_and_the_pp_prefix_key_the_same_way():
    assert _key("PAYPAL *SPOTIFY P1A2B3C") == _key("PP*SPOTIFY K9Z8Y7X") == "expense:paypal spotify"


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
    # The existing cases (#63, #68) give the same keys as before.
    ("O2 UK", "expense:o2 uk"),
    ("MONZO123", "expense:monzo123"),
    ("RENT 1606LANDMARKE FT", "expense:rent 1606landmarke ft"),
    ("EE LIMITED Q42181371737681503 DDR", "expense:ee limited ddr"),
    ("COMMUNITYFIBRE LTD A1539913 DDR", "expense:communityfibre ltd ddr"),
    # "PP" only marks PayPal as the "PP*" prefix, not as a word.
    ("PP UTILITIES 12AB", "expense:pp utilities 12ab"),
    # A merchant whose own name mentions PayPal-like text elsewhere is untouched.
    ("SPOTIFY P1A2B3C", "expense:spotify p1a2b3c"),
])
def test_descriptors_outside_paypal_key_as_before(desc, key):
    assert _key(desc) == key
