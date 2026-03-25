from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str = "sqlite:///./alpha_miner.db"
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-6"
    LLM_MAX_CALLS_PER_DAY: int = 20
    DIVERSITY_THRESHOLD: float = 0.7
    PROXY_DATA_TICKERS: int = 500
    GP_POPULATION_SIZE: int = 500
    GP_GENERATIONS: int = 20
    WQ_MODE: str = "manual"
    WQ_REQUEST_INTERVAL_SEC: float = 3.0
    WQ_EMAIL: str = ""
    WQ_PASSWORD: str = ""
    WQ_POLL_INTERVAL_SEC: float = 5.0
    WQ_POLL_TIMEOUT_SEC: float = 300.0
    CORS_ORIGINS: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
