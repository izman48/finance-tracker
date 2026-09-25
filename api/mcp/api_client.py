"""A small async client for the REST API, with pluggable credentials.

The tools don't know or care how they're authenticated:
  PasswordCredentials      — stdio/local: log in with the account password,
                             re-login once when the session expires.
  RequestBearerCredentials — http/remote: forward the token of the MCP request
                             being served. No fallback, no retry: a caller
                             without a valid token gets nothing.
"""
import httpx
from mcp.server.auth.middleware.auth_context import get_access_token


class NotAuthenticatedError(RuntimeError):
    """No authenticated caller in context — refuse rather than guess."""


class InsufficientScopeError(PermissionError):
    pass


class PasswordCredentials:
    retry_on_401 = True

    def __init__(self, api_url: str, email: str, password: str):
        self._login_url = f"{api_url}/auth/login"
        self._email = email
        self._password = password
        self._token: str | None = None

    async def token(self, http: httpx.AsyncClient) -> str:
        if self._token is None:
            await self.refresh(http)
        return self._token

    async def refresh(self, http: httpx.AsyncClient) -> None:
        r = await http.post(self._login_url, data={"username": self._email, "password": self._password})
        r.raise_for_status()
        self._token = r.json()["access_token"]

    def require_scope(self, scope: str) -> None:
        """The account owner, logged in with their password, holds every scope."""


class RequestBearerCredentials:
    retry_on_401 = False

    async def token(self, http: httpx.AsyncClient) -> str:
        return self._caller().token

    async def refresh(self, http: httpx.AsyncClient) -> None:  # pragma: no cover - never retried
        raise NotAuthenticatedError("remote tokens are refreshed by the client, not here")

    def require_scope(self, scope: str) -> None:
        if scope not in self._caller().scopes:
            raise InsufficientScopeError(f"This connection wasn't granted '{scope}'. Reconnect and approve it.")

    @staticmethod
    def _caller():
        access = get_access_token()
        if access is None:
            raise NotAuthenticatedError("no authenticated MCP request in context")
        return access


class ApiClient:
    def __init__(self, api_url: str, credentials, transport: httpx.AsyncBaseTransport | None = None):
        self._api = api_url
        self.credentials = credentials
        self._transport = transport

    async def get(self, path: str, params: dict | None = None):
        return await self._request("GET", path, params=params)

    async def post(self, path: str, payload: dict):
        return await self._request("POST", path, json=payload)

    async def _request(self, method: str, path: str, **kwargs):
        async with httpx.AsyncClient(transport=self._transport, timeout=60) as http:
            token = await self.credentials.token(http)
            r = await http.request(method, f"{self._api}{path}", headers=_bearer(token), **kwargs)
            if r.status_code == 401 and self.credentials.retry_on_401:
                await self.credentials.refresh(http)
                token = await self.credentials.token(http)
                r = await http.request(method, f"{self._api}{path}", headers=_bearer(token), **kwargs)
            r.raise_for_status()
            return r.json()


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
