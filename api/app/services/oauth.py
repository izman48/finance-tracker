"""OAuth 2.1 authorization server for remote MCP clients.

Public clients only: registered dynamically (RFC 7591), no client secret,
PKCE S256 mandatory. The consent step runs in the web app with the user's
session, which is the moment the server holds their DEK; it's wrapped under
the authorization code, then under each refresh token in turn, so a client
that keeps refreshing keeps access without the server ever storing a key it
could use on its own.

Errors are OAuthError, carrying the RFC 6749 error code. Before the client and
redirect URI are validated an error must never redirect (that would make us an
open redirector); after, it goes back to the client via `redirect_to`.
"""
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.oauth_tokens import (
    MCP_ACCESS_TOKEN_TTL,
    SCOPE_READ,
    SUPPORTED_SCOPES,
    create_mcp_access_token,
)
from app.core.user_crypto import (
    generate_oauth_secret,
    hash_oauth_secret,
    unwrap_dek_with_secret,
    wrap_dek_with_secret,
)
from app.models import OAuthAuthorizationCode, OAuthClient, OAuthGrant, User

logger = logging.getLogger(__name__)
settings = get_settings()

CODE_TTL = timedelta(minutes=5)
# A grant nobody refreshes for this long lapses; each refresh pushes it out.
GRANT_IDLE_TTL = timedelta(days=30)

GRANT_TYPES = ("authorization_code", "refresh_token")
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_PKCE_VERIFIER = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
_PKCE_CHALLENGE = re.compile(r"^[A-Za-z0-9\-_]{43}$")  # base64url(SHA-256), unpadded


class OAuthError(Exception):
    def __init__(self, error: str, description: str, status_code: int = 400, redirect_to: str | None = None):
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code
        self.redirect_to = redirect_to


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime) -> datetime:
    # SQLite (tests) hands back naive datetimes; Postgres keeps the zone.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def metadata() -> dict:
    """RFC 8414 authorization server metadata."""
    issuer = settings.oauth_issuer
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",  # the web app's consent page
        "token_endpoint": f"{issuer}/api/v1/oauth/token",
        "registration_endpoint": f"{issuer}/api/v1/oauth/register",
        "scopes_supported": list(SUPPORTED_SCOPES),
        "response_types_supported": ["code"],
        "grant_types_supported": list(GRANT_TYPES),
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
    }


# --------------------------------------------------------------------------- #
# Clients
# --------------------------------------------------------------------------- #
def _is_loopback_http(parsed) -> bool:
    return parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS


def valid_redirect_uri(uri: str) -> bool:
    """https anywhere, or http on loopback only (native apps, RFC 8252)."""
    try:
        p = urlparse(uri)
    except ValueError:
        return False
    if p.fragment or not p.netloc:
        return False
    return p.scheme == "https" or _is_loopback_http(p)


def redirect_allowed(registered: list[str], requested: str) -> bool:
    """Exact match — except a loopback redirect may use any port (RFC 8252 §7.3)."""
    if requested in registered:
        return True
    try:
        req = urlparse(requested)
    except ValueError:
        return False
    if not _is_loopback_http(req):
        return False
    for uri in registered:
        reg = urlparse(uri)
        if _is_loopback_http(reg) and (reg.hostname, reg.path, reg.query) == (req.hostname, req.path, req.query):
            return True
    return False


def register_client(
    db: Session,
    redirect_uris: list[str],
    client_name: str | None,
    token_endpoint_auth_method: str,
    grant_types: list[str] | None,
    response_types: list[str] | None,
) -> OAuthClient:
    if token_endpoint_auth_method != "none":
        raise OAuthError("invalid_client_metadata", "Only public clients (PKCE, no secret) are supported")
    if grant_types and not set(grant_types) <= set(GRANT_TYPES):
        raise OAuthError("invalid_client_metadata", "Unsupported grant_types")
    if response_types and set(response_types) != {"code"}:
        raise OAuthError("invalid_client_metadata", "Only response_type 'code' is supported")
    if not redirect_uris or len(redirect_uris) > 10:
        raise OAuthError("invalid_redirect_uri", "Give between 1 and 10 redirect_uris")
    bad = [u for u in redirect_uris if not valid_redirect_uri(u)]
    if bad:
        raise OAuthError("invalid_redirect_uri", "redirect_uris must be https, or http on localhost")

    client = OAuthClient(
        client_id=secrets.token_urlsafe(24),
        client_name=(client_name or "MCP client").strip()[:100] or "MCP client",
        redirect_uris=json.dumps(redirect_uris),
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def client_redirect_uris(client: OAuthClient) -> list[str]:
    return json.loads(client.redirect_uris)


# --------------------------------------------------------------------------- #
# Authorization (consent)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AuthorizationRequest:
    client: OAuthClient
    redirect_uri: str
    state: str | None
    code_challenge: str


def _with_params(uri: str, params: dict) -> str:
    params = {k: v for k, v in params.items() if v is not None}
    return f"{uri}{'&' if '?' in uri else '?'}{urlencode(params)}"


def validate_authorization_request(db: Session, params: dict[str, str | None]) -> AuthorizationRequest:
    client = db.get(OAuthClient, params.get("client_id") or "")
    if client is None:
        raise OAuthError("invalid_request", "Unknown client")
    redirect_uri = params.get("redirect_uri") or ""
    if not redirect_allowed(client_redirect_uris(client), redirect_uri):
        raise OAuthError("invalid_request", "redirect_uri is not registered for this client")

    # From here on the redirect target is trusted: send errors back to it.
    state = params.get("state")

    def fail(error: str, description: str) -> OAuthError:
        return OAuthError(
            error,
            description,
            redirect_to=_with_params(redirect_uri, {"error": error, "error_description": description, "state": state}),
        )

    if params.get("response_type") != "code":
        raise fail("unsupported_response_type", "response_type must be 'code'")
    if params.get("code_challenge_method") != "S256":
        raise fail("invalid_request", "PKCE with code_challenge_method S256 is required")
    challenge = params.get("code_challenge") or ""
    if not _PKCE_CHALLENGE.match(challenge):
        raise fail("invalid_request", "Missing or malformed code_challenge")
    resource = params.get("resource")
    if resource and resource.rstrip("/") != settings.mcp_resource_url:
        raise fail("invalid_target", "Unknown resource")
    scope = params.get("scope")
    if scope and not set(scope.split()) <= set(SUPPORTED_SCOPES):
        raise fail("invalid_scope", "Unknown scope requested")
    return AuthorizationRequest(client, redirect_uri, state, challenge)


def deny(request: AuthorizationRequest) -> str:
    return _with_params(request.redirect_uri, {"error": "access_denied", "state": request.state})


def approve(db: Session, user: User, dek: bytes, request: AuthorizationRequest, scopes: list[str]) -> str:
    """Record the consent as a single-use code; return where to send the browser."""
    if SCOPE_READ not in scopes or not set(scopes) <= set(SUPPORTED_SCOPES):
        raise OAuthError("invalid_scope", f"Approved scopes must include {SCOPE_READ} and be supported")
    code = generate_oauth_secret()
    db.add(
        OAuthAuthorizationCode(
            code_hash=hash_oauth_secret(code),
            client_id=request.client.client_id,
            user_id=user.id,
            redirect_uri=request.redirect_uri,
            code_challenge=request.code_challenge,
            scopes=" ".join(s for s in SUPPORTED_SCOPES if s in scopes),
            resource=settings.mcp_resource_url,
            session_version=user.session_version,
            wrapped_dek=wrap_dek_with_secret(dek, code),
            expires_at=_now() + CODE_TTL,
        )
    )
    db.commit()
    return _with_params(request.redirect_uri, {"code": code, "state": request.state})


# --------------------------------------------------------------------------- #
# Token endpoint
# --------------------------------------------------------------------------- #
def _invalid_grant(description: str) -> OAuthError:
    return OAuthError("invalid_grant", description)


def _pkce_ok(verifier: str, challenge: str) -> bool:
    if not _PKCE_VERIFIER.match(verifier):
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(digest, challenge)


def _token_response(grant: OAuthGrant, refresh_token: str, scopes: list[str], dek: bytes) -> dict:
    return {
        "access_token": create_mcp_access_token(grant, scopes, dek),
        "token_type": "Bearer",
        "expires_in": int(MCP_ACCESS_TOKEN_TTL.total_seconds()),
        "refresh_token": refresh_token,
        "scope": " ".join(scopes),
    }


def exchange_code(
    db: Session,
    client_id: str | None,
    code: str | None,
    redirect_uri: str | None,
    code_verifier: str | None,
    resource: str | None,
) -> dict:
    if not (client_id and code and redirect_uri and code_verifier):
        raise OAuthError("invalid_request", "client_id, code, redirect_uri and code_verifier are required")

    # Row lock: a concurrent redemption waits, then finds the code gone.
    row = (
        db.query(OAuthAuthorizationCode)
        .filter(OAuthAuthorizationCode.code_hash == hash_oauth_secret(code))
        .with_for_update()
        .first()
    )
    if row is None:
        raise _invalid_grant("Unknown or already used code")
    # Burn it before checking anything, so a failed attempt can't be retried.
    db.delete(row)
    db.commit()

    if _utc(row.expires_at) <= _now():
        raise _invalid_grant("Code expired")
    if row.client_id != client_id:
        raise _invalid_grant("Code was issued to another client")
    if row.redirect_uri != redirect_uri:
        raise _invalid_grant("redirect_uri does not match the authorization request")
    if not _pkce_ok(code_verifier, row.code_challenge):
        raise _invalid_grant("PKCE verification failed")
    if resource and resource.rstrip("/") != row.resource:
        raise OAuthError("invalid_target", "Code was issued for another resource")
    user = db.get(User, row.user_id)
    if user is None or user.session_version != row.session_version:
        raise _invalid_grant("Session no longer valid")
    try:
        dek = unwrap_dek_with_secret(row.wrapped_dek, code)
    except InvalidToken:
        raise _invalid_grant("Code could not be redeemed")

    refresh_token = generate_oauth_secret()
    now = _now()
    grant = OAuthGrant(
        user_id=user.id,
        client_id=client_id,
        scopes=row.scopes,
        resource=row.resource,
        session_version=row.session_version,
        refresh_token_hash=hash_oauth_secret(refresh_token),
        wrapped_dek=wrap_dek_with_secret(dek, refresh_token),
        last_used_at=now,
        expires_at=now + GRANT_IDLE_TTL,
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)
    logger.info(f"OAuth grant {grant.id} created for user {user.id}, client {client_id}")
    return _token_response(grant, refresh_token, row.scopes.split(), dek)


def refresh(db: Session, client_id: str | None, refresh_token: str | None, scope: str | None) -> dict:
    if not (client_id and refresh_token):
        raise OAuthError("invalid_request", "client_id and refresh_token are required")

    presented = hash_oauth_secret(refresh_token)
    grant = (
        db.query(OAuthGrant).filter(OAuthGrant.refresh_token_hash == presented).with_for_update().first()
    )
    if grant is None:
        # A rotated-out token coming back means two parties hold this family:
        # assume theft and revoke it, cutting off the access tokens too.
        replayed = db.query(OAuthGrant).filter(OAuthGrant.previous_refresh_token_hash == presented).first()
        if replayed is not None and replayed.revoked_at is None:
            replayed.revoked_at = _now()
            db.commit()
            logger.warning(f"Refresh token reuse: revoked OAuth grant {replayed.id}")
        raise _invalid_grant("Unknown refresh token")

    if grant.revoked_at is not None:
        raise _invalid_grant("Grant revoked")
    if _utc(grant.expires_at) <= _now():
        raise _invalid_grant("Grant expired after inactivity; sign in again")
    if grant.client_id != client_id:
        raise _invalid_grant("Refresh token was issued to another client")
    user = db.get(User, grant.user_id)
    if user is None or user.session_version != grant.session_version:
        raise _invalid_grant("Session no longer valid; sign in again")

    granted = grant.scopes.split()
    scopes = scope.split() if scope else granted
    if not set(scopes) <= set(granted):
        raise OAuthError("invalid_scope", "Cannot widen scope on refresh")
    try:
        dek = unwrap_dek_with_secret(grant.wrapped_dek, refresh_token)
    except InvalidToken:
        raise _invalid_grant("Refresh token could not be redeemed")

    new_token = generate_oauth_secret()
    now = _now()
    grant.previous_refresh_token_hash = presented
    grant.refresh_token_hash = hash_oauth_secret(new_token)
    grant.wrapped_dek = wrap_dek_with_secret(dek, new_token)
    grant.last_used_at = now
    grant.expires_at = now + GRANT_IDLE_TTL
    db.commit()
    return _token_response(grant, new_token, [s for s in granted if s in scopes], dek)
