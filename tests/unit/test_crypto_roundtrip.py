"""Crypto primitive roundtrip tests (C1)."""

import json
import os
from pathlib import Path

import pytest

from engine.security.identity import NodeIdentity, generate_node_identity
from engine.security.keystore import Keystore


def test_identity_encrypt_decrypt_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Identity private key survives encrypt → save → load → decrypt."""
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test-roundtrip-password")
    monkeypatch.delenv("B1E55ED_DEV_MODE", raising=False)

    ident = generate_node_identity()
    path = tmp_path / "identity.key"
    ident.save(path)

    loaded = NodeIdentity.load(path)
    assert loaded.private_key == ident.private_key
    assert loaded.public_key == ident.public_key

    # Verify signing still works
    data = b"roundtrip test data"
    sig = loaded.sign(data)
    assert loaded.verify(sig, data)


def test_identity_wrong_password_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrong password fails to decrypt identity."""
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "correct-password")
    monkeypatch.delenv("B1E55ED_DEV_MODE", raising=False)

    ident = generate_node_identity()
    path = tmp_path / "identity.key"
    ident.save(path)

    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "wrong-password")
    with pytest.raises(ValueError, match="Invalid password"):
        NodeIdentity.load(path)


def test_keystore_encrypt_decrypt_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keystore values survive encrypt → save → load → decrypt."""
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "keystore-test-pw")

    vault = tmp_path / "vault.enc"
    salt = tmp_path / "salt"
    meta = tmp_path / "meta.json"
    ks = Keystore(vault_path=vault, salt_path=salt, password="keystore-test-pw", enable_keyring=False, metadata_path=meta)
    ks.set("api_key", "test-api-key-12345")
    ks.set("other_key", "value-67890")

    ks2 = Keystore(vault_path=vault, salt_path=salt, password="keystore-test-pw", enable_keyring=False, metadata_path=meta)
    assert ks2.get("api_key") == "test-api-key-12345"
    assert ks2.get("other_key") == "value-67890"


def test_v1_identity_loads_with_v2_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """v1 identity files (PBKDF2 + Fernet) are still readable."""
    import base64

    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    pw = "legacy-password"
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", pw)

    # Create a v1-format identity file manually
    ident = generate_node_identity()
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000)
    fernet_key = base64.urlsafe_b64encode(kdf.derive(pw.encode()))
    f = Fernet(fernet_key)
    encrypted = f.encrypt(bytes.fromhex(ident.private_key))

    v1_blob = {
        "alg": "ed25519",
        "created_at": ident.created_at,
        "node_id": ident.node_id,
        "public_key": ident.public_key,
        "private_key_enc": base64.b64encode(encrypted).decode(),
        "kdf": {
            "name": "pbkdf2_hmac_sha256",
            "iterations": 480_000,
            "salt_b64": base64.b64encode(salt).decode(),
        },
    }

    path = tmp_path / "v1_identity.key"
    path.write_text(json.dumps(v1_blob))

    # v2 code should load v1 file
    loaded = NodeIdentity.load(path)
    assert loaded.private_key == ident.private_key
    assert loaded.verify(loaded.sign(b"test"), b"test")


def test_v2_identity_not_readable_with_wrong_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """v2 encrypted identity fails with wrong password."""
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "correct")
    ident = generate_node_identity()
    path = tmp_path / "identity.key"
    ident.save(path)

    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "wrong")
    with pytest.raises(ValueError, match="Invalid password"):
        NodeIdentity.load(path)


def test_identity_sign_verify_consistency() -> None:
    """Multiple sign/verify cycles produce consistent results."""
    ident = generate_node_identity()

    for i in range(10):
        data = f"message {i}".encode()
        sig = ident.sign(data)
        assert ident.verify(sig, data)
        # Different data fails
        assert not ident.verify(sig, f"wrong {i}".encode())
