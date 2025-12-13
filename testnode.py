import asyncio
import os
import socket
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

KEYFILE = "node_key.pem"
NODE_ID = "node_test"
REGION = "EU"
FRAGMENTS = ["frag1", "frag2", "frag3", "frag4", "frag5"]
HEARTBEAT_INTERVAL = 30  # seconds
SATELLITE_HOST = "127.0.0.1"
SATELLITE_PORT = 4001

# Load or generate keyfile
if os.path.exists(KEYFILE):
    with open(KEYFILE, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
else:
    private_key = Ed25519PrivateKey.generate()
    with open(KEYFILE, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    print(f"Generated new keyfile: {KEYFILE}")

async def send_repair_request(writer, fragment):
    message = f"REPAIR:{fragment}"
    writer.write(message.encode())
    await writer.drain()
    print(f"Repair request sent for {fragment}")

async def send_heartbeat(writer, uptime):
    heartbeat_data = f"HEARTBEAT:{NODE_ID}:{REGION}:{uptime}"
    signature = private_key.sign(heartbeat_data.encode())
    writer.write(heartbeat_data.encode() + b"|" + signature)
    await writer.drain()
    print(f"Heartbeat sent: {heartbeat_data}")

async def node_communication():
    while True:
        try:
            reader, writer = await asyncio.open_connection(SATELLITE_HOST, SATELLITE_PORT)
            print(f"Connected to satellite {SATELLITE_HOST}:{SATELLITE_PORT}")
            uptime_start = time.time()

            # Start heartbeat loop
            async def heartbeat_loop():
                while True:
                    uptime = int(time.time() - uptime_start)
                    await send_heartbeat(writer, uptime)
                    await asyncio.sleep(HEARTBEAT_INTERVAL)

            asyncio.create_task(heartbeat_loop())

            # Simulate repair requests
            for frag in FRAGMENTS:
                await send_repair_request(writer, frag)
                await asyncio.sleep(1)

            # Keep connection open
            while True:
                await asyncio.sleep(1)

        except (ConnectionRefusedError, ConnectionResetError):
            print("Connection lost, retry later")
            await asyncio.sleep(5)

async def main():
    await node_communication()

if __name__ == "__main__":
    asyncio.run(main())
