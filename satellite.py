import asyncio
import ssl
import os
import json
from datetime import datetime

HOST = "0.0.0.0"
PORT = 4001
REPAIR_PROCESS_DELAY = 10  # slowed down for visible queue

ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
if not os.path.exists("cert.pem") or not os.path.exists("key.pem"):
    print("TLS cert/key not found, generating self-signed certificate...")
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime as dt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with open("key.pem", "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"CA"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"LibreMesh"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(x509.random_serial_number()
    ).not_valid_before(dt.datetime.utcnow()
    ).not_valid_after(dt.datetime.utcnow() + dt.timedelta(days=365)
    ).sign(key, hashes.SHA256())
    with open("cert.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print("-----\nGenerated cert.pem and key.pem")

ssl_context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

nodes = {}
repair_queue = asyncio.Queue()
notifications = []
MAX_NOTIFICATIONS = 10

def add_notification(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    notifications.append(f"{timestamp} - {msg}")
    if len(notifications) > MAX_NOTIFICATIONS:
        notifications.pop(0)

def print_table():
    os.system("clear")
    print("=== Repair Queue ===")
    if repair_queue.empty():
        print("No repair jobs queued.")
    else:
        for idx, item in enumerate(list(repair_queue._queue)):
            print(f"{idx+1}. {item}")
    print("="*70)
    print("=== Notifications (last 10) ===")
    for note in notifications:
        print(note)
    print("="*70)

async def repair_worker():
    while True:
        frag = await repair_queue.get()
        add_notification(f"Processing repair for fragment {frag}")
        print_table()
        await asyncio.sleep(REPAIR_PROCESS_DELAY)
        repair_queue.task_done()

async def handle_node(reader, writer):
    addr = writer.get_extra_info('peername')
    add_notification(f"Node connected: {addr}")
    print_table()

    while True:
        try:
            data = await reader.readline()
            if not data:
                break
            message = json.loads(data.decode())
            if message.get("type") == "repair_request":
                frag = message.get("fragment_id")
                await repair_queue.put(frag)
                add_notification(f"Repair job queued for fragment {frag}")
                print_table()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            break
    writer.close()
    await writer.wait_closed()
    add_notification(f"Node disconnected: {addr}")
    print_table()

async def start_server():
    server = await asyncio.start_server(handle_node, HOST, PORT, ssl=ssl_context)
    add_notification(f"Satellite listening on port {PORT}")
    print_table()
    asyncio.create_task(repair_worker())
    async with server:
        await server.serve_forever()

async def main():
    try:
        await start_server()
    except KeyboardInterrupt:
        print("\nSatellite shutting down.")

if __name__ == "__main__":
    asyncio.run(main())
