from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str

    # Security
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # TrueLayer Open Banking
    truelayer_client_id: str = ""
    truelayer_client_secret: str = ""
    truelayer_redirect_uri: str = "http://localhost:5173/callback"
    truelayer_sandbox: bool = True  # Use sandbox for development

    # Environment
    environment: str = "development"

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

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
