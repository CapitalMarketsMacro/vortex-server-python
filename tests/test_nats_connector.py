import pytest
import orjson
from vortex.connectors.nats import NATSConnector


@pytest.mark.asyncio
async def test_nats_dispatch_on_message(
    registry, router, sample_table_config, sample_transport_config
):
    registry.register(sample_table_config)
    connector = NATSConnector(sample_transport_config, registry, router)

    payload = orjson.dumps({"instrument": "USDJPY", "bid": 149.5, "ask": 149.51})
    await connector._dispatch("test_prices", payload)

    table = registry.get("test_prices")
    view = table.view()
    data = view.to_columns()
    assert "USDJPY" in data["instrument"]
