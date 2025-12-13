import asyncio
import json
import ssl
import os
import subprocess
from typing import Dict, List

# ----------------------------
# Config / constants
# ----------------------------
SATELLITE_PORT = 4001
HEARTBEAT_INTERVAL = 5  # seconds for table updates
MAX_CONCURRENT_REPAIRS = 5
MAX_NOTIFICATIONS = 10
REPAIR_PROCESS_DELAY = 2  # seconds per repair job (slowed down for visibility)

CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

# ----------------------------
# TLS setup with auto cert generation
# ----------------------------
if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
    print("TLS cert/key not found, generating self-signed certificate...")
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", KEY_FILE, "-out", CERT_FILE, "-days", "365",
        "-subj", "/C=US/ST=State/L=City/O=LibreMesh/CN=localhost"
    ], check=True)
    print(f"Generated {CERT_FILE} and {KEY_FILE}")

ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

# ----------------------------
# Data models
# ----------------------------
class NodeInfo:
    def __init__(self, node_id: str, region: str):
        self.node_id = node_id
        self.region = region
        self.rank = 100
        self.online = True
        self.uptime = 0
        self.last_heartbeat = 0
        self.fragments: List[str] = []

class FragmentInfo:
    def __init__(self, fragment_id: str):
        self.fragment_id = fragment_id
        self.nodes: List[str] = []

# ----------------------------
# Satellite
# ----------------------------
class Satellite:
    def __init__(self):
        self.nodes: Dict[str, NodeInfo] = {}
        self.fragments: Dict[str, FragmentInfo] = {}
        self.repair_queue: asyncio.Queue = asyncio.Queue()
        self.notifications: List[str] = []
        self.lock = asyncio.Lock()

    async def handle_node(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        self.add_notification(f"Node connected: {addr}")
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                message = json.loads(data.decode())
                await self.process_message(message, writer)
        except Exception as e:
            self.add_notification(f"Error with node {addr}: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def process_message(self, message: dict, writer: asyncio.StreamWriter):
        msg_type = message.get("type")
        if msg_type == "heartbeat":
            await self.update_node(message)
        elif msg_type == "repair_request":
            await self.assign_repair(message)

    async def update_node(self, message: dict):
        node_id = message["node_id"]
        async with self.lock:
            if node_id not in self.nodes:
                self.nodes[node_id] = NodeInfo(node_id, message.get("region", "unknown"))
            node = self.nodes[node_id]
            node.uptime = message.get("uptime", node.uptime)
            node.rank = message.get("rank", node.rank)
            node.last_heartbeat = message.get("timestamp", node.last_heartbeat)
            node.fragments = message.get("fragments", node.fragments)

    async def assign_repair(self, message: dict):
        fragment_id = message["fragment_id"]
        async with self.lock:
            await self.repair_queue.put(fragment_id)
            self.add_notification(f"Repair job queued for fragment {fragment_id}")

    async def repair_worker(self):
        while True:
            fragment_id = await self.repair_queue.get()
            self.add_notification(f"Processing repair for fragment {fragment_id}")
            # Simulate repair processing delay
            await asyncio.sleep(REPAIR_PROCESS_DELAY)
            self.repair_queue.task_done()

    def add_notification(self, msg: str):
        self.notifications.append(msg)
        if len(self.notifications) > MAX_NOTIFICATIONS:
            self.notifications.pop(0)

    def print_ascii_table(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        print("\n=== Satellite Node Status ===")
        if not self.nodes:
            print("No nodes connected.")
        else:
            print(f"{'Node ID':<15} {'Region':<10} {'Rank':<5} {'Uptime':<10} {'Fragments':<20}")
            print("-" * 70)
            for node in self.nodes.values():
                uptime_str = str(node.uptime)
                fragments_str = ",".join(node.fragments)
                print(f"{node.node_id:<15} {node.region:<10} {node.rank:<5} {uptime_str:<10} {fragments_str:<20}")
        print("\n=== Repair Queue ===")
        if self.repair_queue.empty():
            print("No repair jobs queued.")
        else:
            queued = list(self.repair_queue._queue)
            for frag in queued:
                print(f"Fragment: {frag}")
        print("=" * 70)
        # Print last notifications
        print("\n=== Notifications (last 10) ===")
        if not self.notifications:
            print("No notifications.")
        else:
            for note in self.notifications:
                print(note)
        print("=" * 70)

    async def display_ascii_table(self):
        while True:
            async with self.lock:
                self.print_ascii_table()
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def start_server(self):
        server = await asyncio.start_server(
            self.handle_node, '0.0.0.0', SATELLITE_PORT, ssl=ssl_context
        )
        print(f"Satellite listening on port {SATELLITE_PORT}")
        async with server:
            await server.serve_forever()

# ----------------------------
# Main
# ----------------------------
async def main():
    satellite = Satellite()
    for _ in range(MAX_CONCURRENT_REPAIRS):
        asyncio.create_task(satellite.repair_worker())
    asyncio.create_task(satellite.display_ascii_table())
    await satellite.start_server()

if __name__ == "__main__":
    asyncio.run(main())
