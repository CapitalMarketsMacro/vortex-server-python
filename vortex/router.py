from __future__ import annotations
import logging
import orjson

logger = logging.getLogger(__name__)

# Apache Arrow IPC stream starts with a continuation marker (0xFFFFFFFF).
_ARROW_MAGIC = b"\xff\xff\xff\xff"


class UpdateRouter:
    """
    Receives raw payloads from connectors and calls table.update().

    Payload handling:
        bytes starting with Arrow IPC magic  →  passed as-is (fastest path)
        bytes (other)                        →  decoded as UTF-8 JSON
        dict / list[dict]                    →  passed directly
    """

    async def route(self, table, payload: bytes | dict | list) -> None:
        try:
            if isinstance(payload, (bytes, bytearray)):
                if payload[:4] == _ARROW_MAGIC:
                    table.update(bytes(payload))
                else:
                    data = orjson.loads(payload)
                    table.update(data if isinstance(data, list) else [data])
            elif isinstance(payload, dict):
                table.update([payload])
            elif isinstance(payload, list):
                table.update(payload)
            else:
                logger.warning("UpdateRouter: unhandled payload type %s", type(payload))
        except Exception:
            logger.exception("UpdateRouter: failed to update table")
