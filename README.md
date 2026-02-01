# 🌐 LibreMesh

### *Distributed Storage for Fun & Bragging Rights*

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)]()

> **Community-driven distributed storage with leaderboards and bragging rights.** Run a node, compete for reputation, learn distributed systems. No tokens, no crypto, just pure hobby-grade resilient storage.

**LibreMesh** is a decentralized, open-source storage network built for hobbyists and enthusiasts. Erasure-coded fragments distributed across volunteer nodes, with automatic repair orchestration, real-time scoring, and competitive leaderboards. Zero financial incentives, maximum fun.

---

## 📊 At a Glance

| Feature | Status | Details |
|---------|--------|---------|
| **Architecture** | ✅ Implemented | Satellite mesh with origin authority, persistent connections |
| **Erasure Coding** | ✅ Operational | Reed-Solomon k=6, n=10 (survive 4 simultaneous node failures) |
| **Fragment Storage** | ✅ Operational | JSON-RPC put/get/list on all satellites and storage nodes |
| **Repair System** | ✅ Operational | SQLite queue, atomic claiming, distributed reconstruction |
| **Encryption** | ✅ Operational | Client-side AES-GCM before fragmentation (keys never leave client) |
| **Reputation Scoring** | ✅ Operational | 6-factor composite (uptime, reachability, repairs, health, latency, P2P) |
| **Proof-of-Storage** | ✅ Operational | Nonce-based challenges, distributed auditing every 120s |
| **Leaderboard** | ✅ Operational | Terminal UI, color-coded tiers (★ Excellent, ● Good, ○ Deprioritized) |
| **Geographic Diversity** | ✅ Operational | 12 zones, min 3-zone spread, 50% per-zone cap |
| **Network Monitoring** | ✅ Live | Real-time CPU/mem/latency, repair queue, node health, P2P connectivity |
| **Security** | ✅ Hardened | TLS fingerprints, signed registry, SHA-256 attestation |
| **Network Size** | 🔧 Alpha | 2-3 test nodes, targeting 10-20 by Q1 2026 |

---

## 🎯 Why LibreMesh?

> *"Professional-grade distributed storage, hobby-grade participation model."*

**The problem:** Want to run distributed storage infrastructure for learning and fun? Your options are either cryptocurrency-based (complex, speculative) or purely technical (no community, no competition). Nothing exists for hobbyists who just want to run cool infrastructure.

**The solution:** LibreMesh provides production-quality erasure-coded storage with a participation model built around competition, reputation, and learning. Run nodes because it's interesting, compete for leaderboard positions, master distributed systems through hands-on operation.

### For Storage Node Operators
- 🏆 **Leaderboards**: Compete for top uptime, repair contributions, and response times
- 📊 **Public Stats**: Show off your node's reliability and earned reputation
- 🛠️ **Learn by Doing**: Hands-on experience with distributed systems on real hardware
- 🤝 **Community**: Join a network of hobbyists building something cool together
- 💾 **Raspberry Pi Friendly**: Designed to run on Pi 5 with USB storage

**For the Network:**
- 🔒 **Client-side encryption**: Your data, your keys, complete privacy
- 🔄 **Reed-Solomon erasure coding**: Survive multiple node failures (k-of-n recovery)
- 🚀 **Automatic repair**: Network self-heals when fragments go missing
- 📡 **Real-time monitoring**: Live CPU/memory stats, repair queue, node health
- 🌍 **Decentralized storage**: Data spread across volunteer satellites/storage nodes; single origin authority for coordination (operator-managed trust anchor)

**What This Is NOT:**
- ❌ Not a cryptocurrency or blockchain project
- ❌ Not commercial cloud storage (no SLAs, no guarantees)
- ❌ Not a get-rich-quick scheme (zero financial incentives)

**What This IS:**
- ✅ A fun hobby project for server enthusiasts with long-term commitment
- ✅ A learning platform for distributed systems (hands-on education)
- ✅ A community experiment in voluntary cooperation and competitive participation
- ✅ A production-grade reference implementation of erasure coding and repair orchestration

---

## 🎯 Project Goals

**Short-term (2025-Q1):**
- ✅ Finish core repair orchestration
- ✅ Complete storagenode lifecycle
- ✅ Ship tests and documentation
- 🎉 **Launch alpha network** (3-5 nodes)

**Mid-term (2025-Q2/Q3):**
- 📈 Grow to 10-20 active nodes
- 🎮 Launch public leaderboard
- 🌍 Add geographic diversity tracking

**Long-term (2025-Q4+):**
- 🚀 Scale to 50-100 nodes
- 🏆 Establish competitive teams
- 📊 Web dashboard for stats/monitoring
- 🎓 Educational content (workshops, talks)
- 📚 Write deployment guides (Pi SD images, Docker)
- 🤝 Community governance model

**Non-Goals:**
- ❌ Cryptocurrency or tokens
- ❌ Commercial cloud service
- ❌ Enterprise SLAs or guarantees
- ❌ Profit motive

---

## Key Concepts

### Storage Node
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

## 🏗️ Architecture

LibreMesh uses a **satellite mesh network** with persistent control connections and distributed repair orchestration:

```
                    ┌──────────────────────────────────────┐
                    │        Origin Satellite              │
                    │  • Trusted node registry (signed)    │
                    │  • Repair job queue (SQLite)         │
                    │  • Fragment health monitoring        │
                    └───────┬──────────────────┬───────────┘
                            │  Persistent      │
                            │  bidirectional   │
                            │  control sync    │
                            │  (TLS encrypted) │
         ┌──────────────────┴─────┐    ┌──────┴──────────────────┐
         │                        │    │                         │
    ┌────▼────────┐          ┌────▼────▼───┐          ┌─────────▼────┐
    │  Satellite  │◄─ Sync ─►│  Satellite  │◄─ Sync ─►│  Satellite   │
    │   Node 1    │          │   Node 2    │          │   Node 3     │
    │             │          │             │          │              │
    │  • Repair   │          │  • Repair   │          │  • Repair    │
    │  • Metrics  │          │  • Metrics  │          │  • Metrics   │
    └─────┬───────┘          └──────┬──────┘          └──────┬───────┘
          │                         │                        │
          │ Fragment Storage RPC    │ Fragment Storage RPC   │ Fragment Storage RPC
          │ (TLS encrypted)         │ (TLS encrypted)        │ (TLS encrypted)
          │                         │                        │
    ┌─────▼─────────────────────────▼────────────────────────▼──────┐
    │                Storage Nodes (Pure Storage)                    │
    │  • Lightweight - no control port, minimal interface            │
    │  • Reports metrics via heartbeat to Origin                     │
    │  • P2P connectivity testing between peers                      │
    └────────────────────────────────────────────────────────────────┘
          │                         │                        │
    ┌─────▼─────┐             ┌─────▼─────┐          ┌─────▼─────┐
    │  Storage  │             │  Storage  │          │  Storage  │
    │  Node 1   │             │  Node 2   │          │  Node 3   │
    │           │             │           │          │           │
    │ Fragments │             │ Fragments │          │ Fragments │
    │  + Parity │             │  + Parity │          │  + Parity │
    └───────────┘             └───────────┘          └───────────┘

                    Reed-Solomon k=6, n=10 Erasure Coding
                    (Survive up to 4 simultaneous node failures)
```

**Key Components:**

### 🛰️ Origin Satellite (Control Plane Authority)
- **Registry management**: Signs and distributes trusted satellite list
- **Repair orchestration**: SQLite job queue with atomic claiming and leases
- **Health monitoring**: Periodic fragment scans, creates repair jobs
- **Real-time sync**: Maintains persistent connections to all satellites
- **Metrics hub**: Distributes system-wide repair stats to all nodes

### 📡 Satellite Nodes
- **Repair worker**: Claims jobs and reconstructs missing fragments using Reed-Solomon; handles repair overflow when dedicated repair nodes are unavailable or overloaded
- **Status sync**: Sends heartbeat (when unchanged) or full sync every 30s with TLS encryption
- **Metrics reporting**: CPU%, memory%, fragment count, repair contributions
- **Auto-reconnect**: Exponential backoff to origin if connection drops

### 🔧 Repair System
- **Job lifecycle**: pending → claimed (5min lease) → completed/failed
- **Atomic claiming**: SQLite prevents duplicate claims
- **Lease expiry**: Origin reclaims stale jobs automatically
- **Reconstruction**: Fetch k surviving fragments, decode, store to target node
- **Statistics tracking**: Jobs created/completed/failed visible on all nodes

### 🔐 Security Model
- **Client-side encryption**: AES-GCM before fragmentation (keys never leave client)
- **Transport layer encryption**: All connections between nodes use TLS; network traffic is encrypted and cannot be eavesdropped 
- **Pre-flight encryption**: Feeders encrypt data before sending to satellites (double encryption: application + transport)
- **TLS fingerprints**: Node identity verified via certificate SHA-256 attestation
- **Signed registry**: Origin signs satellite list with RSA-4096
- **GitHub trust anchor**: Origin public key distributed via GitHub
- **No authentication required**: Fragments are read-only and encrypted; integrity verified via checksums only

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.11+**
- **Hardware**: Raspberry Pi 5 recommended (4GB+ RAM)
- **Storage**: 2TB+ USB3 HDD for satellite nodes
- **Network**: Static IP or DDNS recommended

### Setup & Installation

```bash
# Download the essential files
wget https://raw.githubusercontent.com/boelle/LibreMesh/refs/heads/main/satellite.py
wget https://raw.githubusercontent.com/boelle/LibreMesh/refs/heads/main/requirements.txt
wget https://raw.githubusercontent.com/boelle/LibreMesh/refs/heads/main/satellite_config.json

# Install dependencies
apt-get install -y python3-cryptography python3-zfec python3-psutil python3-requests python3-geoip2 smartmontools mergerfs libfuse3

**Dependencies** (5 packages):
- `cryptography` (❗ required): TLS certificates, fingerprints, RSA, AES-GCM encryption  
- `zfec` (❗ required): Reed-Solomon erasure coding (needs C toolchain: gcc/clang)
- `psutil` (optional): CPU/memory metrics (shows N/A if missing)
- `geoip2` (optional): Geographic zone detection (requires MaxMind account)
- `requests` (optional): HTTP client for GitHub registry fetching

### Run a Satellite Node (Join Network)

```bash
# Same setup as above, but use satellite config
cp satellite_config.json config.json

# Edit config.json
nano config.json
# - Set advertised_ip to your IP
# - Set network.origin_host to origin's IP
# Run satellite
python3 satellite.py
```

**Satellite provides:**
- Control port: 8888 (sync with origin)
- Storage port: 9889 (fragment storage)
- Repair worker (claims jobs from origin)

### What You'll See

**Terminal UIs by Role:**

<details>
<summary><b>Satellite Node UI</b> (click to expand)</summary>

```
==============================================================================
                            LibreMesh Home
==============================================================================

Satellite ID:       LibreMesh-Sat-01
Advertising IP:     192.168.0.163:8888
Node Role:          SATELLITE
TLS Fingerprint:    SHA256:a3b4c5d6e7f8...
Registry Source:    LIVE (updated 12s ago)

Trusted Satellites:     3
Trusted Repair Nodes:   2

Storage Nodes:          8

Satellites:             3/3 online
Repair Nodes:           2/2 online

Repair Queue:           0 jobs
Deletion Queue:         0 jobs

CPU: 5.2%  |  Memory: 248.5 MB (41.2%)  |  Uptime: 2d 4h 23m

==============================================================================
Navigation: [H]ome | [S]atellites | [N]odes | [R]epair | [L]ogs | [Q]uit
==============================================================================
```
*Interactive curses UI with keyboard navigation between screens.*

</details>

<details>
<summary><b>Storage Node UI</b> (click to expand)</summary>

```
==============================================================================
                          Storage Node Home
==============================================================================

Node ID:            LibreMesh-Storage-03
Zone:               US-West-A
Storage Port:       9889
Storage Path:       /mnt/usb/fragments
TLS Fingerprint:    SHA256:b2c3d4e5f6...

Connection Status:  CONNECTED (last heartbeat: 8s ago)
Origin Server:      192.168.0.163:8888

Storage Capacity:   127.34 / 1800.00 GB (7.07%)
Fragment Count:     14,523 fragments
Disk Health:        HEALTHY (1.00)

Performance Metrics:
  Uptime:           5d 12h 34m
  Reputation Score: 0.87 (★ Excellent)
  Response Latency: 42ms avg
  Repairs Completed: 23
  Audits Passed:    1,234 / 1,234 (100%)

CPU: 2.1%  |  Memory: 89.2 MB (14.3%)

==============================================================================
Navigation: [H]ome | [V]iewerboard | [L]ogs | [Q]uit
==============================================================================
```
*Lightweight UI showing storage metrics and performance.*

</details>

<details>
<summary><b>Repair Node UI</b> (click to expand)</summary>

```
==============================================================================
                            LibreMesh Home
==============================================================================

Satellite ID:       LibreMesh-Repair-01
Advertising IP:     192.168.0.164:8888
Node Role:          REPAIR_NODE
TLS Fingerprint:    SHA256:c4d5e6f7g8...
Registry Source:    LIVE (updated 5s ago)

Trusted Satellites:     3
Trusted Repair Nodes:   2

Storage Nodes:          8

Satellites:             3/3 online
Repair Nodes:           2/2 online

Repair Queue:           3 jobs (2 claimed by this node)
Deletion Queue:         0 jobs

Repair Performance:
  Jobs Completed:       156 (today: 8)
  Success Rate:         98.7%
  Avg Reconstruct Time: 4.2s

CPU: 8.3%  |  Memory: 156.8 MB (26.1%)  |  Uptime: 1d 18h 45m

==============================================================================
Navigation: [H]ome | [R]epair | [L]ogs | [Q]uit
==============================================================================
```
*Focused on repair job claiming and reconstruction metrics.*

</details>

<details>
<summary><b>Feeder UI</b> (click to expand)</summary>

```
==============================================================================
                        Feeder Upload Guard
==============================================================================
Status: OPERATIONAL - uploads allowed
Unprotected usage: 234.5MB / 5120.0MB
Grace remaining before auto-pause: 3600s

Storage Nodes Online: 8/8
Average Response Latency: 38ms
Last Upload: file_abc123.dat (2.4MB) - SUCCESS (12s ago)
Fragments Placed: 10/10 (k=6, n=10)
  Zone Distribution: US-West: 3, EU-Central: 4, Asia-Pacific: 3

Recent Activity:
  [14:23:45] Uploaded: report.pdf (1.2MB) → 10 fragments
  [14:18:32] Uploaded: image.jpg (450KB) → 10 fragments
  [14:12:01] Retrieved: backup.tar.gz (8.3MB)

==============================================================================
Commands: [U]pload | [D]ownload | [L]ist files | [Q]uit
==============================================================================
```
*Simplified UI for file operations and upload status.*

</details>

---

## 🛠️ Configuration

Configs are self-documented in the templates. Start from these and edit your node details (name, advertised_ip, origin_host/port, storage_port): [origin_config.json](origin_config.json), [satellite_config.json](satellite_config.json), [hybrid_config.json](hybrid_config.json).

Auto-detect behavior: On startup, nodes now prefer the live origin registry (via repair RPC on 7888) to choose the next ID and port, falling back to local/GitHub seed only if the origin is unreachable. This prevents ID collisions when spinning up multiple nodes quickly.

---

## 📜 License

LibreMesh is licensed under **GNU AGPLv3**.

**What this means:**
- ✅ Free to use, modify, and distribute
- ✅ Must keep source open (even for network services)
- ✅ Must share modifications under same license
- ❌ Cannot make proprietary forks
- ❌ No warranty (use at own risk)

**Why AGPL?**
- Ensures the project stays open and community-driven
- Prevents commercial cloud providers from taking without contributing back
- Aligns with Folding@home / BOINC philosophy (community-first)

Full license: [LICENSE](LICENSE)

---

## 🤝 Contributing

LibreMesh is in **active development** (alpha stage). Contributions welcome!

**Priority Areas:**
- 🧪 **Testing**: Unit tests, integration tests, stress tests
- 📊 **Metrics**: Better auditing and scoring algorithms  
- 🎨 **UI/UX**: Improve terminal dashboard, add web interface option
- 📚 **Documentation**: Setup guides, troubleshooting, architecture deep-dives
- 🔧 **Optimizations**: Performance profiling, bottleneck fixes
- 🌍 **Deployment**: Docker images, systemd units, Pi SD card images

**Development Process:**
1. Check `todo.txt` for current task priorities
2. Open an issue to discuss major changes
3. Follow existing code style (4-space indent, docstrings)
4. Test on actual hardware (Raspberry Pi preferred)
5. Submit PR with clear description

**Communication:**
- GitHub Issues for bugs and features
- Discussions for architecture questions
- (Future: Discord/Matrix for community chat)

---

## 🙏 Technology & Credits

**Core Technologies:**
- **Python 3.11+** with asyncio for concurrent persistent connections
- **SQLite3** for atomic repair job orchestration
- **Reed-Solomon erasure coding** (zfec) for k-of-n fragment recovery
- **TLS + AES-GCM** (cryptography library) for transport and data encryption
- **psutil** for real-time resource monitoring

**Design Principles:**
- **Client-side encryption**: Least-authority design, keys never leave client
- **Decentralized coordination**: No single point of failure (satellite mesh)
- **Voluntary participation**: Community-driven, zero financial incentives
- **Competitive gamification**: Leaderboards and reputation scoring
- **Raspberry Pi scale**: Designed for affordable hobby hardware

**Special Thanks:**
- Open source community for foundational libraries
- Distributed systems research community
- Early contributors and testers

---

## 📞 Contact & Community

**Current Status**: Solo development, seeking early contributors

**Ways to get involved:**
- ⭐ **Star this repo** if you find it interesting
- 🐛 **Report bugs** via GitHub Issues
- 💡 **Suggest features** in Discussions
- 🔧 **Submit PRs** for fixes and improvements
- 🚀 **Run a node** and help test the network

**Project Maintainer**: @boelle (GitHub)

---

## ❓ FAQ

**Q: Is this production-ready?**  
A: No, alpha stage. Don't store irreplaceable data yet.

**Q: How do I earn money running a node?**  
A: You don't. This is for fun, learning, and bragging rights.

**Q: What hardware do I need?**  
A: Raspberry Pi 5 (4GB+) with USB3 HDD (2TB+) is ideal. X86 servers work too.

**Q: What if nodes go offline?**  
A: Automatic repair kicks in. With k=6, n=10, you can lose 4 nodes and still recover data.

**Q: How is data encrypted?**  
A: Client-side AES-GCM before fragmentation. Keys never leave the client.

**Q: Can I trust other nodes?**  
A: Doesn't matter - they only see encrypted fragments. Integrity is checked via checksums.

**Q: How do I climb the leaderboard?**  
A: Keep your node online, complete repairs, respond quickly to challenges.

**Q: Is there a GUI?**  
A: Minimal terminal UI with live leaderboard, repair stats, and node health. Web dashboard planned later.

**Q: Can I run multiple roles on one Pi?**  
A: Yes! Use hybrid mode: `"roles": ["satellite", "storagenode", "repairnode"]`

**Q: What's the minimum network size?**  
A: Recommend 4+ nodes minimum for production (1 origin + 3 satellites/storage nodes). For testing: k=2, n=3 (2 data, 1 parity) on 3-4 local nodes.

**Q: What about spam and abuse?**  
A: LibreMesh uses behavioral pattern recognition to throttle (not block) suspicious activity. We monitor for automated abuse patterns like repetitive operations, rapid churn, and robotic timing. Normal human usage won't trigger it. Throttling is transparent—all RPC responses include your spam score (0-10) and explanation. First offense resets after 24h; repeat patterns escalate. The system is designed to bore attackers, not frustrate legitimate users.

**Q: What if I'm throttled by mistake?**  
A: All RPC responses show your spam score and why you're throttled. Normal usage won't trigger it. If legitimate high-volume activity (backups, batch jobs) gets flagged, contact the network operator for whitelisting (Discord: https://discord.gg/SuyB5zkXdN). Throttling resets automatically after 24h of clean activity.

---

<p align="center">
  <b>Built with ❤️ by hobbyists, for hobbyists</b><br>
  <i>No tokens. No hype. Just resilient distributed storage.</i>
</p>

<p align="center">
  <a href="https://github.com/boelle/LibreMesh/stargazers">⭐ Star</a> •
  <a href="https://github.com/boelle/LibreMesh/issues">🐛 Issues</a> •
  <a href="https://github.com/boelle/LibreMesh/discussions">💬 Discuss</a> •
  <a href="https://discord.gg/SuyB5zkXdN">💬 Discord</a>
</p>
