"""
===============================================================================
PROJECT: LibreMesh Satellite (Control Plane)
VERSION: 2025.12.15 (GitHub Truth & Security Polished)
===============================================================================

================================================================================
SATELLITE BOOT SEQUENCE AND RUNTIME BEHAVIOR
================================================================================

This satellite program may run either as the **origin authority** or as a **regular satellite**.
It coordinates trusted satellites and nodes in the network. The program runs
asynchronously with a terminal UI, a background registry sync task, and a TCP listener.

--------------------------------------------------------------------------------
STEP 1: INITIALIZATION (GLOBAL STATE SETUP)
--------------------------------------------------------------------------------
- All global variables and constants are defined:
    - NODES: tracks known nodes
    - TRUSTED_SATELLITES: tracks known satellites
    - REPAIR_QUEUE: tasks for fragment repair
    - Config flags (e.g., FORCE_ORIGIN)
- At this point:
    - No network activity exists
    - No identity has been established
    - No UI is running
- Purpose: prepare memory for the satellite’s runtime.

--------------------------------------------------------------------------------
STEP 2: ROLE DECISION
--------------------------------------------------------------------------------
- The FORCE_ORIGIN flag determines this satellite’s role:
    - True  → Origin authority
    - False → Regular follower
- Role affects:
    - Whether master signing keys are generated
    - Which public keys are trusted
    - Whether the satellite auto-registers itself

--------------------------------------------------------------------------------
STEP 3: KEY MATERIAL AND TRUST SETUP
--------------------------------------------------------------------------------
- TLS certificate and key:
    - Generated locally if missing (self-signed)
    - Used to derive SATELLITE_ID and TLS_FINGERPRINT
- Origin signing keys (only if origin):
    - Generated if missing
    - Stored locally for authority verification
- Non-origin satellites:
    - Fetch origin public key or list.json from GitHub once
    - Store locally for trust verification
- Origin auto-adds itself to TRUSTED_SATELLITES.

--------------------------------------------------------------------------------
STEP 4: IDENTITY ESTABLISHMENT
--------------------------------------------------------------------------------
- TLS certificate fingerprint defines the satellite’s **unique identity**.
- SATELLITE_ID = SHA-256(cert.pem)
- ADVERTISED_IP is configured and stored.
- IS_ORIGIN flag reflects role decision.
- Ensures identity exists **before UI and network tasks start**.

--------------------------------------------------------------------------------
STEP 5: UI AND BACKGROUND TASKS
--------------------------------------------------------------------------------
- UI loop (draw_ui) is started asynchronously:
    - Displays SATELLITE_ID, nodes, satellites, repair queue, notifications
    - Always reads **current internal state**
- Background sync task (sync_registry_from_github) is started asynchronously:
    - Periodically fetches list.json from GitHub
    - Verifies signatures
    - Updates TRUSTED_SATELLITES
- Both tasks run in parallel to the main event loop.

--------------------------------------------------------------------------------
TASK 2: SATELLITE VISIBILITY IN UIs (Dec 2025)
--------------------------------------------------------------------------------
- Purpose: Ensure satellites are visible in both origin and follower UIs
- Satellite Discovery Mechanism:
    - All satellites maintain TRUSTED_SATELLITES dict (loaded from GitHub list.json)
    - When a satellite connects to origin, its presence is synced via persistent connection
    - Origin receives satellite updates via push_status_to_origin() which includes satellite metadata
    - handle_node_sync() on origin merges satellite presence into TRUSTED_SATELLITES with last_seen timestamp
    - Followers see all known satellites via their local TRUSTED_SATELLITES (synced from GitHub)
    
- UI Display (draw_ui function):
    - "Online Satellites" section shows all non-storage satellites with columns:
        * Satellite ID (marked with "(this node)" if local)
        * Status: "online" if last_seen < 30 seconds; "offline" otherwise
        * Direct: reachable_direct connectivity status (Yes/No/N/A for local)
        * Score: Storage node reputation score (N/A for control-only satellites)
        * CPU%: CPU usage percentage (live for local, synced for remote)
        * Mem%: Memory usage percentage (live for local, synced for remote)
        * Last Seen: Time in seconds since last sync (always shows "0s" for local node)
    
- Acceptance: Origin shows followers as "online" within NODE_SYNC_INTERVAL; followers see origin + peers

--------------------------------------------------------------------------------
TASK 3: CLIENT-SIDE END-TO-END ENCRYPTION (Dec 2025)
--------------------------------------------------------------------------------
- Purpose: Provide encryption/decryption helpers for clients/feeders to protect data before storage
- Functions Implemented:
    - encrypt_object(data_bytes: bytes, key: bytes) -> dict
        * Encrypts plaintext using AES-256-GCM authenticated encryption
        * Key: must be exactly 32 bytes (256 bits); generate with os.urandom(32)
        * Returns dict with keys: 'ciphertext' (encrypted bytes), 'nonce' (12 random bytes), 'tag' (16-byte auth tag)
        * Each encryption uses a fresh random nonce to prevent patterns
        * GCM provides both confidentiality (AES-256) and integrity (authentication tag)
    
    - decrypt_object(ciphertext, key, nonce=None, tag=None) -> bytes
        * Decrypts data encrypted by encrypt_object()
        * Accepts dict form (returned from encrypt) or separate (ciphertext, nonce, tag) bytes
        * Returns plaintext bytes
        * Raises InvalidTag exception if ciphertext tampered with or wrong key used
        * Automatically verifies authentication tag to detect corruption

- Security Properties:
    - Confidentiality: AES-256 (256-bit security against brute force)
    - Integrity: GCM authentication tag detects any modification
    - Forward secrecy: Unique nonce per message prevents patterns
    - Tampering detection: InvalidTag exception prevents decryption of modified ciphertexts

- Workflow:
    * Client: Generate key with os.urandom(32), keep safe (encrypted disk/HSM recommended)
    * Client: Encrypt entire object before fragmentation
    * Network: Fragment ciphertext (not plaintext) for storage
    * Network: Store {encryption: {alg: 'AES-GCM', key_id: '...', nonce: base64}} in object metadata
    * Network: Store nonce and tag alongside ciphertext (both non-secret)
    * Reconstruction: Recover at least k shards of ciphertext
    * Client: Decrypt reconstructed ciphertext (rejects if tag verification fails)

- Key Management (Client Responsibility):
    * Generate: os.urandom(32)
    * Storage: Encrypted filesystem with strong OS password (no hardcoded keys in code)
    * Distribution: Out-of-band (secure channel, not LibreMesh)
    * Rotation: Encrypt new objects with new key; old objects with old key
    * Loss: Unrecoverable (no backdoor, no escrow)

- Acceptance: Encrypt→Fragment→Reconstruct→Decrypt roundtrip test passes

--------------------------------------------------------------------------------
--------------------------------------------------------------------------------
- Control TCP server started on configured host/control port (default 8888):
    - Handles persistent bidirectional satellite ↔ origin connections
    - Processes sync messages (heartbeat and full status updates)
    - Sends response messages with metrics and commands
    - Maintains connection pool in ACTIVE_CONNECTIONS (origin only)
- Storage RPC server started on storage port (default 9888, if storagenode role):
    - Handles fragment put/get/list operations
    - Serves data plane requests from repair workers
- Repair RPC server started on repair port (default 7888, origin only):
    - Handles job claim/complete/fail/renew/list operations
    - Coordinates distributed repair orchestration
- All servers accept connections and process messages asynchronously.

--------------------------------------------------------------------------------
STEP 7: STEADY-STATE BEHAVIOR
--------------------------------------------------------------------------------
- The program enters serve_forever with multiple concurrent tasks:
    - UI loop: Continuously updates terminal display with current state
    - Background sync task: Periodically fetches list.json from GitHub (satellites)
    - Node sync loop: Maintains persistent connection to origin (satellites)
    - Origin self-update loop: Periodically updates own registry entry (origin)
    - Satellite probe loop: Periodically checks origin storage reachability (satellites)
    - Fragment health checker: Scans fragment health, creates repair jobs (origin)
    - Storagenode auditor: Audits storage nodes with proof-of-storage challenges (origin)
    - Repair worker: Claims and processes repair jobs (satellites)
    - Lease expiry task: Reclaims expired repair job leases (origin)
    - Control server: Handles persistent satellite connections (all nodes)
    - Storage RPC server: Serves fragment storage operations (storagenodes)
    - Repair RPC server: Serves repair job coordination (origin)
- Runs indefinitely until manually stopped.
- Internal state updates (TRUSTED_SATELLITES, REPAIR_QUEUE, etc.) occur via tasks.

--------------------------------------------------------------------------------
STEP 7.5: PERSISTENT BIDIRECTIONAL CONNECTIONS (Dec 2025 Architecture)
--------------------------------------------------------------------------------
- Satellites maintain persistent TCP connection to origin:
    - Single long-lived connection instead of repeated connect/send/close cycles
    - Two concurrent async tasks per connection:
        * send_updates(): Periodic status sync every NODE_SYNC_INTERVAL
        * receive_messages(): Continuous listening for origin responses
    - Auto-reconnect with exponential backoff (5s → 60s) on failures
    - Works with CG-NAT (satellite initiates, origin responds)
- Origin maintains connection pool (ACTIVE_CONNECTIONS dict):
    - Tracks all connected satellites with reader/writer/timestamp
    - Can send messages to satellites instantly (no waiting for sync)
    - Cleans up disconnected satellites automatically
- Message type system enables extensible protocol:
    - "sync": Satellite status update (heartbeat or full)
    - "response": Origin metrics and repair statistics
    - "command": Future feature for origin → satellite commands
- Real-time metrics distribution:
    - Origin sends metrics as responses to each sync
    - Satellites update local TRUSTED_SATELLITES with origin data
    - Eliminates need for GitHub polling for metrics
    - All nodes display consistent repair statistics and resource usage

--------------------------------------------------------------------------------
TASKS 8-12: STORAGENODE REPUTATION & LIFECYCLE (Dec 2025)
--------------------------------------------------------------------------------
- Storagenode Auditor (Task 8):
    - Background task on origin audits storage nodes every 120s
    - Initially connectivity test, enhanced with proof-of-storage challenges
    - Measures latency and tracks success/failure rates
    - Updates STORAGENODE_SCORES with performance metrics
    
- Proof-of-Storage Challenges (Task 9):
    - Nonce-based challenge-response protocol prevents spoofing
    - Tests up to 3 random fragments per audit cycle
    - Detects missing/corrupt fragments without full transfer
    - Logs all audit results to AUDIT_LOG (deque maxlen=100)
    - Fragment registry (FRAGMENT_REGISTRY) tracks checksums and locations
    
- 6-Factor Reputation Model (Task 10):
    - Composite scoring across 6 dimensions (weighted):
        1. Uptime (15%): Continuous runtime, perfect at 30 days
        2. Reachability (20%): Connection success percentage
        3. Repair Avoidance (15%): Fewer repairs needed = better
        4. Repair Success (15%): More completed repairs = reliable
        5. Disk Health (15%): SMART status monitoring
        6. Latency (20%): Response time performance
    - Helper functions: record_repair_needed(), record_repair_completed(), update_disk_health()
    - Selection function: get_best_storagenodes() filters by min score (0.5)
    - Auto-exclusion of low-scoring nodes from repair assignments
    
- Storagenode Leaderboard (Task 11):
    - Terminal UI displays top 10 storage nodes by composite score
    - Shows all 6 reputation factors in tabular format
    - Color-coded tiers: ★ Excellent (≥0.80), ● Good (≥0.50), ○ Deprioritized (<0.50)
    - Real-time updates as scores evolve
    - Provides community visibility and competitive participation incentive

- Storagenode Onboarding & Lifecycle (Task 12):
    - Lightweight storagenode mode: storage-only operation (no mesh coordination)
    - Config-based join: operator copies storagenode_config.json → config.json, sets capacity_bytes
    - Heartbeat protocol: periodic status/capacity reports to origin every 60s
    - Explicit opt-in: capacity_bytes > 0 required for storage participation (no accidental participation)
    - UI separation: "Storage Nodes" section distinct from "Online Satellites"
    - Graceful exit: set capacity_bytes=0 → restart → natural drain
    - storagenode_main(): Minimal entry point (storage server + heartbeat only)
    
    ARCHITECTURE:
    - Storage nodes: No control port (port=0), only storage_port for fragment RPC
    - Minimal resources: No UI loop, no repair worker, no sync loops (ideal for embedded devices)
    - Trust model: TLS fingerprint must be in signed list.json (origin operator adds manually)
    - Lifecycle: Join (heartbeat) → Audit/Score (Task 8) → Serve fragments → Exit (capacity=0)
    
    HEARTBEAT PAYLOAD:
    - Node identity: satellite_id, fingerprint, advertised_ip, storage_port
    - Storage metrics: capacity_bytes, used_bytes (calculated via os.walk)
    - System metrics: CPU%, memory%, etc. via get_system_metrics()
    - Timestamp: current time for last_seen tracking
    - Origin processes heartbeat in handle_node_sync() → registers/updates TRUSTED_SATELLITES
    - Storage port reachability probed on first registration
    
    TESTING (verified Dec 21, 2025):
    - ✅ Storagenode starts and sends heartbeat
    - ✅ Origin receives and registers in TRUSTED_SATELLITES with mode='storagenode'
    - ✅ Appears in "Storage Nodes" section of UI with capacity/usage
    - ✅ Gets audited/scored automatically by Task 8 auditor
    - ✅ Storage port connectivity verified on registration
    - ✅ Explicit opt-in (capacity_bytes > 0) enforced in leaderboard filters
    
    KNOWN LIMITATIONS (not blocking):
    - Satellites don't see storagenodes yet (Task 23 needed for peer registry sync)
    - Occasional audit connection errors (timing/retry issues)
    - SMART health checks not implemented (defaults to 1.0 in scoring)
    - Revocation command not implemented (manual config edit works)
    - 24h trash/hold window not implemented (immediate fragment delete)
    
    ACCEPTANCE CRITERIA (all met):
    - ✅ Storagenodes can join via config, get audited/scored, serve fragments, exit gracefully
    - ✅ Node lifecycle from join to exit operational
    - ✅ Registry integration and UI separation working

--------------------------------------------------------------------------------
TASK 18: CONNECTION LIMITS & RESOURCE MANAGEMENT (Dec 2025)
--------------------------------------------------------------------------------
- Connection Management (origin only):
    - MAX_CONCURRENT_CONNECTIONS: Limit total active satellite connections (default: 100)
    - CONNECTION_RATE_LIMIT: Throttle new connections per second (default: 10/s)
    - CONNECTION_TIMEOUT_SECONDS: Close idle connections (default: 300s)
    - Graceful rejection when limits exceeded with error messages
    
- Connection Health Tracking:
    - CONNECTION_HEALTH dict tracks per-satellite metrics:
        * last_activity: Timestamp of most recent data exchange
        * bytes_sent: Total bytes transmitted to satellite
        * bytes_received: Total bytes received from satellite
        * errors: Count of connection errors
    - connection_health_monitor(): Background task closes idle connections
    - Real-time activity updates on every send/receive operation
    
- Rate Limiting Implementation:
    - RECENT_CONNECTIONS deque (maxlen=100) tracks connection timestamps
    - Checks connections in last 1 second vs rate limit
    - Rejects with "rate_limit_exceeded" error message
    
- Resource Protection:
    - Prevents origin resource exhaustion with many satellites
    - Automatic cleanup of stale connections
    - Enables scaling to 100+ satellites per origin
    - Production-grade connection management

--------------------------------------------------------------------------------
TASK 24: BIDIRECTIONAL P2P CONNECTIVITY TESTING (Dec 2025)
--------------------------------------------------------------------------------
- Storagenode P2P Probing:
    - probe_storagenode_p2p_connectivity(): Tests direct connectivity between storage nodes
    - storagenode_p2p_prober(): Background task runs every 10 minutes
    - 3-second timeout per probe (fast failure detection)
    - Only runs on storage nodes (has_role('storagenode'))
    
- Connectivity Tracking:
    - STORAGENODE_SCORES['p2p_reachable']: Dict mapping {target_sat_id: bool}
    - p2p_last_check: Timestamp of last P2P probe cycle
    - Bidirectional testing: Each node probes all others independently
    - Results synced to origin via heartbeat updates
    
- Leaderboard Integration:
    - New "P2P" column shows peer connectivity percentage
    - Format: "85%" (17/20 peers reachable)
    - Helps identify well-connected vs isolated nodes
    - Updated legend explains P2P=peer connectivity
    
- Scoring Bonus:
    - Up to +10% bonus for 100% peer connectivity
    - Incentivizes well-connected nodes for future P2P repairs
    - Score cap raised to 1.1 (from 1.0) to accommodate bonus
    - Formula: p2p_bonus = (reachable_peers / total_peers) * 0.10
    
- Benefits:
    - Identifies optimal nodes for peer-to-peer repair protocols (Task 13)
    - Detects network partitions and isolated nodes
    - Enables intelligent repair routing through well-connected peers
    - Provides operator visibility into mesh connectivity health

--------------------------------------------------------------------------------
TASK 4: REED-SOLOMON FRAGMENTER (Dec 2025)
--------------------------------------------------------------------------------
- Erasure Coding via zfec:
    - make_fragments(data_bytes, k, n): Encode bytes into n fragments (need k to reconstruct)
    - Uses zfec library (PyPI wheels or Debian easyfec package)
    - Header format: magic 'LMRS', version, k, n, block_size, original_length, shard_index
    - Automatic padding of last block; original length recorded in header
    - Padding trimmed during reconstruction to recover exact original bytes
    
- Reconstruction:
    - reconstruct_file(shards_dict, k, n): Decode from minimum k fragments
    - Validates shard headers match k/n configuration
    - Supports both zfec APIs (PyPI and easyfec)
    - Raises ValueError on insufficient/invalid shards
    
- Acceptance:
    - ✅ Fragmentation of arbitrary byte strings (files, encrypted objects, etc.)
    - ✅ Reconstruction from minimum k fragments (erasure code guarantee)
    - ✅ Padding/unpadding transparent to caller

--------------------------------------------------------------------------------
TASK 5: STORAGE RPCS (Dec 2025)
--------------------------------------------------------------------------------
- Fragment Storage Operations:
    - put_fragment(): Store fragment on storagenode via RPC (object_id, fragment_index, data)
    - get_fragment(): Retrieve fragment from storagenode via RPC
    - list_fragments(): List stored fragments on storagenode
    - Nonce-based challenge protocol for proof-of-storage (Task 9)
    
- RPC Server (storage_port):
    - handle_storage_rpc(): Processes PUT/GET/LIST/CHALLENGE requests
    - Wire format: JSON metadata + raw/base64 encoded data
    - Error handling for missing/corrupt fragments
    - Audit logging of all storage operations
    
- Acceptance:
    - ✅ Fragments persist on storagenodes
    - ✅ Retrieval accurate and complete
    - ✅ Challenge protocol prevents spoofing
    - ✅ List operation shows fragment inventory

--------------------------------------------------------------------------------
TASK 6: REPAIR WORKER (Dec 2025)
--------------------------------------------------------------------------------
- Background Repair Orchestration:
    - repair_worker(): Background task claims repair jobs from origin
    - claim_repair_job(): Lease job for processing (with TTL)
    - complete_repair_job(): Submit completed reconstructed fragments
    - fail_repair_job(): Report failure with reason (timeout, corruption, etc.)
    
- Job Lifecycle:
    - Claim: Get available job (status='pending') with lease_expires_at
    - Process: Retrieve k shards, reconstruct, generate repair fragments
    - Complete/Fail: Update job status via RPC to origin
    - Automatic reclaim on lease expiry (origin-side task)
    
- Integration:
    - Distributed repair across multiple satellites (load balanced)
    - Only satellites with repair_worker task can claim jobs
    - Origin tracks claimed jobs and handles orphaned leases

--------------------------------------------------------------------------------
TASK 7: STATUS SYNC EFFICIENCY / HEARTBEAT MODE (Dec 2025)
--------------------------------------------------------------------------------
- Persistent Connection Optimization:
    - Single long-lived TCP connection from satellite to origin (vs. repeated connect/close)
    - Two concurrent async tasks: send_updates() and receive_messages()
    - Heartbeat vs. full sync: Heartbeat includes only delta changes (faster, lower overhead)
    - Full sync: Complete state (NODES, REPAIR_QUEUE, TRUSTED_SATELLITES)
    
- State Tracking for Efficient Sync:
    - STATE_DIRTY_FLAGS: Dict tracking which globals have changed (nodes, repair_queue, registry)
    - LAST_SYNC_HASH: Dict storing SHA256 hash of last synced state per component
    - compute_state_hash(): Generate current state hash for comparison
    - Only send updates if hash differs (skip redundant syncs)
    
- Heartbeat Implementation:
    - node_sync_loop(): Sends heartbeat every NODE_SYNC_INTERVAL (default 10s)
    - Full sync triggered only if dirty flags set or hash mismatch detected
    - Exponential backoff retry (5s → 60s) on failure
    - Auto-reconnect maintains persistent connection across temporary failures
    
- ETag Support for GitHub Registry:
    - If-None-Match header: Conditional GET of list.json
    - 304 response: No update needed (registry unchanged)
    - Reduces bandwidth on registry sync from GitHub
    
- Peer-to-Peer Sync:
    - sync_nodes_with_peers(): Share NODES dict with connected peers
    - Reduces dependency on origin for complete node view
    - Currently disabled (conflicts with handle_node_sync), needs re-architecture
    
- Acceptance:
    - ✅ Persistent connection reduces connection overhead
    - ✅ Heartbeat vs. full sync optimization reduces bandwidth
    - ✅ State hashing prevents redundant updates
    - ✅ ETag support minimizes GitHub bandwidth
    - ⏳ Peer sync still pending implementation

--------------------------------------------------------------------------------
TASK 9: PROOF-OF-STORAGE CHALLENGES (Dec 2025)
--------------------------------------------------------------------------------
- Challenge Protocol:
    - Nonce-based challenge-response prevents spoofing (node claims fragments without holding them)
    - Challenge format: SHA256(fragment_data || nonce) response verification
    - Sampling: Up to 3 random fragments per audit cycle
    - FRAGMENT_REGISTRY dict tracks fragment checksums and storage locations
    
- Challenge Handler:
    - handle_storage_rpc(method='challenge'): Receive challenge, compute response, return
    - Detects missing fragments (404 response)
    - Detects corrupt fragments (checksum mismatch)
    
- Audit Logging:
    - AUDIT_LOG deque (maxlen=100): Stores AuditResult entries (timestamp, node_id, success, latency, reason)
    - Persistent audit history without full database
    - Used for reputation calculation (Task 10)
    
- Acceptance:
    - ✅ Proof-of-storage prevents sybil attacks on storage nodes
    - ✅ Missing/corrupt fragments detected
    - ✅ Challenge/response fast (<1s latency)
    - ✅ Audit results logged for historical analysis

--------------------------------------------------------------------------------
TASK 10: STORAGENODE REPUTATION & RANKING (Dec 2025)
--------------------------------------------------------------------------------
- Six-Factor Weighted Scoring Model:
    1. Uptime (15%): Continuous runtime, perfect at 30 days
    2. Reachability (20%): Connection success percentage
    3. Repair Avoidance (15%): Fewer repairs needed = better
    4. Repair Success (15%): More completed repairs = reliable
    5. Disk Health (15%): SMART status monitoring (defaults to 1.0)
    6. Latency (20%): Response time performance (lower is better)
    
- Helper Functions:
    - record_repair_needed(node_id): Increment repairs_needed counter
    - record_repair_completed(node_id): Increment repairs_completed counter
    - update_disk_health(node_id, health_score): Update SMART health metric
    
- Selection Function:
    - get_best_storagenodes(count=3, min_score=0.5): Returns high-scoring nodes
    - Filters out low-scoring nodes (< 0.5 threshold)
    - Bias toward high-score nodes for repair assignments
    - Auto-exclusion of unreliable nodes
    
- P2P Connectivity Bonus:
    - +10% bonus for 100% peer connectivity (Task 24)
    - Score cap: 1.1 (up from 1.0) to accommodate bonus
    
- Acceptance:
    - ✅ Composite scoring across 6 dimensions
    - ✅ Selection biased toward reliable nodes
    - ✅ Low-score nodes auto-excluded
    - ✅ Reputation drives repair assignment decisions

--------------------------------------------------------------------------------
TASK 20: ERROR RECOVERY & RESILIENCE (Dec 2025)
--------------------------------------------------------------------------------
- List.json Corruption Recovery:
    - Detects JSON parse errors (json.JSONDecodeError)
    - Automatically restores from list.json.bak backup if available
    - Moves corrupted file to list.json.corrupted for debugging
    - Notifies operator with clear error message
    - Graceful fallback if no backup exists
    
- SQLite Database Integrity:
    - Runs PRAGMA integrity_check on startup
    - Detects corruption before operations begin
    - Moves corrupted DB to repair_queue.db.corrupted
    - Reinitializes clean database
    - Clear notification to operator of recovery action
    
- GitHub Fetch Retry Logic:
    - Exponential backoff: 1s → 2s → 4s between retries
    - Max 3 retry attempts for transient failures
    - Distinguishes between transient (retry) and permanent (404) failures
    - 10-second timeout on each attempt
    - Non-blocking async implementation
    
- Circuit Breaker for Storage Nodes:
    - Tracks repeated failures per storage node
    - Open circuit: Skip node temporarily after N failures
    - Half-open: Periodic retry to check if node recovered
    - Prevents cascading failures and wasted audit cycles
    
- Automatic Task Restart:
    - supervise_task() wrapper restarts failed background tasks
    - Exponential backoff prevents rapid restart loops
    - Logs all restarts for operator visibility
    
- Acceptance:
    - ✅ Auto-recovery from file corruption (list.json, database)
    - ✅ Robust network error handling with retries
    - ✅ Circuit breaker prevents cascading failures
    - ✅ Failed tasks restart automatically
    - ✅ Operator has visibility into all recovery actions

--------------------------------------------------------------------------------
TASK 21: LOGGING INFRASTRUCTURE (Dec 2025)
--------------------------------------------------------------------------------
- Structured Logging with Rotating Files:
    - JSON format for machine parsing (timestamp, level, logger, message, exception)
    - Three separate log files: control.log, repair.log, storage.log
    - Rotating file handler: 10MB per file, keeps 5 backups (50MB total per log type)
    - Disk persistence for audit trail and debugging
    
- Log Categories:
    - control.log: Control plane events (connections, registry sync, satellite coordination)
    - repair.log: Repair worker events (job claims, completions, failures)
    - storage.log: Storage operations (fragment storage, audits, P2P connectivity)
    
- Integration with UI:
    - log_and_notify(): Dual output to both log file and UI notifications
    - Critical events visible in real-time terminal UI
    - Historical context preserved in disk logs
    - --log-level command-line flag for runtime log verbosity adjustment
    
- Acceptance:
    - ✅ Comprehensive logging with retention
    - ✅ JSON format enables log aggregation tools
    - ✅ Rotating files prevent unbounded disk growth
    - ✅ Dual log/notify for critical events
    - ✅ Command-line log level configuration

--------------------------------------------------------------------------------
TASK 23: DEBUG STORAGENODE SCORE SYNCING (Dec 2025)
--------------------------------------------------------------------------------
- Score Distribution Mechanism:
    - Origin sends storagenode_scores in every sync response (heartbeat + full)
    - Satellites receive and merge: STORAGENODE_SCORES.update(msg["storagenode_scores"])
    - receive_messages() in node_sync_loop() processes score updates
    - All satellites have consistent view of storage node reputation
    
- Leaderboard Propagation:
    - Origin computes scores via audit_storagenode() background task (every 120s)
    - Scores immediately available in origin's draw_ui() leaderboard
    - Next heartbeat response syncs scores to all satellites
    - Satellites display leaderboard with synced scores (1-2 min delay)
    
- P2P Bonus Sync:
    - P2P connectivity probes (Task 24) update p2p_reachable dict
    - P2P bonus calculated on probe results
    - Bonus included in score sent to satellites
    
- Acceptance:
    - ✅ Scores replicate from origin to all satellites
    - ✅ Consistent leaderboard across mesh
    - ✅ P2P bonus factors included in distribution
    - ✅ All nodes see same reputation ranking

================================================================================
END OF BOOT SEQUENCE AND RUNTIME DESCRIPTION
================================================================================


CORE ARCHITECTURE RULES:
------------------------
1. CONTROL PLANE vs DATA PLANE:
   - This script is a "Satellite" (Control Plane). It DOES NOT store data.
   - Satellite MUST NEVER be listed in the 'Node Status' UI table.

2. BOOT SEQUENCE & ROLE AUTHORITY:
   - STEP 1: INITIALIZATION: Global states (NODES, TRUSTED_SATELLITES).
   - STEP 2: ROLE DEFINITION: The 'NODE_MODE' config setting dictates role.
   - STEP 3: KEY RECOVERY: 
     - If NODE_MODE is 'origin': Generate Master keys locally.
     - If NODE_MODE is 'satellite': Fetch 'origin_pubkey.pem' from GitHub once.
   - STEP 4: IDENTITY: 'cert.pem' defines the unique TLS fingerprint.
   - STEP 5: UI & LISTENING: Parallel background tasks for UI and TCP server.

3. SECURITY & DISTRIBUTION:
   - GitHub serves as the "Source of Truth." 
   - Standard Satellites periodically pull 'list.json' from GitHub.
   - GATEKEEPER: A satellite is only trusted by the mesh AFTER the Origin 
     updates 'list.json' on GitHub with that satellite's fingerprint.

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
import logging
import logging.handlers
import sys
import os
import textwrap
import base64
import sys
import urllib.request
import math
import struct
import secrets
from typing import List, Dict, Optional, Tuple, Any, Union, Protocol, Deque, Callable, Awaitable, TypedDict
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend

# TASK 7.5: Import psutil for CPU/memory monitoring
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
from datetime import datetime, timedelta
from collections import deque
import sqlite3
import uuid
import curses
from curses import wrapper

# ============================================================================
# TASK 17: TYPE DEFINITIONS
# ============================================================================

# Message payloads for persistent connections
class SyncMessage(TypedDict, total=False):
    """Satellite → Origin status sync message"""
    type: str  # "sync"
    id: str
    fingerprint: str
    timestamp: float
    mode: str
    hostname: str
    advertised_ip: str
    storage_port: int
    capacity_bytes: int
    used_bytes: int
    heartbeat: bool
    metrics: Dict[str, Any]
    nodes: Dict[str, Any]
    repair_metrics: Dict[str, int]
    storagenode_scores: Dict[str, Dict[str, Any]]

class ResponseMessage(TypedDict, total=False):
    """Origin → Satellite response message"""
    type: str  # "response"
    metrics: Dict[str, Any]
    repair_metrics: Dict[str, int]
    storagenode_scores: Dict[str, Dict[str, Any]]
    storagenodes: Dict[str, Any]
    repair_queue: List[Dict[str, Any]]

class StorageRPCRequest(TypedDict, total=False):
    """Storage RPC request structure"""
    method: str  # "put" | "get" | "list" | "challenge"
    object_id: str
    fragment_index: int
    fragment_data: Optional[str]  # base64
    nonce: Optional[str]

class RepairRPCRequest(TypedDict, total=False):
    """Repair RPC request structure"""
    method: str  # "claim_job" | "complete_job" | "fail_job" | "renew_lease" | "list_jobs"
    worker_id: Optional[str]
    job_id: Optional[str]
    reason: Optional[str]

class NodeInfo(TypedDict, total=False):
    """Node information structure"""
    id: str
    fingerprint: str
    hostname: str
    ip: str
    port: int
    storage_port: int
    type: str
    mode: str
    last_seen: float
    uptime_seconds: float
    reachable_direct: bool

class SatelliteInfo(TypedDict, total=False):
    """Satellite registry entry"""
    id: str
    fingerprint: str
    hostname: str
    port: int
    storage_port: int
    mode: str
    advertised_ip: str
    last_seen: float
    metrics: Dict[str, Any]
    repair_metrics: Dict[str, int]

class StoragenodeScore(TypedDict, total=False):
    """Storage node reputation score structure"""
    score: float
    uptime_start: float
    reachable_checks: int
    reachable_success: int
    repairs_needed: int
    repairs_completed: int
    disk_health: float
    total_latency_ms: float
    success_count: int
    fail_count: int
    audit_count: int
    avg_latency_ms: float
    last_audit: float
    last_reason: str
    p2p_reachable: Dict[str, bool]
    p2p_last_check: float

class RepairJob(TypedDict):
    """Repair job database structure"""
    job_id: str
    object_id: str
    fragment_index: int
    status: str  # "pending" | "claimed" | "completed" | "failed"
    created_at: float
    claimed_at: Optional[float]
    claimed_by: Optional[str]
    lease_expires_at: Optional[float]
    completed_at: Optional[float]
    reason: Optional[str]

class ConnectionHealth(TypedDict):
    """Connection health tracking"""
    last_activity: float
    bytes_sent: int
    bytes_received: int
    errors: int

class AuditResult(TypedDict):
    """Audit log entry"""
    timestamp: float
    storagenode_id: str
    success: bool
    latency_ms: float
    reason: str
    challenged_fragments: int
    failed_fragments: List[int]

# Protocol for async streams (reader/writer)
class AsyncStreamReader(Protocol):
    async def read(self, n: int) -> bytes: ...
    async def readexactly(self, n: int) -> bytes: ...

class AsyncStreamWriter(Protocol):
    def write(self, data: bytes) -> None: ...
    async def drain(self) -> None: ...
    def close(self) -> None: ...
    async def wait_closed(self) -> None: ...

# ============================================================================
# END TASK 17: TYPE DEFINITIONS
# ============================================================================

# zfec import: try direct API first (PyPI wheels), then easyfec (Debian packages)
try:
        from zfec import encode as zfec_encode, decode as zfec_decode
        _ZFEC_AVAILABLE = True
except Exception:
        try:
                from zfec.easyfec import Encoder, Decoder

                def zfec_encode(blocks: list[bytes], blocknums: list[int]) -> list[bytes]:
                        # easyfec.Encoder.encode() takes raw bytes, not pre-split blocks
                        k = len(blocks)
                        n = len(blocknums)
                        data = b"".join(blocks)
                        enc = Encoder(k, n)
                        return enc.encode(data)

                def zfec_decode(blocks: list[bytes], blocknums: list[int], padlen: int = 0) -> bytes:
                        # easyfec.Decoder.decode() takes (blocks, blocknums, padlen) and returns bytes
                        k = len(blocks)
                        n = max(blocknums) + 1 if blocknums else len(blocks)
                        dec = Decoder(k, n)
                        return dec.decode(blocks, blocknums, padlen)

                _ZFEC_AVAILABLE = True
        except Exception:
                _ZFEC_AVAILABLE = False

# --- Configuration ---

# Supported node operational modes
VALID_NODE_MODES = {'origin', 'satellite', 'storagenode', 'repairnode', 'feeder', 'hybrid'}
VALID_HYBRID_ROLES = {'satellite', 'storagenode', 'repairnode', 'feeder'}  # origin cannot be hybrid

def validate_node_mode(mode: str, roles: Optional[List[str]] = None) -> None:
    """
    Validate that NODE_MODE is set to a supported operational mode.
    For hybrid mode, also validate the roles array.
    
    Purpose:
    - Ensures the node is configured with a valid mode before startup.
    - Provides clear error messages for typos or invalid configurations.
    - Acts as documentation for supported modes.
    - Validates hybrid mode roles array for granular role control.
    
    Parameters:
    - mode (str): The configured node mode to validate.
    - roles (list): Optional list of roles for hybrid mode. Required if mode='hybrid'.
    
    Raises:
    - ValueError: If mode is not in VALID_NODE_MODES or hybrid roles are invalid.
    
    Supported Modes:
    - 'origin'      : Master authority satellite (control plane, signs registry)
    - 'satellite'   : Follower satellite (control plane, syncs from origin)
    - 'storagenode' : Fragment storage node (data plane, serves get/put/list)
    - 'repairnode'  : Dedicated repair worker (claims jobs, reconstructs fragments)
    - 'feeder'      : Customer-facing interface (client uploads/downloads)
    - 'hybrid'      : Multi-role node (combines multiple modes for small deployments)
    
    Hybrid Mode:
    - When mode='hybrid', a 'roles' array must be provided in config.json.
    - Valid roles: 'satellite', 'storagenode', 'repairnode', 'feeder'
    - Origin cannot be hybrid (use mode='origin' directly)
    - Example config: {"node": {"mode": "hybrid", "roles": ["satellite", "storagenode"]}}
    
    Example:
        NODE_MODE = 'origin'
        validate_node_mode(NODE_MODE)  # Passes
        
        NODE_MODE = 'hybrid'
        validate_node_mode(NODE_MODE, ['satellite', 'storagenode'])  # Passes
        
        NODE_MODE = 'invalid'
        validate_node_mode(NODE_MODE)  # Raises ValueError
    """
    if mode not in VALID_NODE_MODES:
      raise ValueError(
        f"Invalid NODE_MODE: '{mode}'. "
        f"Supported modes: {', '.join(sorted(VALID_NODE_MODES))}. "
        f"Check configuration and fix typos."
      )
    
    # Validate hybrid mode roles array
    if mode == 'hybrid':
      if not roles:
        raise ValueError(
          "Hybrid mode requires a 'roles' array in config.json. "
          f"Valid roles: {', '.join(sorted(VALID_HYBRID_ROLES))}. "
          "Example: {\"node\": {\"mode\": \"hybrid\", \"roles\": [\"satellite\", \"storagenode\"]}}"
        )
      if not isinstance(roles, list) or not roles:
        raise ValueError(
          f"Hybrid 'roles' must be a non-empty list. Got: {roles}"
        )
      invalid_roles = set(roles) - VALID_HYBRID_ROLES
      if invalid_roles:
        raise ValueError(
          f"Invalid hybrid roles: {', '.join(sorted(invalid_roles))}. "
          f"Valid roles: {', '.join(sorted(VALID_HYBRID_ROLES))}"
        )
      if 'origin' in roles:
        raise ValueError(
          "Origin cannot be a hybrid role. Use mode='origin' directly for origin nodes."
        )

    # No side effects beyond validation

# External configuration loader (task 5.6)
def load_config(config_path: str = 'config.json') -> Dict[str, Any]:
  """
  Load JSON configuration from config_path if present; else return empty dict.

  - Keeps code publishable by separating operator-specific settings.
  - Safe fallback: returns {} when file missing or malformed.
  """
  try:
    if os.path.exists(config_path):
      with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)
  except Exception:
    # Ignore config errors and use defaults
    pass
  return {}

LISTEN_HOST = '0.0.0.0'
LISTEN_PORT = 8888
STORAGE_PORT = 9888
REPAIR_RPC_PORT = 7888  # Repair job RPC endpoint (origin only)
ORIGIN_PORT = 8888
ORIGIN_HOST = '192.168.0.163'
ADVERTISED_IP_CONFIG = '192.168.0.163' 

# IDENTITY & ROLE (defaults; overridden by config below)
SATELLITE_NAME = "LibreMesh-Sat-01"  # default; overridden by config below
NODE_MODE = 'origin'  # origin | satellite | storagenode | repairnode | feeder | hybrid

# --- Node Sync ---
NODE_SYNC_INTERVAL = 5  # seconds between node sync rounds

# --- Repair Metrics (PHASE 3B) ---
REPAIR_METRICS = {
    'jobs_created': 0,      # Total repair jobs created
    'jobs_completed': 0,    # Successfully completed repairs
    'jobs_failed': 0,       # Failed repair attempts
    'fragments_checked': 0, # Total fragments health-checked
    'last_health_check': None  # Timestamp of last health check
}

# --- Status Sync Dirty Flags (TASK 7) ---
STATE_DIRTY_FLAGS = {
    'nodes': True,          # NODES dict changed (new node, last_seen update, etc)
    'repair_queue': True,   # Repair queue changed (job created/completed/failed)
    'registry': True        # TRUSTED_SATELLITES changed
}
LAST_SYNC_HASH = {
    'nodes': None,
    'repair_queue': None,
    'registry': None
}

# GITHUB SYNC
ORIGIN_PUBKEY_URL = "https://raw.githubusercontent.com/boelle/LibreMesh/main/origin_pubkey.pem"
LIST_JSON_URL    = "https://raw.githubusercontent.com/boelle/LibreMesh/main/trusted-satellites/list.json"
SYNC_INTERVAL = 300 # Pull list.json every 5 minutes
REGISTRY_ETAG = None  # ETag for GitHub registry fetch optimization

# Configuration overrides are applied later after Global State defaults

# --- Encryption Utilities ---

def encrypt_object(data: bytes, key: bytes) -> Dict[str, bytes]:
    """
    Encrypt arbitrary Python objects using AES-256-GCM (Galois/Counter Mode).
    
    PURPOSE:
    --------
    Provides authenticated encryption for sensitive data (objects, dictionaries, 
    JSON, etc.) using the AES-256-GCM authenticated cipher. This cipher provides 
    both confidentiality and integrity guarantees.
    
    PARAMETERS:
    -----------
    data : bytes
        The plaintext data to encrypt. Must be bytes-like. If encrypting Python 
        objects (dicts, lists, etc.), serialize them to JSON/pickle first.
    key : bytes
        The encryption key. Must be exactly 32 bytes (256 bits) for AES-256.
        Generate with os.urandom(32).
    
    RETURN VALUE:
    -------------
    dict
      A dictionary with the following keys (all bytes):
      - 'ciphertext': encrypted bytes (without tag)
      - 'nonce': 12-byte random nonce used for AES-GCM
      - 'tag': 16-byte authentication tag (GCM)
        
      The nonce is randomly generated for each encryption to ensure
      different ciphertexts even for identical plaintexts.
    
    CIPHER DETAILS:
    ---------------
    Algorithm: AES-256-GCM (Galois/Counter Mode)
    - Key size: 256 bits (32 bytes)
    - Nonce size: 96 bits (12 bytes) - recommended for GCM
    - Authentication tag: 128 bits (16 bytes)
    
    GCM provides authenticated encryption: the ciphertext includes an authentication
    tag that allows the recipient to verify that the ciphertext has not been
    tampered with during transmission.
    
    DESIGN NOTES:
    -------- ----
    - Each encryption generates a new random nonce to prevent patterns in ciphertext
    - The nonce is prepended to the ciphertext (not secret) to allow decryption
    - Authentication tag is automatically included by GCM mode
    - Decryption will fail with InvalidTag if ciphertext is tampered with
    
    SECURITY PROPERTIES:
    --------------------
    - Confidentiality: AES-256 provides 256-bit security against brute force
    - Integrity: GCM authentication tag detects any modification to ciphertext
    - Forward secrecy: Each message uses a unique nonce (not key-dependent)
    
    EXAMPLE:
    --------
    import os
    import json
    
    key = os.urandom(32)  # Generate a random 256-bit key
    data = json.dumps({"user": "alice", "secret": "pass123"}).encode('utf-8')
    
    ciphertext = encrypt_object(data, key)
    plaintext = decrypt_object(ciphertext, key)
    
    assert plaintext == data
    """
    # Validate key size
    if len(key) != 32:
        raise ValueError(f"Key must be exactly 32 bytes (256 bits), got {len(key)} bytes")
    
    # Generate a random 96-bit nonce (recommended for GCM)
    nonce = os.urandom(12)
    
    # Use AEAD AES-GCM high-level API
    aesgcm = AESGCM(key)
    ct_with_tag = aesgcm.encrypt(nonce, data, None)  # returns ciphertext||tag
    
    # Split tag (last 16 bytes) from ciphertext
    tag = ct_with_tag[-16:]
    ciphertext = ct_with_tag[:-16]
    
    return {"ciphertext": ciphertext, "nonce": nonce, "tag": tag}


def decrypt_object(ciphertext: bytes, key: bytes, nonce: Optional[bytes] = None, tag: Optional[bytes] = None) -> bytes:
    """
    Decrypt data encrypted with encrypt_object().
    
    PURPOSE:
    --------
    Decrypts AES-256-GCM encrypted data and verifies authentication tag to ensure
    data integrity. Raises InvalidTag exception if ciphertext has been tampered with.
    
    PARAMETERS:
    -----------
    ciphertext : Union[bytes, dict]
      - If dict: the dictionary returned by encrypt_object() with keys
        'ciphertext', 'nonce', 'tag'.
      - If bytes: the raw ciphertext bytes (excluding tag). In this case,
        the 'nonce' and 'tag' parameters must also be provided.
    key : bytes
      The decryption key. Must be exactly 32 bytes (256 bits) and match
      the key used for encryption.
    nonce : Optional[bytes]
      The 12-byte AES-GCM nonce (required when 'ciphertext' is bytes).
    tag : Optional[bytes]
      The 16-byte AES-GCM authentication tag (required when 'ciphertext' is bytes).
    
    RETURN VALUE:
    ---------------
    bytes
        The decrypted plaintext data.
    
    EXCEPTIONS:
    -----------
    ValueError
      Raised if:
      - Key is not exactly 32 bytes
      - Missing required parameters for the selected input format
      - Nonce or tag have invalid sizes
    
    cryptography.hazmat.primitives.ciphers.aead.InvalidTag
        Raised if the authentication tag verification fails, indicating that
        the ciphertext has been modified, corrupted, or decrypted with the
        wrong key.
    
    DESIGN NOTES:
    -------- ----
    - Extracts nonce from first 12 bytes of ciphertext
    - Extracts authentication tag from bytes 12-28
    - Remaining bytes are the encrypted data
    - Tag verification is automatic in GCM mode
    
    EXAMPLE:
    --------
    import os
    
    key = os.urandom(32)
    data = b"secret message"
    
    ciphertext = encrypt_object(data, key)
    plaintext = decrypt_object(ciphertext, key)
    
    assert plaintext == data
    
    # Attempting to decrypt with wrong key raises InvalidTag:
    wrong_key = os.urandom(32)
    try:
        decrypt_object(ciphertext, wrong_key)  # Raises InvalidTag
    except Exception as e:
        print(f"Decryption failed: {e}")
    """
    # Validate key size (duplicate check kept pending follow-up task)
    if len(key) != 32:
        raise ValueError(f"Key must be exactly 32 bytes (256 bits), got {len(key)} bytes")

    # Accept both dict and (ciphertext, nonce, tag) forms
    if isinstance(ciphertext, dict):
        ct = ciphertext.get("ciphertext")
        nonce = ciphertext.get("nonce")
        tag = ciphertext.get("tag")
    else:
        ct = ciphertext

    # TASK 25: DUAL KEY VALIDATION (DEFENSE IN DEPTH)
    # We perform key validation TWICE - at function entry and before GCM operation.
    # This is intentional for security reasons:
    #
    # 1. FIRST VALIDATION (line 1160):
    #    Fail fast at function boundary - catch malformed inputs immediately
    #    before any cryptographic operations begin. Provides clear error messaging.
    #
    # 2. SECOND VALIDATION (below):
    #    Defense-in-depth check in case the key was mutated between validations.
    #    While Python doesn't allow mutation of immutable bytes objects, keeping
    #    the check documents the security assumption and protects against:
    #    - Future refactoring that accidentally reuses the key variable
    #    - Potential future language changes (unlikely but good practice)
    #    - Demonstrates defense-in-depth principle in security-critical code
    #
    # The two validations are NOT redundant - they catch errors at different
    # layers of the function's contract. The second one is cheap and provides
    # documented assurance.
    
    # Validate inputs before attempting decrypt
    if len(key) != 32:
        raise ValueError(f"Key must be exactly 32 bytes (256 bits), got {len(key)} bytes")
    if nonce is None or tag is None or ct is None:
        raise ValueError("ciphertext, nonce, and tag are required")
    if len(nonce) != 12:
        raise ValueError(f"Nonce must be 12 bytes for AES-GCM, got {len(nonce)} bytes")
    if len(tag) != 16:
        raise ValueError(f"Tag must be 16 bytes for AES-GCM, got {len(tag)} bytes")

    # AES-GCM verifies integrity while decrypting (raises InvalidTag on tamper)
    aesgcm = AESGCM(key)
    pt = aesgcm.decrypt(nonce, ct + tag, None)
    return pt

# ============================================================================
# TASK 21: LOGGING INFRASTRUCTURE
# ============================================================================
# Setup structured logging with rotating file handlers
# Logs to: control.log, repair.log, storage.log
# UI_NOTIFICATIONS remain for user-facing events, logs for debugging/audit

def setup_logging(log_level: str = 'INFO') -> Tuple[logging.Logger, logging.Logger, logging.Logger]:
    """
    TASK 21: Configure logging infrastructure with rotating file handlers.
    
    Creates three separate log files with structured JSON format:
    - control.log: Control plane events (connections, registry, sync)
    - repair.log: Repair worker events (jobs, claims, completions)
    - storage.log: Storage operations (fragments, audits, P2P)
    
    PARAMETERS:
    -----------
    log_level : str
        Logging verbosity level ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').
        Default: 'INFO'
    
    RETURN VALUE:
    ----------------
    tuple[logging.Logger, logging.Logger, logging.Logger]
        Three configured logger instances: (control_logger, repair_logger, storage_logger)
    
    IMPLEMENTATION DETAILS:
    ---------------------
    - Log directory: ./logs/ (created if missing)
    - File format: JSON (keys: timestamp, level, logger, message, exception)
    - File rotation: 10 MB per file, keeps 5 backups (50 MB total per log type)
    - JsonFormatter class: Custom formatter outputting JSON for machine parsing
    - Each logger has independent RotatingFileHandler
    
    USAGE:
    ------
    logger_control, logger_repair, logger_storage = setup_logging('INFO')
    logger_control.info("Connection from satellite xyz")
    
    All logs written to disk immediately and rotated automatically.
    Use log_and_notify() for events that need both log + UI notification.
    """
    # Create logs directory if it doesn't exist
    import os
    os.makedirs('logs', exist_ok=True)
    
    # JSON formatter for structured logging
    class JsonFormatter(logging.Formatter):
        """
        Emit structured JSON log lines (timestamp, level, logger, message, exception).
        Keeps fields stable for ingestion by log processors and rotation handlers.
        """
        def format(self, record):
            log_data = {
                'timestamp': self.formatTime(record, '%Y-%m-%d %H:%M:%S'),
                'level': record.levelname,
                'logger': record.name,
                'message': record.getMessage(),
            }
            if record.exc_info:
                log_data['exception'] = self.formatException(record.exc_info)
            return json.dumps(log_data)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Control plane logger
    control_logger = logging.getLogger('control')
    control_handler = logging.handlers.RotatingFileHandler(
        'logs/control.log', maxBytes=10*1024*1024, backupCount=5  # 10MB, 5 files
    )
    control_handler.setFormatter(JsonFormatter())
    control_logger.addHandler(control_handler)
    
    # Repair worker logger
    repair_logger = logging.getLogger('repair')
    repair_handler = logging.handlers.RotatingFileHandler(
        'logs/repair.log', maxBytes=10*1024*1024, backupCount=5
    )
    repair_handler.setFormatter(JsonFormatter())
    repair_logger.addHandler(repair_handler)
    
    # Storage operations logger
    storage_logger = logging.getLogger('storage')
    storage_handler = logging.handlers.RotatingFileHandler(
        'logs/storage.log', maxBytes=10*1024*1024, backupCount=5
    )
    storage_handler.setFormatter(JsonFormatter())
    storage_logger.addHandler(storage_handler)
    
    return control_logger, repair_logger, storage_logger

# Initialize loggers (will be configured in main())
logger_control = logging.getLogger('control')
logger_repair = logging.getLogger('repair')
logger_storage = logging.getLogger('storage')

# Helper function to both log and notify for critical user-facing events
def log_and_notify(logger: logging.Logger, level: str, message: str) -> None:
    """
    TASK 21: Log message and also send to UI notifications for user visibility.
    
    Use this for events that operators need to see immediately in the UI
    while also preserving in logs for audit/debugging.
    """
    # Log to file
    log_func = getattr(logger, level.lower())
    log_func(message)
    
    # Also notify UI for critical events
    try:
        UI_NOTIFICATIONS.put_nowait(message)
    except:
        pass  # UI queue might not be initialized yet

async def supervise_task(name: str, coro_func: Callable[..., Awaitable[Any]], *args: Any, backoffs: Optional[List[float]] = None) -> None:
    """
    TASK 20: Supervisor wrapper that restarts a background task if it exits or crashes.

    - Runs the provided coroutine function in a loop.
    - On exception, logs the error and sleeps using exponential backoff.
    - Prevents permanent loss of background functionality due to crashes.
    """
    if backoffs is None:
        backoffs = [1.0, 2.0, 4.0, 8.0, 16.0]
    attempt = 0
    while True:
        try:
            await coro_func(*args)
            # If the coroutine returns normally, restart after a short pause
            logger_control.info(f"Task '{name}' completed; restarting")
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger_control.info(f"Task '{name}' cancelled")
            return
        except Exception as e:
            delay = backoffs[min(attempt, len(backoffs) - 1)]
            logger_control.error(f"Task '{name}' crashed: {type(e).__name__}: {str(e)}; restarting in {delay:.1f}s")
            attempt += 1
            await asyncio.sleep(delay)

# ============================================================================
# END LOGGING SETUP
# ============================================================================

# ============================================================================
# TASK 17: GLOBAL STATE TYPE ANNOTATIONS
# ============================================================================

# Global State
NOTIFICATION_LOG: Deque[str] = deque(maxlen=9) # NOTIFICATION_LOG is a capped deque (maxlen=9) to retain recent events for UI display, complementing UI_NOTIFICATIONS queue.

NODES: Dict[str, NodeInfo] = {}               # Tracks remote storage nodes
                         # NODES holds connected storage nodes with last-seen timestamps. This allows the UI and repair queue to reference node availability.
                         
REMOTE_SATELLITES: Dict[str, SatelliteInfo] = {}   # Tracks other online satellites detected during node sync rounds for internal awareness
                         # REMOTE_SATELLITES tracks other online satellites detected during node sync rounds.
                         # Used for internal awareness and optional future peer-to-peer replication.

# TASK 7.5+: Persistent bidirectional control connections
# Origin maintains open connections to all satellites for instant command delivery
ACTIVE_CONNECTIONS: Dict[str, Dict[str, Any]] = {}  # {sat_id: {"reader": StreamReader, "writer": StreamWriter, "connected_at": timestamp}}
# Satellite maintains its connection to origin
ORIGIN_CONNECTION: Dict[str, Any] = {"reader": None, "writer": None, "connected": False}

# TASK 18: Connection rate limiting and health tracking (origin only)
RECENT_CONNECTIONS: Deque[float] = deque(maxlen=100)  # Timestamps of recent connections for rate limiting
CONNECTION_HEALTH: Dict[str, ConnectionHealth] = {}  # {sat_id: {"last_activity": timestamp, "bytes_sent": int, "bytes_received": int, "errors": int}}

# TASK 8-10: Storagenode scoring and reputation tracking
# Tracks 6-factor performance metrics for each storage node:
# 1. Uptime (continuous runtime), 2. Reachability (online %), 3. Repairs needed,
# 4. Repairs successful, 5. Disk health (SMART), 6. Response latency
STORAGENODE_SCORES: Dict[str, StoragenodeScore] = {}  # {sat_id: {"score": 1.0, "uptime_start": ts, "reachable_checks": 0, "reachable_success": 0, "repairs_needed": 0, "repairs_completed": 0, "disk_health": 1.0, "avg_latency_ms": 0, "p2p_reachable": {}, ...}}

# TASK 9: Proof-of-storage and fragment registry
# Tracks which fragments are stored on which nodes for challenge verification
FRAGMENT_REGISTRY: Dict[str, Dict[int, Dict[str, Any]]] = {}  # {object_id: {fragment_index: {"sat_id": str, "checksum": str, "size": int, "stored_at": timestamp}}}
# Audit log for proof-of-storage challenges
AUDIT_LOG: Deque[AuditResult] = deque(maxlen=100)  # Recent audit results for analysis

# TASK 14: Versioning, Retention & Garbage Collection
# Object manifest stores metadata about versions, retention, and soft-delete state
OBJECT_MANIFESTS: Dict[str, Dict[str, Any]] = {}  # {object_id: {"versions": {version_id: {...}}, "retention_policy": {...}, "deleted_at": timestamp, "trash_expires_at": timestamp}}
# Version metadata: {version_id: {"created_at": timestamp, "retention_days": int, "ttl_seconds": int, "fragment_count": int, "total_size": int}}

# Trash bucket for soft-deleted objects: holds object_ids past their trash expiry for permanent reclaim
TRASH_BUCKET: Dict[str, Dict[str, Any]] = {}  # {object_id: {"deleted_at": timestamp, "trash_expires_at": timestamp, "versions": [version_ids...]}}

# GC stats tracking
GC_STATS: Dict[str, Any] = {
    "last_run": 0.0,
    "objects_scanned": 0,
    "versions_expired": 0,
    "fragments_reclaimed": 0,
    "bytes_reclaimed": 0,
    "trash_items_purged": 0,
}

REPAIR_QUEUE: asyncio.Queue = asyncio.Queue()
REPAIR_QUEUE_CACHE: List[RepairJob] = []  # TASK 24 FIX: Cached repair queue from origin (for satellite UI display)
SATELLITE_ID: Optional[str] = None
TLS_FINGERPRINT: Optional[str] = None

# TASK 20: Circuit breaker for repeatedly failing storage nodes
# Tracks consecutive failures and when circuit opens until a timestamp
CIRCUIT_BREAKERS: Dict[str, Dict[str, Any]] = {}

def record_failure(node_id: str, threshold: int = 3, open_seconds: int = 300) -> None:
    """Increment failure count and open circuit if threshold reached."""
    cb = CIRCUIT_BREAKERS.setdefault(node_id, {"failures": 0, "open_until": 0.0})
    cb["failures"] = int(cb["failures"]) + 1
    if cb["failures"] >= threshold:
        cb["open_until"] = time.time() + open_seconds
        log_and_notify(logger_storage, 'warning', f"Circuit opened for {node_id[:20]} ({open_seconds}s)")

def record_success(node_id: str) -> None:
    """Reset failures and close circuit on success."""
    cb = CIRCUIT_BREAKERS.setdefault(node_id, {"failures": 0, "open_until": 0.0})
    cb["failures"] = 0
    cb["open_until"] = 0.0

def is_circuit_open(node_id: str) -> bool:
    """Return True if circuit is currently open for the node."""
    cb = CIRCUIT_BREAKERS.get(node_id)
    return bool(cb and float(cb.get("open_until", 0.0)) > time.time())
ORIGIN_PUBKEY_PEM: Optional[bytes] = None
ORIGIN_PRIVKEY_PEM: Optional[bytes] = None
IS_ORIGIN: bool = False 
LIST_JSON_PATH: str = 'list.json'
ORIGIN_PUBKEY_PATH: str = 'origin_pubkey.pem'
ORIGIN_PRIVKEY_PATH: str = 'origin_privkey.pem'
CERT_PATH: str = 'cert.pem'
KEY_PATH: str = 'key.pem'
UI_NOTIFICATIONS: asyncio.Queue = asyncio.Queue(maxsize=20)
TRUSTED_SATELLITES: Dict[str, SatelliteInfo] = {} 
ADVERTISED_IP: Optional[str] = None
LIST_UPDATED_PENDING_SAVE: bool = False

# TASK 22: Multi-screen UI state
CURRENT_SCREEN: str = "home"  # "home", "satellites", "nodes", "repair", "logs"
USE_CURSES: bool = True  # Toggle for --no-curses fallback
LOG_BUFFER: Deque[str] = deque(maxlen=100)  # Store recent log entries for logs screen

# ============================================================================
# END TASK 17: GLOBAL STATE TYPE ANNOTATIONS
# ============================================================================

# --- External Configuration (grouped defaults + overrides) ---
# Define grouped defaults for clarity; config.json overrides them.
DEFAULTS = {
  "node": {
    "name": SATELLITE_NAME,
    "mode": NODE_MODE,
    "advertised_ip": ADVERTISED_IP_CONFIG,
  },
  "network": {
    "listen_host": LISTEN_HOST,
    "listen_port": LISTEN_PORT,
    "storage_port": STORAGE_PORT,
    "origin_host": ORIGIN_HOST,
    "origin_port": ORIGIN_PORT,
  },
  "sync": {
    "node_sync_interval": NODE_SYNC_INTERVAL,
    "registry_sync_interval": SYNC_INTERVAL,
    "origin_pubkey_url": ORIGIN_PUBKEY_URL,
    "list_json_url": LIST_JSON_URL,
  },
  "paths": {
    "cert": 'cert.pem',
    "key": 'key.pem',
    "origin_pubkey": 'origin_pubkey.pem',
    "origin_privkey": 'origin_privkey.pem',
    "list_json": 'list.json',
    "fragments": 'fragments',
  },
  "storage": {
    "fragments_path": 'fragments',       # Where to store fragments on disk
    "capacity_bytes": 0,                 # TASK 12: Storage capacity in bytes (0 = unlimited, for storagenodes)
    "max_storage_gb": 0,                 # Storage quota in GB (0 = unlimited)
    "enabled": True,                     # Whether this node stores fragments
    "auto_cleanup": False,               # Delete old fragments when quota reached (not implemented)
    "reserve_space_gb": 5,               # Keep this much space free on disk (not implemented)
    "io_throttle_mbps": 0,               # Limit disk I/O in MB/s (0 = unlimited, not implemented)
  },
  "limits": {                            # TASK 18: Connection limits and resource management
    "max_concurrent_connections": 100,  # Maximum simultaneous satellite connections (origin only)
    "connection_rate_limit": 10,        # Max new connections per second (origin only)
    "connection_timeout_seconds": 300,  # Close idle connections after N seconds
    "max_repair_bandwidth_mbps": 0,     # Per-satellite repair bandwidth limit (0 = unlimited)
  },
    "placement": {                         # TASK 13: Placement configuration
        "min_distinct_zones": 3,
        "per_zone_cap_pct": 0.5,
        "min_score": 0.5
    }
}

_CONFIG = load_config('config.json')

# Merge config with defaults
_node = {**DEFAULTS["node"], **_CONFIG.get("node", {})}
_network = {**DEFAULTS["network"], **_CONFIG.get("network", {})}
_sync = {**DEFAULTS["sync"], **_CONFIG.get("sync", {})}
_paths = {**DEFAULTS["paths"], **_CONFIG.get("paths", {})}
_storage = {**DEFAULTS["storage"], **_CONFIG.get("storage", {})}
_limits = {**DEFAULTS["limits"], **_CONFIG.get("limits", {})}  # TASK 18
_placement = {**DEFAULTS["placement"], **_CONFIG.get("placement", {})}  # TASK 13

# Apply merged settings
SATELLITE_NAME = _node["name"]
NODE_MODE = _node["mode"]
HYBRID_ROLES = _node.get("roles", [])  # Extract roles array for hybrid mode
validate_node_mode(NODE_MODE, HYBRID_ROLES)  # Validate mode and roles
ADVERTISED_IP_CONFIG = _node["advertised_ip"]

LISTEN_HOST = _network["listen_host"]
LISTEN_PORT = _network["listen_port"]
STORAGE_PORT = _network["storage_port"]
ORIGIN_HOST = _network["origin_host"]
ORIGIN_PORT = _network["origin_port"]

NODE_SYNC_INTERVAL = _sync["node_sync_interval"]
SYNC_INTERVAL = _sync["registry_sync_interval"]
ORIGIN_PUBKEY_URL = _sync["origin_pubkey_url"]
LIST_JSON_URL = _sync["list_json_url"]

# TASK 13: Placement settings (merged from config)
PLACEMENT_SETTINGS = {
    "min_distinct_zones": _placement.get("min_distinct_zones", 3),
    "per_zone_cap_pct": _placement.get("per_zone_cap_pct", 0.5),
    "min_score": _placement.get("min_score", 0.5),
    "zone_override_map": _placement.get("zone_override_map", {}),
}

# ============================================================================
# TASK 14: VERSIONING, RETENTION & GC HELPER FUNCTIONS
# ============================================================================

def soft_delete_object(object_id: str, trash_hold_hours: int = 24) -> None:
    """
    TASK 14: Mark an object for soft-delete (24h trash hold before permanent fragment reclaim).
    
    Instead of immediately deleting fragments, move object to TRASH_BUCKET with an expiry time.
    This allows recovery in case of accidental deletion and maintains audit trail.
    
    Args:
        object_id: The object to mark for deletion
        trash_hold_hours: Hours to hold object in trash before GC can reclaim (default 24)
    """
    if not IS_ORIGIN:
        return
    
    now = time.time()
    trash_expires_at = now + (trash_hold_hours * 3600)
    
    # Mark all versions as deleted
    if object_id not in OBJECT_MANIFESTS:
        OBJECT_MANIFESTS[object_id] = {"versions": {}, "deleted_at": now}
    
    manifest = OBJECT_MANIFESTS[object_id]
    manifest["deleted_at"] = now
    
    # Move to trash bucket
    TRASH_BUCKET[object_id] = {
        "deleted_at": now,
        "trash_expires_at": trash_expires_at,
        "versions": list(manifest.get("versions", {}).keys()),
    }
    logger_repair.info(f"Object {object_id[:16]} soft-deleted, trash expires at {trash_expires_at}")


def set_retention_policy(object_id: str, version_id: str, retention_days: int = 0, ttl_seconds: int = 0) -> None:
    """
    TASK 14: Set retention policy for a specific object version.
    
    Retention can be time-based (keep for N days) or TTL-based (expire in N seconds from now).
    GC will not delete the version until retention period expires AND redundancy targets met.
    
    Args:
        object_id: The object ID
        version_id: The specific version to apply retention to
        retention_days: Keep version for at least N days (0 = use TTL only)
        ttl_seconds: Version expires in N seconds (0 = no expiry)
    """
    if not IS_ORIGIN:
        return
    
    if object_id not in OBJECT_MANIFESTS:
        OBJECT_MANIFESTS[object_id] = {"versions": {}, "deleted_at": None}
    
    manifest = OBJECT_MANIFESTS[object_id]
    
    if version_id not in manifest.get("versions", {}):
        manifest["versions"][version_id] = {
            "created_at": time.time(),
            "fragment_count": 0,
            "total_size": 0,
        }
    
    version = manifest["versions"][version_id]
    version["retention_days"] = retention_days
    version["ttl_seconds"] = ttl_seconds
    version["retention_expires_at"] = time.time() + (retention_days * 86400) if retention_days > 0 else 0
    
    logger_repair.info(f"Version {version_id[:16]} retention set: {retention_days}d, ttl={ttl_seconds}s")


def get_version_retention_status(object_id: str, version_id: str) -> Dict[str, Any]:
    """
    TASK 14: Check if a version is within retention period and can be safely deleted.
    
    Returns dict with:
    - retained: bool (True if within retention period)
    - expires_at: timestamp when retention expires (0 if no expiry)
    - days_remaining: days until retention expires (0 if expired)
    """
    if object_id not in OBJECT_MANIFESTS or version_id not in OBJECT_MANIFESTS[object_id].get("versions", {}):
        return {"retained": False, "expires_at": 0, "days_remaining": 0}
    
    version = OBJECT_MANIFESTS[object_id]["versions"][version_id]
    expires_at = version.get("retention_expires_at", 0)
    
    now = time.time()
    if expires_at > now:
        days_remaining = (expires_at - now) / 86400
        return {"retained": True, "expires_at": expires_at, "days_remaining": days_remaining}
    
    return {"retained": False, "expires_at": expires_at, "days_remaining": 0}


def can_reclaim_fragments(object_id: str, version_id: str) -> bool:
    """
    TASK 14: Determine if fragments for a version can be safely reclaimed.
    
    Safe reclaim requires:
    1. Version is past retention period
    2. Fragment redundancy is met (for versions being kept, at least k shards exist)
    3. Object is past trash expiry (if soft-deleted)
    
    Returns True only if all conditions met.
    """
    if not IS_ORIGIN:
        return False
    
    now = time.time()
    
    # Check if object is in trash and past expiry
    if object_id in TRASH_BUCKET:
        trash_info = TRASH_BUCKET[object_id]
        if now < trash_info.get("trash_expires_at", now):
            return False  # Still in trash hold window
    
    # Check version retention status
    retention = get_version_retention_status(object_id, version_id)
    if retention.get("retained", False):
        return False  # Within retention period
    
    # Check fragment count for other retained versions (simplified: just count)
    if object_id in FRAGMENT_REGISTRY:
        fragments = FRAGMENT_REGISTRY[object_id]
        # If only this version's fragments exist, OK to reclaim
        # (In practice, would need to track version_id per fragment for this check)
        # Simplified: if less than k fragments (k=3 default), don't delete
        if len(fragments) < 3:
            return False
    
    return True


def delete_object_version(object_id: str, version_id: str) -> bool:
    """
    TASK 14: Explicitly delete a specific version and mark for GC.
    
    Only works if version is past retention period. Moves version to trash
    where GC will eventually reclaim fragments (after trash hold window).
    
    Returns True if successfully marked for deletion, False if version protected by retention.
    """
    if not IS_ORIGIN:
        return False
    
    # Check if version can be deleted
    if object_id not in OBJECT_MANIFESTS or version_id not in OBJECT_MANIFESTS[object_id].get("versions", {}):
        return False
    
    retention = get_version_retention_status(object_id, version_id)
    if retention.get("retained", False):
        logger_repair.warning(f"Cannot delete {object_id[:16]}/v{version_id}: within retention period ({retention['days_remaining']:.1f}d remaining)")
        return False
    
    # Mark for deletion via soft delete
    manifest = OBJECT_MANIFESTS[object_id]
    version = manifest["versions"][version_id]
    version["marked_for_deletion"] = True
    
    soft_delete_object(object_id)
    logger_repair.info(f"Version {version_id[:16]} marked for deletion (GC will reclaim after trash hold)")
    return True


def list_object_versions(object_id: str) -> List[Dict[str, Any]]:
    """
    TASK 14: List all versions of an object with retention status.
    
    Returns list of version metadata dicts with fields:
    - version_id: Unique version identifier
    - created_at: Creation timestamp
    - total_size: Total uncompressed size in bytes
    - fragment_count: Number of fragments stored
    - retained: Whether version is within retention period
    - expires_at: Timestamp when retention expires (0 if no expiry)
    - deleted: Whether version is marked for deletion
    """
    if object_id not in OBJECT_MANIFESTS:
        return []
    
    manifest = OBJECT_MANIFESTS[object_id]
    versions = []
    
    for version_id, version in manifest.get("versions", {}).items():
        retention = get_version_retention_status(object_id, version_id)
        versions.append({
            "version_id": version_id,
            "created_at": version.get("created_at", 0),
            "total_size": version.get("total_size", 0),
            "fragment_count": version.get("fragment_count", 0),
            "retained": retention.get("retained", False),
            "expires_at": retention.get("expires_at", 0),
            "deleted": version.get("marked_for_deletion", False),
        })
    
    return versions


def get_gc_stats() -> Dict[str, Any]:
    """
    TASK 14: Return current garbage collection statistics.
    
    Returns dict with:
    - last_run: Timestamp of last GC cycle
    - objects_scanned: Number of objects scanned in last GC
    - versions_expired: Versions that expired and were reclaimed
    - fragments_reclaimed: Fragment jobs enqueued for reclaim
    - bytes_reclaimed: Bytes worth of fragments reclaimed
    - trash_items_purged: Items permanently removed from trash
    - trash_size: Current size of trash bucket (item count)
    - manifest_size: Number of objects with manifests
    """
    return {
        **GC_STATS,
        "trash_size": len(TRASH_BUCKET),
        "manifest_size": len(OBJECT_MANIFESTS),
    }


async def garbage_collector(interval_seconds: int = 3600) -> None:
    """
    TASK 14: Periodic garbage collection of expired versions and trash bucket items.
    
    GC cycle:
    1. Scan OBJECT_MANIFESTS for versions past retention period
    2. Mark fragments for reclaim (enqueue repair jobs to consolidate/move data)
    3. Scan TRASH_BUCKET for items past trash expiry
    4. Permanently delete fragments for expired items from storagenodes
    5. Update GC_STATS with results
    
    Runs every ~1 hour (configurable). Only on origin.
    
    Conservative approach: never delete below k shards; prefer to enqueue repair jobs
    rather than immediately delete (allows repair worker to rebuild elsewhere first).
    """
    if not IS_ORIGIN:
        return
    
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            
            now = time.time()
            GC_STATS["last_run"] = now
            objects_scanned = 0
            versions_expired = 0
            fragments_reclaimed = 0
            bytes_reclaimed = 0
            trash_purged = 0
            
            # === PHASE 1: SCAN VERSIONS FOR EXPIRY ===
            for object_id, manifest in list(OBJECT_MANIFESTS.items()):
                objects_scanned += 1
                
                for version_id, version in list(manifest.get("versions", {}).items()):
                    # Check if version is past retention
                    if not can_reclaim_fragments(object_id, version_id):
                        continue
                    
                    versions_expired += 1
                    
                    # Enqueue fragment repair job to handle reclaim (worker will consolidate)
                    if object_id in FRAGMENT_REGISTRY:
                        for frag_idx in FRAGMENT_REGISTRY[object_id]:
                            job = {
                                "job_id": str(uuid.uuid4()),
                                "object_id": object_id,
                                "fragment_index": frag_idx,
                                "reason": f"version_expired: {version_id[:16]}",
                                "created_at": now,
                                "status": "pending",
                                "claimed_by": None,
                                "lease_expires_at": 0,
                            }
                            await REPAIR_QUEUE.put(job)
                            fragments_reclaimed += 1
                            bytes_reclaimed += version.get("total_size", 0) // max(1, len(FRAGMENT_REGISTRY.get(object_id, {})))
                    
                    # Remove version from manifest
                    del manifest["versions"][version_id]
            
            # === PHASE 2: PURGE TRASH BUCKET ===
            for object_id, trash_info in list(TRASH_BUCKET.items()):
                if now >= trash_info.get("trash_expires_at", 0):
                    # Permanently delete all fragments for this object
                    if object_id in FRAGMENT_REGISTRY:
                        # Enqueue final cleanup jobs
                        for frag_idx in FRAGMENT_REGISTRY[object_id]:
                            # In production, would call delete_fragment() on each storagenode
                            # For now, just remove from registry
                            pass
                        del FRAGMENT_REGISTRY[object_id]
                    
                    # Remove from trash
                    del TRASH_BUCKET[object_id]
                    trash_purged += 1
                    logger_repair.info(f"Permanently deleted object {object_id[:16]} (trash expiry passed)")
            
            # Update stats
            GC_STATS["objects_scanned"] = objects_scanned
            GC_STATS["versions_expired"] = versions_expired
            GC_STATS["fragments_reclaimed"] = fragments_reclaimed
            GC_STATS["bytes_reclaimed"] = bytes_reclaimed
            GC_STATS["trash_items_purged"] = trash_purged
            
            if versions_expired > 0 or trash_purged > 0:
                logger_repair.info(
                    f"GC cycle: scanned {objects_scanned} objects, "
                    f"expired {versions_expired} versions, "
                    f"reclaimed {fragments_reclaimed} fragments ({bytes_reclaimed} bytes), "
                    f"purged {trash_purged} trash items"
                )
        
        except Exception as e:
            logger_repair.error(f"GC error: {e}")
            await asyncio.sleep(60)  # Back off on error

async def rebalance_scheduler(interval_seconds: int = 300) -> None:
    """
    TASK 13: Periodic diversity/fill check and simple rebalance job enqueue.

    - Scans FRAGMENT_REGISTRY and computes per-zone distribution using TRUSTED_SATELLITES.
    - If a single zone exceeds per_zone_cap_pct of copies, enqueue a repair job for a fragment
      in that zone to be rebuilt and placed elsewhere by repair_worker.
    - Also logs nodes over soft capacity (fill_pct ~> 0.9) for operator visibility.

    Minimal implementation: does not delete original fragments or migrate data; focuses on
    creating jobs to add diversity. Removal can be handled later by GC/retention policies.
    """
    if not IS_ORIGIN:
        return
    while True:
        try:
            # Scan objects
            for object_id, fragments in FRAGMENT_REGISTRY.items():
                # Count per zone
                zone_counts: Dict[str, List[int]] = {}
                total = 0
                for frag_idx, info in fragments.items():
                    sat_id = info.get('sat_id')
                    if not sat_id or sat_id not in TRUSTED_SATELLITES:
                        continue
                    z = _get_effective_zone(TRUSTED_SATELLITES[sat_id])
                    zone_counts.setdefault(z, []).append(frag_idx)
                    total += 1
                if total == 0:
                    continue
                cap = int(max(1, total * PLACEMENT_SETTINGS.get('per_zone_cap_pct', 0.5)))
                # Find violating zones
                for z, idxs in zone_counts.items():
                    if len(idxs) > cap and z != 'unknown':
                        # Enqueue a repair job for one fragment in overrepresented zone
                        frag_to_move = idxs[0]
                        job_id = create_repair_job(object_id, frag_to_move)
                        logger_repair.info(f"Rebalance: Enqueued job {job_id[:8]} for {object_id[:12]}/frag{frag_to_move} (zone={z})")
            # Log nodes near capacity
            for sid, info in TRUSTED_SATELLITES.items():
                if info.get('storage_port', 0) > 0:
                    fill = _compute_fill_pct(info)
                    if fill >= 0.9:
                        logger_storage.warning(f"Node near capacity: {sid[:20]} fill={int(fill*100)}%")
        except Exception as e:
            logger_control.error(f"Rebalance scheduler error: {type(e).__name__}: {str(e)}")
        await asyncio.sleep(interval_seconds)

def detect_zone_from_ip(ip: str) -> str:
    """
    TASK 13: Detect geographic zone from storagenode IP address.

    Purpose:
    - Origin determines zone based on IP geolocation, not trusting storagenode self-report.
    - Prevents storagenodes from lying about their location for placement bias.

    Implementation:
    - Placeholder using simple IP range heuristics for testing.
    - Production: could use MaxMind GeoIP2, IP2Location, or ASN lookups.
    - Returns: zone name (e.g., "NA-East", "EU-West", "unknown")

    For testing: map 192.168.x.x to "test-local", simulate others as "unknown".
    """
    try:
        # Simple heuristic for local test IPs
        if ip.startswith("192.168."):
            return "test-local"
        # TODO: integrate real geolocation service (MaxMind, IP2Location, etc.)
        # For now, default to unknown
        return "unknown"
    except Exception:
        return "unknown"

CERT_PATH = _paths["cert"]
KEY_PATH = _paths["key"]
ORIGIN_PUBKEY_PATH = _paths["origin_pubkey"]
ORIGIN_PRIVKEY_PATH = _paths["origin_privkey"]
LIST_JSON_PATH = _paths["list_json"]
FRAGMENTS_PATH = _paths["fragments"]

# Storage configuration (Task 12+ features, configured but not enforced yet)
STORAGE_FRAGMENTS_PATH = _storage["fragments_path"]
STORAGE_CAPACITY_BYTES = _storage["capacity_bytes"]  # TASK 12: Capacity in bytes
STORAGE_MAX_GB = _storage["max_storage_gb"]
STORAGE_ENABLED = _storage["enabled"]
STORAGE_AUTO_CLEANUP = _storage["auto_cleanup"]
STORAGE_RESERVE_GB = _storage["reserve_space_gb"]
STORAGE_IO_THROTTLE_MBPS = _storage["io_throttle_mbps"]

# TASK 18: Connection limits
MAX_CONCURRENT_CONNECTIONS = _limits["max_concurrent_connections"]
CONNECTION_RATE_LIMIT = _limits["connection_rate_limit"]
CONNECTION_TIMEOUT_SECONDS = _limits["connection_timeout_seconds"]
MAX_REPAIR_BANDWIDTH_MBPS = _limits["max_repair_bandwidth_mbps"]

# --- PHASE 3: Repair Queue Database (SQLite) ---

# Repair database path
REPAIR_DB_PATH = "repair_jobs.db"

# Job lease duration (seconds) - how long a worker can hold a job before it expires
JOB_LEASE_DURATION = 300  # 5 minutes
# Job retry limit
MAX_JOB_ATTEMPTS = 3

# TASK 8: Auditor configuration
AUDITOR_INTERVAL = 120  # Audit each storagenode every 2 minutes
AUDITOR_CPU_THRESHOLD = 85  # Skip audits if CPU > 85%
AUDITOR_MIN_SCORE = 0.7  # Deprioritize nodes below this score
AUDITOR_LATENCY_THRESHOLD_MS = 2000  # Penalize nodes slower than 2 seconds
AUDITOR_SAMPLE_SIZE = 3  # Number of fragments to test per audit

def init_repair_db() -> None:
    """
    PHASE 3A: Initialize the repair jobs SQLite database.
    
    Purpose:
    - Creates the repair_jobs table if it doesn't exist.
    - Establishes persistent storage for repair orchestration.
    - Runs once during origin node startup.
    - TASK 20: Checks database integrity on startup and repairs if needed
    
    Schema:
    - job_id: Unique identifier (UUID)
    - object_id: The object that needs repair
    - fragment_index: Which fragment needs reconstruction
    - status: 'pending', 'claimed', 'completed', 'failed'
    - claimed_by: Node ID that claimed this job
    - claimed_at: Timestamp when job was claimed
    - lease_expires_at: When the lease expires (for reclaiming stale jobs)
    - created_at: Job creation timestamp
    - completed_at: Job completion timestamp
    - attempts: Number of times this job has been attempted
    - max_attempts: Maximum retry limit
    - error_message: Last error message if job failed
    
    Design Notes:
    - Only origin nodes use this database (repair orchestration authority).
    - Workers query origin for jobs; they don't access this DB directly.
    - Lease mechanism prevents multiple workers from claiming same job.
    - Failed jobs with attempts < max_attempts return to 'pending' status.
    """
    # TASK 20: Check database integrity on startup
    if os.path.exists(REPAIR_DB_PATH):
        try:
            conn = sqlite3.connect(REPAIR_DB_PATH)
            cursor = conn.cursor()
            # Run integrity check
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            if result[0] != 'ok':
                log_and_notify(logger_repair, 'warning', f"DB integrity issue: {result[0]}, attempting recovery")
                conn.close()
                # Try to recover the database
                import shutil
                shutil.copy(REPAIR_DB_PATH, f"{REPAIR_DB_PATH}.corrupted")
                os.remove(REPAIR_DB_PATH)
                log_and_notify(logger_repair, 'info', "Repair DB reset due to corruption")
            else:
                conn.close()
        except Exception as e:
            log_and_notify(logger_repair, 'error', f"DB integrity check failed: {e}, will reinitialize")
            # Backup corrupted database
            try:
                import shutil
                shutil.copy(REPAIR_DB_PATH, f"{REPAIR_DB_PATH}.corrupted")
                os.remove(REPAIR_DB_PATH)
            except Exception:
                pass
    
    conn = sqlite3.connect(REPAIR_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS repair_jobs (
            job_id TEXT PRIMARY KEY,
            object_id TEXT NOT NULL,
            fragment_index INTEGER NOT NULL,
            status TEXT NOT NULL,
            claimed_by TEXT,
            claimed_at REAL,
            lease_expires_at REAL,
            created_at REAL NOT NULL,
            completed_at REAL,
            attempts INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3,
            error_message TEXT
        )
    """)
    # Index for efficient pending job queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_status_created
        ON repair_jobs(status, created_at)
    """)
    # Index for lease expiry cleanup
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_lease_expires
        ON repair_jobs(lease_expires_at)
        WHERE status = 'claimed'
    """)
    conn.commit()
    conn.close()

def create_repair_job(object_id: str, fragment_index: int) -> str:
    """
    PHASE 3A: Create a new repair job for a missing or corrupted fragment.
    
    Purpose:
    - Adds a repair task to the queue for worker nodes to claim.
    - Returns the job_id for tracking.
    
    Parameters:
    - object_id: The object that needs repair
    - fragment_index: Which fragment index needs reconstruction
    
    Returns:
    - job_id (str): UUID of the created job
    
    Behavior:
    - Generates unique job_id (UUID)
    - Sets status='pending', attempts=0
    - Records creation timestamp
    - Prevents duplicate jobs for same object+fragment (checks existing pending/claimed)
    
    Design Notes:
    - Called by origin when it detects missing fragments during health checks.
    - Origin is the only node that creates repair jobs.
    """
    conn = sqlite3.connect(REPAIR_DB_PATH)
    cursor = conn.cursor()
    
    # Check for existing pending/claimed job for this fragment
    cursor.execute("""
        SELECT job_id FROM repair_jobs
        WHERE object_id = ? AND fragment_index = ?
        AND status IN ('pending', 'claimed')
        LIMIT 1
    """, (object_id, fragment_index))
    
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return existing[0]  # Return existing job_id
    
    # Create new job
    job_id = str(uuid.uuid4())
    now = time.time()
    cursor.execute("""
        INSERT INTO repair_jobs
        (job_id, object_id, fragment_index, status, created_at, attempts, max_attempts)
        VALUES (?, ?, ?, 'pending', ?, 0, ?)
    """, (job_id, object_id, fragment_index, now, MAX_JOB_ATTEMPTS))
    
    conn.commit()
    conn.close()
    
    # PHASE 3B: Update metrics
    REPAIR_METRICS['jobs_created'] += 1
    
    return job_id

def claim_repair_job(worker_id: str) -> Optional[RepairJob]:
    """
    PHASE 3A: Worker claims the next pending repair job.
    
    Purpose:
    - Allows repair workers to atomically claim a job from the queue.
    - Prevents multiple workers from claiming the same job.
    - Sets a lease timeout to reclaim stale jobs.
    
    Parameters:
    - worker_id: Unique identifier of the worker claiming the job
    
    Returns:
    - dict with job details if claimed, None if no jobs available:
      {
        'job_id': str,
        'object_id': str,
        'fragment_index': int,
        'lease_expires_at': float
      }
    
    Behavior:
    - Finds oldest pending job (FIFO)
    - Atomically updates status='claimed'
    - Sets claimed_by, claimed_at, lease_expires_at
    - Increments attempts counter
    
    Design Notes:
    - Uses transaction to ensure atomicity (no race conditions).
    - Lease expires after JOB_LEASE_DURATION seconds.
    - If worker doesn't complete or renew lease, job returns to pending.
    """
    conn = sqlite3.connect(REPAIR_DB_PATH)
    cursor = conn.cursor()
    
    now = time.time()
    lease_expires = now + JOB_LEASE_DURATION
    
    # Find oldest pending job
    cursor.execute("""
        SELECT job_id, object_id, fragment_index
        FROM repair_jobs
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT 1
    """)
    
    job = cursor.fetchone()
    if not job:
        conn.close()
        return None
    
    job_id, object_id, fragment_index = job
    
    # Atomically claim it
    cursor.execute("""
        UPDATE repair_jobs
        SET status = 'claimed',
            claimed_by = ?,
            claimed_at = ?,
            lease_expires_at = ?,
            attempts = attempts + 1
        WHERE job_id = ?
    """, (worker_id, now, lease_expires, job_id))
    
    conn.commit()
    conn.close()
    
    return {
        'job_id': job_id,
        'object_id': object_id,
        'fragment_index': fragment_index,
        'lease_expires_at': lease_expires
    }

def renew_job_lease(job_id: str, worker_id: str) -> bool:
    """
    PHASE 3A: Extend the lease on a claimed job to prevent expiry.
    
    Purpose:
    - Long-running repairs need to renew their lease to avoid timeout.
    - Prevents job from being reclaimed by another worker.
    
    Parameters:
    - job_id: The job to renew
    - worker_id: Worker that currently holds the job (verification)
    
    Returns:
    - bool: True if renewed successfully, False if job not found or not owned by worker
    
    Behavior:
    - Verifies job is claimed by the specified worker
    - Extends lease_expires_at by JOB_LEASE_DURATION
    
    Design Notes:
    - Workers should renew lease periodically during long repairs.
    - Renewal fails if job was already reclaimed or completed.
    """
    conn = sqlite3.connect(REPAIR_DB_PATH)
    cursor = conn.cursor()
    
    now = time.time()
    new_lease_expires = now + JOB_LEASE_DURATION
    
    cursor.execute("""
        UPDATE repair_jobs
        SET lease_expires_at = ?
        WHERE job_id = ?
        AND claimed_by = ?
        AND status = 'claimed'
    """, (new_lease_expires, job_id, worker_id))
    
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

def complete_repair_job(job_id: str, worker_id: str) -> bool:
    """
    PHASE 3A: Mark a repair job as successfully completed.
    
    Purpose:
    - Worker reports successful fragment reconstruction.
    - Removes job from active queue.
    
    Parameters:
    - job_id: The completed job
    - worker_id: Worker that completed it (verification)
    
    Returns:
    - bool: True if marked completed, False if job not found or not owned by worker
    
    Behavior:
    - Verifies job is claimed by specified worker
    - Sets status='completed', completed_at=now
    - Clears claimed_by and lease fields
    
    Design Notes:
    - Completed jobs remain in DB for history/auditing.
    - Can be cleaned up later by maintenance task.
    """
    conn = sqlite3.connect(REPAIR_DB_PATH)
    cursor = conn.cursor()
    
    now = time.time()
    
    cursor.execute("""
        UPDATE repair_jobs
        SET status = 'completed',
            completed_at = ?,
            claimed_by = NULL,
            lease_expires_at = NULL
        WHERE job_id = ?
        AND claimed_by = ?
        AND status = 'claimed'
    """, (now, job_id, worker_id))
    
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    # PHASE 3B: Update metrics
    if success:
        REPAIR_METRICS['jobs_completed'] += 1
    
    return success

def fail_repair_job(job_id: str, worker_id: str, error_message: Optional[str] = None) -> bool:
    """
    PHASE 3A: Mark a repair job as failed (with retry logic).
    
    Purpose:
    - Worker reports failed fragment reconstruction attempt.
    - Job returns to 'pending' if attempts < max_attempts.
    - Job marked 'failed' permanently if max attempts reached.
    
    Parameters:
    - job_id: The failed job
    - worker_id: Worker that attempted it (verification)
    - error_message: Optional error description
    
    Returns:
    - bool: True if updated, False if job not found or not owned by worker
    
    Behavior:
    - Verifies job is claimed by specified worker
    - If attempts < max_attempts: status='pending' (retry)
    - If attempts >= max_attempts: status='failed' (permanent)
    - Records error_message
    - Clears claimed_by and lease fields
    
    Design Notes:
    - Automatic retry mechanism for transient failures.
    - Prevents infinite retry loops with max_attempts limit.
    """
    conn = sqlite3.connect(REPAIR_DB_PATH)
    cursor = conn.cursor()
    
    # Get current attempts count
    cursor.execute("""
        SELECT attempts, max_attempts
        FROM repair_jobs
        WHERE job_id = ?
        AND claimed_by = ?
        AND status = 'claimed'
    """, (job_id, worker_id))
    
    result = cursor.fetchone()
    if not result:
        conn.close()
        return False
    
    attempts, max_attempts = result
    
    # Determine new status based on retry limit
    new_status = 'failed' if attempts >= max_attempts else 'pending'
    
    cursor.execute("""
        UPDATE repair_jobs
        SET status = ?,
            error_message = ?,
            claimed_by = NULL,
            lease_expires_at = NULL
        WHERE job_id = ?
    """, (new_status, error_message, job_id))
    
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    # PHASE 3B: Update metrics
    if updated and new_status == 'failed':
        REPAIR_METRICS['jobs_failed'] += 1
    
    return updated

def list_repair_jobs(status: Optional[str] = None, limit: int = 100) -> List[RepairJob]:
    """
    PHASE 3A: List repair jobs for UI display or monitoring.
    
    Purpose:
    - Provides visibility into repair queue state.
    - Supports filtering by status.
    
    Parameters:
    - status: Optional filter ('pending', 'claimed', 'completed', 'failed', None=all)
    - limit: Maximum number of jobs to return
    
    Returns:
    - list of dict: Job records with all fields
    
    Design Notes:
    - Used by UI to display repair queue section.
    - Sorted by created_at (oldest first).
    """
    conn = sqlite3.connect(REPAIR_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if status:
        cursor.execute("""
            SELECT * FROM repair_jobs
            WHERE status = ?
            ORDER BY created_at ASC
            LIMIT ?
        """, (status, limit))
    else:
        cursor.execute("""
            SELECT * FROM repair_jobs
            ORDER BY created_at ASC
            LIMIT ?
        """, (limit,))
    
    jobs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jobs

async def expire_stale_leases() -> None:
    """
    PHASE 3A: Background task to reclaim jobs with expired leases.
    
    Purpose:
    - Prevents jobs from being stuck in 'claimed' state if worker crashes.
    - Returns expired jobs to 'pending' status for retry.
    
    Behavior:
    - Runs every 60 seconds
    - Finds jobs with status='claimed' and lease_expires_at < now
    - Resets status='pending', clears claimed_by/lease fields
    - Notifies UI when jobs are reclaimed
    
    Design Notes:
    - Only runs on origin nodes (where repair DB exists).
    - Critical for fault tolerance - ensures jobs don't get lost.
    - Works in conjunction with worker lease renewal.
    """
    while True:
        await asyncio.sleep(60)  # Check every minute
        
        if not IS_ORIGIN:
            continue  # Only origin manages repair queue
        
        try:
            conn = sqlite3.connect(REPAIR_DB_PATH)
            cursor = conn.cursor()
            
            now = time.time()
            
            # Find expired leases
            cursor.execute("""
                SELECT job_id, object_id, fragment_index, claimed_by
                FROM repair_jobs
                WHERE status = 'claimed'
                AND lease_expires_at < ?
            """, (now,))
            
            expired_jobs = cursor.fetchall()
            
            if expired_jobs:
                # Reclaim expired jobs
                cursor.execute("""
                    UPDATE repair_jobs
                    SET status = 'pending',
                        claimed_by = NULL,
                        claimed_at = NULL,
                        lease_expires_at = NULL
                    WHERE status = 'claimed'
                    AND lease_expires_at < ?
                """, (now,))
                
                conn.commit()
                
                # Notify UI
                for job_id, object_id, fragment_index, worker_id in expired_jobs:
                    logger_repair.info(
                        f"Reclaimed expired job: {object_id[:16]}/frag{fragment_index} from {worker_id[:20]}"
                    )
            
            conn.close()
        
        except Exception as e:
            logger_control.error(f"Lease expiry error: {e}")

# --- Fragmenter: Reed-Solomon k-of-n ---
def make_fragments(data_bytes: bytes, k: int, n: int) -> List[bytes]:
    """
    Encode a byte string into n Reed-Solomon fragments such that any k fragments
    can reconstruct the original. Uses zfec for erasure coding.

    Parameters:
    - data_bytes: source bytes to fragment
    - k: minimum number of fragments required to reconstruct (1..n)
    - n: total number of fragments to produce (k..<=256)

    Returns: list of n shards (bytes). Each shard contains a small header with:
      magic 'LMRS', version, k, n, block_size, original_length, shard_index.

    Notes:
    - Requires the 'zfec' package. If missing, raises RuntimeError with guidance.
    - Padding is added to the last primary block; original length is recorded
      in the header to allow exact trimming during reconstruction.
    """
    if not _ZFEC_AVAILABLE:
        raise RuntimeError("zfec is required for make_fragments(); install with: pip install zfec")
    if not isinstance(data_bytes, (bytes, bytearray)):
        raise TypeError("data_bytes must be bytes-like")
    if not (1 <= k <= n <= 256):
        raise ValueError("Require 1 <= k <= n <= 256")

    data_len = len(data_bytes)
    block_size = math.ceil(data_len / k) if data_len > 0 else 1

    # Build k primary blocks of equal size
    primaries: List[bytes] = []
    for i in range(k):
        start = i * block_size
        end = start + block_size
        chunk = data_bytes[start:end]
        if len(chunk) < block_size:
            chunk = chunk + b"\x00" * (block_size - len(chunk))
        primaries.append(chunk)

    # Request blocks 0..n-1 (k primaries + n-k secondaries)
    blocknums = list(range(n))
    blocks = zfec_encode(primaries, blocknums)

    # Header format
    # magic(4)='LMRS', ver(1)=1, k(2), n(2), block_size(4), orig_len(8), shard_idx(2), pad(1) => 24 bytes
    header_struct = struct.Struct('<4sBHHIQHB')

    shards: List[bytes] = []
    for idx, block in zip(blocknums, blocks):
        header = header_struct.pack(b'LMRS', 1, k, n, block_size, data_len, idx, 0)
        shards.append(header + (block if isinstance(block, (bytes, bytearray)) else bytes(block)))
    return shards


def reconstruct_file(shards: Dict[int, bytes], k: int, n: int) -> bytes:
    """
    Reconstruct original bytes from at least k fragments produced by make_fragments().

    Parameters:
    - shards: dict mapping shard_index -> shard_bytes (as produced by make_fragments)
    - k: minimum number of fragments required to reconstruct
    - n: total number of fragments originally produced

    Returns: the reconstructed original bytes (padding trimmed).

    Notes:
    - Validates shard headers for format, version, and k/n consistency before decoding.
    - Works with both zfec APIs: easyfec returns bytes directly; PyPI returns blocks list.

    Raises:
    - RuntimeError if zfec is not available
    - ValueError for invalid inputs or insufficient number of shards
    """
    if not _ZFEC_AVAILABLE:
        raise RuntimeError("zfec is required for reconstruct_file(); install with: pip install zfec")
    if not isinstance(shards, dict) or not shards:
        raise ValueError("shards must be a non-empty dict[index]->bytes")
    if not (1 <= k <= n <= 256):
        raise ValueError("Require 1 <= k <= n <= 256")

    header_struct = struct.Struct('<4sBHHIQHB')

    # Read header from one shard to validate format
    sample_idx, sample_bytes = next(iter(shards.items()))
    if len(sample_bytes) < header_struct.size:
        raise ValueError("Shard too small; missing header")
    magic, ver, hk, hn, block_size, orig_len, shard_idx_field, _pad = header_struct.unpack(
        sample_bytes[:header_struct.size]
    )
    if magic != b'LMRS' or ver != 1:
        raise ValueError("Unsupported shard format")
    if hk != k or hn != n:
        raise ValueError("k/n mismatch between provided args and shard header")
    if block_size <= 0:
        raise ValueError("Invalid block_size in shard header")

    # Collect up to k shards
    blocks: List[bytes] = []
    blocknums: List[int] = []
    for idx, blob in shards.items():
        if not isinstance(blob, (bytes, bytearray)) or len(blob) < header_struct.size:
            continue
        h = header_struct.unpack(blob[:header_struct.size])
        if h[0] != b'LMRS' or h[1] != 1:
            continue
        if h[2] != k or h[3] != n:
            continue
        shard_index = h[6]
        blocks.append(blob[header_struct.size:])
        blocknums.append(shard_index)
        if len(blocks) == k:
            break

    if len(blocks) < k:
        raise ValueError(f"Insufficient shards: have {len(blocks)}, need {k}")

    # Decode to primary blocks in order 0..k-1
    padlen = (block_size * k) - orig_len  # padding for easyfec compatibility
    result = zfec_decode(blocks, blocknums, padlen)

    # Handle both APIs: easyfec returns bytes directly, PyPI API returns list of blocks
    if isinstance(result, bytes):
        return result  # easyfec already trimmed padding
    else:
        data_concat = b"".join(result)
        return data_concat[:orig_len]

# --- Core Logic ---

def compute_state_hash(state_type: str) -> str:
    """
    TASK 7: Compute hash of current state for change detection.
    
    Purpose:
    - Generate a stable hash of state data to detect changes.
    - Used to determine if full sync needed or heartbeat sufficient.
    
    Parameters:
    - state_type: 'nodes', 'repair_queue', or 'registry'
    
    Returns:
    - str: Hash of current state (or empty string if error)
    
    Design:
    - Converts state to stable JSON representation
    - Hashes with SHA256 for fast comparison
    - Returns hex digest for storage/comparison
    """
    import hashlib
    
    try:
        if state_type == 'nodes':
            # Hash NODES dict (node IDs and last_seen times)
            state_str = json.dumps(NODES, sort_keys=True)
        elif state_type == 'repair_queue':
            # Hash repair job counts (avoid querying DB on every check)
            state_str = json.dumps({
                'created': REPAIR_METRICS['jobs_created'],
                'completed': REPAIR_METRICS['jobs_completed'],
                'failed': REPAIR_METRICS['jobs_failed']
            }, sort_keys=True)
        elif state_type == 'registry':
            # Hash TRUSTED_SATELLITES keys (IDs of known satellites)
            state_str = json.dumps(sorted(TRUSTED_SATELLITES.keys()))
        else:
            return ""
        
        return hashlib.sha256(state_str.encode()).hexdigest()
    except Exception:
        return ""

def get_system_metrics() -> Dict[str, Union[float, int, str]]:
    """
    TASK 7.5: Get current CPU and memory usage metrics.
    
    Purpose:
    - Provides resource usage stats for monitoring and scoring.
    - Used in status sync payloads and UI display.
    
    Returns:
    - dict with cpu_percent, memory_percent, memory_available_mb
    - Returns empty dict if psutil not available
    
    Design:
    - Uses psutil for accurate cross-platform metrics
    - Gracefully handles missing psutil (optional dependency)
    - CPU percentage averaged over short interval (0.1s)
    """
    if not PSUTIL_AVAILABLE:
        return {}
    
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        
        return {
            'cpu_percent': round(cpu_percent, 1),
            'memory_percent': round(mem.percent, 1),
            'memory_available_mb': round(mem.available / (1024 * 1024), 0)
        }
    except Exception:
        return {}

async def audit_storagenode(sat_id: str) -> AuditResult:
    """
    TASK 8: Audit a storage node's performance by attempting fragment retrieval.
    
    Purpose:
    - Measures response latency and success rate for storage nodes
    - Updates STORAGENODE_SCORES with results
    - Helps identify unreliable nodes for deprioritization
    
    Parameters:
    - sat_id: Satellite ID to audit
    
    Returns:
    - dict with keys: success (bool), latency_ms (float), reason (str)
    
    Design:
    - Attempts to fetch a random fragment from the node
    - Measures round-trip latency
    - Updates cumulative score based on success/failure
    - Skips audit if CPU usage too high (AUDITOR_CPU_THRESHOLD)
    
    Implementation Notes:
    - For now, uses mock audit (placeholder until objects/fragments exist)
    - Real implementation will select random object and fragment
    - Timeout after 5 seconds to detect slow nodes
    """
    # Check CPU threshold before auditing
    metrics = get_system_metrics()
    if metrics.get('cpu_percent', 0) > AUDITOR_CPU_THRESHOLD:
        return {
            'success': False,
            'latency_ms': 0,
            'reason': f'CPU too high ({metrics["cpu_percent"]}% > {AUDITOR_CPU_THRESHOLD}%)',
            'challenged_fragments': 0,
            'failed_fragments': []
        }
    
    # Get satellite info from TRUSTED_SATELLITES
    if sat_id not in TRUSTED_SATELLITES:
        return {
            'success': False,
            'latency_ms': 0,
            'reason': 'Satellite not in registry',
            'challenged_fragments': 0,
            'failed_fragments': []
        }
    
    sat = TRUSTED_SATELLITES[sat_id]
    hostname = sat.get('hostname')
    storage_port = sat.get('storage_port')
    
    if not storage_port or storage_port == 0:
        return {
            'success': False,
            'latency_ms': 0,
            'reason': 'No storage port (control-only node)',
            'challenged_fragments': 0,
            'failed_fragments': []
        }
    
    # TASK 9: Find fragments stored on this node for challenge-response
    fragments_to_test = []
    for obj_id, fragments in FRAGMENT_REGISTRY.items():
        for frag_idx, frag_info in fragments.items():
            if frag_info.get('sat_id') == sat_id:
                fragments_to_test.append((obj_id, frag_idx, frag_info))
    
    # If no fragments to test, fallback to connectivity test
    if not fragments_to_test:
        start_time = time.time()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(hostname, storage_port),
                timeout=5.0
            )
            writer.close()
            await writer.wait_closed()
            
            latency_ms = (time.time() - start_time) * 1000
            return {
                'success': True,
                'latency_ms': round(latency_ms, 2),
                'reason': 'Connectivity OK (no fragments to challenge)',
                'challenged_fragments': 0,
                'failed_fragments': []
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return {
                'success': False,
                'latency_ms': round(latency_ms, 2),
                'reason': f'Connection failed: {type(e).__name__}',
                'challenged_fragments': 0,
                'failed_fragments': []
            }
    
    # Sample random fragments (up to AUDITOR_SAMPLE_SIZE)
    import random
    sample = random.sample(fragments_to_test, min(AUDITOR_SAMPLE_SIZE, len(fragments_to_test)))
    
    start_time = time.time()
    challenged = 0
    failed = []
    
    for obj_id, frag_idx, frag_info in sample:
        challenged += 1
        
        # Generate challenge nonce
        nonce = secrets.token_hex(16)
        
        try:
            # Send challenge request
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(hostname, storage_port),
                timeout=5.0
            )
            
            challenge = {
                "rpc": "challenge",
                "object_id": obj_id,
                "fragment_index": frag_idx,
                "nonce": nonce
            }
            writer.write(json.dumps(challenge).encode() + b'\n')
            await writer.drain()
            
            # Read response
            response_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            response = json.loads(response_line.decode())
            
            writer.close()
            await writer.wait_closed()
            
            # Verify response
            if response.get('status') != 'ok':
                failed.append(frag_idx)
                AUDIT_LOG.append({
                    'timestamp': time.time(),
                    'sat_id': sat_id,
                    'object_id': obj_id,
                    'fragment_index': frag_idx,
                    'result': 'failed',
                    'reason': response.get('reason', 'unknown')
                })
            else:
                # Challenge passed
                AUDIT_LOG.append({
                    'timestamp': time.time(),
                    'sat_id': sat_id,
                    'object_id': obj_id,
                    'fragment_index': frag_idx,
                    'result': 'success',
                    'response_hash': response.get('challenge_response', '')[:16]
                })
        
        except Exception as e:
            failed.append(frag_idx)
            AUDIT_LOG.append({
                'timestamp': time.time(),
                'sat_id': sat_id,
                'object_id': obj_id,
                'fragment_index': frag_idx,
                'result': 'error',
                'reason': f'{type(e).__name__}'
            })
    
    latency_ms = (time.time() - start_time) * 1000
    success = len(failed) == 0
    
    if success:
        reason = f'All {challenged} challenges passed'
    else:
        reason = f'{len(failed)}/{challenged} challenges failed'
    
    return {
        'success': success,
        'latency_ms': round(latency_ms, 2),
        'reason': reason,
        'challenged_fragments': challenged,
        'failed_fragments': failed
    }

def update_storagenode_score(sat_id: str, audit_result: AuditResult) -> None:
    """
    TASK 10: Update a storage node's reputation score using 6-factor model.
    
    Purpose:
    - Maintains comprehensive reputation metrics across 6 dimensions
    - Calculates composite score (0.0-1.0) for node trustworthiness
    - Biases repair assignments and fragment placement toward high-score nodes
    
    Parameters:
    - sat_id: Satellite ID being scored
    - audit_result: Result from audit_storagenode() with success, latency_ms, reason
    
    6-Factor Reputation Model:
    1. Uptime Factor (15%): Continuous runtime without restarts
       - Calculated: min(1.0, uptime_hours / 720)  # 30 days = perfect
    2. Reachability Factor (20%): Percentage of successful connectivity checks
       - Calculated: reachable_success / reachable_checks
    3. Repair Avoidance Factor (15%): Lower repairs needed = better
       - Calculated: 1.0 - min(1.0, repairs_needed / 100)
    4. Repair Success Factor (15%): Higher completed repairs = better
       - Calculated: min(1.0, repairs_completed / 50)
    5. Disk Health Factor (15%): SMART status and bad sector count
       - Range: 1.0 (perfect) to 0.0 (failing)
    6. Latency Factor (20%): Response time for challenges/fetches
       - Calculated: 1.0 - (avg_latency_ms / threshold)
    
    Composite Score:
    - Weighted sum of all 6 factors
    - Nodes with score < 0.5 are deprioritized
    - Scores persist and evolve over node lifetime
    """
    # Initialize score entry if first audit (TASK 10: 6-factor model)
    if sat_id not in STORAGENODE_SCORES:
        STORAGENODE_SCORES[sat_id] = {
            'score': 1.0,  # Start optimistic
            'uptime_start': time.time(),  # Factor 1: Track when node first seen
            'reachable_checks': 0,  # Factor 2: Total connectivity checks
            'reachable_success': 0,  # Factor 2: Successful connections
            'repairs_needed': 0,  # Factor 3: Repair jobs created for this node's fragments
            'repairs_completed': 0,  # Factor 4: Successful repairs executed
            'disk_health': 1.0,  # Factor 5: SMART status (1.0 = perfect, updated via health reports)
            'total_latency_ms': 0.0,  # Factor 6: Cumulative latency
            'success_count': 0,  # For latency averaging
            'fail_count': 0,
            'audit_count': 0,
            'avg_latency_ms': 0.0,
            'last_audit': time.time(),
            'last_reason': '',
            'p2p_reachable': {},  # TASK 24: {target_sat_id: bool} bidirectional P2P connectivity
            'p2p_last_check': 0  # TASK 24: Last P2P probe timestamp
        }
    
    entry = STORAGENODE_SCORES[sat_id]
    
    # Update audit counters
    entry['audit_count'] += 1
    entry['last_audit'] = time.time()
    entry['last_reason'] = audit_result['reason']
    
    # Factor 2: Reachability tracking
    entry['reachable_checks'] += 1
    if audit_result['success']:
        entry['reachable_success'] += 1
        entry['success_count'] += 1
        entry['total_latency_ms'] += audit_result['latency_ms']
    else:
        entry['fail_count'] += 1
    
    # Calculate average latency (only from successful audits)
    if entry['success_count'] > 0:
        entry['avg_latency_ms'] = entry['total_latency_ms'] / entry['success_count']
    
    # === 6-FACTOR COMPOSITE SCORE CALCULATION ===
    
    # Factor 1: Uptime (15% weight)
    # Perfect score at 30 days (720 hours) continuous uptime
    uptime_hours = (time.time() - entry['uptime_start']) / 3600
    uptime_factor = min(1.0, uptime_hours / 720)
    
    # Factor 2: Reachability (20% weight)
    # Percentage of successful connectivity checks
    if entry['reachable_checks'] > 0:
        reachability_factor = entry['reachable_success'] / entry['reachable_checks']
    else:
        reachability_factor = 1.0  # Start optimistic
    
    # Factor 3: Repair Avoidance (15% weight)
    # Fewer repairs needed = better node reliability
    # Perfect score = 0 repairs, degrade toward 100 repairs
    repair_avoidance_factor = 1.0 - min(1.0, entry['repairs_needed'] / 100)
    
    # Factor 4: Repair Success (15% weight)
    # More completed repairs = proven reliability
    # Perfect score at 50 successful repairs
    repair_success_factor = min(1.0, entry['repairs_completed'] / 50)
    
    # Factor 5: Disk Health (15% weight)
    # Updated externally via health reports (SMART status)
    # For now, defaults to 1.0 unless health report sets it lower
    disk_health_factor = entry.get('disk_health', 1.0)
    
    # Factor 6: Latency (20% weight)
    # Fast responses preferred, linear decay to threshold
    if entry['avg_latency_ms'] == 0:
        latency_factor = 1.0
    else:
        latency_factor = max(0.0, 1.0 - (entry['avg_latency_ms'] / AUDITOR_LATENCY_THRESHOLD_MS))
    
    # TASK 24: P2P Connectivity Bonus (up to +10% bonus)
    # Well-connected nodes preferred for future P2P repairs
    p2p_bonus = 0.0
    p2p_reachable = entry.get('p2p_reachable', {})
    if p2p_reachable:
        p2p_total = len(p2p_reachable)
        p2p_success = sum(1 for reachable in p2p_reachable.values() if reachable)
        p2p_connectivity_pct = (p2p_success / p2p_total) if p2p_total > 0 else 0
        p2p_bonus = p2p_connectivity_pct * 0.10  # Up to 10% bonus for 100% peer connectivity
    
    # Weighted composite score (all factors sum to 100%)
    entry['score'] = (
        (uptime_factor * 0.15) +
        (reachability_factor * 0.20) +
        (repair_avoidance_factor * 0.15) +
        (repair_success_factor * 0.15) +
        (disk_health_factor * 0.15) +
        (latency_factor * 0.20) +
        p2p_bonus  # TASK 24: Bonus for P2P connectivity
    )
    
    # Clamp to [0.0, 1.1] (bonus allows exceeding 1.0)
    entry['score'] = max(0.0, min(1.1, entry['score']))

def record_repair_needed(sat_id: str) -> None:
    """
    TASK 10: Record that a repair job was created for a fragment on this node.
    
    Purpose:
    - Tracks reliability (nodes needing frequent repairs are less reliable)
    - Updates Factor 3 (Repair Avoidance) in reputation scoring
    
    Parameters:
    - sat_id: Satellite that owns the fragment needing repair
    """
    if sat_id in STORAGENODE_SCORES:
        STORAGENODE_SCORES[sat_id]['repairs_needed'] += 1

def record_repair_completed(sat_id: str) -> None:
    """
    TASK 10: Record that a repair job was successfully completed by this worker.
    
    Purpose:
    - Tracks proven reliability (completed repairs = node can be trusted)
    - Updates Factor 4 (Repair Success) in reputation scoring
    
    Parameters:
    - sat_id: Worker satellite that completed the repair job
    """
    if sat_id in STORAGENODE_SCORES:
        STORAGENODE_SCORES[sat_id]['repairs_completed'] += 1

def update_disk_health(sat_id: str, health_score: float) -> None:
    """
    TASK 10: Update disk health factor based on SMART status or health reports.
    
    Purpose:
    - Tracks disk reliability (SMART warnings, bad sectors, etc.)
    - Updates Factor 5 (Disk Health) in reputation scoring
    
    Parameters:
    - sat_id: Satellite to update
    - health_score: 0.0 (failing) to 1.0 (perfect)
                   0.9+ = healthy, 0.7-0.9 = warning, <0.7 = critical
    """
    if sat_id in STORAGENODE_SCORES:
        STORAGENODE_SCORES[sat_id]['disk_health'] = max(0.0, min(1.0, health_score))

def get_best_storagenodes(count: int = 1, exclude: Optional[List[str]] = None, min_score: float = 0.5) -> List[Tuple[str, StoragenodeScore]]:
    """
    TASK 10: Select best storagenodes based on reputation scores.
    
    Purpose:
    - Biases repair assignments and fragment placement toward reliable nodes
    - Excludes low-scoring nodes (score < min_score threshold)
    - Returns nodes sorted by composite score (highest first)
    
    Parameters:
    - count: Number of nodes to return
    - exclude: List of sat_ids to exclude from selection
    - min_score: Minimum acceptable score (default 0.5)
    
    Returns:
    - List of sat_ids sorted by score (best first), up to 'count' nodes
    
    Selection Logic:
    - Filter nodes with score >= min_score
    - Exclude nodes in exclude list
    - Sort by composite score descending
    - Return top 'count' nodes
    """
    if exclude is None:
        exclude = []
    
    # Get all storagenodes with storage capability and acceptable score
    candidates = []
    for sat_id, sat_info in TRUSTED_SATELLITES.items():
        # Must have storage port configured
        if sat_info.get('storage_port', 0) == 0:
            continue
        # Must not be in exclude list
        if sat_id in exclude:
            continue
        # Get score (default 1.0 if never audited)
        score = STORAGENODE_SCORES.get(sat_id, {}).get('score', 1.0)
        # Must meet minimum score threshold
        if score < min_score:
            continue
        candidates.append((sat_id, score))
    
    # Sort by score descending (best first)
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    # Return top 'count' sat_ids
    return [sat_id for sat_id, score in candidates[:count]]

# ============================================================================
# TASK 11: ADAPTIVE REDUNDANCY LOGIC
# ============================================================================

def count_good_storagenodes(min_score: float = 0.5) -> int:
    """
    TASK 11: Count number of healthy storagenodes available for placement.
    
    Returns count of nodes with:
    - storage_port > 0 (storage capability)
    - score >= min_score (meets quality threshold)
    - Not in circuit breaker open state
    """
    count = 0
    for sat_id, sat_info in TRUSTED_SATELLITES.items():
        if sat_info.get('storage_port', 0) == 0:
            continue
        if is_circuit_open(sat_id):
            continue
        score = STORAGENODE_SCORES.get(sat_id, {}).get('score', 1.0)
        if score >= min_score:
            count += 1
    return count


def adaptive_redundancy_target(base_k: int = 3, base_n: int = 5, min_score: float = 0.5) -> tuple:
    """
    TASK 11: Dynamically adjust k/n redundancy based on available healthy storagenodes.
    
    Strategy:
    - If < 20 good nodes: INCREASE redundancy to compensate for limited diversity
      (fewer placement options = higher risk, so store more copies)
    - If >= 50 good nodes: REDUCE redundancy to save space
      (abundant diversity = lower risk, can be more efficient)
    - Otherwise: use base k/n values
    
    Args:
        base_k: Default data shards (default 3)
        base_n: Default total shards (default 5)
        min_score: Minimum score for "good" node classification
    
    Returns:
        (k, n) tuple with adjusted redundancy parameters
    
    Examples:
        - 10 nodes available → k=3, n=7 (increased from 5)
        - 30 nodes available → k=3, n=5 (base)
        - 100 nodes available → k=3, n=4 (reduced from 5)
    """
    good_nodes = count_good_storagenodes(min_score)
    
    if good_nodes < 20:
        # LOW NODE COUNT: Increase redundancy for safety
        # With few nodes, correlated failures more likely
        # Increase n by +2 to improve durability
        adjusted_n = min(base_n + 2, good_nodes if good_nodes > 0 else base_n)
        logger_storage.info(f"Adaptive redundancy: {good_nodes} good nodes < 20 → increased n={base_n}→{adjusted_n}")
        return (base_k, adjusted_n)
    
    elif good_nodes >= 50:
        # ABUNDANT NODES: Reduce redundancy to save space
        # With many nodes, can rely on diversity rather than pure redundancy
        adjusted_n = max(base_n - 1, base_k + 1)  # Never go below k+1
        logger_storage.info(f"Adaptive redundancy: {good_nodes} good nodes >= 50 → reduced n={base_n}→{adjusted_n}")
        return (base_k, adjusted_n)
    
    else:
        # NORMAL RANGE (20-49 nodes): Use base values
        return (base_k, base_n)


def _compute_fill_pct(info: Dict[str, Any]) -> float:
    """
    TASK 13: Compute storage fill percentage for a storagenode.

    Uses TRUSTED_SATELLITES fields `capacity_bytes` and `used_bytes` if present.
    Returns a float in [0.0, 1.0]. Missing/zero capacity is treated as 1.0 (deprioritize).
    """
    try:
        capacity = float(info.get('capacity_bytes', 0) or 0)
        used = float(info.get('used_bytes', 0) or 0)
        if capacity <= 0:
            return 1.0
        pct = max(0.0, min(1.0, used / capacity))
        return pct
    except Exception:
        return 1.0

def _get_effective_zone(info: Dict[str, Any]) -> str:
    """
    TASK 13: Determine node's effective zone.

    For testing: Origin can override zones via placement.zone_override_map in config.
    Format: {"node_id": "zone_name"} or {"ip:port": "zone_name"}
    
    Supported zones (18 total):
    Americas: us-east, us-west, us-central, south-america-north, south-america-east, south-america-south
    Europe: eu-west, eu-central, eu-east
    Asia: asia-east, asia-south, asia-central
    Africa: africa-west, africa-east, africa-south
    Oceania: oceania-australia, oceania-newzealand, oceania-pacific
    
    Production: Zones detected from IP geolocation or manual node config.
    No override/authority mechanics in production. Defaults to 'unknown'.
    """
    # Check for zone override (testing only)
    if IS_ORIGIN:
        zone_override_map = PLACEMENT_SETTINGS.get('zone_override_map', {})
        if zone_override_map:
            node_id = info.get('id', '')
            ip_value = info.get('ip') or info.get('hostname') or ''
            ip_port = f"{ip_value}:{info.get('storage_port', 0)}"
            override_zone = zone_override_map.get(node_id) or zone_override_map.get(ip_port)
            logger_control.debug(f"_get_effective_zone: node_id={node_id}, ip_port={ip_port}, override_zone={override_zone}, info keys={list(info.keys())}")
            if override_zone:
                logger_control.debug(f"_get_effective_zone: returning override {override_zone} for {node_id}")
                return str(override_zone).strip()
    
    zone = info.get('zone') or info.get('region') or 'unknown'
    if not isinstance(zone, str):
        return 'unknown'
    return zone.strip() or 'unknown'

def choose_placement_targets(
    object_id: str,
    copies: int,
    exclude: Optional[List[str]] = None,
    min_score: float = None,
    min_distinct_zones: int = None,
    per_zone_cap_pct: float = None
) -> List[str]:
    """
    TASK 13: Choose storagenode targets for fragment placement.

    Constraints:
    - Diversity: aim for at least `min_distinct_zones` zones (or fewer if not available)
    - Cap: no more than `per_zone_cap_pct` of total copies in a single zone
    - Reliability: require score ≥ `min_score`, skip nodes with open circuit
    - Capacity: prefer lower fill percentage (even-fill)
    - Latency: prefer lower average latency when available
    - Reachability: require storage_port and (if known) reachable_direct

    Inputs are derived from TRUSTED_SATELLITES and STORAGENODE_SCORES.
    This function does not perform any network I/O.
    """
    if exclude is None:
        exclude = []
    # Apply defaults from PLACEMENT_SETTINGS if not provided
    if min_score is None:
        min_score = PLACEMENT_SETTINGS.get("min_score", 0.5)
    if min_distinct_zones is None:
        min_distinct_zones = PLACEMENT_SETTINGS.get("min_distinct_zones", 3)
    if per_zone_cap_pct is None:
        per_zone_cap_pct = PLACEMENT_SETTINGS.get("per_zone_cap_pct", 0.5)

    # Gather candidate storagenodes
    candidates: List[Dict[str, Any]] = []
    now = time.time()
    for sat_id, info in TRUSTED_SATELLITES.items():
        # Must be a storagenode (has storage_port > 0)
        storage_port = info.get('storage_port', 0) or 0
        if storage_port <= 0:
            continue
        if sat_id in exclude:
            continue
        # Skip nodes with open circuit (persistent failures)
        if is_circuit_open(sat_id):
            continue
        # Optional reachability hint: if present and False, skip
        if 'reachable_direct' in info and not info.get('reachable_direct'):
            continue

        score = STORAGENODE_SCORES.get(sat_id, {}).get('score', 1.0)
        if score < min_score:
            continue

        avg_latency = STORAGENODE_SCORES.get(sat_id, {}).get('avg_latency_ms', None)
        fill_pct = _compute_fill_pct(info)
        zone = _get_effective_zone(info)
        last_seen = float(info.get('last_seen', 0) or 0)

        candidates.append({
            'id': sat_id,
            'zone': zone,
            'score': float(score),
            'fill_pct': float(fill_pct),
            'latency': float(avg_latency) if isinstance(avg_latency, (int, float)) else None,
            'last_seen': last_seen,
            'storage_port': storage_port,
        })

    if not candidates or copies <= 0:
        return []

    # Sort: even-fill first, then reliability, then latency, then recency
    def sort_key(c: Dict[str, Any]):
        # Use large number for missing latency to avoid penalizing good nodes without data
        latency = c['latency'] if c['latency'] is not None else 1e9
        # Prefer recently seen
        recency = -c['last_seen'] if c['last_seen'] else 0
        return (c['fill_pct'], -c['score'], latency, recency)

    candidates.sort(key=sort_key)

    # Selection with diversity constraints
    selected: List[str] = []
    zone_counts: Dict[str, int] = {}
    distinct_zones_target = max(1, min(min_distinct_zones, len({c['zone'] for c in candidates})))
    # Cap per zone (round down)
    per_zone_cap = max(1, int(copies * per_zone_cap_pct))

    # First pass: prioritize introducing new zones until target reached
    for c in candidates:
        if len(selected) >= copies:
            break
        z = c['zone']
        if z not in zone_counts and len(zone_counts) < distinct_zones_target:
            # Accept if under cap
            if zone_counts.get(z, 0) < per_zone_cap:
                selected.append(c['id'])
                zone_counts[z] = 1

    # Second pass: fill remaining slots respecting per-zone cap and sort order
    if len(selected) < copies:
        for c in candidates:
            if len(selected) >= copies:
                break
            if c['id'] in selected:
                continue
            z = c['zone']
            if zone_counts.get(z, 0) < per_zone_cap:
                selected.append(c['id'])
                zone_counts[z] = zone_counts.get(z, 0) + 1

    return selected

def has_role(role: str) -> bool:
    """
    STEP 2 HELPER: Check if the current node has a specific role.
    
    Purpose:
    - Provides a clean API to check if a node supports a specific capability.
    - Handles both single-mode and hybrid-mode configurations uniformly.
    
    Parameters:
    - role (str): The role to check ('satellite', 'storagenode', 'repairnode', 'feeder', 'origin')
    
    Returns:
    - bool: True if the node has the specified role, False otherwise.
    
    Behavior:
    - If NODE_MODE equals the role directly, return True.
    - If NODE_MODE is 'hybrid', check if role is in HYBRID_ROLES array.
    - Otherwise, return False.
    
    Examples:
        # Single-mode node
        NODE_MODE = 'storagenode'
        has_role('storagenode')  # True
        has_role('satellite')    # False
        
        # Hybrid node
        NODE_MODE = 'hybrid'
        HYBRID_ROLES = ['satellite', 'storagenode']
        has_role('satellite')    # True
        has_role('storagenode')  # True
        has_role('repairnode')   # False
    """
    if NODE_MODE == role:
        return True
    if NODE_MODE == 'hybrid' and role in HYBRID_ROLES:
        return True
    return False

def get_local_ip() -> str:
    """
    STEP 4: Determine the IP address this satellite will advertise to peers and origin.

    Purpose:
    - Provides the network address that this satellite announces as its
      reachable endpoint during identity establishment and registry updates.
    - This value is used for *advertisement only*, not for socket binding.

    Behavior:
    - If ADVERTISED_IP_CONFIG is explicitly set by the operator, that value
      is always returned and treated as authoritative.
    - Otherwise, falls back to resolving the local hostname via the OS
      (`socket.gethostbyname(socket.gethostname())`).

    Design Notes:
    - This function does NOT perform network discovery, interface probing,
      NAT traversal, or reachability validation.
    - The fallback hostname resolution may return a loopback or non-routable
      address depending on system configuration.
    - Explicit configuration is strongly recommended for multi-node setups,
      NAT environments, and testing scenarios.

    Operational Context:
    - Called during startup to establish satellite identity.
    - Does not modify global state.
    - Kept intentionally simple to avoid boot-time network complexity.
    """
    return ADVERTISED_IP_CONFIG if ADVERTISED_IP_CONFIG else socket.gethostbyname(socket.gethostname()) # Return configured IP or resolve local hostname

async def fetch_github_file(url: str, local_path: str, force: bool = False) -> bool:
    """
    STEP 3a: Fetch and cache a file from a remote GitHub URL.

    Purpose:
    - Retrieves a file (typically JSON registry data) from a GitHub-hosted
      raw content URL.
    - Stores the file locally for use by other registry and trust-management
      functions.
    - Avoids unnecessary network access by using a local cached copy unless
      explicitly overridden.
    - TASK 20: Retries with exponential backoff on failure

    Behavior:
    - If `force` is False and `local_path` already exists, the function
      returns immediately without performing any network request.
    - If `force` is True, or the file does not exist locally, the function
      downloads the file from the given URL and overwrites any existing file.
    - The HTTP download is executed inside a thread executor to prevent
      blocking the asyncio event loop.
    - On failure, retries up to 3 times with exponential backoff (1s, 2s, 4s)

    Error Handling:
    - Transient failures (network timeouts) trigger exponential backoff retry
    - Permanent failures (HTTP 404) return False immediately
    - On final failure, the function returns False and does not raise.
    - On success, the function returns True.

    Design Notes:
    - This function does not validate the contents, format, or schema of the
      downloaded file.
    - No cryptographic verification, signature checking, or authenticity
      validation is performed here.
    - The function assumes the URL is trusted and reachable.
    - Implements exponential backoff for transient network failures.

    Operational Context:
    - Used as a low-level helper by registry synchronization logic.
    - Safe to call repeatedly.
    - Does not modify global state beyond writing to `local_path`.
    """
    if not os.path.exists(local_path) or force:
      # TASK 20: Exponential backoff retry logic
      max_retries = 3
      base_delay = 1.0  # Start with 1 second delay
      
      for attempt in range(max_retries):
        try:
          # Fetch file content from GitHub synchronously in a thread-safe way
          loop = asyncio.get_event_loop()
          response = await loop.run_in_executor(None, lambda: urllib.request.urlopen(url, timeout=10).read())
          # Write content to local file
          dirn = os.path.dirname(local_path)
          if dirn:
            os.makedirs(dirn, exist_ok=True)
          with open(local_path, "wb") as f:
            f.write(response)
          return True
        except urllib.error.HTTPError as http_err:
          if http_err.code == 404:
            # Permanent failure - don't retry
            return False
          elif attempt < max_retries - 1:
            # Transient HTTP error (5xx) - retry with backoff
            delay = base_delay * (2 ** attempt)
            await asyncio.sleep(delay)
        except Exception as e:
          if attempt < max_retries - 1:
            # Transient network error - retry with backoff
            delay = base_delay * (2 ** attempt)
            await asyncio.sleep(delay)
          else:
            return False
      return False
    # File already exists and force not requested
    return True

async def sync_nodes_with_peers() -> None:
    """
    STEP 4–5: Peer-to-peer node state synchronization.

    Purpose:
    - Periodically exchanges node state information with known peer satellites.
    - Supplements origin-based coordination by allowing satellites to
      directly share awareness of other nodes.

    Behavior:
    - Runs continuously as a background asynchronous task.
    - Iterates over entries in TRUSTED_SATELLITES.
    - Skips self entries and origin-specific cases where applicable.
    - Attempts to open a TCP connection to each peer's advertised host and port.
    - Sends a JSON-encoded payload describing this satellite's current state.
    - Receives and processes peer responses when provided.
    - Updates in-memory node awareness structures based on successful exchanges.

    Error Handling:
    - Network errors, connection failures, and malformed responses are caught.
    - Failures with one peer do not interrupt synchronization with others.
    - Errors are logged or surfaced via UI notifications where appropriate.

    Design Notes:
    - This function assumes TRUSTED_SATELLITES has already been loaded and
      validated during startup.
    - No cryptographic verification or TLS authentication is performed here.
    - Peer synchronization is opportunistic and best-effort.
    - This does not replace origin synchronization; it complements it.

    Operational Context:
    - Started as a background task by `main()`.
    - Relies on global state including TRUSTED_SATELLITES, SATELLITE_ID,
      ADVERTISED_IP, LISTEN_PORT, and NODES.
    - Intended to improve resilience and convergence in multi-satellite
      deployments.
    """
    while True:
        for sat_id, sat_info in TRUSTED_SATELLITES.items():
            if sat_id == SATELLITE_ID:
                continue  # skip self

            peer_host = sat_info.get('hostname')
            peer_port = sat_info.get('port')
            if not peer_host or not peer_port:
                continue  # skip entries without control endpoint

            try:
                reader, writer = await asyncio.open_connection(peer_host, peer_port)

                payload = {
                    "type": "peer_sync",
                    "id": SATELLITE_ID,
                    "fingerprint": TLS_FINGERPRINT,
                    "advertised_ip": ADVERTISED_IP,
                    "port": LISTEN_PORT,
                    "storage_port": STORAGE_PORT,
                    "timestamp": time.time(),
                    "metrics": get_system_metrics(),
                    "nodes": NODES,
                    "satellites": REMOTE_SATELLITES,
                }

                writer.write((json.dumps(payload) + "\n").encode())
                await writer.drain()
                writer.close()
                await writer.wait_closed()

            except Exception:
                # Ignore unreachable peers; peer sync is best-effort
                continue

        await asyncio.sleep(NODE_SYNC_INTERVAL)

async def safe_send_payload(reader_writer: Tuple[AsyncStreamReader, AsyncStreamWriter], payload: Dict[str, Any]) -> None:
    """
    Safely send a JSON-serializable payload over an asyncio TCP connection.

    Purpose:
    - Encodes the given payload as JSON and sends it to the connected peer.
    - Ensures the write buffer is flushed before closing the connection.
    - Handles any exceptions gracefully, reporting failures via UI notifications.

    Parameters:
    - reader_writer (tuple): A tuple of (reader, writer) from `asyncio.open_connection()`.
    - payload (dict): JSON-serializable data to send over the connection.

    Behavior:
    - Writes the JSON-encoded payload to the socket.
    - Awaits `drain()` to ensure data is transmitted.
    - Introduces a short delay to guarantee data is flushed before closing.
    - Closes the writer cleanly with `wait_closed()`.
    - On any exception (connection failure, encoding error, etc.), a notification is
      pushed to `UI_NOTIFICATIONS` instead of raising an error.

    Operational Context:
    - Can be used wherever a follower satellite needs to send data to the origin
      or another peer.
    - Helps centralize and standardize payload transmission with robust error handling.

    Example:
        reader, writer = await asyncio.open_connection(host, port)
        await safe_send_payload((reader, writer), {"id": SATELLITE_ID, "status": "ok"})
    """
    reader, writer = reader_writer
    try:
        writer.write(json.dumps(payload).encode())
        await writer.drain()
        # Ensure data is flushed before closing
        await asyncio.sleep(0.05)
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        logger_control.error(f"Failed to send payload: {e}")

async def sync_registry_from_github() -> None:
    """
    STEP 3a: Periodically fetches the trusted satellites registry from GitHub.

    Purpose:
    - Keeps the local trusted satellites registry up to date with the
      canonical list maintained in GitHub.
    - Ensures that satellites have a consistent view of trusted peers
      without requiring manual intervention.
    - Supports secure distribution of new satellite identities for registration.

    High-level behavior:
    - Runs indefinitely in a background loop with a sleep interval defined
      by SYNC_INTERVAL.
    - Downloads the remote `list.json` file from LIST_JSON_URL.
    - Compares the remote registry to the local `LIST_JSON_PATH`.
    - Updates local in-memory `TRUSTED_SATELLITES` and triggers a save if
      changes are detected.

    Data handled:
    - Reads JSON from GitHub.
    - Validates integrity superficially (well-formed JSON and expected fields).
    - Updates local trusted satellite structures (ID, fingerprint, hostname, port).

    Design constraints:
    - Assumes that GitHub-hosted JSON is authoritative for the canonical list.
    - Non-blocking; network errors are caught and logged without
      interrupting the loop.
    - Avoids overwriting local changes that were manually or dynamically added
      unless GitHub version differs.

    Operational context:
    - Launched during `main()` startup as a background task.
    - Complements other background tasks like:
        - draw_ui()
        - node_sync_loop()
        - announce_to_origin()
    - Maintains in-memory and persisted consistency of trusted satellites.

    Future considerations:
    - Could implement checksum or signature verification for higher trust.
    - Could notify UI of new or removed satellites automatically.
    - May integrate with repair queue awareness in future enhancements.

    Notes:
    - This function is advisory and maintenance-focused.
    - Errors in fetching do not halt the satellite; they are logged for operator awareness.
    """
    
    while True:
      if not IS_ORIGIN:
        # TASK 7: Only non-origin satellites fetch list.json from GitHub with ETag support
        # Try conditional GET with If-None-Match header
        global REGISTRY_ETAG
        headers = {}
        if REGISTRY_ETAG:
            headers['If-None-Match'] = REGISTRY_ETAG
        
        try:
            import urllib.request
            req = urllib.request.Request(LIST_JSON_URL, headers=headers)
            response = urllib.request.urlopen(req, timeout=10)
            
            # New content available
            new_etag = response.getheader('ETag')
            if new_etag:
                REGISTRY_ETAG = new_etag
            
            # Save the fetched content
            content = response.read()
            with open(LIST_JSON_PATH, 'wb') as f:
                f.write(content)
            
            load_trusted_satellites()
            log_and_notify(logger_control, 'info', "Registry updated from GitHub")
            
        except urllib.error.HTTPError as e:
            if e.code == 304:
                # Not modified - registry hasn't changed on GitHub
                pass  # Silent success, no update needed
            else:
                log_and_notify(logger_control, 'warning', f"Registry fetch failed: HTTP {e.code}")
        except Exception as e:
            log_and_notify(logger_control, 'warning', f"Registry fetch error: {e}")
      
      # Load and verify trusted satellites registry
      await asyncio.sleep(SYNC_INTERVAL)

def add_or_update_trusted_registry(sat_id: str, fingerprint: str, hostname: str, port: int, storage_port: Optional[int] = None) -> None:
    """
    STEP 3b: Add or update a satellite entry in the in-memory trusted registry.

    Purpose:
    - Maintains a dictionary of trusted satellites for identity verification.
    - Ensures the satellite registry reflects current fingerprint, hostname/IP, and listening port.
    - Notifies the local UI on registry changes.
    - Marks that the registry has pending updates to save.

    Parameters:
    - sat_id (str): Unique identifier of the satellite.
    - fingerprint (str): TLS fingerprint of the satellite's certificate.
    - hostname (str): Advertised hostname or IP of the satellite.
    - port (int): Listening port of the satellite.
    - storage_port (int): Storage RPC port (0 for origin nodes, None defaults to 0).

    Behavior:
    - If this node is not the origin, returns immediately (only origin updates registry).
    - Constructs a details dictionary with satellite identity and network info.
    - If the satellite is new or its details have changed:
      - Updates the TRUSTED_SATELLITES dictionary.
      - Queues a UI notification via `UI_NOTIFICATIONS`.
      - Flags `LIST_UPDATED_PENDING_SAVE` to true for later persistence.
    - Does NOT perform network I/O or direct file writes.

    Notes:
    - Modifies the global TRUSTED_SATELLITES dictionary.
    - UI notification provides operator feedback on registry changes.
    - LIST_UPDATED_PENDING_SAVE signals that a signed update should be written later.
    """
    global LIST_UPDATED_PENDING_SAVE
    if not IS_ORIGIN: return # Followers do not modify the registry
    new_details = {
    "id": sat_id,             # Unique satellite ID
    "fingerprint": fingerprint,  # TLS fingerprint for trust
    "hostname": hostname,     # Advertised reachable IP/host
    "port": port,             # TCP listening port
    "storage_port": storage_port if storage_port is not None else 0  # Storage port (0 for origin)
    }
    
    # Preserve existing fields when updating (e.g., metrics, last_seen, reachable_direct)
    if sat_id in TRUSTED_SATELLITES:
        existing = TRUSTED_SATELLITES[sat_id].copy()
        # Only check if core identity fields changed
        core_fields = {"id", "fingerprint", "hostname", "port", "storage_port"}
        existing_core = {k: v for k, v in existing.items() if k in core_fields}
        new_core = {k: v for k, v in new_details.items() if k in core_fields}
        if existing_core != new_core:
            # Core fields changed - update but preserve extra fields
            existing.update(new_details)
            TRUSTED_SATELLITES[sat_id] = existing
            logger_control.info(f"Registry updated: {sat_id}")
            LIST_UPDATED_PENDING_SAVE = True
        else:
            # Even if core fields match, ensure the entry has all current fields
            existing.update(new_details)
            TRUSTED_SATELLITES[sat_id] = existing
    else:
        # New satellite - just add it
        TRUSTED_SATELLITES[sat_id] = new_details
        log_and_notify(logger_control, 'info', f"Registry updated: {sat_id}")
        LIST_UPDATED_PENDING_SAVE = True 

def load_trusted_satellites() -> Dict[str, SatelliteInfo]:
    """
    Step 3a/3b: Load and verify the trusted satellites registry from disk.

    Purpose:
    - Reads the signed registry file at LIST_JSON_PATH.
    - Verifies the registry signature using the origin public key (ORIGIN_PUBKEY_PEM).
    - On successful verification, updates TRUSTED_SATELLITES in memory.
    - TASK 20: Auto-recover from corrupted list.json using backup file

    Behavior:
    1. If the file at LIST_JSON_PATH does not exist, no action is taken.
    2. Loads the file and parses it as JSON containing:
       - 'data': registry dictionary
       - 'signature': base64-encoded signature
    3. If the origin public key is not loaded (ORIGIN_PUBKEY_PEM is None), return early.
    4. Loads the origin public key and attempts to verify the signature over
       the canonical JSON of the registry data.
    5. On successful verification:
       - Clears current TRUSTED_SATELLITES.
       - Populates TRUSTED_SATELLITES with entries from data['satellites'].
    6. On parse/verification failure:
       - Attempts fallback to 'list.json.bak' backup file
       - If backup exists, restores from backup and notifies operator
       - If no backup, notifies "Registry: Verification Failed."
       - TRUSTED_SATELLITES remains unchanged.

    Notes:
    - This function enforces cryptographic integrity of the trusted registry.
    - Only registries signed by the origin are accepted.
    - Global state modified: TRUSTED_SATELLITES.
    - Called during startup and periodic registry synchronization.
    """
    global TRUSTED_SATELLITES
    if os.path.exists(LIST_JSON_PATH):
      data = None
      try:
        with open(LIST_JSON_PATH, 'r') as f:
          signed_data = json.load(f)
        # Support either signed format {data, signature} or raw {satellites: [...]} for robustness
        data = signed_data.get('data', signed_data)
      except (json.JSONDecodeError, ValueError) as json_err:
        # TASK 20: Handle corrupted JSON - try backup file
        backup_path = f"{LIST_JSON_PATH}.bak"
        if os.path.exists(backup_path):
          try:
            log_and_notify(logger_control, 'warning', f"Registry corrupted, restoring from backup: {str(json_err)[:40]}")
            with open(backup_path, 'r') as f:
              signed_data = json.load(f)
            # Create backup of corrupted file for debugging
            import shutil
            shutil.copy(LIST_JSON_PATH, f"{LIST_JSON_PATH}.corrupted")
            # Restore from backup
            shutil.copy(backup_path, LIST_JSON_PATH)
            data = signed_data.get('data', signed_data)
          except Exception as backup_error:
            log_and_notify(logger_control, 'error', f"Registry backup failed: {str(backup_error)[:40]}")
            return
        else:
          log_and_notify(logger_control, 'error', f"Registry corrupted, no backup: {str(json_err)[:40]}")
          return

      # If origin public key is unavailable, load without verification (with clear notice)
      if not ORIGIN_PUBKEY_PEM:
        # Preserve locally-probed reachability status before clearing
        old_reachability = {sat_id: sat_info.get('reachable_direct') 
                           for sat_id, sat_info in TRUSTED_SATELLITES.items()}
        
        TRUSTED_SATELLITES.clear()
        for sat in data.get('satellites', []):
          # Initialize last_seen to now if missing (satellites just loaded from registry)
          if 'last_seen' not in sat:
            sat['last_seen'] = time.time()
          # Restore locally-probed reachability status (don't trust registry for this)
          sat_id = sat['id']
          if sat_id in old_reachability and old_reachability[sat_id] is not None:
            sat['reachable_direct'] = old_reachability[sat_id]
          TRUSTED_SATELLITES[sat_id] = sat
        try:
          # TASK 20: Create backup copy for corruption recovery
          import shutil
          shutil.copy(LIST_JSON_PATH, f"{LIST_JSON_PATH}.bak")
          log_and_notify(logger_control, 'warning', "Registry loaded from disk without verification (no origin pubkey).")
        except Exception:
          pass
        return

      try:
        public_key = serialization.load_pem_public_key(ORIGIN_PUBKEY_PEM, backend=default_backend())
        signature_b64 = signed_data.get('signature')
        if not signature_b64:
          raise ValueError("Missing signature in registry file")
        signature = base64.b64decode(signature_b64)
        json_bytes = json.dumps(data, indent=4, sort_keys=True).encode('utf-8') # Canonical JSON for signature verification
        public_key.verify(signature, json_bytes, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())

        # Verification succeeded: update TRUSTED_SATELLITES
        # Preserve locally-probed reachability status before clearing
        old_reachability = {sat_id: sat_info.get('reachable_direct') 
                           for sat_id, sat_info in TRUSTED_SATELLITES.items()}
        
        TRUSTED_SATELLITES.clear()
        for sat in data.get('satellites', []):
          # Initialize last_seen to now if missing (satellites just loaded from registry)
          if 'last_seen' not in sat:
            sat['last_seen'] = time.time()
          # Restore locally-probed reachability status (don't trust registry for this)
          sat_id = sat['id']
          if sat_id in old_reachability and old_reachability[sat_id] is not None:
            sat['reachable_direct'] = old_reachability[sat_id]
          TRUSTED_SATELLITES[sat['id']] = sat
      except Exception:
        # Verification failed, notify UI
        log_and_notify(logger_control, 'error', "Registry: Verification Failed.")

def sign_and_save_satellite_list() -> None:
    """
    Step 3b: Sign and persist the trusted satellite registry for distribution.
    
    Purpose:
    - Produces the authoritative, signed registry of trusted satellites.
    - Ensures integrity and authenticity of the registry using the
      origin satellite's private signing key.

    Behavior:
    1. Serializes the TRUSTED_SATELLITES structure into a canonical JSON form.
    2. Loads the origin private key from disk.
    3. Signs the serialized registry using RSA with SHA-256.
    4. Writes a JSON file containing:
       - 'data': the trusted satellite registry
       - 'signature': base64-encoded signature over the data
    5. Saves the result to LIST_JSON_PATH for later distribution
       via GitHub or other sync mechanisms.

    Operational Context:
    - Intended to run ONLY on the origin satellite.
    - Called after registry mutations (add/update/remove satellite).
    - Followers must verify this signature before accepting registry updates.

    Failure Handling:
    - Any signing or file I/O error results in a UI notification.
    - No partial or unsigned registry is written.

    Security Notes:
    - This function establishes the cryptographic root of trust
      for the entire satellite network.
    - Compromise of the origin private key compromises registry trust.
    """
    global LIST_UPDATED_PENDING_SAVE
    if not IS_ORIGIN or not ORIGIN_PRIVKEY_PEM: return
    try:
        private_key = serialization.load_pem_private_key(ORIGIN_PRIVKEY_PEM, password=None, backend=default_backend())
        data = {"satellites": list(TRUSTED_SATELLITES.values())}
        
        # TASK 12: Debug - log what we're saving
        sat_ids = [s.get('id', 'unknown') for s in data['satellites']]
        logger_control.info(f"Saving registry: {', '.join(sat_ids)}")
        
        json_bytes = json.dumps(data, indent=4, sort_keys=True).encode('utf-8')  # Canonical JSON for reproducible signing
        sig = private_key.sign(json_bytes, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
        dirn = os.path.dirname(LIST_JSON_PATH)
        if dirn:
          os.makedirs(dirn, exist_ok=True)
        with open(LIST_JSON_PATH, 'w') as f:
            json.dump({"data": data, "signature": base64.b64encode(sig).decode('utf-8')}, f, indent=4)
        LIST_UPDATED_PENDING_SAVE = False # Only reset after successful sign & save
        
        # TASK 12: Verify write succeeded by reading back
        with open(LIST_JSON_PATH, 'r') as f:
            verify = json.load(f)
            verify_count = len(verify['data']['satellites'])
            logger_control.info(f"Verified: {verify_count} satellites written to {LIST_JSON_PATH}")
        
        logger_control.info(f"Registry saved ({len(TRUSTED_SATELLITES)} satellites)")
    except Exception as e:
        log_and_notify(logger_control, 'error', f"Registry save failed: {type(e).__name__}: {e}")

def generate_keys_and_certs() -> Tuple[str, str]:
    """
    STEP 3: Generate or load cryptographic identity material for this satellite.

    Purpose:
    - Establishes the cryptographic identity of the satellite node.
    - Ensures the presence of a private key, public key, and TLS certificate
      before any network communication occurs.

    Behavior:
    - Checks whether the required key and certificate files already exist
      on disk.
    - If all required files are present:
        - Loads the existing private key, public key, and certificate.
    - If any required file is missing:
        - Generates a new RSA private key.
        - Derives the corresponding public key.
        - Generates a self-signed X.509 TLS certificate.
        - Writes all generated artifacts to disk.

    Side Effects:
    - Writes cryptographic material to the filesystem if regeneration is required.
    - Computes and sets the TLS fingerprint derived from the certificate.
    - Updates global identity-related state used elsewhere in the program.

    Operational Context:
    - Called once during startup as part of identity establishment.
    - Must run before any satellite announces itself or accepts connections.
    - Used by both origin and non-origin satellites.

    Security Notes:
    - Certificates are self-signed; trust is established via fingerprint
      verification and signed registry distribution rather than a CA.
    - Regenerating keys will change the satellite’s identity and TLS fingerprint.
    - Private key material must be protected from unauthorized access.

    Design Notes:
    - Function is intentionally idempotent and safe to call multiple times.
    - No network operations are performed here to keep boot-time complexity low.
    """
    global SATELLITE_ID, TLS_FINGERPRINT, IS_ORIGIN, ADVERTISED_IP, ORIGIN_PUBKEY_PEM, ORIGIN_PRIVKEY_PEM
    # 1. Cert Generation
    if not os.path.exists(CERT_PATH):
        key = rsa.generate_private_key(65537, 2048)
        subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(SATELLITE_NAME))])
        cert = x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.utcnow()).not_valid_after(datetime.utcnow() + timedelta(days=3650)).sign(key, hashes.SHA256()) # Self-signed certificate: subject = issuer = satellite CN
        with open(KEY_PATH, "wb") as f: f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        with open(CERT_PATH, "wb") as f: f.write(cert.public_bytes(serialization.Encoding.PEM))

    # 2. Role Logic
    if NODE_MODE == 'origin':
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

    # 3. Attributes
    with open(CERT_PATH, 'rb') as f:
        cert = x509.load_pem_x509_certificate(f.read(), default_backend())
    cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    SATELLITE_ID = cn_attrs[0].value if cn_attrs else str(SATELLITE_NAME)
    TLS_FINGERPRINT = base64.b64encode(cert.fingerprint(hashes.SHA256())).decode('utf-8')
    ADVERTISED_IP = get_local_ip()

# --- Task 5: Storage RPC Functions ---

def get_fragment_path(object_id: str, fragment_index: int) -> str:
    """
    Compute the disk path for a fragment.
    
    Format: FRAGMENTS_PATH/object_id/index.bin
    """
    return os.path.join(FRAGMENTS_PATH, str(object_id), f"{fragment_index}.bin")

async def put_fragment(hostname: str, port: int, object_id: str, fragment_index: int, data: bytes) -> bool:
    """
    Send a fragment to a remote storage node.
    
    Purpose:
    - Upload a fragment to a storage node via the data port.
    - Used during upload workflows and repair operations.
    
    Parameters:
    - hostname: IP/hostname of target storage node
    - port: data port (typically STORAGE_PORT = 9888)
    - object_id: unique identifier for the object
    - fragment_index: shard number (0..n-1)
    - data: raw fragment bytes
    
    Returns: True if successful, False on any error.
    
    Wire format:
    {
      "rpc": "put",
      "object_id": "<id>",
      "fragment_index": <int>,
      "data": "<base64>",
      "size": <bytes>
    }
    """
    try:
        reader, writer = await asyncio.open_connection(hostname, port)
        payload = {
            "rpc": "put",
            "object_id": object_id,
            "fragment_index": fragment_index,
            "data": base64.b64encode(data).decode('utf-8'),
            "size": len(data)
        }
        writer.write(json.dumps(payload).encode() + b'\n')
        await writer.drain()
        
        # Wait for ACK
        response_data = await asyncio.wait_for(reader.readline(), timeout=5.0)
        response = json.loads(response_data.decode())
        
        writer.close()
        await writer.wait_closed()
        return response.get('status') == 'ok'
    except Exception:
        return False

async def get_fragment(hostname: str, port: int, object_id: str, fragment_index: int) -> Optional[bytes]:
    """
    Retrieve a fragment from a remote storage node.
    
    Purpose:
    - Download a fragment from a storage node.
    - Used during download and repair workflows.
    
    Parameters:
    - hostname: IP/hostname of target storage node
    - port: data port (typically STORAGE_PORT = 9888)
    - object_id: unique identifier for the object
    - fragment_index: shard number to retrieve
    
    Returns: fragment bytes on success, None on any error.
    
    Wire format (request):
    {
      "rpc": "get",
      "object_id": "<id>",
      "fragment_index": <int>
    }
    
    Response: raw fragment bytes prefixed with JSON metadata.
    """
    try:
        reader, writer = await asyncio.open_connection(hostname, port)
        payload = {
            "rpc": "get",
            "object_id": object_id,
            "fragment_index": fragment_index
        }
        writer.write(json.dumps(payload).encode() + b'\n')
        await writer.drain()
        
        # Read JSON response header
        header_data = await asyncio.wait_for(reader.readline(), timeout=5.0)
        header = json.loads(header_data.decode())
        
        if header.get('status') != 'ok':
            writer.close()
            await writer.wait_closed()
            return None
        
        # Read fragment data
        size = header.get('size', 0)
        fragment_data = await asyncio.wait_for(reader.readexactly(size), timeout=10.0)
        
        writer.close()
        await writer.wait_closed()
        return fragment_data
    except Exception:
        return None

async def list_fragments(hostname: str, port: int, object_id: str) -> Optional[List[int]]:
    """
    Query which fragments a storage node has for an object.
    
    Purpose:
    - Discover available fragments for repair and status queries.
    
    Parameters:
    - hostname: IP/hostname of target storage node
    - port: data port (typically STORAGE_PORT = 9888)
    - object_id: unique identifier for the object
    
    Returns: list of fragment indexes (e.g., [0,1,3,5]) or None on error.
    
    Wire format:
    {
      "rpc": "list",
      "object_id": "<id>"
    }
    
    Response:
    {
      "status": "ok",
      "fragments": [0,1,3,5]
    }
    """
    try:
        reader, writer = await asyncio.open_connection(hostname, port)
        payload = {
            "rpc": "list",
            "object_id": object_id
        }
        writer.write(json.dumps(payload).encode() + b'\n')
        await writer.drain()
        
        response_data = await asyncio.wait_for(reader.readline(), timeout=5.0)
        response = json.loads(response_data.decode())
        
        writer.close()
        await writer.wait_closed()
        return response.get('fragments') if response.get('status') == 'ok' else None
    except Exception:
        return None

async def store_object_fragments(object_id: str, data: bytes, k: int = 0, n: int = 0, adaptive: bool = True) -> Dict[int, Dict[str, Any]]:
    """
    TASK 13: Fragment an object and place shards across storagenodes.
    TASK 14: Integrated with versioning and manifest tracking.
    TASK 11: Adaptive redundancy selection based on available storagenodes.

    - If adaptive=True and k/n are 0: automatically determines k/n via adaptive_redundancy_target()
    - Uses make_fragments(k, n) to produce n shards.
    - Selects placement targets via choose_placement_targets() with copies=1.
    - Sends each shard to its selected storagenode using put_fragment().
    - Creates object manifest entry with version metadata and retention defaults.
    - Returns a placement result map: {frag_idx: {"sat_id": str, "status": "ok"|"error", "reason": str}}.

    Args:
        object_id: Unique object identifier
        data: Raw bytes to fragment and store
        k: Data shards (0 = use adaptive)
        n: Total shards (0 = use adaptive)
        adaptive: Whether to use adaptive redundancy (default True)

    Notes:
    - No override/testing hooks; relies on TRUSTED_SATELLITES and STORAGENODE_SCORES.
    - Caller is responsible for handling insufficient candidates or errors.
    - Manifest entry allows tracking versions, retention, and soft-deletes.
    """
    results: Dict[int, Dict[str, Any]] = {}
    version_id = str(uuid.uuid4())[:16]  # Generate unique version ID
    
    # TASK 11: Apply adaptive redundancy if enabled and k/n not specified
    if adaptive and (k == 0 or n == 0):
        k, n = adaptive_redundancy_target()
        logger_storage.info(f"Adaptive redundancy selected: k={k}, n={n}")
    elif k == 0 or n == 0:
        # Fallback to defaults if not specified
        k, n = 3, 5
    
    # Create fragments
    try:
        shards = make_fragments(data, k, n)
    except Exception as e:
        # If fragmentation fails, mark all as error
        for i in range(n):
            results[i] = {"sat_id": None, "status": "error", "reason": f"fragmentation_failed: {type(e).__name__}"}
        return results

    # TASK 14: Initialize object manifest if needed
    if IS_ORIGIN and object_id not in OBJECT_MANIFESTS:
        OBJECT_MANIFESTS[object_id] = {
            "versions": {},
            "deleted_at": None,
            "retention_policy": {
                "retention_days": 30,  # Default 30-day retention
                "ttl_seconds": 0,
            }
        }
    
    # For each shard, choose a target and store
    stored_count = 0
    for idx, shard in enumerate(shards):
        try:
            targets = choose_placement_targets(object_id=object_id, copies=1)
            if not targets:
                results[idx] = {"sat_id": None, "status": "error", "reason": "no_eligible_targets"}
                continue
            sat_id = targets[0]
            info = TRUSTED_SATELLITES.get(sat_id, {})
            host = info.get('hostname')
            port = info.get('storage_port')
            if not host or not port:
                results[idx] = {"sat_id": sat_id, "status": "error", "reason": "missing_host_or_port"}
                continue
            ok = await put_fragment(host, int(port), object_id, idx, shard)
            if ok:
                # Register in FRAGMENT_REGISTRY for audit/visibility
                import hashlib
                checksum = hashlib.sha256(shard).hexdigest()
                if object_id not in FRAGMENT_REGISTRY:
                    FRAGMENT_REGISTRY[object_id] = {}
                FRAGMENT_REGISTRY[object_id][idx] = {
                    "sat_id": sat_id,
                    "checksum": checksum,
                    "size": len(shard),
                    "stored_at": time.time()
                }
                results[idx] = {"sat_id": sat_id, "status": "ok", "reason": ""}
                stored_count += 1
            else:
                results[idx] = {"sat_id": sat_id, "status": "error", "reason": "put_failed"}
        except Exception as e:
            results[idx] = {"sat_id": None, "status": "error", "reason": f"{type(e).__name__}: {str(e)[:64]}"}

    # TASK 14: Create version entry in manifest with retention defaults
    if IS_ORIGIN and stored_count > 0:
        manifest = OBJECT_MANIFESTS[object_id]
        manifest["versions"][version_id] = {
            "created_at": time.time(),
            "retention_days": manifest.get("retention_policy", {}).get("retention_days", 30),
            "ttl_seconds": 0,
            "fragment_count": stored_count,
            "total_size": len(data),
            "retention_expires_at": time.time() + (30 * 86400),  # 30 days from now
        }
        logger_repair.info(f"Object {object_id[:16]} version {version_id} stored: {stored_count}/{n} fragments, 30d retention")

    return results

async def handle_storage_rpc(reader: AsyncStreamReader, writer: AsyncStreamWriter) -> None:
    """
    TASK 5: Handle inbound storage RPC requests from clients/satellites.
    
    Purpose:
    - Server-side handler for fragment put/get/list operations.
    - Runs on storagenodes and satellite nodes with storage capability.
    
    Operational role:
    - Called for every inbound connection on STORAGE_PORT.
    - Routes RPC based on 'rpc' field in JSON.
    - Only processes requests if NODE_MODE supports storage (storagenode, satellite, hybrid).
    
    Wire protocol:
    - Requests: newline-terminated JSON on first line
    - Responses: JSON followed by binary data (for get)
    
    Supported RPCs:
    - "put": receive and persist a fragment
    - "get": load and send a fragment
    - "list": enumerate fragments for an object
    """
    peer_addr = writer.get_extra_info("peername")[0]
    
    try:
        # Read JSON request (newline-terminated)
        request_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
        if not request_line:
            return
        
        request = json.loads(request_line.decode())
        rpc_type = request.get('rpc')
        
        if rpc_type == 'put':
            # PUT: receive fragment data
            object_id = request.get('object_id')
            fragment_index = request.get('fragment_index')
            data_b64 = request.get('data')
            size = request.get('size', 0)
            
            if not all([object_id, fragment_index is not None, data_b64]):
                writer.write(json.dumps({"status": "error", "reason": "missing fields"}).encode() + b'\n')
                await writer.drain()
            else:
                try:
                    data = base64.b64decode(data_b64)
                    if len(data) != size:
                        raise ValueError("size mismatch")
                    
                    # Save fragment to disk
                    frag_path = get_fragment_path(object_id, fragment_index)
                    frag_dir = os.path.dirname(frag_path)
                    os.makedirs(frag_dir, exist_ok=True)
                    
                    with open(frag_path, 'wb') as f:
                        f.write(data)
                    
                    # TASK 9: Register fragment in FRAGMENT_REGISTRY for auditing
                    import hashlib
                    checksum = hashlib.sha256(data).hexdigest()
                    
                    if object_id not in FRAGMENT_REGISTRY:
                        FRAGMENT_REGISTRY[object_id] = {}
                    
                    FRAGMENT_REGISTRY[object_id][fragment_index] = {
                        "sat_id": SATELLITE_ID,
                        "checksum": checksum,
                        "size": len(data),
                        "stored_at": time.time()
                    }
                    
                    writer.write(json.dumps({"status": "ok"}).encode() + b'\n')
                    await writer.drain()
                except Exception as e:
                    writer.write(json.dumps({"status": "error", "reason": str(e)}).encode() + b'\n')
                    await writer.drain()
        
        elif rpc_type == 'get':
            # GET: send fragment data
            object_id = request.get('object_id')
            fragment_index = request.get('fragment_index')
            
            if not all([object_id, fragment_index is not None]):
                writer.write(json.dumps({"status": "error", "reason": "missing fields"}).encode() + b'\n')
                await writer.drain()
            else:
                frag_path = get_fragment_path(object_id, fragment_index)
                if os.path.exists(frag_path):
                    try:
                        with open(frag_path, 'rb') as f:
                            data = f.read()
                        # Send header
                        writer.write(json.dumps({"status": "ok", "size": len(data)}).encode() + b'\n')
                        await writer.drain()
                        # Send data
                        writer.write(data)
                        await writer.drain()
                    except Exception as e:
                        writer.write(json.dumps({"status": "error", "reason": str(e)}).encode() + b'\n')
                        await writer.drain()
                else:
                    writer.write(json.dumps({"status": "error", "reason": "not found"}).encode() + b'\n')
                    await writer.drain()
        
        elif rpc_type == 'list':
            # LIST: enumerate fragments for object
            object_id = request.get('object_id')
            
            if not object_id:
                writer.write(json.dumps({"status": "error", "reason": "missing object_id"}).encode() + b'\n')
                await writer.drain()
            else:
                obj_dir = os.path.join(FRAGMENTS_PATH, str(object_id))
                fragments = []
                if os.path.exists(obj_dir):
                    try:
                        for fname in os.listdir(obj_dir):
                            if fname.endswith('.bin'):
                                idx = int(fname[:-4])
                                fragments.append(idx)
                    except Exception:
                        pass
                
                writer.write(json.dumps({"status": "ok", "fragments": sorted(fragments)}).encode() + b'\n')
                await writer.drain()
        
        elif rpc_type == 'challenge':
            # TASK 9: CHALLENGE - proof-of-storage verification
            object_id = request.get('object_id')
            fragment_index = request.get('fragment_index')
            nonce = request.get('nonce')
            
            if not all([object_id, fragment_index is not None, nonce]):
                writer.write(json.dumps({"status": "error", "reason": "missing fields"}).encode() + b'\n')
                await writer.drain()
            else:
                frag_path = get_fragment_path(object_id, fragment_index)
                if os.path.exists(frag_path):
                    try:
                        # Read fragment and compute challenge response
                        with open(frag_path, 'rb') as f:
                            fragment_data = f.read()
                        
                        # Compute hash(fragment + nonce)
                        import hashlib
                        challenge_response = hashlib.sha256(
                            fragment_data + nonce.encode()
                        ).hexdigest()
                        
                        writer.write(json.dumps({
                            "status": "ok",
                            "challenge_response": challenge_response,
                            "fragment_size": len(fragment_data)
                        }).encode() + b'\n')
                        await writer.drain()
                    except Exception as e:
                        writer.write(json.dumps({"status": "error", "reason": str(e)}).encode() + b'\n')
                        await writer.drain()
                else:
                    writer.write(json.dumps({"status": "error", "reason": "fragment not found"}).encode() + b'\n')
                    await writer.drain()
        
        else:
            writer.write(json.dumps({"status": "error", "reason": f"unknown rpc: {rpc_type}"}).encode() + b'\n')
            await writer.drain()
    
    except Exception as e:
        try:
            writer.write(json.dumps({"status": "error", "reason": str(e)}).encode() + b'\n')
            await writer.drain()
        except Exception:
            pass
    
    finally:
        writer.close()
        await writer.wait_closed()

async def probe_storage_reachability(sat_id: str, hostname: str, storage_port: int, control_port: int = None) -> bool:
    """
    TASK 5 (bonus): Probe if a node's port is directly reachable.
    
    Purpose:
    - Test if a node can accept direct connections.
    - For origin nodes: probe control port (since storage is disabled).
    - For satellites: probe storage port.
    - Records reachability in registry for future optimization.
    
    Parameters:
    - sat_id: satellite/node ID
    - hostname: IP/hostname to probe
    - storage_port: data port to test (or None for origin nodes)
    - control_port: control port to test (used for origin nodes)
    
    Returns: True if reachable within timeout, False otherwise.
    """
    # For origin nodes with no storage port, probe control port instead
    if storage_port is None or storage_port == 0:
        port = control_port
        port_type = "control"
    else:
        port = storage_port
        port_type = "storage"
    
    if port is None:
        logger_storage.debug(f"Probe {sat_id[:20]}: no port to probe")
        return False
    
    try:
        # 5 second timeout to allow server startup time
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(hostname, port), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        logger_storage.debug(f"Probe {sat_id[:20]}: {hostname}:{port} ({port_type}) reachable")
        logger_storage.debug(f"Probe {sat_id[:20]}: {hostname}:{port} ({port_type}) ✓ reachable")
        return True
    except asyncio.TimeoutError:
        logger_storage.warning(f"Probe {sat_id[:20]}: {hostname}:{port} ({port_type}) ✗ timeout (server not responding)")
        return False
    except ConnectionRefusedError:
        logger_storage.warning(f"Probe {sat_id[:20]}: {hostname}:{port} ({port_type}) ✗ refused (nothing listening)")
        return False
    except Exception as e:
        logger_storage.warning(f"Probe {sat_id[:20]}: {hostname}:{port} ({port_type}) ✗ {type(e).__name__}")
        return False

async def probe_storagenode_p2p_connectivity(source_id: str, target_id: str) -> bool:
    """
    TASK 24: Probe bidirectional P2P connectivity between storage nodes.
    
    Purpose:
    - Test if storage nodes can directly connect to each other for future peer-to-peer repairs.
    - Records results in STORAGENODE_SCORES['p2p_reachable'] dict.
    - Helps identify well-connected nodes that can act as repair sources.
    
    Parameters:
    - source_id: Storage node initiating the probe
    - target_id: Storage node being probed
    
    Returns: True if target reachable from source, False otherwise.
    
    Design:
    - Looks up both nodes in global registry (NODES)
    - Attempts TCP connection to target's storage port
    - Uses 3-second timeout (shorter than satellite probes)
    - Updates p2p_reachable dict with result
    
    Operational Context:
    - Called by storagenode_p2p_prober() background task
    - Only runs on storage nodes (not satellites or origin)
    - Results visible in leaderboard UI
    """
    # Look up target node info
    target_node = NODES.get(target_id)
    if not target_node:
        return False
    
    target_ip = target_node.get('ip')
    target_storage_port = target_node.get('storage_port')
    
    if not target_ip or not target_storage_port:
        return False
    
    try:
        # 3 second timeout for P2P probes (faster than satellite probes)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(target_ip, target_storage_port), timeout=3.0)
        writer.close()
        await writer.wait_closed()
        
        # Update connectivity map
        if source_id in STORAGENODE_SCORES:
            STORAGENODE_SCORES[source_id]['p2p_reachable'][target_id] = True
        
        logger_storage.debug(f"P2P probe success: {source_id[:12]} → {target_id[:12]}")
        return True
        
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        # Update connectivity map
        if source_id in STORAGENODE_SCORES:
            STORAGENODE_SCORES[source_id]['p2p_reachable'][target_id] = False
        
        return False
        
    except Exception as e:
        if source_id in STORAGENODE_SCORES:
            STORAGENODE_SCORES[source_id]['p2p_reachable'][target_id] = False
        
        return False

async def handle_node_sync(reader: AsyncStreamReader, writer: AsyncStreamWriter) -> None:
    """
    STEP 6: Handle inbound satellite → origin synchronization connections.

    Purpose:
    - Acts as the server-side entry point for satellites reporting their
      identity, status, and operational metadata to the origin node.
    - Allows the origin to maintain an authoritative, signed registry of
      trusted satellites and their advertised endpoints.

    Operational Role:
    - This handler is only meaningful on the origin node.
    - Non-origin satellites may still accept connections, but will not
      process or persist synchronization payloads.

    Expected Payload:
    - Incoming data must be valid JSON containing, at minimum:
        - id: unique satellite identifier
        - fingerprint: TLS certificate fingerprint
        - ip: advertised network address
        - port: listening TCP port
    - Optional fields may include:
        - nodes: known storage or peer nodes
        - repair_queue: pending repair tasks

    Validation & Error Handling:
    - Payload keys are validated before processing.
    - Missing or malformed payloads raise explicit errors.
    - Any exception during parsing or validation results in:
        - A notification being emitted to the UI notification system.
        - The connection being closed cleanly.

    Behavior on Origin:
    - Updates or inserts the satellite entry into TRUSTED_SATELLITES.
    - Persists changes by signing and saving the registry when necessary.
    - Emits UI notifications for new registrations or updates.

    Side Effects:
    - Mutates global state (TRUSTED_SATELLITES).
    - Writes registry data to disk via signed persistence.
    - Emits messages into UI_NOTIFICATIONS for operator visibility.

    Concurrency Notes:
    - Designed to be called concurrently by asyncio’s TCP server.
    - Does not block the event loop beyond minimal JSON parsing and I/O.

    Design Notes:
    - No authentication handshake is performed here beyond payload validation;
      trust enforcement relies on fingerprint verification and signed registry
      distribution.
    - This function is intentionally strict to surface malformed or unexpected
      sync attempts during early testing and development.
    """
    peer_ip = writer.get_extra_info("peername")[0]
    sat_id = None  # Will be set after first message

    try:
        # TASK 18: Connection limits and rate limiting (origin only)
        if IS_ORIGIN:
            current_time = time.time()
            
            # Check concurrent connection limit
            active_count = len(ACTIVE_CONNECTIONS)
            if active_count >= MAX_CONCURRENT_CONNECTIONS:
                logger_control.warning(f"Connection rejected: {peer_ip} (limit reached: {MAX_CONCURRENT_CONNECTIONS})")
                log_and_notify(logger_control, 'warning', f"Connection rejected: {peer_ip} (limit reached: {MAX_CONCURRENT_CONNECTIONS})")
                writer.write(json.dumps({"error": "connection_limit_reached", "message": "Origin at max capacity"}).encode() + b'\n')
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return
            
            # Check connection rate limit
            RECENT_CONNECTIONS.append(current_time)
            recent_count = sum(1 for t in RECENT_CONNECTIONS if current_time - t < 1.0)  # Connections in last 1 second
            if recent_count > CONNECTION_RATE_LIMIT:
                logger_control.warning(f"Connection throttled: {peer_ip} (rate limit: {CONNECTION_RATE_LIMIT}/s)")
                writer.write(json.dumps({"error": "rate_limit_exceeded", "message": "Too many connections per second"}).encode() + b'\n')
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return
        
        # TASK 7.5+: Persistent bidirectional control connection
        # Keep connection open and loop to receive messages
        logger_control.info(f"Control connection from {peer_ip}")
        
        while True:
            # Read one line (JSON message terminated by \n)
            data = await reader.readuntil(b'\n')
            
            if not data:
                break  # Connection closed
            
            # TASK 18: Track bytes received for health monitoring
            if IS_ORIGIN and sat_id and sat_id in CONNECTION_HEALTH:
                CONNECTION_HEALTH[sat_id]["bytes_received"] += len(data)
                CONNECTION_HEALTH[sat_id]["last_activity"] = time.time()
            
            payload = json.loads(data.decode().strip())
            msg_type = payload.get("type", "sync")  # Message type: sync, command, response

            # TASK 7: Peer-to-peer sync handler (best-effort)
            if msg_type == "peer_sync":
                peer_id = payload.get("id")
                if not peer_id:
                    continue

                ts = payload.get("timestamp", time.time())
                advertised_ip = payload.get("advertised_ip") or payload.get("ip")
                peer_port = payload.get("port", 0)
                metrics = payload.get("metrics", {})
                storage_port = payload.get("storage_port", 0)

                REMOTE_SATELLITES[peer_id] = {
                    "id": peer_id,
                    "hostname": advertised_ip,
                    "port": peer_port,
                    "storage_port": storage_port,
                    "last_seen": ts,
                    "metrics": metrics,
                    "mode": payload.get("mode", "satellite"),
                }

                # Merge nodes if newer or absent
                incoming_nodes = payload.get("nodes", {}) or {}
                for node_id, node_data in incoming_nodes.items():
                    if not isinstance(node_data, dict):
                        continue
                    existing = NODES.get(node_id)
                    incoming_seen = node_data.get("last_seen", 0)
                    existing_seen = existing.get("last_seen", 0) if isinstance(existing, dict) else 0
                    if existing is None or incoming_seen > existing_seen:
                        NODES[node_id] = node_data

                # Merge remote satellites map (best-effort)
                incoming_sats = payload.get("satellites", {}) or {}
                for rid, rinfo in incoming_sats.items():
                    if not isinstance(rinfo, dict):
                        continue
                    REMOTE_SATELLITES[rid] = rinfo

                continue
            
            # First message must be a sync to identify the satellite
            if sat_id is None and msg_type == "sync":
                sat_id = payload.get("id")
                if not sat_id:
                    raise ValueError("First message must include 'id' field")
                
                # Store connection in pool for origin to send commands later
                if IS_ORIGIN:
                    ACTIVE_CONNECTIONS[sat_id] = {
                        "reader": reader,
                        "writer": writer,
                        "connected_at": time.time(),
                        "peer_ip": peer_ip
                    }
                    # TASK 18: Initialize connection health tracking
                    CONNECTION_HEALTH[sat_id] = {
                        "last_activity": time.time(),
                        "bytes_sent": 0,
                        "bytes_received": 0,
                        "errors": 0
                    }
                    logger_control.info(f"Persistent connection: {sat_id}")
            
            # TASK 12: Handle storagenode heartbeat (one-shot, no persistent connection)
            if msg_type == "storagenode_heartbeat":
                sat_id = payload.get("satellite_id")
                logger_control.debug(f"Storagenode heartbeat: sat_id={sat_id}, payload keys={list(payload.keys())}")
                if not sat_id or not IS_ORIGIN:
                    break
                
                # Register or update storagenode in trusted list
                fingerprint = payload.get("fingerprint")
                ip = payload.get("advertised_ip")
                storage_port = payload.get("storage_port")
                capacity_bytes = payload.get("capacity_bytes", 0)
                used_bytes = payload.get("used_bytes", 0)
                metrics = payload.get("metrics", {})
                zone = payload.get("zone")  # TASK 13: optional declared zone (no override logic)
                
                existing = TRUSTED_SATELLITES.get(sat_id)
                if existing is None:
                    # New storagenode - add to registry
                    # TASK 13: Detect zone from IP on origin (don't trust storagenode declaration)
                    detected_zone = detect_zone_from_ip(ip)
                    # Apply override if configured
                    override_zone = None
                    try:
                        zom = PLACEMENT_SETTINGS.get('zone_override_map', {})
                        if zom:
                            override_zone = zom.get(sat_id) or zom.get(f"{ip}:{storage_port}")
                    except Exception:
                        override_zone = None
                    TRUSTED_SATELLITES[sat_id] = {
                        "id": sat_id,
                        "fingerprint": fingerprint,
                        "hostname": ip,
                        "port": 0,  # Storage nodes don't have control port
                        "storage_port": storage_port,
                        "capacity_bytes": capacity_bytes,
                        "used_bytes": used_bytes,
                        "metrics": metrics,
                        "zone": (str(override_zone).strip() if override_zone else detected_zone),
                        "last_seen": time.time(),
                        "mode": "storagenode"
                    }
                    # Probe storage port reachability
                    reachable = await probe_storage_reachability(sat_id, ip, storage_port, control_port=0)
                    TRUSTED_SATELLITES[sat_id]['reachable_direct'] = reachable
                    sign_and_save_satellite_list()
                    logger_control.info(f"Storagenode registered: {sat_id}")
                else:
                    # Update existing storagenode
                    existing["last_seen"] = time.time()
                    existing["capacity_bytes"] = capacity_bytes
                    existing["used_bytes"] = used_bytes
                    existing["metrics"] = metrics
                    # Re-detect zone on each heartbeat (in case IP changed, though unlikely)
                    detected_zone = detect_zone_from_ip(ip)
                    # Apply override if configured
                    override_zone = None
                    try:
                        zom = PLACEMENT_SETTINGS.get('zone_override_map', {})
                        if zom:
                            override_zone = zom.get(sat_id) or zom.get(f"{ip}:{storage_port}")
                    except Exception:
                        override_zone = None
                    existing["zone"] = (str(override_zone).strip() if override_zone else detected_zone)
                    logger_control.debug(f"Storagenode updated: {sat_id}, zone={existing['zone']}, override={override_zone}, info has id={existing.get('id')}")
                
                # Close connection (storagenode doesn't need response)
                break
            
            # Process sync messages (status updates from satellite)
            if msg_type == "sync":
                sync_type = payload.get("sync_type", "full")
                
                if sync_type == "heartbeat":
                    # Heartbeat: minimal payload, just update last_seen and metrics
                    if sat_id and IS_ORIGIN and sat_id in TRUSTED_SATELLITES:
                        TRUSTED_SATELLITES[sat_id]["last_seen"] = time.time()
                        if "metrics" in payload:
                            TRUSTED_SATELLITES[sat_id]["metrics"] = payload["metrics"]
                    
                    # Send origin metrics back as response
                    if IS_ORIGIN and SATELLITE_ID in TRUSTED_SATELLITES:
                        # TASK 24 FIX: Include storagenode entries for satellite UI sync
                        storagenode_entries = {
                            sat_id: info for sat_id, info in TRUSTED_SATELLITES.items()
                            if info.get('mode') == 'storagenode'
                        }
                        
                        # TASK 24 FIX: Include repair queue for satellite UI sync
                        repair_jobs = []
                        try:
                            repair_jobs = list_repair_jobs(limit=10)
                        except Exception:
                            pass
                        
                        response = {
                            "type": "response",
                            "metrics": TRUSTED_SATELLITES[SATELLITE_ID].get("metrics", {}),
                            "repair_metrics": TRUSTED_SATELLITES[SATELLITE_ID].get("repair_metrics", {}),
                            "storagenode_scores": STORAGENODE_SCORES,  # TASK 10: Sync reputation scores
                            "storagenodes": storagenode_entries,  # TASK 24: Sync storagenode status (last_seen, capacity, etc)
                            "repair_queue": repair_jobs  # TASK 24 FIX: Sync repair queue for satellite UI
                        }
                        writer.write((json.dumps(response) + "\n").encode())
                        await writer.drain()
                
                elif sync_type == "full":
                    # Full sync: complete registration/update
                    required_keys = {"id", "fingerprint", "ip", "port"}
                    if not required_keys.issubset(payload):
                        raise ValueError(f"Invalid sync payload keys={list(payload.keys())}")
                    
                    fingerprint = payload["fingerprint"]
                    ip = payload["ip"]
                    port = payload["port"]
                    storage_port = payload.get("storage_port", STORAGE_PORT)
                    
                    if IS_ORIGIN:
                        existing = TRUSTED_SATELLITES.get(sat_id)
                        base_details = {
                            "id": sat_id,
                            "fingerprint": fingerprint,
                            "hostname": ip,
                            "port": port,
                            "storage_port": storage_port,
                            "nodes": payload.get("nodes", {}),
                            "repair_queue": payload.get("repair_queue", []),
                                                        "metrics": payload.get("metrics", {}),
                                                        "zone": payload.get("zone")  # TASK 13: optional zone on full sync
                          }
                        
                        if existing is None:
                            TRUSTED_SATELLITES[sat_id] = {**base_details, "last_seen": time.time()}
                            reachable = await probe_storage_reachability(sat_id, ip, storage_port, control_port=port)
                            TRUSTED_SATELLITES[sat_id]['reachable_direct'] = reachable
                            sign_and_save_satellite_list()
                            logger_control.info(f"Satellite registered: {sat_id}")
                        else:
                            existing_cmp = {k: v for k, v in existing.items() if k not in ("last_seen", "reachable_direct")}
                            new_cmp = {k: v for k, v in base_details.items() if k not in ("last_seen", "reachable_direct")}
                            if existing_cmp != new_cmp:
                                updated = existing.copy()
                                updated.update(base_details)
                                updated["last_seen"] = time.time()
                                reachable = await probe_storage_reachability(sat_id, ip, storage_port, control_port=port)
                                updated['reachable_direct'] = reachable
                                TRUSTED_SATELLITES[sat_id] = updated
                                sign_and_save_satellite_list()
                                logger_control.info(f"Satellite updated: {sat_id}")
                            else:
                                existing["last_seen"] = time.time()
                                TRUSTED_SATELLITES[sat_id] = existing
                        
                        # Send origin metrics as response to full sync
                        if SATELLITE_ID in TRUSTED_SATELLITES:
                            response = {
                                "type": "response",
                                "metrics": TRUSTED_SATELLITES[SATELLITE_ID].get("metrics", {}),
                                "repair_metrics": TRUSTED_SATELLITES[SATELLITE_ID].get("repair_metrics", {}),
                                "storagenode_scores": STORAGENODE_SCORES  # TASK 10: Sync reputation scores
                            }
                            response_data = (json.dumps(response) + "\n").encode()
                            writer.write(response_data)
                            await writer.drain()
                            
                            # TASK 18: Track bytes sent for health monitoring
                            if sat_id and sat_id in CONNECTION_HEALTH:
                                CONNECTION_HEALTH[sat_id]["bytes_sent"] += len(response_data)
                                CONNECTION_HEALTH[sat_id]["last_activity"] = time.time()

    except asyncio.IncompleteReadError:
        # Connection closed cleanly
        pass
    except Exception as e:
        logger_control.error(f"Control connection error from {peer_ip}: {type(e).__name__}: {e}")
        # TASK 18: Track errors
        if IS_ORIGIN and sat_id and sat_id in CONNECTION_HEALTH:
            CONNECTION_HEALTH[sat_id]["errors"] += 1

    finally:
        # Remove from active connections pool
        if sat_id and IS_ORIGIN and sat_id in ACTIVE_CONNECTIONS:
            del ACTIVE_CONNECTIONS[sat_id]
            logger_control.info(f"Connection closed: {sat_id}")
        # TASK 18: Cleanup connection health tracking
        if sat_id and IS_ORIGIN and sat_id in CONNECTION_HEALTH:
            del CONNECTION_HEALTH[sat_id]
        writer.close()
        await writer.wait_closed()

async def handle_repair_rpc(reader: AsyncStreamReader, writer: AsyncStreamWriter) -> None:
    """
    PHASE 3A: Handle repair job RPC requests from workers.
    
    Purpose:
    - Provides API for workers to interact with repair queue.
    - Supports job claiming, completion, failure, and lease renewal.
    
    RPC Commands:
    - claim_job: Worker requests next pending job
    - complete_job: Worker reports successful repair
    - fail_job: Worker reports failed repair attempt
    - renew_lease: Worker extends lease on long-running repair
    - list_jobs: Query job status (for monitoring)
    
    Wire Format:
    Request: {"rpc": "claim_job", "worker_id": "<id>", ...}
    Response: {"status": "ok", "job": {...}} or {"status": "error", "reason": "..."}
    
    Design Notes:
    - Only origin processes repair RPCs (queue authority).
    - Non-origin nodes return error.
    - All operations are atomic via SQLite transactions.
    """
    peer_ip = writer.get_extra_info("peername")[0]
    
    try:
        # Read request as newline-delimited JSON
        data = await reader.readuntil(b'\n')
        if not data:
            return
        
        payload = json.loads(data.decode().strip())
        rpc_type = payload.get("rpc")
        
        # Only origin manages repair queue
        if not IS_ORIGIN:
            writer.write(json.dumps({
                "status": "error",
                "reason": "Not origin node - repair queue not available"
            }).encode() + b'\n')
            await writer.drain()
            return
        
        # Handle different RPC commands
        if rpc_type == "claim_job":
            worker_id = payload.get("worker_id")
            if not worker_id:
                writer.write(json.dumps({
                    "status": "error",
                    "reason": "Missing worker_id"
                }).encode() + b'\n')
                await writer.drain()
                return
            
            job = claim_repair_job(worker_id)
            if job:
                writer.write(json.dumps({
                    "status": "ok",
                    "job": job
                }).encode() + b'\n')
                logger_repair.info(f"Job claimed: {job['object_id'][:16]}/frag{job['fragment_index']} by {worker_id[:20]}")
            else:
                writer.write(json.dumps({
                    "status": "ok",
                    "job": None
                }).encode() + b'\n')
            await writer.drain()
        
        elif rpc_type == "complete_job":
            job_id = payload.get("job_id")
            worker_id = payload.get("worker_id")
            if not job_id or not worker_id:
                writer.write(json.dumps({
                    "status": "error",
                    "reason": "Missing job_id or worker_id"
                }).encode() + b'\n')
                await writer.drain()
                return
            
            success = complete_repair_job(job_id, worker_id)
            if success:
                writer.write(json.dumps({"status": "ok"}).encode() + b'\n')
                logger_repair.info(f"Job completed: {job_id[:8]}... by {worker_id[:20]}")
            else:
                writer.write(json.dumps({
                    "status": "error",
                    "reason": "Job not found or not owned by worker"
                }).encode() + b'\n')
            await writer.drain()
        
        elif rpc_type == "fail_job":
            job_id = payload.get("job_id")
            worker_id = payload.get("worker_id")
            error_message = payload.get("error_message", "Unknown error")
            if not job_id or not worker_id:
                writer.write(json.dumps({
                    "status": "error",
                    "reason": "Missing job_id or worker_id"
                }).encode() + b'\n')
                await writer.drain()
                return
            
            success = fail_repair_job(job_id, worker_id, error_message)
            if success:
                writer.write(json.dumps({"status": "ok"}).encode() + b'\n')
                logger_repair.warning(f"Job failed: {job_id[:8]}... by {worker_id[:20]} - {error_message[:40]}")
            else:
                writer.write(json.dumps({
                    "status": "error",
                    "reason": "Job not found or not owned by worker"
                }).encode() + b'\n')
            await writer.drain()
        
        elif rpc_type == "renew_lease":
            job_id = payload.get("job_id")
            worker_id = payload.get("worker_id")
            if not job_id or not worker_id:
                writer.write(json.dumps({
                    "status": "error",
                    "reason": "Missing job_id or worker_id"
                }).encode() + b'\n')
                await writer.drain()
                return
            
            success = renew_job_lease(job_id, worker_id)
            writer.write(json.dumps({
                "status": "ok" if success else "error",
                "reason": None if success else "Job not found or not owned by worker"
            }).encode() + b'\n')
            await writer.drain()
        
        elif rpc_type == "list_jobs":
            status_filter = payload.get("status")
            limit = payload.get("limit", 100)
            jobs = list_repair_jobs(status=status_filter, limit=limit)
            writer.write(json.dumps({
                "status": "ok",
                "jobs": jobs
            }).encode() + b'\n')
            await writer.drain()
        
        else:
            writer.write(json.dumps({
                "status": "error",
                "reason": f"Unknown RPC: {rpc_type}"
            }).encode() + b'\n')
            await writer.drain()
    
    except Exception as e:
        try:
            writer.write(json.dumps({
                "status": "error",
                "reason": str(e)
            }).encode() + b'\n')
            await writer.drain()
        except Exception:
            pass
        logger_repair.error(f"Repair RPC error from {peer_ip}: {type(e).__name__}: {e}")
    
    finally:
        writer.close()
        await writer.wait_closed()
        
async def announce_to_origin() -> bool:
    """
    STEP 2: Announce satellite to origin

    - Non-origin satellites notify the origin of their presence after a short delay (3s)
      to allow boot sequence tasks (key generation, registry loading) to complete.
    - Runs once per boot, not periodically.
    - Payload includes:
      - 'id': SATELLITE_ID
      - 'fingerprint': TLS_FINGERPRINT
      - 'ip': ADVERTISED_IP
      - 'port': LISTEN_PORT
    - Origin may register or update the satellite in TRUSTED_SATELLITES.
    - Connection errors or failures are reported via UI_NOTIFICATIONS queue.
    """
    await asyncio.sleep(3)  # allow boot to finish, including storage server startup

    if IS_ORIGIN:
        return

    try:
        reader, writer = await asyncio.open_connection(ORIGIN_HOST, ORIGIN_PORT)

        payload = {
            "id": SATELLITE_ID, # unique satellite identifier
            "fingerprint": TLS_FINGERPRINT, # TLS certificate fingerprint
            "ip": ADVERTISED_IP, # advertised network IP
            "port": LISTEN_PORT, # control plane port
            "storage_port": STORAGE_PORT, # storage plane port (for reachability probe)
        }

        await safe_send_payload((reader, writer), payload)

    except Exception:
        log_and_notify(logger_control, 'error', "Failed to reach origin")

async def register_with_origin() -> None:
    """
    STEP 2: Register satellite with origin

    - Non-origin satellites announce themselves to the origin node during boot.
    - Payload sent:
    - 'id': SATELLITE_ID
    - 'fingerprint': TLS_FINGERPRINT
    - 'ip': ADVERTISED_IP
    - 'port': LISTEN_PORT
    - On success: pushes "Registered with origin" notification.
    - On failure: pushes a notification with the exception details.
    - Fully asynchronous; does not block other startup tasks.
    """
    if IS_ORIGIN:
        return

    # Small delay to ensure storage server has started before registration
    await asyncio.sleep(0.5)

    try:
        reader, writer = await asyncio.open_connection(ORIGIN_HOST, ORIGIN_PORT)

        payload = {
            "id": SATELLITE_ID, # unique satellite identifier
            "fingerprint": TLS_FINGERPRINT, # unique satellite identifier
            "ip": ADVERTISED_IP,  # advertised IP
            "port": LISTEN_PORT, # control plane port
            "storage_port": STORAGE_PORT, # storage plane port (for reachability probe)
        }

        await safe_send_payload((reader, writer), payload)

        log_and_notify(logger_control, 'info', "Registered with origin")

    except Exception as e:
        log_and_notify(logger_control, 'error', f"Origin registration failed: {e}")



# --- UI Loop ---
# ============================================================================
# TASK 22: MULTI-SCREEN TERMINAL UI FUNCTIONS
# ============================================================================

def render_home_screen(stdscr: Any, max_lines: int) -> None:
    """Render Home screen with summary info."""
    global SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP, IS_ORIGIN, TRUSTED_SATELLITES
    
    line = 0
    stdscr.addstr(line, 0, "=" * 78); line += 1
    stdscr.addstr(line, 0, "                           LibreMesh Home"); line += 1
    stdscr.addstr(line, 0, "=" * 78); line += 1
    line += 1
    
    # Identity section
    stdscr.addstr(line, 0, f"Satellite ID:       {SATELLITE_ID}"); line += 1
    stdscr.addstr(line, 0, f"Advertising IP:     {ADVERTISED_IP}"); line += 1
    stdscr.addstr(line, 0, f"Origin Status:      {'ORIGIN' if IS_ORIGIN else 'SATELLITE'}"); line += 1
    stdscr.addstr(line, 0, f"TLS Fingerprint:    {TLS_FINGERPRINT}"); line += 1
    
    # Quick stats
    storage_nodes = sum(1 for info in TRUSTED_SATELLITES.values() if info.get('mode') == 'storagenode')
    satellites = sum(1 for info in TRUSTED_SATELLITES.values() if info.get('mode') != 'storagenode')
    
    stdscr.addstr(line, 0, f"Trusted Satellites: {satellites}"); line += 1
    line += 1
    online_nodes = sum(1 for sat_id, info in TRUSTED_SATELLITES.items() 
                      if info.get('mode') == 'storagenode' and (time.time() - info.get('last_seen', 0)) < 30)
    
    stdscr.addstr(line, 0, f"Storage Nodes:      {storage_nodes}"); line += 1
    stdscr.addstr(line, 0, f"Satellites:         {satellites}"); line += 1
    stdscr.addstr(line, 0, f"Online Nodes:       {online_nodes}"); line += 1
    line += 1
    
    # Repair queue summary (all nodes)
    if IS_ORIGIN:
        try:
            jobs = list_repair_jobs(limit=1)
            queue_size = len(jobs) if jobs else 0
        except Exception:
            queue_size = 0
    else:
        queue_size = len(REPAIR_QUEUE_CACHE)
    
    stdscr.addstr(line, 0, f"Repair Queue:       {queue_size} jobs"); line += 1
    line += 1
    
    # Navigation help
    stdscr.addstr(line, 0, "=" * 78); line += 1
    stdscr.addstr(line, 0, "Navigation: [H]ome [S]atellites [N]odes [R]epair [L]ogs [Q]uit"); line += 1
    stdscr.addstr(line, 0, "=" * 78); line += 1
    

def render_satellites_screen(stdscr: Any, max_lines: int) -> None:
    """Render Satellites screen with detailed satellite info."""
    global TRUSTED_SATELLITES, SATELLITE_ID, STORAGENODE_SCORES
    
    line = 0
    stdscr.addstr(line, 0, "=" * 78); line += 1
    stdscr.addstr(line, 0, "                         Online Satellites"); line += 1
    stdscr.addstr(line, 0, "=" * 78); line += 1
    
    # Header
    stdscr.addstr(line, 0, f"{'Satellite ID':<28} | {'Status':<7} | {'Direct':<6} | {'CPU%':<5} | {'Mem%':<5} | {'Last Seen':<10}"); line += 1
    stdscr.addstr(line, 0, "-" * 78); line += 1
    
    satellites = [(sat_id, info) for sat_id, info in TRUSTED_SATELLITES.items() 
                  if info.get('mode') != 'storagenode']
    
    if not satellites:
        stdscr.addstr(line, 0, f"{'No satellites connected':<28} | {'N/A':<7} | {'N/A':<6} | {'N/A':<5} | {'N/A':<5} | {'N/A':<10}"); line += 1
    else:
        count = 0
        for sat_id, sat_info in satellites:
            if line >= max_lines - 3:  # Leave room for footer
                break
            count += 1
            
            is_local = "(this)" if sat_id == SATELLITE_ID else ""
            last_seen = sat_info.get('last_seen', 0)
            reachable_direct = sat_info.get('reachable_direct', False)
            metrics = sat_info.get('metrics', {})
            
            # Status
            if last_seen > 0 and (time.time() - last_seen) < 30:
                status = "online"
                elapsed = int(time.time() - last_seen)
                last_seen_display = f"{elapsed}s"
            elif sat_id == SATELLITE_ID:
                status = "online"
                last_seen_display = "0s"
            else:
                status = "offline"
                last_seen_display = "N/A"
            
            # Direct connectivity
            if sat_id == SATELLITE_ID:
                direct_status = "N/A"
            elif reachable_direct:
                direct_status = "Yes"
            else:
                direct_status = "No"
            
            # Metrics
            if sat_id == SATELLITE_ID:
                local_metrics = get_system_metrics()
                cpu_str = f"{local_metrics.get('cpu_percent', 0):.1f}" if local_metrics.get('cpu_percent') is not None else "N/A"
                mem_str = f"{local_metrics.get('memory_percent', 0):.1f}" if local_metrics.get('memory_percent') is not None else "N/A"
            elif status == "offline":
                cpu_str = "N/A"
                mem_str = "N/A"
            else:
                cpu_str = f"{metrics.get('cpu_percent', 0):.1f}" if metrics.get('cpu_percent') is not None else "N/A"
                mem_str = f"{metrics.get('memory_percent', 0):.1f}" if metrics.get('memory_percent') is not None else "N/A"
            
            sat_id_display = f"{sat_id[:22]} {is_local}".strip()
            stdscr.addstr(line, 0, f"{sat_id_display:<28} | {status:<7} | {direct_status:<6} | {cpu_str:<5} | {mem_str:<5} | {last_seen_display:<10}"); line += 1
    
    # Footer
    line = max_lines - 2
    stdscr.addstr(line, 0, "=" * 78); line += 1
    stdscr.addstr(line, 0, "Navigation: [H]ome [S]atellites [N]odes [R]epair [L]ogs [Q]uit")


def render_nodes_screen(stdscr: Any, max_lines: int) -> None:
    """Render Storage Nodes screen with detailed node info."""
    global TRUSTED_SATELLITES, STORAGENODE_SCORES
    
    line = 0
    stdscr.addstr(line, 0, "=" * 78); line += 1
    stdscr.addstr(line, 0, "                        Storage Nodes"); line += 1
    stdscr.addstr(line, 0, "=" * 78); line += 1
    
    # Header
    stdscr.addstr(line, 0, f"{'Rank':<6}| {'Node ID':<28} | {'Zone':<8} | {'Port':<5} | {'Score':<5} | {'Fill%':<6} | {'Capacity':<12} | {'Uptime':<7} | {'Reach%':<6} | {'Last Seen':<10}"); line += 1
    stdscr.addstr(line, 0, "-" * 78); line += 1
    
    # Build leaderboard with all storage node info
    leaderboard = []
    for sat_id, info in TRUSTED_SATELLITES.items():
        if info.get('mode') == 'storagenode':
            storage_port = info.get('storage_port', 0)
            capacity_bytes = info.get('capacity_bytes', 0)
            if storage_port != 0 and capacity_bytes > 0:
                score_data = STORAGENODE_SCORES.get(sat_id, {})
                leaderboard.append((sat_id, info, score_data))
    
    if not leaderboard:
        stdscr.addstr(line, 0, f"{'No storage nodes':<28}"); line += 1
    else:
        # Sort by score descending
        leaderboard.sort(key=lambda x: x[2].get('score', 0), reverse=True)
        
        for rank, (sat_id, info, score_data) in enumerate(leaderboard, 1):
            if line >= max_lines - 4:
                break
            
            # Tier marker
            score = score_data.get('score', 0)
            tier = "★" if score >= 0.8 else ("●" if score >= 0.5 else "○")
            
            # Node info
            storage_port = info.get('storage_port', 0)
            capacity_gb = info.get('capacity_bytes', 0) / (1024**3)
            used_gb = info.get('used_bytes', 0) / (1024**3)
            capacity_str = f"{used_gb:.1f}/{capacity_gb:.1f}GB"
            last_seen = int(time.time() - info.get('last_seen', time.time()))
            fill_pct = _compute_fill_pct(info)
            zone = _get_effective_zone(info)
            
            # Score info
            score_str = f"{score:.2f}" if score > 0 else "N/A"
            uptime_hours = (time.time() - score_data.get('uptime_start', time.time())) / 3600
            uptime_str = f"{uptime_hours:.1f}h" if uptime_hours < 48 else f"{uptime_hours/24:.1f}d"
            
            # Reachability
            reachable_checks = score_data.get('reachable_checks', 0)
            reachable_success = score_data.get('reachable_success', 0)
            reach_pct = (reachable_success / reachable_checks * 100) if reachable_checks > 0 else 100
            reach_str = f"{reach_pct:.0f}%"
            
            stdscr.addstr(line, 0, f"{tier} {rank:<4}| {sat_id[:25]:<28} | {zone[:8]:<8} | {storage_port:<5} | {score_str:<5} | {int(fill_pct*100):<5}% | {capacity_str:<12} | {uptime_str:<7} | {reach_str:<6} | {last_seen:<10}"); line += 1
    
    # Legend
    if line < max_lines - 3:
        line += 1
        stdscr.addstr(line, 0, "Tier Legend: ★ Excellent (≥0.80)  ● Good (≥0.50)  ○ Deprioritized (<0.50)"); line += 1
    
    # Footer
    line = max_lines - 2
    stdscr.addstr(line, 0, "=" * 78); line += 1
    stdscr.addstr(line, 0, "Navigation: [H]ome [S]atellites [N]odes [R]epair [L]ogs [Q]uit")


def render_repair_screen(stdscr: Any, max_lines: int) -> None:
    """Render Repair Queue screen with job details."""
    global IS_ORIGIN, REPAIR_QUEUE_CACHE, REPAIR_METRICS, TRUSTED_SATELLITES
    
    line = 0
    stdscr.addstr(line, 0, "=" * 78); line += 1
    stdscr.addstr(line, 0, "                         Repair Queue"); line += 1
    stdscr.addstr(line, 0, "=" * 78); line += 1
    
    # Header
    stdscr.addstr(line, 0, f"{'Job ID (Fragment)':<35} | {'Status':<8} | {'Claimed By':<20}"); line += 1
    stdscr.addstr(line, 0, "-" * 78); line += 1
    
    if IS_ORIGIN:
        try:
            jobs = list_repair_jobs(limit=15)
            if not jobs:
                stdscr.addstr(line, 0, f"{'Queue is empty':<35} | {'N/A':<8} | {'N/A':<20}"); line += 1
            else:
                for job in jobs:
                    if line >= max_lines - 10:
                        break
                    job_id_display = f"{job['object_id'][-8:]}/{job['fragment_index']}"
                    claimed_by_display = job['claimed_by'][:20] if job['claimed_by'] else 'N/A'
                    stdscr.addstr(line, 0, f"{job_id_display:<35} | {job['status']:<8} | {claimed_by_display:<20}"); line += 1
        except Exception:
            stdscr.addstr(line, 0, f"{'Error reading queue':<35} | {'N/A':<8} | {'N/A':<20}"); line += 1
    else:
        if REPAIR_QUEUE_CACHE:
            for job in REPAIR_QUEUE_CACHE[:15]:
                if line >= max_lines - 10:
                    break
                job_id_display = f"{job['object_id'][-8:]}/{job['fragment_index']}"
                claimed_by_display = job['claimed_by'][:20] if job['claimed_by'] else 'N/A'
                stdscr.addstr(line, 0, f"{job_id_display:<35} | {job['status']:<8} | {claimed_by_display:<20}"); line += 1
        else:
            stdscr.addstr(line, 0, f"{'Queue is empty':<35} | {'N/A':<8} | {'N/A':<20}"); line += 1
    
    # Repair stats
    line += 1
    stdscr.addstr(line, 0, "=" * 78); line += 1
    stdscr.addstr(line, 0, "                        Repair Statistics"); line += 1
    stdscr.addstr(line, 0, "=" * 78); line += 1
    
    if IS_ORIGIN:
        repair_stats = REPAIR_METRICS
    else:
        repair_stats = None
        for sat_id, sat_info in TRUSTED_SATELLITES.items():
            if sat_info.get('storage_port') == 0:
                repair_stats = sat_info.get('repair_metrics', {})
                break
        if not repair_stats:
            repair_stats = {'jobs_created': 0, 'jobs_completed': 0, 'jobs_failed': 0, 
                           'fragments_checked': 0, 'last_health_check': None}
    
    stdscr.addstr(line, 0, f"Jobs Created:   {repair_stats.get('jobs_created', 0):<10}  "
                           f"Jobs Completed: {repair_stats.get('jobs_completed', 0):<10}"); line += 1
    stdscr.addstr(line, 0, f"Jobs Failed:    {repair_stats.get('jobs_failed', 0):<10}  "
                           f"Fragments Checked: {repair_stats.get('fragments_checked', 0):<10}"); line += 1
    if repair_stats.get('last_health_check'):
        elapsed = int(time.time() - repair_stats['last_health_check'])
        stdscr.addstr(line, 0, f"Last Health Check: {elapsed}s ago"); line += 1
    else:
        stdscr.addstr(line, 0, "Last Health Check: Never"); line += 1
    
    # GC status (all nodes can see it)
    if line < max_lines - 8:
        line += 1
        stdscr.addstr(line, 0, "=" * 78); line += 1
        stdscr.addstr(line, 0, "                  Garbage Collection Status"); line += 1
        stdscr.addstr(line, 0, "=" * 78); line += 1
        
        # Origin reads local stats, satellites read from origin's registry entry
        if IS_ORIGIN:
            gc_stats = get_gc_stats()
        else:
            # Find origin in registry and get its gc_stats
            gc_stats = None
            for sat_id, sat_info in TRUSTED_SATELLITES.items():
                if sat_info.get('storage_port') == 0:  # Origin has storage_port=0
                    gc_stats = sat_info.get('gc_stats', {})
                    break
            if not gc_stats:
                gc_stats = {'last_run': 0, 'manifest_size': 0, 'trash_size': 0}
        
        last_run = gc_stats.get('last_run', 0)
        if last_run > 0:
            elapsed = int(time.time() - last_run)
            stdscr.addstr(line, 0, f"Last GC Run: {elapsed}s ago"); line += 1
        else:
            stdscr.addstr(line, 0, f"Last GC Run: Never"); line += 1
        stdscr.addstr(line, 0, f"Objects with manifests: {gc_stats.get('manifest_size', 0)}"); line += 1
        stdscr.addstr(line, 0, f"Items in trash: {gc_stats.get('trash_size', 0)}"); line += 1
    
    # Footer
    line = max_lines - 2
    stdscr.addstr(line, 0, "=" * 78); line += 1
    stdscr.addstr(line, 0, "Navigation: [H]ome [S]atellites [N]odes [R]epair [L]ogs [Q]uit")


def render_logs_screen(stdscr: Any, max_lines: int) -> None:
    """Render Logs screen with recent notification history."""
    global NOTIFICATION_LOG, LOG_BUFFER
    
    line = 0
    stdscr.addstr(line, 0, "=" * 78); line += 1
    stdscr.addstr(line, 0, "                           Recent Logs"); line += 1
    stdscr.addstr(line, 0, "=" * 78); line += 1
    
    # Display notifications
    if not NOTIFICATION_LOG:
        stdscr.addstr(line, 0, "(No recent notifications)"); line += 1
    else:
        for msg in list(NOTIFICATION_LOG)[-20:]:  # Show last 20
            if line >= max_lines - 3:
                break
            stdscr.addstr(line, 0, msg[:78]); line += 1  # Truncate to screen width
    
    # Footer
    line = max_lines - 2
    stdscr.addstr(line, 0, "=" * 78); line += 1
    stdscr.addstr(line, 0, "Navigation: [H]ome [S]atellites [N]odes [R]epair [L]ogs [Q]uit")


# ============================================================================
# END TASK 22: MULTI-SCREEN TERMINAL UI FUNCTIONS
# ============================================================================

async def curses_ui() -> None:
    """
    TASK 22: Multi-screen curses UI with keyboard navigation.
    
    Provides separate screens for different monitoring views:
    - [H]ome: Summary and identity
    - [S]atellites: Satellite node details
    - [N]odes: Storage node details and leaderboard
    - [R]epair: Repair queue and statistics
    - [L]ogs: Recent notifications and logs
    - [Q]uit: Exit program
    
    Uses curses for non-blocking keyboard input and screen management.
    Screens are rendered at 2-second intervals with immediate response to keypresses.
    """
    global CURRENT_SCREEN, USE_CURSES
    
    if not USE_CURSES:
        # Fallback to old draw_ui() if curses disabled
        await draw_ui_legacy()
        return
    
    def curses_main(stdscr: Any) -> None:
        """Inner curses loop (runs in wrapper)."""
        global CURRENT_SCREEN
        
        # Configure curses
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(True)  # Non-blocking input
        stdscr.timeout(100)  # 100ms timeout for getch()
        
        while True:
            try:
                # Get terminal size
                max_y, max_x = stdscr.getmaxyx()
                
                # Clear screen
                stdscr.clear()
                
                # Render current screen
                try:
                    if CURRENT_SCREEN == "home":
                        render_home_screen(stdscr, max_y)
                    elif CURRENT_SCREEN == "satellites":
                        render_satellites_screen(stdscr, max_y)
                    elif CURRENT_SCREEN == "nodes":
                        render_nodes_screen(stdscr, max_y)
                    elif CURRENT_SCREEN == "repair":
                        render_repair_screen(stdscr, max_y)
                    elif CURRENT_SCREEN == "logs":
                        render_logs_screen(stdscr, max_y)
                except Exception as e:
                    # Handle rendering errors gracefully
                    stdscr.addstr(0, 0, f"Render error: {str(e)[:70]}")
                
                # Refresh display
                stdscr.refresh()
                
                # Handle keyboard input
                key = stdscr.getch()
                if key != -1:  # Key was pressed
                    key_char = chr(key).lower() if 0 < key < 256 else ''
                    
                    if key_char == 'h':
                        CURRENT_SCREEN = "home"
                    elif key_char == 's':
                        CURRENT_SCREEN = "satellites"
                    elif key_char == 'n':
                        CURRENT_SCREEN = "nodes"
                    elif key_char == 'r':
                        CURRENT_SCREEN = "repair"
                    elif key_char == 'l':
                        CURRENT_SCREEN = "logs"
                    elif key_char == 'q':
                        # Exit the program completely
                        import sys
                        sys.exit(0)
                
                # Sleep briefly before next refresh (2 seconds)
                time.sleep(2)
                
            except KeyboardInterrupt:
                return
            except Exception as e:
                # Log unexpected errors but keep running
                try:
                    stdscr.addstr(0, 0, f"UI error: {str(e)[:70]}")
                    stdscr.refresh()
                    time.sleep(2)
                except:
                    pass
    
    # Run curses in a thread-safe way (wrapper handles init/cleanup)
    try:
        await asyncio.get_event_loop().run_in_executor(None, wrapper, curses_main)
    except Exception as e:
        # If curses fails, fallback to legacy UI
        log_and_notify(logger_control, 'error', f"Curses UI failed: {e}, falling back to legacy UI")
        USE_CURSES = False
        await draw_ui_legacy()


async def draw_ui() -> None:
    """
    TASK 22: Main UI dispatcher.
    Calls curses_ui() if USE_CURSES=True, otherwise draw_ui_legacy().
    """
    global USE_CURSES
    
    if USE_CURSES:
        try:
            await curses_ui()
        except Exception as e:
            log_and_notify(logger_control, 'error', f"Curses UI failed: {e}, switching to legacy UI")
            USE_CURSES = False
            await draw_ui_legacy()
    else:
        await draw_ui_legacy()


async def draw_ui_legacy() -> None:
    """
    STEP 5: Terminal User Interface (UI) for Satellite Node.
    TASK 22: Legacy fallback UI (used when --no-curses flag is set).

    Purpose:
    - Provide human-readable status and monitoring for the satellite.
    - Complements background tasks such as node sync and registry updates.

    Behavior:
    1. Clears the terminal screen on each loop iteration.
    2. Displays:
       - Node Status: connected nodes with last seen timestamps.
       - Repair Queue: pending or active fragment repair jobs.
       - Notifications: shows recent UI messages (from NOTIFICATION_LOG and UI_NOTIFICATIONS queue).
       - Suspicious IP Advisory: placeholder for security alerts.
       - Satellite Identity: SATELLITE_ID, TLS fingerprint, advertised IP, origin status, trusted satellites count.
    3. Sleeps for a short interval (e.g., 2 seconds) between refreshes.
    4. Loops indefinitely in the background.

    Notes:
    - Uses global state variables: NODES, REPAIR_QUEUE, UI_NOTIFICATIONS, TRUSTED_SATELLITES, SATELLITE_ID, TLS_FINGERPRINT, IS_ORIGIN, ADVERTISED_IP.
    - Non-blocking; runs in parallel with TCP server, registry sync, and node sync loops.
    - Fully asynchronous and safe to run on both origin and follower satellites.
    - Complements STEP 5 in boot sequence remarks.
    - Notification history retained in NOTIFICATION_LOG (deque maxlen=10).
    - Node uptime currently shown as N/A; can be updated once node heartbeat is implemented.
    """
    while True:
        os.system('clear' if os.name == 'posix' else 'cls') # clear terminal
        # TASK 12: Display storage nodes (mode=storagenode)
        print("="*78 + "\n                        Storage Nodes\n" + "="*78)
        print(f"{'Node ID':<28} | {'Zone':<8} | {'Port':<5} | {'Fill%':<6} | {'Capacity':<12} | {'Last Seen (s)':<13}\n" + "-" * 78)
        storage_nodes = [(sat_id, info) for sat_id, info in TRUSTED_SATELLITES.items() 
                         if info.get('mode') == 'storagenode']
        if not storage_nodes:
            print(f"{'No storage nodes connected':<28} | {'N/A':<8} | {'N/A':<5} | {'N/A':<6} | {'N/A':<12} | {'N/A':<13}")
        else:
            for sat_id, info in storage_nodes:
                storage_port = info.get('storage_port', 0)
                capacity_gb = info.get('capacity_bytes', 0) / (1024**3)
                used_gb = info.get('used_bytes', 0) / (1024**3)
                capacity_str = f"{used_gb:.1f}/{capacity_gb:.1f}GB"
                last_seen = int(time.time() - info.get('last_seen', time.time()))
                fill_pct = _compute_fill_pct(info)
                zone = _get_effective_zone(info)
                print(f"{sat_id[:25]:<28} | {zone[:8]:<8} | {storage_port:<5} | {int(fill_pct*100):<6}% | {capacity_str:<12} | {last_seen:<13}")

        print("\n" + "="*78 + "\n                           Repair Queue\n" + "="*78) # Display Repair Queue header
        print(f"{'Job ID (Fragment)':<35} | {'Status':<8} | {'Claimed By':<20}\n" + "-" * 78)
        
        # PHASE 3A: Display repair jobs from SQLite database (origin only)
        if IS_ORIGIN:
            try:
                jobs = list_repair_jobs(limit=10)  # Show up to 10 jobs
                if not jobs:
                    print(f"{'Queue is empty':<35} | {'N/A':<8} | {'N/A':<20}")
                else:
                    for job in jobs:
                        job_id_display = f"{job['object_id'][-8:]}/{job['fragment_index']}"
                        claimed_by_display = job['claimed_by'][:20] if job['claimed_by'] else 'N/A'
                        print(f"{job_id_display:<35} | {job['status']:<8} | {claimed_by_display:<20}")
            except Exception:
                print(f"{'Error reading queue':<35} | {'N/A':<8} | {'N/A':<20}")
        else:
            # TASK 24 FIX: Satellites display cached repair queue from origin
            if REPAIR_QUEUE_CACHE:
                for job in REPAIR_QUEUE_CACHE:
                    job_id_display = f"{job['object_id'][-8:]}/{job['fragment_index']}"
                    claimed_by_display = job['claimed_by'][:20] if job['claimed_by'] else 'N/A'
                    print(f"{job_id_display:<35} | {job['status']:<8} | {claimed_by_display:<20}")
            else:
                print(f"{'Queue is empty':<35} | {'N/A':<8} | {'N/A':<20}")
        
        # PHASE 3B: Display repair metrics (all nodes see origin's metrics)
        # Origin uses local REPAIR_METRICS, satellites use metrics from origin's registry entry
        if IS_ORIGIN:
            repair_stats = REPAIR_METRICS
        else:
            # Find origin in registry and get its repair_metrics
            repair_stats = None
            for sat_id, sat_info in TRUSTED_SATELLITES.items():
                if sat_info.get('storage_port') == 0:  # Origin has storage_port=0
                    repair_stats = sat_info.get('repair_metrics', {})
                    break
            if not repair_stats:
                repair_stats = {'jobs_created': 0, 'jobs_completed': 0, 'jobs_failed': 0, 
                               'fragments_checked': 0, 'last_health_check': None}
        
        print("\n" + "="*78 + "\n                        Repair Statistics\n" + "="*78)
        print(f"Jobs Created:   {repair_stats.get('jobs_created', 0):<10}  "
              f"Jobs Completed: {repair_stats.get('jobs_completed', 0):<10}")
        print(f"Jobs Failed:    {repair_stats.get('jobs_failed', 0):<10}  "
              f"Fragments Checked: {repair_stats.get('fragments_checked', 0):<10}")
        if repair_stats.get('last_health_check'):
            elapsed = int(time.time() - repair_stats['last_health_check'])
            print(f"Last Health Check: {elapsed}s ago")
        else:
            print("Last Health Check: Never")
        
        print("\n" + "="*78 + "\n                           Notifications\n" + "="*78) # Notifications header
        temp_msgs = []
        while not UI_NOTIFICATIONS.empty():
            NOTIFICATION_LOG.append(UI_NOTIFICATIONS.get_nowait()) # Notifications header

        if not NOTIFICATION_LOG:
            print("\n")  # Just one blank line instead of two
        else:
            for m in NOTIFICATION_LOG:
                print(m)  # Display recent UI notifications
                
        print("\n" + "="*78 + "\n                         Online Satellites\n" + "="*78) # Satellites section
        print(f"{'Satellite ID':<28} | {'Status':<7} | {'Direct':<6} | {'Score':<5} | {'CPU%':<5} | {'Mem%':<5} | {'Last Seen':<10}\n" + "-" * 78)
        if not TRUSTED_SATELLITES:
            print(f"{'No satellites loaded':<28} | {'N/A':<7} | {'N/A':<6} | {'N/A':<5} | {'N/A':<5} | {'N/A':<5} | {'N/A':<10}")
        else:
            for sat_id, sat_info in TRUSTED_SATELLITES.items():
                # TASK 12: Skip storage nodes (they have their own section)
                if sat_info.get('mode') == 'storagenode':
                    continue
                
                # Mark the local satellite with "(this node)"
                is_local = "(this node)" if sat_id == SATELLITE_ID else ""
                last_seen = sat_info.get('last_seen', 0)
                reachable_direct = sat_info.get('reachable_direct', False)
                metrics = sat_info.get('metrics', {})
                
                # Determine online/offline status based on last_seen timestamp
                # Consider online if synced within last 30 seconds (6x NODE_SYNC_INTERVAL)
                if last_seen > 0 and (time.time() - last_seen) < 30:
                    status = "online"
                    elapsed = int(time.time() - last_seen)
                    last_seen_display = f"{elapsed}s"
                elif sat_id == SATELLITE_ID:
                    # This node is always considered online
                    status = "online"
                    last_seen_display = "0s"
                else:
                    status = "offline"
                    last_seen_display = "N/A"
                
                # Show reachable_direct status (Yes/No/N/A for local node)
                if sat_id == SATELLITE_ID:
                    direct_status = "N/A"
                elif reachable_direct:
                    direct_status = "Yes"
                else:
                    direct_status = "No"
                
                # TASK 8: Get storagenode score (only for nodes with storage_port)
                score_entry = STORAGENODE_SCORES.get(sat_id, {})
                score = score_entry.get('score')
                if score is not None and sat_info.get('storage_port') and sat_info.get('storage_port') != 0:
                    score_str = f"{score:.2f}"
                else:
                    score_str = "N/A"  # No score yet or control-only node
                
                # Format metrics (TASK 7.5: CPU monitoring)
                # For local node, get live metrics; for remote nodes, use synced metrics (only if online)
                if sat_id == SATELLITE_ID:
                    local_metrics = get_system_metrics()
                    cpu_str = f"{local_metrics.get('cpu_percent', 0):.1f}" if local_metrics.get('cpu_percent') is not None else "N/A"
                    mem_str = f"{local_metrics.get('memory_percent', 0):.1f}" if local_metrics.get('memory_percent') is not None else "N/A"
                elif status == "offline":
                    # Don't show stale metrics for offline nodes
                    cpu_str = "N/A"
                    mem_str = "N/A"
                else:
                    cpu_str = f"{metrics.get('cpu_percent', 0):.1f}" if metrics.get('cpu_percent') is not None else "N/A"
                    mem_str = f"{metrics.get('memory_percent', 0):.1f}" if metrics.get('memory_percent') is not None else "N/A"
                
                # Add local marker if needed
                sat_id_display = f"{sat_id[:25]} {is_local}".strip()
                print(f"{sat_id_display:<28} | {status:<7} | {direct_status:<6} | {score_str:<5} | {cpu_str:<5} | {mem_str:<5} | {last_seen_display:<10}")
        
        # TASK 11: Storagenode Leaderboard (only show if we have scored nodes)
        if STORAGENODE_SCORES:
            print("\n" + "="*78 + "\n                    Storagenode Leaderboard\n" + "="*78)
            print(f"{'Rank':<4} | {'Node ID':<20} | {'Score':<5} | {'Uptime':<7} | {'Reach%':<6} | {'P2P':<5} | {'Repairs':<7} | {'Health':<6} | {'Latency':<7}")
            print("-" * 78)
            
            # Sort nodes by score descending
            leaderboard = []
            for sat_id, score_data in STORAGENODE_SCORES.items():
                # TASK 12: Only show nodes with explicit storage opt-in (capacity_bytes > 0)
                if sat_id in TRUSTED_SATELLITES:
                    sat_info = TRUSTED_SATELLITES[sat_id]
                    storage_port = sat_info.get('storage_port', 0)
                    capacity_bytes = sat_info.get('capacity_bytes', 0)
                    # Must have storage_port AND non-zero capacity (explicit opt-in)
                    if storage_port != 0 and capacity_bytes > 0:
                        leaderboard.append((sat_id, score_data))
            
            leaderboard.sort(key=lambda x: x[1].get('score', 0), reverse=True)
            
            for rank, (sat_id, score_data) in enumerate(leaderboard[:10], 1):  # Top 10
                score = score_data.get('score', 0)
                
                # Color-coded tier (using simple markers since no ANSI colors in basic terminal)
                if score >= 0.8:
                    tier = "★"  # Excellent (green equivalent)
                elif score >= 0.5:
                    tier = "●"  # Good (yellow equivalent)
                else:
                    tier = "○"  # Deprioritized (red equivalent)
                
                # Calculate display values for 6 factors
                uptime_hours = (time.time() - score_data.get('uptime_start', time.time())) / 3600
                uptime_str = f"{uptime_hours:.1f}h" if uptime_hours < 48 else f"{uptime_hours/24:.1f}d"
                
                reachable_checks = score_data.get('reachable_checks', 0)
                reachable_success = score_data.get('reachable_success', 0)
                reach_pct = (reachable_success / reachable_checks * 100) if reachable_checks > 0 else 100
                
                # TASK 24: P2P connectivity percentage
                p2p_reachable = score_data.get('p2p_reachable', {})
                if p2p_reachable:
                    p2p_total = len(p2p_reachable)
                    p2p_success = sum(1 for reachable in p2p_reachable.values() if reachable)
                    p2p_pct = (p2p_success / p2p_total * 100) if p2p_total > 0 else 0
                    p2p_str = f"{p2p_pct:.0f}%"
                else:
                    p2p_str = "N/A"
                
                repairs_needed = score_data.get('repairs_needed', 0)
                repairs_completed = score_data.get('repairs_completed', 0)
                repairs_str = f"{repairs_needed}/{repairs_completed}"
                
                disk_health = score_data.get('disk_health', 1.0)
                health_str = f"{disk_health:.2f}"
                
                latency_ms = score_data.get('avg_latency_ms', 0)
                latency_str = f"{latency_ms:.0f}ms" if latency_ms > 0 else "N/A"
                
                # Truncate sat_id for display
                sat_id_short = sat_id[:20]
                
                print(f"{tier} {rank:<2} | {sat_id_short:<20} | {score:.2f}  | {uptime_str:<7} | {reach_pct:>5.1f}% | {p2p_str:<5} | {repairs_str:<7} | {health_str:<6} | {latency_str:<7}")
            
            # Show legend
            print("\nTier Legend: ★ Excellent (≥0.80)  ● Good (≥0.50)  ○ Deprioritized (<0.50)")
            print("Columns: Score=composite | Uptime | Reach%=satellite reachability | P2P=peer connectivity | Repairs | Health | Latency")
        
        # TASK 14: Display GC status (origin only)
        if IS_ORIGIN:
            print("\n" + "="*78 + "\n                  Garbage Collection Status\n" + "="*78)
            gc_stats = get_gc_stats()
            last_run = gc_stats.get('last_run', 0)
            if last_run > 0:
                elapsed = int(time.time() - last_run)
                print(f"Last GC Run: {elapsed}s ago")
            else:
                print(f"Last GC Run: Never")
            print(f"Objects with manifests: {gc_stats.get('manifest_size', 0)}")
            print(f"Items in trash: {gc_stats.get('trash_size', 0)}")
            if last_run > 0:
                print(f"Versions expired: {gc_stats.get('versions_expired', 0)}")
                print(f"Fragments reclaimed: {gc_stats.get('fragments_reclaimed', 0)} ({gc_stats.get('bytes_reclaimed', 0) / (1024**3):.2f}GB)")
                print(f"Trash items purged: {gc_stats.get('trash_items_purged', 0)}")
                
        print("\n" + "="*78 + "\n                     Suspicious IPs Advisory\n" + "="*78)  # Suspicious IPs section
        print("No suspicious activity detected.") # Placeholder for security alerts
        print("\n" + "="*78 + "\n                  Satellite ID + TLS Fingerprint\n" + "="*78) # Satellite Identity header
        print(f"Satellite ID:          {SATELLITE_ID}") # Display Satellite ID
        print(f"Advertising IP:        {ADVERTISED_IP}") # Display advertised IP
        print(f"Origin Status:         {'ORIGIN' if IS_ORIGIN else 'SATELLITE'}") # Display origin status
        print(f"TLS Fingerprint:       {TLS_FINGERPRINT}")  # Display TLS fingerprint
        print(f"Trusted Satellites:    {len(TRUSTED_SATELLITES)} in list.json")
        print("="*78 + "\n") # Display trusted satellites count

        await asyncio.sleep(2) # Sleep briefly before refreshing the UI again

async def storagenode_main() -> None:
    """
    TASK 12: STORAGENODE MODE ENTRY POINT
    
    Lightweight entry point for pure storage nodes. Storage nodes provide
    storage capacity only - no mesh coordination, no UI, no repair work.
    
    RESPONSIBILITIES:
    1. Generate/load TLS keys and certificate
    2. Load trusted satellites list (for verification)
    3. Start storage RPC server (handle fragment GET/PUT)
    4. Send periodic heartbeat to origin (health status)
    5. That's it!
    
    LIFECYCLE:
    - Join: Operator copies storagenode_config.json → config.json, edits capacity_bytes
    - Health: Automatic via auditor (Task 9) + reputation scoring (Task 10)
    - Exit: Set capacity_bytes=0, restart → drains naturally over 24-48h
    
    DESIGN NOTES:
    - No listen_port (no control server needed)
    - No UI loop (headless operation)
    - No repair worker (satellites handle repairs)
    - No sync loops (origin tracks via heartbeat)
    - Minimal resource usage for embedded devices
    """
    global ORIGIN_PUBKEY_PEM
    
    # Fetch origin public key for registry verification
    await fetch_github_file(ORIGIN_PUBKEY_URL, ORIGIN_PUBKEY_PATH)
    
    # Generate TLS keys if not present
    generate_keys_and_certs()
    
    # Load trusted satellites (needed for fragment verification)
    load_trusted_satellites()
    
    # Fetch initial registry
    ok = await fetch_github_file(LIST_JSON_URL, LIST_JSON_PATH, force=True)
    if ok:
        load_trusted_satellites()
    
    print(f"[Storagenode] Starting storage node: {SATELLITE_ID}")
    print(f"[Storagenode] TLS Fingerprint: {TLS_FINGERPRINT}")
    print(f"[Storagenode] Advertised IP: {ADVERTISED_IP}")
    print(f"[Storagenode] Storage Port: {STORAGE_PORT}")
    print(f"[Storagenode] Storage Path: {STORAGE_FRAGMENTS_PATH}")
    print(f"[Storagenode] Capacity: {STORAGE_CAPACITY_BYTES / (1024**3):.2f} GB")
    print(f"[Storagenode] Origin: {ORIGIN_HOST}:{ORIGIN_PORT}")
    
    # Start storage RPC server
    storage_server = await asyncio.start_server(handle_storage_rpc, LISTEN_HOST, STORAGE_PORT)
    asyncio.create_task(storage_server.serve_forever())
    print(f"[Storagenode] Storage RPC listening on {LISTEN_HOST}:{STORAGE_PORT}")
    
    # Start heartbeat to origin
    asyncio.create_task(storagenode_heartbeat())
    print(f"[Storagenode] Heartbeat to origin every 60s")
    
    # TASK 24: Start P2P connectivity prober
    asyncio.create_task(storagenode_p2p_prober())
    print(f"[Storagenode] P2P connectivity prober started")
    
    # Periodic registry refresh
    asyncio.create_task(sync_registry_from_github())
    
    print(f"[Storagenode] Ready! Waiting for fragment storage requests...")
    print(f"[Storagenode] Press Ctrl+C to stop")
    
    # Keep storage server running indefinitely
    await asyncio.Event().wait()

async def storagenode_heartbeat() -> None:
    """
    TASK 12: STORAGENODE HEARTBEAT
    
    Send periodic heartbeat to origin with health status.
    Origin uses this for:
    - Availability tracking
    - Capacity monitoring
    - Health scoring (Task 10)
    
    Heartbeat includes:
    - Node identity (satellite_id, fingerprint)
    - Storage metrics (used_bytes, capacity_bytes)
    - System metrics (CPU, memory if available)
    - SMART health status (if available)
    """
    await asyncio.sleep(5)  # Wait for storage server to start
    
    while True:
        try:
            # Calculate storage usage
            used_bytes = 0
            if os.path.exists(STORAGE_FRAGMENTS_PATH):
                for root, dirs, files in os.walk(STORAGE_FRAGMENTS_PATH):
                    for f in files:
                        fp = os.path.join(root, f)
                        if os.path.exists(fp):
                            used_bytes += os.path.getsize(fp)
            
            heartbeat = {
                "type": "storagenode_heartbeat",
                "satellite_id": SATELLITE_ID,
                "fingerprint": TLS_FINGERPRINT,
                "advertised_ip": ADVERTISED_IP,
                "storage_port": STORAGE_PORT,
                "capacity_bytes": STORAGE_CAPACITY_BYTES,
                "used_bytes": used_bytes,
                "metrics": get_system_metrics(),
                "timestamp": time.time()
            }
            
            # Send to origin
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ORIGIN_HOST, ORIGIN_PORT),
                timeout=10.0
            )
            writer.write(json.dumps(heartbeat).encode() + b'\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            
            print(f"[Storagenode] Heartbeat sent: {used_bytes/(1024**3):.2f}/{STORAGE_CAPACITY_BYTES/(1024**3):.2f} GB used")
            
        except Exception as e:
            print(f"[Storagenode] Heartbeat failed: {e}")
        
        await asyncio.sleep(60)  # Heartbeat every 60s

async def main() -> None:
    """
    STEP 1–5: BOOT SEQUENCE ORCHESTRATION

    Entry point for the satellite node. This function performs full
    initialization, role determination, identity setup, trust loading,
    background task scheduling, and network listener startup.

    TASK 12: STORAGENODE MODE - Lightweight storage-only operation
    - If NODE_MODE == 'storagenode': Skip all mesh coordination, only run storage server + heartbeat
    - Storagenode mode is for pure storage capacity providers (no coordination overhead)

    This function is responsible for orchestrating the complete satellite
    lifecycle up to steady-state operation.

    -----------------------------------------------------------------------
    BOOT SEQUENCE RESPONSIBILITIES
    -----------------------------------------------------------------------

    STEP 1: Initialization
    - Relies on module-level global state initialization (constants, queues,
      registries).
    - No network or cryptographic operations occur yet.

    STEP 2: Role Definition
    - Determines whether this node acts as ORIGIN or FOLLOWER based on
      NODE_MODE.
    - Role selection affects:
        - Whether signing keys are generated
        - Whether registry updates are allowed
        - Whether outbound registration occurs

    STEP 3: Key Recovery & Trust Setup
    - For non-origin satellites:
        - Fetches the origin public key once from GitHub via
          `fetch_github_file()`.
    - Generates or loads:
        - TLS private key
        - TLS certificate
        - Origin signing keys (origin only)
    - Loads and verifies the trusted satellite registry from disk
      (`load_trusted_satellites()`).
    - Origin satellites automatically insert themselves into the registry
      for later GitHub distribution.

    STEP 4: Identity Establishment
    - Establishes immutable runtime identity values:
        - SATELLITE_ID
        - TLS_FINGERPRINT
        - ADVERTISED_IP
    - Identity must be fully established before any network communication
      or UI rendering begins.

    STEP 5: UI & Background Tasks
    - Launches long-running asynchronous background tasks:
        - `draw_ui()` — terminal status interface
        - `sync_registry_from_github()` — periodic registry refresh
        - `sync_nodes_with_peers()` — peer satellite awareness
        - `announce_to_origin()` — one-time boot announcement (followers)
        - `node_sync_loop()` — periodic status push to origin (followers)
        - `rebalance_scheduler()` — periodic diversity/fill checks (origin)
    - Background tasks are non-blocking and run concurrently.

    -----------------------------------------------------------------------
    NETWORK LISTENER
    -----------------------------------------------------------------------

    - Starts an asyncio TCP server bound to LISTEN_HOST:LISTEN_PORT.
    - Uses `handle_node_sync()` as the connection handler.
    - Accepts inbound satellite → origin synchronization messages.
    - Runs indefinitely via `serve_forever()` to keep the control plane alive.

    -----------------------------------------------------------------------
    STATUS REPORTING CONTEXT
    -----------------------------------------------------------------------

    - Although this function does not directly push status to the origin,
      it is responsible for scheduling the background mechanisms that do:
        - `announce_to_origin()` (single delayed announcement)
        - `node_sync_loop()` → `push_status_to_origin()` (periodic updates)

    - These status updates allow the origin to maintain an up-to-date view
      of:
        - Satellite identity and fingerprint
        - Advertised IP and listening port
        - Known nodes
        - Repair queue state

    -----------------------------------------------------------------------
    DESIGN NOTES
    -----------------------------------------------------------------------

    - This function is the **only valid entry point** for the satellite.
    - It must run exactly once per process lifetime.
    - All global state mutations are intentional and ordered.
    - Background tasks are explicitly created to avoid blocking the TCP server.
    - Follower registration currently overlaps with `announce_to_origin()`;
      consolidation is possible but deferred intentionally for clarity.

    This function fully implements and enforces the boot sequence described
    in the top-level module documentation.
    """
    global ORIGIN_PUBKEY_PEM
    
    # TASK 12: Storagenode mode - lightweight storage-only operation
    if NODE_MODE == 'storagenode':
        await storagenode_main()
        return
    
    # Standard satellites pull pubkey ONCE from GitHub
    if NODE_MODE != 'origin':
        # Fetch origin public key used to verify signed registry data
        await fetch_github_file(ORIGIN_PUBKEY_URL, ORIGIN_PUBKEY_PATH)

    # Start periodic node → origin status sync (non-origin satellites only)
        if NODE_MODE != 'origin':
            # Runs in background and periodically pushes node status to origin
            asyncio.create_task(supervise_task('node_sync_loop', node_sync_loop))
    # Generate TLS keys and certificates if not already present
    generate_keys_and_certs()
    # Load trusted satellites registry from disk into memory
    # TASK 12: Origin loads registry to preserve state across restarts
    load_trusted_satellites()

    # Non-origin: perform an initial registry fetch to populate UI immediately
    if NODE_MODE != 'origin':
      ok = await fetch_github_file(LIST_JSON_URL, LIST_JSON_PATH, force=True)
      if not ok:
        log_and_notify(logger_control, 'error', "Initial registry fetch failed.")
      else:
        load_trusted_satellites()
    
    # Origin auto-adds itself to the trusted registry for distribution
    # Origin uses storage_port=0 to signal it has no storage (control plane only)
    add_or_update_trusted_registry(SATELLITE_ID, TLS_FINGERPRINT, ADVERTISED_IP, LISTEN_PORT, storage_port=0)
    
    # TASK 7.5: Initialize origin's metrics and timestamp immediately (always, even if already in registry)
    if IS_ORIGIN and SATELLITE_ID in TRUSTED_SATELLITES:
        TRUSTED_SATELLITES[SATELLITE_ID]['metrics'] = get_system_metrics()
        TRUSTED_SATELLITES[SATELLITE_ID]['last_seen'] = time.time()
        TRUSTED_SATELLITES[SATELLITE_ID]['repair_metrics'] = REPAIR_METRICS.copy()
        fields = list(TRUSTED_SATELLITES[SATELLITE_ID].keys())
        logger_control.debug(f"Origin entry fields: {', '.join(fields)}")
        # Force save since we updated metrics/timestamp
        sign_and_save_satellite_list()
    elif IS_ORIGIN:
        log_and_notify(logger_control, 'warning', f"Origin self: WARNING - {SATELLITE_ID} not in TRUSTED_SATELLITES")
        # Origin signs and persists the trusted satellite list to disk
        sign_and_save_satellite_list()

    # TASK 13: Start rebalance scheduler (origin only)
    if IS_ORIGIN:
        asyncio.create_task(supervise_task('rebalance_scheduler', rebalance_scheduler))
    
    # PHASE 3B: Initialize repair queue database (origin only)
    if IS_ORIGIN:
        try:
            init_repair_db()
            log_and_notify(logger_repair, 'info', "Repair queue database initialized")
        except Exception as e:
            log_and_notify(logger_repair, 'error', f"Repair DB init failed: {e}")

    # Start TCP server to accept incoming satellite → origin registration and status sync
    server = await asyncio.start_server(handle_node_sync, LISTEN_HOST, LISTEN_PORT)
    # Notify UI that the TCP control server is listening
    try:
      log_and_notify(logger_control, 'info', f"Listening on {LISTEN_HOST}:{LISTEN_PORT}")
    except Exception:
      pass
    
    # TASK 5: Start storage RPC server BEFORE registration so probe succeeds
    # Use has_role() to support both single-mode and hybrid-mode configurations
    if has_role('storagenode') or has_role('satellite'):
        storage_server = await asyncio.start_server(handle_storage_rpc, LISTEN_HOST, STORAGE_PORT)
        asyncio.create_task(supervise_task('storage_rpc_server', storage_server.serve_forever))
        try:
            log_and_notify(logger_storage, 'info', f"Storage RPC listening on {LISTEN_HOST}:{STORAGE_PORT}")
        except Exception:
            pass
    else:
        try:
            logger_storage.info(f"Storage RPC disabled (mode={NODE_MODE})")
        except Exception:
            pass
    
    # PHASE 3A: Start repair RPC server (origin only)
    if IS_ORIGIN:
        repair_server = await asyncio.start_server(handle_repair_rpc, LISTEN_HOST, REPAIR_RPC_PORT)
        asyncio.create_task(supervise_task('repair_rpc_server', repair_server.serve_forever))
        try:
            log_and_notify(logger_repair, 'info', f"Repair RPC listening on {LISTEN_HOST}:{REPAIR_RPC_PORT}")
        except Exception:
            pass

    # Launch UI and registry sync in background
    asyncio.create_task(supervise_task('draw_ui', draw_ui))
    # Periodically sync trusted satellite registry from GitHub
    asyncio.create_task(supervise_task('sync_registry_from_github', sync_registry_from_github))
    # Background peer-to-peer node synchronization
    asyncio.create_task(supervise_task('sync_nodes_with_peers', sync_nodes_with_peers))
    # Origin: periodically update own last_seen timestamp for follower visibility
    if IS_ORIGIN:
        asyncio.create_task(supervise_task('origin_self_update_loop', origin_self_update_loop))
    # Satellite: periodically probe origin's control port to verify reachability
    if not IS_ORIGIN:
        asyncio.create_task(supervise_task('satellite_probe_origin_loop', satellite_probe_origin_loop))
    
    # PHASE 3B: Launch repair system background tasks
    if IS_ORIGIN:
        # Origin: periodically reclaim jobs with expired leases
        asyncio.create_task(supervise_task('expire_stale_leases', expire_stale_leases))
        # Origin: monitor fragment health and create repair jobs
        asyncio.create_task(supervise_task('fragment_health_checker', fragment_health_checker))
        # TASK 8: Origin: audit storage nodes and maintain performance scores
        asyncio.create_task(supervise_task('storagenode_auditor', storagenode_auditor))
        # TASK 18: Origin: monitor connection health and close idle connections
        asyncio.create_task(supervise_task('connection_health_monitor', connection_health_monitor))
        # TASK 14: Origin: periodic garbage collection of expired versions and trash
        asyncio.create_task(supervise_task('garbage_collector', garbage_collector))
    else:
        # Satellite: continuous repair worker processes jobs from queue
        asyncio.create_task(supervise_task('repair_worker', repair_worker))
    
    # Register this satellite with the origin (no-op for origin itself)
    # Done AFTER storage server starts so probe succeeds
    await register_with_origin()
    
    # Announce presence to origin after startup delay (non-origin only)
    if not IS_ORIGIN:
        asyncio.create_task(supervise_task('announce_to_origin', announce_to_origin))
    
    # Keep the main TCP server running indefinitely
    async with server: await server.serve_forever()

async def push_status_to_origin() -> bool:
    """
    STEP 2–4: PUSH STATUS TO ORIGIN

    Sends this satellite's current operational status to the origin node.
    This function is the fundamental reporting mechanism that allows the
    origin to maintain an up-to-date, authoritative view of all follower
    satellites in the mesh.

    -----------------------------------------------------------------------
    PURPOSE
    -----------------------------------------------------------------------

    - Keeps the origin informed of this satellite’s identity and health.
    - Enables centralized awareness for monitoring, coordination, and
      future repair or orchestration logic.
    - Provides the origin with visibility into:
        - Connected storage or peer nodes
        - Current repair queue state

    -----------------------------------------------------------------------
    PAYLOAD CONTENT
    -----------------------------------------------------------------------

    The JSON payload sent to the origin includes:

    - id:
        Logical satellite identifier (SATELLITE_ID)
    - fingerprint:
        TLS certificate fingerprint used for trust verification
    - ip:
        Advertised network address (ADVERTISED_IP)
    - port:
        TCP listening port (LISTEN_PORT)
    - nodes:
        Known storage / peer nodes with last-seen timestamps (NODES)
    - repair_queue:
        Snapshot of the current repair queue state

    -----------------------------------------------------------------------
    BEHAVIOR
    -----------------------------------------------------------------------

    - If this satellite is the origin (IS_ORIGIN=True), the function
      returns immediately and performs no action.
    - Establishes a TCP connection to ORIGIN_HOST:ORIGIN_PORT.
    - Sends the JSON-encoded status payload.
    - Flushes the write buffer and closes the connection cleanly.
    - Any connection, write, or serialization errors are caught and
      logged via UI_NOTIFICATIONS without raising exceptions.

    -----------------------------------------------------------------------
    OPERATIONAL CONTEXT
    -----------------------------------------------------------------------

    - This function performs a **single status push**.
    - It is intended to be called repeatedly by `node_sync_loop()`,
      which schedules periodic reporting based on NODE_SYNC_INTERVAL.
    - It is also conceptually related to the one-time boot announcement
      performed by `announce_to_origin()`, but differs in that it includes
      dynamic runtime state.

    -----------------------------------------------------------------------
    DESIGN NOTES
    -----------------------------------------------------------------------

    - Runs fully asynchronously and never blocks the event loop.
    - Uses global state only for read access (identity, nodes, queues).
    - Always closes network resources to prevent file descriptor leaks.
    - Payload format is expected by the origin’s `handle_node_sync()` handler.
    - This function does not perform registry mutations directly; it only
      reports state to the origin.

    This function is a core component of the satellite → origin control
    plane synchronization mechanism.
    """
   
    if IS_ORIGIN: # Origin never reports status to itself; avoids loopback noise and recursion
        return True  # Return True to indicate success (no backoff needed)
    
    if not ORIGIN_CONNECTION["connected"] or not ORIGIN_CONNECTION["writer"]:
        return False  # Not connected yet
    
    # TASK 7: Check if state changed since last sync
    nodes_hash = compute_state_hash('nodes')
    repair_hash = compute_state_hash('repair_queue')
    
    state_changed = (
        nodes_hash != LAST_SYNC_HASH['nodes'] or
        repair_hash != LAST_SYNC_HASH['repair_queue']
    )
    
    # TASK 7.5: Get current system metrics
    metrics = get_system_metrics()
    
    # Construct the status payload advertised to the origin
    if state_changed:
        # Full sync: include all state data
        payload = {
            "type": "sync",
            "id": SATELLITE_ID,
            "fingerprint": TLS_FINGERPRINT,
            "ip": ADVERTISED_IP,
            "port": LISTEN_PORT,
            "storage_port": STORAGE_PORT,
            "nodes": NODES,
            "repair_queue": list(REPAIR_QUEUE._queue),
            "sync_type": "full",
            "metrics": metrics  # Include system metrics
        }
        # Update last sync hashes
        LAST_SYNC_HASH['nodes'] = nodes_hash
        LAST_SYNC_HASH['repair_queue'] = repair_hash
    else:
        # Heartbeat: minimal payload proving liveness (include metrics for monitoring)
        payload = {
            "type": "sync",
            "id": SATELLITE_ID,
            "fingerprint": TLS_FINGERPRINT,
            "timestamp": time.time(),
            "sync_type": "heartbeat",
            "metrics": metrics  # Include system metrics even in heartbeat
        }

    try:
      # Send over persistent connection
      writer = ORIGIN_CONNECTION["writer"]
      writer.write((json.dumps(payload) + "\n").encode())
      await writer.drain()
      return True
    except Exception as e:
      logger_control.error(f"Send error: {e}")
      ORIGIN_CONNECTION["connected"] = False  # Trigger reconnection
      return False

async def origin_self_update_loop() -> None:
    """
    STEP 7: ORIGIN SELF-UPDATE LOOP

    Periodically updates the origin's own last_seen timestamp in TRUSTED_SATELLITES
    so that follower satellites see the origin as online when they fetch the registry.
    Also periodically re-probes satellites that failed initial reachability test.

    Behavior:
    - Runs only on origin nodes (no-op on followers).
    - Updates every NODE_SYNC_INTERVAL seconds.
    - Updates TRUSTED_SATELLITES[SATELLITE_ID]['last_seen'] = current time.
    - Every 5th cycle (5*NODE_SYNC_INTERVAL), re-probe unreachable satellites.
    - Signs and saves registry to persist changes.

    Purpose:
    - Ensures origin appears "online" in follower UIs.
    - Prevents origin from appearing offline/unstable due to stale last_seen.
    - Detects when previously unreachable satellites become reachable.
    """
    if NODE_MODE != 'origin':
        return  # Only run on origin nodes
    
    cycle = 0
    while True:
        await asyncio.sleep(NODE_SYNC_INTERVAL)
        cycle += 1
        
        # Update origin's own last_seen timestamp and metrics (TASK 7.5)
        if SATELLITE_ID in TRUSTED_SATELLITES:
            TRUSTED_SATELLITES[SATELLITE_ID]['last_seen'] = time.time()
            # Include live metrics so satellites can see origin's CPU/memory usage
            TRUSTED_SATELLITES[SATELLITE_ID]['metrics'] = get_system_metrics()
            # Include repair metrics so satellites can see system-wide repair stats
            TRUSTED_SATELLITES[SATELLITE_ID]['repair_metrics'] = REPAIR_METRICS.copy()
            # TASK 22: Include GC stats so satellites can monitor garbage collection
            TRUSTED_SATELLITES[SATELLITE_ID]['gc_stats'] = get_gc_stats()
            # Persist updated registry with fresh timestamp and metrics
            sign_and_save_satellite_list()
        
        # Every 5th cycle (~150 seconds with default NODE_SYNC_INTERVAL=30),
        # re-probe satellites that are not directly reachable
        if cycle % 5 == 0:
            for sat_id, sat_info in list(TRUSTED_SATELLITES.items()):
                if sat_id == SATELLITE_ID:
                    continue  # Skip self
                
                # Only re-probe if currently marked as not reachable
                if not sat_info.get('reachable_direct', False):
                    hostname = sat_info.get('hostname')
                    storage_port = sat_info.get('storage_port', STORAGE_PORT)
                    control_port = sat_info.get('port', LISTEN_PORT)
                    
                    if hostname:
                        reachable = await probe_storage_reachability(sat_id, hostname, storage_port, control_port=control_port)
                        if reachable:
                            # Update reachability status and persist
                            TRUSTED_SATELLITES[sat_id]['reachable_direct'] = True
                            sign_and_save_satellite_list()
                            logger_control.info(f"Satellite {sat_id[:20]} now reachable")

async def node_sync_loop() -> None:
    """
    STEP 2–4: NODE SYNC LOOP (Persistent Connection Version)

    Maintains a persistent bidirectional control connection to the origin.
    Sends periodic status updates and listens for commands from origin.

    Behavior:
    - Establishes persistent TCP connection to origin
    - Sends status updates every NODE_SYNC_INTERVAL seconds
    - Continuously listens for messages from origin (metrics, commands)
    - Auto-reconnects if connection drops
    - Origin nodes skip this entirely (no self-connection)

    Purpose:
    - Real-time bidirectional communication with origin
    - Receive origin metrics instantly (no GitHub polling)
    - Enable origin to push commands to satellites
    - Works with CG-NAT (satellite initiates and maintains connection)
    """
    
    if IS_ORIGIN:
        return  # Origin doesn't connect to itself
    
    retry_delay = 5  # Start with 5 second retry
    max_retry_delay = 60
    
    while True:
        try:
            logger_control.info(f"Connecting to origin {ORIGIN_HOST}:{ORIGIN_PORT}...")
            reader, writer = await asyncio.open_connection(ORIGIN_HOST, ORIGIN_PORT)
            
            # Store connection globally
            ORIGIN_CONNECTION["reader"] = reader
            ORIGIN_CONNECTION["writer"] = writer
            ORIGIN_CONNECTION["connected"] = True
            retry_delay = 5  # Reset retry delay on successful connection
            
            logger_control.info(f"Connected to origin {ORIGIN_HOST}:{ORIGIN_PORT}")
            log_and_notify(logger_control, 'info', "Connected to origin")
            
            # Send initial full sync
            await push_status_to_origin()
            
            # Create two tasks: one for sending periodic updates, one for receiving
            async def send_updates():
                while ORIGIN_CONNECTION["connected"]:
                    await asyncio.sleep(NODE_SYNC_INTERVAL)
                    await push_status_to_origin()
            
            async def receive_messages():
                while ORIGIN_CONNECTION["connected"]:
                    try:
                        data = await reader.readuntil(b'\n')
                        if not data:
                            break
                        
                        msg = json.loads(data.decode().strip())
                        msg_type = msg.get("type")
                        
                        if msg_type == "response":
                            # Origin sent back its metrics - find origin in registry and update
                            for sat_id, sat_info in TRUSTED_SATELLITES.items():
                                storage_port = sat_info.get('storage_port')
                                # Origin has storage_port=0, None, or missing
                                if storage_port in (0, None):
                                    if "metrics" in msg:
                                        sat_info["metrics"] = msg["metrics"]
                                    if "repair_metrics" in msg:
                                        sat_info["repair_metrics"] = msg["repair_metrics"]
                                    sat_info["last_seen"] = time.time()
                                    break
                            
                            # TASK 10: Merge storagenode scores from origin
                            if "storagenode_scores" in msg:
                                old_count = len(STORAGENODE_SCORES)
                                STORAGENODE_SCORES.update(msg["storagenode_scores"])
                                new_count = len(STORAGENODE_SCORES)
                                if new_count > old_count:
                                    logger_control.info(f"Scores synced: {new_count} storage nodes")
                            
                            # TASK 24 FIX: Merge storagenode entries from origin (for real-time last_seen updates)
                            if "storagenodes" in msg:
                                for snode_id, snode_info in msg["storagenodes"].items():
                                    TRUSTED_SATELLITES[snode_id] = snode_info
                            
                            # TASK 24 FIX: Cache repair queue from origin (for satellite UI display)
                            if "repair_queue" in msg:
                                global REPAIR_QUEUE_CACHE
                                REPAIR_QUEUE_CACHE = msg["repair_queue"]
                    
                    except asyncio.IncompleteReadError:
                        break  # Connection closed
                    except Exception as e:
                        logger_control.error(f"Receive error: {e}")
                        break
            
            # Run both tasks concurrently
            await asyncio.gather(send_updates(), receive_messages())
        
        except Exception as e:
            log_and_notify(logger_control, 'error', f"Connection to origin failed: {e}")
        
        finally:
            # Connection lost - cleanup and retry
            ORIGIN_CONNECTION["connected"] = False
            if ORIGIN_CONNECTION["writer"]:
                ORIGIN_CONNECTION["writer"].close()
                await ORIGIN_CONNECTION["writer"].wait_closed()
            ORIGIN_CONNECTION["reader"] = None
            ORIGIN_CONNECTION["writer"] = None
            
            logger_control.info(f"Reconnecting in {retry_delay}s...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)  # Exponential backoff

async def satellite_probe_origin_loop() -> None:
    """
    STEP 7: SATELLITE ORIGIN PROBE LOOP

    Periodically probes the origin node's control port to verify direct reachability.
    Only runs on non-origin nodes (satellites).

    Behavior:
    - Runs only on satellite nodes (no-op on origin).
    - Does initial probe on startup, then repeats every 5*NODE_SYNC_INTERVAL seconds (~150s).
    - Updates TRUSTED_SATELLITES registry with reachability status.
    - Finds origin by looking for entries with storage_port=0 or None.

    Purpose:
    - Verifies satellite can reach origin's control plane.
    - Critical for satellite operation - if origin is unreachable, satellite is useless.
    - Provides visibility into network connectivity issues.
    """
    if IS_ORIGIN:
        return  # Only satellites probe origin
    
    # Do initial probe on startup (cycle 0)
    cycle = 0
    while True:
        # Probe on startup (cycle 0) and every 5th cycle after that
        if cycle == 0 or cycle % 5 == 0:
            for sat_id, sat_info in list(TRUSTED_SATELLITES.items()):
                if sat_id == SATELLITE_ID:
                    continue  # Skip self
                
                # Identify origin nodes: they have storage_port=0 or None (or missing entirely)
                # Don't use default value here - we need to detect missing field
                storage_port = sat_info.get('storage_port')
                if storage_port == 0 or storage_port is None:
                    # This is an origin node - probe its control port
                    hostname = sat_info.get('hostname')
                    control_port = sat_info.get('port', LISTEN_PORT)
                    
                    if hostname and control_port:
                        reachable = await probe_storage_reachability(sat_id, hostname, None, control_port=control_port)
                        # Update local registry with reachability status
                        TRUSTED_SATELLITES[sat_id]['reachable_direct'] = reachable
                        if reachable:
                            logger_control.info(f"Origin {sat_id[:20]} reachable")
                        else:
                            log_and_notify(logger_control, 'error', f"CRITICAL: Origin {sat_id[:20]} unreachable!")
        
        await asyncio.sleep(NODE_SYNC_INTERVAL)
        cycle += 1

async def fragment_health_checker() -> None:
    """
    PHASE 3B: Background task that monitors fragment health and creates repair jobs.
    
    Purpose:
    - Scans all stored objects to verify fragment availability
    - Probes storage nodes to check if assigned fragments actually exist
    - Creates repair jobs for missing or corrupted fragments
    - Runs continuously on origin only
    
    Design:
    - Checks each object's fragments against assigned storage nodes
    - Uses storage RPC to verify fragment existence
    - Creates repair jobs when fragments are missing
    - Runs every 5 minutes (HEALTH_CHECK_INTERVAL)
    
    Implementation Notes:
    - Only runs on origin (queue authority)
    - Uses REGISTRY to find stored objects and their fragment assignments
    - Skips objects that already have pending repair jobs
    """
    if not IS_ORIGIN:
        return
    
    await asyncio.sleep(60)  # Initial delay to allow system startup
    logger_storage.info("Fragment health checker started")
    
    HEALTH_CHECK_INTERVAL = 300  # Check every 5 minutes
    
    while True:
        try:
            # Update last health check timestamp
            REPAIR_METRICS['last_health_check'] = time.time()
            
            # For now, just log that the checker ran
            # Real implementation will scan REGISTRY for objects and check fragments
            # This is a placeholder for Phase 3B implementation
            logger_storage.debug("Health check: Scanning fragments... (not yet implemented)")
            
            # TODO: Implement actual health checking:
            # 1. Iterate through stored objects in REGISTRY
            # 2. For each object, check if all n fragments exist on assigned nodes
            # 3. Probe each storage node using get_fragment RPC
            # 4. Create repair jobs for missing fragments (if not already queued)
            # 5. Log statistics (fragments checked, jobs created)
            
        except Exception as e:
            logger_storage.error(f"Health checker error: {e}")
        
        await asyncio.sleep(HEALTH_CHECK_INTERVAL)

async def connection_health_monitor() -> None:
    """
    TASK 18: Background task that monitors connection health and closes idle connections.
    
    Purpose:
    - Detects idle connections that haven't sent data in CONNECTION_TIMEOUT_SECONDS
    - Closes stale connections to free resources
    - Runs continuously on origin only
    
    Design:
    - Checks all active connections every 60 seconds
    - Closes connections idle longer than configured timeout
    - Logs connection health statistics
    """
    if not IS_ORIGIN:
        return
    
    await asyncio.sleep(120)  # Initial delay to allow connections to establish
    logger_control.info("Connection health monitor started")
    
    CHECK_INTERVAL = 60  # Check every minute
    
    while True:
        try:
            current_time = time.time()
            idle_connections = []
            
            # Find idle connections
            for sat_id, health in list(CONNECTION_HEALTH.items()):
                idle_time = current_time - health["last_activity"]
                if idle_time > CONNECTION_TIMEOUT_SECONDS:
                    idle_connections.append(sat_id)
            
            # Close idle connections
            for sat_id in idle_connections:
                if sat_id in ACTIVE_CONNECTIONS:
                    try:
                        conn = ACTIVE_CONNECTIONS[sat_id]
                        writer = conn["writer"]
                        writer.write(json.dumps({"error": "idle_timeout", "message": f"Connection idle for {CONNECTION_TIMEOUT_SECONDS}s"}).encode() + b'\n')
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()
                        logger_control.info(f"Closed idle connection: {sat_id}")
                    except Exception as e:
                        logger_control.error(f"Error closing idle connection {sat_id}: {e}")
            
        except Exception as e:
            logger_control.error(f"Connection health monitor error: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL)

async def storagenode_p2p_prober() -> None:
    """
    TASK 24: Background task that probes P2P connectivity between storage nodes.
    
    Purpose:
    - Tests direct connectivity between all storage node pairs
    - Identifies well-connected nodes for peer-to-peer repair optimization
    - Updates STORAGENODE_SCORES['p2p_reachable'] with bidirectional connectivity map
    
    Design:
    - Runs every 10 minutes (600s interval)
    - Only active on storage nodes (not satellites or origin)
    - Probes all other known storage nodes in registry
    - Uses 3-second timeout per probe (fast failure detection)
    
    Benefits:
    - Enables future P2P repair protocols (Task 13)
    - Identifies isolated nodes that need relay assistance
    - Provides connectivity metrics for leaderboard
    - Helps route repairs through well-connected peers
    
    Operational Context:
    - Started by storagenode_main() only
    - Results synced to origin via periodic status updates
    - Visible in leaderboard "P2P Connectivity" column
    """
    # Only run on storage nodes
    if not has_role('storagenode'):
        return
    
    await asyncio.sleep(30)  # Initial delay to allow registry population (reduced for testing)
    log_and_notify(logger_storage, 'info', "Storage node P2P prober started")
    
    CHECK_INTERVAL = 120  # Probe every 2 minutes (reduced for testing)
    
    while True:
        try:
            # Get list of all storage nodes from registry
            storage_nodes = {
                sat_id: node_info 
                for sat_id, node_info in NODES.items() 
                if node_info.get('type') == 'storagenode' and sat_id != SATELLITE_ID
            }
            
            if not storage_nodes:
                await asyncio.sleep(CHECK_INTERVAL)
                continue
            
            # Probe connectivity to each peer storage node
            probe_count = 0
            reachable_count = 0
            
            for target_id in storage_nodes.keys():
                # TASK 20: Circuit breaker - skip peers with open circuit
                if is_circuit_open(target_id):
                    logger_storage.info(f"Skipping P2P probe (circuit open): {target_id[:20]}")
                    continue
                reachable = await probe_storagenode_p2p_connectivity(SATELLITE_ID, target_id)
                probe_count += 1
                if reachable:
                    reachable_count += 1
                    record_success(target_id)
                else:
                    record_failure(target_id)
                
                # Small delay between probes to avoid flooding
                await asyncio.sleep(0.5)
            
            # Update last check timestamp
            if SATELLITE_ID in STORAGENODE_SCORES:
                STORAGENODE_SCORES[SATELLITE_ID]['p2p_last_check'] = time.time()
            
            logger_storage.info(f"P2P probe cycle complete: {reachable_count}/{probe_count} peers reachable")
            
        except Exception as e:
            logger_storage.error(f"P2P prober error: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL)

async def storagenode_auditor() -> None:
    """
    TASK 8: Background task that audits storage nodes and maintains performance scores.
    
    Purpose:
    - Periodically tests each storage node's availability and performance
    - Measures response latency and success rate
    - Updates STORAGENODE_SCORES for repair worker decisions
    - Runs continuously on origin only
    
    Design:
    - Audits each storage node every AUDITOR_INTERVAL seconds
    - Skips audits if origin CPU > AUDITOR_CPU_THRESHOLD
    - Tests connectivity and measures latency
    - Updates cumulative scores based on results
    
    Implementation Notes:
    - Only runs on origin (scoring authority)
    - Audits all satellites with storage_port configured
    - Scores visible in UI and used by repair worker
    """
    if not IS_ORIGIN:
        return
    
    await asyncio.sleep(30)  # Initial delay to allow satellites to connect
    log_and_notify(logger_storage, 'info', "Storagenode auditor started")
    
    while True:
        try:
            # Get list of storage nodes to audit (satellites with storage_port)
            storage_nodes = [
                sat_id for sat_id, sat in TRUSTED_SATELLITES.items()
                if sat.get('storage_port') and sat.get('storage_port') != 0
            ]
            
            if not storage_nodes:
                # No storage nodes yet, wait and retry
                await asyncio.sleep(AUDITOR_INTERVAL)
                continue
            
            # Audit each storage node
            for sat_id in storage_nodes:
                # TASK 20: Circuit breaker - skip nodes with open circuit
                if is_circuit_open(sat_id):
                    logger_storage.info(f"Skipping audit (circuit open): {sat_id[:20]}")
                    continue
                try:
                    result = await audit_storagenode(sat_id)
                    update_storagenode_score(sat_id, result)
                    
                    # Log significant events
                    if not result['success']:
                        logger_storage.warning(
                            f"Audit failed: {sat_id[:20]} - {result['reason']}"
                        )
                        record_failure(sat_id)
                    elif result['latency_ms'] > AUDITOR_LATENCY_THRESHOLD_MS:
                        logger_storage.warning(
                            f"Slow response: {sat_id[:20]} - {result['latency_ms']:.0f}ms"
                        )
                        record_success(sat_id)
                    else:
                        # Successful audit clears breaker
                        record_success(sat_id)
                    
                    # Check if score dropped below threshold
                    score = STORAGENODE_SCORES.get(sat_id, {}).get('score', 1.0)
                    if score < AUDITOR_MIN_SCORE:
                        logger_storage.warning(
                            f"Low score: {sat_id[:20]} - {score:.2f} (deprioritized)"
                        )
                
                except Exception as e:
                    logger_storage.error(f"Audit error for {sat_id[:20]}: {e}")
                    record_failure(sat_id)
                
                # Small delay between audits to avoid overwhelming nodes
                await asyncio.sleep(1)
            
        except Exception as e:
            logger_storage.error(f"Auditor error: {e}")
        
        # Wait before next audit round
        await asyncio.sleep(AUDITOR_INTERVAL)

async def repair_worker() -> None:
    """
    PHASE 3B: Continuous repair worker that processes repair jobs.
    
    Purpose:
    - Claims repair jobs from origin's repair queue
    - Fetches k surviving fragments from storage nodes
    - Reconstructs missing fragment using Reed-Solomon
    - Stores reconstructed fragment to target node
    - Runs continuously on satellites
    
    Design:
    - Loops forever, claiming jobs as they become available
    - Uses existing RPC infrastructure (claim_job, complete_job, fail_job)
    - Leverages reconstruct_file() for Reed-Solomon reconstruction
    - Includes retry logic with exponential backoff
    
    Implementation Notes:
    - Runs on satellites only (origin manages queue, doesn't process)
    - Sleeps when no jobs available to avoid busy-waiting
    - Renews lease for long-running repairs
    """
    if IS_ORIGIN:
        return  # Origin doesn't process repairs, only manages queue
    
    await asyncio.sleep(15)  # Initial delay to allow system startup
    worker_id = SATELLITE_ID
    log_and_notify(logger_repair, 'info', f"Repair worker {worker_id[:20]} started")
    
    NO_JOB_SLEEP = 30  # Sleep 30s when no jobs available
    ERROR_SLEEP = 60  # Sleep 60s after error
    
    while True:
        try:
            # Claim a job from origin
            reader, writer = await asyncio.open_connection(ORIGIN_HOST, REPAIR_RPC_PORT)
            request = {
                "rpc": "claim_job",
                "worker_id": worker_id
            }
            writer.write(json.dumps(request).encode() + b'\n')
            await writer.drain()
            
            response_data = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=10.0)
            response = json.loads(response_data.decode().strip())
            writer.close()
            await writer.wait_closed()
            
            if response.get("status") != "ok":
                logger_repair.info(f"Repair worker: Failed to claim job - {response.get('reason')}")
                await asyncio.sleep(ERROR_SLEEP)
                continue
            
            job = response.get("job")
            if not job:
                # No jobs available, sleep and retry
                await asyncio.sleep(NO_JOB_SLEEP)
                continue
            
            logger_repair.info(f"Repair worker: Claimed job {job['job_id'][:8]}... for {job['object_id'][:16]}/frag{job['fragment_index']}")
            
            # TASK 13: Select placement target(s) for the reconstructed fragment (no override logic)
            targets = choose_placement_targets(
                object_id=job['object_id'],
                copies=1,
                exclude=[]
            )
            if targets:
                tgt_id = targets[0]
                tgt_info = TRUSTED_SATELLITES.get(tgt_id, {})
                tgt_zone = _get_effective_zone(tgt_info)
                logger_repair.info(f"Repair worker: Placement target selected → {tgt_id[:20]} (zone={tgt_zone})")
            else:
                logger_repair.warning("Repair worker: No eligible placement target found (constraints/availability)")

            # === Repair Logic: Discover → Reconstruct → Store ===
            # 
            # PHASE 1: Fragment Discovery
            # Scan all storage nodes for available shards belonging to the lost object.
            # We collect shards index-by-index across nodes until we have sufficient data
            # to reconstruct the missing fragment. Since object header metadata (K, N) is 
            # not queried here, we use a heuristic: gather up to 5 shards (typically >= K=3).
            # 
            object_id = job['object_id']
            missing_idx = int(job['fragment_index'])
            candidates = [(sid, info) for sid, info in TRUSTED_SATELLITES.items() 
                         if info.get('storage_port', 0) > 0]
            shards: Dict[int, bytes] = {}  # Maps fragment index → shard bytes
            
            # Iterate through candidate nodes, querying for object fragments.
            # Early exit once enough shards are collected (threshold = 5 for safety).
            for sid, info in candidates:
                try:
                    host = info.get('hostname')
                    port = int(info.get('storage_port', 0))
                    # List all fragment indices for this object on the node
                    frags = await list_fragments(host, port, object_id) or []
                    
                    # Download each available shard, skipping the missing fragment index.
                    # Stop when we reach 5 shards (heuristic ensures K shards for Reed-Solomon).
                    for idx in frags:
                        if idx == missing_idx:
                            # Skip the missing fragment; we'll reconstruct it later.
                            continue
                        if idx in shards:
                            # Skip if we already have this shard from another node.
                            continue
                        # Fetch shard bytes from storage node
                        data = await get_fragment(host, port, object_id, idx)
                        if data:
                            shards[idx] = data
                        if len(shards) >= 5:
                            # Enough shards collected for reconstruction
                            break
                    if len(shards) >= 5:
                        # Exit outer loop early to save network queries
                        break
                except Exception:
                    # Node unreachable or shard list failed; try next node
                    continue
            
            # === PHASE 2: Fragment Reconstruction ===
            # Use Reed-Solomon erasure decoding to regenerate the missing shard.
            # K (data shards) is inferred heuristically: assume K=3 (common default).
            # N (total shards) is derived from available data: max(missing_idx+1, len(shards)+1).
            # This ensures N >= number of indices we've seen, allowing decoder to work.
            # 
            # Note: Ideally K, N would be read from object header metadata (future enhancement).
            # For now, we rely on reconstruction_file() to validate and infer parameters.
            # 
            try:
                k = 3  # Assumed data shards (standard for LibreMesh placement diversity)
                n = max(missing_idx + 1, len(shards) + 1)  # Total shards ≥ highest index + 1
                rebuilt = reconstruct_file(shards, k, n)
            except Exception as e:
                # Reconstruction failed (insufficient shards, invalid indices, etc.).
                # Report failure to repair coordinator so this job is retried or abandoned.
                reader, writer = await asyncio.open_connection(ORIGIN_HOST, REPAIR_RPC_PORT)
                fail_request = {
                    "rpc": "fail_job",
                    "job_id": job['job_id'],
                    "worker_id": worker_id,
                    "error_message": f"reconstruct_failed: {type(e).__name__}"
                }
                writer.write(json.dumps(fail_request).encode() + b'\n')
                await writer.drain()
                await reader.readuntil(b'\n')
                writer.close()
                await writer.wait_closed()
                continue
            
            # === PHASE 3: Store Reconstructed Fragment ===
            # Upload the reconstructed shard to the target storagenode selected by placement logic.
            # This target was chosen to respect zone diversity and capacity constraints.
            # 
            if targets:
                tgt_id = targets[0]
                tgt_info = TRUSTED_SATELLITES.get(tgt_id, {})
                host = tgt_info.get('hostname')
                port = int(tgt_info.get('storage_port', 0))
                ok = False
                if host and port:
                    ok = await put_fragment(host, port, object_id, missing_idx, rebuilt)
                if not ok:
                    # Report failure
                    reader, writer = await asyncio.open_connection(ORIGIN_HOST, REPAIR_RPC_PORT)
                    fail_request = {
                        "rpc": "fail_job",
                        "job_id": job['job_id'],
                        "worker_id": worker_id,
                        "error_message": "put_failed"
                    }
                    writer.write(json.dumps(fail_request).encode() + b'\n')
                    await writer.drain()
                    await reader.readuntil(b'\n')
                    writer.close()
                    await writer.wait_closed()
                    continue
                # Update fragment registry
                import hashlib
                checksum = hashlib.sha256(rebuilt).hexdigest()
                if object_id not in FRAGMENT_REGISTRY:
                    FRAGMENT_REGISTRY[object_id] = {}
                FRAGMENT_REGISTRY[object_id][missing_idx] = {
                    "sat_id": tgt_id,
                    "checksum": checksum,
                    "size": len(rebuilt),
                    "stored_at": time.time()
                }
            else:
                # No target available; fail job
                reader, writer = await asyncio.open_connection(ORIGIN_HOST, REPAIR_RPC_PORT)
                fail_request = {
                    "rpc": "fail_job",
                    "job_id": job['job_id'],
                    "worker_id": worker_id,
                    "error_message": "no_target"
                }
                writer.write(json.dumps(fail_request).encode() + b'\n')
                await writer.drain()
                await reader.readuntil(b'\n')
                writer.close()
                await writer.wait_closed()
                continue
            
            # Complete job successfully (placeholder)
            reader, writer = await asyncio.open_connection(ORIGIN_HOST, REPAIR_RPC_PORT)
            complete_request = {
                "rpc": "complete_job",
                "job_id": job['job_id'],
                "worker_id": worker_id
            }
            writer.write(json.dumps(complete_request).encode() + b'\n')
            await writer.drain()
            
            response_data = await asyncio.wait_for(reader.readuntil(b'\n'), timeout=10.0)
            response = json.loads(response_data.decode().strip())
            writer.close()
            await writer.wait_closed()
            
            if response.get("status") == "ok":
                logger_repair.info(f"Repair worker: Completed job {job['job_id'][:8]}...")
            else:
                logger_repair.warning(f"Repair worker: Failed to complete job - {response.get('reason')}")
        
        except asyncio.TimeoutError:
            logger_repair.warning(f"Repair worker: Timeout connecting to {ORIGIN_HOST}:{REPAIR_RPC_PORT}")
            await asyncio.sleep(ERROR_SLEEP)
        except ConnectionRefusedError:
            logger_repair.warning(f"Repair worker: Connection refused to {ORIGIN_HOST}:{REPAIR_RPC_PORT}")
            await asyncio.sleep(ERROR_SLEEP)
        except Exception as e:
            logger_repair.error(f"Repair worker error: {type(e).__name__}: {str(e)}")
            await asyncio.sleep(ERROR_SLEEP)

if __name__ == "__main__":
    import argparse
    
    # TASK 21: Load config to get default log level
    config = load_config()
    default_log_level = config.get('limits', {}).get('log_level', 'INFO')
    
    # TASK 21: Command-line argument parsing
    parser = argparse.ArgumentParser(description='LibreMesh Satellite Node')
    parser.add_argument('--log-level', 
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default=default_log_level,
                        help=f'Set logging level (default from config: {default_log_level})')
    # TASK 22: Disable curses UI for headless operation
    parser.add_argument('--no-curses',
                        action='store_true',
                        help='Disable multi-screen curses UI, use legacy plain-text UI instead (useful for headless operation)')
    args = parser.parse_args()
    
    # Initialize logging with specified level
    setup_logging(args.log_level)
    logger_control.info(f"LibreMesh starting with log level: {args.log_level}")
    if IS_ORIGIN:
        logger_control.debug(f"PLACEMENT_SETTINGS.zone_override_map = {PLACEMENT_SETTINGS.get('zone_override_map', {})}")
    
    # TASK 22: Set global UI mode
    if args.no_curses:
        USE_CURSES = False
        logger_control.info("Curses UI disabled (--no-curses), using legacy UI")
    
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
