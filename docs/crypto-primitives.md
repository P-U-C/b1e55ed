# Cryptographic Primitives

> Single source of truth for all crypto used in b1e55ed.

## Current Implementation (v1)

| Purpose | Primitive | Library | Notes |
|---------|-----------|---------|-------|
| Identity signing | Ed25519 | cryptography | Event signing, karma intents |
| Key derivation | PBKDF2-HMAC-SHA256 (480K iter) | cryptography | Identity + keystore encryption |
| At-rest encryption | Fernet (AES-128-CBC + HMAC-SHA256) | cryptography | Identity file, keystore vault |
| Hash chain | SHA-256 | hashlib | Event integrity |
| Canonical serialization | JSON (sorted keys, compact) | json | Deterministic hashing |
| Vanity grinding | secp256k1 + Keccak-256 | eth-account | Forge identity |

## Target (v2 — Before >$10K AUM)

| Purpose | Current | Target | Why |
|---------|---------|--------|-----|
| KDF | PBKDF2 (480K iter) | Argon2id (19 MiB, 2 iter, 1 thread) | Memory-hard, GPU-resistant |
| Encryption | Fernet (AES-128-CBC) | AES-256-GCM | Stronger cipher, authenticated |
| Key size | 128-bit (Fernet) | 256-bit (AES-256-GCM) | Industry standard |

## Migration Plan

1. Add Argon2id + AES-256-GCM support alongside existing primitives
2. New identities use v2 primitives by default
3. `b1e55ed identity migrate` command upgrades v1 → v2 in place
4. Read path supports both v1 and v2 (version field in identity file)
5. After migration period, deprecate v1 (log warning on load)

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
