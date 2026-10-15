"""Characters that change how text looks without being visible.

Names chosen by third parties (an OAuth client's `client_name`, chosen by
whoever registered the client) are shown to the user, where bidi overrides,
zero-width characters, controls and blank-rendering letters can make one
name pass for another ("Claude Desktop" plus a hidden suffix).
"""
import unicodedata

# Control, format (bidi controls, zero-width, BOM), surrogate, private use,
# unassigned, and line/paragraph separators.
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
# Letters and marks that render blank but aren't in those categories.
_BLANK_RENDERING = frozenset("\u034f\u115f\u1160\u17b4\u17b5\u3164\uffa0")


def _is_hidden(ch: str) -> bool:
    return unicodedata.category(ch) in _HIDDEN_CATEGORIES or ch in _BLANK_RENDERING


def has_hidden_characters(text: str) -> bool:
    return any(_is_hidden(ch) for ch in text)


def without_hidden_characters(text: str) -> str:
    """For names stored before registration refused them."""
    return "".join(ch for ch in text if not _is_hidden(ch))


def visible_text(text: str) -> str:
    """A pydantic validator: text a person can see, nothing hidden (T-12-12).
    Names the user types become labels Claude reads (a lender's repayment, a
    holding's contribution, a card plan's instalment), so they follow the
    same rule as commitment labels."""
    if not text.strip() or has_hidden_characters(text):
        raise ValueError("must be visible text without control or hidden characters")
    return text
