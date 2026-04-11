#!/usr/bin/env python3
"""
Seeds the Vortex Mongo database with an initial set of transports and tables
that mirror the original tables.yaml. Safe to run multiple times — uses upsert.

Usage:
    python scripts/seed_mongo.py
"""
from __future__ import annotations
import logging

from vortex.config.settings import load_settings
from vortex.store.mongo import MongoStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("seed_mongo")


TRANSPORTS = [
    {
        "name": "nats-monty",
        "type": "nats",
        "enabled": True,
        "config": {
            "url": "nats://montunoblenumbat2404:8821",
        },
    },
    {
        "name": "solace-local",
        "type": "solace",
        "enabled": False,
        "config": {
            "host": "localhost",
            "port": 55555,
            "vpn": "default",
            "username": "admin",
            "password": "admin",
        },
    },
    {
        "name": "ws-sim",
        "type": "ws",
        "enabled": True,
        "config": {
            "url": "ws://localhost:9000/feed",
            "reconnect_interval": 5.0,
        },
    },
]

TABLES = [
    {
        "name": "fx_executions",
        "transport_name": "solace-local",
        "topic": "FX/EXEC/>",
        "durable": None,
        "index": None,
        "limit": 5000,
        "nats_mode": "core",
        "schema": {
            "exec_id": "string",
            "ccy_pair": "string",
            "side": "string",
            "notional": "float",
            "px": "float",
            "spot_rate": "float",
            "value_date": "date",
            "venue": "string",
            "trader": "string",
            "ts": "datetime",
        },
    },
    {
        "name": "ust_trades",
        "transport_name": "nats-monty",
        "topic": "rates.ust.trades.>",
        "durable": None,
        "index": "trade_id",
        "limit": None,
        "nats_mode": "core",
        "schema": {
            "trade_id": "string",
            "isin": "string",
            "cusip": "string",
            "side": "string",
            "qty": "float",
            "price": "float",
            "yield": "float",
            "spread_to_benchmark": "float",
            "trader": "string",
            "ts": "datetime",
        },
    },
    {
        "name": "live_prices",
        "transport_name": "ws-sim",
        "topic": "",
        "durable": None,
        "index": "instrument",
        "limit": None,
        "nats_mode": "core",
        "schema": {
            "instrument": "string",
            "bid": "float",
            "ask": "float",
            "mid": "float",
            "bid_size": "float",
            "ask_size": "float",
            "ts": "datetime",
        },
    },
]


def main() -> None:
    settings = load_settings()
    store = MongoStore(settings.mongo.uri, settings.mongo.database)

    for t in TRANSPORTS:
        store.upsert_transport(t)
        logger.info("upserted transport: %s (%s)", t["name"], t["type"])

    for t in TABLES:
        store.upsert_table(t)
        logger.info("upserted table:     %s → %s", t["name"], t["transport_name"])

    logger.info(
        "done. %d transports, %d tables in database '%s'.",
        len(TRANSPORTS), len(TABLES), settings.mongo.database,
    )
    store.close()


if __name__ == "__main__":
    main()
