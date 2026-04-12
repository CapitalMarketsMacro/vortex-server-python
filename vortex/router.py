from __future__ import annotations
import orjson

from vortex.observability import get_logger

logger = get_logger(__name__)

# Apache Arrow IPC stream starts with a continuation marker (0xFFFFFFFF).
_ARROW_MAGIC = b"\xff\xff\xff\xff"


class UpdateRouter:
    """
    Receives raw payloads from connectors and calls table.update().

    Payload handling:
        bytes starting with Arrow IPC magic  →  passed as-is (fastest path)
        bytes (other)                        →  decoded as UTF-8 JSON
        dict / list[dict]                    →  passed directly

    Exceptions raised here are caught by the connector's _dispatch wrapper
    and recorded as 'dispatch_error' drops in the metrics.
    """

    async def route(self, table, payload: bytes | dict | list) -> None:
        if isinstance(payload, (bytes, bytearray)):
            if payload[:4] == _ARROW_MAGIC:
                table.update(bytes(payload))
                return
            data = orjson.loads(payload)
            table.update(data if isinstance(data, list) else [data])
            return
        if isinstance(payload, dict):
            table.update([payload])
            return
        if isinstance(payload, list):
            table.update(payload)
            return
        raise TypeError(f"unhandled payload type {type(payload).__name__}")
