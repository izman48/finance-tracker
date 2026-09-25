import pytest

from config import ConfigError, Settings


def test_defaults_to_stdio_with_password_login():
    s = Settings.from_env({"FINANCE_EMAIL": "a@b.c", "FINANCE_PASSWORD": "pw"})
    assert s.transport == "stdio"
    assert s.api_url == "http://localhost:8000/api/v1"


def test_stdio_requires_credentials():
    with pytest.raises(ConfigError, match="FINANCE_EMAIL"):
        Settings.from_env({})


def test_api_url_trailing_slash_is_stripped():
    s = Settings.from_env(
        {"FINANCE_EMAIL": "a", "FINANCE_PASSWORD": "b", "FINANCE_API_URL": "http://x/api/v1/"}
    )
    assert s.api_url == "http://x/api/v1"


def test_http_requires_public_url():
    with pytest.raises(ConfigError, match="MCP_PUBLIC_URL"):
        Settings.from_env({"MCP_TRANSPORT": "http"})


def test_http_does_not_need_a_password():
    s = Settings.from_env({"MCP_TRANSPORT": "http", "MCP_PUBLIC_URL": "https://example.com"})
    assert s.transport == "http"
    assert s.resource_url == "https://example.com/mcp"
    assert s.public_host == "example.com"


def test_http_rejects_plain_http_public_url():
    # Bearer tokens carry the user's session key — never over cleartext.
    with pytest.raises(ConfigError, match="https"):
        Settings.from_env({"MCP_TRANSPORT": "http", "MCP_PUBLIC_URL": "http://example.com"})


def test_http_allows_plain_http_for_localhost():
    s = Settings.from_env({"MCP_TRANSPORT": "http", "MCP_PUBLIC_URL": "http://localhost:8001/"})
    assert s.resource_url == "http://localhost:8001/mcp"
    assert s.public_host == "localhost:8001"


def test_unknown_transport_is_rejected():
    with pytest.raises(ConfigError, match="MCP_TRANSPORT"):
        Settings.from_env({"MCP_TRANSPORT": "sse"})
