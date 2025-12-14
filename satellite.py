import asyncio
import ssl
import os
import time
import socket
from collections import deque

PORT = 4001
REPAIR_DELAY = 10  # seconds
MAX_NOTIFICATIONS = 10

nodes = {}  # node_id -> dict
connections = {}  # writer -> node_id
repair_queue = asyncio.Queue()
notifications = deque(maxlen=MAX_NOTIFICATIONS)

# --------------------------------------------------
def notify(msg):
    ts = time.strftime("%H:%M:%S")
    notifications.append(f"{ts} - {msg}")

# --------------------------------------------------
def clear_screen():
    os.system("clear")

def render_table():
    clear_screen()

    print("=== Satellite Node Status ===")
    print(f"{'Node ID':15} {'Region':10} {'Rank':5} {'Uptime':10} Fragments")
    print("-" * 70)

    for node_id, n in nodes.items():
        frags = ",".join(sorted(n["fragments"]))
        print(f"{node_id:15} {n['region']:10} {n['rank']:5} {n['uptime']:10} {frags}")

    print("\n=== Repair Queue ===")
    if repair_queue.empty():
        print("No repair jobs queued.")
    else:
        for i, item in enumerate(list(repair_queue._queue), 1):
            print(f"{i}. {item}")

    print("=" * 70)
    print("\n=== Notifications (last 10) ===")
    for n in notifications:
        print(n)
    print("=" * 70)

# --------------------------------------------------
async def repair_worker():
    while True:
        fragment = await repair_queue.get()
        notify(f"Processing repair for fragment {fragment}")
        await asyncio.sleep(REPAIR_DELAY)
        repair_queue.task_done()

# --------------------------------------------------
async def handle_client(reader, writer):
    peer = writer.get_extra_info("peername")

    try:
        while True:
            data = await reader.readline()
            if not data:
                break

            msg = data.decode().strip()

            if msg.startswith("IDENT:"):
                _, node_id, region, pubkey = msg.split(":", 3)

                if node_id not in nodes:
                    nodes[node_id] = {
                        "region": region,
                        "rank": 85,
                        "uptime": 0,
                        "last_hb": time.time(),
                        "fragments": set(),
                    }
                    notify(f"Node registered: {node_id}")

                connections[writer] = node_id

            elif msg.startswith("HEARTBEAT:"):
                _, node_id, region, uptime = msg.split(":")

                if node_id in nodes:
                    nodes[node_id]["uptime"] = int(uptime)
                    nodes[node_id]["last_hb"] = time.time()

            elif msg.startswith("REPAIR:"):
                _, node_id, fragment = msg.split(":", 2)

                if node_id in nodes:
                    if fragment not in nodes[node_id]["fragments"]:
                        nodes[node_id]["fragments"].add(fragment)
                        await repair_queue.put(fragment)
                        notify(f"Repair job queued for fragment {fragment}")

    except Exception as e:
        notify(f"Connection error: {e}")

    finally:
        node_id = connections.pop(writer, None)
        if node_id:
            notify(f"Node disconnected: {node_id}")
        writer.close()
        await writer.wait_closed()

# --------------------------------------------------
async def ui_loop():
    while True:
        render_table()
        await asyncio.sleep(1)

# --------------------------------------------------
async def main():
    hostname = socket.gethostname()
    notify(f"Satellite listening on port {PORT}")
    notify(f"Hostname: {hostname}")

    ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    if not os.path.exists("cert.pem") or not os.path.exists("key.pem"):
        notify("TLS cert/key missing")
        raise RuntimeError("cert.pem/key.pem required")

    ssl_ctx.load_cert_chain("cert.pem", "key.pem")

    server = await asyncio.start_server(
        handle_client, "0.0.0.0", PORT, ssl=ssl_ctx
    )

    asyncio.create_task(repair_worker())
    asyncio.create_task(ui_loop())

    async with server:
        await server.serve_forever()

# --------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
