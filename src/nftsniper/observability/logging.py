"""Структурированное логирование на structlog.

- JSON-вывод для прод (``log_json=True``), читаемый консоль для дев.
- Логгеры stdlib (uvicorn, fastapi, sqlalchemy) идут через тот же
  конвейер via ``ProcessorFormatter`` — единый формат везде.
- Внутренние (structlog) и внешние (stdlib) записи проходят один
  и тот же рендерер; таймстемпы — ISO 8601, UTC.
"""

import logging
import sys

import structlog
from structlog.types import Processor


def build_processor_formatter(json_output: bool = False) -> structlog.stdlib.ProcessorFormatter:
    """Formatter для stdlib-руки: все записи рендерятся одним рендерером."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    # Внешние (stdlib) записи: structlog 25.x берёт уже отформатированное
    # record.getMessage(), поэтому position-аргументы здесь не восстанавливаются.
    foreign_pre_chain: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
    ]

    if json_output:
        renderer: Processor = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    return structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=foreign_pre_chain,
    )


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Инициализирует stdlib logging + structlog. Идемпотентно."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    handler = logging.StreamHandler()
    handler.setFormatter(build_processor_formatter(json_output))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None, **initial_values: object) -> structlog.stdlib.BoundLogger:
    """Логгер с опциональными полями, привязанными сразу (env, version, ...)."""
    # structlog.get_logger создаётся динамически и не типизирован,
    # поэтому фиксируем тип явной аннотацией.
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    if initial_values:
        logger = logger.bind(**initial_values)
    return logger
