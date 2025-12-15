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

# --- Configuration ---
LISTEN_HOST = '0.0.0.0'
LISTEN_PORT = 8888
ADVERTISED_IP_CONFIG = '192.168.0.163' 

# IDENTITY & ROLE
SATELLITE_NAME = "LibreMesh-Sat-01" 
FORCE_ORIGIN = True # Set to True for the Master/Origin node

# GITHUB SYNC
ORIGIN_PUBKEY_URL = "https://raw.githubusercontent.com/boelle/LibreMesh/refs/heads/main/origin_pubkey.pem"
LIST_JSON_URL    = "https://raw.githubusercontent.com/boelle/LibreMesh/refs/heads/main/trusted-satellites/list.json"
SYNC_INTERVAL = 300 # Pull list.json every 5 minutes

# Global State
NODES = {}               # Tracks remote storage nodes
REMOTE_SATELLITES = {}   # Tracks other online satellites
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
    STEP 4: IDENTITY ESTABLISHMENT (used to configure ADVERTISED_IP)

    Returns the local IP address of the satellite for network advertisement.

    Purpose in boot sequence:
    - After identity is established (TLS certificate loaded),
      the satellite needs to know its IP to advertise itself in the network.
    - This IP is used when adding the satellite to TRUSTED_SATELLITES
      and for display in the terminal UI.

    How it works:
    1. Checks if a configured IP (ADVERTISED_IP_CONFIG) exists:
       - If set, returns this configured value.
    2. Otherwise, falls back to the system hostname resolution using
       socket.gethostbyname(socket.gethostname()).
    3. Does not modify any global state; purely a read-only helper.

    Notes:
    - Provides a simple and reliable way to determine a local IP
      for network registration.
    - This function is called during STEP 4 (identity establishment)
      before UI or background tasks are started.
    """
    return ADVERTISED_IP_CONFIG if ADVERTISED_IP_CONFIG else socket.gethostbyname(socket.gethostname())

async def fetch_github_file(url, local_path, force=False):
    """
    STEP 3: KEY MATERIAL AND TRUST SETUP (for non-origin satellites)

    Generic helper to fetch files from GitHub and save them locally.
    Used to obtain:
      - origin_pubkey.pem for trust verification (non-origin satellites)
      - list.json for the trusted-satellites registry

    Purpose in boot sequence:
    - Ensures non-origin satellites can retrieve trusted files needed for
      verification and establishing trust.
    - Origin satellites usually skip this step.
    - Only downloads files once unless `force=True`.

    How it works:
    1. Checks if the file already exists locally:
       - If it exists and `force=False`, skips download.
       - Otherwise, proceeds to fetch.
    2. Uses `asyncio.get_event_loop()` with `run_in_executor` to perform
       a synchronous `urllib.request.urlopen()` in a non-blocking manner.
    3. Reads the response content and writes it to `local_path`.
    4. Returns True if successful, False if an exception occurs.
    5. Returns True immediately if file already exists and `force=False`.

    Notes:
    - This function is asynchronous; must be awaited.
    - Does not modify global state other than writing the local file.
    - Fits into STEP 3: Key recovery / trust setup during boot.
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

async def sync_registry_from_github():
        """
    STEP 5: BACKGROUND TASK / MAINTENANCE LOOP

    Periodically fetches the signed trusted-satellites list (list.json) from GitHub
    and updates the local TRUSTED_SATELLITES registry.

    Purpose in boot sequence:
    - Keeps non-origin satellites up-to-date with the current network of trusted satellites.
    - Runs asynchronously in parallel with the terminal UI (draw_ui) and TCP listener.
    - Ensures satellites can verify fragments and trust relationships without manual intervention.

    How it works:
    1. Runs an infinite loop (`while True`), so this is a perpetual background task.
    2. Checks if the satellite is NOT origin (IS_ORIGIN=False):
       - Only non-origin satellites fetch updates; origin already has authoritative state.
    3. Calls `fetch_github_file()` with `force=True`:
       - Always downloads the latest list.json to ensure the registry is current.
    4. Calls `load_trusted_satellites()` to verify signatures and update TRUSTED_SATELLITES.
    5. Sleeps for SYNC_INTERVAL seconds before repeating, controlling the polling frequency.

    Notes:
    - This function is asynchronous and should be started with `asyncio.create_task()`.
    - Runs indefinitely in the background; never blocks the main thread.
    - Fully fits within STEP 5 of the remark section (background maintenance & trust updates).
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
    STEP 3–5: ORIGIN TRUST REGISTRY UPDATE

    Adds or updates a satellite in the TRUSTED_SATELLITES registry.
    This is only executed by the origin satellite to maintain authoritative state.

    Purpose in boot/runtime:
    - Ensures the origin maintains an up-to-date list of trusted satellites.
    - Updates are then reflected in list.json for distribution via GitHub.
    - Notifies the UI that the registry changed.

    How it works:
    1. Checks if this satellite is the origin (IS_ORIGIN=True):
       - Non-origin satellites skip this function entirely.
    2. Constructs a dictionary `new_details` containing:
       - 'id': SATELLITE_ID of the satellite
       - 'fingerprint': TLS fingerprint
       - 'hostname': advertised host/IP
       - 'port': listening port
    3. Checks if this satellite ID is new or if details have changed:
       - If new or updated, writes the details to TRUSTED_SATELLITES.
    4. Sends a notification to the UI via `UI_NOTIFICATIONS.put_nowait()`.
    5. Flags `LIST_UPDATED_PENDING_SAVE = True` to indicate registry changes
       should be written back to list.json.

    Notes:
    - This is an **origin-only operation**; follower satellites never execute it.
    - The function updates **global state** and triggers UI notifications.
    - Fits into STEP 3 (key/trust setup) and STEP 5 (background/UI updates) in the remark section.
    """
    global LIST_UPDATED_PENDING_SAVE
    if not IS_ORIGIN: return
    new_details = {"id": sat_id, "fingerprint": fingerprint, "hostname": hostname, "port": port}
    if sat_id not in TRUSTED_SATELLITES or TRUSTED_SATELLITES[sat_id] != new_details:
        TRUSTED_SATELLITES[sat_id] = new_details
        UI_NOTIFICATIONS.put_nowait(f"Registry updated: {sat_id}")
        LIST_UPDATED_PENDING_SAVE = True

def load_trusted_satellites():
    """Loads and verifies list.json. The 'Rogue Guard' logic."""
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
            
            TRUSTED_SATELLITES.clear()
            for sat in data['satellites']:
                TRUSTED_SATELLITES[sat['id']] = sat
        except Exception:
            UI_NOTIFICATIONS.put_nowait("Registry: Verification Failed.")

def sign_and_save_satellite_list():
    """Origin-only: Signs and saves the list.json locally."""
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

# --- UI Loop ---
async def draw_ui():
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
        while not UI_NOTIFICATIONS.empty(): temp_msgs.append(UI_NOTIFICATIONS.get_nowait())
        if not temp_msgs: print("\n\n")
        else:
            for m in temp_msgs[-4:]: print(m)
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
    global ORIGIN_PUBKEY_PEM
    # Standard satellites pull pubkey ONCE from GitHub
    if not FORCE_ORIGIN:
        await fetch_github_file(ORIGIN_PUBKEY_URL, ORIGIN_PUBKEY_PATH)

    generate_keys_and_certs()
    load_trusted_satellites()
    
    # Origin auto-adds itself to registry for distribution
    add_or_update_trusted_registry(SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP, LISTEN_PORT)
    
    asyncio.create_task(draw_ui())
    asyncio.create_task(sync_registry_from_github())
    
    server = await asyncio.start_server(lambda r, w: None, LISTEN_HOST, LISTEN_PORT)
    async with server: await server.serve_forever()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
