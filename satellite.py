import asyncio
import socket
import ssl
import json
import time
import os
import textwrap
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

NODES = {} # {node_id: {'writer': ..., 'last_seen': ..., 'uptime': ...}}
REPAIR_QUEUE = asyncio.Queue()
SATELLITE_ID = None
TLS_FINGERPRINT = None
ORIGIN_PUBKEY = None # Stays bytes format
LIST_JSON_PATH = 'list.json'
ORIGIN_PUBKEY_PATH = 'origin_pubkey.pem'
CERT_PATH = 'cert.pem'
KEY_PATH = 'key.pem'
UI_NOTIFICATIONS = asyncio.Queue(maxsize=10)


# --- Helper Functions ---
def generate_keys_and_certs():
    """Generates satellite keys and origin pubkey if missing."""
    print("Checking for existing keys and certificates...")
    
    # 1. Generate/Load Satellite TLS Key and Cert
    if not os.path.exists(CERT_PATH) or not os.path.exists(KEY_PATH):
        print("Generating new satellite cert.pem and key.pem...")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        # Self-signed certificate generation (simplified for example)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"CA"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, u"San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"LibreMesh Satellite"),
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

    # 2. Generate/Load Origin Pubkey (now can be generated if missing)
    global ORIGIN_PUBKEY
    if not os.path.exists(ORIGIN_PUBKEY_PATH):
        print(f"Generating new master {ORIGIN_PUBKEY_PATH}...")
        # A new key pair is made for the *network origin key*
        origin_priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        origin_pub_key = origin_priv_key.public_key()
        ORIGIN_PUBKEY = origin_pub_key.public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
        with open(ORIGIN_PUBKEY_PATH, "wb") as f:
            f.write(ORIGIN_PUBKEY)
        print(f"Master {ORIGIN_PUBKEY_PATH} generated and saved.")
        # NOTE: In a real implementation, you'd also want to sign the initial list.json here if it also needed creating.
    else:
        with open(ORIGIN_PUBKEY_PATH, "rb") as f:
            ORIGIN_PUBKEY = f.read().strip()
        print(f"Reusing existing master {ORIGIN_PUBKEY_PATH}.")
    
    # 3. Derive Satellite ID and Fingerprint (must be stable)
    global SATELLITE_ID, TLS_FINGERPRINT
    with open(CERT_PATH, 'rb') as f:
        cert_data = f.read()
    cert = x509.load_pem_x509_certificate(cert_data, default_backend())
    # SATELLITE_ID can be derived from the cert's subject common name or hash
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
        # Apply the SSL context if available
        self.transport = transport
        # print("Connection made (potential TLS handshake pending)")

    def data_received(self, data):
        self.last_seen = time.time() # Reset last seen on any activity
        message = data.decode().strip()
        # print(f"Received: {message}")
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
                    # Update existing node info if it reconnects/registers
                    NODES[self.node_id]['writer'] = self.transport
                    NODES[self.node_id]['last_seen'] = time.time()
                # print(f"Registered Node: {self.node_id}")

            elif command == "HEARTBEAT" and self.node_id:
                # Handled by the self.last_seen update in data_received
                pass
            
            # --- CRITICAL FIX ---
            # Nodes cannot send REPAIR_REQUESTs. This message type is now ignored.
            elif command == "REPAIR_REQUEST":
                # print(f"Ignoring invalid REPAIR_REQUEST from node {self.node_id}")
                pass

            else:
                print(f"Unknown command or no node ID: {command}")

        except json.JSONDecodeError:
            print(f"Invalid JSON in message: {message}")
        except Exception as e:
            print(f"Error handling message: {e}")

    def connection_lost(self, exc):
        if self.node_id in NODES:
            # We don't remove the node immediately; we let the watchdog handle timeouts.
            # print(f"Connection lost with {self.node_id}. Waiting for timeout...")
            pass


# --- Background Tasks ---

async def audit_and_queue_repairs():
    """
    Simulates the satellite's internal audit process.
    This replaces the node-initiated repair requests.
    """
    # This task is where the satellite identifies *which* fragments need repair
    # based on its internal checksum database.
    while True:
        await asyncio.sleep(45) # Run audit every 45 seconds (placeholder timing)
        # Placeholder logic: Find a hypothetical broken fragment and add to queue
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
            # await UI_NOTIFICATIONS.put(f"[AUDIT] Identified need for repair: {fake_fragment_id}")

async def repair_worker():
    """Processes jobs in the REPAIR_QUEUE."""
    while True:
        # Get a job from the queue
        job = await REPAIR_QUEUE.get()
        
        # --- CRITICAL FIX: The previous bug was here (not draining the queue) ---
        try:
            job["status"] = "CLAIMED"
            job["claimed_by"] = SATELLITE_ID
            # print(f"[REPAIR WORKER] Claimed job: {job['fragment_id']}")
            
            # Simulate repair work (rebuilding fragment from other good nodes)
            await asyncio.sleep(5) 
            
            # After successful "repair" (simulation), the job is done.
            await UI_NOTIFICATIONS.put(f"[WORKER] Repair completed: {job['fragment_id']} for node {job['requested_by_node_id']}")
            
            # The job is implicitly removed from the queue because asyncio.Queue.get() removes the item.
            
        except Exception as e:
            print(f"Error processing repair job: {e}")
        finally:
            REPAIR_QUEUE.task_done() # Signal that the task is done

async def watchdog_task():
    """Monitors node timeouts and updates 'last seen' in the UI data."""
    while True:
        await asyncio.sleep(1) # Runs every second
        current_time = time.time()
        
        offline_nodes = []
        for node_id, data in NODES.items():
            # Update 'last_seen_seconds' dynamically for UI display
            data['last_seen_seconds'] = int(current_time - data['last_seen'])
            data['uptime_seconds'] = int(current_time - data['uptime_start'])

            if current_time - data['last_seen'] > NODE_TIMEOUT:
                offline_nodes.append(node_id)
        
        for node_id in offline_nodes:
            # Nodes are kept in NODES list, but marked as offline implicitly via last_seen_seconds for UI
            # We don't want to clear NODES on disconnect immediately to preserve uptime tracking across transient issues
            pass


async def display_ui():
    """Renders the UI based on the Handoff specifications."""
    HEADER_WIDTH = 54
    while True:
        os.system('clear' if os.name == 'posix' else 'cls')

        # 1. Satellite Node Status (Centered Header, Aligned Columns)
        print("=" * HEADER_WIDTH)
        print("Satellite Node Status".center(HEADER_WIDTH))
        print("=" * HEADER_WIDTH)
        # Columns: Node ID (20) | Rank (4) | Last Seen (13) | Uptime (10)
        print("Node ID             | Rank | Last Seen (s) | Uptime (s)")
        print("-" * HEADER_WIDTH)
        for node_id, data in NODES.items():
            last_seen = data.get('last_seen_seconds', 0)
            uptime = data.get('uptime_seconds', 0)
            rank = 100 # Placeholder as requested
            print(f"{node_id:19} | {rank:4} | {last_seen:13} | {uptime:10}")
        if not NODES:
             # FIX: Corrected placeholder to include all columns (NodeID + Rank + Last Seen + Uptime)
             print(f"{'No nodes connected':19} | {'N/A':4} | {'N/A':13} | {'N/A':10}")


        # 2. Repair Queue (Centered Header)
        print("\n" + "=" * HEADER_WIDTH)
        print("Repair Queue".center(HEADER_WIDTH))
        print("=" * HEADER_WIDTH)
        print("Job ID (Fragment)              | Status | Claimed By")
        print("-" * HEADER_WIDTH)
        queue_items = list(REPAIR_QUEUE._queue) # Access internal queue for display without blocking
        for job in queue_items:
            frag_id_short = job['fragment_id'][:30]
            status = job['status']
            claimed = job['claimed_by'] or 'None'
            print(f"{frag_id_short:30} | {status:6} | {claimed}")
        if not queue_items:
             # Aligned using the same widths as the header (30, 6, 14)
             print(f"{'Queue is empty':30} | {'N/A':6} | {'N/A':14}")


        # 3. Notifications (Centered Header)
        print("\n" + "=" * HEADER_WIDTH)
        print("Notifications".center(HEADER_WIDTH))
        print("=" * HEADER_WIDTH)
        # Drain notifications queue for display
        while not UI_NOTIFICATIONS.empty():
            notif = await UI_NOTIFICATIONS.get()
            print(f"- {datetime.now().strftime('%H:%M:%S')} | {notif}")
        
        print("\n" * (5 - UI_NOTIFICATIONS.qsize())) # Padding for stable UI height


        # 4. Suspicious IPs Advisory (Centered Header)
        print("\n" + "=" * HEADER_WIDTH)
        print("Suspicious IPs Advisory".center(HEADER_WIDTH))
        print("=" * HEADER_WIDTH)
        print("No suspicious activity detected.")


        # 5. Satellite ID + TLS Fingerprint (Centered Header)
        print("\n" + "=" * HEADER_WIDTH)
        print("Satellite ID + TLS Fingerprint".center(HEADER_WIDTH))
        print("=" * HEADER_WIDTH)
        print(f"Satellite ID:    {SATELLITE_ID}")
        print(f"TLS Fingerprint: {TLS_FINGERPRINT}")
        print("=" * HEADER_WIDTH)


        await asyncio.sleep(1) # Refresh UI every second


async def main():
    generate_keys_and_certs() # Setup keys/certs on startup

    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile=CERT_PATH, keyfile=KEY_PATH)
    # The handoff implies we might need client cert verification setup here too for full mutual TLS

    loop = asyncio.get_running_loop()
    server = await loop.create_server(
        SatelliteProtocol, LISTEN_HOST, LISTEN_PORT, ssl=ssl_context
    )

    print(f"Serving on {LISTEN_HOST}:{LISTEN_PORT} (TLS enabled)...")

    # Start background tasks
    asyncio.create_task(display_ui())
    asyncio.create_task(watchdog_task())
    asyncio.create_task(audit_and_queue_repairs())
    asyncio.create_task(repair_worker())


    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    import random # Used in audit_and_queue_repairs placeholder
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Satellite shutting down.")
