import asyncio
import ssl

HOST = '127.0.0.1'
PORT = 4001
FRAGMENTS = ['frag1', 'frag2', 'frag3', 'frag4', 'frag5']

async def send_repair_request(writer, fragment):
    message = f"REPAIR {fragment}\n"
    writer.write(message.encode())
    await writer.drain()
    print(f"Repair request sent for {fragment}")

async def node_communication():
    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    reader, writer = await asyncio.open_connection(HOST, PORT, ssl=ssl_context)
    try:
        for frag in FRAGMENTS:
            await send_repair_request(writer, frag)
            await asyncio.sleep(1)  # short delay to see jobs in queue
        # Keep the connection alive for satellite to process
        while True:
            await asyncio.sleep(1)
    except Exception as e:
        print(f"Connection error: {e}")
    finally:
        writer.close()
        await writer.wait_closed()

async def main():
    await node_communication()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest node shutting down.")
