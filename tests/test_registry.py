import pytest
from vortex.config.table_config import TableConfig


def test_register_and_get(registry, sample_table_config):
    table = registry.register(sample_table_config)
    assert table is not None
    assert registry.get("test_prices") is table


def test_get_missing_raises(registry):
    with pytest.raises(KeyError):
        registry.get("does_not_exist")


def test_tables_by_transport(registry):
    cfg1 = TableConfig("t1", "nats-a", {"a": str}, topic="a.>", index="a")
    cfg2 = TableConfig("t2", "solace-a", {"b": str}, topic="B/>")
    registry.register(cfg1)
    registry.register(cfg2)
    a_cfgs = registry.tables_by_transport("nats-a")
    assert len(a_cfgs) == 1
    assert a_cfgs[0].name == "t1"
