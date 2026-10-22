"""Application config from environment."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    # Subtitle languages for yt-dlp --sub-langs (regex, comma-separated; "all" for any).
    # Order is preference: manual subtitles are picked by the first matching pattern.
    # Auto captions are always fetched in the video's original language first.
    SUBTITLE_LANGS: str = "zh.*,en"
    # Skip the pipeline for videos already saved in the transcript store (any age);
    # set False to always re-run and refresh the stored transcript.
    TRANSCRIPT_DEDUP: bool = True
    # SQLite file for durable transcript storage
    TRANSCRIPT_DB_PATH: str = "./data/transcripts.db"
    # Directory for downloaded video files (in Docker: set it under the /data bind mount)
    DOWNLOAD_DIR: str = "./data/downloads"
    # yt-dlp timeout for one video download in seconds
    DOWNLOAD_TIMEOUT: int = Field(default=1800, gt=0)
    # Downloaded files older than this are deleted when a new download starts
    # (hours; 0 keeps files forever)
    DOWNLOAD_TTL_HOURS: float = Field(default=72.0, ge=0)
    # Preferred maximum video height in pixels; yt-dlp falls back to the best
    # format at or below it, then to any format when none exists
    DOWNLOAD_MAX_HEIGHT: int = Field(default=720, gt=0)
    # OpenAI-compatible chat completions; optional for transcript-only requests.
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)
    # Observability
    ENV: str | None = None
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    # Optional. Comma-separated key=value (e.g. "Authorization=Basic xxx,stream-name=default").
    OTEL_EXPORTER_OTLP_HEADERS: str | None = None


settings = Settings()
