import asyncio
import random
import time
import ssl
import os
from collections import deque

# Set up directories and files
if not os.path.exists("cert.pem") or not os.path.exists("key.pem"):
    print("TLS cert/key not found, generating self-signed certificate...")
    os.system("openssl req -new -newkey rsa:2048 -days 365 -nodes -x509 -keyout key.pem -out cert.pem")

# Constants
MAX_REPAIR_QUEUE_SIZE = 5
MAX_NOTIFICATIONS = 10
REPAIR_DELAY = 10  # seconds

# Data structures
repair_queue = deque(maxlen=MAX_REPAIR_QUEUE_SIZE)
notifications = deque(maxlen=MAX_NOTIFICATIONS)
connected_nodes = set()

# Simulated node data
node_id = "node_test"
region = "EU"
rank = 85
uptime = 0
fragments = ["frag1", "frag2", "frag3", "frag4", "frag5"]

# Utility functions
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

async def handle_node_connection(reader, writer):
    global uptime
    node_address = writer.get_extra_info('peername')
    print(f"Node connected: {node_address}")

    connected_nodes.add(node_address)

    while True:
        data = await reader.read(100)
        message = data.decode()
        
        if message.startswith("repair"):
            fragment = message.split()[1]
            repair_queue.append(fragment)
            notifications.append(f"Repair job queued for fragment {fragment}")
            print(f"Repair job queued for fragment {fragment}")

        if message == "disconnect":
            break

        await asyncio.sleep(1)

    writer.close()
    await writer.wait_closed()
    connected_nodes.remove(node_address)
    notifications.append(f"Node disconnected: {node_address}")
    print(f"Node disconnected: {node_address}")

async def repair_worker():
    while True:
        if repair_queue:
            fragment = repair_queue.popleft()
            notifications.append(f"Processing repair for fragment {fragment}")
            print(f"Processing repair for fragment {fragment}")
            await asyncio.sleep(REPAIR_DELAY)  # Simulate repair delay
            notifications.append(f"Repair complete for fragment {fragment}")
            print(f"Repair complete for fragment {fragment}")
        await asyncio.sleep(1)

async def start_server():
    server = await asyncio.start_server(
        handle_node_connection, '0.0.0.0', 4001,
        ssl_context=ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    )
    print("Satellite listening on port 4001")

    async with server:
        await asyncio.gather(server.serve_forever(), repair_worker())

def display_status():
    clear_screen()

    print("=== Satellite Node Status ===")
    print(f"Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    print(f"{node_id:<15} {region:<10} {rank:<4} {uptime:<8} {', '.join(fragments)}")
    print("")

    print("=== Repair Queue ===")
    if repair_queue:
        for idx, fragment in enumerate(repair_queue, 1):
            print(f"{idx}. {fragment}")
    else:
        print("No repair jobs queued.")
    print("======================================================================")

    print("=== Notifications (last 10) ===")
    for notification in notifications:
        print(f"{time.strftime('%H:%M:%S')} - {notification}")
    print("======================================================================")

async def main():
    # Start server and handle repair worker
    await start_server()

if __name__ == "__main__":
    asyncio.run(main())
