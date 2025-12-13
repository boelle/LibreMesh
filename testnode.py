import asyncio

SATELLITE_HOST = '127.0.0.1'
SATELLITE_PORT = 4001
NODE_ID = "node_test"
REGION = "EU"
FRAGMENTS = [f"frag{i}" for i in range(1, 6)]
HEARTBEAT_INTERVAL = 30  # seconds

async def send_heartbeat(writer):
    uptime = 0
    while True:
        message = f"HEARTBEAT:{NODE_ID}:{REGION}:{uptime}\n"
        try:
            writer.write(message.encode())
            await writer.drain()
        except Exception as e:
            print(f"Connection lost while sending heartbeat: {e}")
            break
        uptime += HEARTBEAT_INTERVAL
        await asyncio.sleep(HEARTBEAT_INTERVAL)

async def send_repair_request(writer, fragment):
    try:
        message = f"REPAIR_REQUEST:{fragment}\n"
        writer.write(message.encode())
        await writer.drain()
        print(f"Repair request sent for {fragment}")
    except Exception as e:
        print(f"Failed to send repair request for {fragment}: {e}")

async def node_communication():
    while True:
        try:
            reader, writer = await asyncio.open_connection(SATELLITE_HOST, SATELLITE_PORT)
            print(f"Connected to satellite {SATELLITE_HOST}:{SATELLITE_PORT}")

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(send_heartbeat(writer))

            # Send initial repair requests
            for frag in FRAGMENTS:
                await send_repair_request(writer, frag)
                await asyncio.sleep(1)  # stagger slightly so queue is visible

            # Keep connection alive
            await heartbeat_task

        except Exception as e:
            print(f"Connection lost, retry later: {e}")
            await asyncio.sleep(5)  # retry after delay

async def main():
    await node_communication()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nNode shutting down.")
