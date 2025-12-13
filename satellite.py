import asyncio
import ssl
import os
import datetime

PORT = 4001
repair_queue = []
notifications = []
connected_nodes = []
in_progress = set()

# Display table
def display_table():
    os.system('clear')
    print("=== Satellite Node Status ===")
    print("Node ID         Region     Rank  Uptime     Fragments")
    print("----------------------------------------------------------------------")
    for node in connected_nodes:
        print(f"{node['id']}      {node['region']}        {node['rank']}    {node['uptime']}        {','.join(node['fragments'])}")
    print("\n=== Repair Queue ===")
    if repair_queue:
        for i, frag in enumerate(repair_queue, 1):
            print(f"{i}. {frag}")
    else:
        print("No repair jobs queued.")
    print("======================================================================")
    print("\n=== Notifications (last 10) ===")
    for n in notifications[-10:]:
        print(n)
    print("======================================================================")

def add_notification(msg):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    notifications.append(f"{timestamp} - {msg}")
    display_table()

async def process_repair(frag):
    await asyncio.sleep(10)  # slow down repair
    add_notification(f"Processing repair for fragment {frag}")
    if frag in repair_queue:
        repair_queue.remove(frag)
    in_progress.remove(frag)
    display_table()

async def handle_node(reader, writer):
    addr = writer.get_extra_info('peername')
    add_notification(f"Node connected: {addr}")
    # Fake node metadata for demo
    node_info = {
        'id': f"node_{addr[1]}",
        'region': "EU",
        'rank': 85,
        'uptime': 0,
        'fragments': [f"frag{i}" for i in range(1,6)]
    }
    connected_nodes.append(node_info)
    display_table()

    try:
        while True:
            await asyncio.sleep(5)
            # increment uptime
            node_info['uptime'] += 5
            # enqueue repairs only if not already queued or in progress
            for frag in node_info['fragments']:
                if frag not in repair_queue and frag not in in_progress:
                    repair_queue.append(frag)
                    add_notification(f"Repair job queued for fragment {frag}")
                    in_progress.add(frag)
                    asyncio.create_task(process_repair(frag))
            display_table()
    except asyncio.CancelledError:
        pass
    finally:
        add_notification(f"Node disconnected: {addr}")
        connected_nodes.remove(node_info)
        display_table()

async def start_server():
    if not os.path.exists("cert.pem") or not os.path.exists("key.pem"):
        add_notification("TLS cert/key not found, generating self-signed certificate...")
        os.system("openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'")
        add_notification("Generated cert.pem and key.pem")
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
    server = await asyncio.start_server(handle_node, "0.0.0.0", PORT, ssl=ssl_context)
    add_notification(f"Satellite listening on port {PORT}")
    async with server:
        await server.serve_forever()

async def main():
    await start_server()

if __name__ == "__main__":
    asyncio.run(main())
