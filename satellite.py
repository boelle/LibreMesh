import asyncio
import ssl
import os
from datetime import datetime

PORT = 4001
REPAIR_DELAY = 10  # seconds

connected_nodes = {}
repair_queue = []
notifications = []

MAX_NOTIFICATIONS = 10

def log_notification(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    notifications.append(f"{timestamp} - {message}")
    if len(notifications) > MAX_NOTIFICATIONS:
        notifications.pop(0)

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def display_table():
    clear_screen()
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for node_id, info in connected_nodes.items():
        fragments_str = ",".join(info.get("fragments", []))
        print(f"{node_id:<15}{info.get('region',''):<10}{info.get('rank',0):<6}{info.get('uptime',0):<10}{fragments_str}")
    print("\n=== Repair Queue ===")
    if repair_queue:
        for i, frag in enumerate(repair_queue, 1):
            print(f"{i}. {frag}")
    else:
        print("No repair jobs queued.")
    print("======================================================================\n")
    print("=== Notifications (last 10) ===")
    for note in notifications:
        print(note)
    print("======================================================================\n")

async def process_repair():
    while True:
        if repair_queue:
            frag = repair_queue.pop(0)
            log_notification(f"Processing repair for fragment {frag}")
            display_table()
            await asyncio.sleep(REPAIR_DELAY)
        else:
            await asyncio.sleep(1)

async def handle_node(reader, writer):
    addr = writer.get_extra_info('peername')
    log_notification(f"Node connected: {addr}")

    # Add node immediately
    node_id = f"node_{addr[1]}"
    connected_nodes[node_id] = {
        "region": "EU",
        "rank": 85,
        "uptime": 0,
        "fragments": [f"frag{i}" for i in range(1, 6)]
    }
    display_table()

    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            msg = data.decode().strip()
            if msg.startswith("HEARTBEAT"):
                parts = msg.split()
                if len(parts) >= 2:
                    connected_nodes[node_id]["uptime"] = int(parts[1])
                    display_table()
            elif msg.startswith("REPAIR"):
                frag = msg.split()[1]
                repair_queue.append(frag)
                log_notification(f"Repair job queued for fragment {frag}")
                display_table()
    except asyncio.IncompleteReadError:
        pass
    finally:
        log_notification(f"Node disconnected: {addr}")
        connected_nodes.pop(node_id, None)
        display_table()
        writer.close()
        await writer.wait_closed()

async def start_server():
    # Ensure TLS cert/key exists
    cert_file = "cert.pem"
    key_file = "key.pem"
    if not (os.path.exists(cert_file) and os.path.exists(key_file)):
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend
        import datetime as dt

        log_notification("TLS cert/key not found, generating self-signed certificate...")

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        with open(key_file, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
                                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"LibreMesh"),
                                      x509.NameAttribute(NameOID.COMMON_NAME, u"LibreMesh")])
        cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
            key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(
            dt.datetime.utcnow()).not_valid_after(dt.datetime.utcnow() + dt.timedelta(days=3650)).add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256(),
                                                                               default_backend())
        with open(cert_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        log_notification(f"Generated {cert_file} and {key_file}")

    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile=cert_file, keyfile=key_file)

    server = await asyncio.start_server(handle_node, '0.0.0.0', PORT, ssl=ssl_context)
    log_notification(f"Satellite listening on port {PORT}")
    display_table()

    async with server:
        await server.serve_forever()

async def main():
    repair_task = asyncio.create_task(process_repair())
    await start_server()
    await repair_task

if __name__ == "__main__":
    asyncio.run(main())
