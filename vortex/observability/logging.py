from __future__ import annotations
import logging
import sys
from contextlib import contextmanager
from typing import Any, Iterator

import structlog

from .correlation import correlation_id


def _add_correlation_id(_logger, _method_name, event_dict: dict) -> dict:
    """Inject the active correlation ID (if any) into every log line."""
    cid = correlation_id()
    if cid is not None:
        event_dict.setdefault("cid", cid)
    return event_dict


def configure_logging(level: str = "INFO", json_output: bool | None = None) -> None:
    """
    Configure structlog and the stdlib root logger so:
      - structlog.get_logger(...) emits structured events
      - existing logging.getLogger(...) calls funnel through the same processor chain
      - third-party library logs (nats, tornado, pymongo, ...) get the same format
      - JSON in production, pretty console in DEBUG mode (default), overridable

    Idempotent — safe to call multiple times.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    if json_output is None:
        json_output = log_level > logging.DEBUG

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        _add_correlation_id,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Replace existing handlers so re-configuration doesn't duplicate output
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(log_level)

    # Quiet down very chatty libraries unless DEBUG explicitly asked for them
    if log_level > logging.DEBUG:
        for noisy in ("nats.aio.client", "websockets.client", "websockets.server", "pymongo"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


@contextmanager
def bind_context(**kwargs: Any) -> Iterator[None]:
    """
    Temporarily bind key/value pairs into the log context for everything
    that runs inside this block (in this asyncio task).
    """
    tokens = []
    for k, v in kwargs.items():
        tokens.append(structlog.contextvars.bind_contextvars(**{k: v}))
    try:
        yield
    finally:
        structlog.contextvars.clear_contextvars()
