from __future__ import annotations
import uuid
from contextvars import ContextVar

# One correlation ID per task / per request. structlog merges this into every log line.
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set(value)


def new_correlation_id() -> str:
    cid = uuid.uuid4().hex[:12]
    _correlation_id.set(cid)
    return cid
