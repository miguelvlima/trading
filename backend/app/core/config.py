from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Trading App Backend"
    env: str = "dev"
    mode: str = "PAPER"
    database_url: str = Field(
        default="postgresql+psycopg://trading:trading@localhost:5432/trading"
    )
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
