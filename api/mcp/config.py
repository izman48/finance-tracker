"""Server settings, read once from the environment.

Two transports:
  stdio  (default) — a local client spawns this process; it logs in to the API
                     with the account's email and password.
  http             — the deployed, remote server. Every request carries the
                     caller's own OAuth bearer token; no password is held here.
"""
from dataclasses import dataclass
from typing import Literal, Mapping
from urllib.parse import urlparse

DEFAULT_API_URL = "http://localhost:8000/api/v1"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ConfigError(ValueError):
    """The environment doesn't describe a runnable server."""


@dataclass(frozen=True)
class Settings:
    transport: Literal["stdio", "http"]
    api_url: str
    email: str = ""
    password: str = ""
    public_url: str = ""
    host: str = "0.0.0.0"
    port: int = 8001

    @property
    def resource_url(self) -> str:
        """This server's OAuth resource identifier (RFC 8707/9728)."""
        return f"{self.public_url}/mcp"

    @property
    def public_host(self) -> str:
        """The Host header clients reach us by (DNS-rebinding allowlist)."""
        return urlparse(self.public_url).netloc

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        transport = env.get("MCP_TRANSPORT", "stdio")
        api_url = env.get("FINANCE_API_URL", DEFAULT_API_URL).rstrip("/")

        if transport == "stdio":
            email, password = env.get("FINANCE_EMAIL", ""), env.get("FINANCE_PASSWORD", "")
            if not email or not password:
                raise ConfigError("stdio mode needs FINANCE_EMAIL and FINANCE_PASSWORD")
            return cls("stdio", api_url, email=email, password=password)

        if transport == "http":
            public_url = env.get("MCP_PUBLIC_URL", "").rstrip("/")
            if not public_url:
                raise ConfigError("http mode needs MCP_PUBLIC_URL (e.g. https://your.domain)")
            parsed = urlparse(public_url)
            if parsed.scheme != "https" and parsed.hostname not in _LOCAL_HOSTS:
                raise ConfigError("MCP_PUBLIC_URL must be https outside localhost")
            return cls(
                "http",
                api_url,
                public_url=public_url,
                host=env.get("MCP_HOST", "0.0.0.0"),
                port=int(env.get("MCP_PORT", "8001")),
            )

        raise ConfigError(f"MCP_TRANSPORT must be 'stdio' or 'http', not {transport!r}")
