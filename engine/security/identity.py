"""engine.security.identity

Unified identity: one Ethereum key (from The Forge vanity grind),
one derived Ed25519 signing key, one node_id.

Key hierarchy:
  Forge (secp256k1) → HKDF → Ed25519 signing key
  node_id = b1e55ed-{eth_address[2:10]}

The Forge's vanity address IS the identity. Ed25519 is for fast signing
of events, karma intents, and attestations.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_ITERATIONS = 480_000
_HKDF_INFO = b"b1e55ed-ed25519-signing-key-v1"


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _password() -> str:
    pw = os.environ.get("B1E55ED_MASTER_PASSWORD") or os.environ.get("B1E55ED_IDENTITY_PASSWORD")
    if pw:
        return pw
    raise ValueError("Missing identity encryption password. Set B1E55ED_MASTER_PASSWORD (preferred) or B1E55ED_IDENTITY_PASSWORD.")


# ---------------------------------------------------------------------------
# Ed25519 derivation from Ethereum key
# ---------------------------------------------------------------------------

def derive_ed25519_from_eth(eth_private_key_hex: str) -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Deterministically derive Ed25519 keypair from Ethereum private key via HKDF."""
    eth_bytes = bytes.fromhex(eth_private_key_hex.removeprefix("0x"))
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_HKDF_INFO,
    ).derive(eth_bytes)
    priv = Ed25519PrivateKey.from_private_bytes(derived)
    return priv, priv.public_key()


# ---------------------------------------------------------------------------
# Unified Identity
# ---------------------------------------------------------------------------

@dataclass
class NodeIdentity:
    """Unified identity combining Forge Ethereum address and derived Ed25519 signing key.

    For backwards compatibility, the class name remains NodeIdentity.
    All signing operations use the derived Ed25519 key.
    """
    node_id: str
    public_key: str     # Ed25519 public key hex
    private_key: str    # Ed25519 private key hex (in-memory; encrypted at rest)
    created_at: str
    eth_address: str = ""       # Forge vanity address (0xb1e55ed...)
    eth_private_key: str = ""   # Ethereum private key hex (in-memory; encrypted at rest)

    @property
    def public_key_hex(self) -> str:
        return self.public_key

    @property
    def forge_address(self) -> str:
        """The Forge vanity Ethereum address, if available."""
        return self.eth_address

    def _private_obj(self) -> Ed25519PrivateKey:
        raw = bytes.fromhex(self.private_key)
        return Ed25519PrivateKey.from_private_bytes(raw)

    def _public_obj(self) -> Ed25519PublicKey:
        raw = bytes.fromhex(self.public_key)
        return Ed25519PublicKey.from_public_bytes(raw)

    def sign(self, data: bytes) -> bytes:
        return self._private_obj().sign(data)

    def verify(self, sig: bytes, data: bytes) -> bool:
        try:
            self._public_obj().verify(sig, data)
            return True
        except Exception:
            return False

    def save(self, path: str | Path) -> None:
        """Save identity to JSON, with encrypted private keys."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        pw = os.environ.get("B1E55ED_MASTER_PASSWORD") or os.environ.get("B1E55ED_IDENTITY_PASSWORD")

        blob: dict = {
            "node_id": self.node_id,
            "created_at": self.created_at,
            "public_key": self.public_key,
            "alg": "ed25519",
            "version": 2,
        }

        if self.eth_address:
            blob["eth_address"] = self.eth_address

        if pw:
            salt = os.urandom(16)
            f = Fernet(_derive_fernet_key(pw, salt))
            encrypted_priv = f.encrypt(bytes.fromhex(self.private_key))
            blob["private_key_enc"] = base64.b64encode(encrypted_priv).decode("ascii")
            blob["kdf"] = {
                "name": "pbkdf2_hmac_sha256",
                "iterations": _ITERATIONS,
                "salt_b64": base64.b64encode(salt).decode("ascii"),
            }
            # Also encrypt Ethereum key if present
            if self.eth_private_key:
                encrypted_eth = f.encrypt(bytes.fromhex(self.eth_private_key.removeprefix("0x")))
                blob["eth_private_key_enc"] = base64.b64encode(encrypted_eth).decode("ascii")
        else:
            dev_mode = os.environ.get("B1E55ED_DEV_MODE", "").lower() in ("1", "true", "yes")
            if not dev_mode:
                raise ValueError(
                    "SECURITY ERROR: Cannot save plaintext identity without B1E55ED_DEV_MODE=1. "
                    "Set B1E55ED_MASTER_PASSWORD to encrypt identity at rest."
                )
            blob["private_key"] = self.private_key
            if self.eth_private_key:
                blob["eth_private_key"] = self.eth_private_key
            blob["warning"] = "DEVELOPMENT MODE: identity private key stored unencrypted"

        path.write_text(json.dumps(blob, indent=2, sort_keys=True), encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)

    @classmethod
    def load(cls, path: str | Path) -> NodeIdentity:
        path = Path(path)
        blob = json.loads(path.read_text(encoding="utf-8"))

        if blob.get("alg") != "ed25519":
            raise ValueError("Unsupported identity alg")

        version = blob.get("version", 1)
        eth_address = blob.get("eth_address", "")
        eth_private_key = ""

        # Decrypt Ed25519 key
        if "private_key_enc" in blob:
            salt = base64.b64decode(blob["kdf"]["salt_b64"])
            f = Fernet(_derive_fernet_key(_password(), salt))

            try:
                priv_raw = f.decrypt(base64.b64decode(blob["private_key_enc"]))
            except InvalidToken as e:
                raise ValueError("Invalid password or corrupted identity file") from e

            priv_hex = priv_raw.hex()

            # Decrypt Ethereum key if present
            if "eth_private_key_enc" in blob:
                try:
                    eth_raw = f.decrypt(base64.b64decode(blob["eth_private_key_enc"]))
                    eth_private_key = eth_raw.hex()
                except InvalidToken:
                    pass  # Non-fatal: Ed25519 key is sufficient for operations
        else:
            # Plaintext fallback
            priv_hex = str(blob["private_key"])
            eth_private_key = blob.get("eth_private_key", "")

        return cls(
            node_id=str(blob["node_id"]),
            public_key=str(blob["public_key"]),
            private_key=priv_hex,
            created_at=str(blob["created_at"]),
            eth_address=eth_address,
            eth_private_key=eth_private_key,
        )


@dataclass
class IdentityHandle:
    path: Path
    identity: NodeIdentity


def _default_identity_path() -> Path:
    home = Path(os.environ.get("HOME", "~")).expanduser()
    return home / ".b1e55ed" / "identity.key"


def ensure_identity(path: str | Path | None = None) -> IdentityHandle:
    """Load identity from disk or generate + persist."""
    p = Path(path) if path else _default_identity_path()
    if p.exists():
        return IdentityHandle(path=p, identity=NodeIdentity.load(p))

    ident = generate_node_identity()
    ident.save(p)
    return IdentityHandle(path=p, identity=ident)


def identity_status(path: str | Path | None = None) -> dict:
    p = Path(path) if path else _default_identity_path()
    if not p.exists():
        return {"present": False, "path": str(p)}

    try:
        ident = NodeIdentity.load(p)
        status: dict = {
            "present": True,
            "path": str(p),
            "node_id": ident.node_id,
            "created_at": ident.created_at,
            "public_key": ident.public_key,
        }
        if ident.eth_address:
            status["eth_address"] = ident.eth_address
        return status
    except Exception as e:
        return {"present": False, "path": str(p), "error": str(e)}


def generate_node_identity(*, eth_private_key: str | None = None, eth_address: str | None = None) -> NodeIdentity:
    """Generate a new identity.

    If eth_private_key is provided (from Forge grind), derives Ed25519 from it.
    Otherwise falls back to standalone Ed25519 generation (legacy/test mode).
    """

    created_at = datetime.now(tz=UTC).isoformat()

    if eth_private_key:
        # Unified: derive Ed25519 from Ethereum key
        priv_ed, pub_ed = derive_ed25519_from_eth(eth_private_key)

        pub_raw = pub_ed.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        priv_raw = priv_ed.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

        addr = eth_address or ""
        # node_id from Ethereum address if available
        node_id = f"b1e55ed-{addr[2:10].lower()}" if addr else f"b1e55ed-{pub_raw.hex()[:8]}"

        return NodeIdentity(
            node_id=node_id,
            public_key=pub_raw.hex(),
            private_key=priv_raw.hex(),
            created_at=created_at,
            eth_address=addr,
            eth_private_key=eth_private_key.removeprefix("0x"),
        )

    # Legacy: standalone Ed25519 (for tests and pre-Forge bootstrap)
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    pub_raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    priv_raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )

    node_id = f"b1e55ed-{pub_raw.hex()[:8]}"

    return NodeIdentity(
        node_id=node_id,
        public_key=pub_raw.hex(),
        private_key=priv_raw.hex(),
        created_at=created_at,
    )
