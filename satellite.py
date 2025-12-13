import asyncio
import ssl
import os
import json
from datetime import datetime

HOST = '0.0.0.0'
PORT = 4001
CERT_FILE = 'cert.pem'
KEY_FILE = 'key.pem'
ACK_FILE = 'acks.json'

connected_nodes = []
repair_queue = []
notifications = []

ACKED_FRAGMENTS = {}

# Load ACKed fragments from disk
if os.path.exists(ACK_FILE):
    with open(ACK_FILE, 'r') as f:
        ACKED_FRAGMENTS = json.load(f)

def save_acks():
    with open(ACK_FILE, 'w') as f:
        json.dump(ACKED_FRAGMENTS, f)

def notify(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    notifications.append(f"{timestamp} - {message}")
    if len(notifications) > 10:
        notifications.pop(0)
    display_table()

def display_table():
    os.system('clear')
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for node in connected_nodes:
        node_id = node['id']
        region = node['region']
        rank = node['rank']
        uptime = node['uptime']
        fragments = ','.join(node['fragments'])
        print(f"{node_id:<15}{region:<10}{rank:<6}{uptime:<10}{fragments}")
    print("\n=== Repair Queue ===")
    if repair_queue:
        for idx, frag in enumerate(repair_queue, start=1):
            print(f"{idx}. {frag}")
    else:
        print("No repair jobs queued.")
    print("======================================================================")
    print("\n=== Notifications (last 10) ===")
    for note in notifications:
        print(note)
    print("======================================================================")

async def handle_node(reader, writer):
    addr = writer.get_extra_info('peername')
    connected_nodes.append({
        'id': f"node{addr[1]}",
        'region': 'EU',
        'rank': 85,
        'uptime': 0,
        'fragments': [f"frag{i}" for i in range(1,6)]
    })
    notify(f"Node connected: {addr}")

    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            msg = data.decode().strip()
            if msg.startswith("REPAIR"):
                frag_id = msg.split()[1]
                if frag_id not in ACKED_FRAGMENTS:
                    repair_queue.append(frag_id)
                    notify(f"Repair job queued for fragment {frag_id}")
            await asyncio.sleep(0.1)
    except ConnectionResetError:
        pass
    finally:
        notify(f"Node disconnected: {addr}")
        connected_nodes[:] = [n for n in connected_nodes if n['id'] != f"node{addr[1]}"]
        writer.close()
        await writer.wait_closed()

async def process_repairs():
    while True:
        if repair_queue:
            frag = repair_queue.pop(0)
            notify(f"Processing repair for fragment {frag}")
            await asyncio.sleep(10)  # slow down for visibility
            ACKED_FRAGMENTS[frag] = datetime.now().isoformat()
            save_acks()
        await asyncio.sleep(0.1)

async def start_server():
    if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
        print("TLS cert/key not found, generating self-signed certificate...")
        os.system(f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout {KEY_FILE} -out {CERT_FILE} -subj '/CN=localhost'")
        print("Generated cert.pem and key.pem")

    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

    server = await asyncio.start_server(
        handle_node,
        HOST,
        PORT,
        ssl=ssl_context
    )
    notify(f"Satellite listening on port {PORT}")
    await asyncio.gather(server.serve_forever(), process_repairs())

async def main():
    await start_server()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down satellite.")
