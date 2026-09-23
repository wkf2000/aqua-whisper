"""faster-whisper model: loaded once per worker process and reused across tasks."""

from pathlib import Path

import structlog
from faster_whisper import WhisperModel

from app.config import settings

logger = structlog.get_logger()

_model: WhisperModel | None = None


def _resolve_model(model_path_or_name: str) -> tuple[str, dict]:
    """Return (model path or size name, kwargs) for WHISPER_MODEL.

    A local directory containing model.bin is loaded with local_files_only;
    otherwise the value is treated as a Hugging Face size name.
    """
    project_root = Path(__file__).resolve().parent.parent
    resolved_path = (
        (project_root / model_path_or_name).resolve()
        if not Path(model_path_or_name).is_absolute()
        else Path(model_path_or_name)
    )
    model_kwargs: dict = {"compute_type": settings.WHISPER_COMPUTE_TYPE}
    if resolved_path.is_dir() and (resolved_path / "model.bin").exists():
        model_kwargs["local_files_only"] = True
        return str(resolved_path), model_kwargs
    if settings.WHISPER_DOWNLOAD_ROOT:
        model_kwargs["download_root"] = settings.WHISPER_DOWNLOAD_ROOT
    return model_path_or_name, model_kwargs


def get_model() -> WhisperModel:
    """Return the process-wide model, loading it on first use."""
    global _model
    if _model is None:
        model_path_or_name = settings.WHISPER_MODEL.strip()
        path, model_kwargs = _resolve_model(model_path_or_name)
        logger.info(
            "whisper.model_load",
            model=path,
            compute_type=model_kwargs.get("compute_type"),
        )
        _model = WhisperModel(path, **model_kwargs)
    return _model


def clear_model_cache() -> None:
    """Drop the cached model. Test helper: forces a fresh load on next get_model()."""
    global _model
    _model = None
