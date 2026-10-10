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


def has_hidden_characters(text: str) -> bool:
    return any(
        unicodedata.category(ch) in _HIDDEN_CATEGORIES or ch in _BLANK_RENDERING
        for ch in text
    )
