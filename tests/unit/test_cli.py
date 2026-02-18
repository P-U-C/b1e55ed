from __future__ import annotations

import pytest

from engine.cli import build_parser, main


def test_cli_help_includes_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([])
    assert rc == 2
    out = capsys.readouterr().out
    assert "setup" in out
    assert "brain" in out
    assert "api" in out
    assert "dashboard" in out
    assert "status" in out


def test_cli_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--version"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.endswith("(0xb1e55ed)")
    assert out.startswith("b1e55ed v")


def test_cli_unknown_command_errors(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["nope"])  # argparse rejects unknown subcommand

    # main() should surface the same behavior via argparse
    with pytest.raises(SystemExit):
        main(["nope"])


@pytest.mark.parametrize("cmd", ["setup", "brain", "api", "dashboard", "status"])
def test_cli_parses_all_subcommands(cmd: str) -> None:
    parser = build_parser()
    ns = parser.parse_args([cmd])
    assert ns.command == cmd
