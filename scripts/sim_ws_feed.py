#!/usr/bin/env python3
"""
Runs a local WebSocket server that emits simulated FX price ticks.
VortexServerPython's WSSourceConnector connects to this as a client.
Usage: python scripts/sim_ws_feed.py
Set VORTEX_WS_SOURCE__URL=ws://localhost:9000/feed
"""
import asyncio
import random
import orjson
from datetime import datetime, timezone
import websockets

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF"]
BASES = {"EURUSD": 1.08, "GBPUSD": 1.27, "USDJPY": 149.5, "AUDUSD": 0.65, "USDCHF": 0.90}


async def feed(ws):
    print(f"Client connected: {ws.remote_address}")
    try:
        while True:
            pair = random.choice(PAIRS)
            bid = round(BASES[pair] + random.gauss(0, 0.0002), 5)
            ask = round(bid + 0.0001, 5)
            msg = {
                "instrument": pair,
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2, 5),
                "bid_size": round(random.uniform(1e6, 10e6), 0),
                "ask_size": round(random.uniform(1e6, 10e6), 0),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            await ws.send(orjson.dumps(msg))
            await asyncio.sleep(random.uniform(0.05, 0.3))
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")


async def main():
    async with websockets.serve(feed, "localhost", 9000, ping_interval=20):
        print("WS feed server on ws://localhost:9000/feed")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
