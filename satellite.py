"""
===============================================================================
PROJECT: LibreMesh Satellite (Control Plane)
VERSION: 2025.12.15
===============================================================================

CORE ARCHITECTURE RULES:
------------------------
1. CONTROL PLANE vs DATA PLANE:
   - This script is a "Satellite" (Control Plane). It DOES NOT store data.
   - Satellite MUST NEVER be listed in the 'Node Status' UI table.

2. BOOT SEQUENCE:
   - STEP 1: INITIALIZATION: Global states (NODES, TRUSTED_SATELLITES).
   - STEP 2: IDENTITY: 'cert.pem' defines the TLS identity/fingerprint.
   - STEP 3: ROLE: Determined by 'FORCE_ORIGIN' and 'origin_privkey.pem'.
   - STEP 4: UI & LISTENING: Parallel background tasks for UI and TCP server.

3. SECURITY & DISTRIBUTION:
   - 'FORCE_ORIGIN = False' prevents accidental master key generation.
   - Standard satellites fetch the master public key from a trusted GitHub URL.
   - Verification MUST happen via 'origin_pubkey.pem' before list.json is trusted.

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

# ROLE CONFIGURATION
FORCE_ORIGIN = True # Set to False for standard satellites to prevent key gen
ORIGIN_PUBKEY_URL = "https://raw.githubusercontent.com/boelle/LibreMesh/refs/heads/main/origin_pubkey.pem"

NODES = {} 
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

# --- Helper Functions ---
def get_local_ip():
    return ADVERTISED_IP_CONFIG if ADVERTISED_IP_CONFIG else socket.gethostbyname(socket.gethostname())

async def fetch_origin_pubkey():
    """Attempts to download the master public key from GitHub if missing."""
    if not os.path.exists(ORIGIN_PUBKEY_PATH):
        UI_NOTIFICATIONS.put_nowait("Fetching master public key from GitHub...")
        try:
            # Using loop.run_in_executor to keep urllib non-blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: urllib.request.urlopen(ORIGIN_PUBKEY_URL).read())
            with open(ORIGIN_PUBKEY_PATH, "wb") as f:
                f.write(response)
            UI_NOTIFICATIONS.put_nowait("Master public key successfully updated from GitHub.")
            return True
        except Exception as e:
            UI_NOTIFICATIONS.put_nowait(f"GitHub Fetch Failed: {e}")
            return False
    return True

def add_or_update_trusted_registry(sat_id, fingerprint, hostname, port):
    global LIST_UPDATED_PENDING_SAVE
    if not IS_ORIGIN: return
    new_details = {"id": sat_id, "fingerprint": fingerprint, "hostname": hostname, "port": port}
    if sat_id not in TRUSTED_SATELLITES or TRUSTED_SATELLITES[sat_id] != new_details:
        TRUSTED_SATELLITES[sat_id] = new_details
        UI_NOTIFICATIONS.put_nowait(f"Registry Updated: {sat_id}")
        LIST_UPDATED_PENDING_SAVE = True

def load_trusted_satellites():
    global TRUSTED_SATELLITES
    if os.path.exists(LIST_JSON_PATH):
        try:
            with open(LIST_JSON_PATH, 'r') as f:
                signed_data = json.load(f)
            data = signed_data['data']
            # Security Check: Ensure we have a key to verify the signature
            if not ORIGIN_PUBKEY_PEM:
                UI_NOTIFICATIONS.put_nowait("Registry Warning: No public key found for verification.")
                return

            public_key = serialization.load_pem_public_key(ORIGIN_PUBKEY_PEM, backend=default_backend())
            signature = base64.b64decode(signed_data['signature'])
            json_data_bytes = json.dumps(data, indent=4, sort_keys=True).encode('utf-8')
            public_key.verify(signature, json_data_bytes, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
            for sat in data['satellites']:
                TRUSTED_SATELLITES[sat['id']] = sat
        except Exception as e:
            UI_NOTIFICATIONS.put_nowait(f"Registry Verification Error: {e}")

def sign_and_save_satellite_list():
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
    except Exception as e:
        UI_NOTIFICATIONS.put_nowait(f"Disk Write Error: {e}")

def generate_keys_and_certs():
    global SATELLITE_ID, TLS_FINGERPRINT, IS_ORIGIN, ADVERTISED_IP, ORIGIN_PUBKEY_PEM, ORIGIN_PRIVKEY_PEM
    # 1. TLS Identity Generation
    if not os.path.exists(CERT_PATH):
        key = rsa.generate_private_key(65537, 2048)
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"localhost")])
        cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.utcnow()).not_valid_after(datetime.utcnow() + timedelta(days=3650)).sign(key, hashes.SHA256())
        with open(KEY_PATH, "wb") as f: f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        with open(CERT_PATH, "wb") as f: f.write(cert.public_bytes(serialization.Encoding.PEM))

    # 2. Master Key Determination
    if os.path.exists(ORIGIN_PRIVKEY_PATH):
        # Found local private key -> Node is an Origin
        with open(ORIGIN_PUBKEY_PATH, "rb") as f: ORIGIN_PUBKEY_PEM = f.read()
        with open(ORIGIN_PRIVKEY_PATH, "rb") as f: ORIGIN_PRIVKEY_PEM = f.read()
        IS_ORIGIN = True
    elif os.path.exists(ORIGIN_PUBKEY_PATH):
        # Found only local public key -> Node is a Satellite
        with open(ORIGIN_PUBKEY_PATH, "rb") as f: ORIGIN_PUBKEY_PEM = f.read()
        IS_ORIGIN = False
    elif FORCE_ORIGIN:
        # No keys found, but FORCE_ORIGIN is True -> Generate new Master keys
        IS_ORIGIN = True
        priv = rsa.generate_private_key(65537, 2048)
        ORIGIN_PUBKEY_PEM = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        ORIGIN_PRIVKEY_PEM = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
        with open(ORIGIN_PUBKEY_PATH, "wb") as f: f.write(ORIGIN_PUBKEY_PEM)
        with open(ORIGIN_PRIVKEY_PATH, "wb") as f: f.write(ORIGIN_PRIVKEY_PEM)
    else:
        # No keys found and not forcing origin -> Will wait for GitHub fetch in main()
        IS_ORIGIN = False

    # 3. Attribute Extraction
    with open(CERT_PATH, 'rb') as f:
        cert = x509.load_pem_x509_certificate(f.read(), default_backend())
    
    cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    SATELLITE_ID = cn_attrs[0].value if cn_attrs else "localhost"
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

async def save_list_periodically():
    while True:
        await asyncio.sleep(10)
        if LIST_UPDATED_PENDING_SAVE:
            sign_and_save_satellite_list()

async def main():
    # Initial setup
    generate_keys_and_certs()
    
    # If standard satellite and missing key, fetch from GitHub
    if not IS_ORIGIN and not ORIGIN_PUBKEY_PEM:
        await fetch_origin_pubkey()
        # Reload key after fetch
        if os.path.exists(ORIGIN_PUBKEY_PATH):
            global ORIGIN_PUBKEY_PEM
            with open(ORIGIN_PUBKEY_PATH, "rb") as f:
                ORIGIN_PUBKEY_PEM = f.read()

    load_trusted_satellites()
    add_or_update_trusted_registry(SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP, LISTEN_PORT)
    
    # Background tasks
    asyncio.create_task(draw_ui())
    asyncio.create_task(save_list_periodically())
    
    server = await asyncio.start_server(lambda r, w: None, LISTEN_HOST, LISTEN_PORT)
    async with server: await server.serve_forever()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
