import asyncio
import ssl
import os
import time
from collections import deque

PORT = 4001
REPAIR_DELAY = 10  # seconds

# ---------------------------------------------------------------------
# TLS setup
# ---------------------------------------------------------------------
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
    print("TLS cert/key not found, generating self-signed certificate...")
    os.system(
        "openssl req -x509 -newkey rsa:2048 -nodes "
        "-keyout key.pem -out cert.pem -days 365 "
        "-subj '/CN=libremesh-satellite'"
    )

ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_ctx.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

# ---------------------------------------------------------------------
# State
# ---------------------------------------------------------------------
connected_nodes = {}
repair_queue = deque()
notifications = deque(maxlen=10)

start_time = time.time()

# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------
def clear_screen():
    os.system("clear")

def uptime_seconds():
    return int(time.time() - start_time)

def render():
    clear_screen()

    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for nid, n in connected_nodes.items():
        print(
            f"{nid:<15} {n['region']:<10} {n['rank']:<4} "
            f"{uptime_seconds():<10} {','.join(n['fragments'])}"
        )
    print()

    print("=== Repair Queue ===")
    if repair_queue:
        for i, frag in enumerate(repair_queue, 1):
            print(f"{i}. {frag}")
    else:
        print("No repair jobs queued.")
    print("======================================================================")
    print()
    print("=== Notifications (last 10) ===")
    for n in notifications:
        print(n)
    print("======================================================================")

# ---------------------------------------------------------------------
# Network handlers
# ---------------------------------------------------------------------
async def handle_node(reader, writer):
    addr = writer.get_extra_info("peername")
    node_id = f"node{addr[1]}"

    connected_nodes[node_id] = {
        "region": "EU",
        "rank": 85,
        "fragments": []
    }

    notifications.append(f"{time.strftime('%H:%M:%S')} - Node connected: {addr}")

    try:
        while True:
            data = await reader.readline()
            if not data:
                break

            msg = data.decode().strip()

            if msg.startswith("FRAG"):
                frag = msg.split()[1]
                connected_nodes[node_id]["fragments"].append(frag)
                repair_queue.append(frag)
                notifications.append(
                    f"{time.strftime('%H:%M:%S')} - Repair job queued for fragment {frag}"
                )

            render()
    finally:
        connected_nodes.pop(node_id, None)
        notifications.append(f"{time.strftime('%H:%M:%S')} - Node disconnected: {addr}")
        render()
        writer.close()
        await writer.wait_closed()

# ---------------------------------------------------------------------
# Repair worker
# ---------------------------------------------------------------------
async def repair_worker():
    while True:
        if repair_queue:
            frag = repair_queue.popleft()
            notifications.append(
                f"{time.strftime('%H:%M:%S')} - Processing repair for fragment {frag}"
            )
            render()
            await asyncio.sleep(REPAIR_DELAY)
        await asyncio.sleep(1)

# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
async def main():
    server = await asyncio.start_server(
        handle_node,
        host="0.0.0.0",
        port=PORT,
        ssl=ssl_ctx   # <-- FIX IS HERE
    )

    notifications.append(f"{time.strftime('%H:%M:%S')} - Satellite listening on port {PORT}")
    notifications.append(f"{time.strftime('%H:%M:%S')} - Hostname: {os.uname().nodename}")
    render()

    async with server:
        await asyncio.gather(
            server.serve_forever(),
            repair_worker()
        )

if __name__ == "__main__":
    asyncio.run(main())
