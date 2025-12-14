#!/usr/bin/env python3
import asyncio
import os
import ssl
import time
import datetime
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

CERTFILE = "cert.pem"
KEYFILE = "key.pem"
HANDSHAKE_TIMEOUT = 10

class Node:
    def __init__(self, node_id, region):
        self.node_id = node_id
        self.region = region
        self.rank = 100  # optional, can be calculated later
        self.uptime = 0
        self.last_seen = 0
        self.fragments = []

        self._connected_time = time.time()
        self._last_activity = time.time()

    def activity(self):
        self.last_seen = 0
        self._last_activity = time.time()

    def tick(self):
        self.uptime = int(time.time() - self._connected_time)
        self.last_seen = int(time.time() - self._last_activity)

class Satellite:
    def __init__(self, host="0.0.0.0", port=4001):
        self.host = host
        self.port = port
        self.nodes = {}
        self.repair_queue = []
        self.notifications = []
        self.fingerprint = self.ensure_keys()

    def ensure_keys(self):
        if not (os.path.exists(CERTFILE) and os.path.exists(KEYFILE)):
            self.create_self_signed_cert()
        # Load key for fingerprint
        with open(KEYFILE, "rb") as f:
            priv = ed25519.Ed25519PrivateKey.from_private_bytes(f.read())
        pub = priv.public_key()
        pub_bytes = pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return pub_bytes.hex()

    def create_self_signed_cert(self):
        # create ed25519 private key
        priv = ed25519.Ed25519PrivateKey.generate()
        priv_bytes = priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )
        with open(KEYFILE, "wb") as f:
            f.write(priv_bytes)
        # create dummy self-signed cert (PEM)
        with open(CERTFILE, "w") as f:
            f.write("-----BEGIN CERTIFICATE-----\n")
            f.write("MIIDdzCCAl+gAwIBAgIUdummyCERTIFICATE==\n")
            f.write("-----END CERTIFICATE-----\n")

    async def handle_client(self, reader, writer):
        peer = writer.get_extra_info('peername')[0]
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=HANDSHAKE_TIMEOUT)
            if not line:
                writer.close()
                await writer.wait_closed()
                return
            parts = line.decode().strip().split(":")
            if parts[0] == "HEARTBEAT":
                node_id, region, uptime = parts[1], parts[2], int(parts[3])
                if node_id not in self.nodes:
                    node = Node(node_id, region)
                    self.nodes[node_id] = node
                    self.notifications.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Node registered: {node_id}")
                self.nodes[node_id].activity()
        except Exception as e:
            self.notifications.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Client error: {str(e)}")
        finally:
            # Do not close connection to keep alive
            pass

    async def ui_loop(self):
        while True:
            os.system("clear")
            # Node status
            print("+-------------------------------------------------------------+")
            print("|                     Satellite Node Status                  |")
            print("+------------+----------+------+----------+-----------------+")
            print("| Node ID    | Region   | Rank | Uptime   | Fragments       |")
            print("+------------+----------+------+----------+-----------------+")
            for node in self.nodes.values():
                node.tick()
                frag_str = ",".join(node.fragments)
                print(f"| {node.node_id:<10} | {node.region:<8} | {node.rank:<4} | {node.uptime:<8} | {frag_str:<15} |")
            print("+-------------------------------------------------------------+")
            # Repair Queue
            print("\n+-------------------------------------------+")
            print("|                Repair Queue               |")
            print("+------------+----------------+------------+")
            for job in self.repair_queue:
                print(f"| {job['fragment']:<10} | {job['requested_by']:<14} | {job.get('claimed_by',''):<10} |")
            print("+-------------------------------------------+")
            # Notifications
            print("\n+------------------------------------------------+")
            print("|                  Notifications                |")
            print("+------------------------------------------------+")
            for note in self.notifications[-10:]:
                print(f"| {note:<46} |")
            print("+------------------------------------------------+")
            # Suspicious IPs advisory (empty for now)
            print("\n+-----------------------------------------------+")
            print("|               Suspicious IPs Advisory        |")
            print("+------------+------------+---------+----------+")
            print("| IP         | Connections| Penalty | Last Seen|")
            print("+------------+------------+---------+----------+")
            print("+-----------------------------------------------+\n")
            print(f"Satellite ID: {self.fingerprint[:8]}")
            print(f"TLS Fingerprint: {self.fingerprint}")
            await asyncio.sleep(1)

    async def start_server(self):
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(CERTFILE, KEYFILE)
        server = await asyncio.start_server(self.handle_client, self.host, self.port, ssl=ssl_ctx)
        await asyncio.gather(server.serve_forever(), self.ui_loop())

def main():
    sat = Satellite()
    print(f"Satellite TLS fingerprint: {sat.fingerprint[:8]}")
    asyncio.run(sat.start_server())

if __name__ == "__main__":
    main()
