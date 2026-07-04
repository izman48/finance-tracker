from datetime import datetime, timedelta, timezone
from typing import Annotated
import secrets
import uuid

from cryptography.fernet import InvalidToken
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.user_crypto import current_dek, unwrap_session_dek, wrap_dek_for_session
from app.models import User
from app.schemas import TokenData

settings = get_settings()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate password hash."""
    return pwd_context.hash(password)


# Token type claim ("typ"). Every JWT carries one so a token minted for one
# purpose can't be replayed for another (e.g. a password-reset or OAuth-state
# token presented as an API bearer token). Each verifier checks its own type.
ACCESS_TOKEN_TYPE = "access"


def create_access_token(
    data: dict, expires_delta: timedelta | None = None, dek: bytes | None = None
) -> str:
    """Create a JWT access token.

    When `dek` is given, it rides along as the `dk` claim, encrypted under the
    server key — how the session carries the user's data-encryption key
    without the server persisting it (see core/user_crypto.py).
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "typ": ACCESS_TOKEN_TYPE})
    if dek is not None:
        to_encode["dk"] = wrap_dek_for_session(dek)
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> TokenData:
    """Decode and validate a JWT access token.

    Rejects any token whose `typ` is not the access type, so reset and
    OAuth-state tokens (same signing key, same `sub`) cannot be used as bearer
    credentials.
    """
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        user_id: str = payload.get("sub")
        if user_id is None or payload.get("typ") != ACCESS_TOKEN_TYPE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return TokenData(user_id=uuid.UUID(user_id))
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def set_session_dek(request: Request) -> None:
    """App-wide dependency: stash the session DEK in the request context.

    Reads the bearer token (if any) and, when it carries a valid `dk` claim,
    unwraps the user's data-encryption key into the `current_dek` contextvar
    for the encrypted column types to use. Never rejects a request itself —
    endpoints that touch encrypted columns without a DEK fail closed via
    DEKUnavailableError (mapped to 401).

    Must stay async: it runs in the request's task context, so the contextvar
    propagates into sync endpoints' threadpool. A sync dependency's context is
    a throwaway copy and the value would be lost.
    """
    # Fail closed: start every request keyless so nothing inherited from the
    # surrounding context can decrypt data the current token isn't entitled to.
    current_dek.set(None)
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return
    try:
        payload = jwt.decode(
            auth[7:], settings.secret_key, algorithms=[settings.algorithm]
        )
        wrapped = payload.get("dk")
        if payload.get("typ") == ACCESS_TOKEN_TYPE and wrapped:
            current_dek.set(unwrap_session_dek(wrapped))
    except (JWTError, InvalidToken):
        pass  # bad/expired token: auth itself will reject where it matters


# How long an OAuth `state` token stays valid (bank authorization is quick).
OAUTH_STATE_EXPIRE_MINUTES = 10


def create_oauth_state(user_id: str, dek: bytes | None = None) -> str:
    """Create a signed, short-lived OAuth `state` token.

    Replaces passing the raw user_id as state. The token binds the flow to a
    user, carries a random nonce, and expires quickly, so a third party cannot
    forge a callback (CSRF) or read the user_id from the URL. It also carries
    the session DEK (server-encrypted, like the access token's `dk` claim)
    because the TrueLayer callback arrives with no bearer token but must
    encrypt the new bank tokens and synced data.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=OAUTH_STATE_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "nonce": secrets.token_urlsafe(16),
        "typ": "oauth_state",
        "exp": expire,
    }
    if dek is not None:
        payload["dk"] = wrap_dek_for_session(dek)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def verify_oauth_state(state: str) -> tuple[str, bytes | None]:
    """Validate an OAuth `state` token; return (user_id, session DEK or None).

    Raises ValueError if the token is missing, expired, tampered with, or not an
    oauth_state token.
    """
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise ValueError("Invalid or expired OAuth state") from exc

    if payload.get("typ") != "oauth_state":
        raise ValueError("Wrong token type for OAuth state")
    user_id = payload.get("sub")
    if not user_id:
        raise ValueError("OAuth state missing subject")
    dek: bytes | None = None
    if payload.get("dk"):
        try:
            dek = unwrap_session_dek(payload["dk"])
        except InvalidToken as exc:
            raise ValueError("OAuth state carries an unreadable session key") from exc
    return user_id, dek


# Password reset links are emailed, so keep their lifetime short.
RESET_TOKEN_EXPIRE_MINUTES = 30


def _password_fingerprint(hashed_password: str) -> str:
    """Short stable digest of the current password hash.

    Embedding it in reset tokens makes them effectively single-use: once the
    password changes, every previously issued token stops validating.
    """
    import hashlib

    return hashlib.sha256(hashed_password.encode()).hexdigest()[:16]


def create_password_reset_token(user: User) -> str:
    """Create a signed, short-lived, single-use password reset token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user.id),
        "typ": "pwd_reset",
        "fp": _password_fingerprint(user.hashed_password),
        "nonce": secrets.token_urlsafe(8),
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def verify_password_reset_token(token: str, db: Session) -> User:
    """Validate a reset token and return its user.

    Raises ValueError if expired, tampered with, the wrong type, or already
    consumed (password changed since issuance).
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise ValueError("Invalid or expired reset link") from exc

    if payload.get("typ") != "pwd_reset":
        raise ValueError("Wrong token type")
    user = db.query(User).filter(User.id == uuid.UUID(payload.get("sub", ""))).first()
    if not user:
        raise ValueError("User not found")
    if payload.get("fp") != _password_fingerprint(user.hashed_password):
        raise ValueError("Reset link already used")
    return user


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Dependency to get the current authenticated user."""
    token_data = decode_access_token(token)
    user = db.query(User).filter(User.id == token_data.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# Type alias for dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
