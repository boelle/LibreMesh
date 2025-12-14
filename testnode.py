import asyncio
import socket
import ssl
import json
import time
import os
import random
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from datetime import datetime, timedelta

# --- Configuration ---
SATELLITE_HOST = '127.0.0.1'
SATELLITE_PORT = 8888
NODE_ID = "testnode_A"
CERT_PATH = f'{NODE_ID}_cert.pem'
KEY_PATH = f'{NODE_ID}_key.pem'
ORIGIN_PUBKEY_PATH = 'origin_pubkey.pem' # Node needs access to this to verify list.json later

# --- Helper Functions ---
def generate_node_keys():
    """Generates node keys and cert if missing."""
    if not os.path.exists(CERT_PATH) or not os.path.exists(KEY_PATH):
        print(f"Generating new node cert for {NODE_ID}...")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
            x509.NameAttribute(NameOID.COMMON_NAME, NODE_ID),
        ])
        cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.utcnow()).not_valid_after(datetime.utcnow() + timedelta(days=3650)).sign(private_key=key, algorithm=hashes.SHA256(), backend=default_backend())

        with open(KEY_PATH, "wb") as f:
            f.write(key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.TraditionalOpenSSL, encryption_algorithm=serialization.NoEncryption()))
        with open(CERT_PATH, "wb") as f:
            f.write(cert.public_bytes(encoding=serialization.Encoding.PEM))
        print(f"Node certs generated for {NODE_ID}.")
    else:
        print(f"Reusing existing node certs for {NODE_ID}.")

async def send_message(writer, message):
    """Helper to send messages with signing later if needed."""
    writer.write(message.encode() + b'\n')
    await writer.drain()

async def node_client():
    generate_node_keys()

    # Client SSL Context (Trust the satellite's self-signed cert for testing)
    # In production, this would verify the chain of trust properly
    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=CERT_PATH) # Trust the satellite's own cert
    ssl_context.load_cert_chain(certfile=CERT_PATH, keyfile=KEY_PATH)

    while True:
        try:
            reader, writer = await asyncio.open_connection(
                SATELLITE_HOST, SATELLITE_PORT, ssl=ssl_context
            )
            print(f"Connected to satellite at {SATELLITE_HOST}:{SATELLITE_PORT}")

            # 1. Register with the Satellite
            registration_message = json.dumps({"node_id": NODE_ID})
            await send_message(writer, f"REGISTER {registration_message}")
            print(f"Sent REGISTER message.")

            # Start background task to listen for satellite messages
            listener_task = asyncio.create_task(listen_for_messages(reader))

            # 2. Start heartbeat loop
            while True:
                await asyncio.sleep(30)
                await send_message(writer, "HEARTBEAT")
                # print(f"Sent HEARTBEAT at {datetime.now().strftime('%H:%M:%S')}")
        
        except (ConnectionRefusedError, ssl.SSLError, OSError) as e:
            print(f"Connection failed: {e}. Retrying in 10 seconds...")
            if 'listener_task' in locals() and not listener_task.done():
                listener_task.cancel()
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            print("Node connection loop cancelled.")
            break
        except Exception as e:
            print(f"An unexpected error occurred in main loop: {e}")
            break

async def listen_for_messages(reader):
    """Listens for messages coming back from the satellite."""
    try:
        while True:
            data = await reader.readline()
            if not data:
                break
            message = data.decode().strip()
            if message:
                print(f"[RX from Satellite]: {message}")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error while listening to satellite: {e}")
    finally:
        print("Satellite listener stopped.")


if __name__ == '__main__':
    try:
        asyncio.run(node_client())
    except KeyboardInterrupt:
        print("Node shutting down.")
