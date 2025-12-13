import asyncio
import ssl
import random
import time

SATELLITE_HOST = "127.0.0.1"
SATELLITE_PORT = 4001

FRAGMENTS = ["frag1", "frag2", "frag3", "frag4", "frag5"]

async def node_communication():
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    reader, writer = await asyncio.open_connection(
        SATELLITE_HOST,
        SATELLITE_PORT,
        ssl=ssl_ctx
    )

    try:
        for frag in FRAGMENTS:
            msg = f"FRAG {frag}\n"
            writer.write(msg.encode())
            await writer.drain()
            print(f"Repair request sent for {frag}")
            await asyncio.sleep(2)  # slow, visible behavior

        # stay connected so satellite can work
        while True:
            await asyncio.sleep(1)

    except (ConnectionResetError, BrokenPipeError):
        print("Connection closed by satellite")

    finally:
        writer.close()
        await writer.wait_closed()

async def main():
    await node_communication()

if __name__ == "__main__":
    asyncio.run(main())
