"""Tests for SPI resolution CLI wiring."""

from __future__ import annotations

import argparse
import json
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

cli = import_module("engine.cli.main")


def test_resolve_outcomes_includes_spi(capsys) -> None:
    """resolve-outcomes should include SPI resolution counts in JSON output."""
    ctx = cli.CliContext(repo_root=Path("."))
    args = argparse.Namespace(json=True)

    fake_db = MagicMock()
    fake_resolver = MagicMock()
    fake_resolver.resolve_pending.return_value = 2
    fake_resolver.last_skipped_missing_price = 1
    spi_outcomes = [
        SimpleNamespace(status="resolved"),
        SimpleNamespace(status="resolved"),
        SimpleNamespace(status="expired"),
    ]

    with (
        patch("engine.core.database.Database", return_value=fake_db),
        patch("engine.brain.outcome_resolver.OutcomeResolver", return_value=fake_resolver),
        patch("engine.spi.resolution.resolve_expired_signals", return_value=spi_outcomes),
    ):
        rc = cli._cmd_resolve_outcomes(ctx, args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["resolved"] == 2
    assert payload["skipped_missing_price"] == 1
    assert payload["spi_resolved"] == 2
    assert payload["spi_expired"] == 1


def test_resolve_spi_standalone() -> None:
    """resolve-spi command should be registered and dispatchable."""
    parser = cli.build_parser()
    ns = parser.parse_args(["resolve-spi", "--json"])
    assert ns.command == "resolve-spi"
