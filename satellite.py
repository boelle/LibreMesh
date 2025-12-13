import asyncio
import json
import ssl
from typing import Dict, List, Tuple

# ----------------------------
# Config / constants
# ----------------------------
SATELLITE_PORT = 4001
METADATA_FILE = "metadata.json"
HEARTBEAT_INTERVAL = 30  # seconds
MAX_CONCURRENT_REPAIRS = 5

# TLS context
ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")


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
        self.nodes: List[str] = []  # node_ids holding this fragment

# ----------------------------
# Satellite
# ----------------------------
class Satellite:
    def __init__(self):
        self.nodes: Dict[str, NodeInfo] = {}
        self.fragments: Dict[str, FragmentInfo] = {}
        self.repair_queue: asyncio.Queue = asyncio.Queue()
        self.lock = asyncio.Lock()

    async def handle_node(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        print(f"Node connected: {addr}")
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                message = json.loads(data.decode())
                await self.process_message(message, writer)
        except Exception as e:
            print(f"Error with node {addr}: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def process_message(self, message: dict, writer: asyncio.StreamWriter):
        msg_type = message.get("type")
        if msg_type == "heartbeat":
            await self.update_node(message)
        elif msg_type == "repair_request":
            await self.assign_repair(message)
        # more message types can be added here

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
            print(f"Repair job queued for fragment {fragment_id}")

    async def repair_worker(self):
        while True:
            fragment_id = await self.repair_queue.get()
            print(f"Processing repair for fragment {fragment_id}")
            # logic to assign repair to repair nodes here
            await asyncio.sleep(0.1)  # placeholder
            self.repair_queue.task_done()

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
    # Start repair workers
    for _ in range(MAX_CONCURRENT_REPAIRS):
        asyncio.create_task(satellite.repair_worker())
    # Start server
    await satellite.start_server()

if __name__ == "__main__":
    asyncio.run(main())
