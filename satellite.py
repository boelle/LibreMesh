import asyncio
import ssl
import os
import socket
from datetime import datetime

HOST = "0.0.0.0"
PORT = 4001
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

connected_nodes = {}
repair_queue = []
notifications = []

MAX_NOTIFICATIONS = 10

# TLS context
ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
    print("TLS cert/key not found, generating self-signed certificate...")
    os.system(f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 "
              f"-keyout {KEY_FILE} -out {CERT_FILE} -subj '/CN=localhost'")
ssl_context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

def add_notification(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    notifications.append(f"{timestamp} - {msg}")
    if len(notifications) > MAX_NOTIFICATIONS:
        notifications.pop(0)
    print_table()

def print_table():
    os.system("clear")
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for node_id, info in connected_nodes.items():
        fragments = ",".join(info.get("fragments", []))
        print(f"{node_id:<15}{info['region']:<10}{info['rank']:<6}{info['uptime']:<10}{fragments}")
    if not connected_nodes:
        print()
    print("\n=== Repair Queue ===")
    if repair_queue:
        for idx, job in enumerate(repair_queue, 1):
            print(f"{idx}. {job}")
    else:
        print("No repair jobs queued.")
    print("======================================================================\n")
    print("=== Notifications (last 10) ===")
    for note in notifications:
        print(note)
    print("======================================================================")

async def handle_node(reader, writer):
    addr = writer.get_extra_info("peername")
    node_id = f"node{addr[1]}"
    connected_nodes[node_id] = {"region": "EU", "rank": 85, "uptime": 0, "fragments": [f"frag{i}" for i in range(1,6)]}
    add_notification(f"Node connected: {addr}")
    try:
        while True:
            data = await reader.read(100)
            if not data:
                break
            # For simplicity, echo back
            writer.write(data)
            await writer.drain()
    except:
        pass
    finally:
        writer.close()
        await writer.wait_closed()
        add_notification(f"Node disconnected: {addr}")
        connected_nodes.pop(node_id, None)

async def repair_worker():
    while True:
        if repair_queue:
            job = repair_queue.pop(0)
            add_notification(f"Processing repair for fragment {job}")
            await asyncio.sleep(10)  # slow down repair so it is visible
        else:
            await asyncio.sleep(1)

async def main():
    hostname = socket.gethostname()
    add_notification(f"Satellite listening on port {PORT}")
    add_notification(f"Hostname: {hostname}")
    os.system("clear")
    print_table()
    server = await asyncio.start_server(handle_node, HOST, PORT, ssl=ssl_context)
    asyncio.create_task(repair_worker())
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSatellite shutting down...")
