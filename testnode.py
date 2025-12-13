import asyncio
import ssl
import json
import random
import time

SATELLITE_HOST = "127.0.0.1"
SATELLITE_PORT = 4001

NODE_ID = f"node{random.randint(1000,9999)}"
REGION = "EU"
FRAGMENTS = [f"frag{i}" for i in range(1, 6)]
HEARTBEAT_INTERVAL = 3  # seconds

ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

async def send_heartbeat(writer):
    while True:
        message = {
            "type": "heartbeat",
            "node_id": NODE_ID,
            "region": REGION,
            "rank": random.randint(80, 100),
            "uptime": int(time.time()) % 10000,
            "timestamp": int(time.time()),
            "fragments": FRAGMENTS
        }
        writer.write((json.dumps(message) + "\n").encode())
        await writer.drain()
        await asyncio.sleep(HEARTBEAT_INTERVAL)

async def send_repair_request(writer):
    # simulate a repair job request after a short delay
    await asyncio.sleep(5)
    for frag in FRAGMENTS:
        message = {
            "type": "repair_request",
            "fragment_id": frag
        }
        writer.write((json.dumps(message) + "\n").encode())
        await writer.drain()
        await asyncio.sleep(2)

async def main():
    reader, writer = await asyncio.open_connection(
        SATELLITE_HOST, SATELLITE_PORT, ssl=ssl_context
    )
    print(f"Connected to satellite at {SATELLITE_HOST}:{SATELLITE_PORT} as {NODE_ID}")
    await asyncio.gather(
        send_heartbeat(writer),
        send_repair_request(writer)
    )

if __name__ == "__main__":
    asyncio.run(main())
