#!/usr/bin/env python3
"""
Publishes simulated FX price ticks to NATS for local dev testing.
Usage: python scripts/sim_nats_publisher.py
Requires: nats-py, orjson
"""
import asyncio
import random
import orjson
from datetime import datetime, timezone
import nats

NATS_URL = "nats://montunoblenumbat2404:8821"
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF"]
SUBJECT = "rates.ust.trades.sim"


async def main():
    nc = await nats.connect(NATS_URL)
    print(f"Publishing to NATS subject: {SUBJECT}")
    try:
        while True:
            pair = random.choice(PAIRS)
            base = {"EURUSD": 1.08, "GBPUSD": 1.27, "USDJPY": 149.5,
                    "AUDUSD": 0.65, "USDCHF": 0.90}[pair]
            spread = 0.0001
            bid = round(base + random.gauss(0, 0.0002), 5)
            ask = round(bid + spread, 5)
            msg = {
                "trade_id": f"T{random.randint(100000,999999)}",
                "isin": f"US{random.randint(10000000,99999999)}{random.randint(0,9)}",
                "cusip": f"{random.randint(100000000,999999999)}",
                "side": random.choice(["BUY", "SELL"]),
                "qty": round(random.uniform(1e6, 50e6), 0),
                "price": round(99 + random.uniform(-1, 1), 4),
                "yield": round(4.5 + random.gauss(0, 0.05), 4),
                "spread_to_benchmark": round(random.uniform(0, 50), 2),
                "trader": random.choice(["trader_a", "trader_b", "trader_c"]),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            await nc.publish(SUBJECT, orjson.dumps(msg))
            print(f"  → {msg['trade_id']}  {msg['side']}  {msg['qty']:,.0f}")
            await asyncio.sleep(random.uniform(0.2, 1.0))
    finally:
        await nc.drain()


if __name__ == "__main__":
    asyncio.run(main())
