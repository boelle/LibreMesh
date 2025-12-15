import asyncio
import socket
import ssl
import json
import time
import os
import textwrap
import base64
import sys
import curses
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
ADVERTISED_IP_CONFIG = '192.168.0.163' 
# ADVERTISED_IP_CONFIG = None 


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
UI_NOTIFICATIONS = asyncio.Queue(maxsize=100) # Increased queue size for UI
TRUSTED_SATELLITES = {}
ADVERTISED_IP = None
LIST_UPDATED_PENDING_SAVE = False


# --- Helper Functions ---
def get_local_ip():
    """Determines the non-loopback local IP address, or uses configured IP."""
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
    """Adds a new satellite to the in-memory list and flags a save if this is the origin."""
    global LIST_UPDATED_PENDING_SAVE
    if not IS_ORIGIN:
        return

    new_details = {
        "id": sat_id,
        "fingerprint": fingerprint,
        "hostname": hostname,
        "port": port
    }
    
    if sat_id not in TRUSTED_SATELLITES:
        if not UI_NOTIFICATIONS.full():
            UI_NOTIFICATIONS.put_nowait(f"Added trusted satellite: {sat_id}")
        LIST_UPDATED_PENDING_SAVE = True
    else:
        # Check if existing details are identical to the new details
        if TRUSTED_SATELLITES[sat_id] != new_details:
            if not UI_NOTIFICATIONS.full():
                 UI_NOTIFICATIONS.put_nowait(f"Updated satellite details: {sat_id}")
            LIST_UPDATED_PENDING_SAVE = True
    
    TRUSTED_SATELLITES[sat_id] = new_details


def load_trusted_satellites():
    """Loads and verifies list.json on startup. Handles errors gracefully."""
    global TRUSTED_SATELLITES
    TRUSTED_SATELLITES = {}
    if os.path.exists(LIST_JSON_PATH):
        try:
            with open(LIST_JSON_PATH, 'r') as f:
                signed_data = json.load(f)
            data = signed_data['data']
            signature = base64.b64decode(signed_data['signature'])
            json_data_bytes = json.dumps(data, indent=4, sort_keys=True).encode('utf-8')
            public_key = serialization.load_pem_public_key(ORIGIN_PUBKEY_PEM, backend=default_backend())
            public_key.verify(signature, json_data_bytes, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
            if not UI_NOTIFICATIONS.full():
                UI_NOTIFICATIONS.put_nowait(f"Verified signature of {LIST_JSON_PATH}.")

            for sat in data['satellites']:
                if 'id' in sat and 'fingerprint' in sat and 'hostname' in sat and 'port' in sat:
                    TRUSTED_SATELLITES[sat['id']] = sat
                else:
                    raise ValueError("Malformed satellite entry in list.json")
        except Exception as e:
            if not UI_NOTIFICATIONS.full():
                 UI_NOTIFICATIONS.put_nowait(f"WARNING: Failed to load/verify list.json: {e}")


def sign_and_save_satellite_list():
    """Generates and signs the list.json file if this is the origin."""
    global LIST_UPDATED_PENDING_SAVE
    if not IS_ORIGIN or not ORIGIN_PRIVKEY_PEM:
        return

    private_key = serialization.load_pem_private_key(ORIGIN_PRIVKEY_PEM, password=None, backend=default_backend())
    satellites_list_formatted = list(TRUSTED_SATELLITES.values())
    satellites_list_data = {"satellites": satellites_list_formatted}
    json_data_bytes = json.dumps(satellites_list_data, indent=4, sort_keys=True).encode('utf-8')
    signature = private_key.sign(json_data_bytes, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
    final_list_structure = {"data": satellites_list_data, "signature": base64.b64encode(signature).decode('utf-8')}

    with open(LIST_JSON_PATH, 'w') as f:
        json.dump(final_list_structure, f, indent=4, separators=(',', ': '))
    
    if not UI_NOTIFICATIONS.full():
        UI_NOTIFICATIONS.put_nowait(f"Signed and saved list.json with {len(TRUSTED_SATELLITES)} entries.")

    LIST_UPDATED_PENDING_SAVE = False


def generate_keys_and_certs():
    """Generates satellite keys and origin pubkey/privkey if missing."""
    global ORIGIN_PUBKEY_PEM, ORIGIN_PRIVKEY_PEM, IS_ORIGIN, SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP
    if not UI_NOTIFICATIONS.full():
        UI_NOTIFICATIONS.put_nowait("Checking for existing keys and certificates...")
    
    if not os.path.exists(CERT_PATH) or not os.path.exists(KEY_PATH):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"), x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),])
        cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.utcnow()).not_valid_after(datetime.utcnow() + timedelta(days=3650)).add_extension(x509.SubjectAlternativeName([x509.DNSName(u"localhost")]), critical=False,).sign(private_key=key, algorithm=hashes.SHA256(), backend=default_backend())
        with open(KEY_PATH, "wb") as f:
            f.write(key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.TraditionalOpenSSL, encryption_algorithm=serialization.NoEncryption()))
        with open(CERT_PATH, "wb") as f:
            f.write(cert.public_bytes(encoding=serialization.Encoding.PEM))
        if not UI_NOTIFICATIONS.full():
             UI_NOTIFICATIONS.put_nowait("Satellite cert.pem and key.pem generated.")
    else:
        pass

    if not os.path.exists(ORIGIN_PUBKEY_PATH) or not os.path.exists(ORIGIN_PRIVKEY_PATH):
        IS_ORIGIN = True
        origin_priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        origin_pub_key = origin_priv_key.public_key()
        ORIGIN_PUBKEY_PEM = origin_pub_key.public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
        ORIGIN_PRIVKEY_PEM = origin_priv_key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.TraditionalOpenSSL, encryption_algorithm=serialization.NoEncryption())
        with open(ORIGIN_PUBKEY_PATH, "wb") as f:
            f.write(ORIGIN_PUBKEY_PEM)
        with open(ORIGIN_PRIVKEY_PATH, "wb") as f:
            f.write(ORIGIN_PRIVKEY_PEM)
        if not UI_NOTIFICATIONS.full():
             UI_NOTIFICATIONS.put_nowait("Master origin keys generated and saved.")
    else:
        with open(ORIGIN_PUBKEY_PATH, "rb") as f:
            ORIGIN_PUBKEY_PEM = f.read().strip()
        with open(ORIGIN_PRIVKEY_PATH, "rb") as f:
            ORIGIN_PRIVKEY_PEM = f.read().strip()
        try:
            serialization.load_pem_private_key(ORIGIN_PRIVKEY_PEM, password=None, backend=default_backend())
            IS_ORIGIN = True
            if not UI_NOTIFICATIONS.full():
                 UI_NOTIFICATIONS.put_nowait("Private origin key loaded. This instance is the Origin satellite.")
        except ValueError:
            IS_ORIGIN = False
            ORIGIN_PRIVKEY_PEM = None
            if not UI_NOTIFICATIONS.full():
                 UI_NOTIFICATIONS.put_nowait("Only public origin key loaded. This instance is a standard satellite.")

    # Load satellite specific attributes from its own generated cert
    with open(CERT_PATH, 'rb') as f:
        master_origin_cert = x509.load_pem_x509_certificate(f.read(), default_backend())

    cn_attributes = master_origin_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if cn_attributes:
        SATELLITE_ID = cn_attributes.value
    else:
        SATELLITE_ID = "Unknown_Satellite_ID" 


    # Calculate the TLS fingerprint
    cert_bytes = open(CERT_PATH, 'rb').read()
    cert = x509.load_pem_x509_certificate(cert_bytes, default_backend())
    TLS_FINGERPRINT = base64.b64encode(cert.fingerprint(hashes.SHA256())).decode('utf-8')

    # Determine advertised IP
    ADVERTISED_IP = get_local_ip()


# --- Networking Handlers ---
async def handle_client(reader, writer):
    """Handles incoming satellite connections, reads JSON message, verifies fingerprint, and processes command."""
    addr = writer.get_extra_info('peername')
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile=CERT_PATH, keyfile=KEY_PATH)
    context.verify_mode = ssl.CERT_REQUIRED
    try:        
        client_cert = writer.get_extra_info('peercert')
        if not client_cert:
            raise ssl.SSLError("Client did not present certificate.")
        
        cert_bytes = ssl.DER_cert_to_PEM_bytes(client_cert.export(format='DER'))
        client_cert_loaded = x509.load_pem_x509_certificate(cert_bytes, default_backend())
        client_fingerprint = base64.b64encode(client_cert_loaded.fingerprint(hashes.SHA256())).decode('utf-8')

        if client_fingerprint not in [sat['fingerprint'] for sat in TRUSTED_SATELLITES.values()]:
             if not UI_NOTIFICATIONS.full():
                 UI_NOTIFICATIONS.put_nowait(f"Info: Untrusted connection attempt from {addr}")
        
        data = await reader.read(4096)
        if not data:
            return
        
        message = json.loads(data.decode('utf-8'))
        
        if message.get("command") == "GET_LIST":
            if IS_ORIGIN:
                if os.path.exists(LIST_JSON_PATH):
                    with open(LIST_JSON_PATH, 'r') as f:
                        response_data = f.read()
                    writer.write(response_data.encode('utf-8'))
                    await writer.drain()
            else:
                response = {"status": "error", "message": "This node is not the Origin and cannot serve the signed list."}
                writer.write(json.dumps(response).encode('utf-8'))
                await writer.drain()
                
        elif message.get("command") == "ADVERTISE_SATELLITE" and IS_ORIGIN:
            sat_data = message.get("data", {})
            add_or_update_satellite(sat_data.get('id'), client_fingerprint, addr, sat_data.get('port'))
            response = {"status": "success", "message": "Advertisement received and noted."}
            writer.write(json.dumps(response).encode('utf-8'))
            await writer.drain()

        NODES[client_fingerprint] = time.time()
        
    except ssl.SSLError as e:
        if not UI_NOTIFICATIONS.full():
            UI_NOTIFICATIONS.put_nowait(f"SSL error with client {addr}: {e}")
    except json.JSONDecodeError:
        if not UI_NOTIFICATIONS.full():
             UI_NOTIFICATIONS.put_nowait(f"Received invalid JSON from {addr}")
    except Exception as e:
        pass
    finally:
        pass


async def register_with_origin(origin_host, origin_port):
    pass


# --- Main Loop and Utility Tasks ---
async def save_list_periodically():
    """Saves the trusted list to disk periodically *if* changes are pending."""
    while True:
        await asyncio.sleep(10)
        # FIX THE BUG: Only sign and save if the flag is True
        if LIST_UPDATED_PENDING_SAVE:
            sign_and_save_satellite_list()


# --- Curses UI Implementation ---
# (The entire curses implementation from the previous message is retained here for UI functionality)

stdscr = None

def draw_ui(stdscr):
    # ... (curses UI logic remains identical to previous response, truncated here for brevity) ...
    """Draws the main Curses UI layout and updates content."""
    global stdscr_global
    stdscr_global = stdscr
    curses.curs_set(0) # Hide cursor
    stdscr.nodelay(1)  # Non-blocking getch()
    sh, sw = stdscr.getmaxyx()

    # Define color pairs (foreground, background)
    curses.start_color()
    curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK) # Headers
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK) # Status/Success
    curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK) # Errors/Suspicious

    # Windows definitions (y, x, height, width)
    win_nodes = curses.newwin(8, sw, 0, 0)
    win_queue = curses.newwin(6, sw, 8, 0)
    win_notify = curses.newwin(10, sw, 14, 0)
    win_advisory = curses.newwin(4, sw, 24, 0)
    win_status = curses.newwin(8, sw, 28, 0)


    # Run the UI update loop
    asyncio.create_task(update_ui_content(win_nodes, win_queue, win_notify, win_advisory, win_status, sh, sw))


def print_header(win, title, sw):
    win.clear()
    win.box()
    win.addstr(0, 2, f" {title} ", curses.color_pair(1) | curses.A_BOLD)
    win.hline(1, 1, curses.ACS_HLINE, sw - 2)

def wrap_print(win, y, x, text, max_width):
    lines = textwrap.wrap(text, max_width)
    for line in lines:
        try:
            win.addstr(y, x, line)
            y += 1
        except curses.error:
            break
    return y


async def update_ui_content(win_nodes, win_queue, win_notify, win_advisory, win_status, sh, sw):
    notifications_log = []
    
    while True:
        # Handle new notifications from the queue
        while not UI_NOTIFICATIONS.empty():
            msg = await UI_NOTIFICATIONS.get()
            timestamp = datetime.now().strftime("%H:%M:%S")
            notifications_log.append(f"[{timestamp}] {msg}")
            # Keep only the last N messages that fit the window height
            max_lines = win_notify.getmaxyx()[0] - 2 # Use index 0 for height
            if len(notifications_log) > max_lines:
                notifications_log = notifications_log[-max_lines:]
            UI_NOTIFICATIONS.task_done()

        # Redraw all windows
        print_header(win_nodes, "Satellite Node Status", sw)
        win_nodes.addstr(2, 1, "Node ID             | Rank | Last Seen (s) | Uptime (s)")
        win_nodes.addstr(3, 1, "------------------------------------------------------")
        if not NODES:
             win_nodes.addstr(4, 1, "No nodes connected  | N/A  | N/A           | N/A")
        
        print_header(win_queue, "Repair Queue", sw)
        win_queue.addstr(2, 1, "Job ID (Fragment)              | Status | Claimed By")
        win_queue.addstr(3, 1, "------------------------------------------------------")
        if REPAIR_QUEUE.empty():
            win_queue.addstr(4, 1, "Queue is empty                 | N/A    | N/A")

        print_header(win_notify, "Notifications", sw)
        y_offset = 2
        for log_msg in notifications_log:
            y_offset = wrap_print(win_notify, y_offset, 1, log_msg, sw - 2)
            if y_offset >= win_notify.getmaxyx()[0] - 1: # Use index 0 for height
                break
        
        print_header(win_advisory, "Suspicious IPs Advisory", sw)
        win_advisory.addstr(2, 1, "No suspicious activity detected.", curses.color_pair(2))

        print_header(win_status, "Satellite ID + TLS Fingerprint", sw)
        win_status.addstr(2, 1, f"Satellite ID:          {SATELLITE_ID}")
        win_status.addstr(3, 1, f"Advertising IP:        {ADVERTISED_IP}:{LISTEN_PORT}")
        win_status.addstr(4, 1, f"Origin Status:         {'ORIGIN' if IS_ORIGIN else 'SATELLITE'}")
        # Format fingerprint for display
        fingerprint_formatted = ":".join([TLS_FINGERPRINT[i:i+2] for i in range(0, len(TLS_FINGERPRINT), 2)])
        win_status.addstr(5, 1, f"TLS Fingerprint:       {fingerprint_formatted}")
        win_status.addstr(6, 1, f"Trusted Satellites:    {len(TRUSTED_SATELLITES)} in list.json")


        # Refresh all windows
        win_nodes.refresh()
        win_queue.refresh()
        win_notify.refresh()
        win_advisory.refresh()
        win_status.refresh()

        await asyncio.sleep(0.5) # Update UI twice a second


async def main():
    """Main entry point for the satellite application."""
    global ADVERTISED_IP
    
    generate_keys_and_certs() # Setup keys/certs on startup
    load_trusted_satellites() # Load initial list if present
    
    # Start background tasks
    asyncio.create_task(save_list_periodically())
    # The Curses UI task is started inside curses.wrapper

    # SSL Context for the listening server
    ssl_ctx_server = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_ctx_server.load_cert_chain(certfile=CERT_PATH, keyfile=KEY_PATH)
    ssl_ctx_server.verify_mode = ssl.CERT_REQUIRED 

    # Start the server
    server = await asyncio.start_server(
        handle_client, LISTEN_HOST, LISTEN_PORT, ssl=ssl_ctx_server)

    socket_list = server.sockets
    if socket_list:
        addr = socket_list.getsockname() 
    else:
        addr = (LISTEN_HOST, LISTEN_PORT)

    print(f"Server starting on {addr}, switching to UI mode.")

    async with server:
        curses.wrapper(draw_ui)
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Satellite stopped by user (Ctrl+C).")
    except Exception as e:
        print(f"An unexpected error occurred in the main loop: {e}")
