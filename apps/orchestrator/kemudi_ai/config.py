from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything comes from the environment (infra/.env in the dev stack)."""

    model_config = SettingsConfigDict(env_prefix="KEMUDI_", extra="ignore")

    hermes_url: str = "http://localhost:8642/v1"
    hermes_api_key: str = ""
    ai_model: str = "deepseek-flash"
    ai_db_url: str = "sqlite:///data/kemudi-ai.db"
    taiga_api_url: str = "http://localhost:9100/api/v1"
    # Rough cost estimate for the audit log; 0 means "not tracked".
    token_price_idr_per_1k: float = 0.0
    llm_timeout_s: float = 180.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
