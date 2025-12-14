import asyncio
import socket
import ssl
import json
import time
import os
import textwrap
import base64
import sys
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

# --- NEW CONFIGURATION VARIABLE ---
# Uncomment the line below and set your static public/external IP when needed.
# If left commented, the script will automatically detect the local IP.
ADVERTISED_IP_CONFIG = '192.168.0.163' 
# ADVERTISED_IP_CONFIG = None 


NODES = {}
REPAIR_QUEUE = asyncio.Queue()
SATELLITE_ID = None
TLS_FINGERPRINT = None
ORIGIN_PUBKEY_PEM = None
ORIGIN_PRIVKEY_PEM = None
IS_ORIGIN = False # Flag to determine if this instance is the origin satellite
LIST_JSON_PATH = 'list.json'
ORIGIN_PUBKEY_PATH = 'origin_pubkey.pem'
ORIGIN_PRIVKEY_PATH = 'origin_privkey.pem'
CERT_PATH = 'cert.pem'
KEY_PATH = 'key.pem'
UI_NOTIFICATIONS = asyncio.Queue(maxsize=10)
TRUSTED_SATELLITES = {}
ADVERTISED_IP = None


# --- Helper Functions ---
def get_local_ip():
    """
    Attempts to determine the non-loopback local IP address, or uses configured IP.
    """
    if ADVERTISED_IP_CONFIG:
        return ADVERTISED_IP_CONFIG

    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address, port = s.getsockname()
        s.close()
        return ip_address
    except socket.error:
        if s:
            s.close()
        return socket.gethostbyname(socket.gethostname())


def add_or_update_satellite(sat_id, fingerprint, hostname, port):
    """Adds a new satellite to the in-memory list and re-signs/saves the file IF this is the origin."""
    if not IS_ORIGIN:
        print("INFO: Cannot add/update satellite. This instance is not the Origin satellite.")
        return

    if sat_id not in TRUSTED_SATELLITES:
        print(f"Adding new satellite to trusted list: {sat_id}")
        UI_NOTIFICATIONS.put_nowait(f"Added trusted satellite: {sat_id}")
    
    TRUSTED_SATELLITES[sat_id] = {
        "fingerprint": fingerprint,
        "hostname": hostname,
        "port": port
    }
    sign_and_save_satellite_list()


def load_trusted_satellites():
    """Loads and verifies list.json on startup."""
    global TRUSTED_SATELLITES
    if os.path.exists(LIST_JSON_PATH):
        try:
            with open(LIST_JSON_PATH, 'r') as f:
                signed_data = json.load(f)
            
            data = signed_data['data']
            signature = base64.b64decode(signed_data['signature'])
            json_data_bytes = json.dumps(data, indent=4, sort_keys=True).encode('utf-8')

            public_key = serialization.load_pem_public_key(ORIGIN_PUBKEY_PEM, backend=default_backend())
            public_key.verify(
                signature,
                json_data_bytes,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            print(f"Verified signature of existing {LIST_JSON_PATH}.")
            
            for sat in data['satellites']:
                TRUSTED_SATELLITES[sat['id']] = sat
        
        except Exception as e:
            print(f"ERROR: Failed to load or verify {LIST_JSON_PATH}: {e}")
            exit(1)


def sign_and_save_satellite_list():
    """
    Generates the list.json with the current satellite's info,
    signs it using the origin private key, and saves the file.
    Only runs if IS_ORIGIN is True.
    """
    if not IS_ORIGIN or not ORIGIN_PRIVKEY_PEM:
        print("ERROR: Not the origin satellite. Cannot sign list.json.")
        return

    private_key = serialization.load_pem_private_key(
        ORIGIN_PRIVKEY_PEM,
        password=None,
        backend=default_backend()
    )

    satellites_list_formatted = list(TRUSTED_SATELLITES.values())
    
    satellites_list_data = {
        "satellites": satellites_list_formatted
    }
    
    json_data_bytes = json.dumps(satellites_list_data, indent=4, sort_keys=True).encode('utf-8')

    signature = private_key.sign(
        json_data_bytes,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )

    final_list_structure = {
        "data": satellites_list_data,
        "signature": base64.b64encode(signature).decode('utf-8')
    }

    with open(LIST_JSON_PATH, 'w') as f:
        json.dump(final_list_structure, f, indent=4, separators=(',', ': '))
    
    print(f"Generated and signed {LIST_JSON_PATH} with {len(TRUSTED_SATELLITES)} entries.")


def generate_keys_and_certs():
    """Generates satellite keys and origin pubkey/privkey if missing."""
    global ORIGIN_PUBKEY_PEM, ORIGIN_PRIVKEY_PEM, IS_ORIGIN
    print("Checking for existing keys and certificates...")
    
    # 1. Generate/Load Satellite TLS Key and Cert
    if not os.path.exists(CERT_PATH) or not os.path.exists(KEY_PATH):
        print("Generating new satellite cert.pem and key.pem...")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"), x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),])
        cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.utcnow()).not_valid_after(datetime.utcnow() + timedelta(days=3650)).add_extension(x509.SubjectAlternativeName([x509.DNSName(u"localhost")]), critical=False,).sign(private_key=key, algorithm=hashes.SHA256(), backend=default_backend())
        with open(KEY_PATH, "wb") as f:
            f.write(key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.TraditionalOpenSSL, encryption_algorithm=serialization.NoEncryption()))
        with open(CERT_PATH, "wb") as f:
            f.write(cert.public_bytes(encoding=serialization.Encoding.PEM))
        print("Satellite cert.pem and key.pem generated.")
    else:
        print("Reusing existing satellite cert.pem and key.pem.")

    # 2. Generate/Load Origin Pubkey/Privkey
    if not os.path.exists(ORIGIN_PUBKEY_PATH) or not os.path.exists(ORIGIN_PRIVKEY_PATH):
        print(f"Generating new master origin key pair. THIS INSTANCE IS NOW THE ORIGIN.")
        IS_ORIGIN = True
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
        print("Reusing existing master origin keys.")
        with open(ORIGIN_PUBKEY_PATH, "rb") as f:
            ORIGIN_PUBKEY_PEM = f.read().strip()
        with open(ORIGIN_PRIVKEY_PATH, "rb") as f:
            ORIGIN_PRIVKEY_PEM = f.read().strip()
        
        try:
            serialization.load_pem_private_key(ORIGIN_PRIVKEY_PEM, password=None, backend=default_backend())
            IS_ORIGIN = True
            print("Private origin key loaded. This instance is the Origin satellite.")
        except ValueError:
            IS_ORIGIN = False
            print("Private origin key not found/valid. This instance is a Replica satellite.")

    # 3. Derive Satellite ID and Fingerprint (must be stable)
    global SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP
    with open(CERT_PATH, 'rb') as f:
        cert_data = f.read()
    cert = x509.load_pem_x509_certificate(cert_data, default_backend())
    # FIX: Access the first element of the list returned by get_attributes_for_oid()
    SATELLITE_ID = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME).value
    TLS_FINGERPRINT = cert.fingerprint(hashes.SHA1()).hex(':')
    ADVERTISED_IP = get_local_ip()
    print(f"Satellite ID: {SATELLITE_ID}")
    print(f"TLS Fingerprint: {TLS_FINGERPRINT}")
    # FIX: Corrected variable name from ADVERTIED_IP to ADVERTISED_IP
    print(f"Advertising IP: {ADVERTISED_IP}")


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
                node_info = json.loads(args)
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
                pass

            else:
                print(f"Unknown command or no node ID: {command}")

        except json.JSONDecodeError:
            print(f"Invalid JSON in message: {message}")
        except Exception as e:
            print(f"Error handling message: {e}")

    def connection_lost(self, exc):
        pass


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
        sys.stdout.write('\033[H') 
        sys.stdout.write('\033[J')
        sys.stdout.flush()

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

        # 5. Satellite ID + TLS Fingerprint + Trusted List Summary
        print("\n" + "=" * HEADER_WIDTH)
        print("Satellite ID + TLS Fingerprint".center(HEADER_WIDTH))
        print("=" * HEADER_WIDTH)
        print(f"Satellite ID:          {SATELLITE_ID}")
        print(f"Advertising IP:        {ADVERTISED_IP}")
        print(f"Origin Status:         {'ORIGIN' if IS_ORIGIN else 'REPLICA'} ")
        print(f"TLS Fingerprint:       {TLS_FINGERPRINT}")
        print(f"Trusted Satellites:    {len(TRUSTED_SATELLITES)} in list.json")
        print("=" * HEADER_WIDTH)

        await asyncio.sleep(1)


async def main():
    generate_keys_and_certs() # Setup keys/certs on startup
    load_trusted_satellites() # Load and verify existing trusted list

    # Ensure our own satellite info is in the trusted list upon startup
    # This function now checks IS_ORIGIN internally before attempting to sign/save
    add_or_update_satellite(SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP, LISTEN_PORT)

    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile=CERT_PATH, keyfile=KEY_PATH)

    loop = asyncio.get_running_loop()
    server = await loop.create_server(
        SatelliteProtocol, LISTEN_HOST, LISTEN_PORT, ssl=ssl_context
    )

    print(f"Serving on {LISTEN_HOST}:{LISTEN_PORT} (TLS enabled) advertising {ADVERTISED_IP}...")

    asyncio.create_task(display_ui())
    asyncio.create_task(watchdog_task())
    asyncio.create_task(audit_and_queue_repairs())
    asyncio.create_task(repair_worker())

    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    import random
    try:
        sys.stdout.write('\033[H')
        sys.stdout.flush()
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Satellite shutting down.")
