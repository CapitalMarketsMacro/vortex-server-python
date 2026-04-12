"""
Vortex observability — logging, metrics, correlation, retry primitives.

Public API:
    configure_logging   — set up structlog + stdlib bridge
    get_logger          — structlog logger factory (use this instead of logging.getLogger)
    bind_context        — context manager that binds key/value pairs into the log context
    correlation_id      — get/set the current correlation ID for the active task
    new_correlation_id  — generate a fresh ID and bind it
    ExponentialBackoff  — retry-with-jitter helper
    metrics             — Prometheus metric registry
"""
from .logging import configure_logging, get_logger, bind_context
from .correlation import correlation_id, new_correlation_id, set_correlation_id
from .backoff import ExponentialBackoff
from . import metrics

__all__ = [
    "configure_logging",
    "get_logger",
    "bind_context",
    "correlation_id",
    "new_correlation_id",
    "set_correlation_id",
    "ExponentialBackoff",
    "metrics",
]
