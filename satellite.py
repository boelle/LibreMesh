import asyncio
import ssl
import os
import datetime

PORT = 4001
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

connected_nodes = {}
repair_queue = []
notifications = []

MAX_NOTIFICATIONS = 10

# Ensure TLS certificate exists
if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
    print("TLS cert/key not found, generating self-signed certificate...")
    os.system(f"openssl req -x509 -newkey rsa:2048 -nodes -keyout {KEY_FILE} -out {CERT_FILE} -days 365 -subj '/CN=localhost'")

ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

def add_notification(message):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    notifications.append(f"{timestamp} - {message}")
    if len(notifications) > MAX_NOTIFICATIONS:
        notifications.pop(0)

def print_table():
    os.system('clear')
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for node_id, node_info in connected_nodes.items():
        fragments_str = ",".join(node_info["fragments"])
        print(f"{node_id:<15}{node_info['region']:<10}{node_info['rank']:<6}{node_info['uptime']:<10}{fragments_str}")
    print("\n=== Repair Queue ===")
    if repair_queue:
        for idx, frag in enumerate(repair_queue, 1):
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
    add_notification(f"Node connected: {addr}")
    node_id = f"node{addr[1]}"
    connected_nodes[node_id] = {
        "region": "EU",
        "rank": 85,
        "uptime": 0,
        "fragments": [f"frag{i}" for i in range(1, 6)]
    }
    print_table()
    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            message = data.decode().strip()
            if message.startswith("HEARTBEAT"):
                parts = message.split(":")
                node_id = parts[1]
                region = parts[2]
                uptime = int(parts[3])
                if node_id not in connected_nodes:
                    connected_nodes[node_id] = {
                        "region": region,
                        "rank": 85,
                        "uptime": uptime,
                        "fragments": [f"frag{i}" for i in range(1,6)]
                    }
                else:
                    connected_nodes[node_id]["uptime"] = uptime
                    connected_nodes[node_id]["region"] = region
                print_table()
            elif message.startswith("REPAIR_REQUEST"):
                frag = message.split(":")[1]
                repair_queue.append(frag)
                add_notification(f"Repair job queued for fragment {frag}")
                print_table()
    except Exception as e:
        add_notification(f"Error with node {addr}: {e}")
    finally:
        add_notification(f"Node disconnected: {addr}")
        connected_nodes.pop(node_id, None)
        print_table()
        writer.close()
        await writer.wait_closed()

async def repair_worker():
    while True:
        if repair_queue:
            frag = repair_queue.pop(0)
            add_notification(f"Processing repair for fragment {frag}")
            print_table()
            await asyncio.sleep(10)  # slow repair so you can see it
        else:
            await asyncio.sleep(1)

async def start_server():
    server = await asyncio.start_server(handle_node, '0.0.0.0', PORT, ssl=ssl_context)
    add_notification(f"Satellite listening on port {PORT}")
    print_table()
    async with server:
        await asyncio.gather(server.serve_forever(), repair_worker())

async def main():
    await start_server()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSatellite shutting down.")
