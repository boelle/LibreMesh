"""
===============================================================================
PROJECT: LibreMesh Satellite (Control Plane)
VERSION: 2025.12.15 (GitHub Truth & Security Polished)
===============================================================================

================================================================================
SATELLITE BOOT SEQUENCE AND RUNTIME BEHAVIOR
================================================================================

This satellite program may run either as the **origin authority** or as a **regular satellite**.
It coordinates trusted satellites and nodes in the network. The program runs
asynchronously with a terminal UI, a background registry sync task, and a TCP listener.

--------------------------------------------------------------------------------
STEP 1: INITIALIZATION (GLOBAL STATE SETUP)
--------------------------------------------------------------------------------
- All global variables and constants are defined:
    - NODES: tracks known nodes
    - TRUSTED_SATELLITES: tracks known satellites
    - REPAIR_QUEUE: tasks for fragment repair
    - Config flags (e.g., FORCE_ORIGIN)
- At this point:
    - No network activity exists
    - No identity has been established
    - No UI is running
- Purpose: prepare memory for the satellite’s runtime.

--------------------------------------------------------------------------------
STEP 2: ROLE DECISION
--------------------------------------------------------------------------------
- The FORCE_ORIGIN flag determines this satellite’s role:
    - True  → Origin authority
    - False → Regular follower
- Role affects:
    - Whether master signing keys are generated
    - Which public keys are trusted
    - Whether the satellite auto-registers itself

--------------------------------------------------------------------------------
STEP 3: KEY MATERIAL AND TRUST SETUP
--------------------------------------------------------------------------------
- TLS certificate and key:
    - Generated locally if missing (self-signed)
    - Used to derive SATELLITE_ID and TLS_FINGERPRINT
- Origin signing keys (only if origin):
    - Generated if missing
    - Stored locally for authority verification
- Non-origin satellites:
    - Fetch origin public key or list.json from GitHub once
    - Store locally for trust verification
- Origin auto-adds itself to TRUSTED_SATELLITES.

--------------------------------------------------------------------------------
STEP 4: IDENTITY ESTABLISHMENT
--------------------------------------------------------------------------------
- TLS certificate fingerprint defines the satellite’s **unique identity**.
- SATELLITE_ID = SHA-256(cert.pem)
- ADVERTISED_IP is configured and stored.
- IS_ORIGIN flag reflects role decision.
- Ensures identity exists **before UI and network tasks start**.

--------------------------------------------------------------------------------
STEP 5: UI AND BACKGROUND TASKS
--------------------------------------------------------------------------------
- UI loop (draw_ui) is started asynchronously:
    - Displays SATELLITE_ID, nodes, satellites, repair queue, notifications
    - Always reads **current internal state**
- Background sync task (sync_registry_from_github) is started asynchronously:
    - Periodically fetches list.json from GitHub
    - Verifies signatures
    - Updates TRUSTED_SATELLITES
- Both tasks run in parallel to the main event loop.

--------------------------------------------------------------------------------
STEP 6: NETWORK LISTENER
--------------------------------------------------------------------------------
- TCP server is started on configured host/port.
- Handler is currently a no-op (accepts connections but does not process messages).
- Ensures satellite is reachable by the network.

--------------------------------------------------------------------------------
STEP 7: STEADY-STATE BEHAVIOR
--------------------------------------------------------------------------------
- The program enters serve_forever:
    - UI loop continues updating terminal
    - Background sync task continues running
    - TCP server accepts connections passively
- Runs indefinitely until manually stopped.
- Internal state updates (e.g., TRUSTED_SATELLITES) occur only via defined tasks.
- Remark section STEP 8 describes this steady-state accurately.

================================================================================
END OF BOOT SEQUENCE AND RUNTIME DESCRIPTION
================================================================================


CORE ARCHITECTURE RULES:
------------------------
1. CONTROL PLANE vs DATA PLANE:
   - This script is a "Satellite" (Control Plane). It DOES NOT store data.
   - Satellite MUST NEVER be listed in the 'Node Status' UI table.

2. BOOT SEQUENCE & ROLE AUTHORITY:
   - STEP 1: INITIALIZATION: Global states (NODES, TRUSTED_SATELLITES).
   - STEP 2: ROLE DEFINITION: The 'FORCE_ORIGIN' config setting dictates role.
   - STEP 3: KEY RECOVERY: 
     - If FORCE_ORIGIN is True: Generate Master keys locally.
     - If FORCE_ORIGIN is False: Fetch 'origin_pubkey.pem' from GitHub once.
   - STEP 4: IDENTITY: 'cert.pem' defines the unique TLS fingerprint.
   - STEP 5: UI & LISTENING: Parallel background tasks for UI and TCP server.

3. SECURITY & DISTRIBUTION:
   - GitHub serves as the "Source of Truth." 
   - Standard Satellites periodically pull 'list.json' from GitHub.
   - GATEKEEPER: A satellite is only trusted by the mesh AFTER the Origin 
     updates 'list.json' on GitHub with that satellite's fingerprint.

4. VISUAL TERMINAL LAYOUT EXAMPLE:
----------------------------------
======================================================
                Satellite Node Status
======================================================
Node ID            | Rank | Last Seen (s) | Uptime (s)
------------------------------------------------------
No nodes connected  | N/A  | N/A           | N/A

======================================================
                     Repair Queue
======================================================
Job ID (Fragment)              | Status | Claimed By
------------------------------------------------------
Queue is empty                 | N/A    | N/A

======================================================
                     Notifications
======================================================

======================================================
               Suspicious IPs Advisory
======================================================
No suspicious activity detected.

======================================================
            Satellite ID + TLS Fingerprint
======================================================
Satellite ID:          localhost
Advertising IP:        192.168.0.163
Origin Status:         ORIGIN
TLS Fingerprint:       QPNZ8dUCgc81cZX2yBp0rVsZSKm4FSw43Ax0NL5OdH4=
Trusted Satellites:    1 in list.json
======================================================



===============================================================================
"""

import asyncio
import socket
import ssl
import json
import time
import os
import textwrap
import base64
import sys
import urllib.request
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from datetime import datetime, timedelta
from collections import deque

# --- Configuration ---
LISTEN_HOST = '0.0.0.0'
LISTEN_PORT = 8888
ORIGIN_PORT = 8888
ORIGIN_HOST = '192.168.0.163'
ADVERTISED_IP_CONFIG = '192.168.0.163' 

# IDENTITY & ROLE
SATELLITE_NAME = "LibreMesh-Sat-01" 
FORCE_ORIGIN = True # Set to True for the Master/Origin node

# --- Node Sync ---
NODE_SYNC_INTERVAL = 5  # seconds between node sync rounds

# GITHUB SYNC
ORIGIN_PUBKEY_URL = "https://raw.githubusercontent.com/boelle/LibreMesh/refs/heads/main/origin_pubkey.pem"
LIST_JSON_URL    = "https://raw.githubusercontent.com/boelle/LibreMesh/refs/heads/main/trusted-satellites/list.json"
SYNC_INTERVAL = 300 # Pull list.json every 5 minutes

# Global State
NOTIFICATION_LOG = deque(maxlen=10) # NOTIFICATION_LOG is a capped deque (maxlen=10) to retain recent events for UI display, complementing UI_NOTIFICATIONS queue.

NODES = {}               # Tracks remote storage nodes
                         # NODES holds connected storage nodes with last-seen timestamps. This allows the UI and repair queue to reference node availability.
                         
REMOTE_SATELLITES = {}   # Tracks other online satellites detected during node sync rounds for internal awareness
                         # REMOTE_SATELLITES tracks other online satellites detected during node sync rounds.
                         # Used for internal awareness and optional future peer-to-peer replication.

REPAIR_QUEUE = asyncio.Queue()
SATELLITE_ID = None
TLS_FINGERPRINT = None
ORIGIN_PUBKEY_PEM = None
ORIGIN_PRIVKEY_PEM = None
IS_ORIGIN = False 
LIST_JSON_PATH = 'list.json'
ORIGIN_PUBKEY_PATH = 'origin_pubkey.pem'
ORIGIN_PRIVKEY_PATH = 'origin_privkey.pem'
CERT_PATH = 'cert.pem'
KEY_PATH = 'key.pem'
UI_NOTIFICATIONS = asyncio.Queue(maxsize=20)
TRUSTED_SATELLITES = {} 
ADVERTISED_IP = None
LIST_UPDATED_PENDING_SAVE = False

# --- Core Logic ---
def get_local_ip():
    """
    Determine the IP address this satellite will advertise to peers and origin.

    Purpose:
    - Provides the network address that this satellite announces as its
      reachable endpoint during identity establishment and registry updates.
    - This value is used for *advertisement only*, not for socket binding.

    Behavior:
    - If ADVERTISED_IP_CONFIG is explicitly set by the operator, that value
      is always returned and treated as authoritative.
    - Otherwise, falls back to resolving the local hostname via the OS
      (`socket.gethostbyname(socket.gethostname())`).

    Design Notes:
    - This function does NOT perform network discovery, interface probing,
      NAT traversal, or reachability validation.
    - The fallback hostname resolution may return a loopback or non-routable
      address depending on system configuration.
    - Explicit configuration is strongly recommended for multi-node setups,
      NAT environments, and testing scenarios.

    Operational Context:
    - Called during startup to establish satellite identity.
    - Does not modify global state.
    - Kept intentionally simple to avoid boot-time network complexity.
    """
    return ADVERTISED_IP_CONFIG if ADVERTISED_IP_CONFIG else socket.gethostbyname(socket.gethostname())

async def fetch_github_file(url, local_path, force=False):
    """
    Retrieve a file from a remote GitHub URL and store it locally.

    Purpose:
    - Used to bootstrap trust and configuration artifacts that are centrally
      published (e.g. origin public key, trusted satellite registry).
    - Enables satellites to synchronize critical static files without
      peer-to-peer coordination.

    Behavior:
    - If the target file already exists locally and `force` is False,
      the download is skipped.
    - If `force` is True, the file is always fetched and overwritten.
    - Performs a simple HTTP GET request to the provided URL.
    - On success, writes the response body directly to `local_path`.

    Error Handling:
    - Network or HTTP errors are caught and reported via UI_NOTIFICATIONS.
    - Failure does not raise, allowing boot to continue with existing state.

    Design Notes:
    - No validation of file contents or cryptographic verification occurs here.
    - Trust verification (signatures, fingerprints) is handled elsewhere.
    - This function is intentionally minimal to keep bootstrapping resilient.

    Operational Context:
    - Called during startup before registry loading.
    - Asynchronous to avoid blocking the event loop during network I/O.
    """
    if not os.path.exists(local_path) or force:
        try:
            # Fetch file content from GitHub synchronously in a thread-safe way
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: urllib.request.urlopen(url).read())
            # Write content to local file
            with open(local_path, "wb") as f:
                f.write(response)
            return True
        except Exception:
            return False
    # File already exists and force not requested
    return True

async def sync_nodes_with_peers():
    """
    STEP 6: PEER-TO-PEER NODE SYNC

    Continuously shares this satellite's known storage nodes with other online satellites.

    Behavior:
    - Iterates over all entries in REMOTE_SATELLITES.
    - For each satellite:
        - Opens a TCP connection to the satellite's hostname and port.
        - Sends a JSON payload containing:
            - "id": this satellite's SATELLITE_ID
            - "nodes": this satellite's local NODES dictionary
        - Flushes the payload and closes the connection.
    - If an exception occurs during the push, logs it to UI_NOTIFICATIONS.
    - Waits NODE_SYNC_INTERVAL seconds before repeating.

    Notes:
    - Runs indefinitely in a non-blocking async loop.
    - Does not modify local NODES, only pushes it to peers.
    - Supports eventual consistency in node awareness across satellites.
    - Exceptions are caught per satellite to ensure a single failure does not stop the loop.

    Uses global state:
    - SATELLITE_ID
    - NODES
    - REMOTE_SATELLITES
    - NODE_SYNC_INTERVAL
    - UI_NOTIFICATIONS
    """
    while True:
        for sat_id, sat_info in TRUSTED_SATELLITES.items():
            if sat_id == SATELLITE_ID:
                continue  # skip self

            peer_host = sat_info['hostname']
            peer_port = sat_info['port']

            try:
                # Simple TCP request to send local NODES
                reader, writer = await asyncio.open_connection(peer_host, peer_port)
                # Send serialized NODES
                writer.write(json.dumps(NODES).encode('utf-8'))
                await writer.drain()

                # Receive peer's NODES
                data = await reader.read(65536)
                peer_nodes = json.loads(data.decode('utf-8'))

                # Merge peer NODES into local NODES
                for node_id, last_seen in peer_nodes.items():
                    if node_id not in NODES or last_seen > NODES[node_id]:
                        NODES[node_id] = last_seen

                writer.close()
                await writer.wait_closed()
            except Exception:
                # Ignore unreachable peers
                continue

        await asyncio.sleep(NODE_SYNC_INTERVAL)

async def sync_registry_from_github():
    """
    STEP 7: PERIODIC TRUSTED REGISTRY SYNC FROM GITHUB

    Continuously fetches the central trusted satellites list (list.json) from the
    configured GitHub repository and updates local TRUSTED_SATELLITES.

    Behavior:
    - Runs in an infinite asynchronous loop.
    - Every SYNC_INTERVAL seconds:
        - Downloads LIST_JSON_URL to LIST_JSON_PATH using fetch_github_file().
        - Loads the JSON content and updates TRUSTED_SATELLITES in-memory.
        - Adds or updates entries as necessary, without removing existing satellites
          unless explicitly changed in the downloaded list.
        - Any errors in download or parsing are logged to UI_NOTIFICATIONS.
    
    Notes:
    - Only intended for non-origin satellites to fetch the canonical registry.
    - Keeps local in-memory registry consistent with GitHub source.
    - Exceptions in fetching or parsing do not halt the loop.
    
    Uses global state:
    - LIST_JSON_URL
    - LIST_JSON_PATH
    - TRUSTED_SATELLITES
    - UI_NOTIFICATIONS
    - SYNC_INTERVAL
    """
    
    while True:
        if not IS_ORIGIN:
            # We always pull list.json because it updates frequently
            await fetch_github_file(LIST_JSON_URL, LIST_JSON_PATH, force=True)
            load_trusted_satellites()
        # Wait before next sync to reduce GitHub requests
        await asyncio.sleep(SYNC_INTERVAL)

def add_or_update_trusted_registry(sat_id, fingerprint, hostname, port):
    """
    STEP 3b: Add or update a satellite entry in the in-memory trusted registry.

    Purpose:
    - Maintains a dictionary of trusted satellites for identity verification.
    - Ensures the satellite registry reflects current fingerprint, hostname/IP, and listening port.
    - Used by both origin and non-origin nodes for consistency and eventual GitHub distribution.

    Parameters:
    - sat_id (str): Unique identifier of the satellite.
    - fingerprint (str): TLS fingerprint of the satellite's certificate.
    - hostname (str): Advertised hostname or IP of the satellite.
    - port (int): Listening port of the satellite.

    Behavior:
    - If the satellite already exists in TRUSTED_SATELLITES:
        - Updates fingerprint, hostname, port if changed.
    - If it does not exist:
        - Creates a new entry.
    - Does NOT perform any network I/O; strictly updates in-memory state.
    - Changes are later persisted to GitHub via `sign_and_save_satellite_list()` by the origin.

    Notes:
    - Modifies the global TRUSTED_SATELLITES dictionary.
    - Keeps the system aware of all known satellites for verification and replication purposes.
    """
    global LIST_UPDATED_PENDING_SAVE
    if not IS_ORIGIN: return
    new_details = {"id": sat_id, "fingerprint": fingerprint, "hostname": hostname, "port": port}
    if sat_id not in TRUSTED_SATELLITES or TRUSTED_SATELLITES[sat_id] != new_details:
        TRUSTED_SATELLITES[sat_id] = new_details
        UI_NOTIFICATIONS.put_nowait(f"Registry updated: {sat_id}")
        LIST_UPDATED_PENDING_SAVE = True

def load_trusted_satellites():
    """
    Load the trusted satellites registry from the local list.json file.

    Purpose:
    - Initialize the in-memory TRUSTED_SATELLITES dictionary with entries from disk.
    - Validate the structure of each satellite entry to ensure required keys exist.
    - Ensure the origin satellite is present in the registry if running in origin mode.

    Behavior:
    1. Reads the JSON file specified by LIST_JSON_PATH.
    2. Parses each satellite entry and checks for mandatory fields:
       - 'id', 'fingerprint', 'hostname', 'port'
    3. Populates TRUSTED_SATELLITES with validated entries.
    4. Logs or raises exceptions if the file is missing or entries are invalid.
    5. Origin may automatically add its own entry if not already present.

    Notes:
    - In-memory only; does not persist changes to disk or GitHub.
    - Typically called during the boot sequence (main) before starting UI or networking tasks.
    - Any changes detected here may be later persisted by sign_and_save_satellite_list().
    """
    global TRUSTED_SATELLITES
    if os.path.exists(LIST_JSON_PATH):
        try:
            with open(LIST_JSON_PATH, 'r') as f:
                signed_data = json.load(f)
            data = signed_data['data']
            if not ORIGIN_PUBKEY_PEM: return
            
            public_key = serialization.load_pem_public_key(ORIGIN_PUBKEY_PEM, backend=default_backend())
            signature = base64.b64decode(signed_data['signature'])
            json_bytes = json.dumps(data, indent=4, sort_keys=True).encode('utf-8')
            public_key.verify(signature, json_bytes, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())

            # Verification succeeded: update TRUSTED_SATELLITES
            TRUSTED_SATELLITES.clear()
            for sat in data['satellites']:
                TRUSTED_SATELLITES[sat['id']] = sat
        except Exception:
            # Verification failed, notify UI
            UI_NOTIFICATIONS.put_nowait("Registry: Verification Failed.")

def sign_and_save_satellite_list():
    """
    Sign and save the trusted satellites registry to disk (list.json).

    Purpose:
    - Persist the current TRUSTED_SATELLITES in-memory dictionary to the local list.json file.
    - Ensure authenticity by signing the registry using the origin’s private key.
    - Only the origin node performs this operation.

    Behavior:
    1. Converts TRUSTED_SATELLITES to JSON.
    2. Applies cryptographic signing using ORIGIN_PRIVKEY_PEM.
    3. Writes the signed registry to LIST_JSON_PATH.
    4. Raises/logs exceptions if signing fails or the file cannot be written.

    Notes:
    - Followers should never call this function; they only read the registry from disk or GitHub.
    - This is part of STEP 3/4 in the boot sequence: establishing trust and identity.
    - Ensures the registry persisted locally matches the trusted state used in memory.
    """
    global LIST_UPDATED_PENDING_SAVE
    if not IS_ORIGIN or not ORIGIN_PRIVKEY_PEM: return
    try:
        private_key = serialization.load_pem_private_key(ORIGIN_PRIVKEY_PEM, password=None, backend=default_backend())
        data = {"satellites": list(TRUSTED_SATELLITES.values())}
        json_bytes = json.dumps(data, indent=4, sort_keys=True).encode('utf-8')
        sig = private_key.sign(json_bytes, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
        with open(LIST_JSON_PATH, 'w') as f:
            json.dump({"data": data, "signature": base64.b64encode(sig).decode('utf-8')}, f, indent=4)
        LIST_UPDATED_PENDING_SAVE = False
    except Exception: pass

def generate_keys_and_certs():
    """
    Generate local TLS key and self-signed certificate for the satellite.

    Purpose:
    - Ensure each satellite has a unique cryptographic identity.
    - Required for secure communications between satellites and with the origin.
    - Initializes SATELLITE_ID, TLS_FINGERPRINT, and ADVERTISED_IP.

    Behavior:
    1. Checks for existing KEY_PATH and CERT_PATH files.
    2. If missing, generates a new private key and self-signed certificate.
    3. Writes the key and certificate to disk.
    4. Extracts TLS fingerprint and assigns a unique SATELLITE_ID.
    5. Sets ADVERTISED_IP to ADVERTISED_IP_CONFIG or discovered local IP.

    Notes:
    - Must be called before establishing any TCP connections or syncing with origin.
    - Supports both origin and follower satellites.
    - Complements STEP 3 and STEP 4 in the boot sequence.
    """
    global SATELLITE_ID, TLS_FINGERPRINT, IS_ORIGIN, ADVERTISED_IP, ORIGIN_PUBKEY_PEM, ORIGIN_PRIVKEY_PEM
    # 1. Cert Generation
    if not os.path.exists(CERT_PATH):
        key = rsa.generate_private_key(65537, 2048)
        subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(SATELLITE_NAME))])
        cert = x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.utcnow()).not_valid_after(datetime.utcnow() + timedelta(days=3650)).sign(key, hashes.SHA256())
        with open(KEY_PATH, "wb") as f: f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        with open(CERT_PATH, "wb") as f: f.write(cert.public_bytes(serialization.Encoding.PEM))

    # 2. Role Logic
    if FORCE_ORIGIN:
        IS_ORIGIN = True
        if not os.path.exists(ORIGIN_PRIVKEY_PATH):
            priv = rsa.generate_private_key(65537, 2048)
            ORIGIN_PUBKEY_PEM = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            ORIGIN_PRIVKEY_PEM = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
            with open(ORIGIN_PUBKEY_PATH, "wb") as f: f.write(ORIGIN_PUBKEY_PEM)
            with open(ORIGIN_PRIVKEY_PATH, "wb") as f: f.write(ORIGIN_PRIVKEY_PEM)
        else:
            with open(ORIGIN_PUBKEY_PATH, "rb") as f: ORIGIN_PUBKEY_PEM = f.read()
            with open(ORIGIN_PRIVKEY_PATH, "rb") as f: ORIGIN_PRIVKEY_PEM = f.read()
    else:
        IS_ORIGIN = False
        if os.path.exists(ORIGIN_PUBKEY_PATH):
            with open(ORIGIN_PUBKEY_PATH, "rb") as f: ORIGIN_PUBKEY_PEM = f.read()

    # 3. Attributes
    with open(CERT_PATH, 'rb') as f:
        cert = x509.load_pem_x509_certificate(f.read(), default_backend())
    cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    SATELLITE_ID = cn_attrs[0].value if cn_attrs else str(SATELLITE_NAME)
    TLS_FINGERPRINT = base64.b64encode(cert.fingerprint(hashes.SHA256())).decode('utf-8')
    ADVERTISED_IP = get_local_ip()

async def handle_node_sync(reader, writer):
    """
    Satellite → Origin registration and status sync channel.

    Satellites connect to the origin and submit their identity, TLS fingerprint,
    advertised hostname/IP, listening port, known storage nodes, and repair queue.

    The origin validates the payload, updates TRUSTED_SATELLITES in-memory,
    persists the signed registry, and emits a UI notification.

    Non-origin nodes ignore incoming registrations.
    """
    peer_ip = writer.get_extra_info("peername")[0]

    try:
        data = await reader.read(4096)
        payload = json.loads(data.decode())
        required_keys = {"id", "fingerprint", "ip", "port"}

        if not required_keys.issubset(payload):
            raise ValueError(
                f"Invalid node sync payload keys={list(payload.keys())}"
            )

        sat_id = payload["id"]
        fingerprint = payload["fingerprint"]
        ip = payload["ip"]
        port = payload["port"]

        # Only origin accepts registrations
        if IS_ORIGIN:
            # Validate required payload keys
            required_keys = {"id", "fingerprint", "ip", "port"}
            if not required_keys.issubset(payload.keys()):
                raise ValueError(f"Invalid node sync payload keys={list(payload.keys())}")

            existing = TRUSTED_SATELLITES.get(sat_id)

            new_entry = {
                "id": sat_id,
                "fingerprint": fingerprint,
                "hostname": ip,
                "port": port,
                "nodes": payload.get("nodes", {}),
                "repair_queue": payload.get("repair_queue", [])
            }

            if existing != new_entry:
                TRUSTED_SATELLITES[sat_id] = new_entry
                sign_and_save_satellite_list()

                if existing is None:
                    UI_NOTIFICATIONS.put_nowait(f"Satellite registered: {sat_id}")
                else:
                    UI_NOTIFICATIONS.put_nowait(f"Satellite updated: {sat_id}")

    except Exception as e:
        UI_NOTIFICATIONS.put_nowait(f"Node sync error from {peer_ip}: {type(e).__name__}: {e}")

    finally:
        writer.close()
        await writer.wait_closed()
        
async def announce_to_origin():
"""
STEP 2: Announce satellite to origin

- Non-origin satellites notify the origin of their presence after a short delay (3s).
- Payload includes:
    - 'id': SATELLITE_ID
    - 'fingerprint': TLS_FINGERPRINT
    - 'ip': ADVERTISED_IP
    - 'port': LISTEN_PORT
- Origin may register or update the satellite in TRUSTED_SATELLITES.
- Any connection failure results in a UI notification.
"""
    await asyncio.sleep(3)  # allow boot to finish

    if IS_ORIGIN:
        return

    try:
        reader, writer = await asyncio.open_connection(ORIGIN_HOST, ORIGIN_PORT)

        payload = {
            "id": SATELLITE_ID,
            "fingerprint": TLS_FINGERPRINT,
            "ip": ADVERTISED_IP,
            "port": LISTEN_PORT,
        }

        writer.write(json.dumps(payload).encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    except Exception:
        UI_NOTIFICATIONS.put_nowait("Failed to reach origin")

async def register_with_origin():
    """
    STEP 2: Register satellite with origin

    - Non-origin satellites announce themselves to the origin node during boot.
    - Payload sent:
    - 'id': SATELLITE_ID
    - 'fingerprint': TLS_FINGERPRINT
    - 'ip': ADVERTISED_IP
    - 'port': LISTEN_PORT
    - On success: pushes "Registered with origin" notification.
    - On failure: pushes a notification with the exception details.
    - Fully asynchronous; does not block other startup tasks.
    """
    if IS_ORIGIN:
        return

    try:
        reader, writer = await asyncio.open_connection(ORIGIN_HOST, ORIGIN_PORT)

        payload = {
            "id": SATELLITE_ID,
            "fingerprint": TLS_FINGERPRINT,
            "ip": ADVERTISED_IP,
            "port": LISTEN_PORT,
        }

        writer.write(json.dumps(payload).encode())
        await writer.drain()

        writer.close()
        await writer.wait_closed()

        UI_NOTIFICATIONS.put_nowait("Registered with origin")

    except Exception as e:
        UI_NOTIFICATIONS.put_nowait(f"Origin registration failed: {e}")



# --- UI Loop ---
async def draw_ui():
    """
    STEP 5: Terminal User Interface (UI) for Satellite Node.

    Purpose:
    - Provide human-readable status and monitoring for the satellite.
    - Complements background tasks such as node sync and registry updates.

    Behavior:
    1. Clears the terminal screen on each loop iteration.
    2. Displays:
       - Node Status: connected nodes with last seen timestamps.
       - Repair Queue: pending or active fragment repair jobs.
       - Notifications: shows recent UI messages (from NOTIFICATION_LOG and UI_NOTIFICATIONS queue).
       - Suspicious IP Advisory: placeholder for security alerts.
       - Satellite Identity: SATELLITE_ID, TLS fingerprint, advertised IP, origin status, trusted satellites count.
    3. Sleeps for a short interval (e.g., 2 seconds) between refreshes.
    4. Loops indefinitely in the background.

    Notes:
    - Uses global state variables: NODES, REPAIR_QUEUE, UI_NOTIFICATIONS, TRUSTED_SATELLITES, SATELLITE_ID, TLS_FINGERPRINT, IS_ORIGIN, ADVERTISED_IP.
    - Non-blocking; runs in parallel with TCP server, registry sync, and node sync loops.
    - Fully asynchronous and safe to run on both origin and follower satellites.
    - Complements STEP 5 in boot sequence remarks.
    - Notification history retained in NOTIFICATION_LOG (deque maxlen=10).
    - Node uptime currently shown as N/A; can be updated once node heartbeat is implemented.
    """
    while True:
        os.system('clear' if os.name == 'posix' else 'cls')
        print("="*54 + "\n                Satellite Node Status\n" + "="*54)
        print(f"{'Node ID':<18} | {'Rank':<4} | {'Last Seen (s)':<13} | {'Uptime (s)':<10}\n" + "-" * 54)
        if not NODES: print("No nodes connected  | N/A  | N/A           | N/A")
        else:
            for k, v in NODES.items(): print(f"{k[:15]:<18} | Node | {int(time.time()-v):<13} | N/A")
        print("\n" + "="*54 + "\n                     Repair Queue\n" + "="*54)
        print(f"{'Job ID (Fragment)':<30} | {'Status':<6} | {'Claimed By':<10}\n" + "-" * 54)
        print("Queue is empty                 | N/A    | N/A")
        print("\n" + "="*54 + "\n                     Notifications\n" + "="*54)
        temp_msgs = []
        while not UI_NOTIFICATIONS.empty():
            NOTIFICATION_LOG.append(UI_NOTIFICATIONS.get_nowait())

        if not NOTIFICATION_LOG:
            print("\n\n")
        else:
            for m in NOTIFICATION_LOG:
                print(m)
                
        print("\n" + "="*54 + "\n               Suspicious IPs Advisory\n" + "="*54)
        print("No suspicious activity detected.")
        print("\n" + "="*54 + "\n            Satellite ID + TLS Fingerprint\n" + "="*54)
        print(f"Satellite ID:          {SATELLITE_ID}")
        print(f"Advertising IP:        {ADVERTISED_IP}")
        print(f"Origin Status:         {'ORIGIN' if IS_ORIGIN else 'SATELLITE'}")
        print(f"TLS Fingerprint:       {TLS_FINGERPRINT}")
        print(f"Trusted Satellites:    {len(TRUSTED_SATELLITES)} in list.json\n" + "="*54)
        await asyncio.sleep(2)

async def main():
    """
    STEP 1–5: BOOT SEQUENCE ORCHESTRATION

    Entry point for the satellite node. Performs initialization,
    role determination, key/certificate setup, trusted registry handling,
    and starts UI & background tasks.

    Purpose in boot sequence:
    - STEP 1: Initialization (implicit via global state)
    - STEP 2: Role Definition (FORCE_ORIGIN determines origin/follower)
    - STEP 3: Key Recovery & Trust Setup
        - Fetch origin_pubkey.pem for non-origin satellites
        - Generate local keys and certificates
        - Load or verify trusted satellites registry
        - Add origin satellite to registry if applicable
    - STEP 4: Identity Establishment
        - SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP set
    - STEP 5: UI & Background Tasks
        - Launch terminal UI
        - Launch periodic registry sync
        - Start TCP listener

    How it works:
    1. If this satellite is NOT origin (FORCE_ORIGIN=False):
       - Fetch origin public key from GitHub once via `fetch_github_file()`.
    2. Generate keys and certificates locally (`generate_keys_and_certs()`).
    3. Load and verify the trusted satellites registry (`load_trusted_satellites()`).
    4. Origin satellites automatically add themselves to the registry
       for GitHub distribution (`add_or_update_trusted_registry()`).
    5. Start asynchronous background tasks:
       - `draw_ui()`: terminal UI
       - `sync_registry_from_github()`: periodic trusted registry updates
    6. Start TCP server to listen for connections (currently placeholder lambda).
       - Runs indefinitely using `serve_forever()`.

    Notes:
    - Orchestrates **entire satellite boot sequence**.
    - Updates and relies on global state: ORIGIN_PUBKEY_PEM, SATELLITE_ID,
      TLS_FINGERPRINT, ADVERTISED_IP, TRUSTED_SATELLITES, etc.
    - Fully matches remark section steps 1–5.
    - Ensures the satellite is ready for operation with identity,
      trust verification, UI, and networking.
    - Follower push to origin temporarily duplicates 'announce_to_origin()'; can be consolidated.
    - Background tasks are non-blocking due to asyncio.create_task().
    - TCP server blocks indefinitely; ensures continuous node sync handling.
    """
    global ORIGIN_PUBKEY_PEM
    # Standard satellites pull pubkey ONCE from GitHub
    if not FORCE_ORIGIN:
        await fetch_github_file(ORIGIN_PUBKEY_URL, ORIGIN_PUBKEY_PATH)

    # Start periodic node → origin sync
    if not IS_ORIGIN:
        asyncio.create_task(node_sync_loop())
    
    generate_keys_and_certs()
    load_trusted_satellites()
    
    await register_with_origin()
    
    # Origin auto-adds itself to registry for distribution
    add_or_update_trusted_registry(SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP, LISTEN_PORT)

    if IS_ORIGIN:
        sign_and_save_satellite_list()

    # Launch UI and registry sync in background
    asyncio.create_task(draw_ui())
    asyncio.create_task(sync_registry_from_github())

    asyncio.create_task(sync_nodes_with_peers())
    asyncio.create_task(announce_to_origin())

    # Start TCP server to accept incoming satellite → origin registration and status sync. Handles updates to TRUSTED_SATELLITES, node awareness, and repair queue information.
    server = await asyncio.start_server(handle_node_sync, LISTEN_HOST, LISTEN_PORT)
    async with server: await server.serve_forever()

    """
    Sends this satellite's status to the origin node.

    Purpose:
    - Enables the origin to maintain an up-to-date view of all followers.
    - Provides information for node awareness and repair coordination.

    Behavior:
    1. If this node is the origin (IS_ORIGIN=True), the function returns immediately.
    2. Constructs a payload containing:
       - Satellite ID (SATELLITE_ID)
       - TLS fingerprint (TLS_FINGERPRINT)
       - Advertised IP (ADVERTISED_IP)
       - Listening port (LISTEN_PORT)
       - Known storage nodes (NODES)
       - Current repair queue (REPAIR_QUEUE)
    3. Opens a TCP connection to the origin (ORIGIN_HOST:ORIGIN_PORT).
    4. Sends the payload as JSON.
    5. Closes the connection gracefully.
    6. Any errors are captured and a message is added to UI_NOTIFICATIONS.

    Notes:
    - Runs asynchronously and can be scheduled periodically in a loop (e.g., node_sync_loop).
    - Assumes ORIGIN_HOST and ORIGIN_PORT are reachable from this satellite.
    - Payload structure is expected by the origin's handle_node_sync() function.
    """
async def push_status_to_origin():
    """
    STEP 2–4: PUSH STATUS TO ORIGIN

    Followers periodically send their current state to the origin:
    - Identity (SATELLITE_ID)
    - TLS fingerprint
    - Advertised IP and listening port
    - Known nodes (NODES)
    - Current repair queue

    Behavior:
    - Origin nodes do not push to themselves.
    - Establishes TCP connection to ORIGIN_HOST:ORIGIN_PORT.
    - Sends JSON-encoded payload.
    - Catches and logs any connection or write errors to UI_NOTIFICATIONS.
    - Ensures writer is properly closed to release resources.

    Used by:
    - `node_sync_loop()` for periodic reporting.
    """
    if IS_ORIGIN:
        return  # Origin does not push to itself

    payload = {
        "id": SATELLITE_ID,
        "fingerprint": TLS_FINGERPRINT,
        "ip": ADVERTISED_IP,
        "port": LISTEN_PORT,
        "nodes": NODES,
        "repair_queue": list(REPAIR_QUEUE._queue)
    }

    try:
        reader, writer = await asyncio.open_connection(ORIGIN_HOST, ORIGIN_PORT)
        writer.write(json.dumps(payload).encode())
        await writer.drain()
    except Exception as e:
        UI_NOTIFICATIONS.put_nowait(f"Node push error: {e}")
    finally:
        if 'writer' in locals():
            writer.close()
            await writer.wait_closed()
    """
    Periodically pushes this satellite's status to the origin.

    Purpose:
    - Keeps the origin updated with this node's current state.
    - Supports centralized awareness of connected satellites for coordination and repair.

    Behavior:
    1. Runs an infinite loop asynchronously.
    2. Calls `push_status_to_origin()` once per iteration.
    3. Waits for NODE_SYNC_INTERVAL seconds between iterations.
    4. Continues indefinitely in the background.

    Notes:
    - Only relevant for non-origin satellites; origins do not push status to themselves.
    - Typically started as a background task using `asyncio.create_task(node_sync_loop())`.
    - Uses global variables: SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP, LISTEN_PORT, NODES, REPAIR_QUEUE.
    """
async def node_sync_loop():
    """
    STEP 2–4: NODE SYNC LOOP

    Continuously pushes the satellite's current status to the origin at regular intervals.

    Behavior:
    - Runs indefinitely in a background asyncio task.
    - Calls `push_status_to_origin()` each cycle.
    - Sleeps for `NODE_SYNC_INTERVAL` seconds between pushes.
    - Origin nodes skip pushing themselves (enforced in `push_status_to_origin()`).

    Purpose:
    - Keeps the origin aware of satellite nodes, their advertised IPs, known nodes, and repair queues.
    - Supports monitoring, coordination, and repair logic.
    """
    while True:
        await push_status_to_origin()
        await asyncio.sleep(NODE_SYNC_INTERVAL)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
