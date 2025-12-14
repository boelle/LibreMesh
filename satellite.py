#!/usr/bin/env python3
import asyncio
import os
import ssl
import hashlib
import time
from collections import deque
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

# Config
HOST = "0.0.0.0"
PORT = 4001
KEY_FILE = "satellite_key.pem"
CERT_FILE = "satellite_cert.pem"
HEARTBEAT_TIMEOUT = 120  # seconds

# UI settings
UI_REFRESH = 1  # seconds

class Node:
    def __init__(self, node_id, region):
        self.node_id = node_id
        self.region = region
        self.rank = 100
        self.uptime = 0
        self.fragments = []
        self.last_seen = 0
        self.online_time = 0
        self.last_activity_ts = time.time()
        self.connection = None

class Satellite:
    def __init__(self):
        self.nodes = {}
        self.repair_queue = deque()
        self.notifications = deque(maxlen=10)
        self.suspicious_ips = {}
        self.fingerprint = self.ensure_keys()
        self.id = self.fingerprint[:8]

    def ensure_keys(self):
        # Create key if missing
        if not os.path.exists(KEY_FILE):
            key = ed25519.Ed25519PrivateKey.generate()
            with open(KEY_FILE, "wb") as f:
                f.write(key.private_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PrivateFormat.Raw,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            # For TLS cert, self-signed
            import subprocess
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "ed25519", "-keyout", KEY_FILE,
                "-out", CERT_FILE, "-days", "365", "-nodes",
                "-subj", "/CN=LibreMeshSatellite"
            ])
        # Load private key and calculate SHA256 of public key for fingerprint
        with open(KEY_FILE, "rb") as f:
            priv_bytes = f.read()
        priv = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
        pub = priv.public_key()
        pub_bytes = pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return hashlib.sha256(pub_bytes).hexdigest()

    async def start(self):
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(CERT_FILE, KEY_FILE)
        server = await asyncio.start_server(self.handle_client, HOST, PORT, ssl=ssl_context)
        print(f"Satellite ID: {self.id}")
        print(f"TLS Fingerprint: {self.fingerprint}")
        await asyncio.gather(server.serve_forever(), self.ui_loop())

    async def handle_client(self, reader, writer):
        ip = writer.get_extra_info('peername')[0]
        self.suspicious_ips.setdefault(ip, {"connections": 0, "penalty": 0, "last_seen": 0})
        self.suspicious_ips[ip]["connections"] += 1
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=300)
                if not line:
                    break
                line = line.decode().strip()
                self.process_message(line, ip)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            self.notifications.append(f"[{time.strftime('%H:%M:%S')}] Client error while reading line: {ip}")
        finally:
            writer.close()
            await writer.wait_closed()
            # Do not remove node, keep it for last_seen counting
            self.notifications.append(f"[{time.strftime('%H:%M:%S')}] Node disconnected: {ip}")

    def process_message(self, msg, ip):
        now = time.time()
        parts = msg.split(":")
        if parts[0] == "IDENT":
            node_id, region, _ = parts[1], parts[2], parts[3]
            node = self.nodes.get(node_id) or Node(node_id, region)
            node.connection = ip
            node.last_seen = 0
            node.last_activity_ts = now
            self.nodes[node_id] = node
            self.notifications.append(f"[{time.strftime('%H:%M:%S')}] Node registered: {node_id}")
        elif parts[0] == "HEARTBEAT":
            node_id = parts[1]
            node = self.nodes.get(node_id)
            if node:
                node.last_seen = 0
                node.last_activity_ts = now
        elif parts[0] == "REPAIR":
            fragment = parts[2]
            node_id = parts[1]
            self.repair_queue.append({"fragment": fragment, "requested_by": node_id, "claimed_by": None})
            self.notifications.append(f"[{time.strftime('%H:%M:%S')}] Repair requested: {fragment} by {node_id}")
        # Reset last_seen for IP
        self.suspicious_ips[ip]["last_seen"] = 0
        self.suspicious_ips[ip]["connections"] += 0

    async def ui_loop(self):
        while True:
            self.update_last_seen()
            self.claim_repairs()
            self.print_ui()
            await asyncio.sleep(UI_REFRESH)

    def update_last_seen(self):
        now = time.time()
        for node in self.nodes.values():
            node.last_seen = int(now - node.last_activity_ts)
            node.online_time += 1  # increment online time each second
        for ip_data in self.suspicious_ips.values():
            ip_data["last_seen"] += 1

    def claim_repairs(self):
        # Claim available repairs
        for job in list(self.repair_queue):
            if job["claimed_by"] is None:
                job["claimed_by"] = self.id
                self.notifications.append(f"[{time.strftime('%H:%M:%S')}] Satellite claimed job: {job['fragment']}")
                # Simulate instant execution for test
                self.notifications.append(f"[{time.strftime('%H:%M:%S')}] Repair completed: {job['fragment']}")
                self.repair_queue.remove(job)

    def print_ui(self):
        os.system("clear")
        print("+-------------------------------------------------------------+")
        print("|                     Satellite Node Status                  |")
        print("+------------+----------+------+----------+-----------------+")
        print("| Node ID    | Region   | Rank | Uptime   | Fragments       |")
        print("+------------+----------+------+----------+-----------------+")
        for node in self.nodes.values():
            print(f"| {node.node_id:<10} | {node.region:<8} | {node.rank:<4} | {node.uptime:<8} | {' '.join(node.fragments):<15} |")
        print("+-------------------------------------------------------------+\n")

        # Repair Queue
        print("+-------------------------------------------+")
        print("|                Repair Queue               |")
        print("+------------+----------------+------------+")
        print("| Fragment   | Requested By   | Claimed By |")
        print("+------------+----------------+------------+")
        for job in self.repair_queue:
            print(f"| {job['fragment']:<10} | {job['requested_by']:<14} | {job['claimed_by'] or '':<10} |")
        print("+-------------------------------------------+\n")

        # Notifications
        print("+------------------------------------------------+")
        print("|                  Notifications                |")
        print("+------------------------------------------------+")
        for note in list(self.notifications)[-10:]:
            print(f"| {note:<46} |")
        print("+------------------------------------------------+\n")

        # Suspicious IPs
        print("+-----------------------------------------------+")
        print("|               Suspicious IPs Advisory        |")
        print("+------------+------------+---------+----------+")
        print("| IP         | Connections| Penalty | Last Seen|")
        print("+------------+------------+---------+----------+")
        for ip, data in self.suspicious_ips.items():
            print(f"| {ip:<10} | {data['connections']:<10} | {data['penalty']:<7} | {data['last_seen']:<8} |")
        print("+-----------------------------------------------+\n")

        print(f"Satellite ID: {self.id}")
        print(f"TLS Fingerprint: {self.fingerprint}")

def main():
    sat = Satellite()
    asyncio.run(sat.start())

if __name__ == "__main__":
    main()
