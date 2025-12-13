import asyncio
import json
import ssl
import time

SATELLITE_HOST = "127.0.0.1"
SATELLITE_PORT = 4001
NODE_ID = "test-node-001"
REGION = "eu"

ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE  # for local testing only

async def send_heartbeat(writer):
    while True:
        heartbeat = {
            "type": "heartbeat",
            "node_id": NODE_ID,
            "region": REGION,
            "uptime": int(time.time()),
            "rank": 100,
            "timestamp": int(time.time()),
            "fragments": ["frag1", "frag2"]
        }
        writer.write((json.dumps(heartbeat) + "\n").encode())
        await writer.drain()
        await asyncio.sleep(30)  # heartbeat interval

async def test_node():
    reader, writer = await asyncio.open_connection(
        SATELLITE_HOST, SATELLITE_PORT, ssl=ssl_context
    )
    print(f"Connected to satellite at {SATELLITE_HOST}:{SATELLITE_PORT}")
    asyncio.create_task(send_heartbeat(writer))
    # Optional: send a test repair request after a few seconds
    await asyncio.sleep(5)
    repair_req = {
        "type": "repair_request",
        "fragment_id": "frag1"
    }
    writer.write((json.dumps(repair_req) + "\n").encode())
    await writer.drain()

    # Keep the connection open
    while True:
        await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(test_node())
