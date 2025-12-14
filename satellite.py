#!/usr/bin/env python3
import asyncio
import os
import ssl
import time
import datetime
import random
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

HOST = "0.0.0.0"
PORT = 4001
KEYFILE = "cert.key"
CERTFILE = "cert.pem"
HANDSHAKE_TIMEOUT = 10
UI_REFRESH_INTERVAL = 1  # seconds
REPAIR_EXECUTION_TIME = 3  # seconds for demo

class Node:
    def __init__(self, node_id, region, public_key):
        self.node_id = node_id
        self.region = region
        self.public_key = public_key
        self.uptime = 0
        self.last_seen = 0
        self.fragments = []
        self.rank = 100  # Optional placeholder

class RepairJob:
    def __init__(self, fragment, requested_by):
        self.fragment = fragment
        self.requested_by = requested_by
        self.claimed_by = None

class Satellite:
    def __init__(self):
        self.nodes = {}
        self.repair_queue = []
        self.notifications = []
        self.suspicious_ips = {}
        self.fingerprint = self.ensure_keys()
        self.server = None

    def ensure_keys(self):
        if not os.path.exists(KEYFILE) or not os.path.exists(CERTFILE):
            # generate ed25519 keypair
            priv = ed25519.Ed25519PrivateKey.generate()
            pub = priv.public_key()
            priv_bytes = priv.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
            pub_bytes = pub.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw
            )
            with open(KEYFILE, "wb") as f:
                f.write(priv_bytes)
            with open(CERTFILE, "wb") as f:
                f.write(pub_bytes)
        else:
            with open(KEYFILE, "rb") as f:
                priv_bytes = f.read()
        # Return fingerprint for display (hex of pub key)
        priv = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
        pub_bytes = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return pub_bytes.hex()[:8]  # short fingerprint

    async def handle_client(self, reader, writer):
        peer = writer.get_extra_info("peername")
        ip = peer[0]
        self.suspicious_ips.setdefault(ip, {"connections": 0, "penalty": 0, "last_seen": 0})
        self.suspicious_ips[ip]["connections"] += 1

        node = None
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=None)
                if not line:
                    break
                line = line.decode().strip()
                self.suspicious_ips[ip]["last_seen"] = 0  # reset on any activity

                if line.startswith("IDENT:"):
                    _, node_id, region, pubkey_hex = line.split(":")
                    if node_id not in self.nodes:
                        node = Node(node_id, region, pubkey_hex)
                        self.nodes[node_id] = node
                        self.add_notification(f"Node registered: {node_id}")
                    else:
                        node = self.nodes[node_id]

                elif line.startswith("HEARTBEAT:"):
                    _, node_id, region, uptime = line.split(":")
                    if node_id in self.nodes:
                        n = self.nodes[node_id]
                        n.uptime = int(uptime)
                        node = n
                elif line.startswith("REPAIR:"):
                    _, node_id, fragment = line.split(":")
                    job = RepairJob(fragment, node_id)
                    self.repair_queue.append(job)
                    self.add_notification(f"Repair requested: {fragment} by {node_id}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.add_notification(f"Client error: {e}")
        finally:
            if node:
                self.add_notification(f"Node disconnected: {node.node_id}")
            writer.close()
            await writer.wait_closed()

    def add_notification(self, msg):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {msg}"
        self.notifications.append(entry)
        if len(self.notifications) > 10:
            self.notifications.pop(0)

    async def repair_worker(self):
        while True:
            if self.repair_queue:
                job = self.repair_queue.pop(0)
                job.claimed_by = self.fingerprint
                self.add_notification(f"Satellite claimed job: {job.fragment}")
                await asyncio.sleep(REPAIR_EXECUTION_TIME)
                self.add_notification(f"Repair completed: {job.fragment}")
            else:
                await asyncio.sleep(0.5)

    async def ui_loop(self):
        while True:
            os.system("clear")
            print("+" + "-"*61 + "+")
            print("|                     Satellite Node Status                  |")
            print("+" + "-"*12 + "+" + "-"*10 + "+" + "-"*6 + "+" + "-"*10 + "+" + "-"*17 + "+")
            print("| Node ID    | Region   | Rank | Uptime   | Fragments       |")
            print("+" + "-"*12 + "+" + "-"*10 + "+" + "-"*6 + "+" + "-"*10 + "+" + "-"*17 + "+")
            for n in self.nodes.values():
                frags = ",".join(n.fragments)
                print(f"| {n.node_id:<10} | {n.region:<8} | {n.rank:<4} | {n.uptime:<8} | {frags:<15} |")
            print("+" + "-"*61 + "+\n")

            print("+" + "-"*43 + "+")
            print("|                Repair Queue               |")
            print("+" + "-"*12 + "+" + "-"*16 + "+" + "-"*12 + "+")
            print("| Fragment   | Requested By   | Claimed By |")
            print("+" + "-"*12 + "+" + "-"*16 + "+" + "-"*12 + "+")
            for job in self.repair_queue:
                claimed = job.claimed_by if job.claimed_by else ""
                print(f"| {job.fragment:<10} | {job.requested_by:<14} | {claimed:<10} |")
            print("+" + "-"*43 + "+\n")

            print("+" + "-"*48 + "+")
            print("|                  Notifications                |")
            print("+" + "-"*48 + "+")
            for note in self.notifications:
                print(f"| {note:<46} |")
            print("+" + "-"*48 + "+\n")

            print("+" + "-"*47 + "+")
            print("|               Suspicious IPs Advisory        |")
            print("+" + "-"*12 + "+" + "-"*12 + "+" + "-"*9 + "+" + "-"*10 + "+")
            print("| IP         | Connections| Penalty | Last Seen|")
            print("+" + "-"*12 + "+" + "-"*12 + "+" + "-"*9 + "+" + "-"*10 + "+")
            for ip, info in self.suspicious_ips.items():
                print(f"| {ip:<10} | {info['connections']:<10} | {info['penalty']:<7} | {info['last_seen']:<8} |")
            print("+" + "-"*47 + "+\n")

            print(f"Satellite ID: {self.fingerprint}")
            print(f"TLS Fingerprint: {self.fingerprint}ae2e35cecd08f067d7b5576b7ec7d406cf37e006d3568dd351590539\n")

            # increment last_seen counters
            for info in self.suspicious_ips.values():
                info["last_seen"] += UI_REFRESH_INTERVAL
            for n in self.nodes.values():
                n.last_seen += UI_REFRESH_INTERVAL

            await asyncio.sleep(UI_REFRESH_INTERVAL)

    async def start_server(self):
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        ssl_ctx.load_cert_chain(CERTFILE, KEYFILE)

        self.server = await asyncio.start_server(
            self.handle_client, HOST, PORT, ssl=ssl_ctx
        )

        self.add_notification("Satellite started")
        async with self.server:
            await asyncio.gather(
                self.server.serve_forever(),
                self.ui_loop(),
                self.repair_worker()
            )

def main():
    sat = Satellite()
    print(f"Satellite TLS fingerprint: {sat.fingerprint}")
    try:
        asyncio.run(sat.start_server())
    except KeyboardInterrupt:
        print("Satellite shutting down.")

if __name__ == "__main__":
    main()
