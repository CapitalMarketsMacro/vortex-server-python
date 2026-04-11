from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

_TYPE_MAP: dict[str, type | str] = {
    "string": str,
    "float": float,
    "integer": int,
    "boolean": bool,
    "datetime": "datetime",
    "date": "date",
}

_REVERSE_TYPE_MAP: dict[Any, str] = {
    str: "string",
    float: "float",
    int: "integer",
    bool: "boolean",
    "datetime": "datetime",
    "date": "date",
}

TRANSPORT_TYPES = ("nats", "solace", "ws")
SCHEMA_TYPES = tuple(_TYPE_MAP.keys())
NATS_MODES = ("core", "jetstream")


@dataclass
class TransportConfig:
    name: str
    type: str                   # "nats" | "solace" | "ws"
    config: dict                # type-specific connection fields
    enabled: bool = True


@dataclass
class TableConfig:
    name: str
    transport_name: str         # references TransportConfig.name
    schema: dict[str, type | str]
    topic: str = ""             # Solace topic or NATS subject; unused for ws
    durable: str | None = None  # NATS JetStream durable name (only used when nats_mode="jetstream")
    index: str | None = None
    limit: int | None = None
    nats_mode: str = "core"     # "core" | "jetstream" — only meaningful for NATS transports


def schema_from_strings(raw: dict[str, str]) -> dict[str, type | str]:
    """Convert {col: 'string'} → {col: str} for perspective-python."""
    return {col: _TYPE_MAP.get(typ, str) for col, typ in raw.items()}


def schema_to_strings(schema: dict[str, type | str]) -> dict[str, str]:
    """Inverse of schema_from_strings — used by the admin UI to render forms."""
    return {col: _REVERSE_TYPE_MAP.get(typ, "string") for col, typ in schema.items()}
