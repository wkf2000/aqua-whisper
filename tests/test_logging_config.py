"""Basic smoke tests for logging configuration."""

import structlog

from app.logging_config import setup_logging


def test_setup_logging_configures_structlog() -> None:
    """setup_logging should configure structlog and allow logging without error."""
    setup_logging(service_name="test-service", environment="test")
    logger = structlog.get_logger()

    # This should not raise and should return None (structlog logging API).
    result = logger.info("test_event", foo="bar")
    assert result is None

