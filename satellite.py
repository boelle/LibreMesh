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
    STEP 4: Determine the IP address this satellite will advertise to peers and origin.

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
    return ADVERTISED_IP_CONFIG if ADVERTISED_IP_CONFIG else socket.gethostbyname(socket.gethostname()) # Return configured IP or resolve local hostname

async def fetch_github_file(url, local_path, force=False):
    """
    Step 3a: Downloads a file from a GitHub URL and saves it locally.

    Purpose:
    - Provides a simple mechanism to fetch the origin public key or 
      trusted satellites list from GitHub.
    - Ensures that each satellite can retrieve authoritative files
      from a centralized source for secure bootstrapping.

    Parameters:
    - url (str): The full HTTPS URL pointing to the file on GitHub.
    - local_path (str): The path on local filesystem where the file should be saved.
    - force (bool, default=False): If True, the file is always downloaded even if it exists locally.

    High-level behavior:
    - Checks if the local file exists. If `force` is False and the file exists, it skips download.
    - Performs an asynchronous HTTP GET request to fetch the file contents.
    - Writes the fetched content to `local_path` in a safe manner.
    - Handles network errors gracefully without raising unhandled exceptions.

    Design constraints:
    - Assumes the GitHub URL is public and accessible; no authentication handled.
    - File overwrite occurs only if `force` is True or local file is missing.
    - The function is non-blocking and can run in parallel with other async tasks.

    Operational context:
    - Used during satellite boot (`main()`) for initial retrieval of `origin_pubkey.pem` or `list.json`.
    - Complements periodic tasks like `sync_registry_from_github()` for ongoing updates.
    - Errors are logged via `UI_NOTIFICATIONS` queue for operator awareness.

    Notes:
    - This function does not verify cryptographic signatures or hashes of downloaded content.
    - Intended for lightweight, reliable file retrieval during startup.
    - Safe for repeated calls; minimizes unnecessary network traffic if files exist.
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
    Step 7: Periodically synchronizes node information with peer satellites.

    Purpose:
    - Keeps each satellite aware of other online satellites and storage nodes
      in the network.
    - Updates global `REMOTE_SATELLITES` with current peer statuses.
    - Facilitates future peer-to-peer replication and repair tasks.

    High-level behavior:
    - Iterates over known trusted satellites (`TRUSTED_SATELLITES`) excluding self.
    - Attempts to connect asynchronously to each satellite's listening port.
    - Requests their current nodes and repair queue status.
    - Updates local `REMOTE_SATELLITES` dictionary with the received data.
    - Handles connection failures gracefully, logs issues via `UI_NOTIFICATIONS`.

    Operational context:
    - Runs continuously in an asynchronous loop, sleeping for `NODE_SYNC_INTERVAL` seconds between rounds.
    - Complements origin-based synchronization (`push_status_to_origin()`), providing peer awareness even if origin is temporarily unreachable.
    - Assumes a trusted network; no encryption/authentication is handled in this step.

    Design constraints:
    - Non-blocking: uses asyncio tasks to avoid halting other operations.
    - Lightweight: does not persist data to disk, only updates in-memory structures.
    - Resilient to network failures: failed connections do not raise unhandled exceptions.

    Inline remarks suggestions:
    - Annotate connection attempt to peer, payload exchange, and update of `REMOTE_SATELLITES`.
    - Explain retry behavior or lack thereof.
    - Clarify that `REMOTE_SATELLITES` stores per-satellite nodes and repair queue snapshots.
    """
    while True:
        for sat_id, sat_info in TRUSTED_SATELLITES.items():
            if sat_id == SATELLITE_ID:
                continue  # skip self

            peer_host = sat_info['hostname']
            peer_port = sat_info['port']

            try:
                # Simple TCP request to send local NODES
                reader, writer = await asyncio.open_connection(peer_host, peer_port) # Connect to peer satellite
                # Send serialized NODES
                writer.write(json.dumps(NODES).encode('utf-8')) # Send local node info
                await writer.drain()

                # Receive peer's NODES
                data = await reader.read(65536)
                peer_nodes = json.loads(data.decode('utf-8')) # Deserialize peer node info

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
    Step 3a: Periodically fetches the trusted satellites registry from GitHub.

    Purpose:
    - Keeps the local trusted satellites registry up to date with the
      canonical list maintained in GitHub.
    - Ensures that satellites have a consistent view of trusted peers
      without requiring manual intervention.
    - Supports secure distribution of new satellite identities for registration.

    High-level behavior:
    - Runs indefinitely in a background loop with a sleep interval defined
      by SYNC_INTERVAL.
    - Downloads the remote `list.json` file from LIST_JSON_URL.
    - Compares the remote registry to the local `LIST_JSON_PATH`.
    - Updates local in-memory `TRUSTED_SATELLITES` and triggers a save if
      changes are detected.

    Data handled:
    - Reads JSON from GitHub.
    - Validates integrity superficially (well-formed JSON and expected fields).
    - Updates local trusted satellite structures (ID, fingerprint, hostname, port).

    Design constraints:
    - Assumes that GitHub-hosted JSON is authoritative for the canonical list.
    - Non-blocking; network errors are caught and logged without
      interrupting the loop.
    - Avoids overwriting local changes that were manually or dynamically added
      unless GitHub version differs.

    Operational context:
    - Launched during `main()` startup as a background task.
    - Complements other background tasks like:
        - draw_ui()
        - node_sync_loop()
        - announce_to_origin()
    - Maintains in-memory and persisted consistency of trusted satellites.

    Future considerations:
    - Could implement checksum or signature verification for higher trust.
    - Could notify UI of new or removed satellites automatically.
    - May integrate with repair queue awareness in future enhancements.

    Notes:
    - This function is advisory and maintenance-focused.
    - Errors in fetching do not halt the satellite; they are logged for operator awareness.
    """
    
    while True:
        if not IS_ORIGIN:
            # Only non-origin satellites fetch list.json from GitHub
            await fetch_github_file(LIST_JSON_URL, LIST_JSON_PATH, force=True) # Force pull latest list
            load_trusted_satellites()
        # Load and verify trusted satellites registry
        await asyncio.sleep(SYNC_INTERVAL)

def add_or_update_trusted_registry(sat_id, fingerprint, hostname, port):
"""
STEP 3b: Add or update a satellite entry in the in-memory trusted registry.

Purpose:
- Maintains a dictionary of trusted satellites for identity verification.
- Ensures the satellite registry reflects current fingerprint, hostname/IP, and listening port.
- Notifies the local UI on registry changes.
- Marks that the registry has pending updates to save.

Parameters:
- sat_id (str): Unique identifier of the satellite.
- fingerprint (str): TLS fingerprint of the satellite's certificate.
- hostname (str): Advertised hostname or IP of the satellite.
- port (int): Listening port of the satellite.

Behavior:
- If this node is not the origin, returns immediately (only origin updates registry).
- Constructs a details dictionary with satellite identity and network info.
- If the satellite is new or its details have changed:
  - Updates the TRUSTED_SATELLITES dictionary.
  - Queues a UI notification via `UI_NOTIFICATIONS`.
  - Flags `LIST_UPDATED_PENDING_SAVE` to true for later persistence.
- Does NOT perform network I/O or direct file writes.

Notes:
- Modifies the global TRUSTED_SATELLITES dictionary.
- UI notification provides operator feedback on registry changes.
- LIST_UPDATED_PENDING_SAVE signals that a signed update should be written later.
"""
    global LIST_UPDATED_PENDING_SAVE
    if not IS_ORIGIN: return # Followers do not modify the registry
    new_details = {
    "id": sat_id,             # Unique satellite ID
    "fingerprint": fingerprint,  # TLS fingerprint for trust
    "hostname": hostname,     # Advertised reachable IP/host
    "port": port              # TCP listening port
    }
    if sat_id not in TRUSTED_SATELLITES or TRUSTED_SATELLITES[sat_id] != new_details:
        TRUSTED_SATELLITES[sat_id] = new_details
        UI_NOTIFICATIONS.put_nowait(f"Registry updated: {sat_id}") # Inform operator via UI
        LIST_UPDATED_PENDING_SAVE = True 

def load_trusted_satellites():
"""
Step 3a/3b: Load and verify the trusted satellites registry from disk.

Purpose:
- Reads the signed registry file at LIST_JSON_PATH.
- Verifies the registry signature using the origin public key (ORIGIN_PUBKEY_PEM).
- On successful verification, updates TRUSTED_SATELLITES in memory.

Behavior:
1. If the file at LIST_JSON_PATH does not exist, no action is taken.
2. Loads the file and parses it as JSON containing:
   - 'data': registry dictionary
   - 'signature': base64-encoded signature
3. If the origin public key is not loaded (ORIGIN_PUBKEY_PEM is None), return early.
4. Loads the origin public key and attempts to verify the signature over
   the canonical JSON of the registry data.
5. On successful verification:
   - Clears current TRUSTED_SATELLITES.
   - Populates TRUSTED_SATELLITES with entries from data['satellites'].
6. On any exception (missing file, parse error, verification failure, etc.):
   - A UI notification "Registry: Verification Failed." is enqueued.
   - TRUSTED_SATELLITES remains unchanged.

Notes:
- This function enforces cryptographic integrity of the trusted registry.
- Only registries signed by the origin are accepted.
- Global state modified: TRUSTED_SATELLITES.
- Called during startup and periodic registry synchronization.
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
            json_bytes = json.dumps(data, indent=4, sort_keys=True).encode('utf-8') # Canonical JSON for signature verification
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
Step 3b: Sign and persist the trusted satellite registry for distribution.

Purpose:
- Produces the authoritative, signed registry of trusted satellites.
- Ensures integrity and authenticity of the registry using the
  origin satellite's private signing key.

Behavior:
1. Serializes the TRUSTED_SATELLITES structure into a canonical JSON form.
2. Loads the origin private key from disk.
3. Signs the serialized registry using RSA with SHA-256.
4. Writes a JSON file containing:
   - 'data': the trusted satellite registry
   - 'signature': base64-encoded signature over the data
5. Saves the result to LIST_JSON_PATH for later distribution
   via GitHub or other sync mechanisms.

Operational Context:
- Intended to run ONLY on the origin satellite.
- Called after registry mutations (add/update/remove satellite).
- Followers must verify this signature before accepting registry updates.

Failure Handling:
- Any signing or file I/O error results in a UI notification.
- No partial or unsigned registry is written.

Security Notes:
- This function establishes the cryptographic root of trust
  for the entire satellite network.
- Compromise of the origin private key compromises registry trust.
"""
    global LIST_UPDATED_PENDING_SAVE
    if not IS_ORIGIN or not ORIGIN_PRIVKEY_PEM: return
    try:
        private_key = serialization.load_pem_private_key(ORIGIN_PRIVKEY_PEM, password=None, backend=default_backend())
        data = {"satellites": list(TRUSTED_SATELLITES.values())}
        json_bytes = json.dumps(data, indent=4, sort_keys=True).encode('utf-8')  # Canonical JSON for reproducible signing
        sig = private_key.sign(json_bytes, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
        with open(LIST_JSON_PATH, 'w') as f:
            json.dump({"data": data, "signature": base64.b64encode(sig).decode('utf-8')}, f, indent=4)
        LIST_UPDATED_PENDING_SAVE = False # Only reset after successful sign & save
    except Exception: pass

def generate_keys_and_certs():
"""
Step 3a: Generate or load cryptographic identity material for this satellite.

Purpose:
- Establishes the cryptographic identity of the satellite node.
- Ensures the presence of a private key, public key, and TLS certificate
  before any network communication occurs.

Behavior:
- Checks whether the required key and certificate files already exist
  on disk.
- If all required files are present:
    - Loads the existing private key, public key, and certificate.
- If any required file is missing:
    - Generates a new RSA private key.
    - Derives the corresponding public key.
    - Generates a self-signed X.509 TLS certificate.
    - Writes all generated artifacts to disk.

Side Effects:
- Writes cryptographic material to the filesystem if regeneration is required.
- Computes and sets the TLS fingerprint derived from the certificate.
- Updates global identity-related state used elsewhere in the program.

Operational Context:
- Called once during startup as part of identity establishment.
- Must run before any satellite announces itself or accepts connections.
- Used by both origin and non-origin satellites.

Security Notes:
- Certificates are self-signed; trust is established via fingerprint
  verification and signed registry distribution rather than a CA.
- Regenerating keys will change the satellite’s identity and TLS fingerprint.
- Private key material must be protected from unauthorized access.

Design Notes:
- Function is intentionally idempotent and safe to call multiple times.
- No network operations are performed here to keep boot-time complexity low.
"""
    global SATELLITE_ID, TLS_FINGERPRINT, IS_ORIGIN, ADVERTISED_IP, ORIGIN_PUBKEY_PEM, ORIGIN_PRIVKEY_PEM
    # 1. Cert Generation
    if not os.path.exists(CERT_PATH):
        key = rsa.generate_private_key(65537, 2048)
        subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(SATELLITE_NAME))])
        cert = x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.utcnow()).not_valid_after(datetime.utcnow() + timedelta(days=3650)).sign(key, hashes.SHA256()) # Self-signed certificate: subject = issuer = satellite CN
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
Step 6: Handle inbound satellite → origin synchronization connections.

Purpose:
- Acts as the server-side entry point for satellites reporting their
  identity, status, and operational metadata to the origin node.
- Allows the origin to maintain an authoritative, signed registry of
  trusted satellites and their advertised endpoints.

Operational Role:
- This handler is only meaningful on the origin node.
- Non-origin satellites may still accept connections, but will not
  process or persist synchronization payloads.

Expected Payload:
- Incoming data must be valid JSON containing, at minimum:
    - id: unique satellite identifier
    - fingerprint: TLS certificate fingerprint
    - ip: advertised network address
    - port: listening TCP port
- Optional fields may include:
    - nodes: known storage or peer nodes
    - repair_queue: pending repair tasks

Validation & Error Handling:
- Payload keys are validated before processing.
- Missing or malformed payloads raise explicit errors.
- Any exception during parsing or validation results in:
    - A notification being emitted to the UI notification system.
    - The connection being closed cleanly.

Behavior on Origin:
- Updates or inserts the satellite entry into TRUSTED_SATELLITES.
- Persists changes by signing and saving the registry when necessary.
- Emits UI notifications for new registrations or updates.

Side Effects:
- Mutates global state (TRUSTED_SATELLITES).
- Writes registry data to disk via signed persistence.
- Emits messages into UI_NOTIFICATIONS for operator visibility.

Concurrency Notes:
- Designed to be called concurrently by asyncio’s TCP server.
- Does not block the event loop beyond minimal JSON parsing and I/O.

Design Notes:
- No authentication handshake is performed here beyond payload validation;
  trust enforcement relies on fingerprint verification and signed registry
  distribution.
- This function is intentionally strict to surface malformed or unexpected
  sync attempts during early testing and development.
"""
    peer_ip = writer.get_extra_info("peername")[0]

    try:
        data = await reader.read(4096) # Read incoming payload from satellite
        payload = json.loads(data.decode())
        required_keys = {"id", "fingerprint", "ip", "port"} # Validate required fields

        if not required_keys.issubset(payload):
            raise ValueError(
                f"Invalid node sync payload keys={list(payload.keys())}"
            )

        sat_id = payload["id"] # optional node snapshot
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
                "repair_queue": payload.get("repair_queue", []) # optional repair queue snapshot
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

- Non-origin satellites notify the origin of their presence after a short delay (3s)
  to allow boot sequence tasks (key generation, registry loading) to complete.
- Runs once per boot, not periodically.
- Payload includes:
  - 'id': SATELLITE_ID
  - 'fingerprint': TLS_FINGERPRINT
  - 'ip': ADVERTISED_IP
  - 'port': LISTEN_PORT
- Origin may register or update the satellite in TRUSTED_SATELLITES.
- Connection errors or failures are reported via UI_NOTIFICATIONS queue.
"""
    await asyncio.sleep(3)  # allow boot to finish

    if IS_ORIGIN:
        return

    try:
        reader, writer = await asyncio.open_connection(ORIGIN_HOST, ORIGIN_PORT)

        payload = {
            "id": SATELLITE_ID, # unique satellite identifier
            "fingerprint": TLS_FINGERPRINT, # TLS certificate fingerprint
            "ip": ADVERTISED_IP, # advertised network IP
            "port": LISTEN_PORT, # advertised network IP
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
            "id": SATELLITE_ID, # unique satellite identifier
            "fingerprint": TLS_FINGERPRINT, # unique satellite identifier
            "ip": ADVERTISED_IP,  # advertised IP
            "port": LISTEN_PORT, # advertised IP
        }

        writer.write(json.dumps(payload).encode())
        await writer.drain()

        writer.close()
        await writer.wait_closed()

        UI_NOTIFICATIONS.put_nowait("Registered with origin")

    except Exception as e:
        UI_NOTIFICATIONS.put_nowait(f"Origin registration failed: {e}") # notify operator of failure



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
        os.system('clear' if os.name == 'posix' else 'cls') # clear terminal
        print("="*54 + "\n                Satellite Node Status\n" + "="*54) # Display Node Status header
        print(f"{'Node ID':<18} | {'Rank':<4} | {'Last Seen (s)':<13} | {'Uptime (s)':<10}\n" + "-" * 54)
        if not NODES: print("No nodes connected  | N/A  | N/A           | N/A")
        else:
            for k, v in NODES.items(): print(f"{k[:15]:<18} | Node | {int(time.time()-v):<13} | N/A")
            # Loop through NODES dictionary to display last seen time for each node

        print("\n" + "="*54 + "\n                     Repair Queue\n" + "="*54) # Display Repair Queue header
        print(f"{'Job ID (Fragment)':<30} | {'Status':<6} | {'Claimed By':<10}\n" + "-" * 54)
        print("Queue is empty                 | N/A    | N/A") # Placeholder if queue is empty
        print("\n" + "="*54 + "\n                     Notifications\n" + "="*54) # Notifications header
        temp_msgs = []
        while not UI_NOTIFICATIONS.empty():
            NOTIFICATION_LOG.append(UI_NOTIFICATIONS.get_nowait()) # Notifications header

        if not NOTIFICATION_LOG:
            print("\n\n")
        else:
            for m in NOTIFICATION_LOG:
                print(m)  # Display recent UI notifications
                
        print("\n" + "="*54 + "\n               Suspicious IPs Advisory\n" + "="*54)  # Suspicious IPs section
        print("No suspicious activity detected.") # Placeholder for security alerts
        print("\n" + "="*54 + "\n            Satellite ID + TLS Fingerprint\n" + "="*54) # Satellite Identity header
        print(f"Satellite ID:          {SATELLITE_ID}") # Display Satellite ID
        print(f"Advertising IP:        {ADVERTISED_IP}") # Display advertised IP
        print(f"Origin Status:         {'ORIGIN' if IS_ORIGIN else 'SATELLITE'}") # Display origin status
        print(f"TLS Fingerprint:       {TLS_FINGERPRINT}")  # Display TLS fingerprint
        print(f"Trusted Satellites:    {len(TRUSTED_SATELLITES)} in list.json\n" + "="*54) # Display trusted satellites count

        await asyncio.sleep(2) # Sleep briefly before refreshing the UI again

async def main():
    """
    STEP 1–5: BOOT SEQUENCE ORCHESTRATION

    Entry point for the satellite node. This function performs full
    initialization, role determination, identity setup, trust loading,
    background task scheduling, and network listener startup.

    This function is responsible for orchestrating the complete satellite
    lifecycle up to steady-state operation.

    -----------------------------------------------------------------------
    BOOT SEQUENCE RESPONSIBILITIES
    -----------------------------------------------------------------------

    STEP 1: Initialization
    - Relies on module-level global state initialization (constants, queues,
      registries).
    - No network or cryptographic operations occur yet.

    STEP 2: Role Definition
    - Determines whether this node acts as ORIGIN or FOLLOWER based on
      FORCE_ORIGIN.
    - Role selection affects:
        - Whether signing keys are generated
        - Whether registry updates are allowed
        - Whether outbound registration occurs

    STEP 3: Key Recovery & Trust Setup
    - For non-origin satellites:
        - Fetches the origin public key once from GitHub via
          `fetch_github_file()`.
    - Generates or loads:
        - TLS private key
        - TLS certificate
        - Origin signing keys (origin only)
    - Loads and verifies the trusted satellite registry from disk
      (`load_trusted_satellites()`).
    - Origin satellites automatically insert themselves into the registry
      for later GitHub distribution.

    STEP 4: Identity Establishment
    - Establishes immutable runtime identity values:
        - SATELLITE_ID
        - TLS_FINGERPRINT
        - ADVERTISED_IP
    - Identity must be fully established before any network communication
      or UI rendering begins.

    STEP 5: UI & Background Tasks
    - Launches long-running asynchronous background tasks:
        - `draw_ui()` — terminal status interface
        - `sync_registry_from_github()` — periodic registry refresh
        - `sync_nodes_with_peers()` — peer satellite awareness
        - `announce_to_origin()` — one-time boot announcement (followers)
        - `node_sync_loop()` — periodic status push to origin (followers)
    - Background tasks are non-blocking and run concurrently.

    -----------------------------------------------------------------------
    NETWORK LISTENER
    -----------------------------------------------------------------------

    - Starts an asyncio TCP server bound to LISTEN_HOST:LISTEN_PORT.
    - Uses `handle_node_sync()` as the connection handler.
    - Accepts inbound satellite → origin synchronization messages.
    - Runs indefinitely via `serve_forever()` to keep the control plane alive.

    -----------------------------------------------------------------------
    STATUS REPORTING CONTEXT
    -----------------------------------------------------------------------

    - Although this function does not directly push status to the origin,
      it is responsible for scheduling the background mechanisms that do:
        - `announce_to_origin()` (single delayed announcement)
        - `node_sync_loop()` → `push_status_to_origin()` (periodic updates)

    - These status updates allow the origin to maintain an up-to-date view
      of:
        - Satellite identity and fingerprint
        - Advertised IP and listening port
        - Known nodes
        - Repair queue state

    -----------------------------------------------------------------------
    DESIGN NOTES
    -----------------------------------------------------------------------

    - This function is the **only valid entry point** for the satellite.
    - It must run exactly once per process lifetime.
    - All global state mutations are intentional and ordered.
    - Background tasks are explicitly created to avoid blocking the TCP server.
    - Follower registration currently overlaps with `announce_to_origin()`;
      consolidation is possible but deferred intentionally for clarity.

    This function fully implements and enforces the boot sequence described
    in the top-level module documentation.
    """
    global ORIGIN_PUBKEY_PEM
    # Standard satellites pull pubkey ONCE from GitHub
    if not FORCE_ORIGIN:
        # Fetch origin public key used to verify signed registry data
        await fetch_github_file(ORIGIN_PUBKEY_URL, ORIGIN_PUBKEY_PATH)

    # Start periodic node → origin status sync (non-origin satellites only)
    if not IS_ORIGIN:
        # Runs in background and periodically pushes node status to origin
        asyncio.create_task(node_sync_loop())
    # Generate TLS keys and certificates if not already present
    generate_keys_and_certs()
    # Load trusted satellites registry from disk into memory
    load_trusted_satellites()
    # Register this satellite with the origin (no-op for origin itself)
    await register_with_origin()
    
    # Origin auto-adds itself to the trusted registry for distribution
    add_or_update_trusted_registry(SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP, LISTEN_PORT)
    
    # Origin signs and persists the trusted satellite list to disk
    if IS_ORIGIN:
        sign_and_save_satellite_list()

    # Launch UI and registry sync in background
    asyncio.create_task(draw_ui())
    # Periodically sync trusted satellite registry from GitHub
    asyncio.create_task(sync_registry_from_github())
    # Background peer-to-peer node synchronization
    asyncio.create_task(sync_nodes_with_peers())
    # Announce presence to origin after startup delay (non-origin only)
    asyncio.create_task(announce_to_origin())

    # Start TCP server to accept incoming satellite → origin registration and status sync. Handles updates to TRUSTED_SATELLITES, node awareness, and repair queue information.
    server = await asyncio.start_server(handle_node_sync, LISTEN_HOST, LISTEN_PORT)
    # Keep the TCP server running indefinitely
    async with server: await server.serve_forever()

async def push_status_to_origin():
    """
    STEP 2–4: PUSH STATUS TO ORIGIN

    Sends this satellite's current operational status to the origin node.
    This function is the fundamental reporting mechanism that allows the
    origin to maintain an up-to-date, authoritative view of all follower
    satellites in the mesh.

    -----------------------------------------------------------------------
    PURPOSE
    -----------------------------------------------------------------------

    - Keeps the origin informed of this satellite’s identity and health.
    - Enables centralized awareness for monitoring, coordination, and
      future repair or orchestration logic.
    - Provides the origin with visibility into:
        - Connected storage or peer nodes
        - Current repair queue state

    -----------------------------------------------------------------------
    PAYLOAD CONTENT
    -----------------------------------------------------------------------

    The JSON payload sent to the origin includes:

    - id:
        Logical satellite identifier (SATELLITE_ID)
    - fingerprint:
        TLS certificate fingerprint used for trust verification
    - ip:
        Advertised network address (ADVERTISED_IP)
    - port:
        TCP listening port (LISTEN_PORT)
    - nodes:
        Known storage / peer nodes with last-seen timestamps (NODES)
    - repair_queue:
        Snapshot of the current repair queue state

    -----------------------------------------------------------------------
    BEHAVIOR
    -----------------------------------------------------------------------

    - If this satellite is the origin (IS_ORIGIN=True), the function
      returns immediately and performs no action.
    - Establishes a TCP connection to ORIGIN_HOST:ORIGIN_PORT.
    - Sends the JSON-encoded status payload.
    - Flushes the write buffer and closes the connection cleanly.
    - Any connection, write, or serialization errors are caught and
      logged via UI_NOTIFICATIONS without raising exceptions.

    -----------------------------------------------------------------------
    OPERATIONAL CONTEXT
    -----------------------------------------------------------------------

    - This function performs a **single status push**.
    - It is intended to be called repeatedly by `node_sync_loop()`,
      which schedules periodic reporting based on NODE_SYNC_INTERVAL.
    - It is also conceptually related to the one-time boot announcement
      performed by `announce_to_origin()`, but differs in that it includes
      dynamic runtime state.

    -----------------------------------------------------------------------
    DESIGN NOTES
    -----------------------------------------------------------------------

    - Runs fully asynchronously and never blocks the event loop.
    - Uses global state only for read access (identity, nodes, queues).
    - Always closes network resources to prevent file descriptor leaks.
    - Payload format is expected by the origin’s `handle_node_sync()` handler.
    - This function does not perform registry mutations directly; it only
      reports state to the origin.

    This function is a core component of the satellite → origin control
    plane synchronization mechanism.
    """
   
    if IS_ORIGIN: # Origin never reports status to itself; avoids loopback noise and recursion
        return  
    # Construct the status payload advertised to the origin
    payload = {
        "id": SATELLITE_ID, # Stable logical identity of this satellite
        "fingerprint": TLS_FINGERPRINT, # Cryptographic identity for trust validation
        "ip": ADVERTISED_IP, # Reachable address advertised to origin
        "port": LISTEN_PORT, # Port this satellite listens on
        "nodes": NODES, # Known storage / peer nodes and last-seen data
        "repair_queue": list(REPAIR_QUEUE._queue) # Known storage / peer nodes and last-seen data
    }

    try:
        # Open outbound TCP connection to the origin's sync endpoint
        reader, writer = await asyncio.open_connection(ORIGIN_HOST, ORIGIN_PORT)
        # Send JSON-encoded status payload
        writer.write(json.dumps(payload).encode())
        await writer.drain()
    except Exception as e:
        # Non-fatal: log failure but allow future retries via node_sync_loop
        UI_NOTIFICATIONS.put_nowait(f"Node push error: {e}")
    finally:
        # Always close the socket cleanly to avoid FD leaks
        if 'writer' in locals():
            writer.close()
            await writer.wait_closed()

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

    # Background task: periodically report this satellite's state to the origin
    while True:
        # Perform a single status push (no-op on origin nodes)
        await push_status_to_origin()
        # Throttle reporting to avoid excessive network traffic
        await asyncio.sleep(NODE_SYNC_INTERVAL)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
