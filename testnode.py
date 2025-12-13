import asyncio
import time
import json
import ssl

NODE_ID = "node_test"
FRAGMENTS = ["frag1", "frag2", "frag3", "frag4", "frag5"]
SATELLITE_HOST = "127.0.0.1"
SATELLITE_PORT = 4001
HEARTBEAT_INTERVAL = 5  # seconds

async def send_repair_request(writer, fragment):
    message = json.dumps({"type": "repair_request", "node_id": NODE_ID, "fragment": fragment})
    writer.write(message.encode() + b"\n")
    await writer.drain()
    print(f"Repair request sent for {fragment}")

async def send_heartbeat(writer, start_time):
    while True:
        uptime = int(time.time() - start_time)
        heartbeat = json.dumps({"type": "heartbeat", "node_id": NODE_ID, "uptime": uptime})
        writer.write(heartbeat.encode() + b"\n")
        await writer.drain()
        await asyncio.sleep(HEARTBEAT_INTERVAL)

async def node_communication():
    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    reader, writer = await asyncio.open_connection(
        SATELLITE_HOST, SATELLITE_PORT, ssl=ssl_context
    )

    start_time = time.time()

    # Start heartbeat task
    asyncio.create_task(send_heartbeat(writer, start_time))

    # Send repair requests for all fragments
    for fragment in FRAGMENTS:
        await send_repair_request(writer, fragment)
        await asyncio.sleep(1)  # stagger requests

    # Keep connection open
    while True:
        line = await reader.readline()
        if not line:
            print("Connection closed by satellite")
            break
        data = line.decode().strip()
        print(f"Satellite message: {data}")

async def main():
    try:
        await node_communication()
    except ConnectionResetError:
        print("Connection lost, retry later")
    except KeyboardInterrupt:
        print("Node stopped by user")

if __name__ == "__main__":
    asyncio.run(main())
