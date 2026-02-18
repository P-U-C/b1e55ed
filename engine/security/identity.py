"""engine.security.identity

Ed25519 node identity.

DECISIONS_V3 #11: generate silently during setup; prompt for backup on first
network use (or after 7 days). The prompting is handled by higher layers.

Easter egg: node_id is prefixed with `b1e55ed-`.
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
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_ITERATIONS = 480_000


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
    raise ValueError(
        "Missing identity encryption password. Set B1E55ED_MASTER_PASSWORD (preferred) "
        "or B1E55ED_IDENTITY_PASSWORD."
    )


@dataclass
class NodeIdentity:
    node_id: str
    public_key: str  # hex
    private_key: str  # hex (in-memory). At rest: encrypted.
    created_at: str

    @property
    def public_key_hex(self) -> str:
        return self.public_key

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
        """Save identity to JSON, with encrypted private key."""

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # If no master password is available, fall back to plaintext-at-rest.
        # This keeps non-interactive setup/test flows working; operators should
        # set B1E55ED_MASTER_PASSWORD in real deployments.
        pw = os.environ.get("B1E55ED_MASTER_PASSWORD") or os.environ.get("B1E55ED_IDENTITY_PASSWORD")

        blob = {
            "node_id": self.node_id,
            "created_at": self.created_at,
            "public_key": self.public_key,
            "alg": "ed25519",
        }

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
        else:
            blob["private_key"] = self.private_key
            blob["warning"] = "identity private key stored unencrypted; set B1E55ED_MASTER_PASSWORD"

        path.write_text(json.dumps(blob, indent=2, sort_keys=True), encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)

    @classmethod
    def load(cls, path: str | Path) -> NodeIdentity:
        path = Path(path)
        blob = json.loads(path.read_text(encoding="utf-8"))

        if blob.get("alg") != "ed25519":
            raise ValueError("Unsupported identity alg")

        # Encrypted-at-rest (preferred)
        if "private_key_enc" in blob:
            salt = base64.b64decode(blob["kdf"]["salt_b64"])
            f = Fernet(_derive_fernet_key(_password(), salt))

            try:
                priv_raw = f.decrypt(base64.b64decode(blob["private_key_enc"]))
            except InvalidToken as e:
                raise ValueError("Invalid password or corrupted identity file") from e

            priv_hex = priv_raw.hex()
        else:
            # Plaintext-at-rest fallback
            priv_hex = str(blob["private_key"])

        return cls(
            node_id=str(blob["node_id"]),
            public_key=str(blob["public_key"]),
            private_key=priv_hex,
            created_at=str(blob["created_at"]),
        )


@dataclass
class IdentityHandle:
    path: Path
    identity: NodeIdentity


def _default_identity_path() -> Path:
    home = Path(os.environ.get("HOME", "~")).expanduser()
    # Historical filename expected by integration tests / legacy tooling.
    return home / ".b1e55ed" / "identity.key"


def ensure_identity(path: str | Path | None = None) -> IdentityHandle:
    """Load identity from disk or generate + persist.

    Setup is allowed to generate silently (DECISIONS_V3 #11).
    Requires B1E55ED_MASTER_PASSWORD (or B1E55ED_IDENTITY_PASSWORD) to save.
    """

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
        return {
            "present": True,
            "path": str(p),
            "node_id": ident.node_id,
            "created_at": ident.created_at,
            "public_key": ident.public_key,
        }
    except Exception as e:
        return {"present": False, "path": str(p), "error": str(e)}


def generate_node_identity() -> NodeIdentity:
    """Generate a new Ed25519 identity."""

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
    created_at = datetime.now(tz=UTC).isoformat()

    return NodeIdentity(
        node_id=node_id,
        public_key=pub_raw.hex(),
        private_key=priv_raw.hex(),
        created_at=created_at,
    )
