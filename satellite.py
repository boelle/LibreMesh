import asyncio
import ssl
import os
import datetime

PORT = 4001

# Simulated node info
connected_nodes = {}
repair_queue = []
notifications = []

MAX_NOTIFICATIONS = 10

# Dummy fragments for repair
fragments = ["frag1", "frag2", "frag3", "frag4", "frag5"]

# SSL setup
ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
if not os.path.exists("cert.pem") or not os.path.exists("key.pem"):
    print("TLS cert/key not found, generating self-signed certificate...")
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"CA"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"LibreMesh"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"LibreMesh"),
    ])
    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
        key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(
        datetime.datetime.utcnow()).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=365)).sign(key, hashes.SHA256(), default_backend())
    with open("cert.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open("key.pem", "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
ssl_context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

# Node uptime tracking
node_start_times = {}

# Table display
def update_table():
    os.system('clear')
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for node, info in connected_nodes.items():
        uptime = int((datetime.datetime.now() - node_start_times[node]).total_seconds())
        print(f"{node:<15}{info['region']:<10}{info['rank']:<6}{uptime:<10}{','.join(info['fragments'])}")
    print("\n=== Repair Queue ===")
    if repair_queue:
        for idx, frag in enumerate(repair_queue, 1):
            print(f"{idx}. {frag}")
    else:
        print("No repair jobs queued.")
    print("======================================================================")
    print("\n=== Notifications (last 10) ===")
    for note in notifications[-MAX_NOTIFICATIONS:]:
        print(note)
    print("======================================================================\n")

def log_notification(msg):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    notifications.append(f"{timestamp} - {msg}")
    update_table()

async def process_repair():
    while True:
        if repair_queue:
            frag = repair_queue.pop(0)
            log_notification(f"Processing repair for fragment {frag}")
            await asyncio.sleep(10)  # slow down for visibility
            update_table()
        else:
            await asyncio.sleep(1)

async def handle_node(reader, writer):
    addr = writer.get_extra_info('peername')
    node_name = f"node{addr[1]}"
    connected_nodes[node_name] = {
        "region": "EU",
        "rank": 85,
        "fragments": fragments.copy()
    }
    node_start_times[node_name] = datetime.datetime.now()
    log_notification(f"Node connected: {addr}")

    # Queue repair jobs
    for frag in fragments:
        repair_queue.append(frag)
        log_notification(f"Repair job queued for fragment {frag}")

    try:
        while True:
            data = await reader.read(100)
            if not data:
                break
    except:
        pass
    writer.close()
    await writer.wait_closed()
    del connected_nodes[node_name]
    del node_start_times[node_name]
    log_notification(f"Node disconnected: {addr}")

async def start_server():
    server = await asyncio.start_server(handle_node, '0.0.0.0', PORT, ssl=ssl_context)
    log_notification(f"Satellite listening on port {PORT}")
    await server.serve_forever()

async def periodic_table_update():
    while True:
        update_table()
        await asyncio.sleep(1)

async def main():
    # Start repair worker
    asyncio.create_task(process_repair())
    # Start server
    asyncio.create_task(start_server())
    # Start periodic table updater
    await periodic_table_update()

if __name__ == "__main__":
    asyncio.run(main())
