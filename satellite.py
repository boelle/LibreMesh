import asyncio
import ssl
import os
from datetime import datetime

HOST = '0.0.0.0'
PORT = 4001
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

connected_nodes = {}  # node_id -> {'region': ..., 'rank': ..., 'uptime': ..., 'fragments': [...]}
repair_queue = []
notifications = []

MAX_NOTIFICATIONS = 10
REPAIR_DELAY = 10  # seconds


def log_notification(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    notifications.append(f"{timestamp} - {message}")
    if len(notifications) > MAX_NOTIFICATIONS:
        notifications.pop(0)


def print_table():
    os.system('clear')
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for node_id, info in connected_nodes.items():
        frag_list = ",".join(info['fragments'])
        print(f"{node_id:<14}{info['region']:<11}{info['rank']:<6}{info['uptime']:<10}{frag_list}")
    print("\n=== Repair Queue ===")
    if repair_queue:
        for idx, frag in enumerate(repair_queue, 1):
            print(f"{idx}. {frag}")
    else:
        print("No repair jobs queued.")
    print("="*70)
    print("\n=== Notifications (last 10) ===")
    for note in notifications:
        print(note)
    print("="*70)


async def handle_node(reader, writer):
    addr = writer.get_extra_info('peername')
    log_notification(f"Node connected: {addr}")

    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            message = data.decode().strip()
            # Expecting heartbeat messages like: HEARTBEAT node_id uptime
            if message.startswith("HEARTBEAT"):
                parts = message.split()
                node_id = parts[1]
                uptime = int(parts[2])
                if node_id not in connected_nodes:
                    # Initialize node info
                    connected_nodes[node_id] = {
                        'region': 'EU',
                        'rank': 85,
                        'uptime': uptime,
                        'fragments': [f"frag{i}" for i in range(1, 6)]
                    }
                else:
                    connected_nodes[node_id]['uptime'] = uptime
                print_table()
            elif message.startswith("REPAIR"):
                fragment = message.split()[1]
                repair_queue.append(fragment)
                log_notification(f"Repair job queued for fragment {fragment}")
                print_table()
                # Schedule actual repair
                asyncio.create_task(process_repair(fragment))
    except Exception as e:
        log_notification(f"Error with node {addr}: {e}")
    finally:
        log_notification(f"Node disconnected: {addr}")
        print_table()
        writer.close()
        await writer.wait_closed()


async def process_repair(fragment):
    await asyncio.sleep(REPAIR_DELAY)
    if fragment in repair_queue:
        log_notification(f"Processing repair for fragment {fragment}")
        repair_queue.remove(fragment)
        print_table()


async def start_server():
    if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
        log_notification("TLS cert/key not found, generating self-signed certificate...")
        os.system(f"openssl req -new -x509 -days 365 -nodes -out {CERT_FILE} -keyout {KEY_FILE} -subj '/CN=localhost'")

    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

    server = await asyncio.start_server(handle_node, HOST, PORT, ssl=ssl_context)
    log_notification(f"Satellite listening on port {PORT}")
    print_table()

    async with server:
        await server.serve_forever()


async def main():
    await start_server()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Satellite shutting down...")
