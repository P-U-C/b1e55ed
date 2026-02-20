"""Unified identity: Forge Ethereum key → derived Ed25519 signing key (U1)."""

from pathlib import Path

import pytest

from engine.security.identity import (
    NodeIdentity,
    derive_ed25519_from_eth,
    generate_node_identity,
)


def test_derive_ed25519_deterministic() -> None:
    """Same Ethereum key always produces same Ed25519 keypair."""
    eth_key = "0x" + "ab" * 32
    priv1, pub1 = derive_ed25519_from_eth(eth_key)
    priv2, pub2 = derive_ed25519_from_eth(eth_key)

    from cryptography.hazmat.primitives import serialization

    pub1_bytes = pub1.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub2_bytes = pub2.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert pub1_bytes == pub2_bytes


def test_different_eth_keys_different_ed25519() -> None:
    """Different Ethereum keys produce different Ed25519 keys."""
    from cryptography.hazmat.primitives import serialization

    _, pub1 = derive_ed25519_from_eth("ab" * 32)
    _, pub2 = derive_ed25519_from_eth("cd" * 32)

    p1 = pub1.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    p2 = pub2.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert p1 != p2


def test_generate_with_eth_key() -> None:
    """generate_node_identity with eth key produces unified identity."""
    eth_key = "deadbeef" * 8
    eth_addr = "0xb1e55ed1234567890abcdef1234567890abcdef"

    ident = generate_node_identity(eth_private_key=eth_key, eth_address=eth_addr)

    assert ident.eth_address == eth_addr
    assert ident.eth_private_key == eth_key
    assert ident.node_id == "b1e55ed-b1e55ed1"  # first 8 chars of address after 0x
    assert ident.public_key  # Ed25519 derived
    assert ident.forge_address == eth_addr


def test_generate_legacy_no_eth_key() -> None:
    """generate_node_identity without eth key falls back to standalone Ed25519."""
    ident = generate_node_identity()

    assert ident.node_id.startswith("b1e55ed-")
    assert ident.public_key
    assert ident.private_key
    assert ident.eth_address == ""
    assert ident.eth_private_key == ""


def test_sign_verify_with_derived_key() -> None:
    """Signing and verification work with derived Ed25519 key."""
    eth_key = "aa" * 32
    ident = generate_node_identity(eth_private_key=eth_key, eth_address="0xb1e55edaabbccdd")

    data = b"test message for signing"
    sig = ident.sign(data)
    assert ident.verify(sig, data)

    # Tampered data fails
    assert not ident.verify(sig, b"tampered")


def test_save_load_roundtrip_unified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unified identity survives save/load with encryption."""
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test-password-123")
    monkeypatch.delenv("B1E55ED_DEV_MODE", raising=False)

    eth_key = "cc" * 32
    eth_addr = "0xb1e55ed9876543210fedcba9876543210fedcba"
    ident = generate_node_identity(eth_private_key=eth_key, eth_address=eth_addr)

    path = tmp_path / "identity.key"
    ident.save(path)

    loaded = NodeIdentity.load(path)
    assert loaded.node_id == ident.node_id
    assert loaded.public_key == ident.public_key
    assert loaded.private_key == ident.private_key
    assert loaded.eth_address == eth_addr
    assert loaded.eth_private_key == eth_key


def test_save_load_roundtrip_plaintext_dev_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev mode plaintext save/load works."""
    monkeypatch.setenv("B1E55ED_DEV_MODE", "1")
    monkeypatch.delenv("B1E55ED_MASTER_PASSWORD", raising=False)
    monkeypatch.delenv("B1E55ED_IDENTITY_PASSWORD", raising=False)

    ident = generate_node_identity(eth_private_key="dd" * 32, eth_address="0xb1e55edDEADBEEF")

    path = tmp_path / "identity.key"
    ident.save(path)

    loaded = NodeIdentity.load(path)
    assert loaded.eth_address == "0xb1e55edDEADBEEF"
    assert loaded.eth_private_key == "dd" * 32


def test_load_v1_identity_backwards_compat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """v1 identities (no eth_address) still load correctly."""
    monkeypatch.setenv("B1E55ED_DEV_MODE", "1")
    monkeypatch.delenv("B1E55ED_MASTER_PASSWORD", raising=False)
    monkeypatch.delenv("B1E55ED_IDENTITY_PASSWORD", raising=False)

    # Write a v1-style identity file
    import json
    v1_blob = {
        "alg": "ed25519",
        "created_at": "2026-01-01T00:00:00+00:00",
        "node_id": "b1e55ed-aabbccdd",
        "private_key": "ee" * 32,
        "public_key": "ff" * 32,
    }
    path = tmp_path / "identity.key"
    path.write_text(json.dumps(v1_blob))

    loaded = NodeIdentity.load(path)
    assert loaded.node_id == "b1e55ed-aabbccdd"
    assert loaded.eth_address == ""
    assert loaded.eth_private_key == ""
