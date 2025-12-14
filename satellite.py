import asyncio
import ssl
from pathlib import Path
from collections import deque
import datetime
import os
import hashlib
import json
import base64
import urllib.request
import psutil
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes

# ----------------------------
# Config
# ----------------------------
NODE_PORT = 4001
SAT_PEER_PORT = 5001
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"
HEARTBEAT_TIMEOUT = 90
NOTIFICATION_LIMIT = 10
MAX_CPU_LOAD = 85
TRUSTED_LIST_URL = "https://raw.githubusercontent.com/LibreMesh/trusted-satellites/main/list.json"

IS_ORIGIN = True  # Set True if this satellite is the origin
ORIGIN_PRIVKEY_FILE = "origin_privkey.pem"
ORIGIN_PUBKEY_FILE = "origin_pubkey.pem"
TRUSTED_LIST_FILE = "list.json"

# ----------------------------
# Data models
# ----------------------------
class Node:
    def __init__(self, node_id, region, pubkey):
        self.node_id = node_id
        self.region = region
        self.pubkey = pubkey
        self.uptime = 0
        self.rank = 100
        self.fragments = []
        self.last_heartbeat = datetime.datetime.utcnow()
        self.online = True

class RepairJob:
    def __init__(self, fragment_id, requested_by):
        self.fragment_id = fragment_id
        self.requested_by = requested_by
        self.timestamp = datetime.datetime.utcnow()
        self.claimed_by = None

# ----------------------------
# Satellite
# ----------------------------
class Satellite:
    def __init__(self):
        self.nodes = {}
        self.repair_queue = deque()
        self.notifications = deque(maxlen=NOTIFICATION_LIMIT)
        self.lock = asyncio.Lock()
        self.satellite_id = None
        self.key_fingerprint = None
        self.peers = {}  # satellite_id -> (ip, port)
        self.origin_privkey = None
        self.origin_pubkey = None

    # ------------------------
    # UI
    # ------------------------
    def render_ui(self):
        os.system("cls" if os.name == "nt" else "clear")
        # Node Status Table
        print("+-------------------------------------------------------------+")
        print("|                     Satellite Node Status                  |")
        print("+------------+----------+------+----------+-----------------+")
        print("| Node ID    | Region   | Rank | Uptime   | Fragments       |")
        print("+------------+----------+------+----------+-----------------+")
        for node in self.nodes.values():
            frag_list = ",".join(node.fragments)
            print(f"| {node.node_id:<10} | {node.region:<8} | {node.rank:<4} | {node.uptime:<8} | {frag_list:<15} |")
        print("+-------------------------------------------------------------+\n")

        # Repair Queue Table
        print("+-------------------------------------------+")
        print("|                Repair Queue               |")
        print("+------------+----------------+------------+")
        print("| Fragment   | Requested By   | Claimed By |")
        print("+------------+----------------+------------+")
        for job in self.repair_queue:
            claim = job.claimed_by or "unclaimed"
            print(f"| {job.fragment_id:<10} | {job.requested_by:<14} | {claim:<10} |")
        print("+-------------------------------------------+\n")

        # Notifications Table
        print("+------------------------------------------------+")
        print("|                  Notifications                |")
        print("+------------------------------------------------+")
        for note in self.notifications:
            print(f"| {note:<46} |")
        print("+------------------------------------------------+\n")

        # Satellite ID and TLS fingerprint
        print(f"Satellite ID: {self.satellite_id}")
        print(f"TLS Fingerprint: {self.key_fingerprint}")

    def add_notification(self, message):
        timestamp = datetime.datetime.utcnow().strftime("%H:%M:%S")
        self.notifications.append(f"[{timestamp}] {message}")
        self.render_ui()

    # ------------------------
    # Node Handling
    # ------------------------
    async def process_line(self, line, writer):
        line = line.strip()
        if line.startswith("IDENT:"):
            parts = line.split(":", 3)
            if len(parts) != 4:
                return
            node_id, region, pubkey = parts[1], parts[2], parts[3]
            await self.register_node(node_id, region, pubkey)
        elif line.startswith("HEARTBEAT:"):
            parts = line.split(":", 4)
            if len(parts) != 5:
                return
            node_id, region, uptime = parts[1], parts[2], int(parts[3])
            await self.heartbeat(node_id, region, uptime)
        elif line.startswith("REPAIR:"):
            parts = line.split(":", 2)
            if len(parts) != 3:
                return
            node_id, fragment_id = parts[1], parts[2]
            await self.queue_repair(node_id, fragment_id)

    async def register_node(self, node_id, region, pubkey):
        async with self.lock:
            if node_id in self.nodes:
                self.nodes[node_id].online = True
                self.add_notification(f"Node re-identified: {node_id}")
                return
            self.nodes[node_id] = Node(node_id, region, pubkey)
            self.add_notification(f"Node registered: {node_id}")

    async def heartbeat(self, node_id, region, uptime):
        async with self.lock:
            node = self.nodes.get(node_id)
            if not node:
                return
            node.region = region
            node.uptime = uptime
            node.last_heartbeat = datetime.datetime.utcnow()

    async def queue_repair(self, node_id, fragment_id):
        async with self.lock:
            job = RepairJob(fragment_id, node_id)
            self.repair_queue.append(job)
            self.add_notification(f"Repair requested: {fragment_id} by {node_id}")

    # ------------------------
    # Node Connection
    # ------------------------
    async def handle_connection(self, reader, writer):
        addr = writer.get_extra_info("peername")
        self.add_notification(f"Node connected from {addr}")
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                await self.process_line(data.decode(), writer)
        except Exception as e:
            self.add_notification(f"Error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    # ------------------------
    # Repair Worker
    # ------------------------
    async def repair_worker(self):
        while True:
            async with self.lock:
                for job in list(self.repair_queue):
                    if job.claimed_by is None and psutil.cpu_percent() < MAX_CPU_LOAD:
                        job.claimed_by = self.satellite_id
                        self.add_notification(f"Satellite claimed job: {job.fragment_id}")
                        await self.execute_repair(job)
                        self.repair_queue.remove(job)
            await asyncio.sleep(1)

    async def execute_repair(self, job: RepairJob):
        self.add_notification(f"Executing repair: {job.fragment_id}")
        await asyncio.sleep(1)  # simulate repair
        self.add_notification(f"Repair completed: {job.fragment_id}")

    # ------------------------
    # TLS Keys and Fingerprint
    # ------------------------
    def ensure_tls_keys(self):
        if not Path(CERT_FILE).exists() or not Path(KEY_FILE).exists():
            self.add_notification("Generating self-signed TLS keys...")
            self.generate_tls_keys()
        with open(CERT_FILE, "rb") as f:
            data = f.read()
            self.key_fingerprint = hashlib.sha256(data).hexdigest()
        self.satellite_id = self.key_fingerprint[:8]
        print(f"Satellite TLS fingerprint: {self.key_fingerprint}")

    def generate_tls_keys(self):
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"LibreMesh"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"LibreMesh Satellite"),
        ])
        cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
            key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(
            datetime.datetime.utcnow()).not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650)
        ).sign(key, hashes.SHA256(), default_backend())

        with open(KEY_FILE, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))
        with open(CERT_FILE, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

    # ------------------------
    # Trusted List
    # ------------------------
    def load_origin_keys(self):
        if IS_ORIGIN:
            if not Path(ORIGIN_PRIVKEY_FILE).exists():
                # generate signing key for origin
                priv = ed25519.Ed25519PrivateKey.generate()
                with open(ORIGIN_PRIVKEY_FILE, "wb") as f:
                    f.write(priv.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption()
                    ))
                pub = priv.public_key()
                with open(ORIGIN_PUBKEY_FILE, "wb") as f:
                    f.write(pub.public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo
                    ))
            with open(ORIGIN_PRIVKEY_FILE, "rb") as f:
                self.origin_privkey = serialization.load_pem_private_key(f.read(), password=None)
            with open(ORIGIN_PUBKEY_FILE, "rb") as f:
                self.origin_pubkey = serialization.load_pem_public_key(f.read())
        else:
            with open(ORIGIN_PUBKEY_FILE, "rb") as f:
                self.origin_pubkey = serialization.load_pem_public_key(f.read())

    def generate_trusted_list(self):
        if not IS_ORIGIN:
            return
        payload = {"version": 1, "satellites": [{"ip": "127.0.0.1", "port": NODE_PORT, "fingerprint": self.key_fingerprint}]}
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        signature = self.origin_privkey.sign(payload_bytes)
        payload["signature"] = base64.b64encode(signature).decode()
        with open(TRUSTED_LIST_FILE, "w") as f:
            json.dump(payload, f, indent=2)
        self.add_notification(f"Origin created signed trusted list: {TRUSTED_LIST_FILE}")
        print("Base64 signature for GitHub copy:", payload["signature"])

    def fetch_trusted_list(self):
        if IS_ORIGIN:
            return
        try:
            with urllib.request.urlopen(TRUSTED_LIST_URL) as resp:
                data = json.loads(resp.read())
            signature_b64 = data.pop("signature", None)
            if not signature_b64:
                self.add_notification("Trusted list missing signature")
                return
            payload_bytes = json.dumps(data, sort_keys=True).encode()
            signature = base64.b64decode(signature_b64)
            self.origin_pubkey.verify(signature, payload_bytes)
            self.add_notification("Trusted list signature verified")
            for sat in data["satellites"]:
                self.peers[sat["fingerprint"][:8]] = (sat["ip"], sat["port"])
        except Exception as e:
            self.add_notification(f"Failed to fetch/verify trusted list: {e}")

    # ------------------------
    # Server start
    # ------------------------
    async def start_server(self):
        self.ensure_tls_keys()
        self.load_origin_keys()
        self.generate_trusted_list()
        self.fetch_trusted_list()

        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
        server = await asyncio.start_server(self.handle_connection, "0.0.0.0", NODE_PORT, ssl=ssl_ctx)
        self.add_notification(f"Satellite listening on port {NODE_PORT}")
        async with server:
            await server.serve_forever()

# ----------------------------
# Main
# ----------------------------
def main():
    sat = Satellite()
    loop = asyncio.get_event_loop()
    loop.create_task(sat.repair_worker())
    loop.run_until_complete(sat.start_server())

if __name__ == "__main__":
    main()
