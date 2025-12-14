#!/usr/bin/env python3
import asyncio
import ssl
import os
import datetime
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography import x509
from cryptography.x509.oid import NameOID
import ipaddress

CERTFILE = "cert.pem"
KEYFILE = "key.pem"
HANDSHAKE_TIMEOUT = 10

class Satellite:
    def __init__(self):
        self.nodes = {}
        self.repair_queue = []
        self.notifications = []
        self.suspicious_ips = {}
        self.fingerprint = self.ensure_keys()
        self.id = self.fingerprint[:8]

    def ensure_keys(self):
        if not os.path.exists(KEYFILE) or not os.path.exists(CERTFILE):
            self.generate_self_signed_cert()
        # Load the key to get fingerprint
        with open(CERTFILE, "rb") as f:
            pem_data = f.read()
        import hashlib
        fp = hashlib.sha256(pem_data).hexdigest()
        return fp

    def generate_self_signed_cert(self):
        # Generate private key
        key = ed25519.Ed25519PrivateKey.generate()
        priv_bytes = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()
        )
        with open(KEYFILE, "wb") as f:
            f.write(priv_bytes)

        # Generate self-signed certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"LibreMesh Satellite"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"LibreMesh Satellite"),
        ])
        cert = x509.CertificateBuilder().subject_name(subject).issuer_name(
            issuer
        ).public_key(key.public_key()).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=3650)
        ).sign(key, algorithm=None)
        cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
        with open(CERTFILE, "wb") as f:
            f.write(cert_bytes)

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        ip = addr[0]
        if ip not in self.suspicious_ips:
            self.suspicious_ips[ip] = {"connections": 1, "penalty": 0, "last_seen": 0}
        else:
            self.suspicious_ips[ip]["connections"] += 1
            self.suspicious_ips[ip]["last_seen"] = 0

        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=HANDSHAKE_TIMEOUT)
                if not line:
                    break
                # process line
                msg = line.decode().strip()
                if msg.startswith("HEARTBEAT"):
                    parts = msg.split(":")
                    node_id = parts[1]
                    region = parts[2]
                    uptime = int(parts[3])
                    now = datetime.datetime.utcnow()
                    if node_id not in self.nodes:
                        self.nodes[node_id] = {
                            "region": region,
                            "uptime": uptime,
                            "last_seen": 0,
                            "fragments": [],
                            "last_activity": now
                        }
                        self.notifications.append(f"[{now.strftime('%H:%M:%S')}] Node registered: {node_id}")
                    else:
                        self.nodes[node_id]["uptime"] = uptime
                        self.nodes[node_id]["last_seen"] = 0
                        self.nodes[node_id]["last_activity"] = now
        except Exception as e:
            self.notifications.append(f"[{datetime.datetime.utcnow().strftime('%H:%M:%S')}] Client error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def ui_loop(self):
        while True:
            self.print_ui()
            # Update last_seen counters
            for node in self.nodes.values():
                delta = datetime.datetime.utcnow() - node["last_activity"]
                node["last_seen"] = int(delta.total_seconds())
            for ip in self.suspicious_ips.values():
                ip["last_seen"] += 1
            await asyncio.sleep(1)

    def print_ui(self):
        # Simplified UI
        print("\n+-------------------------------------------------------------+")
        print("|                     Satellite Node Status                  |")
        print("+------------+----------+------+----------+-----------------+")
        print("| Node ID    | Region   | Rank | Uptime   | Fragments       |")
        print("+------------+----------+------+----------+-----------------+")
        for node_id, node in self.nodes.items():
            print(f"| {node_id:<10} | {node['region']:<8} | 100  | {node['uptime']:<8} | {' '.join(node['fragments']):<15} |")
        print("+-------------------------------------------------------------+")
        print(f"\nSatellite ID: {self.id}")
        print(f"TLS Fingerprint: {self.fingerprint}")

    async def start_server(self):
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(CERTFILE, KEYFILE)
        server = await asyncio.start_server(self.handle_client, "0.0.0.0", 4001, ssl=ssl_ctx)
        async with server:
            await asyncio.gather(server.serve_forever(), self.ui_loop())

def main():
    sat = Satellite()
    print(f"Satellite TLS fingerprint: {sat.fingerprint}")
    asyncio.run(sat.start_server())

if __name__ == "__main__":
    main()
