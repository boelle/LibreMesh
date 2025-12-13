import asyncio
import socket
import time

SATELLITE_HOST = "127.0.0.1"
SATELLITE_PORT = 4001
HEARTBEAT_INTERVAL = 30  # seconds
NODE_ID = "node_test"
REGION = "EU"
FRAGMENTS = ["frag1", "frag2", "frag3", "frag4", "frag5"]

async def send_heartbeat(writer):
    heartbeat_msg = f"HEARTBEAT:{NODE_ID}:{REGION}:{int(time.time())}\n"
    writer.write(heartbeat_msg.encode())
    await writer.drain()
    print(f"Heartbeat sent: {heartbeat_msg.strip()}")

async def send_repair_request(writer, fragment):
    msg = f"REPAIR:{fragment}\n"
    writer.write(msg.encode())
    await writer.drain()
    print(f"Repair request sent for {fragment}")

async def node_communication():
    while True:
        try:
            reader, writer = await asyncio.open_connection(SATELLITE_HOST, SATELLITE_PORT)
            print(f"Connected to satellite {SATELLITE_HOST}:{SATELLITE_PORT}")

            # Send all repair requests initially
            for frag in FRAGMENTS:
                await send_repair_request(writer, frag)

            # Heartbeat loop
            while True:
                await send_heartbeat(writer)
                await asyncio.sleep(HEARTBEAT_INTERVAL)

        except (ConnectionRefusedError, ConnectionResetError, socket.gaierror):
            print("Connection lost, retry later")
            await asyncio.sleep(5)  # wait before reconnect
        except asyncio.CancelledError:
            writer.close()
            await writer.wait_closed()
            break

async def main():
    await node_communication()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Node shutdown requested")
