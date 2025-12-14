#!/usr/bin/env python3
import asyncio
import ssl
import os
import sys
import time
import traceback
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

HOST = "0.0.0.0"
PORT = 4001
TLS_CERT = "cert.pem"
TLS_KEY = "key.pem"
IDENTITY_KEY = "satellite_key.raw"
HEARTBEAT_INTERVAL = 30
UI_REFRESH = 1
MAX_NOTIFICATIONS = 10

class Node:
    def __init__(self, node_id, region):
        self.node_id = node_id
        self.region = region
        self.rank = 100  # placeholder
        self.uptime = 0
        self.last_seen = 0
        self.fragments = []
        self.last_activity = time.time()

class Satellite:
    def __init__(self):
        self.nodes = {}
        self.repair_queue = []
        self.notifications = []
        self.suspicious_ips = {}
        self.fingerprint = self.ensure_keys()
        self.loop = asyncio.get_event_loop()

    def ensure_keys(self):
        # Identity key
        if not os.path.exists(IDENTITY_KEY):
            key = ed25519.Ed25519PrivateKey.generate()
            with open(IDENTITY_KEY, "wb") as f:
                f.write(key.private_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PrivateFormat.Raw,
                    encryption_algorithm=serialization.NoEncryption()
                ))
        else:
            with open(IDENTITY_KEY, "rb") as f:
                key_bytes = f.read()
            key = ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)
        pub = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        self.identity_key = key
        return pub.hex()

    def ensure_tls(self):
        if not os.path.exists(TLS_CERT) or not os.path.exists(TLS_KEY):
            # Generate self-signed certificate
            import subprocess
            subprocess.run([
                "openssl", "req", "-x509", "-nodes", "-days", "365",
                "-newkey", "rsa:2048",
                "-keyout", TLS_KEY,
                "-out", TLS_CERT,
                "-subj", "/CN=LibreMeshSatellite"
            ])
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile=TLS_CERT, keyfile=TLS_KEY)
        return context

    async def handle_client(self, reader, writer):
        peer = writer.get_extra_info("peername")
        ip = peer[0]
        self.suspicious_ips.setdefault(ip, {"connections": 0, "penalty":0, "last_seen":0})
        self.suspicious_ips[ip]["connections"] += 1
        self.suspicious_ips[ip]["last_seen"] = 0

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                line = line.decode().strip()
                # reset last_seen
                for ip_data in self.suspicious_ips.values():
                    ip_data["last_seen"] += UI_REFRESH
                self.suspicious_ips[ip]["last_seen"] = 0

                if line.startswith("IDENT:"):
                    _, node_id, region, _pub = line.split(":", 3)
                    if node_id not in self.nodes:
                        self.nodes[node_id] = Node(node_id, region)
                        self.notify(f"Node registered: {node_id}")
                    self.nodes[node_id].last_activity = time.time()
                elif line.startswith("HEARTBEAT:"):
                    _, node_id, region, uptime = line.split(":", 3)
                    if node_id in self.nodes:
                        self.nodes[node_id].uptime = int(uptime)
                        self.nodes[node_id].last_activity = time.time()
                elif line.startswith("REPAIR:"):
                    _, node_id, fragment = line.split(":", 2)
                    self.repair_queue.append({"fragment": fragment, "requested_by": node_id, "claimed_by": self.fingerprint[:8]})
                    self.notify(f"Repair requested: {fragment} by {node_id}")
                else:
                    self.notify(f"Unknown message: {line}")

        except Exception as e:
            self.notify(f"Client error: {e}")
            traceback.print_exc()
        finally:
            writer.close()
            await writer.wait_closed()
            self.notify(f"Node disconnected: {ip}")

    def notify(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.notifications.append(f"[{timestamp}] {msg}")
        if len(self.notifications) > MAX_NOTIFICATIONS:
            self.notifications.pop(0)

    async def ui_loop(self):
        while True:
            os.system("clear")
            print("+-------------------------------------------------------------+")
            print("|                     Satellite Node Status                  |")
            print("+------------+----------+------+----------+-----------------+")
            print("| Node ID    | Region   | Rank | Uptime   | Fragments       |")
            print("+------------+----------+------+----------+-----------------+")
            for node in self.nodes.values():
                frags = ",".join(node.fragments)
                print(f"| {node.node_id:<10} | {node.region:<8} | {node.rank:<4} | {node.uptime:<8} | {frags:<15} |")
            print("+-------------------------------------------------------------+\n")

            print("+-------------------------------------------+")
            print("|                Repair Queue               |")
            print("+------------+----------------+------------+")
            print("| Fragment   | Requested By   | Claimed By |")
            print("+------------+----------------+------------+")
            for job in self.repair_queue:
                print(f"| {job['fragment']:<10} | {job['requested_by']:<14} | {job['claimed_by']:<10} |")
            print("+-------------------------------------------+\n")

            print("+------------------------------------------------+")
            print("|                  Notifications                |")
            print("+------------------------------------------------+")
            for n in self.notifications:
                print(f"| {n:<46} |")
            print("+------------------------------------------------+\n")

            print("+-----------------------------------------------+")
            print("|               Suspicious IPs Advisory        |")
            print("+------------+------------+---------+----------+")
            for ip, data in self.suspicious_ips.items():
                print(f"| {ip:<10} | {data['connections']:<10} | {data['penalty']:<7} | {data['last_seen']:<8} |")
            print("+-----------------------------------------------+\n")

            print(f"Satellite ID: {self.fingerprint[:8]}")
            print(f"TLS Fingerprint: {self.fingerprint}\n")
            await asyncio.sleep(UI_REFRESH)

    async def start(self):
        ssl_context = self.ensure_tls()
        server = await asyncio.start_server(self.handle_client, HOST, PORT, ssl=ssl_context)
        print(f"Satellite listening on {HOST}:{PORT}")
        await asyncio.gather(server.serve_forever(), self.ui_loop())

def main():
    sat = Satellite()
    asyncio.run(sat.start())

if __name__ == "__main__":
    main()
