from __future__ import annotations
import logging
from vortex.config.table_config import TableConfig

logger = logging.getLogger(__name__)


class TableRegistry:
    """
    Owns all Perspective Table instances.
    Created once at startup; connector threads and the Tornado loop
    both read from it (read is safe; update() is called from the loop).
    """

    def __init__(self, client) -> None:
        self._client = client
        self._tables: dict[str, object] = {}
        self._configs: dict[str, TableConfig] = {}

    def register(self, cfg: TableConfig) -> object:
        kwargs: dict = {}
        if cfg.index:
            kwargs["index"] = cfg.index
        if cfg.limit:
            kwargs["limit"] = cfg.limit

        table = self._client.table(cfg.schema, name=cfg.name, **kwargs)
        self._tables[cfg.name] = table
        self._configs[cfg.name] = cfg
        logger.info(
            "Registered table '%s'  index=%s  limit=%s  transport=%s",
            cfg.name, cfg.index, cfg.limit, cfg.transport_name,
        )
        return table

    def get(self, name: str):
        if name not in self._tables:
            raise KeyError(f"No table registered with name '{name}'")
        return self._tables[name]

    def all_tables(self) -> dict[str, object]:
        return dict(self._tables)

    def tables_by_transport(self, transport_name: str) -> list[TableConfig]:
        return [c for c in self._configs.values() if c.transport_name == transport_name]
