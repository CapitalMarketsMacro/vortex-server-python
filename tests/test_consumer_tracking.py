"""
Verifies the consumer-tracking heuristic in TrackedPerspectiveHandler
without spinning up a real WebSocket. We instantiate the handler with
mock plumbing and call the open / on_message / on_close methods directly.
"""
import pytest
from unittest.mock import MagicMock
from prometheus_client import REGISTRY

from vortex.perspective_handler import TrackedPerspectiveHandler
from vortex.observability import metrics


def _make_handler(table_names):
    """Build an instance bypassing Tornado's __init__ machinery."""
    h = TrackedPerspectiveHandler.__new__(TrackedPerspectiveHandler)
    h.server = MagicMock()
    h.session = MagicMock()
    h.executor = None
    h.loop = None
    h.request = MagicMock()
    h.request.remote_ip = "127.0.0.1"
    h._get_table_names = lambda: table_names
    h._tables_touched = set()
    return h


def _consumer(table):
    return REGISTRY.get_sample_value("vortex_table_consumers", {"table": table}) or 0.0


def test_substring_match_marks_consumer():
    h = _make_handler(["ust_trades", "live_prices"])

    before = _consumer("ust_trades")
    TrackedPerspectiveHandler._instances.add(h)
    h.on_message(b"\x00\x10ust_trades\x00\x00")
    assert _consumer("ust_trades") == before + 1
    assert "ust_trades" in h._tables_touched

    # Second message containing the same table shouldn't double-count
    h.on_message(b"more bytes ust_trades again")
    assert _consumer("ust_trades") == before + 1

    # Cleanup
    h._tables_touched.clear()
    metrics.TABLE_CONSUMERS.labels(table="ust_trades").dec()
    TrackedPerspectiveHandler._instances.discard(h)


def test_unrelated_message_no_match():
    h = _make_handler(["ust_trades"])
    before = _consumer("ust_trades")
    TrackedPerspectiveHandler._instances.add(h)
    h.on_message(b"unrelated arrow payload bytes here")
    assert _consumer("ust_trades") == before
    TrackedPerspectiveHandler._instances.discard(h)


def test_close_decrements_consumer_count():
    h = _make_handler(["live_prices"])
    TrackedPerspectiveHandler._instances.add(h)

    h.on_message(b"some msg with live_prices in it")
    after_open = _consumer("live_prices")

    # Stub super().on_close to skip the real Tornado teardown
    import vortex.perspective_handler as ph
    original = ph.PerspectiveTornadoHandler.on_close
    ph.PerspectiveTornadoHandler.on_close = lambda self: None
    try:
        h.on_close()
    finally:
        ph.PerspectiveTornadoHandler.on_close = original

    assert _consumer("live_prices") == after_open - 1


def test_active_count_tracks_open_close():
    base = TrackedPerspectiveHandler.active_count()

    h1 = _make_handler([])
    h2 = _make_handler([])
    TrackedPerspectiveHandler._instances.add(h1)
    TrackedPerspectiveHandler._instances.add(h2)
    assert TrackedPerspectiveHandler.active_count() == base + 2

    TrackedPerspectiveHandler._instances.discard(h1)
    TrackedPerspectiveHandler._instances.discard(h2)
    assert TrackedPerspectiveHandler.active_count() == base
