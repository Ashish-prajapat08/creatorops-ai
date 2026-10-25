from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")
    database_url: str = "postgresql+psycopg://creatorops:creatorops@localhost:55432/creatorops"
    redis_url: str = "redis://localhost:56379/0"
    environment: str = "development"
    frontend_url: str = "http://localhost:3000"
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    ai_provider: Literal["openai", "nvidia"] = "openai"
    nvidia_api_key: str = ""
    nvidia_model: str = "openai/gpt-oss-20b"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/integrations/gmail/callback"
    encryption_key: str = ""
    sentry_dsn: str = ""
    test_mode: bool = False
    test_auth_secret: str = ""
    email_high_confidence: float = Field(default=0.90, ge=0.5, le=1)
    email_sync_interval_seconds: int = Field(default=300, ge=30, le=86400)
    collection_due_soon_days: int = Field(default=7, ge=0, le=30)

    @property
    def ai_model(self):
        return self.nvidia_model if self.ai_provider == "nvidia" else self.openai_model

    @field_validator("database_url")
    @classmethod
    def postgres_driver(cls, value):
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @model_validator(mode="after")
    def validate_environment(self):
        if self.test_mode and (self.environment != "test" or len(self.test_auth_secret) < 32):
            raise ValueError("Test adapters require ENVIRONMENT=test and a 32-character secret")
        if self.environment == "production":
            if not self.supabase_url or not self.encryption_key:
                raise ValueError("Production requires Supabase and token encryption configuration")
            if not self.frontend_url.startswith(
                "https://"
            ) or not self.google_redirect_uri.startswith("https://"):
                raise ValueError("Production requires HTTPS")
        return self


@lru_cache
def settings():
    return Settings()
