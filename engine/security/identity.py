"""engine.security.identity

Ed25519 node identity.

Decision (DECISIONS_V3 #11): generate identity key silently during onboarding,
and only prompt on first network use.

Implementation notes:
- Key material is stored in the operator config dir: ~/.b1e55ed/
- File format is a minimal JSON envelope to make future migrations easier.
"""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DEFAULT_DIR = Path.home() / ".b1e55ed"
DEFAULT_IDENTITY_PATH = DEFAULT_DIR / "identity.key"


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _new_node_id() -> str:
    # 8 hex chars is enough for a local, human-readable identity.
    import secrets

    return f"b1e55ed-{secrets.token_hex(4)}"


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey
    created_at: datetime

    def sign(self, data: bytes) -> bytes:
        return self.private_key.sign(data)

    def verify(self, sig: bytes, data: bytes) -> bool:
        try:
            self.public_key.verify(sig, data)
            return True
        except Exception:
            return False

    def public_key_hex(self) -> str:
        raw = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return raw.hex()

    def private_key_hex(self) -> str:
        raw = self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return raw.hex()


@dataclass(frozen=True)
class IdentityHandle:
    path: Path
    identity: NodeIdentity


def generate_node_identity(*, node_id: str | None = None) -> NodeIdentity:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    return NodeIdentity(
        node_id=node_id or _new_node_id(),
        private_key=priv,
        public_key=pub,
        created_at=_utc_now(),
    )


def save_identity(identity: NodeIdentity, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "node_id": identity.node_id,
        "created_at": identity.created_at.isoformat(),
        "public_key": identity.public_key_hex(),
        "private_key": identity.private_key_hex(),
        "type": "ed25519",
        "version": 1,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    with suppress(Exception):
        path.chmod(0o600)


def load_identity(path: Path) -> NodeIdentity:
    raw = json.loads(path.read_text(encoding="utf-8"))
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw["private_key"]))
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(raw["public_key"]))
    created_at = datetime.fromisoformat(raw["created_at"])
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return NodeIdentity(
        node_id=str(raw["node_id"]),
        private_key=priv,
        public_key=pub,
        created_at=created_at.astimezone(UTC),
    )


def ensure_identity(path: Path = DEFAULT_IDENTITY_PATH) -> IdentityHandle:
    if path.exists():
        return IdentityHandle(path=path, identity=load_identity(path))
    ident = generate_node_identity()
    save_identity(ident, path)
    return IdentityHandle(path=path, identity=ident)


def identity_status(path: Path = DEFAULT_IDENTITY_PATH) -> str:
    if not path.exists():
        return f"missing ({path})"
    try:
        ident = load_identity(path)
        return f"{ident.node_id} ({path})"
    except Exception as e:
        return f"corrupt ({path}): {e}"
