"""Application config from environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    API_KEY: str = "Your API key here"
    REDIS_URL: str = "redis://localhost:6379/0"


settings = Settings()
