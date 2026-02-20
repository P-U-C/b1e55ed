from __future__ import annotations

import json

import pytest


def test_identity_show_with_no_identity(tmp_path, capsys) -> None:
    from engine.cli import CliContext, _identity_show

    ctx = CliContext(repo_root=tmp_path)
    rc = _identity_show(ctx, type("Args", (), {"json": False})())
    out = capsys.readouterr().out

    assert rc == 1
    assert "No forged identity found" in out


def test_identity_forge_json_arg_parsing() -> None:
    from engine.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["identity", "forge", "--json"])

    assert args.command == "identity"
    assert args.identity_action == "forge"
    assert bool(args.json) is True


def test_identity_file_read_write(tmp_path, capsys) -> None:
    from engine.cli import CliContext, _identity_show

    ctx = CliContext(repo_root=tmp_path)
    ident_dir = tmp_path / ".b1e55ed"
    ident_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "address": "0xb1e55ed00000000000000000000000000000000",
        "node_id": "eth:0xb1e55ed00000000000000000000000000000000",
        "forged_at": 123,
        "candidates_evaluated": 456,
        "elapsed_ms": 789,
    }
    (ident_dir / "identity.json").write_text(json.dumps(payload), encoding="utf-8")

    rc = _identity_show(ctx, type("Args", (), {"json": True})())
    out = capsys.readouterr().out

    assert rc == 0
    msg = json.loads(out)
    assert msg["ok"] is True
    assert msg["identity"]["address"].lower().startswith("0xb1e55ed")


@pytest.mark.parametrize(
    "argv",
    [
        ["identity", "show"],
        ["identity", "show", "--json"],
    ],
)
def test_identity_show_parsing(argv: list[str]) -> None:
    from engine.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(argv)

    assert args.command == "identity"
    assert args.identity_action == "show"
