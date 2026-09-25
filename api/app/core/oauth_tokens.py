"""MCP access tokens: minting, verification, and the scope-gated API dependency.

An MCP access token is a JWT like the web session's, but deliberately narrower:
  - `typ` is `mcp_access`, so the web's get_current_user refuses it — every
    route is web-only unless it opts in through `scoped_user(...)`;
  - `aud` is the MCP server's resource URL (RFC 8707), so it can't be replayed
    at anything else;
  - it carries only the scopes the user approved, and lives an hour;
  - it names its grant (`gid`), and each use checks the grant is still live,
    so revoking the grant (or refresh-token reuse) kills it immediately.
Like the web token it carries the DEK (`dk`, server-encrypted) so the request
can decrypt the user's data.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import MCP_ACCESS_TOKEN_TYPE, get_current_user, oauth2_scheme
from app.core.user_crypto import wrap_dek_for_session
from app.models import OAuthGrant, User

settings = get_settings()

SCOPE_READ = "finance:read"
SCOPE_RULES_WRITE = "finance:rules.write"
SUPPORTED_SCOPES = (SCOPE_READ, SCOPE_RULES_WRITE)

MCP_ACCESS_TOKEN_TTL = timedelta(hours=1)


class InvalidMcpToken(Exception):
    pass


@dataclass(frozen=True)
class McpTokenClaims:
    user_id: uuid.UUID
    grant_id: uuid.UUID
    client_id: str
    scopes: tuple[str, ...]
    session_version: int
    resource: str
    expires_at: int


def create_mcp_access_token(grant: OAuthGrant, scopes: list[str], dek: bytes) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(grant.user_id),
            "typ": MCP_ACCESS_TOKEN_TYPE,
            "aud": grant.resource,
            "cid": grant.client_id,
            "gid": str(grant.id),
            "scope": " ".join(scopes),
            "sv": grant.session_version,
            "dk": wrap_dek_for_session(dek),
            "iat": now,
            "exp": now + MCP_ACCESS_TOKEN_TTL,
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def decode_mcp_access_token(token: str) -> McpTokenClaims:
    """Signature, expiry, type and audience. Raises InvalidMcpToken."""
    try:
        p = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            audience=settings.mcp_resource_url,
        )
        if p.get("typ") != MCP_ACCESS_TOKEN_TYPE:
            raise InvalidMcpToken("not an MCP access token")
        return McpTokenClaims(
            user_id=uuid.UUID(p["sub"]),
            grant_id=uuid.UUID(p["gid"]),
            client_id=p["cid"],
            scopes=tuple(str(p["scope"]).split()),
            session_version=int(p["sv"]),
            resource=p["aud"],
            expires_at=int(p["exp"]),
        )
    except (JWTError, KeyError, ValueError, TypeError) as exc:
        raise InvalidMcpToken("invalid MCP access token") from exc


def resolve_mcp_access(db: Session, token: str) -> tuple[User, McpTokenClaims]:
    """A fully checked MCP token: valid JWT AND its grant and user still honour it."""
    claims = decode_mcp_access_token(token)
    grant = db.get(OAuthGrant, claims.grant_id)
    if (
        grant is None
        or grant.revoked_at is not None
        or grant.user_id != claims.user_id
        or grant.client_id != claims.client_id
    ):
        raise InvalidMcpToken("grant revoked or unknown")
    user = db.get(User, claims.user_id)
    if user is None or user.session_version != claims.session_version:
        raise InvalidMcpToken("session invalidated")
    return user, claims


def _is_mcp_token(token: str) -> bool:
    # Only picks the verification path; both paths verify fully.
    try:
        return jwt.get_unverified_claims(token).get("typ") == MCP_ACCESS_TOKEN_TYPE
    except JWTError:
        return False


def scoped_user(scope: str) -> Callable[..., User]:
    """Dependency for the routes the MCP server calls: a web session, or an
    MCP token holding `scope`. Every other route stays web-only by default."""

    def dependency(
        token: Annotated[str, Depends(oauth2_scheme)],
        db: Annotated[Session, Depends(get_db)],
    ) -> User:
        if not _is_mcp_token(token):
            return get_current_user(token, db)
        try:
            user, claims = resolve_mcp_access(db, token)
        except InvalidMcpToken:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if scope not in claims.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This connection wasn't granted '{scope}'.",
                headers={"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{scope}"'},
            )
        return user

    return dependency


# Routes the MCP tools call opt in with one of these instead of CurrentUser.
CurrentUserOrMcpRead = Annotated[User, Depends(scoped_user(SCOPE_READ))]
CurrentUserOrMcpRulesWrite = Annotated[User, Depends(scoped_user(SCOPE_RULES_WRITE))]
