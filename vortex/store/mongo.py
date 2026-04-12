from __future__ import annotations
from typing import Any
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

from vortex.config.table_config import (
    TransportConfig,
    TableConfig,
    schema_from_strings,
)
from vortex.observability import get_logger

logger = get_logger(__name__)


class MongoStore:
    """
    Thin repository wrapping the Vortex database.

    Collections:
      transports   — {name, type, config, enabled}
      tables       — {name, transport_name, schema, topic, durable, index, limit}
    """

    def __init__(self, uri: str, database: str) -> None:
        self._client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._db = self._client[database]
        self.transports = self._db["transports"]
        self.tables = self._db["tables"]
        self._ensure_indexes()
        logger.info("mongo.connected", uri=uri, database=database)

    def _ensure_indexes(self) -> None:
        self.transports.create_index([("name", ASCENDING)], unique=True)
        self.tables.create_index([("name", ASCENDING)], unique=True)

    # ── transports ──────────────────────────────────────────────────────────

    def list_transports(self) -> list[dict]:
        return list(self.transports.find({}, {"_id": 0}).sort("name"))

    def get_transport(self, name: str) -> dict | None:
        return self.transports.find_one({"name": name}, {"_id": 0})

    def upsert_transport(self, doc: dict) -> None:
        name = doc["name"]
        self.transports.replace_one({"name": name}, doc, upsert=True)

    def delete_transport(self, name: str) -> int:
        res = self.transports.delete_one({"name": name})
        return res.deleted_count

    def load_transport_configs(self) -> list[TransportConfig]:
        return [
            TransportConfig(
                name=d["name"],
                type=d["type"],
                config=d.get("config", {}),
                enabled=d.get("enabled", True),
            )
            for d in self.list_transports()
        ]

    # ── tables ──────────────────────────────────────────────────────────────

    def list_tables(self) -> list[dict]:
        return list(self.tables.find({}, {"_id": 0}).sort("name"))

    def get_table(self, name: str) -> dict | None:
        return self.tables.find_one({"name": name}, {"_id": 0})

    def upsert_table(self, doc: dict) -> None:
        name = doc["name"]
        self.tables.replace_one({"name": name}, doc, upsert=True)

    def delete_table(self, name: str) -> int:
        res = self.tables.delete_one({"name": name})
        return res.deleted_count

    def load_table_configs(self) -> list[TableConfig]:
        out = []
        for d in self.list_tables():
            out.append(
                TableConfig(
                    name=d["name"],
                    transport_name=d["transport_name"],
                    schema=schema_from_strings(d.get("schema", {})),
                    topic=d.get("topic", ""),
                    durable=d.get("durable"),
                    index=d.get("index"),
                    limit=d.get("limit"),
                    nats_mode=d.get("nats_mode", "core"),
                )
            )
        return out

    def close(self) -> None:
        self._client.close()
