# Identity — Key Management and Recovery

b1e55ed uses a two-layer key hierarchy:

```
Ethereum key (secp256k1)   ←── The Forge vanity grind produces this
        │
        └── HKDF-SHA256 ──▶  Ed25519 signing key
                              node_id = b1e55ed-{eth_address[2:10]}
```

The Ed25519 signing key is **deterministically derived** from your Ethereum private key
via HKDF (HMAC-based Key Derivation Function, RFC 5869).  This means:

> **If you still have your Ethereum private key, your identity is recoverable.**

---

## Key Files

| File                        | Contents                          | Sensitivity |
|-----------------------------|-----------------------------------|-------------|
| `.b1e55ed/identity.json`    | Public identity + encrypted keys  | Protect     |
| `.b1e55ed/forge_key.enc`    | Ethereum private key (plaintext!) | **SECRET**  |

> ⚠️ `forge_key.enc` is stored **unencrypted** by the Forge CLI for backwards
> compatibility.  Back it up in a secure location (password manager, hardware
> wallet, encrypted volume).

### Encrypted identity file

When `B1E55ED_MASTER_PASSWORD` is set at forge/setup time, `.b1e55ed/identity.json`
stores both the Ed25519 and Ethereum private keys encrypted with **Argon2id + AES-256-GCM**.
The public key and `node_id` are stored in plaintext.

---

## Backup Recommendations

1. **Back up `forge_key.enc`** (your Ethereum private key).  This single file
   is sufficient to recover your full identity.
2. **Back up `.b1e55ed/identity.json`** as a convenience copy.  This is recoverable
   from `forge_key.enc` but saves re-running `identity restore`.
3. **Back up `B1E55ED_MASTER_PASSWORD`** — without it you cannot decrypt
   `identity.json` even if you have the file.

---

## Recovery — Restoring from Ethereum Key

If you have lost `identity.json` but still have your Ethereum private key
(from `forge_key.enc` or another backup), run:

```bash
# Set your encryption password before restoring (recommended)
export B1E55ED_MASTER_PASSWORD="your-secure-password"

# Restore identity from Ethereum private key
uv run b1e55ed identity restore --eth-key <hex-private-key>
```

This will:
1. Re-derive the Ed25519 signing key via HKDF (identical derivation to the original forge)
2. Reconstruct your `node_id` from the Ethereum address
3. Write the restored identity to the standard location (`.b1e55ed/identity.json`)

Your `node_id` and public key will be identical to the originals — no re-registration needed.

### Example

```bash
# Read your key from forge_key.enc
ETH_KEY=$(cat .b1e55ed/forge_key.enc)

export B1E55ED_MASTER_PASSWORD="hunter2"
uv run b1e55ed identity restore --eth-key "$ETH_KEY"
# → Identity restored: node_id=b1e55ed-b1e55ed1
```

---

## What Happens if You Lose Both Files

If you lose **both** `forge_key.enc` and `identity.json` and have no other
backup of your Ethereum private key, your identity is **permanently lost**.

You will need to forge a new identity (`b1e55ed identity forge`) and
re-register as a contributor.  Your previous karma score and signal history
will remain in the database under the old `node_id` but will be inaccessible
from the new identity.

---

## Technical Details

### Derivation Path

```python
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_HKDF_INFO = b"b1e55ed-ed25519-signing-key-v1"

derived_bytes = HKDF(
    algorithm=hashes.SHA256(),
    length=32,
    salt=None,
    info=_HKDF_INFO,
).derive(eth_private_key_bytes)

ed25519_private_key = Ed25519PrivateKey.from_private_bytes(derived_bytes)
```

The info string `b"b1e55ed-ed25519-signing-key-v1"` is a domain separation
constant that ensures this derivation is unique to this application.

### Node ID Construction

```
node_id = "b1e55ed-" + eth_address[2:10].lower()
```

Where `eth_address` is the checksummed Ethereum address derived from the
secp256k1 public key (the same address produced by The Forge).

---

## See Also

- `docs/getting-started.md` — initial setup and forging
- `docs/crypto-primitives.md` — cryptographic primitives reference
- `engine/security/identity.py` — implementation source
