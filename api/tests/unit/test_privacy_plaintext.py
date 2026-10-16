"""The privacy page's list of unencrypted fields can't drift from the models
(T-12-13; sec: "checked by a test against the models' non-encrypted
columns"). Every column that is not DEK- or server-encrypted, other than
primary keys and foreign keys, must be in exactly one group of
`app.core.privacy_plaintext.PLAINTEXT`, and every group has a phrase that
the privacy page shows (checked from the repo root by
.github/scripts/check_privacy_copy.py)."""
import app.models  # noqa: F401 (registers every table)
from app.core.database import Base
from app.core.encryption import EncryptedString, UserEncryptedDecimal, UserEncryptedString, UserEncryptedToken
from app.core.privacy_plaintext import PLAINTEXT, PRIVACY_PHRASES

ENCRYPTED = (EncryptedString, UserEncryptedString, UserEncryptedDecimal, UserEncryptedToken)


def _plaintext_columns() -> set[str]:
    return {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if not isinstance(column.type, ENCRYPTED) and not column.primary_key and not column.foreign_keys
    }


def _listed() -> list[str]:
    return [f"{table}.{column}" for tables in PLAINTEXT.values() for table, columns in tables.items() for column in columns]


def test_every_plaintext_column_is_listed_once():
    listed = _listed()
    assert sorted(set(listed)) == sorted(listed), "a column is in two groups"
    actual = _plaintext_columns()
    assert set(listed) - actual == set(), "listed but encrypted or gone"
    assert actual - set(listed) == set(), "a new plaintext column: add it to app/core/privacy_plaintext.py and the privacy page"


def test_every_group_has_a_phrase():
    assert set(PLAINTEXT) == set(PRIVACY_PHRASES)
