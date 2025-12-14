import asyncio
import socket
import ssl
import json
import time
import os
import textwrap
import base64
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from datetime import datetime, timedelta

# --- Global Configuration and State ---
LISTEN_HOST = '0.0.0.0'
LISTEN_PORT = 8888
NODE_TIMEOUT = 60 # seconds

NODES = {}
REPAIR_QUEUE = asyncio.Queue()
SATELLITE_ID = None
TLS_FINGERPRINT = None
ORIGIN_PUBKEY_PEM = None
ORIGIN_PRIVKEY_PEM = None # We now manage the origin private key as well
LIST_JSON_PATH = 'list.json'
ORIGIN_PUBKEY_PATH = 'origin_pubkey.pem'
ORIGIN_PRIVKEY_PATH = 'origin_privkey.pem' # Path for new private key file
CERT_PATH = 'cert.pem'
KEY_PATH = 'key.pem'
UI_NOTIFICATIONS = asyncio.Queue(maxsize=10)


# --- Helper Functions ---
def sign_and_save_satellite_list():
    """
    Generates the list.json with the current satellite's info,
    signs it using the origin private key, and saves the file.
    """
    if not ORIGIN_PRIVKEY_PEM:
        print("ERROR: Origin private key not loaded. Cannot sign list.json.")
        return

    # Load the private key object from the PEM bytes
    private_key = serialization.load_pem_private_key(
        ORIGIN_PRIVKEY_PEM,
        password=None,
        backend=default_backend()
    )

    # Data structure for list.json (contains signed data)
    satellites_list_data = {
        "satellites": [
            {
                "id": SATELLITE_ID,
                "fingerprint": TLS_FINGERPRINT,
                "hostname": LISTEN_HOST,
                "port": LISTEN_PORT
            }
            # More satellites would go here in a multi-satellite setup
        ]
    }
    
    # Convert data to JSON string for signing
    json_data_bytes = json.dumps(satellites_list_data, indent=4, sort_keys=True).encode('utf-8')

    # Sign the data
    signature = private_key.sign(
        json_data_bytes,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )

    # Prepare final structure with data and signature
    final_list_structure = {
        "data": satellites_list_data,
        "signature": base64.b64encode(signature).decode('utf-8')
    }

    # Save to list.json
    with open(LIST_JSON_PATH, 'w') as f:
        json.dump(final_list_structure, f, indent=4)
    
    print(f"Generated and signed {LIST_JSON_PATH}.")


def generate_keys_and_certs():
    """Generates satellite keys and origin pubkey/privkey if missing."""
    print("Checking for existing keys and certificates...")
    
    # 1. Generate/Load Satellite TLS Key and Cert
    if not os.path.exists(CERT_PATH) or not os.path.exists(KEY_PATH):
        print("Generating new satellite cert.pem and key.pem...")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
        ])
        cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.utcnow()).not_valid_after(datetime.utcnow() + timedelta(days=3650)).add_extension(x509.SubjectAlternativeName([x509.DNSName(u"localhost")]), critical=False,).sign(private_key=key, algorithm=hashes.SHA256(), backend=default_backend())

        with open(KEY_PATH, "wb") as f:
            f.write(key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.TraditionalOpenSSL, encryption_algorithm=serialization.NoEncryption()))
        with open(CERT_PATH, "wb") as f:
            f.write(cert.public_bytes(encoding=serialization.Encoding.PEM))
        print("Satellite cert.pem and key.pem generated.")
    else:
        print("Reusing existing satellite cert.pem and key.pem.")

    # 2. Generate/Load Origin Pubkey/Privkey
    global ORIGIN_PUBKEY_PEM, ORIGIN_PRIVKEY_PEM
    
    # Check for the presence of both parts of the origin key pair
    if not os.path.exists(ORIGIN_PUBKEY_PATH) or not os.path.exists(ORIGIN_PRIVKEY_PATH):
        print(f"Generating new master origin key pair ({ORIGIN_PUBKEY_PATH} and {ORIGIN_PRIVKEY_PATH})...")
        origin_priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        origin_pub_key = origin_priv_key.public_key()
        
        ORIGIN_PUBKEY_PEM = origin_pub_key.public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
        ORIGIN_PRIVKEY_PEM = origin_priv_key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.TraditionalOpenSSL, encryption_algorithm=serialization.NoEncryption())

        with open(ORIGIN_PUBKEY_PATH, "wb") as f:
            f.write(ORIGIN_PUBKEY_PEM)
        with open(ORIGIN_PRIVKEY_PATH, "wb") as f:
            f.write(ORIGIN_PRIVKEY_PEM)
        print("Master origin keys generated and saved.")
    else:
        with open(ORIGIN_PUBKEY_PATH, "rb") as f:
            ORIGIN_PUBKEY_PEM = f.read().strip()
        with open(ORIGIN_PRIVKEY_PATH, "rb") as f:
            ORIGIN_PRIVKEY_PEM = f.read().strip()
        print("Reusing existing master origin keys.")
    
    # 3. Derive Satellite ID and Fingerprint (must be stable)
    global SATELLITE_ID, TLS_FINGERPRINT
    with open(CERT_PATH, 'rb') as f:
        cert_data = f.read()
    cert = x509.load_pem_x509_certificate(cert_data, default_backend())
    # FIX: get_attributes_for_oid returns a list; access the first item in the list and then its value
    SATELLITE_ID = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    # TLS Fingerprint (SHA1 hash of the DER encoding of the cert) - remains stable if cert file doesn't change
    TLS_FINGERPRINT = cert.fingerprint(hashes.SHA1()).hex(':')
    print(f"Satellite ID: {SATELLITE_ID}")
    print(f"TLS Fingerprint: {TLS_FINGERPRINT}")


# --- Networking/Protocol Classes ---
class SatelliteProtocol(asyncio.Protocol):
    def __init__(self):
        self.node_id = None
        self.last_seen = time.time()
        self.uptime_start = time.time()
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        self.last_seen = time.time()
        message = data.decode().strip()
        asyncio.create_task(self.handle_client_message(message))

    async def handle_client_message(self, message):
        try:
            command, *args = message.split(' ', 1)
            
            if command == "REGISTER" and args:
                node_info = json.loads(args[0])
                self.node_id = node_info.get('node_id')
                if self.node_id not in NODES:
                    NODES[self.node_id] = {'writer': self.transport, 'last_seen': time.time(), 'uptime_start': time.time()}
                    await UI_NOTIFICATIONS.put(f"Node registered: {self.node_id}")
                else:
                    NODES[self.node_id]['writer'] = self.transport
                    NODES[self.node_id]['last_seen'] = time.time()

            elif command == "HEARTBEAT" and self.node_id:
                pass
            
            elif command == "REPAIR_REQUEST":
                pass # Ignored as satellite handles initiation internally now

            else:
                print(f"Unknown command or no node ID: {command}")

        except json.JSONDecodeError:
            print(f"Invalid JSON in message: {message}")
        except Exception as e:
            print(f"Error handling message: {e}")

    def connection_lost(self, exc):
        pass # Watchdog handles timeouts


# --- Background Tasks ---
async def audit_and_queue_repairs():
    while True:
        await asyncio.sleep(45)
        if random.random() > 0.8 and REPAIR_QUEUE.empty():
            fake_fragment_id = f"frag_{random.randint(1, 5)}_checksumABC"
            fake_node_id = random.choice(list(NODES.keys())) if NODES else "unknown_node"
            job = {
                "fragment_id": fake_fragment_id,
                "requested_by_node_id": fake_node_id,
                "status": "QUEUED",
                "claimed_by": None
            }
            await REPAIR_QUEUE.put(job)

async def repair_worker():
    while True:
        job = await REPAIR_QUEUE.get()
        try:
            job["status"] = "CLAIMED"
            job["claimed_by"] = SATELLITE_ID
            await asyncio.sleep(5) 
            await UI_NOTIFICATIONS.put(f"[WORKER] Repair completed: {job['fragment_id']} for node {job['requested_by_node_id']}")
        except Exception as e:
            print(f"Error processing repair job: {e}")
        finally:
            REPAIR_QUEUE.task_done()

async def watchdog_task():
    while True:
        await asyncio.sleep(1)
        current_time = time.time()
        for node_id, data in NODES.items():
            data['last_seen_seconds'] = int(current_time - data['last_seen'])
            data['uptime_seconds'] = int(current_time - data['uptime_start'])


async def display_ui():
    HEADER_WIDTH = 54
    while True:
        os.system('clear' if os.name == 'posix' else 'cls')

        # 1. Satellite Node Status
        print("=" * HEADER_WIDTH)
        print("Satellite Node Status".center(HEADER_WIDTH))
        print("=" * HEADER_WIDTH)
        print("Node ID             | Rank | Last Seen (s) | Uptime (s)")
        print("-" * HEADER_WIDTH)
        for node_id, data in NODES.items():
            last_seen = data.get('last_seen_seconds', 0)
            uptime = data.get('uptime_seconds', 0)
            rank = 100
            print(f"{node_id:19} | {rank:4} | {last_seen:13} | {uptime:10}")
        if not NODES:
             print(f"{'No nodes connected':19} | {'N/A':4} | {'N/A':13} | {'N/A':10}")

        # 2. Repair Queue
        print("\n" + "=" * HEADER_WIDTH)
        print("Repair Queue".center(HEADER_WIDTH))
        print("=" * HEADER_WIDTH)
        print("Job ID (Fragment)              | Status | Claimed By")
        print("-" * HEADER_WIDTH)
        queue_items = list(REPAIR_QUEUE._queue)
        for job in queue_items:
            frag_id_short = job['fragment_id'][:30]
            status = job['status']
            claimed = job['claimed_by'] or 'None'
            print(f"{frag_id_short:30} | {status:6} | {claimed}")
        if not queue_items:
             print(f"{'Queue is empty':30} | {'N/A':6} | {'N/A':14}")

        # 3. Notifications
        print("\n" + "=" * HEADER_WIDTH)
        print("Notifications".center(HEADER_WIDTH))
        print("=" * HEADER_WIDTH)
        while not UI_NOTIFICATIONS.empty():
            notif = await UI_NOTIFICATIONS.get()
            print(f"- {datetime.now().strftime('%H:%M:%S')} | {notif}")
        print("\n" * (5 - UI_NOTIFICATIONS.qsize()))

        # 4. Suspicious IPs Advisory
        print("\n" + "=" * HEADER_WIDTH)
        print("Suspicious IPs Advisory".center(HEADER_WIDTH))
        print("=" * HEADER_WIDTH)
        print("No suspicious activity detected.")

        # 5. Satellite ID + TLS Fingerprint
        print("\n" + "=" * HEADER_WIDTH)
        print("Satellite ID + TLS Fingerprint".center(HEADER_WIDTH))
        print("=" * HEADER_WIDTH)
        print(f"Satellite ID:    {SATELLITE_ID}")
        print(f"TLS Fingerprint: {TLS_FINGERPRINT}")
        print("=" * HEADER_WIDTH)

        await asyncio.sleep(1)


async def main():
    generate_keys_and_certs() # Setup keys/certs on startup
    sign_and_save_satellite_list() # Create the signed list.json

    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile=CERT_PATH, keyfile=KEY_PATH)

    loop = asyncio.get_running_loop()
    server = await loop.create_server(
        SatelliteProtocol, LISTEN_HOST, LISTEN_PORT, ssl=ssl_context
    )

    print(f"Serving on {LISTEN_HOST}:{LISTEN_PORT} (TLS enabled)...")

    asyncio.create_task(display_ui())
    asyncio.create_task(watchdog_task())
    asyncio.create_task(audit_and_queue_repairs())
    asyncio.create_task(repair_worker())

    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    import random
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Satellite shutting down.")
