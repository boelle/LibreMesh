import asyncio
import random
import time

# Simulate a node interacting with the satellite

async def send_repair_request(writer, fragment):
    message = f"repair {fragment}\n"
    writer.write(message.encode())
    await writer.drain()

async def node_communication():
    reader, writer = await asyncio.open_connection('127.0.0.1', 4001)

    # Simulate some random fragments being repaired
    for _ in range(5):
        fragment = f"frag{random.randint(1, 5)}"
        await send_repair_request(writer, fragment)
        print(f"Repair request sent for {fragment}")
        await asyncio.sleep(2)  # Wait 2 seconds between requests

    # Simulate disconnection
    writer.write(b"disconnect\n")
    await writer.drain()
    writer.close()
    await writer.wait_closed()
    print("Node disconnected")

async def main():
    await node_communication()

if __name__ == "__main__":
    asyncio.run(main())
