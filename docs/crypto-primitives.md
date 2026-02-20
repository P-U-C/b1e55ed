# Cryptographic Primitives

> Single source of truth for all crypto used in b1e55ed.

## Current Implementation (v2)

| Purpose | Primitive | Library | Notes |
|---------|-----------|---------|-------|
| Identity signing | Ed25519 | cryptography | Event signing, karma intents |
| Key derivation | **Argon2id** (19 MiB, 2 iter) | argon2-cffi | Memory-hard, GPU-resistant |
| At-rest encryption | **AES-256-GCM** | cryptography | Authenticated encryption |
| Hash chain | SHA-256 | hashlib | Event integrity |
| Canonical serialization | JSON (sorted keys, compact) | json | Deterministic hashing |
| Vanity grinding | secp256k1 + Keccak-256 | eth-account | Forge identity |

## Legacy Support (v1 — read-only)

| Purpose | v1 Primitive | Status |
|---------|-------------|--------|
| KDF | PBKDF2-HMAC-SHA256 (480K iter) | Read-only (for loading old identity files) |
| Encryption | Fernet (AES-128-CBC + HMAC-SHA256) | Read-only (for loading old vaults) |

New writes always use v2. Old files are automatically readable.

## Migration

- `b1e55ed identity migrate` (planned): loads v1 identity, re-saves as v2
- For now: re-saving any identity automatically upgrades to v2

## Threat Model

| Threat | Mitigation |
|--------|-----------|
| Local file compromise | At-rest encryption (Fernet/AES-256-GCM) |
| Password brute force | PBKDF2 480K iter → Argon2id (memory-hard) |
| GPU attacks on KDF | Argon2id (v2 target) |
| Key in memory | Python heap — no mlock yet. Planned for SEC1. |
| Swap/core dump | Not mitigated. Planned for SEC1. |
| Backup compromise | Encrypted at rest + password |
| Supply chain | Pinned dependencies (uv.lock) |
| Hash chain tampering | SHA-256 chain + signed genesis (FIX1) |

## Files

| File | Crypto Used |
|------|-------------|
| `engine/security/identity.py` | PBKDF2, Fernet, Ed25519, HKDF |
| `engine/security/keystore.py` | PBKDF2, Fernet |
| `engine/core/database.py` | SHA-256 (hash chain) |
| `engine/core/models.py` | SHA-256 (event hash) |
| `engine/integrations/forge.py` | secp256k1, Keccak-256 |
