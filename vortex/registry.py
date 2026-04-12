from __future__ import annotations
from vortex.config.table_config import TableConfig
from vortex.observability import get_logger, metrics

logger = get_logger(__name__)


class TableRegistry:
    """
    Owns all Perspective Table instances.
    Created once at startup; connector tasks and the Tornado loop both read
    from it. update() is always called from the asyncio loop.
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
        metrics.TABLES_REGISTERED.set(len(self._tables))
        logger.info(
            "table.registered",
            table=cfg.name,
            index=cfg.index,
            limit=cfg.limit,
            transport=cfg.transport_name,
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
