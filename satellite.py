import asyncio
import os
import ssl
import socket
import time
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

CERTFILE = "cert.pem"
KEYFILE = "key.pem"
PORT = 4001
REPAIR_DELAY = 10  # seconds

connected_nodes = {}
repair_queue = []
notifications = []

MAX_NOTIFICATIONS = 10

def log_notification(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    notifications.append(f"{timestamp} - {msg}")
    if len(notifications) > MAX_NOTIFICATIONS:
        notifications.pop(0)

def print_table():
    os.system("clear")
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for node_id, info in connected_nodes.items():
        fragments = ",".join(info["fragments"])
        print(f"{node_id:<15}{info['region']:<10}{info['rank']:<6}{info['uptime']:<10}{fragments}")
    print("\n=== Repair Queue ===")
    if repair_queue:
        for i, frag in enumerate(repair_queue, 1):
            print(f"{i}. {frag}")
    else:
        print("No repair jobs queued.")
    print("="*70)
    print("\n=== Notifications (last 10) ===")
    for n in notifications:
        print(n)
    print("="*70)

async def process_repair_queue():
    while True:
        if repair_queue:
            frag = repair_queue.pop(0)
            log_notification(f"Processing repair for fragment {frag}")
            print_table()
            await asyncio.sleep(REPAIR_DELAY)
        else:
            await asyncio.sleep(1)

async def handle_node(reader, writer):
    addr = writer.get_extra_info('peername')
    log_notification(f"Node connected: {addr}")

    # Add node with default info
    node_id = f"node{addr[1]}"
    connected_nodes[node_id] = {
        "region": "EU",
        "rank": 85,
        "uptime": 0,
        "fragments": [f"frag{i}" for i in range(1,6)],
        "public_key": None  # Placeholder
    }

    print_table()

    try:
        while True:
            data = await reader.read(1024)
            if not data:
                break

            if data.startswith(b"REPAIR:"):
                frag = data.decode().split(":")[1]
                repair_queue.append(frag)
                log_notification(f"Repair job queued for fragment {frag}")

            elif data.startswith(b"HEARTBEAT:"):
                parts = data.split(b"|")
                heartbeat_data = parts[0].decode()
                signature = parts[1]
                # TODO: Verify signature here if public key is known
                _, hb_node_id, region, uptime = heartbeat_data.split(":")
                uptime = int(uptime)
                if hb_node_id in connected_nodes:
                    connected_nodes[hb_node_id]["uptime"] = uptime
                else:
                    connected_nodes[hb_node_id] = {
                        "region": region,
                        "rank": 85,
                        "uptime": uptime,
                        "fragments": [],
                        "public_key": None
                    }

            print_table()

    except Exception as e:
        log_notification(f"Node error: {e}")

    finally:
        log_notification(f"Node disconnected: {addr}")
        connected_nodes.pop(node_id, None)
        print_table()
        writer.close()
        await writer.wait_closed()

async def start_server():
    if not os.path.exists(CERTFILE) or not os.path.exists(KEYFILE):
        print("TLS cert/key not found, generating self-signed certificate...")
        os.system(f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout {KEYFILE} -out {CERTFILE} -subj '/CN=localhost'")

    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile=CERTFILE, keyfile=KEYFILE)

    server = await asyncio.start_server(handle_node, '0.0.0.0', PORT, ssl=ssl_context)
    log_notification(f"Satellite listening on port {PORT}")
    print_table()

    async with server:
        await asyncio.gather(server.serve_forever(), process_repair_queue())

async def main():
    await start_server()

if __name__ == "__main__":
    asyncio.run(main())
