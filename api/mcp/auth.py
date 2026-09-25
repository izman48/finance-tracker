"""Bearer-token verification for the remote (http) server.

The REST API is the authorization server and the single source of truth about
a token. This server asks it — `GET /oauth/token-info` with the token itself as
the bearer, so no shared secret is needed and a caller only ever learns about
its own token — and accepts the token only if it is active AND was issued for
this resource (audience), so a token minted for anything else can't be
replayed here. Every failure, including the API being unreachable, rejects.
"""
import logging

import httpx
from mcp.server.auth.provider import AccessToken

SCOPE_READ = "finance:read"
SCOPE_RULES_WRITE = "finance:rules.write"

log = logging.getLogger(__name__)


class TokenInfoVerifier:
    def __init__(self, api_url: str, resource_url: str, transport: httpx.AsyncBaseTransport | None = None):
        self._url = f"{api_url}/oauth/token-info"
        self._resource = resource_url
        self._transport = transport

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
                r = await client.get(self._url, headers={"Authorization": f"Bearer {token}"})
            if r.status_code != 200:
                return None
            info = r.json()
        except (httpx.HTTPError, ValueError):
            log.warning("token-info unavailable; rejecting token")  # never log the token
            return None

        audience = info.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        if info.get("active") is not True or self._resource not in audiences or not info.get("client_id"):
            return None
        return AccessToken(
            token=token,
            client_id=info["client_id"],
            scopes=str(info.get("scope", "")).split(),
            expires_at=info.get("exp"),
            resource=self._resource,
            subject=info.get("sub"),
        )
