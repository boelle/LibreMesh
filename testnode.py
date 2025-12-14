#!/usr/bin/env python3
import asyncio
import ssl
import time

SATELLITE_HOST = "127.0.0.1"
SATELLITE_PORT = 4001
NODE_ID = "node_test"
REGION = "EU"

HEARTBEAT_INTERVAL = 30
REPAIR_REQUESTS = ["frag1", "frag2", "frag3", "frag4", "frag5"]

async def main():
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    while True:
        try:
            reader, writer = await asyncio.open_connection(
                SATELLITE_HOST, SATELLITE_PORT, ssl=context
            )
            print(f"Connected to satellite {SATELLITE_HOST}:{SATELLITE_PORT}")
            writer.write(f"IDENT:{NODE_ID}:{REGION}:pubkey\n".encode())
            await writer.drain()

            async def heartbeat_loop():
                uptime = 0
                while True:
                    writer.write(f"HEARTBEAT:{NODE_ID}:{REGION}:{uptime}\n".encode())
                    await writer.drain()
                    print(f"Heartbeat sent: HEARTBEAT:{NODE_ID}:{REGION}:{uptime}")
                    uptime += HEARTBEAT_INTERVAL
                    await asyncio.sleep(HEARTBEAT_INTERVAL)

            async def repair_loop():
                for frag in REPAIR_REQUESTS:
                    writer.write(f"REPAIR:{NODE_ID}:{frag}\n".encode())
                    await writer.drain()
                    print(f"Repair request sent for {frag}")
                    await asyncio.sleep(0.5)

            await asyncio.gather(heartbeat_loop(), repair_loop())
        except Exception as e:
            print(f"Connection lost, retry later ({e})")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
