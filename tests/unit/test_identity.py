from __future__ import annotations

from pathlib import Path

import pytest

from engine.security.identity import NodeIdentity, generate_node_identity


def test_generate_node_identity_format_and_sign_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    ident = generate_node_identity()

    assert ident.node_id.startswith("b1e55ed-")
    assert len(ident.node_id) == len("b1e55ed-") + 8

    msg = b"hello"
    sig = ident.sign(msg)
    assert ident.verify(sig, msg) is True
    assert ident.verify(sig, b"tampered") is False


def test_identity_save_load_roundtrip(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("B1E55ED_MASTER_PASSWORD", "test-password")

    ident = generate_node_identity()
    path = temp_dir / "identity.json"
    ident.save(path)

    loaded = NodeIdentity.load(path)
    assert loaded.node_id == ident.node_id
    assert loaded.public_key == ident.public_key

    # signing still works after load
    data = b"roundtrip"
    sig = loaded.sign(data)
    assert loaded.verify(sig, data) is True
