"""Application config from environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    API_KEY: str = "Your API key here"
    REDIS_URL: str = "redis://localhost:6379/0"
    # Whisper model: size name (e.g. "base", "small") or path to local dir (e.g. "whisper-model", "./whisper-model")
    WHISPER_MODEL: str = "base"
    # Cache dir when using a size name; ignored when WHISPER_MODEL is a local path
    WHISPER_DOWNLOAD_ROOT: str | None = None
    # CTranslate2 compute type: "int8", "float16", "float32", or "auto" (default)
    WHISPER_COMPUTE_TYPE: str = "auto"


settings = Settings()
