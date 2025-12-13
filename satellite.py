#!/usr/bin/env python3

import asyncio
import ssl
import os
import subprocess
import time
import socket
from collections import deque

PORT = 4001
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

REPAIR_DELAY = 10  # seconds
MAX_NOTIFICATIONS = 10

# -------------------- TLS --------------------

def ensure_tls_cert():
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return

    print("TLS cert/key not found, generating self-signed certificate...")
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:4096",
        "-keyout", KEY_FILE, "-out", CERT_FILE,
        "-days", "365", "-nodes",
        "-subj", "/CN=LibreMesh-Satellite"
    ], check=True)

# -------------------- Satellite State --------------------

class SatelliteState:
    def __init__(self):
        self.nodes = {}  # node_id -> info
        self.connected = set()
        self.repair_queue = asyncio.Queue()
        self.repairs_in_progress = set()
        self.lost_fragments = set()
        self.notifications = deque(maxlen=MAX_NOTIFICATIONS)
        self.start_time = time.time()

    def notify(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.notifications.append(f"{ts} - {msg}")

state = SatelliteState()

# -------------------- UI --------------------

def clear_screen():
    os.system("clear")

def render_ui():
    clear_screen()
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("-" * 70)

    now = int(time.time())
    for node_id, info in state.nodes.items():
        uptime = now - info["connected_at"]
        frags = ",".join(info["fragments"])
        print(f"{node_id:<15} {info['region']:<10} {info['rank']:<5} {uptime:<10} {frags}")

    print("\n=== Repair Queue ===")
    if state.repair_queue.empty():
        print("No repair jobs queued.")
    else:
        q = list(state.repair_queue._queue)
        for i, frag in enumerate(q, 1):
            print(f"{i}. {frag}")

    print("=" * 70)
    print("\n=== Notifications (last 10) ===")
    for n in state.notifications:
        print(n)
    print("=" * 70)

# -------------------- Repair Worker --------------------

async def repair_worker():
    while True:
        frag = await state.repair_queue.get()

        if frag not in state.lost_fragments:
            state.repair_queue.task_done()
            continue

        state.repairs_in_progress.add(frag)
        state.notify(f"Processing repair for fragment {frag}")
        render_ui()

        await asyncio.sleep(REPAIR_DELAY)

        state.lost_fragments.discard(frag)
        state.repairs_in_progress.discard(frag)

        state.notify(f"Repair completed for fragment {frag}")
        render_ui()

        state.repair_queue.task_done()

# -------------------- Network --------------------

async def handle_node(reader, writer):
    peer = writer.get_extra_info("peername")
    state.notify(f"Node connected: {peer}")
    render_ui()

    try:
        data = await reader.readline()
        msg = data.decode().strip()

        # expected: node_id,region,rank,frag1|frag2|...
        node_id, region, rank, frag_str = msg.split(",")
        fragments = frag_str.split("|")

        state.nodes[node_id] = {
            "region": region,
            "rank": int(rank),
            "fragments": fragments,
            "connected_at": int(time.time())
        }
        state.connected.add(node_id)

        # Simulate fragment loss once per fragment
        for frag in fragments:
            if frag not in state.lost_fragments and frag not in state.repairs_in_progress:
                state.lost_fragments.add(frag)
                await state.repair_queue.put(frag)
                state.notify(f"Repair job queued for fragment {frag}")

        render_ui()

        while True:
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
        state.notify(f"Node disconnected: {peer}")
        render_ui()
        writer.close()
        await writer.wait_closed()

# -------------------- Main --------------------

async def main():
    ensure_tls_cert()

    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(CERT_FILE, KEY_FILE)

    hostname = socket.gethostname()
    state.notify(f"Satellite listening on port {PORT}")
    state.notify(f"Hostname: {hostname}")

    server = await asyncio.start_server(
        handle_node, "0.0.0.0", PORT, ssl=ssl_context
    )

    asyncio.create_task(repair_worker())
    render_ui()

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
