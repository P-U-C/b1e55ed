"""engine.security.keystore

Flattened keystore with Tier 0-2 backends.

"Keys to the kingdom" live here — store them like you intend to keep them.

Tiering (DECISIONS_V3 #8):
- Tier 0: environment variables (read-only)
- Tier 1: encrypted vault file (Fernet)
- Tier 2: OS keyring via `keyring` (optional)

Tier 3 (YubiKey/MPC) is explicitly Phase 2.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class KeystoreTier(IntEnum):
    ENV = 0
    ENCRYPTED_FILE = 1
    KEYRING = 2


_ITERATIONS = 480_000
_SALT_SIZE = 32
_DEFAULT_DIR = Path.home() / ".b1e55ed" / "secrets"
_DEFAULT_VAULT = _DEFAULT_DIR / "vault.enc"
_DEFAULT_SALT = _DEFAULT_DIR / "vault.salt"
_DEFAULT_METADATA = _DEFAULT_DIR / "key_metadata.json"
_SERVICE_NAME = "b1e55ed"


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _require_password(env_var: str = "B1E55ED_MASTER_PASSWORD") -> str:
    pw = os.environ.get(env_var)
    if pw:
        return pw
    raise ValueError(f"Missing master password. Set {env_var} or pass password explicitly when constructing Keystore.")


@dataclass(frozen=True)
class KeyHealth:
    name: str
    tier: KeystoreTier
    status: str  # healthy|warning|critical|missing
    issues: list[str]


class _EnvBackend:
    def __init__(self, prefix: str | None = None):
        self.prefix = prefix

    def get(self, name: str) -> str:
        v = os.environ.get(name)
        if v is None:
            raise KeyError(name)
        return v

    def set(self, name: str, value: str) -> None:
        raise PermissionError("Tier 0 env store is read-only")

    def list_keys(self) -> list[str]:
        if self.prefix is None:
            return sorted(os.environ.keys())
        return sorted(k for k in os.environ if k.startswith(self.prefix))

    def has(self, name: str) -> bool:
        return os.environ.get(name) is not None


class _EncryptedFileBackend:
    def __init__(
        self,
        *,
        password: str,
        vault_path: Path = _DEFAULT_VAULT,
        salt_path: Path = _DEFAULT_SALT,
        auto_create: bool = True,
    ):
        self.vault_path = Path(vault_path)
        self.salt_path = Path(salt_path)
        self.auto_create = auto_create
        self._password = password
        self._secrets: dict[str, str] = {}
        self._load()

    def _ensure_dir(self) -> None:
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self.vault_path.parent, 0o700)

    def _get_or_create_salt(self) -> bytes:
        if self.salt_path.exists():
            return self.salt_path.read_bytes()
        if not self.auto_create:
            raise FileNotFoundError(str(self.salt_path))
        self._ensure_dir()
        salt = os.urandom(_SALT_SIZE)
        self.salt_path.write_bytes(salt)
        with contextlib.suppress(OSError):
            os.chmod(self.salt_path, 0o600)
        return salt

    def _fernet(self) -> Fernet:
        salt = self._get_or_create_salt()
        return Fernet(_derive_fernet_key(self._password, salt))

    def _load(self) -> None:
        if not self.vault_path.exists():
            self._secrets = {}
            return
        encrypted = self.vault_path.read_bytes()
        try:
            data = self._fernet().decrypt(encrypted)
        except InvalidToken as e:
            raise ValueError("Invalid password or corrupted vault") from e
        self._secrets = json.loads(data.decode("utf-8"))

    def _save(self) -> None:
        self._ensure_dir()
        data = json.dumps(self._secrets, sort_keys=True, indent=2).encode("utf-8")
        encrypted = self._fernet().encrypt(data)
        self.vault_path.write_bytes(encrypted)
        with contextlib.suppress(OSError):
            os.chmod(self.vault_path, 0o600)

    def get(self, name: str) -> str:
        if name not in self._secrets:
            raise KeyError(name)
        return self._secrets[name]

    def set(self, name: str, value: str) -> None:
        self._secrets[name] = value
        self._save()

    def list_keys(self) -> list[str]:
        return sorted(self._secrets.keys())

    def has(self, name: str) -> bool:
        return name in self._secrets


class _KeyringBackend:
    def __init__(self, *, service_name: str = _SERVICE_NAME):
        try:
            import keyring
        except Exception as e:  # pragma: no cover
            raise RuntimeError("keyring library not installed") from e

        self.keyring = keyring
        self.service_name = service_name
        self.registry_key = "__keyring_registry__"

        # best-effort sanity check
        backend = keyring.get_keyring()
        name = type(backend).__name__.lower()
        if "fail" in name or "null" in name:
            raise RuntimeError("No usable keyring backend available")

    def _load_registry(self) -> list[str]:
        try:
            data = self.keyring.get_password(self.service_name, self.registry_key)
            if not data:
                return []
            return json.loads(data)
        except Exception:
            return []

    def _save_registry(self, keys: list[str]) -> None:
        self.keyring.set_password(self.service_name, self.registry_key, json.dumps(sorted(set(keys))))

    def _add_registry(self, name: str) -> None:
        keys = self._load_registry()
        if name not in keys:
            keys.append(name)
            self._save_registry(keys)

    def get(self, name: str) -> str:
        v = self.keyring.get_password(self.service_name, name)
        if v is None:
            raise KeyError(name)
        return v

    def set(self, name: str, value: str) -> None:
        self.keyring.set_password(self.service_name, name, value)
        self._add_registry(name)

    def list_keys(self) -> list[str]:
        return self._load_registry()

    def has(self, name: str) -> bool:
        return self.keyring.get_password(self.service_name, name) is not None


class Keystore:
    """Unified keystore facade.

    Lookup order is Tier 0 → Tier 1 → Tier 2 by default (env overrides are convenient).

    Note: Tier 0 is read-only by design.

    Compatibility: CLI uses `Keystore.default()`, `set()`, and `describe()`.
    """

    @classmethod
    def default(cls) -> Keystore:
        """Default keystore constructor used by the CLI."""

        return cls(enable_keyring=True)

    def __init__(
        self,
        *,
        env_prefix: str | None = None,
        vault_path: Path = _DEFAULT_VAULT,
        salt_path: Path = _DEFAULT_SALT,
        password: str | None = None,
        enable_keyring: bool = True,
        keyring_service: str = _SERVICE_NAME,
        metadata_path: Path = _DEFAULT_METADATA,
    ):
        self._env = _EnvBackend(prefix=env_prefix)
        self._password = password
        self._vault_path = Path(vault_path)
        self._salt_path = Path(salt_path)
        self._metadata_path = Path(metadata_path)

        self._tier1: _EncryptedFileBackend | None = None
        if password is not None or os.environ.get("B1E55ED_MASTER_PASSWORD"):
            self._tier1 = _EncryptedFileBackend(
                password=password or _require_password(),
                vault_path=self._vault_path,
                salt_path=self._salt_path,
            )

        self._tier2: _KeyringBackend | None = None
        if enable_keyring:
            try:
                self._tier2 = _KeyringBackend(service_name=keyring_service)
            except Exception:
                self._tier2 = None

        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._metadata_path.exists():
            self._metadata_path.write_text("{}", encoding="utf-8")
            with contextlib.suppress(OSError):
                os.chmod(self._metadata_path, 0o600)

    def set(self, name: str, value: str, tier: KeystoreTier = KeystoreTier.ENCRYPTED_FILE) -> None:
        """Compatibility wrapper: store a key."""

        self.store_key(name, value, tier)

    def get(self, name: str) -> str:
        """Compatibility wrapper: fetch a key."""

        return self.get_key(name)

    def describe(self) -> str:
        """Human-readable keystore status for CLI output."""

        h = self.key_health()
        parts = [f"overall={h.get('overall')}"]
        parts.append(f"tier1={'on' if h.get('tier1_configured') else 'off'}")
        parts.append(f"tier2={'on' if h.get('tier2_available') else 'off'}")
        return "Keystore(" + ", ".join(parts) + ")"

    def store_key(self, name: str, value: str, tier: KeystoreTier) -> None:
        if tier == KeystoreTier.ENV:
            raise PermissionError("Cannot write to Tier 0 env")
        if tier == KeystoreTier.ENCRYPTED_FILE:
            if self._tier1 is None:
                self._tier1 = _EncryptedFileBackend(
                    password=self._password or _require_password(),
                    vault_path=self._vault_path,
                    salt_path=self._salt_path,
                )
            self._tier1.set(name, value)
        elif tier == KeystoreTier.KEYRING:
            if self._tier2 is None:
                raise RuntimeError("Tier 2 keyring not available")
            self._tier2.set(name, value)
        else:
            raise ValueError(f"Unknown tier: {tier}")

        self._register_metadata(name=name, tier=tier)

    def get_key(self, name: str) -> str:
        if self._env.has(name):
            return self._env.get(name)
        if self._tier1 is not None and self._tier1.has(name):
            return self._tier1.get(name)
        if self._tier2 is not None and self._tier2.has(name):
            return self._tier2.get(name)
        raise KeyError(name)

    def list_keys(self) -> list[str]:
        keys: set[str] = set()
        keys.update(self._env.list_keys())
        if self._tier1 is not None:
            keys.update(self._tier1.list_keys())
        if self._tier2 is not None:
            keys.update(self._tier2.list_keys())
        return sorted(keys)

    def key_health(self) -> dict[str, Any]:
        """Return a lightweight health view.

        The legacy implementation tracked age and permissions. Here we keep a minimal
        metadata registry and report per-key tier availability.
        """

        meta = self._load_metadata()
        out: dict[str, Any] = {"overall": "healthy", "keys": {}}

        overall = "healthy"
        for name, info in meta.items():
            tier = KeystoreTier(int(info.get("tier", 1)))
            present = False
            if tier == KeystoreTier.ENV:
                present = self._env.has(name)
            elif tier == KeystoreTier.ENCRYPTED_FILE:
                # For health, "present" means it exists at rest (not just in-memory).
                present = self._tier1 is not None and self._vault_path.exists() and self._tier1.has(name)
            elif tier == KeystoreTier.KEYRING:
                present = self._tier2 is not None and self._tier2.has(name)

            status = "healthy" if present else "missing"
            if status != "healthy":
                overall = "warning" if overall == "healthy" else overall

            out["keys"][name] = {
                "tier": int(tier),
                "status": status,
                "created_at": info.get("created_at"),
            }

        out["overall"] = overall
        out["tier2_available"] = self._tier2 is not None
        out["tier1_configured"] = self._tier1 is not None
        return out

    # --- metadata ---

    def _load_metadata(self) -> dict[str, Any]:
        try:
            return json.loads(self._metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_metadata(self, data: dict[str, Any]) -> None:
        self._metadata_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(self._metadata_path, 0o600)

    def _register_metadata(self, *, name: str, tier: KeystoreTier) -> None:
        data = self._load_metadata()
        if name not in data:
            from datetime import UTC, datetime

            data[name] = {"tier": int(tier), "created_at": datetime.now(tz=UTC).isoformat()}
        else:
            data[name]["tier"] = int(tier)
        self._save_metadata(data)
