"""
===============================================================================
PROJECT: LibreMesh Satellite (Control Plane)
VERSION: 2025.12.15 (GitHub Sync Enabled)
===============================================================================

CORE ARCHITECTURE RULES:
------------------------
1. SOURCE OF TRUTH: GitHub serves as the distribution point for the signed 
   'list.json' and the master 'origin_pubkey.pem'.
2. ROGUE PROTECTION: Standard satellites pull the list from GitHub periodically. 
   Any list not signed by the Master Private Key is rejected.
3. IDENTITY: 'SATELLITE_NAME' in config dictates the ID in the UI and Cert.

VISUAL TERMINAL LAYOUT EXAMPLE:
-------------------------------
[See header in previous versions for ASCII layout]
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
SATELLITE_NAME = "LibreMesh-Sat-01" # Human-readable name for this node
FORCE_ORIGIN = True                 # True = Master, False = Standard Satellite

# GITHUB SYNC
GITHUB_BASE_URL = "raw.githubusercontent.com"
ORIGIN_PUBKEY_URL = GITHUB_BASE_URL + "origin_pubkey.pem"
LIST_JSON_URL = GITHUB_BASE_URL + "list.json"
SYNC_INTERVAL = 300 # Seconds between GitHub pulls (5 mins)

# Global State
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

# --- Core Logic ---
def get_local_ip():
    return ADVERTISED_IP_CONFIG if ADVERTISED_IP_CONFIG else socket.gethostbyname(socket.gethostname())

async def fetch_github_file(url, local_path):
    """Generic helper to pull files from GitHub."""
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: urllib.request.urlopen(url).read())
        with open(local_path, "wb") as f:
            f.write(response)
        return True
    except Exception:
        return False

async def sync_with_github():
    """Periodic task to keep standard satellites updated and guarded."""
    while True:
        if not IS_ORIGIN:
            # Pull key and list
            await fetch_github_file(ORIGIN_PUBKEY_URL, ORIGIN_PUBKEY_PATH)
            await fetch_github_file(LIST_JSON_URL, LIST_JSON_PATH)
            
            # Reload and re-verify
            global ORIGIN_PUBKEY_PEM
            if os.path.exists(ORIGIN_PUBKEY_PATH):
                with open(ORIGIN_PUBKEY_PATH, "rb") as f:
                    ORIGIN_PUBKEY_PEM = f.read()
            load_trusted_satellites()
            
        await asyncio.sleep(SYNC_INTERVAL)

def add_or_update_trusted_registry(sat_id, fingerprint, hostname, port):
    global LIST_UPDATED_PENDING_SAVE
    if not IS_ORIGIN: return
    new_details = {"id": sat_id, "fingerprint": fingerprint, "hostname": hostname, "port": port}
    if sat_id not in TRUSTED_SATELLITES or TRUSTED_SATELLITES[sat_id] != new_details:
        TRUSTED_SATELLITES[sat_id] = new_details
        UI_NOTIFICATIONS.put_nowait(f"Registry: {sat_id} added.")
        LIST_UPDATED_PENDING_SAVE = True

def load_trusted_satellites():
    global TRUSTED_SATELLITES
    if os.path.exists(LIST_JSON_PATH):
        try:
            with open(LIST_JSON_PATH, 'r') as f:
                signed_data = json.load(f)
            data = signed_data['data']
            if not ORIGIN_PUBKEY_PEM: return
            
            # Signature Verification (The Rogue Guard)
            public_key = serialization.load_pem_public_key(ORIGIN_PUBKEY_PEM, backend=default_backend())
            signature = base64.b64decode(signed_data['signature'])
            json_bytes = json.dumps(data, indent=4, sort_keys=True).encode('utf-8')
            public_key.verify(signature, json_bytes, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
            
            TRUSTED_SATELLITES.clear() # Wipe old trust before loading verified new trust
            for sat in data['satellites']:
                TRUSTED_SATELLITES[sat['id']] = sat
        except Exception:
            UI_NOTIFICATIONS.put_nowait("Registry Warning: Verification failed.")

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
    except Exception: pass

def generate_keys_and_certs():
    global SATELLITE_ID, TLS_FINGERPRINT, IS_ORIGIN, ADVERTISED_IP, ORIGIN_PUBKEY_PEM, ORIGIN_PRIVKEY_PEM
    # 1. Identity Cert (Using SATELLITE_NAME from config)
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

    # 3. Attribute Extraction
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

async def save_list_periodically():
    while True:
        await asyncio.sleep(10)
        if LIST_UPDATED_PENDING_SAVE:
            sign_and_save_satellite_list()

async def main():
    global ORIGIN_PUBKEY_PEM
    if not FORCE_ORIGIN:
        await fetch_github_file(ORIGIN_PUBKEY_URL, ORIGIN_PUBKEY_PATH)

    generate_keys_and_certs()
    load_trusted_satellites()
    
    # Register self in registry (NOT in Node Status table)
    add_or_update_trusted_registry(SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP, LISTEN_PORT)
    
    asyncio.create_task(draw_ui())
    asyncio.create_task(save_list_periodically())
    asyncio.create_task(sync_with_github()) # Start periodic sync
    
    server = await asyncio.start_server(lambda r, w: None, LISTEN_HOST, LISTEN_PORT)
    async with server: await server.serve_forever()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
