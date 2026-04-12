import pytest
import orjson
from prometheus_client import REGISTRY

from vortex.observability import metrics
from vortex.connectors.nats import NATSConnector


def _value(metric_family_name: str, **labels):
    """Read a single metric sample from the global registry."""
    return REGISTRY.get_sample_value(metric_family_name, labels)


@pytest.mark.asyncio
async def test_dispatch_increments_received(
    registry, router, sample_table_config, sample_transport_config
):
    registry.register(sample_table_config)
    connector = NATSConnector(sample_transport_config, registry, router)

    before = _value(
        "vortex_messages_received_total",
        transport="nats-test", table="test_prices",
    ) or 0.0

    payload = orjson.dumps({"instrument": "EURUSD", "bid": 1.08, "ask": 1.0801})
    await connector._dispatch("test_prices", payload)

    after = _value(
        "vortex_messages_received_total",
        transport="nats-test", table="test_prices",
    )
    assert after == before + 1


@pytest.mark.asyncio
async def test_unknown_table_drop(registry, router, sample_transport_config):
    connector = NATSConnector(sample_transport_config, registry, router)

    before = _value(
        "vortex_messages_dropped_total",
        transport="nats-test", reason="unknown_table",
    ) or 0.0

    await connector._dispatch("never_registered", b"{}")

    after = _value(
        "vortex_messages_dropped_total",
        transport="nats-test", reason="unknown_table",
    )
    assert after == before + 1


def test_table_registered_gauge_tracks_count(registry, sample_table_config):
    # Gauge holds the current size of the registry that wrote it last.
    # In production there's only one TableRegistry so this is correct.
    registry.register(sample_table_config)
    assert _value("vortex_tables_registered") == 1.0
