import asyncio
import ssl
import socket
import time

SAT_HOST = "127.0.0.1"
SAT_PORT = 4001
NODE_ID = "node_test"
REGION = "EU"
FRAGMENTS = [f"frag{i}" for i in range(1,6)]

ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

uptime_start = time.time()

async def node_client():
    reader, writer = await asyncio.open_connection(SAT_HOST, SAT_PORT, ssl=ssl_context)
    addr = writer.get_extra_info("sockname")
    print(f"Connected to satellite from {addr}")

    try:
        while True:
            uptime = int(time.time() - uptime_start)
            heartbeat = f"{NODE_ID}|{REGION}|{uptime}|{','.join(FRAGMENTS)}"
            writer.write(heartbeat.encode())
            await writer.drain()
            await asyncio.sleep(5)  # send heartbeat every 5 seconds

            # Read satellite messages if any (for demo/testing)
            try:
                data = await asyncio.wait_for(reader.read(100), timeout=0.1)
                if data:
                    print(f"Received from satellite: {data.decode()}")
            except asyncio.TimeoutError:
                pass
    except KeyboardInterrupt:
        print("\nNode shutting down...")
    finally:
        writer.close()
        await writer.wait_closed()

if __name__ == "__main__":
    asyncio.run(node_client())
