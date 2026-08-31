"""Структурированные логи: JSON-вывод, mdc-поля, пропуск stdlib через тот же конвейер."""

import io
import json
import logging
from collections.abc import Generator

import pytest
import structlog

from nftsniper.observability.logging import (
    build_processor_formatter,
    get_logger,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _restore_logging() -> Generator[None, None, None]:
    setup_logging("INFO", json_output=False)
    yield
    logging.getLogger().handlers.clear()
    structlog.reset_defaults()


def _capture_logs(json_output: bool = True) -> io.StringIO:
    """Стрим + обработчик с тем же форматтером, что и в прод (setup_logging)."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(build_processor_formatter(json_output))
    root = logging.getLogger()
    root.handlers = [handler]
    return stream


def test_structlog_event_is_json() -> None:
    setup_logging("INFO", json_output=True)
    stream = _capture_logs()
    try:
        get_logger("nftsniper.test").info(
            "listing_discovered", collection="Anonymous Numbers", price="120"
        )
    finally:
        logging.getLogger().handlers.clear()

    payload = json.loads(stream.getvalue().strip())
    assert payload["event"] == "listing_discovered"
    assert payload["logger"] == "nftsniper.test"
    assert payload["level"] == "info"
    assert payload["collection"] == "Anonymous Numbers"
    assert payload["price"] == "120"
    assert "timestamp" in payload


def test_cyrillic_survives_json_renderer() -> None:
    setup_logging("INFO", json_output=True)
    stream = _capture_logs()
    try:
        get_logger("test").warning("недооценённый листинг найден", скидка="42%")
    finally:
        logging.getLogger().handlers.clear()

    payload = json.loads(stream.getvalue().strip())
    assert payload["event"] == "недооценённый листинг найден"
    assert payload["скидка"] == "42%"


def test_structlog_positional_args_are_formatted() -> None:
    setup_logging("INFO", json_output=True)
    stream = _capture_logs()
    try:
        get_logger("test").info("discount is %s", "42%")
    finally:
        logging.getLogger().handlers.clear()

    payload = json.loads(stream.getvalue().strip())
    assert payload["event"] == "discount is 42%"


def test_stdlib_logs_go_through_same_pipeline() -> None:
    setup_logging("INFO", json_output=True)
    stream = _capture_logs()
    try:
        # stdlib-стиль с %-плейсхолдером: uvicorn/fastapi так и пишут
        logging.getLogger("uvicorn.access").warning("from_stdlib %s", "positional_arg")
    finally:
        logging.getLogger().handlers.clear()

    payload = json.loads(stream.getvalue().strip())
    assert payload["event"] == "from_stdlib positional_arg"
    assert payload["level"] == "warning"


def test_console_renderer_is_not_json() -> None:
    setup_logging("INFO", json_output=False)
    stream = _capture_logs(json_output=False)
    try:
        get_logger("test").info("hello_console")
    finally:
        logging.getLogger().handlers.clear()

    line = stream.getvalue().strip()
    assert line
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)
    assert "hello_console" in line
