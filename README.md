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
| **Architecture** | ✅ Implemented | Satellite mesh with persistent connections |
| **Erasure Coding** | ✅ Ready | Reed-Solomon k=6, n=10 (survive 4 node failures) |
| **Repair System** | ✅ Operational | SQLite queue, atomic claiming, auto-reconstruction |
| **Encryption** | ✅ Ready | Client-side AES-GCM (keys never leave client) |
| **Monitoring** | ✅ Live | Real-time CPU/mem, repair stats, node health |
| **Scoring** | 🚧 In Progress | Task 8-11 (auditor, reputation, leaderboard) |
| **Geo-Diversity** | 📋 Planned | Task 13 (12 zones, placement rules) |
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
- 🌍 **Truly decentralized**: No central authority, community-run

**What This Is NOT:**
- ❌ Not a cryptocurrency or blockchain project
- ❌ Not commercial cloud storage (no SLAs, no guarantees)
- ❌ Not a get-rich-quick scheme (zero financial incentives)

**What This IS:**
- ✅ A fun hobby project for server enthusiasts
- ✅ A learning platform for distributed systems
- ✅ A community experiment in voluntary cooperation
- ✅ A testbed for erasure coding and repair algorithms

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
         ┌──────────────────┴─────┐    ┌──────┴──────────────────┐
         │                        │    │                         │
    ┌────▼────────┐          ┌────▼────▼───┐          ┌─────────▼────┐
    │  Satellite  │◄─ Sync ─►│  Satellite  │◄─ Sync ─►│  Satellite   │
    │   Node 1    │          │   Node 2    │          │   Node 3     │
    │             │          │             │          │              │
    │  • Storage  │          │  • Storage  │          │  • Storage   │
    │  • Repair   │          │  • Repair   │          │  • Repair    │
    │  • Metrics  │          │  • Metrics  │          │  • Metrics   │
    └─────┬───────┘          └──────┬──────┘          └──────┬───────┘
          │                         │                        │
          │ Storage RPC             │ Storage RPC            │ Storage RPC
          │ (Port 9889)             │ (Port 9889)            │ (Port 9889)
          │                         │                        │
    ┌─────▼─────────────────────────▼────────────────────────▼──────┐
    │                Storage Nodes (Pure Storage)                    │
    │  • Lightweight - no control port, no UI                        │
    │  • Reports metrics via heartbeat to Origin                     │
    │  • P2P connectivity testing (Task 24)                          │
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

### 📡 Satellite Nodes (Storage + Repair)
- **Fragment storage**: Serves put/get/list RPCs on storage port (9889)
- **Repair worker**: Claims jobs, reconstructs missing fragments using Reed-Solomon
- **Status sync**: Sends heartbeat (when unchanged) or full sync every 30s
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
- **TLS fingerprints**: Node identity from cert SHA-256
- **Signed registry**: Origin signs satellite list with RSA-4096
- **GitHub trust anchor**: Origin public key distributed via GitHub
- **No authentication**: Read-only fragments (integrity via checksums, privacy via encryption)

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.11+**
- **Hardware**: Raspberry Pi 5 recommended (4GB+ RAM)
- **Storage**: 2TB+ USB3 HDD for satellite nodes
- **Network**: Static IP or DDNS recommended

### Option 1: Run Origin Satellite (Network Bootstrap)

```bash
# Clone the repo
git clone https://github.com/yourusername/LibreMesh.git
cd LibreMesh

# Install dependencies
pip install -r requirements.txt

### Dependency rationale
- `cryptography` (required): TLS certs, fingerprints, RSA, AES-GCM. Do **not** remove or replace—security-critical and constant-time implementations.
- `zfec` (preferred): Fast erasure coding, but needs a C toolchain to install. If you’re on a minimal system, install build-essential/clang first. We’re skipping the pure-Python fallback for now to keep performance high.
- `psutil` (optional): CPU/memory metrics. If missing, metrics simply show N/A (no breakage).
- `typing_extensions` (removed): Python 3.8+ ships `TypedDict` in stdlib; no backport needed.

# Copy origin config template
cp origin_config.json config.json

# Edit config.json (set your IP address)
nano config.json  # Change advertised_ip to your public/local IP

# Run origin
python satellite.py
```

**Origin provides:**
- Control port: 8888 (satellite sync)
- Repair RPC: 7888 (job coordination)
- No storage port (origin is control-only)

### Option 2: Run Satellite Node (Join Network)

```bash
# Same setup as above, but use satellite config
cp satellite_config.json config.json

# Edit config.json
nano config.json
# - Set advertised_ip to your IP
# - Set network.origin_host to origin's IP
# - Set network.origin_port to 8888

# Run satellite
python satellite.py
```

**Satellite provides:**
- Control port: 8888 (sync with origin)
- Storage port: 9889 (fragment storage)
- Repair worker (claims jobs from origin)

### What You'll See

**Terminal UI (refreshes every 1 second):**
```
╔══════════════════════════════════════════════════════════════════════════════╗
║ LibreMesh Satellite (Control Plane) - Version 2025.12.21                    ║
║══════════════════════════════════════════════════════════════════════════════║
║ Node Identity                                                                ║
║ - ID: 4a3f7e8c9d...                                                          ║
║ - Mode: satellite (roles: satellite, storagenode, repairnode)               ║
║ - Advertised: 192.168.0.163:8888                                            ║
║ - Fingerprint: SHA256:a3b4c5d6...                                           ║
║══════════════════════════════════════════════════════════════════════════════║
║ Online Satellites (2)                                                        ║
║ ID                  Hostname         Direct  CPU%   Mem%   Last Seen        ║
║ LibreMesh-Sat-01    192.168.0.163    N/A     2.6    33.8   (this node)     ║
║ LibreMesh-Sat-02    192.168.0.164    Yes     11.4   34.2   3s ago          ║
║══════════════════════════════════════════════════════════════════════════════║
║ Repair Statistics (System-Wide)                                             ║
║ - Jobs Created: 0                                                            ║
║ - Jobs Completed: 0                                                          ║
║ - Jobs Failed: 0                                                             ║
║ - Fragments Checked: 0                                                       ║
║ - Last Health Check: Never                                                   ║
║══════════════════════════════════════════════════════════════════════════════║
║ Notifications (last 9)                                                       ║
║ [12:34:56] Connected to origin                                               ║
║ [12:34:55] Connecting to origin 192.168.0.163:8888...                       ║
║ [12:34:50] Satellite initialized (mode: satellite)                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## 🎮 Current Features (Alpha)

**✅ Implemented:**
- [x] **Satellite mesh network** with origin authority
- [x] **Persistent bidirectional connections** (real-time metrics, command potential)
- [x] **Repair job orchestration** with SQLite queue and atomic claiming
- [x] **Fragment health monitoring** (placeholder, needs actual object scanning)
- [x] **Repair worker** (claims jobs, placeholder reconstruction logic)
- [x] **Reed-Solomon encoding/decoding** (zfec-based, k=6 n=10)
- [x] **Storage RPC** (put/get/list fragments via JSON-RPC)
- [x] **Client-side encryption** (AES-GCM helpers ready)
- [x] **Status sync efficiency** (heartbeat mode, ETag caching)
- [x] **CPU/Memory monitoring** (psutil integration, live UI display)
- [x] **Hybrid node mode** (satellite+storagenode+repairnode on one host)
- [x] **External configuration** (JSON config files, publishable code)
- [x] **Terminal UI** (real-time dashboard with notifications)

**🚧 In Progress (Next Sessions):**
- [ ] **Storagenode auditor & scoring** (Task 8) - latency/success tracking
- [ ] **Proof-of-storage challenges** (Task 9) - integrity audits without full transfer
- [ ] **Reputation & ranking system** (Task 10) - 6-factor composite scoring
- [ ] **Public leaderboard** (Task 11) - competitive participation

**📋 Roadmap (Jan 2026):**
- [ ] **Storagenode onboarding** (Task 12) - join handshake, health checks, graceful drain
- [ ] **Placement & scheduling** (Task 13) - geo-awareness, diversity, even-fill
- [ ] **Versioning & GC** (Task 14) - object versions, retention policies, safe reclaim
- [ ] **Tests & documentation** (Task 15) - unit tests, security tests, README-dev.md
- [ ] **Dependency reduction** (Task 16) - pure-Python fallbacks, bundling

---

## 📊 Planned Features (Coming Soon)

### 🏆 Leaderboard & Gamification
- **Public stats dashboard** showing top nodes by:
  - Uptime percentage (long-running nodes)
  - Repair contributions (fragments reconstructed)
  - Response latency (fastest nodes)
  - Storage capacity contributed
  - Composite reputation score
- **Team competitions** (operator-defined teams)
- **Badges & achievements** (milestones: 99.9% uptime, 1000 repairs, etc.)
- **Historical graphs** (node performance over time)

### 🔍 Proof-of-Storage Audits
- **Random fragment challenges** with nonce
- **Checksum verification** without full transfer
- **Audit logging** for reputation tracking
- **Penalties for failures** (score reduction, job deprioritization)
- **Spot checks** (occasional full fragment fetch)

### 📍 Geographic Diversity
- **12 fault domains** (NA-East, NA-West, Europe, Asia, etc.)
- **Placement rules**: min 3 zones per object
- **Latency-aware selection** (prefer nearby when diversity satisfied)
- **Rack/operator diversity** (avoid correlated failures)

### 🎯 Smart Scheduling
- **Score-driven assignment** (high-reputation nodes preferred)
- **Even-fill balancing** (avoid hot spots)
- **Per-feeder throttling** (adaptive rate limits)
- **Global backpressure** (slow everyone when capacity low)

---

## 🛠️ Configuration

Settings are externalized in `config.json`. Templates provided:

### Origin Config (`origin_config.json`)
```json
{
  "node": {
    "mode": "origin",
    "name": "LibreMesh-Origin",
    "advertised_ip": "192.168.0.163"
  },
  "network": {
    "listen_host": "0.0.0.0",
    "listen_port": 8888,
    "storage_port": 0,
    "repair_rpc_port": 7888
  },
  "sync": {
    "node_sync_interval": 30,
    "registry_sync_interval": 300
  }
}
```

### Satellite Config (`satellite_config.json`)
```json
{
  "node": {
    "mode": "hybrid",
    "roles": ["satellite", "storagenode", "repairnode"],
    "name": "LibreMesh-Sat-01",
    "advertised_ip": "192.168.0.164"
  },
  "network": {
    "listen_host": "0.0.0.0",
    "listen_port": 8888,
    "storage_port": 9889,
    "origin_host": "192.168.0.163",
    "origin_port": 8888
  },
  "limits": {
    "max_concurrent_connections": 100,
    "connection_rate_limit": 10,
    "connection_timeout_seconds": 300,
    "max_repair_bandwidth_mbps": 0,
    "log_level": "INFO"
  }
}
```

### Logging Configuration

LibreMesh uses structured JSON logging to three separate log files:
- `logs/control.log`: Control plane events (connections, registry, sync)
- `logs/repair.log`: Repair worker events (jobs, claims, completions)
- `logs/storage.log`: Storage operations (fragments, audits, P2P)

**Log Levels** (set in `config.json` under `limits.log_level`):
- `DEBUG`: Verbose output (probes, heartbeats, all operations)
- `INFO`: Normal operation (connections, repairs, important events) - **Default**
- `WARNING`: Warnings and degraded states
- `ERROR`: Errors and failures
- `CRITICAL`: Critical failures requiring attention

**Features:**
- Automatic log rotation (10MB per file, 5 backups = 50MB total per logger)
- JSON format for machine parsing and log aggregation
- Command-line override: `python satellite.py --log-level DEBUG`
- Per-node configuration: Set different log levels for origin/satellites/storagenodes

**Example:**
```bash
# Run with debug logging (override config)
python satellite.py --log-level DEBUG

# Check logs
tail -f logs/control.log | jq .
```

**Config validation:**
- Invalid modes raise clear errors at startup
- Missing config.json uses sensible defaults
- Operator-specific settings never committed to git

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

## 🎯 Project Goals

**Short-term (2025-Q1):**
- ✅ Finish core repair orchestration (Tasks 8-11)
- ✅ Complete storagenode lifecycle (Tasks 12-14)
- ✅ Ship tests and documentation (Task 15-16)
- 🎉 **Launch alpha network** (3-5 nodes)

**Mid-term (2025-Q2/Q3):**
- 📈 Grow to 10-20 active nodes
- 🎮 Launch public leaderboard
- 📚 Write deployment guides (Pi SD images, Docker)
- 🌍 Add geographic diversity tracking

**Long-term (2025-Q4+):**
- 🚀 Scale to 50-100 nodes
- 🏆 Establish competitive teams
- 📊 Web dashboard for stats/monitoring
- 🎓 Educational content (workshops, talks)
- 🤝 Community governance model

**Non-Goals:**
- ❌ Cryptocurrency or tokens
- ❌ Commercial cloud service
- ❌ Enterprise SLAs or guarantees
- ❌ Centralized control or profit motive

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
A: Keep your node online, complete repairs, respond quickly to challenges. (Coming in Task 11)

**Q: Is there a GUI?**  
A: Terminal UI for now. Web dashboard planned later.

**Q: Can I run multiple roles on one Pi?**  
A: Yes! Use hybrid mode: `"roles": ["satellite", "storagenode", "repairnode"]`

**Q: What's the minimum network size?**  
A: 10 nodes for k=6, n=10. Start with k=2, n=3 for 3-node testing.

---

## 🚨 Spam Detection & Fair Play

LibreMesh includes automated spam detection to protect the network from abuse. The system uses pattern recognition rather than punishment—suspicious feeders are throttled (slowed down) rather than blocked, boring attackers into giving up.

### Spam Detection Patterns

We monitor for these patterns, which indicate automated abuse rather than legitimate user behavior:

#### 1. **Duplicate File Abuse**
- **Pattern**: Same file (identical checksum) uploaded 5+ times
- **Why**: Normal users don't re-upload the same file repeatedly. This pattern suggests testing fragmentation or storage limits.
- **Response**: Uploads throttled; feeder warned in RPC response

#### 2. **Upload/Delete Churn**
- **Pattern**: >80% of uploads deleted within 1 hour of upload
- **Why**: Legitimate users keep files; this pattern wastes storage and tests retention logic.
- **Response**: Operations throttled; feeder warned

#### 3. **Storage Amplification Attack**
- **Pattern**: 1000+ objects stored with average size <10KB
- **Why**: Real data has realistic file sizes; 1000s of tiny objects indicates payload testing.
- **Response**: Uploads throttled; feeder warned

#### 4. **Rate Limit Assault**
- **Pattern**: Sustained requests at max rate (60/min) for >30 minutes straight
- **Why**: Humans vary usage; constant maximum-rate indicates scripted attack.
- **Response**: Throttled to 20/min; feeder notified of throttle duration

#### 5. **Robotic Upload Pattern**
- **Pattern**: Exact same interval between uploads (±5 seconds) for 10+ uploads
- **Why**: Humans are inconsistent; machines are predictably regular.
- **Response**: Uploads throttled; feeder warned

#### 6. **Rapid Micro-Changes**
- **Pattern**: Same filename re-uploaded with 1-10 byte changes 10+ times in <1 hour
- **Why**: Indicates fuzzing or testing attack surface, not normal file management.
- **Response**: Uploads throttled; feeder warned

### How "Boring" Works

Instead of blocking, we throttle suspected spammers:
- **Score 5-6**: Warning sent in RPC response; logging enabled
- **Score 8+**: 5-10 second delays added to operations (tedious for bots, suspicious to humans)
- **Per-IP tracking**: Score resets after 24 hours of clean activity
- **Repeat offense**: If same IP shows spam patterns within 7 days, escalates to harder throttling
- **Operator control**: Network operators can whitelist known power-users or batch jobs

### Transparency for Feeders

All RPC responses include:
```json
{
  "status": "ok",
  "spam_score": 0-10,            // 0=clean, 5+=warning, 8+=throttled
  "warning_reason": "string",     // Human-readable explanation
  "throttle_duration_seconds": 0, // How long this operation is delayed
  "suggestion": "string"          // How to avoid throttling
}
```

Feeders always know *why* they're throttled and what to do about it.

### Fair Play Principles

- ✅ **Transparent**: No silent blocking; always explain the pattern detected
- ✅ **Recoverable**: First offense resets after 24h clean behavior
- ✅ **Graduated**: Repeat offenders escalate to harder throttling, not instant ban
- ✅ **Preventable**: Published rules let legitimate power-users configure safely
- ✅ **Human-friendly**: Designed to bore bots, not frustrate humans

---

<p align="center">
  <b>Built with ❤️ by hobbyists, for hobbyists</b><br>
  <i>No tokens. No hype. Just resilient distributed storage.</i>
</p>

<p align="center">
  <a href="https://github.com/yourusername/LibreMesh/stargazers">⭐ Star</a> •
  <a href="https://github.com/yourusername/LibreMesh/issues">🐛 Issues</a> •
  <a href="https://github.com/yourusername/LibreMesh/discussions">💬 Discuss</a>
</p>
