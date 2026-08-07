from functools import lru_cache

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EXTRACTION_GATEWAY_",
        case_sensitive=False,
        extra="ignore",
    )

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    openai_base_url: AnyHttpUrl = "https://api.openai.com/v1"
    request_timeout_seconds: float = 120
    inbound_api_key: str | None = Field(
        default=None,
        description="Bearer token shared with EVIDENCE_EXTRACTION_API_KEY.",
    )

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.inbound_api_key is not None and len(self.inbound_api_key) < 16:
            raise ValueError("inbound_api_key must contain at least 16 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
