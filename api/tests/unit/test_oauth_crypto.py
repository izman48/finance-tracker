"""DEK wrapping under an OAuth secret (authorization code / refresh token).

The server stores only a hash of each secret plus the DEK encrypted under a
key derived from it, so a database copy alone can't unlock anyone's data —
the same guarantee the password-wrapped DEK gives.
"""
import pytest
from cryptography.fernet import InvalidToken

from app.core import user_crypto


def test_round_trip():
    dek = user_crypto.generate_dek()
    secret = user_crypto.generate_oauth_secret()
    wrapped = user_crypto.wrap_dek_with_secret(dek, secret)
    assert user_crypto.unwrap_dek_with_secret(wrapped, secret) == dek


def test_wrong_secret_cannot_unwrap():
    wrapped = user_crypto.wrap_dek_with_secret(
        user_crypto.generate_dek(), user_crypto.generate_oauth_secret()
    )
    with pytest.raises(InvalidToken):
        user_crypto.unwrap_dek_with_secret(wrapped, user_crypto.generate_oauth_secret())


def test_wrapped_form_reveals_neither_dek_nor_secret():
    dek = user_crypto.generate_dek()
    secret = user_crypto.generate_oauth_secret()
    wrapped = user_crypto.wrap_dek_with_secret(dek, secret)
    assert dek.decode() not in wrapped and secret not in wrapped


def test_server_key_alone_cannot_unwrap():
    # Unlike the session `dk` claim, this is not under the server Fernet key.
    wrapped = user_crypto.wrap_dek_with_secret(
        user_crypto.generate_dek(), user_crypto.generate_oauth_secret()
    )
    with pytest.raises(InvalidToken):
        user_crypto.unwrap_session_dek(wrapped)


def test_secrets_are_unique_and_long():
    a, b = user_crypto.generate_oauth_secret(), user_crypto.generate_oauth_secret()
    assert a != b and len(a) >= 43  # >= 256 bits, urlsafe


def test_hash_is_stable_and_not_the_secret():
    s = user_crypto.generate_oauth_secret()
    assert user_crypto.hash_oauth_secret(s) == user_crypto.hash_oauth_secret(s)
    assert s not in user_crypto.hash_oauth_secret(s)
