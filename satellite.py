import asyncio
import ssl
import os
import time
import socket
from collections import deque

PORT = 4001
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

# ---- state ----
nodes = {}
repair_queue = deque()
repair_state = {}  # frag -> queued | repairing | done
notifications = deque(maxlen=10)

# ---- helpers ----
def notify(msg):
    ts = time.strftime("%H:%M:%S")
    notifications.append(f"{ts} - {msg}")

def clear_screen():
    print("\033[2J\033[H", end="")

def render_table():
    clear_screen()
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("-" * 70)

    now = time.time()
    for node_id, n in nodes.items():
        uptime = int(now - n["start"])
        frags = ",".join(n["fragments"])
        print(f"{node_id:<15} {n['region']:<9} {n['rank']:<5} {uptime:<10} {frags}")

    print("\n=== Repair Queue ===")
    if not repair_queue:
        print("No repair jobs queued.")
    else:
        for i, frag in enumerate(repair_queue, 1):
            print(f"{i}. {frag}")

    print("=" * 70)
    print("\n=== Notifications (last 10) ===")
    for n in notifications:
        print(n)
    print("=" * 70)

# ---- TLS ----
def ensure_cert():
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return
    notify("Generating self-signed TLS certificate")
    os.system(
        f"openssl req -x509 -newkey rsa:2048 -keyout {KEY_FILE} "
        f"-out {CERT_FILE} -days 365 -nodes -subj '/CN=LibreMesh'"
    )

# ---- repair worker ----
async def repair_worker():
    while True:
        if repair_queue:
            frag = repair_queue.popleft()
            repair_state[frag] = "repairing"
            notify(f"Processing repair for fragment {frag}")
            render_table()

            await asyncio.sleep(10)  # slow on purpose

            repair_state[frag] = "done"
            notify(f"Repair completed for fragment {frag}")
            render_table()

        await asyncio.sleep(1)

# ---- node handler ----
async def handle_node(reader, writer):
    addr = writer.get_extra_info("peername")
    node_id = f"node{addr[1]}"

    nodes[node_id] = {
        "region": "EU",
        "rank": 85,
        "start": time.time(),
        "fragments": []
    }

    notify(f"Node connected: {addr}")
    render_table()

    try:
        while True:
            data = await reader.readline()
            if not data:
                break

            msg = data.decode().strip()
            if msg.startswith("FRAG"):
                _, frag = msg.split()
                nodes[node_id]["fragments"].append(frag)

                if frag not in repair_state:
                    repair_state[frag] = "queued"
                    repair_queue.append(frag)
                    notify(f"Repair job queued for fragment {frag}")
                    render_table()

    finally:
        notify(f"Node disconnected: {addr}")
        nodes.pop(node_id, None)
        render_table()
        writer.close()
        await writer.wait_closed()

# ---- main ----
async def main():
    ensure_cert()

    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_ctx.load_cert_chain(CERT_FILE, KEY_FILE)

    server = await asyncio.start_server(
        handle_node,
        host="0.0.0.0",
        port=PORT,
        ssl=ssl_ctx
    )

    notify(f"Satellite listening on port {PORT}")
    notify(f"Hostname: {socket.gethostname()}")
    render_table()

    asyncio.create_task(repair_worker())

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
