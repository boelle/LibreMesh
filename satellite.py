import asyncio
import ssl
import os
from datetime import datetime

PORT = 4001
REPAIR_DELAY = 10  # seconds
MAX_NOTIFICATIONS = 10

connected_nodes = {}
repair_queue = []
notifications = []

# TLS setup
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
    print("TLS cert/key not found, generating self-signed certificate...")
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    import datetime as dt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"LibreMesh Satellite")])
    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
        key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(
        dt.datetime.utcnow()).not_valid_after(
        dt.datetime.utcnow() + dt.timedelta(days=365)).sign(key, hashes.SHA256(), default_backend())

    with open(CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(KEY_FILE, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    print("Generated cert.pem and key.pem")

ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

# Node fragment example
example_fragments = ["frag1", "frag2", "frag3", "frag4", "frag5"]

async def handle_node(reader, writer):
    addr = writer.get_extra_info('peername')
    node_id = f"node{addr[1]}"
    connected_nodes[node_id] = {
        "addr": addr,
        "fragments": example_fragments.copy(),
        "rank": 85,
        "region": "EU",
        "connected_since": datetime.utcnow()
    }
    add_notification(f"Node connected: {addr}")
    update_table()
    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            msg = data.decode().strip()
            if msg.startswith("REPAIR"):
                fragment = msg.split()[1]
                queue_repair(fragment)
    except Exception:
        pass
    finally:
        add_notification(f"Node disconnected: {addr}")
        if node_id in connected_nodes:
            del connected_nodes[node_id]
        update_table()
        writer.close()
        await writer.wait_closed()

def add_notification(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    notifications.append(f"{timestamp} - {message}")
    if len(notifications) > MAX_NOTIFICATIONS:
        notifications.pop(0)

def queue_repair(fragment):
    repair_queue.append(fragment)
    add_notification(f"Repair job queued for fragment {fragment}")
    asyncio.create_task(process_repair(fragment))

async def process_repair(fragment):
    await asyncio.sleep(REPAIR_DELAY)
    add_notification(f"Processing repair for fragment {fragment}")
    if fragment in repair_queue:
        repair_queue.remove(fragment)
    update_table()

def update_table():
    os.system("clear")
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for node_id, info in connected_nodes.items():
        uptime_sec = int((datetime.utcnow() - info["connected_since"]).total_seconds())
        print(f"{node_id:<15}{info['region']:<10}{info['rank']:<6}{uptime_sec:<10}{','.join(info['fragments'])}")
    if not connected_nodes:
        print()
    print("\n=== Repair Queue ===")
    if repair_queue:
        for idx, frag in enumerate(repair_queue, start=1):
            print(f"{idx}. {frag}")
    else:
        print("No repair jobs queued.")
    print("======================================================================\n")
    print("=== Notifications (last 10) ===")
    for note in notifications[-MAX_NOTIFICATIONS:]:
        print(note)
    print("======================================================================\n")

async def start_server():
    server = await asyncio.start_server(handle_node, "0.0.0.0", PORT, ssl=ssl_context)
    add_notification(f"Satellite listening on port {PORT}")
    update_table()
    async with server:
        await server.serve_forever()

async def main():
    await start_server()

if __name__ == "__main__":
    asyncio.run(main())
