import asyncio
import ssl
import os
import socket
import datetime
import time

SAT_PORT = 4001
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

connected_nodes = {}
repair_queue = []
notifications = []

MAX_NOTIFICATIONS = 10

# Generate TLS cert if missing
if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
    print("TLS cert/key not found, generating self-signed certificate...")
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    with open(KEY_FILE, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"LibreMesh"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"LibreMesh Satellite"),
    ])
    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
        key.public_key()
    ).serial_number(x509.random_serial_number()).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
    ).sign(key, hashes.SHA256(), default_backend())

    with open(CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f"Generated {CERT_FILE} and {KEY_FILE}")

ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

def add_notification(msg):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    notifications.append(f"{timestamp} - {msg}")
    if len(notifications) > MAX_NOTIFICATIONS:
        notifications.pop(0)

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def display_table():
    clear_screen()
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for node_id, node in connected_nodes.items():
        uptime = int(time.time() - node["start_time"])
        print(f"{node_id:<15}{node['region']:<10}{node['rank']:<6}{uptime:<10}{','.join(node['fragments'])}")
    print("\n=== Repair Queue ===")
    if repair_queue:
        for idx, frag in enumerate(repair_queue, 1):
            print(f"{idx}. {frag}")
    else:
        print("No repair jobs queued.")
    print("======================================================================")
    print("\n=== Notifications (last 10) ===")
    for note in notifications:
        print(note)
    print("======================================================================")

async def handle_node(reader, writer):
    addr = writer.get_extra_info('peername')
    add_notification(f"Node connected: {addr}")

    try:
        while True:
            data = await reader.read(1024)
            if not data:
                break
            # Expect heartbeat: NODEID|REGION|UPTIME|frag1,frag2,...
            msg = data.decode()
            parts = msg.strip().split("|")
            if len(parts) != 4:
                continue
            node_id, region, _, frags = parts
            frags_list = frags.split(",")

            if node_id not in connected_nodes:
                connected_nodes[node_id] = {
                    "region": region,
                    "rank": 85,  # default for demo
                    "fragments": frags_list,
                    "start_time": time.time()
                }
            else:
                connected_nodes[node_id]["fragments"] = frags_list

            # Simulate repair job for each fragment (for testing)
            for frag in frags_list:
                if frag not in repair_queue:
                    repair_queue.append(frag)
                    add_notification(f"Repair job queued for fragment {frag}")
                    asyncio.create_task(process_repair(frag))

            display_table()

    except Exception as e:
        add_notification(f"Error with node {addr}: {e}")
    finally:
        add_notification(f"Node disconnected: {addr}")
        for node_id, node in list(connected_nodes.items()):
            if node["region"] == region and addr[1] == writer.get_extra_info('sockname')[1]:
                del connected_nodes[node_id]
        display_table()
        writer.close()
        await writer.wait_closed()

async def process_repair(frag):
    await asyncio.sleep(10)  # slow down repairs for visibility
    add_notification(f"Processing repair for fragment {frag}")
    if frag in repair_queue:
        repair_queue.remove(frag)
    display_table()

async def main():
    server = await asyncio.start_server(handle_node, '0.0.0.0', SAT_PORT, ssl=ssl_context)
    add_notification(f"Satellite listening on port {SAT_PORT}")
    hostname = socket.gethostname()
    add_notification(f"Hostname: {hostname}")
    display_table()
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSatellite shutting down...")
