import pytest
import perspective
from vortex.registry import TableRegistry
from vortex.router import UpdateRouter
from vortex.config.table_config import TableConfig, TransportConfig


@pytest.fixture
def psp_client():
    server = perspective.Server()
    return server.new_local_client()


@pytest.fixture
def registry(psp_client):
    return TableRegistry(psp_client)


@pytest.fixture
def router():
    return UpdateRouter()


@pytest.fixture
def sample_transport_config():
    return TransportConfig(
        name="nats-test",
        type="nats",
        config={"url": "nats://localhost:4222"},
        enabled=True,
    )


@pytest.fixture
def sample_table_config():
    return TableConfig(
        name="test_prices",
        transport_name="nats-test",
        topic="test.prices.>",
        schema={"instrument": str, "bid": float, "ask": float},
        index="instrument",
    )
