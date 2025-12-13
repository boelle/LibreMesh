import asyncio
import ssl
import os
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization  # <--- needed

HOST = "127.0.0.1"
PORT = 4001
REGION = "EU"
NODE_ID = "node_test"
HEARTBEAT_INTERVAL = 30
REPAIR_FRAGMENTS = ["frag1", "frag2", "frag3", "frag4", "frag5"]
KEYFILE = "node_key.pem"

# Load or generate keyfile
if os.path.exists(KEYFILE):
    with open(KEYFILE, "rb") as f:
        private_key = Ed25519PrivateKey.from_private_bytes(f.read())
else:
    private_key = Ed25519PrivateKey.generate()
    with open(KEYFILE, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        ))

async def send_heartbeat(writer):
    while True:
        uptime = int(time.time() - start_time)
        msg = f"HEARTBEAT:{NODE_ID}:{REGION}:{uptime}"
        writer.write(msg.encode() + b"\n")
        try:
            await writer.drain()
            print(f"Heartbeat sent: {msg}")
        except Exception as e:
            print(f"Heartbeat failed: {e}")
            return
        await asyncio.sleep(HEARTBEAT_INTERVAL)

async def send_repair_request(writer, fragment):
    msg = f"REPAIR:{fragment}"
    writer.write(msg.encode() + b"\n")
    try:
        await writer.drain()
        print(f"Repair request sent for {fragment}")
    except Exception as e:
        print(f"Failed to send repair request for {fragment}: {e}")

async def node_communication():
    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    while True:
        try:
            reader, writer = await asyncio.open_connection(HOST, PORT, ssl=ssl_context)
            print(f"Connected to satellite {HOST}:{PORT}")

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(send_heartbeat(writer))

            # Send repair requests
            for frag in REPAIR_FRAGMENTS:
                await send_repair_request(writer, frag)

            await heartbeat_task
        except Exception as e:
            print(f"Connection lost, retrying in 5s: {e}")
            await asyncio.sleep(5)

async def main():
    await node_communication()

if __name__ == "__main__":
    start_time = time.time()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Node shutting down.")
