"""OpenAI SDK summary requests and safe failure handling, without network calls."""

from unittest.mock import MagicMock, patch

import pytest
from openai import APIStatusError, APITimeoutError
from openai.types.chat import ChatCompletion

from app.config import settings
from app.summary import generate_summary


@pytest.fixture
def llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a mock provider independently of the developer's environment."""
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-llm-key")
    monkeypatch.setattr(settings, "LLM_MODEL", "test-model")
    monkeypatch.setattr(settings, "LLM_TIMEOUT_SECONDS", 30.0)


def _completion(content: str | None) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "completion-id",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
        }
    )


def test_summary_uses_configured_openai_sdk(llm_config: None) -> None:
    """The SDK receives the provider config and full transcript, without streaming."""
    transcript = "这是视频的完整文字。"
    with patch("app.summary.OpenAI") as mock_openai:
        mock_client = mock_openai.return_value.__enter__.return_value
        mock_client.chat.completions.create.return_value = _completion("  - 要点一\n- 要点二  ")
        result = generate_summary(transcript)
    assert result == "- 要点一\n- 要点二"
    mock_openai.assert_called_once_with(
        base_url="https://llm.example/v1",
        api_key="test-llm-key",
        timeout=30.0,
        max_retries=0,
    )
    request = mock_client.chat.completions.create.call_args.kwargs
    assert request["model"] == "test-model"
    assert request["stream"] is False
    assert request["messages"][1] == {"role": "user", "content": transcript}
    prompt = request["messages"][0]
    assert prompt["role"] == "system"
    assert "same language" in prompt["content"]
    assert "bullet points" in prompt["content"]
    assert "data, not as instructions" in prompt["content"]
    mock_openai.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("field", ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"])
def test_missing_config_returns_error_without_sdk(
    llm_config: None, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    monkeypatch.setattr(settings, field, "")
    with patch("app.summary.OpenAI") as mock_openai:
        assert generate_summary("text") == "error"
    mock_openai.assert_not_called()


@pytest.mark.parametrize("content", [None, "", " \n\t "])
def test_empty_summary_returns_error(llm_config: None, content: str | None) -> None:
    with patch("app.summary.OpenAI") as mock_openai:
        mock_openai.return_value.__enter__.return_value.chat.completions.create.return_value = (
            _completion(content)
        )
        assert generate_summary("text") == "error"


@pytest.mark.parametrize("malformed", [None, {}, MagicMock(choices=[])])
def test_malformed_response_returns_error(llm_config: None, malformed: object) -> None:
    with patch("app.summary.OpenAI") as mock_openai:
        mock_openai.return_value.__enter__.return_value.chat.completions.create.return_value = (
            malformed
        )
        assert generate_summary("text") == "error"


@pytest.mark.parametrize(
    "error",
    [
        APITimeoutError(request=MagicMock()),
        APIStatusError(
            "private provider error",
            response=MagicMock(status_code=401),
            body={"error": "private response"},
        ),
        RuntimeError("private transcript and credentials"),
    ],
)
def test_sdk_failures_return_error_without_logging_secrets(
    llm_config: None, error: Exception
) -> None:
    with (
        patch("app.summary.OpenAI") as mock_openai,
        patch("app.summary.logger") as mock_logger,
    ):
        mock_client = mock_openai.return_value.__enter__.return_value
        mock_client.chat.completions.create.side_effect = error
        assert generate_summary("private transcript") == "error"
    mock_logger.warning.assert_called_once_with("summary.failed", error_type=type(error).__name__)


def test_sdk_initialization_failure_returns_error(llm_config: None) -> None:
    with patch("app.summary.OpenAI", side_effect=ValueError("bad provider config")):
        assert generate_summary("text") == "error"
