#!/usr/bin/env python3

import asyncio
import ssl
import os
import json
import time
import hashlib
import base64
import datetime
import urllib.request
from collections import deque
from pathlib import Path

import psutil
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography import x509
from cryptography.x509.oid import NameOID


# ============================================================
# Configuration
# ============================================================

NODE_PORT = 4001
SAT_SAT_PORT = 5001

CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

IS_ORIGIN = True   # intentionally undocumented

ORIGIN_PRIVKEY_FILE = "origin_privkey.pem"
ORIGIN_PUBKEY_FILE = "origin_pubkey.pem"

TRUSTED_LIST_FILE = "list.json"
TRUSTED_LIST_URL = "https://raw.githubusercontent.com/boelle/LibreMesh/refs/heads/main/trusted-satellites/list.json"
ORIGIN_PUBKEY_URL = "https://raw.githubusercontent.com/boelle/LibreMesh/refs/heads/main/origin_pubkey.pem"

MAX_CPU_LOAD = 85
HEARTBEAT_TIMEOUT = 90
NOTIFICATION_LIMIT = 10


# ============================================================
# Models
# ============================================================

class Node:
    def __init__(self, node_id, region, pubkey):
        self.node_id = node_id
        self.region = region
        self.pubkey = pubkey
        self.rank = 100
        self.uptime = 0
        self.fragments = []
        self.last_heartbeat = time.time()
        self.online = True


class RepairJob:
    def __init__(self, fragment, requester):
        self.fragment = fragment
        self.requester = requester
        self.claimed_by = None
        self.created = time.time()


# ============================================================
# Satellite
# ============================================================

class Satellite:
    def __init__(self):
        self.nodes = {}
        self.repair_queue = deque()
        self.notifications = deque(maxlen=NOTIFICATION_LIMIT)
        self.lock = asyncio.Lock()

        self.origin_privkey = None
        self.origin_pubkey = None

        self.tls_fingerprint = None
        self.satellite_id = None

        self.online_satellites = {}
        self.trusted_satellites = {}

    # --------------------------------------------------------
    # UI
    # --------------------------------------------------------

    def redraw(self):
        os.system("clear")

        print("+-------------------------------------------------------------+")
        print("|                     Satellite Node Status                  |")
        print("+------------+----------+------+----------+-----------------+")
        print("| Node ID    | Region   | Rank | Uptime   | Fragments       |")
        print("+------------+----------+------+----------+-----------------+")
        for n in self.nodes.values():
            frags = ",".join(n.fragments)
            print(f"| {n.node_id:<10} | {n.region:<8} | {n.rank:<4} | {n.uptime:<8} | {frags:<15} |")
        print("+-------------------------------------------------------------+\n")

        print("+-------------------------------------------+")
        print("|                Repair Queue               |")
        print("+------------+----------------+------------+")
        print("| Fragment   | Requested By   | Claimed By |")
        print("+------------+----------------+------------+")
        for job in self.repair_queue:
            claim = job.claimed_by or "-"
            print(f"| {job.fragment:<10} | {job.requester:<14} | {claim:<10} |")
        print("+-------------------------------------------+\n")

        print("+------------------------------------------------+")
        print("|                  Notifications                |")
        print("+------------------------------------------------+")
        for n in self.notifications:
            print(f"| {n:<46} |")
        print("+------------------------------------------------+\n")

        print("+-----------------------------------------------+")
        print("|                Online Satellites             |")
        print("+------------+----------------+----------------+")
        print("| Sat ID     | IP             | Last Seen      |")
        print("+------------+----------------+----------------+")
        for sid, ts in self.online_satellites.items():
            ip = self.trusted_satellites.get(sid, {}).get("ip", "?")
            print(f"| {sid:<10} | {ip:<14} | {int(time.time() - ts):<14}s |")
        print("+-----------------------------------------------+\n")

        print(f"Satellite ID: {self.satellite_id}")
        print(f"TLS Fingerprint: {self.tls_fingerprint}")

    def notify(self, msg):
        ts = datetime.datetime.utcnow().strftime("%H:%M:%S")
        self.notifications.append(f"[{ts}] {msg}")
        self.redraw()

    # --------------------------------------------------------
    # TLS
    # --------------------------------------------------------

    def ensure_tls(self):
        if not Path(CERT_FILE).exists() or not Path(KEY_FILE).exists():
            self.generate_tls()

        with open(CERT_FILE, "rb") as f:
            self.tls_fingerprint = hashlib.sha256(f.read()).hexdigest()

        self.satellite_id = self.tls_fingerprint[:8]
        print(f"Satellite TLS fingerprint: {self.tls_fingerprint}")

    def generate_tls(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"LibreMesh"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"Satellite"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .sign(key, hashes.SHA256())
        )

        with open(KEY_FILE, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
        with open(CERT_FILE, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

    # --------------------------------------------------------
    # Origin keys (RAW 32 BYTES ONLY)
    # --------------------------------------------------------

    def load_origin_keys(self):
        if IS_ORIGIN:
            if not Path(ORIGIN_PRIVKEY_FILE).exists():
                priv = ed25519.Ed25519PrivateKey.generate()
                pub = priv.public_key()

                with open(ORIGIN_PRIVKEY_FILE, "wb") as f:
                    f.write(priv.private_bytes(
                        serialization.Encoding.Raw,
                        serialization.PrivateFormat.Raw,
                        serialization.NoEncryption(),
                    ))
                with open(ORIGIN_PUBKEY_FILE, "wb") as f:
                    f.write(pub.public_bytes(
                        serialization.Encoding.Raw,
                        serialization.PublicFormat.Raw,
                    ))

            priv_bytes = Path(ORIGIN_PRIVKEY_FILE).read_bytes()
            if len(priv_bytes) != 32:
                raise RuntimeError("Origin private key must be exactly 32 bytes (raw Ed25519)")

            pub_bytes = Path(ORIGIN_PUBKEY_FILE).read_bytes()
            if len(pub_bytes) != 32:
                raise RuntimeError("Origin public key must be exactly 32 bytes (raw Ed25519)")

            self.origin_privkey = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
            self.origin_pubkey = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)

        else:
            with urllib.request.urlopen(ORIGIN_PUBKEY_URL) as r:
                pub_bytes = r.read()
            if len(pub_bytes) != 32:
                raise RuntimeError("Fetched origin public key is not 32 bytes")
            self.origin_pubkey = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)

    # --------------------------------------------------------
    # Trusted list
    # --------------------------------------------------------

    def write_trusted_list(self):
        if not IS_ORIGIN:
            return

        data = {
            "version": 1,
            "satellites": [{
                "ip": "127.0.0.1",
                "port": NODE_PORT,
                "fingerprint": self.tls_fingerprint
            }]
        }

        payload = json.dumps(data, sort_keys=True).encode()
        sig = self.origin_privkey.sign(payload)
        data["signature"] = base64.b64encode(sig).decode()

        with open(TRUSTED_LIST_FILE, "w") as f:
            json.dump(data, f, indent=2)

        self.notify("Trusted satellite list signed")

    def load_trusted_list(self):
        if IS_ORIGIN:
            return

        with urllib.request.urlopen(TRUSTED_LIST_URL) as r:
            data = json.loads(r.read())

        sig = base64.b64decode(data.pop("signature"))
        payload = json.dumps(data, sort_keys=True).encode()
        self.origin_pubkey.verify(sig, payload)

        for s in data["satellites"]:
            sid = s["fingerprint"][:8]
            self.trusted_satellites[sid] = s

        self.notify("Trusted satellite list verified")

    # --------------------------------------------------------
    # Protocol
    # --------------------------------------------------------

    async def handle_line(self, line):
        if line.startswith("IDENT:"):
            _, nid, region, pubkey = line.strip().split(":", 3)
            async with self.lock:
                if nid not in self.nodes:
                    self.nodes[nid] = Node(nid, region, pubkey)
                    self.notify(f"Node registered: {nid}")

        elif line.startswith("HEARTBEAT:"):
            _, nid, region, uptime = line.strip().split(":", 3)
            async with self.lock:
                if nid in self.nodes:
                    n = self.nodes[nid]
                    n.region = region
                    n.uptime = int(uptime)
                    n.last_heartbeat = time.time()

        elif line.startswith("REPAIR:"):
            _, nid, fragment = line.strip().split(":", 2)
            async with self.lock:
                self.repair_queue.append(RepairJob(fragment, nid))
                self.notify(f"Repair requested: {fragment} by {nid}")

    async def handle_client(self, reader, writer):
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                await self.handle_line(data.decode())
        finally:
            writer.close()

    # --------------------------------------------------------
    # Repair worker
    # --------------------------------------------------------

    async def repair_worker(self):
        while True:
            async with self.lock:
                if self.repair_queue and psutil.cpu_percent() < MAX_CPU_LOAD:
                    job = self.repair_queue.popleft()
                    job.claimed_by = self.satellite_id
                    self.notify(f"Executing repair: {job.fragment}")
                    await asyncio.sleep(1)
                    self.notify(f"Repair completed: {job.fragment}")
            await asyncio.sleep(0.5)

    # --------------------------------------------------------
    # Start
    # --------------------------------------------------------

    async def start(self):
        self.ensure_tls()
        self.load_origin_keys()
        self.write_trusted_list()
        self.load_trusted_list()

        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(CERT_FILE, KEY_FILE)

        server = await asyncio.start_server(
            self.handle_client, "0.0.0.0", NODE_PORT, ssl=ssl_ctx
        )

        self.notify(f"Satellite listening on port {NODE_PORT}")
        asyncio.create_task(self.repair_worker())

        async with server:
            await server.serve_forever()


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    asyncio.run(Satellite().start())
