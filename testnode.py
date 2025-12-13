#!/usr/bin/env python3
import asyncio
import ssl
import random
import time

SAT_HOST = "127.0.0.1"
SAT_PORT = 4001

NODE_ID = f"node{random.randint(10000,99999)}"
REGION = "EU"
FRAGMENTS = ["frag1", "frag2", "frag3", "frag4", "frag5"]

async def main():
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    while True:
        try:
            reader, writer = await asyncio.open_connection(
                SAT_HOST, SAT_PORT, ssl=ssl_ctx
            )

            # HELLO
            hello = f"HELLO {NODE_ID} {REGION} {','.join(FRAGMENTS)}\n"
            writer.write(hello.encode())
            await writer.drain()

            # Start heartbeat task
            asyncio.create_task(send_heartbeats(writer))

            # Send some repair requests slowly
            for frag in FRAGMENTS:
                await asyncio.sleep(2)
                msg = f"REPAIR {frag}\n"
                writer.write(msg.encode())
                await writer.drain()

            # Keep connection alive forever
            while True:
                await asyncio.sleep(10)

        except Exception as e:
            print("Connection lost, retry later")
            await asyncio.sleep(5)

async def send_heartbeats(writer):
    while True:
        await asyncio.sleep(1)
        try:
            writer.write(b"HEARTBEAT\n")
            await writer.drain()
        except:
            break

if __name__ == "__main__":
    asyncio.run(main())
