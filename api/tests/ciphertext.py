"""Proof that a stored column is ciphertext of a known value (T-12-13).

Searching the raw column for the plaintext is flaky: Fernet tokens are
random base64, so a short needle ("150"), or any needle once the token is
upper-cased ("WOS"), turns up by chance now and then. Instead, decrypt the
stored value with the user's key and check it holds the plaintext, and that
the stored value is a Fernet token (not the plaintext). This is a stronger
check, not a weaker one: it proves the column is encrypted under that key.
"""
from cryptography.fernet import Fernet


def assert_ciphertext_of(stored, dek: bytes, plaintext: str) -> None:
    raw = str(stored)
    assert raw.startswith("gAAAAA"), "not a Fernet token"
    assert raw != plaintext
    assert plaintext in Fernet(dek).decrypt(raw.encode()).decode()
