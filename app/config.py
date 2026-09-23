"""Application config from environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Required: fail fast at startup when unset instead of serving a default key.
    API_KEY: str
    REDIS_URL: str = "redis://localhost:6379/0"
    # Whisper model: size name (e.g. "base", "small") or path to local dir (e.g. "whisper-model", "./whisper-model")
    WHISPER_MODEL: str = "base"
    # Cache dir when using a size name; ignored when WHISPER_MODEL is a local path
    WHISPER_DOWNLOAD_ROOT: str | None = None
    # CTranslate2 compute type: "int8", "float16", "float32", or "auto" (default)
    WHISPER_COMPUTE_TYPE: str = "auto"
    # Skip non-speech segments in Whisper (reduces hallucinations on silence/music)
    WHISPER_VAD_FILTER: bool = True
    # Batched inference: faster on CPU but uses more peak memory
    WHISPER_BATCHED: bool = False
    # Subtitle languages for yt-dlp --sub-langs (regex, comma-separated; "all" for any)
    SUBTITLE_LANGS: str = "en"
    # Skip the pipeline for videos already saved in the transcript store (any age);
    # set False to always re-run and refresh the stored transcript.
    TRANSCRIPT_DEDUP: bool = True
    # SQLite file for durable transcript storage
    TRANSCRIPT_DB_PATH: str = "./data/transcripts.db"
    # Observability
    ENV: str | None = None
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    # Optional. Comma-separated key=value (e.g. "Authorization=Basic xxx,stream-name=default").
    OTEL_EXPORTER_OTLP_HEADERS: str | None = None


settings = Settings()
