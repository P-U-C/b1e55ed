from __future__ import annotations

import re

import pytest


def test_python_grinder_finds_short_prefix_quickly() -> None:
    pytest.importorskip("eth_account")

    from engine.integrations.forge import grind

    # 2 hex chars => expected ~256 candidates.
    gen = grind("b1", report_interval=0.01)

    last = None
    for msg in gen:
        last = msg
        if msg.get("type") == "found":
            break

    assert last is not None
    assert last["type"] == "found"
    assert isinstance(last["address"], str)
    assert last["address"].lower().startswith("0xb1")
    assert isinstance(last["private_key"], str)
    pk = last["private_key"].lower()
    if pk.startswith("0x"):
        pk = pk[2:]
    assert re.fullmatch(r"[0-9a-f]+", pk)
    assert int(last["candidates"]) > 0
    assert int(last["elapsed_ms"]) >= 0


def test_python_grinder_progress_message_format() -> None:
    pytest.importorskip("eth_account")

    from engine.integrations.forge import grind

    # Make progress likely by using a longer prefix.
    gen = grind("b1e", report_interval=0.001)

    progress = None
    found = None

    for msg in gen:
        if msg.get("type") == "progress" and progress is None:
            progress = msg
        if msg.get("type") == "found":
            found = msg
            break

    assert found is not None
    assert found["address"].lower().startswith("0xb1e")

    assert progress is not None
    assert set(progress.keys()) >= {"type", "candidates", "elapsed_ms", "rate"}
    assert progress["type"] == "progress"
    assert int(progress["candidates"]) >= 0
    assert int(progress["elapsed_ms"]) >= 0
    assert int(progress["rate"]) >= 0


def test_cli_parser_has_identity_forge() -> None:
    from engine.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["identity", "forge", "--threads", "2", "--json"])

    assert args.command == "identity"
    assert args.identity_action == "forge"
    assert args.threads == 2
    assert bool(args.json) is True
