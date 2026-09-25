"""OAuth endpoints for remote MCP clients (logic in services/oauth.py).

  GET  /.well-known/oauth-authorization-server   discovery (RFC 8414)
  POST /api/v1/oauth/register                    dynamic client registration
  GET  /api/v1/oauth/authorize/details           validate a request for the consent page
  POST /api/v1/oauth/authorize                   the user's decision (web session only)
  POST /api/v1/oauth/token                       code / refresh-token exchange
  GET  /api/v1/oauth/token-info                  what the MCP server asks about a token
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.oauth_tokens import InvalidMcpToken, resolve_mcp_access
from app.core.rate_limit import auth_rate_limiter
from app.core.security import CurrentUser, oauth2_scheme
from app.core.user_crypto import require_dek
from app.services import oauth
from app.services.oauth import OAuthError

well_known_router = APIRouter(tags=["oauth"])
router = APIRouter(prefix="/oauth", tags=["oauth"])

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def oauth_error_response(exc: OAuthError) -> JSONResponse:
    body = {"error": exc.error, "error_description": exc.description}
    if exc.redirect_to:
        body["redirect_to"] = exc.redirect_to
    return JSONResponse(status_code=exc.status_code, content=body, headers=_NO_STORE)


@well_known_router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata() -> dict:
    return oauth.metadata()


class ClientRegistration(BaseModel):
    # Clients send plenty of optional RFC 7591 metadata we don't use.
    model_config = ConfigDict(extra="ignore")

    redirect_uris: list[str] = Field(default_factory=list)
    client_name: str | None = None
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] | None = None
    response_types: list[str] | None = None


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_client(
    body: ClientRegistration,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    auth_rate_limiter.check(request, "oauth-register", limit=20, window_seconds=60 * 60)
    client = oauth.register_client(
        db,
        body.redirect_uris,
        body.client_name,
        body.token_endpoint_auth_method,
        body.grant_types,
        body.response_types,
    )
    return {
        "client_id": client.client_id,
        "client_id_issued_at": int(client.created_at.timestamp()) if client.created_at else None,
        "client_name": client.client_name,
        "redirect_uris": oauth.client_redirect_uris(client),
        "grant_types": list(oauth.GRANT_TYPES),
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


class AuthorizeParams(BaseModel):
    response_type: str | None = None
    client_id: str | None = None
    redirect_uri: str | None = None
    code_challenge: str | None = None
    code_challenge_method: str | None = None
    state: str | None = None
    scope: str | None = None
    resource: str | None = None


class AuthorizeDecision(AuthorizeParams):
    approve: bool
    scopes: list[str] = Field(default_factory=list)


@router.get("/authorize/details")
def authorize_details(
    params: Annotated[AuthorizeParams, Query()],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Check an authorization request before showing consent. Public: it
    reveals only what the client already put in the URL, plus its name."""
    req = oauth.validate_authorization_request(db, params.model_dump())
    requested = (params.scope or "").split()
    return {
        "client_name": req.client.client_name,
        "redirect_host": req.redirect_uri.split("/")[2],
        "requested_scopes": requested,
    }


@router.post("/authorize")
def authorize(
    body: AuthorizeDecision,
    current_user: CurrentUser,  # web session only: an MCP token can't mint grants
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    req = oauth.validate_authorization_request(db, body.model_dump())
    if not body.approve:
        return {"redirect_to": oauth.deny(req)}
    return {"redirect_to": oauth.approve(db, current_user, require_dek(), req, body.scopes)}


@router.post("/token")
def token(
    db: Annotated[Session, Depends(get_db)],
    grant_type: Annotated[str | None, Form()] = None,
    client_id: Annotated[str | None, Form()] = None,
    code: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    code_verifier: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
    scope: Annotated[str | None, Form()] = None,
    resource: Annotated[str | None, Form()] = None,
) -> JSONResponse:
    # No rate limit: codes and refresh tokens are 256-bit random, so guessing
    # is hopeless, and a per-IP limit behind the proxy would throttle everyone.
    if grant_type == "authorization_code":
        body = oauth.exchange_code(db, client_id, code, redirect_uri, code_verifier, resource)
    elif grant_type == "refresh_token":
        body = oauth.refresh(db, client_id, refresh_token, scope)
    else:
        raise OAuthError("unsupported_grant_type", "grant_type must be authorization_code or refresh_token")
    return JSONResponse(content=body, headers=_NO_STORE)


@router.get("/token-info")
def token_info(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Introspection for the MCP server (RFC 7662 fields). The token
    authenticates itself, so a caller only ever learns about its own token."""
    try:
        user, claims = resolve_mcp_access(db, token)
    except InvalidMcpToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"active": False},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "active": True,
        "client_id": claims.client_id,
        "scope": " ".join(claims.scopes),
        "aud": claims.resource,
        "sub": str(user.id),
        "exp": claims.expires_at,
    }
