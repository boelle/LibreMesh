import asyncio
import ssl
import os
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

SATELLITE_HOST = "127.0.0.1"
SATELLITE_PORT = 4001

NODE_ID = "node_test"
REGION = "EU"
HEARTBEAT_INTERVAL = 30
KEYFILE = "node.key"

REPAIR_FRAGMENTS = ["frag1", "frag2", "frag3", "frag4", "frag5"]

# --------------------------------------------------
# Key handling (32-byte raw Ed25519 key)
# --------------------------------------------------
if os.path.exists(KEYFILE):
    with open(KEYFILE, "rb") as f:
        key_bytes = f.read()
        if len(key_bytes) != 32:
            raise ValueError("Invalid keyfile size (must be 32 bytes)")
        private_key = Ed25519PrivateKey.from_private_bytes(key_bytes)
else:
    private_key = Ed25519PrivateKey.generate()
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(KEYFILE, "wb") as f:
        f.write(key_bytes)

public_key = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)

# --------------------------------------------------
# Networking
# --------------------------------------------------
async def send_heartbeat(writer):
    uptime = int(time.time() - START_TIME)
    msg = f"HEARTBEAT:{NODE_ID}:{REGION}:{uptime}\n"
    writer.write(msg.encode())
    await writer.drain()
    print(f"Heartbeat sent: {msg.strip()}")

async def send_repair_request(writer, fragment):
    msg = f"REPAIR:{NODE_ID}:{fragment}\n"
    writer.write(msg.encode())
    await writer.drain()
    print(f"Repair request sent for {fragment}")

async def node_loop():
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    while True:
        try:
            reader, writer = await asyncio.open_connection(
                SATELLITE_HOST, SATELLITE_PORT, ssl=ssl_ctx
            )
            print(f"Connected to satellite {SATELLITE_HOST}:{SATELLITE_PORT}")

            # Send identity once
            writer.write(
                f"IDENT:{NODE_ID}:{REGION}:{public_key.hex()}\n".encode()
            )
            await writer.drain()

            last_hb = 0
            frag_index = 0

            while True:
                now = time.time()

                if now - last_hb >= HEARTBEAT_INTERVAL:
                    await send_heartbeat(writer)
                    last_hb = now

                if frag_index < len(REPAIR_FRAGMENTS):
                    await send_repair_request(writer, REPAIR_FRAGMENTS[frag_index])
                    frag_index += 1

                await asyncio.sleep(2)

        except Exception as e:
            print(f"Connection lost, retry later ({e})")
            await asyncio.sleep(5)

# --------------------------------------------------
# Main
# --------------------------------------------------
async def main():
    await node_loop()

START_TIME = time.time()

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Node shutting down.")
