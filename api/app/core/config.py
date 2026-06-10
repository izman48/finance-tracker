from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder fragments that must never be used as a real signing key in
# live mode. Matched case-insensitively as substrings.
_WEAK_SECRET_MARKERS = ("your-secret", "change", "secret-key", "changeme", "placeholder")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str

    # Security
    secret_key: str
    # Fernet key (urlsafe base64, 32 bytes) for encrypting bank tokens at rest.
    encryption_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # TrueLayer Open Banking
    truelayer_client_id: str = ""
    truelayer_client_secret: str = ""
    truelayer_redirect_uri: str = "http://localhost:5173/callback"
    truelayer_sandbox: bool = True  # Use sandbox for development

    # Environment
    environment: str = "development"

    # Where to send users after the OAuth callback (the UI's public URL).
    frontend_url: str = "http://localhost:5173"

    @property
    def truelayer_auth_url(self) -> str:
        base = (
            "https://auth.truelayer-sandbox.com"
            if self.truelayer_sandbox
            else "https://auth.truelayer.com"
        )
        return base

    @property
    def truelayer_api_url(self) -> str:
        base = (
            "https://api.truelayer-sandbox.com"
            if self.truelayer_sandbox
            else "https://api.truelayer.com"
        )
        return base

    @property
    def is_live_mode(self) -> bool:
        """True when the app handles real banking data.

        Triggered by live TrueLayer (sandbox off) or an explicit production
        deployment. Sandbox-based development/test runs are exempt.
        """
        return (not self.truelayer_sandbox) or self.environment == "production"

    @model_validator(mode="after")
    def _validate_secrets_for_live_mode(self) -> "Settings":
        """Refuse to start in live mode with a weak/placeholder signing key.

        A guessable SECRET_KEY lets anyone forge JWTs for any user, so we fail
        fast rather than boot an insecure server against real bank data.
        """
        if self.is_live_mode:
            key = (self.secret_key or "").lower()
            if len(self.secret_key) < 32 or any(m in key for m in _WEAK_SECRET_MARKERS):
                raise ValueError(
                    "SECRET_KEY is missing, too short, or a known placeholder. "
                    "Generate a strong key (`openssl rand -hex 32`) before running "
                    "in live mode (TRUELAYER_SANDBOX=false or ENVIRONMENT=production)."
                )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
