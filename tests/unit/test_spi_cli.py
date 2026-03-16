"""Unit tests for the SPI CLI commands (Phase 2C).

Covers:
- spi register happy path → config file written, key displayed
- spi register duplicate producer_id → error message
- spi status → lists producers in table format
- spi promote valid transition → success message
- spi promote invalid/terminal transition → error message
- spi test-key valid key → "Key valid" message
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

# ---------------------------------------------------------------------------
# Helpers: import CLI helpers lazily to avoid heavy import costs
# ---------------------------------------------------------------------------


def _import_spi_cmd():
    from engine.cli.main import _cmd_spi, _spi_config_dir, _spi_register_flow

    return _cmd_spi, _spi_register_flow, _spi_config_dir


def _make_args(spi_cmd: str, producer_id: str | None = None, api_url: str = "http://127.0.0.1:5050"):
    """Build a minimal argparse.Namespace for spi commands."""
    import argparse

    ns = argparse.Namespace()
    ns.spi_cmd = spi_cmd
    ns.api_url = api_url
    if producer_id is not None:
        ns.producer_id = producer_id
    return ns


def _make_ctx(tmp_path: Path):
    from engine.cli.main import CliContext

    return CliContext(repo_root=tmp_path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_spi_dir(tmp_path: Path):
    """Return a temp dir for SPI config; caller patches _spi_config_dir manually."""
    spi_dir = tmp_path / "spi" / "producers"
    spi_dir.mkdir(parents=True)
    return spi_dir


# ---------------------------------------------------------------------------
# Test: spi register happy path
# ---------------------------------------------------------------------------


def _get_cli_main_module():
    """Return the actual engine.cli.main module (not the exported main() function)."""
    import importlib

    return importlib.import_module("engine.cli.main")


def test_spi_register_happy_path(tmp_path: Path, tmp_spi_dir: Path, monkeypatch, capsys):
    """spi register → config file written, API key displayed."""
    cli_main = _get_cli_main_module()
    _cmd_spi, _spi_register_flow, _ = _import_spi_cmd()

    api_key = "spi_key_" + "a" * 64
    response_data = {"producer_id": "testprod", "api_key": api_key}

    # Simulate user input
    inputs = iter(["testprod", "testprod Signal Producer", "native", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    # Redirect config dir to temp
    monkeypatch.setattr(cli_main, "_spi_config_dir", lambda: tmp_spi_dir)

    # Mock urllib.request.urlopen
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(response_data).encode()

    with patch("urllib.request.urlopen", return_value=mock_resp):
        rc = _spi_register_flow("http://127.0.0.1:5050")

    assert rc == 0
    captured = capsys.readouterr()
    assert api_key in captured.out
    assert "STORE THIS KEY" in captured.out

    # Config file must exist without the API key
    config_path = tmp_spi_dir / "testprod.json"
    assert config_path.exists(), "Config file not written"
    config = json.loads(config_path.read_text())
    assert config["producer_id"] == "testprod"
    assert config["ingress_mode"] == "native"
    assert "api_key" not in config


# ---------------------------------------------------------------------------
# Test: spi register duplicate
# ---------------------------------------------------------------------------


def test_spi_register_duplicate(tmp_path: Path, tmp_spi_dir: Path, monkeypatch, capsys):
    """spi register with duplicate producer_id → error message printed, rc=1."""
    cli_main = _get_cli_main_module()
    _cmd_spi, _spi_register_flow, _ = _import_spi_cmd()
    monkeypatch.setattr(cli_main, "_spi_config_dir", lambda: tmp_spi_dir)

    error_body = json.dumps({"detail": {"message": "Producer 'dup' is already registered"}}).encode()
    http_error = HTTPError(
        url="http://127.0.0.1:5050/api/v1/spi/producers",
        code=409,
        msg="Conflict",
        hdrs=MagicMock(),  # type: ignore[arg-type]
        fp=MagicMock(read=lambda: error_body),
    )
    # Patch read() on the exception so our code can decode it
    http_error.read = lambda: error_body  # type: ignore[method-assign]

    inputs = iter(["dup", "dup Signal Producer", "native", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    with patch("urllib.request.urlopen", side_effect=http_error):
        rc = _spi_register_flow("http://127.0.0.1:5050")

    assert rc == 1
    captured = capsys.readouterr()
    assert "409" in captured.err or "already registered" in captured.err


# ---------------------------------------------------------------------------
# Test: spi status
# ---------------------------------------------------------------------------


def test_spi_status_lists_producers(tmp_path: Path, monkeypatch, capsys):
    """spi status → table with producer rows printed."""
    _cmd_spi, _, _ = _import_spi_cmd()

    list_resp_data = {
        "producers": [
            {
                "producer_id": "sendoeth",
                "producer_name": "sendoeth Signal Producer",
                "lifecycle_state": "shadow",
                "ingress_mode": "native",
                "registered_at": "2026-03-16T00:00:00+00:00",
            }
        ]
    }
    detail_resp_data = {
        "producer_id": "sendoeth",
        "producer_name": "sendoeth Signal Producer",
        "lifecycle_state": "shadow",
        "ingress_mode": "native",
        "running_karma": 0.75,
        "resolved_count": 10,
        "promotion_eligibility": {},
    }

    call_count = 0

    def _fake_urlopen(req, timeout=10):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        if call_count == 1:
            mock_resp.read.return_value = json.dumps(list_resp_data).encode()
        else:
            mock_resp.read.return_value = json.dumps(detail_resp_data).encode()
        return mock_resp

    ctx = _make_ctx(tmp_path)
    args = _make_args("status")

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        rc = _cmd_spi(ctx, args)

    assert rc == 0
    captured = capsys.readouterr()
    assert "sendoeth" in captured.out
    assert "shadow" in captured.out


# ---------------------------------------------------------------------------
# Test: spi promote valid transition
# ---------------------------------------------------------------------------


def test_spi_promote_valid_transition(tmp_path: Path, capsys):
    """spi promote valid producer → shows prev → next state."""
    _cmd_spi, _, _ = _import_spi_cmd()

    producer_state_data = {
        "producer_id": "sendoeth",
        "producer_name": "sendoeth Signal Producer",
        "lifecycle_state": "onboarding",
        "ingress_mode": "native",
        "running_karma": None,
        "resolved_count": 0,
        "promotion_eligibility": {},
    }
    transition_data = {
        "producer_id": "sendoeth",
        "lifecycle_state": "shadow",
        "previous_state": "onboarding",
    }

    call_count = 0

    def _fake_urlopen(req, timeout=10):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        if call_count == 1:
            mock_resp.read.return_value = json.dumps(producer_state_data).encode()
        else:
            mock_resp.read.return_value = json.dumps(transition_data).encode()
        return mock_resp

    ctx = _make_ctx(tmp_path)
    args = _make_args("promote", producer_id="sendoeth")

    with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        rc = _cmd_spi(ctx, args)

    assert rc == 0
    captured = capsys.readouterr()
    assert "onboarding" in captured.out
    assert "shadow" in captured.out


# ---------------------------------------------------------------------------
# Test: spi promote invalid (terminal) state
# ---------------------------------------------------------------------------


def test_spi_promote_terminal_state(tmp_path: Path, capsys):
    """spi promote a retired producer → error, rc=1."""
    _cmd_spi, _, _ = _import_spi_cmd()

    producer_state_data = {
        "producer_id": "oldprod",
        "producer_name": "Old Producer",
        "lifecycle_state": "retired",
        "ingress_mode": "native",
        "running_karma": None,
        "resolved_count": 5,
        "promotion_eligibility": {},
    }

    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(producer_state_data).encode()

    ctx = _make_ctx(tmp_path)
    args = _make_args("promote", producer_id="oldprod")

    with patch("urllib.request.urlopen", return_value=mock_resp):
        rc = _cmd_spi(ctx, args)

    assert rc == 1
    captured = capsys.readouterr()
    assert "terminal" in captured.err or "cannot promote" in captured.err


# ---------------------------------------------------------------------------
# Test: spi test-key valid
# ---------------------------------------------------------------------------


def test_spi_test_key_valid(tmp_path: Path, monkeypatch, capsys):
    """spi test-key valid key → 'Key valid' message, rc=0."""
    _cmd_spi, _, _ = _import_spi_cmd()

    monkeypatch.setattr("builtins.input", lambda prompt="": "spi_key_validtestkey")

    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps({"signals": []}).encode()

    ctx = _make_ctx(tmp_path)
    args = _make_args("test-key", producer_id="myprod")

    with patch("urllib.request.urlopen", return_value=mock_resp):
        rc = _cmd_spi(ctx, args)

    assert rc == 0
    captured = capsys.readouterr()
    assert "valid" in captured.out.lower()
