from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine.security.keystore import Keystore, KeystoreTier


def test_keystore_tier1_encrypts_at_rest(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test-password")

    vault = temp_dir / "vault.enc"
    salt = temp_dir / "vault.salt"
    meta = temp_dir / "key_metadata.json"

    ks = Keystore(vault_path=vault, salt_path=salt, metadata_path=meta, enable_keyring=False)
    ks.store_key("TEST_API_KEY", "supersecret", KeystoreTier.ENCRYPTED_FILE)

    # file exists and doesn't contain plaintext
    raw = vault.read_bytes()
    assert b"supersecret" not in raw

    assert ks.get_key("TEST_API_KEY") == "supersecret"


def test_keystore_tier0_env_readonly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV_ONLY_KEY", "v")
    ks = Keystore(enable_keyring=False)
    assert ks.get_key("ENV_ONLY_KEY") == "v"

    with pytest.raises(PermissionError):
        ks.store_key("X", "y", KeystoreTier.ENV)


def test_keystore_list_keys_unions_sources(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test-password")
    monkeypatch.setenv("ENV_ONLY_KEY", "env")

    ks = Keystore(
        vault_path=temp_dir / "vault.enc",
        salt_path=temp_dir / "vault.salt",
        metadata_path=temp_dir / "key_metadata.json",
        enable_keyring=False,
    )
    ks.store_key("FILE_KEY", "file", KeystoreTier.ENCRYPTED_FILE)

    keys = ks.list_keys()
    assert "ENV_ONLY_KEY" in keys
    assert "FILE_KEY" in keys


def test_key_health_reports_missing(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test-password")

    vault = temp_dir / "vault.enc"
    salt = temp_dir / "vault.salt"
    meta = temp_dir / "key_metadata.json"

    ks = Keystore(vault_path=vault, salt_path=salt, metadata_path=meta, enable_keyring=False)
    ks.store_key("A", "1", KeystoreTier.ENCRYPTED_FILE)

    # simulate missing key by deleting vault
    os.remove(vault)

    report = ks.key_health()
    assert report["overall"] in {"healthy", "warning"}
    assert report["keys"]["A"]["status"] == "missing"
