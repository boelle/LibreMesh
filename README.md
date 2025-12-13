# LibreMesh

**LibreMesh** is a decentralized, open-source, free storage network. It allows anyone to contribute storage space or store encrypted data across a distributed network of nodes, satellites, and repair nodes. Participation is voluntary and non-commercial — the network exists for the fun of building a resilient, community-driven storage system.

---

## Key Concepts

### Node
- Single physical storage device.
- Stores encrypted fragments.
- Reports metrics to satellites.
- Rank based on uptime, online time, SMART health, repair history, and latency.
- Runs headless; can be attached for operator control.

### Satellite
- Coordinates fragment placement and repairs.
- Maintains metadata map: files → fragments → nodes.
- Syncs with other satellites to prevent split-brain.
- Assigns repair jobs and verifies fragment integrity.

### Repair Node
- Reconstructs missing/damaged fragments using available data + parity.
- Minimal persistent storage; temporary fragments only.

### Feeder / Customer
- Encrypts files before storage.
- Only feeder knows content.
- Data is encrypted in transit and at rest.

---

## Features

- Decentralized & open-source
- Encrypted storage
- Dynamic redundancy with parity
- Repair system for data integrity
- Automatic discovery
- Headless operation with optional attachment
- Minimal logging for efficiency and privacy

---

## Architecture


