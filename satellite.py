#!/usr/bin/env python3
import asyncio
import ssl
import os
import time
import json
from collections import deque, defaultdict
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

# Config
NODE_PORT = 4001
HANDSHAKE_TIMEOUT = 10
HEARTBEAT_INTERVAL = 30
MAX_NOTIFICATION = 50
TARGET_UPTIME = 86400  # 24h in seconds for full rank

# Paths
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"
ORIGIN_LIST_URL = "https://raw.githubusercontent.com/boelle/LibreMesh/refs/heads/main/trusted-satellites/list.json"

# Data classes
class Node:
    def __init__(self, node_id, region, public_key):
        self.node_id = node_id
        self.region = region
        self.public_key = public_key
        self.uptime = 0
        self.rank = 0
        self.last_seen = 0
        self.first_seen = time.time()
        self.total_online_time = 0
        self.online = True
        self.fragments = []

class RepairJob:
    def __init__(self, fragment, requested_by):
        self.fragment = fragment
        self.requested_by = requested_by
        self.claimed_by = None

class Satellite:
    def __init__(self):
        self.nodes = {}
        self.repairs = deque()
        self.notifications = deque(maxlen=MAX_NOTIFICATION)
        self.suspicious_ips = defaultdict(lambda: {"connections":0, "penalty":0, "last_seen":0})
        self.load_keys()
        self.ssl_context = self.create_ssl_context()

    def load_keys(self):
        if not os.path.exists(KEY_FILE) or not os.path.exists(CERT_FILE):
            self.create_self_signed_cert()
        self.fingerprint = self.calculate_fingerprint(KEY_FILE)
        print(f"Satellite TLS fingerprint: {self.fingerprint}")

    def create_ssl_context(self):
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(CERT_FILE, KEY_FILE)
        return context

    def create_self_signed_cert(self):
        # For simplicity: generate key only, not a real X509 cert
        key = ed25519.Ed25519PrivateKey.generate()
        with open(KEY_FILE, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption()
            ))
        # Create dummy cert.pem (empty file for placeholder)
        with open(CERT_FILE, "wb") as f:
            f.write(b"")  # Placeholder
        print("Generated new key and cert files.")

    def calculate_fingerprint(self, keyfile):
        with open(keyfile, "rb") as f:
            key_bytes = f.read()
        return key_bytes.hex()

    async def start(self):
        server = await asyncio.start_server(
            self.handle_client, '0.0.0.0', NODE_PORT, ssl=self.ssl_context
        )
        async with server:
            await asyncio.gather(server.serve_forever(), self.ui_loop())

    async def handle_client(self, reader, writer):
        peer_ip = writer.get_extra_info("peername")[0]
        self.suspicious_ips[peer_ip]["connections"] += 1
        self.suspicious_ips[peer_ip]["last_seen"] = 0

        try:
            # Expect IDENT first
            line = await asyncio.wait_for(reader.readline(), timeout=HANDSHAKE_TIMEOUT)
            line = line.decode().strip()
            if not line.startswith("IDENT:"):
                raise Exception("Expected IDENT")
            parts = line.split(":")
            node_id, region, pubkey_hex = parts[1], parts[2], parts[3]
            node = Node(node_id, region, pubkey_hex)
            self.nodes[node_id] = node
            self.add_notification(f"Node registered: {node_id}")
        except Exception as e:
            self.add_notification(f"Client error during handshake from {peer_ip}: {str(e)}")
            writer.close()
            await writer.wait_closed()
            return

        # Node connected
        while True:
            try:
                line = await reader.readline()
                if not line:
                    raise Exception("Disconnected")
                line = line.decode().strip()
                node.last_seen = 0
                node.online = True

                if line.startswith("HEARTBEAT:"):
                    parts = line.split(":")
                    node.uptime = int(parts[3])
                    self.update_node_rank(node)
                elif line.startswith("REPAIR:"):
                    frag = line.split(":")[2]
                    job = RepairJob(frag, node.node_id)
                    self.repairs.append(job)
                    self.add_notification(f"Repair requested: {frag} by {node.node_id}")
                # Optional: handle latency or storage metrics here

            except Exception:
                node.online = False
                self.add_notification(f"Node disconnected: {node.node_id}")
                break

    def update_node_rank(self, node):
        # Uptime score
        uptime_score = min(1.0, node.uptime / TARGET_UPTIME)
        # Online reliability score
        elapsed = time.time() - node.first_seen
        online_time = node.total_online_time + (0 if not node.online else HEARTBEAT_INTERVAL)
        online_score = min(1.0, online_time / max(elapsed, 1))
        # Optional metrics placeholders
        response_score = 1.0
        storage_score = 1.0
        node.rank = int(100 * (0.5*uptime_score + 0.5*online_score))

    def add_notification(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.notifications.append(f"[{timestamp}] {msg}")

    async def ui_loop(self):
        while True:
            self.refresh_last_seen()
            self.print_ui()
            await asyncio.sleep(1)

    def refresh_last_seen(self):
        for node in self.nodes.values():
            if node.online:
                node.total_online_time += 1
            node.last_seen += 1
        for ip in self.suspicious_ips.values():
            ip["last_seen"] += 1

    def print_ui(self):
        os.system("clear")
        print("+-------------------------------------------------------------+")
        print("|                     Satellite Node Status                  |")
        print("+------------+----------+------+----------+-----------------+")
        print("| Node ID    | Region   | Rank | Uptime   | Fragments       |")
        print("+------------+----------+------+----------+-----------------+")
        for node in self.nodes.values():
            print(f"| {node.node_id:<10} | {node.region:<8} | {node.rank:<4} | {node.uptime:<8} | {','.join(node.fragments):<15} |")
        print("+-------------------------------------------------------------+\n")

        print("+-------------------------------------------+")
        print("|                Repair Queue               |")
        print("+------------+----------------+------------+")
        for job in self.repairs:
            claimed = job.claimed_by[:8] if job.claimed_by else ""
            print(f"| {job.fragment:<10} | {job.requested_by:<14} | {claimed:<10} |")
        print("+-------------------------------------------+\n")

        print("+------------------------------------------------+")
        print("|                  Notifications                |")
        print("+------------------------------------------------+")
        for note in list(self.notifications)[-10:]:
            print(f"| {note:<46} |")
        print("+------------------------------------------------+\n")

        print("+-----------------------------------------------+")
        print("|               Suspicious IPs Advisory        |")
        print("+------------+------------+---------+----------+")
        for ip, info in self.suspicious_ips.items():
            print(f"| {ip:<10} | {info['connections']:<10} | {info['penalty']:<7} | {info['last_seen']:<8} |")
        print("+-----------------------------------------------+\n")

        print(f"Satellite ID: {self.fingerprint[:8]}")
        print(f"TLS Fingerprint: {self.fingerprint}")

# Entry point
if __name__ == "__main__":
    sat = Satellite()
    asyncio.run(sat.start())
