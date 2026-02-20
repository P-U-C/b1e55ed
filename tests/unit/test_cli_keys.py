from __future__ import annotations

import json
import urllib.error
from dataclasses import dataclass
from typing import Any

import pytest

from engine.cli_keys import KNOWN_KEY_SLOTS, cmd_keys_list, cmd_keys_remove, cmd_keys_set, cmd_keys_test


class FakeKeystore:
    def __init__(self, initial: dict[str, str] | None = None):
        self._data = dict(initial or {})

    def get(self, name: str) -> str:
        if name not in self._data:
            raise KeyError(name)
        return self._data[name]

    def set(self, name: str, value: str) -> None:
        self._data[name] = value

    def remove_key(self, name: str) -> bool:
        if name in self._data:
            del self._data[name]
            return True
        return False


@dataclass
class _Resp:
    status: int
    payload: bytes

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


def test_keys_list_marks_configured(capsys: pytest.CaptureFixture[str]) -> None:
    ks = FakeKeystore({"allium.api_key": "x"})
    rc = cmd_keys_list(keystore=ks, as_json=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "✅ allium.api_key" in out
    assert "❌ nansen.api_key" in out


def test_keys_list_json_is_parseable(capsys: pytest.CaptureFixture[str]) -> None:
    ks = FakeKeystore({"allium.api_key": "x"})
    rc = cmd_keys_list(keystore=ks, as_json=True)
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert {k["name"] for k in parsed["keys"]} == set(KNOWN_KEY_SLOTS)


def test_keys_set_and_remove_round_trip() -> None:
    ks = FakeKeystore()
    rc = cmd_keys_set(keystore=ks, name="allium.api_key", value="abc", as_json=False)
    assert rc == 0
    assert ks.get("allium.api_key") == "abc"

    rc = cmd_keys_remove(keystore=ks, name="allium.api_key", as_json=False)
    assert rc == 0
    assert "allium.api_key" not in ks._data


def test_keys_test_happy_path_and_coverage_json(capsys: pytest.CaptureFixture[str]) -> None:
    ks = FakeKeystore(
        {
            "hyperliquid.api_key": "k",
            "hyperliquid.api_secret": "s",
            "allium.api_key": "a",
            "nansen.api_key": "n",
            "reddit.client_id": "r",
            "apify.token": "t",
        }
    )

    def urlopen(req: Any, timeout: float = 0) -> _Resp:
        url = getattr(req, "full_url", str(req))
        if "hyperliquid.xyz/info" in url:
            return _Resp(200, json.dumps({"universe": [{"name": "BTC"}]}).encode())
        if "api.allium.so/api/v1/developer/prices" in url:
            return _Resp(200, json.dumps({"chains": list(range(151))}).encode())
        if "api.nansen.ai/api/v1/" in url:
            return _Resp(200, b"{}")
        if "www.reddit.com/api/v1/authorize" in url:
            return _Resp(200, b"")
        if "api.apify.com/v2/users/me" in url:
            return _Resp(200, json.dumps({"data": {"username": "u"}}).encode())
        raise AssertionError(f"unexpected url: {url}")

    rc = cmd_keys_test(keystore=ks, as_json=True, urlopen=urlopen)
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["coverage"]["active"] == 5
    assert parsed["coverage"]["total"] == 5


def test_keys_test_reports_missing(capsys: pytest.CaptureFixture[str]) -> None:
    ks = FakeKeystore({"allium.api_key": "a"})

    def urlopen(req: Any, timeout: float = 0) -> _Resp:
        url = getattr(req, "full_url", str(req))
        if "api.allium.so/api/v1/developer/prices" in url:
            return _Resp(200, b"{}")
        raise AssertionError(f"unexpected url: {url}")

    rc = cmd_keys_test(keystore=ks, as_json=False, urlopen=urlopen)
    assert rc == 0
    out = capsys.readouterr().out
    assert "✅ allium" in out
    assert "❌ hyperliquid" in out
    assert "Signal coverage:" in out


def test_keys_test_unauthorized_marks_critical(capsys: pytest.CaptureFixture[str]) -> None:
    ks = FakeKeystore({"apify.token": "bad"})

    def urlopen(req: Any, timeout: float = 0) -> _Resp:
        url = getattr(req, "full_url", str(req))
        if "api.apify.com/v2/users/me" in url:
            raise urllib.error.HTTPError(url=url, code=401, msg="unauthorized", hdrs=None, fp=None)
        raise AssertionError(f"unexpected url: {url}")

    rc = cmd_keys_test(keystore=ks, as_json=False, urlopen=urlopen)
    assert rc == 0
    assert "❌ apify" in capsys.readouterr().out
