#!/usr/bin/env python3
import asyncio
import ssl
import os
import subprocess
import time
from collections import deque

PORT = 4001
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

# -------------------- TLS --------------------

def ensure_tls_cert():
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return
    print("TLS cert/key not found, generating self-signed certificate...")
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", KEY_FILE, "-out", CERT_FILE,
        "-days", "365", "-nodes",
        "-subj", "/CN=libremesh-satellite"
    ], check=True)
    print("Generated cert.pem and key.pem")

# -------------------- State --------------------

nodes = {}  # node_id -> dict
repair_queue = asyncio.Queue()
notifications = deque(maxlen=10)

START_TIME = time.time()

# -------------------- UI --------------------

def clear_screen():
    os.system("clear")

def notify(msg):
    ts = time.strftime("%H:%M:%S")
    notifications.append(f"{ts} - {msg}")

def render_table():
    clear_screen()
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for nid, n in nodes.items():
        uptime = int(n["uptime"])
        frags = ",".join(sorted(n["fragments"]))
        print(f"{nid:<15} {n['region']:<10} {n['rank']:<5} {uptime:<10} {frags}")
    print()
    print("=== Repair Queue ===")
    if repair_queue.qsize() == 0:
        print("No repair jobs queued.")
    else:
        for i, item in enumerate(list(repair_queue._queue), 1):
            print(f"{i}. {item}")
    print("=" * 70)
    print()
    print("=== Notifications (last 10) ===")
    for n in notifications:
        print(n)
    print("=" * 70)

# -------------------- Protocol --------------------

async def handle_node(reader, writer):
    peer = writer.get_extra_info("peername")
    node_id = None

    try:
        while True:
            data = await reader.readline()
            if not data:
                break

            msg = data.decode().strip()
            parts = msg.split()

            if parts[0] == "HELLO":
                node_id = parts[1]
                region = parts[2]
                fragments = set(parts[3].split(","))

                nodes[node_id] = {
                    "region": region,
                    "rank": 85,
                    "uptime": 0,
                    "last_heartbeat": time.time(),
                    "fragments": fragments,
                }
                notify(f"Node connected: {node_id}")

            elif parts[0] == "HEARTBEAT":
                if node_id in nodes:
                    now = time.time()
                    last = nodes[node_id]["last_heartbeat"]
                    nodes[node_id]["uptime"] += max(0, now - last)
                    nodes[node_id]["last_heartbeat"] = now

            elif parts[0] == "REPAIR":
                fragment = parts[1]
                await repair_queue.put(fragment)
                notify(f"Repair job queued for fragment {fragment}")

    finally:
        if node_id and node_id in nodes:
            notify(f"Node disconnected: {node_id}")
            del nodes[node_id]
        writer.close()
        await writer.wait_closed()

# -------------------- Repair Worker --------------------

async def repair_worker():
    while True:
        fragment = await repair_queue.get()
        notify(f"Processing repair for fragment {fragment}")
        await asyncio.sleep(10)  # slow on purpose
        repair_queue.task_done()

# -------------------- Server --------------------

async def start_server():
    ensure_tls_cert()

    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(CERT_FILE, KEY_FILE)

    server = await asyncio.start_server(
        handle_node, "0.0.0.0", PORT, ssl=ssl_ctx
    )

    notify(f"Satellite listening on port {PORT}")
    notify(f"Hostname: {os.uname().nodename}")

    async with server:
        await server.serve_forever()

# -------------------- UI Loop --------------------

async def ui_loop():
    while True:
        render_table()
        await asyncio.sleep(1)

# -------------------- Main --------------------

async def main():
    await asyncio.gather(
        start_server(),
        repair_worker(),
        ui_loop(),
    )

if __name__ == "__main__":
    asyncio.run(main())
