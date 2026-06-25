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
    cors_allow_origins: str = "http://localhost:5173"
    jwt_secret_key: str = "change-me-in-prod"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 8
    dev_default_user_email: str = "dev@tradingapp.dev"
    dev_default_user_password: str = "DevPass123!"
    dev_default_user_display_name: str = "Dev User"
    dev_default_user_is_admin: bool = True

    realtime_feed_provider: str = "ibkr"
    realtime_feed_symbols: str = "AAPL,MSFT,NVDA"
    realtime_feed_timeframe: str = "1d"
    realtime_feed_timeframes: str = "1m,5m,15m,30m,1h,4h,1d,1w"
    realtime_feed_poll_seconds: int = 60
    realtime_feed_stale_after_seconds: int = 180
    realtime_feed_min_request_interval_seconds: float = 1.0
    # IBKR caps simultaneous market-data lines (operator env: "API Max tickers=100").
    # Followed symbol + each index share this budget.
    realtime_max_market_data_lines: int = 100
    ibkr_gateway_host: str = "127.0.0.1"
    ibkr_gateway_port: int = 4002
    ibkr_client_id: int = 7
    # IBKR market-data type for live streaming: 1=live, 2=frozen, 3=delayed,
    # 4=delayed-frozen. Paper accounts without live data subscriptions should use
    # 3 so reqMktData returns delayed ticks instead of nothing.
    ibkr_market_data_type: int = 3

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def realtime_feed_symbol_list(self) -> list[str]:
        return [
            symbol.strip().upper()
            for symbol in self.realtime_feed_symbols.split(",")
            if symbol.strip()
        ]

    @property
    def realtime_feed_timeframe_list(self) -> list[str]:
        raw = self.realtime_feed_timeframes or self.realtime_feed_timeframe
        return [tf.strip() for tf in raw.split(",") if tf.strip()]

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url.startswith("postgres://"):
            return self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        if self.database_url.startswith("postgresql://") and "+psycopg" not in self.database_url:
            return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return self.database_url

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
