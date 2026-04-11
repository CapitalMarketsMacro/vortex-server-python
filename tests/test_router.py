import pytest
import orjson
from vortex.router import UpdateRouter


@pytest.mark.asyncio
async def test_route_dict(registry, sample_table_config):
    registry.register(sample_table_config)
    router = UpdateRouter()
    table = registry.get("test_prices")

    await router.route(table, {"instrument": "EURUSD", "bid": 1.08, "ask": 1.0801})

    view = table.view()
    data = view.to_columns()
    assert data["instrument"] == ["EURUSD"]
    assert data["bid"] == [1.08]


@pytest.mark.asyncio
async def test_route_json_bytes(registry, sample_table_config):
    registry.register(sample_table_config)
    router = UpdateRouter()
    table = registry.get("test_prices")

    payload = orjson.dumps({"instrument": "GBPUSD", "bid": 1.27, "ask": 1.2701})
    await router.route(table, payload)

    view = table.view()
    data = view.to_columns()
    assert "GBPUSD" in data["instrument"]
