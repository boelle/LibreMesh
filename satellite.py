import asyncio
import ssl
import os
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

CERTFILE = 'cert.pem'
KEYFILE = 'key.pem'
HANDSHAKE_TIMEOUT = 10
HEARTBEAT_INTERVAL = 30

class Satellite:
    def __init__(self):
        self.nodes = {}
        self.repair_queue = []
        self.notifications = []
        self.suspicious_ips = {}
        self.fingerprint = self.ensure_keys()

    def ensure_keys(self):
        if not os.path.exists(KEYFILE) or not os.path.exists(CERTFILE):
            # Auto-generate self-signed certificate
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.x509 import NameOID, CertificateBuilder
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives import serialization
            import datetime

            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"NA"),
                x509.NameAttribute(NameOID.LOCALITY_NAME, u"NA"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Satellite"),
                x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
            ])
            cert = CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.datetime.utcnow()).not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365)).sign(key, hashes.SHA256())

            with open(CERTFILE, 'wb') as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
            with open(KEYFILE, 'wb') as f:
                f.write(key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()
                ))
        return 'FAKE-FINGERPRINT-1234'  # placeholder for TLS fingerprint

    async def handle_client(self, reader, writer):
        peer = writer.get_extra_info('peername')[0]
        self.suspicious_ips.setdefault(peer, {'connections':0, 'penalty':0, 'last_seen':0})
        self.suspicious_ips[peer]['connections'] += 1

        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=HANDSHAKE_TIMEOUT)
                if not line:
                    break
                data = line.decode().strip()
                if data.startswith('HEARTBEAT'):
                    parts = data.split(':')
                    node_id, region, uptime = parts[1], parts[2], int(parts[3])
                    self.nodes[node_id] = {'region': region, 'uptime': uptime, 'last_seen':0, 'fragments': []}
                elif data.startswith('REPAIR'):  # simplified format: REPAIR:fragX:nodeID
                    _, frag, node_id = data.split(':')
                    self.repair_queue.append({'fragment': frag, 'requested_by': node_id, 'claimed_by': None})
                    self.notifications.append(f'[{datetime.now().strftime("%H:%M:%S")}] Repair requested: {frag} by {node_id}')
            except asyncio.TimeoutError:
                break
        writer.close()
        await writer.wait_closed()

    async def ui_loop(self):
        while True:
            os.system('clear')
            # Node Status Table
            print('+-------------------------------------------------------------+')
            print('|                     Satellite Node Status                  |')
            print('+------------+----------+------+----------+-----------------+')
            print('| Node ID    | Region   | Rank | Uptime   | Fragments       |')
            print('+------------+----------+------+----------+-----------------+')
            for nid, info in self.nodes.items():
                print(f'| {nid:<10} | {info["region"]:<8} | 100  | {info["uptime"]:<8} | {" ":<15} |')
            print('+-------------------------------------------------------------+')

            # Repair Queue Table
            print('\n+-------------------------------------------+')
            print('|                Repair Queue               |')
            print('+------------+----------------+------------+')
            print('| Fragment   | Requested By   | Claimed By |')
            print('+------------+----------------+------------+')
            for job in self.repair_queue:
                print(f'| {job["fragment"]:<10} | {job["requested_by"]:<14} | {job["claimed_by"] or "":<10} |')
            print('+-------------------------------------------+')

            # Notifications
            print('\n+------------------------------------------------+')
            print('|                  Notifications                |')
            print('+------------------------------------------------+')
            for note in self.notifications[-10:]:
                print(f'| {note:<46} |')
            print('+------------------------------------------------+')

            # Suspicious IPs
            print('\n+-----------------------------------------------+')
            print('|               Suspicious IPs Advisory        |')
            print('+------------+------------+---------+----------+')
            print('| IP         | Connections| Penalty | Last Seen|')
            print('+------------+------------+---------+----------+')
            for ip, info in self.suspicious_ips.items():
                print(f'| {ip:<10} | {info["connections"]:<10} | {info["penalty"]:<7} | {info["last_seen"]:<8} |')
            print('+-----------------------------------------------+')

            print(f'\nSatellite ID: 1234')
            print(f'TLS Fingerprint: {self.fingerprint}')

            await asyncio.sleep(2)

    async def start_server(self):
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(CERTFILE, KEYFILE)
        server = await asyncio.start_server(self.handle_client, '0.0.0.0', 4001, ssl=ssl_ctx)
        await asyncio.gather(server.serve_forever(), self.ui_loop())


def main():
    sat = Satellite()
    asyncio.run(sat.start_server())


if __name__ == '__main__':
    main()
