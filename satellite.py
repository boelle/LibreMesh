#!/usr/bin/env python3
import asyncio
import ssl
import os
import time
import json
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from datetime import datetime
from tempfile import NamedTemporaryFile

HOST = '0.0.0.0'
PORT = 4001
CERTFILE = 'cert.pem'
KEYFILE = 'key.pem'
HANDSHAKE_TIMEOUT = 10

class Node:
    def __init__(self, node_id, region, writer):
        self.node_id = node_id
        self.region = region
        self.writer = writer
        self.uptime = 0
        self.last_seen = 0
        self.last_activity_ts = time.time()
        self.fragments = []

class Satellite:
    def __init__(self):
        self.nodes = {}
        self.notifications = []
        self.suspicious_ips = {}
        self.repair_queue = []
        self.fingerprint = self.ensure_keys()
        print(f"Satellite TLS fingerprint: {self.fingerprint}")

    def ensure_keys(self):
        # Generate Ed25519 keypair if missing
        if not os.path.exists(KEYFILE):
            priv = ed25519.Ed25519PrivateKey.generate()
            pem_priv = priv.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            with open(KEYFILE, 'wb') as f:
                f.write(pem_priv)
        if not os.path.exists(CERTFILE):
            # Generate temporary self-signed cert using OpenSSL via ssl module
            ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            # Dummy cert to satisfy load_cert_chain
            with NamedTemporaryFile(delete=False) as f:
                f.write(b"-----BEGIN CERTIFICATE-----\nMIIBszCCAVugAwIBAgIUfTj1/CAf1T+5ZW6Dq1MekR8EC1MwCgYIKoZIzj0EAwIw\nEzERMA8GA1UEAwwIdGVzdC5jb20wHhcNMjAwMTAxMDAwMDAwWhcNMzAwMTAxMDAw\nMDAwWjATMREwDwYDVQQDDAh0ZXN0LmNvbTBZMBMGByqGSM49AgEGCCqGSM49AwEH\nA0IABOBBIC9+Z5Y3vl9d6Y/JH+2D81Uq+7sQa0mWWtQyI/5J1rh0NFGc3WTYvCEp\nv5E8nZ1K3gV5oGqL0mV0FqjUzBRMB0GA1UdDgQWBBRFqEvWq+ABd0n8j8MLFjG3g\n0Hw3DAfBgNVHSMEGDAWgBRFqEvWq+ABd0n8j8MLFjG3g0Hw3DAPBgNVHRMBAf8E\nBTADAQH/MAoGCCqGSM49BAMCA0gAMEUCIQCJ7K4y9vDhyM8aR1H9lV3B07FJbl+0\nV5/WZQ9Evd9YrZwIgD9X5r2v8xQ3R+UQ3q8smk58gfI3gZPvGfPgnZnN+1PY=\n-----END CERTIFICATE-----")
                f.flush()
                os.rename(f.name, CERTFILE)
        with open(KEYFILE, 'rb') as f:
            priv_bytes = f.read()
        return priv_bytes.hex()[:8]

    async def handle_client(self, reader, writer):
        peer = writer.get_extra_info('peername')
        ip = peer[0] if peer else "unknown"
        self.suspicious_ips.setdefault(ip, {'connections': 0, 'penalty': 0, 'last_seen': 0})
        self.suspicious_ips[ip]['connections'] += 1
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=HANDSHAKE_TIMEOUT)
                if not line:
                    break
                line = line.decode().strip()
                self.process_message(line, writer)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self.notify(f"Client error while reading line from {ip}")
        finally:
            writer.close()
            await writer.wait_closed()
            self.notify(f"Node disconnected: {ip}")

    def process_message(self, line, writer):
        ts = time.time()
        parts = line.split(":")
        if parts[0] == "IDENT" and len(parts) == 4:
            node_id, region, _pubkey = parts[1], parts[2], parts[3]
            node = Node(node_id, region, writer)
            self.nodes[node_id] = node
            self.notify(f"Node registered: {node_id}")
        elif parts[0] == "HEARTBEAT" and len(parts) == 4:
            node_id = parts[1]
            uptime = int(parts[3])
            if node_id in self.nodes:
                node = self.nodes[node_id]
                node.uptime = uptime
                node.last_activity_ts = ts
                node.last_seen = 0
        elif parts[0] == "REPAIR" and len(parts) == 2:
            fragment = parts[1]
            self.repair_queue.append({'fragment': fragment, 'claimed_by': self.fingerprint[:8]})
            self.notify(f"Repair requested: {fragment}")

    def notify(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.notifications.append(f"[{ts}] {msg}")
        if len(self.notifications) > 10:
            self.notifications.pop(0)

    async def update_last_seen_loop(self):
        while True:
            now = time.time()
            for node in self.nodes.values():
                node.last_seen = int(now - node.last_activity_ts)
            for ip in self.suspicious_ips:
                self.suspicious_ips[ip]['last_seen'] += 1
            await asyncio.sleep(1)

    def print_ui(self):
        print("+-------------------------------------------------------------+")
        print("|                     Satellite Node Status                  |")
        print("+------------+----------+------+----------+-----------------+")
        print("| Node ID    | Region   | Rank | Uptime   | Fragments       |")
        print("+------------+----------+------+----------+-----------------+")
        for node in self.nodes.values():
            print(f"| {node.node_id:<10} | {node.region:<8} | 100  | {node.uptime:<8} | {' '.join(node.fragments):<15} |")
        print("+-------------------------------------------------------------+\n")

        print("+-------------------------------------------+")
        print("|                Repair Queue               |")
        print("+------------+----------------+------------+")
        for job in self.repair_queue:
            print(f"| {job['fragment']:<10} | node_test      | {job['claimed_by']:<10} |")
        print("+-------------------------------------------+\n")

        print("+------------------------------------------------+")
        print("|                  Notifications                |")
        print("+------------------------------------------------+")
        for msg in self.notifications:
            print(f"| {msg:<46} |")
        print("+------------------------------------------------+\n")

        print("+-----------------------------------------------+")
        print("|               Suspicious IPs Advisory        |")
        print("+------------+------------+---------+----------+")
        for ip, info in self.suspicious_ips.items():
            print(f"| {ip:<10} | {info['connections']:<10} | {info['penalty']:<7} | {info['last_seen']:<8} |")
        print("+-----------------------------------------------+\n")

        print(f"Satellite ID: {self.fingerprint[:8]}")
        print(f"TLS Fingerprint: {self.fingerprint}\n")

    async def ui_loop(self):
        while True:
            os.system('clear')
            self.print_ui()
            await asyncio.sleep(2)

    async def start_server(self):
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(CERTFILE, KEYFILE)
        server = await asyncio.start_server(self.handle_client, HOST, PORT, ssl=ssl_ctx)
        asyncio.create_task(self.update_last_seen_loop())
        await asyncio.gather(server.serve_forever(), self.ui_loop())

def main():
    sat = Satellite()
    asyncio.run(sat.start_server())

if __name__ == "__main__":
    main()
