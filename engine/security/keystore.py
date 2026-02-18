"""engine.security.keystore

Secrets storage, Tier 0-2.

This is intentionally pragmatic in v1:
- Tier 0: environment variables only (no writes)
- Tier 1: local encrypted file (~/.b1e55ed/secrets.json.enc) when a password is provided
- Tier 2: reserved for OS keyring integrations (not required)

The setup flow uses the keystore opportunistically:
- If Tier 1 can be enabled, persist secrets encrypted.
- Otherwise, fall back to Tier 0 (env-only) without failing onboarding.
"""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

DEFAULT_DIR = Path.home() / ".b1e55ed"
DEFAULT_SECRET_PATH = DEFAULT_DIR / "secrets.json.enc"


def _base64_urlsafe(b: bytes) -> bytes:
    import base64

    return base64.urlsafe_b64encode(b)


def _fernet_from_password(password: str, salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    key = _base64_urlsafe(kdf.derive(password.encode("utf-8")))
    return Fernet(key)


class Keystore:
    """Unified keystore front-end."""

    def __init__(self, backend: _Backend) -> None:
        self._b = backend

    @classmethod
    def default(cls) -> Keystore:
        # Tier 1 enabled when an explicit password is present.
        password = os.getenv("B1E55ED_KEYSTORE_PASSWORD")
        if password:
            return cls(Tier1EncryptedFile(password=password))
        return cls(Tier0Env())

    def set(self, key: str, value: str) -> None:
        self._b.set(key, value)

    def get(self, key: str) -> str | None:
        return self._b.get(key)

    def describe(self) -> str:
        return self._b.describe()


class _Backend:
    def set(self, key: str, value: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def get(self, key: str) -> str | None:  # pragma: no cover
        raise NotImplementedError

    def describe(self) -> str:  # pragma: no cover
        raise NotImplementedError


class Tier0Env(_Backend):
    """Tier 0: env vars only. No writes."""

    PREFIX = "B1E55ED_SECRET_"

    def set(self, key: str, value: str) -> None:
        os.environ[self.PREFIX + key.upper().replace(".", "_")] = value

    def get(self, key: str) -> str | None:
        return os.getenv(self.PREFIX + key.upper().replace(".", "_"))

    def describe(self) -> str:
        return "tier0(env)"


@dataclass
class Tier1EncryptedFile(_Backend):
    """Tier 1: local encrypted file."""

    password: str
    path: Path = DEFAULT_SECRET_PATH

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        blob = self.path.read_bytes()
        # File format: salt(16) + fernet(token)
        if len(blob) < 16:
            return {}
        salt, token = blob[:16], blob[16:]
        f = _fernet_from_password(self.password, salt)
        data = f.decrypt(token)
        return json.loads(data.decode("utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        import secrets

        salt = secrets.token_bytes(16)
        f = _fernet_from_password(self.password, salt)
        token = f.encrypt(json.dumps(data, sort_keys=True).encode("utf-8"))
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(salt + token)
        os.replace(tmp, self.path)
        with suppress(Exception):
            self.path.chmod(0o600)

    def set(self, key: str, value: str) -> None:
        data = self._load()
        data[key] = value
        self._save(data)

    def get(self, key: str) -> str | None:
        data = self._load()
        v = data.get(key)
        return None if v is None else str(v)

    def describe(self) -> str:
        return f"tier1(encrypted:{self.path})"
