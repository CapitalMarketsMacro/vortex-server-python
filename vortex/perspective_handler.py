from __future__ import annotations
from typing import Callable, Iterable

from perspective.handlers.tornado import PerspectiveTornadoHandler

from vortex.observability import get_logger, metrics

logger = get_logger(__name__)


class TrackedPerspectiveHandler(PerspectiveTornadoHandler):
    """
    Drop-in replacement for PerspectiveTornadoHandler that tracks how many
    sessions are currently open and which tables each session has requested.

    Total session count is exact (we hook open / on_close).

    Per-table consumer count is a heuristic: we substring-search inbound
    binary protocol messages for the bytes of each known table name. The
    Perspective wire protocol embeds the table name as plain UTF-8 inside
    the open_table request, so this fires reliably for the FIRST inbound
    message that references a table. We mark each (session, table) pair
    only once, so subsequent messages don't double-count, and we decrement
    on session close.

    Limitations:
      • False positives if a table name happens to appear inside an arrow
        payload byte sequence. With distinctive multi-character names this
        is extremely rare.
      • A session that opens a table and then closes the table without
        closing the websocket will still be counted as a consumer until it
        disconnects. Acceptable — Perspective viewers don't typically do
        this; they hold the table for the lifetime of the page.

    The constructor signature accepts an extra kwarg `get_table_names` —
    a zero-arg callable that returns the current iterable of registered
    table names. We re-resolve it on every message so newly-added tables
    are tracked too.
    """

    _instances: set["TrackedPerspectiveHandler"] = set()

    def initialize(
        self,
        perspective_server,
        get_table_names: Callable[[], Iterable[str]] = lambda: (),
        **kwargs,
    ):
        super().initialize(perspective_server=perspective_server, **kwargs)
        self._get_table_names = get_table_names
        self._tables_touched: set[str] = set()

    def open(self):
        super().open()
        TrackedPerspectiveHandler._instances.add(self)
        metrics.WS_CLIENTS.set(len(TrackedPerspectiveHandler._instances))
        try:
            remote = self.request.remote_ip
        except Exception:
            remote = "?"
        logger.info(
            "ws.client_connected",
            remote_ip=remote,
            total_clients=len(TrackedPerspectiveHandler._instances),
        )

    def on_message(self, msg):
        if isinstance(msg, (bytes, bytearray)):
            try:
                names = list(self._get_table_names())
            except Exception:
                names = []
            for name in names:
                if name in self._tables_touched:
                    continue
                if name.encode() in msg:
                    self._tables_touched.add(name)
                    metrics.TABLE_CONSUMERS.labels(table=name).inc()
                    logger.info("ws.client_opened_table", table=name)
        super().on_message(msg)

    def on_close(self):
        TrackedPerspectiveHandler._instances.discard(self)
        metrics.WS_CLIENTS.set(len(TrackedPerspectiveHandler._instances))
        for name in list(self._tables_touched):
            metrics.TABLE_CONSUMERS.labels(table=name).dec()
        self._tables_touched.clear()
        logger.info(
            "ws.client_disconnected",
            total_clients=len(TrackedPerspectiveHandler._instances),
        )
        try:
            super().on_close()
        except Exception:
            logger.exception("ws.on_close_super_failed")

    @classmethod
    def active_count(cls) -> int:
        return len(cls._instances)
