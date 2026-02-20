# The Forge — Identity Derivation Ritual

## Overview

Every b1e55ed identity begins with `0xb1e55ed`. The address is derived through computational work — a vanity grinder that searches for an Ethereum keypair whose address starts with the prefix. The process is intentionally visible. The work is the point.

## Components

### 1. Rust Vanity Grinder (`tools/forge/`)

A standalone Rust binary that searches for Ethereum vanity addresses.

**Interface:**
```
b1e55ed-forge --prefix b1e55ed --threads <N> [--json]
```

**Output (streaming, one line per second):**
```json
{"type":"progress","candidates":142881024,"elapsed_ms":98000,"rate":1457969}
{"type":"found","address":"0xb1e55edA7c2F9B3d4E81...","private_key":"0x...","candidates":189234567,"elapsed_ms":132000}
```

**Implementation:**
- `secp256k1` crate for key generation
- `keccak256` for address derivation
- Multi-threaded (rayon or std::thread)
- Progress reporting to stdout (JSON lines)

### 2. CLI Ritual (`b1e55ed identity forge`)

The Python CLI orchestrates the ritual:

1. Display the forge header
2. Spawn the Rust grinder as subprocess
3. Parse JSON progress lines, render progress bar
4. On found: encrypt private key, store identity
5. Create EAS attestation (if configured)
6. Display completion with address + attestation

### 3. Key Storage

- Private key encrypted with `B1E55ED_MASTER_PASSWORD` (or prompted)
- Stored at `~/.b1e55ed/identity.enc` (or configurable path)
- Ed25519 node identity derived from same entropy

## UX Flow

```
$ b1e55ed identity forge

  ╔══════════════════════════════════════╗
  ║         THE FORGE                    ║
  ║         b1e55ed identity protocol    ║
  ╚══════════════════════════════════════╝

  Every address in this network begins with 0xb1e55ed.
  Yours is being derived now.

  This takes a few minutes.
  The work is the point.

  Searching...

  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░  71.2%
  142,881,024 candidates evaluated
  Elapsed: 1m 38s

  ──────────────────────────────────────

  Forged.

  Address:   0xb1e55edA7c2F9B3d4E81...
  Node:      ed25519:a8f3c2...
  Attested:  EAS #0x7f2a... (Ethereum)

  Your key is encrypted and stored.
  There is no recovery. Guard it accordingly.

  Welcome to the upper class.

  ──────────────────────────────────────
```

## Brand Constraints

- No celebration, no confetti. Understated.
- "The work is the point" — proof of patience.
- Progress bar with raw candidate count — transparency.
- "Forged." not "Generated." or "Created."
- "Welcome to the upper class." — the only warmth. Earned.
- No exclamation marks.

## Security

- Private key never written unencrypted to disk
- Master password required (prompted or env var)
- Key encryption: AES-256-GCM with Argon2id KDF
- Identity file contains: encrypted private key, public address, node_id, created_at
