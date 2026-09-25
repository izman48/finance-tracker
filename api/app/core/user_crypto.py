"""Per-user envelope encryption so the operator cannot read user data at rest.

Each user has a random data-encryption key (DEK). Sensitive rows (transaction
text/amounts, account details, TrueLayer tokens) are encrypted with the DEK.
The DEK is never stored raw — only wrapped by:

  1. a key-encryption key (KEK) derived from the user's password (Argon2id), and
  2. a KEK derived from a one-time recovery code shown at signup.

The server can therefore only unwrap the DEK while it holds the password
(login) or a session token carrying the DEK. During a session the DEK travels
inside the JWT, encrypted under the server's Fernet key (`dk` claim), and is
placed in a request-scoped contextvar that the encrypted column types read.

Losing both the password and the recovery code loses the data — by design.
"""
import base64
import hashlib
import secrets
from contextvars import ContextVar

from argon2.low_level import Type, hash_secret_raw
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.encryption import _get_fernet

# Argon2id parameters (KEK derivation). Logins pay this cost once; the values
# follow the OWASP "second recommended" profile (64 MiB, 3 iterations).
_ARGON2_TIME_COST = 3
_ARGON2_MEMORY_COST = 64 * 1024  # KiB
_ARGON2_PARALLELISM = 1
_KEY_LEN = 32

# The current request's unwrapped DEK. Set by the auth dependency (from the
# JWT `dk` claim) or the OAuth callback (from the state token); read by the
# UserEncrypted* column types.
current_dek: ContextVar[bytes | None] = ContextVar("current_dek", default=None)


class DEKUnavailableError(Exception):
    """No DEK in the request context — the caller must (re-)authenticate."""


def require_dek() -> bytes:
    dek = current_dek.get()
    if dek is None:
        raise DEKUnavailableError(
            "Encryption key unavailable for this session. Please log in again."
        )
    return dek


def generate_dek() -> bytes:
    """A fresh per-user data-encryption key (a Fernet key)."""
    return Fernet.generate_key()


def generate_salt() -> str:
    """A random KDF salt, base64-encoded for storage."""
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode()


def _derive_kek(secret: str, salt: str) -> Fernet:
    """Argon2id-derive a Fernet KEK from a password or recovery code."""
    raw = hash_secret_raw(
        secret=secret.encode(),
        salt=base64.urlsafe_b64decode(salt.encode()),
        time_cost=_ARGON2_TIME_COST,
        memory_cost=_ARGON2_MEMORY_COST,
        parallelism=_ARGON2_PARALLELISM,
        hash_len=_KEY_LEN,
        type=Type.ID,
    )
    return Fernet(base64.urlsafe_b64encode(raw))


def wrap_dek(dek: bytes, secret: str, salt: str) -> str:
    """Encrypt the DEK under a KEK derived from `secret`."""
    return _derive_kek(secret, salt).encrypt(dek).decode()


def unwrap_dek(wrapped: str, secret: str, salt: str) -> bytes:
    """Decrypt a wrapped DEK. Raises InvalidToken on a wrong secret/salt."""
    return _derive_kek(secret, salt).decrypt(wrapped.encode())


# Recovery codes: 8 groups of 4 base32 chars (160 bits of entropy).
_RECOVERY_GROUPS = 8
_RECOVERY_GROUP_LEN = 4


def generate_recovery_code() -> str:
    chars = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    groups = [
        chars[i : i + _RECOVERY_GROUP_LEN]
        for i in range(0, _RECOVERY_GROUPS * _RECOVERY_GROUP_LEN, _RECOVERY_GROUP_LEN)
    ]
    return "-".join(groups)


def normalize_recovery_code(code: str) -> str:
    """Canonical form for wrapping/unwrapping: uppercase, separators stripped."""
    return "".join(code.split()).replace("-", "").upper()


def wrap_dek_for_session(dek: bytes) -> str:
    """Encrypt the DEK under the server key for transport inside a JWT claim.

    The claim keeps the server stateless between requests without ever putting
    the raw DEK on the wire or in the database.
    """
    return _get_fernet().encrypt(dek).decode()


def unwrap_session_dek(token: str) -> bytes:
    """Recover the DEK from a JWT `dk` claim. Raises InvalidToken if invalid."""
    return _get_fernet().decrypt(token.encode())


# --------------------------------------------------------------------------- #
# OAuth secrets (MCP authorization codes and refresh tokens)
# --------------------------------------------------------------------------- #
# A remote MCP client needs the DEK long after the user's web session ends, so
# the DEK is wrapped under the OAuth secret the client holds. The server keeps
# only a hash of the secret (for lookup) and this wrapped copy — like the
# password-wrapped DEK, a copy of the database alone unlocks nothing. The
# secrets are 256-bit random, so a fast KDF (HKDF) is enough; Argon2 is for
# low-entropy passwords.
_OAUTH_SECRET_BYTES = 32
_OAUTH_KEK_INFO = b"nilu oauth-secret kek v1"


def generate_oauth_secret() -> str:
    return secrets.token_urlsafe(_OAUTH_SECRET_BYTES)


def hash_oauth_secret(secret: str) -> str:
    """Lookup key for a stored secret. Unsalted is fine: the input is random."""
    return hashlib.sha256(secret.encode()).hexdigest()


def _oauth_kek(secret: str) -> Fernet:
    raw = HKDF(algorithm=hashes.SHA256(), length=_KEY_LEN, salt=None, info=_OAUTH_KEK_INFO).derive(
        secret.encode()
    )
    return Fernet(base64.urlsafe_b64encode(raw))


def wrap_dek_with_secret(dek: bytes, secret: str) -> str:
    return _oauth_kek(secret).encrypt(dek).decode()


def unwrap_dek_with_secret(wrapped: str, secret: str) -> bytes:
    """Raises InvalidToken if `secret` isn't the one the DEK was wrapped under."""
    return _oauth_kek(secret).decrypt(wrapped.encode())
