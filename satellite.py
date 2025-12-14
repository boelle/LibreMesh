#!/usr/bin/env python3
import asyncio
import ssl
import os
import time
import hashlib
from collections import deque
from dataclasses import dataclass, field
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

HOST = "0.0.0.0"
PORT = 4001

ORIGIN_PRIV = "origin_privkey.bin"
ORIGIN_PUB = "origin_pubkey.bin"

MAX_NOTIFICATIONS = 10
REPAIR_DELAY = 1.0


@dataclass
class Node:
    node_id: str
    region: str
    rank: int = 100
    uptime: int = 0
    fragments: list = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)
    writer: asyncio.StreamWriter = None


class Satellite:
    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.repair_queue: deque = deque()
        self.notifications: deque = deque(maxlen=MAX_NOTIFICATIONS)
        self.ui_dirty = asyncio.Event()

        self.origin_priv = None
        self.origin_pub = None
        self.sat_id = None
        self.tls_fingerprint = None

    # ----------------- KEY HANDLING -----------------

    def load_or_create_origin_keys(self):
        if os.path.exists(ORIGIN_PRIV):
            with open(ORIGIN_PRIV, "rb") as f:
                data = f.read()
                if len(data) != 32:
                    raise RuntimeError("origin_privkey.bin must be exactly 32 bytes")
                self.origin_priv = ed25519.Ed25519PrivateKey.from_private_bytes(data)
        else:
            self.origin_priv = ed25519.Ed25519PrivateKey.generate()
            with open(ORIGIN_PRIV, "wb") as f:
                f.write(
                    self.origin_priv.private_bytes(
                        serialization.Encoding.Raw,
                        serialization.PrivateFormat.Raw,
                        serialization.NoEncryption(),
                    )
                )

        self.origin_pub = self.origin_priv.public_key()
        with open(ORIGIN_PUB, "wb") as f:
            f.write(
                self.origin_pub.public_bytes(
                    serialization.Encoding.Raw,
                    serialization.PublicFormat.Raw,
                )
            )

        raw_pub = self.origin_pub.public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.sat_id = hashlib.sha256(raw_pub).hexdigest()[:8]

    # ----------------- TLS -----------------

    def setup_tls(self):
        if not os.path.exists("cert.pem") or not os.path.exists("key.pem"):
            os.system(
                "openssl req -x509 -newkey rsa:4096 -nodes "
                "-keyout key.pem -out cert.pem -days 365 "
                "-subj '/CN=LibreMesh Satellite'"
            )

        with open("cert.pem", "rb") as f:
            self.tls_fingerprint = hashlib.sha256(f.read()).hexdigest()

        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain("cert.pem", "key.pem")
        return ctx

    # ----------------- UI -----------------

    def notify(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.notifications.append(f"[{ts}] {msg}")
        self.ui_dirty.set()

    async def ui_loop(self):
        while True:
            await self.ui_dirty.wait()
            self.ui_dirty.clear()
            self.render_ui()

    def render_ui(self):
        os.system("clear")

        print("+-------------------------------------------------------------+")
        print("|                     Satellite Node Status                  |")
        print("+------------+----------+------+----------+-----------------+")
        print("| Node ID    | Region   | Rank | Uptime   | Fragments       |")
        print("+------------+----------+------+----------+-----------------+")
        for n in self.nodes.values():
            print(
                f"| {n.node_id:<10} | {n.region:<8} | {n.rank:<4} | "
                f"{n.uptime:<8} | {','.join(n.fragments):<15} |"
            )
        print("+-------------------------------------------------------------+\n")

        print("+-------------------------------------------+")
        print("|                Repair Queue               |")
        print("+------------+----------------+------------+")
        print("| Fragment   | Requested By   | Claimed By |")
        print("+------------+----------------+------------+")
        for frag, node_id in self.repair_queue:
            print(f"| {frag:<10} | {node_id:<14} | {self.sat_id:<10} |")
        print("+-------------------------------------------+\n")

        print("+------------------------------------------------+")
        print("|                  Notifications                |")
        print("+------------------------------------------------+")
        for n in self.notifications:
            print(f"| {n:<46} |")
        print("+------------------------------------------------+\n")

        print(f"Satellite ID: {self.sat_id}")
        print(f"TLS Fingerprint: {self.tls_fingerprint}")

    # ----------------- PROTOCOL -----------------

    async def handle_client(self, reader, writer):
        node = None
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                line = line.decode().strip()

                if line.startswith("IDENT:"):
                    _, node_id, region, _pub = line.split(":", 3)
                    node = Node(node_id=node_id, region=region, writer=writer)
                    self.nodes[node_id] = node
                    self.notify(f"Node registered: {node_id}")

                elif line.startswith("HEARTBEAT:"):
                    _, node_id, region, uptime = line.split(":")
                    if node_id in self.nodes:
                        n = self.nodes[node_id]
                        n.uptime = int(uptime)
                        n.last_seen = time.time()
                        self.ui_dirty.set()

                elif line.startswith("REPAIR:"):
                    _, node_id, fragment = line.split(":")
                    self.repair_queue.append((fragment, node_id))
                    self.notify(f"Repair requested: {fragment} by {node_id}")
                    asyncio.create_task(self.process_repairs())

        finally:
            if node:
                self.nodes.pop(node.node_id, None)
                self.notify(f"Node disconnected: {node.node_id}")
            writer.close()
            await writer.wait_closed()

    async def process_repairs(self):
        while self.repair_queue:
            frag, node_id = self.repair_queue[0]
            self.notify(f"Satellite claimed job: {frag}")
            await asyncio.sleep(REPAIR_DELAY)
            self.notify(f"Repair completed: {frag}")
            self.repair_queue.popleft()
            self.ui_dirty.set()

    # ----------------- START -----------------

    async def start(self):
        self.load_or_create_origin_keys()
        tls = self.setup_tls()

        print(f"Satellite TLS fingerprint: {self.tls_fingerprint}")

        server = await asyncio.start_server(
            self.handle_client, HOST, PORT, ssl=tls
        )

        self.ui_dirty.set()
        async with server:
            await asyncio.gather(server.serve_forever(), self.ui_loop())


if __name__ == "__main__":
    asyncio.run(Satellite().start())
