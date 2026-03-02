"""tests.unit.test_github_publish

Unit tests for engine.integrations.github_publish.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

from engine.config.github_app_defaults import COMMUNITY_APP_ID, COMMUNITY_INSTALLATION_ID
from engine.integrations.github_app import GitHubAppAuth
from engine.integrations.github_publish import publish_attestation_to_github

FAKE_ATTESTATION: dict[str, Any] = {
    "uid": "0xdeadbeef",
    "schema_uid": "0xabc123",
    "attester": "0x1234",
    "recipient": "0x0000",
    "time": 1700000000,
    "expiration": 0,
    "revocable": True,
    "ref_uid": "0x0000",
    "data": {"nodeId": "node-1"},
    "data_bytes": "0x",
    "signature": "0xsig",
    "onchain": False,
}

COMMON_KWARGS: dict[str, Any] = {
    "attestation": FAKE_ATTESTATION,
    "contributor_id": "contrib-1",
    "node_id": "node-1",
    "name": "Alice",
    "role": "agent",
    "registered_at": "2024-01-01T00:00:00+00:00",
    "owner": "test-owner",
    "repo": "test-repo",
    "token": "ghp_testtoken1234567890",
    "labels": ["attestation"],
}


def _make_mock_response(status_code: int, json_data: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


class TestPublishSuccess:
    def test_publish_success(self) -> None:
        """201 response returns dict with issue_url, issue_number, owner, repo."""
        response_data = {
            "html_url": "https://github.com/test-owner/test-repo/issues/42",
            "number": 42,
        }
        mock_resp = _make_mock_response(201, response_data)

        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("engine.integrations.github_publish.httpx.Client", return_value=mock_client):
            result = publish_attestation_to_github(**COMMON_KWARGS)

        assert result is not None
        assert result["issue_url"] == "https://github.com/test-owner/test-repo/issues/42"
        assert result["issue_number"] == 42
        assert result["owner"] == "test-owner"
        assert result["repo"] == "test-repo"

    def test_publish_creates_issue_with_correct_title(self) -> None:
        response_data = {
            "html_url": "https://github.com/test-owner/test-repo/issues/1",
            "number": 1,
        }
        mock_resp = _make_mock_response(201, response_data)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("engine.integrations.github_publish.httpx.Client", return_value=mock_client):
            publish_attestation_to_github(**COMMON_KWARGS)

        call_kwargs = mock_client.post.call_args
        posted_json = call_kwargs.kwargs["json"]
        assert posted_json["title"] == "attestation: 0xdeadbeef"


class TestPublishAuthFailure:
    def test_publish_401_returns_none(self) -> None:
        """401 auth failure returns None immediately."""
        mock_resp = _make_mock_response(401)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("engine.integrations.github_publish.httpx.Client", return_value=mock_client):
            result = publish_attestation_to_github(**COMMON_KWARGS)

        assert result is None
        # Should only try once
        assert mock_client.post.call_count == 1

    def test_publish_403_returns_none_immediately(self) -> None:
        mock_resp = _make_mock_response(403)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("engine.integrations.github_publish.httpx.Client", return_value=mock_client):
            result = publish_attestation_to_github(**COMMON_KWARGS)

        assert result is None
        assert mock_client.post.call_count == 1

    def test_publish_404_returns_none_immediately(self) -> None:
        mock_resp = _make_mock_response(404)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("engine.integrations.github_publish.httpx.Client", return_value=mock_client):
            result = publish_attestation_to_github(**COMMON_KWARGS)

        assert result is None
        assert mock_client.post.call_count == 1


class TestPublishRetries:
    def test_publish_server_error_retries_and_succeeds(self) -> None:
        """500 twice then 201 — succeeds on 3rd attempt."""
        fail_resp = _make_mock_response(500)
        success_resp = _make_mock_response(
            201,
            {"html_url": "https://github.com/test-owner/test-repo/issues/7", "number": 7},
        )

        mock_client = MagicMock()
        mock_client.post.side_effect = [fail_resp, fail_resp, success_resp]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with (
            patch("engine.integrations.github_publish.httpx.Client", return_value=mock_client),
            patch("engine.integrations.github_publish.time.sleep"),  # don't actually sleep
        ):
            result = publish_attestation_to_github(**COMMON_KWARGS)

        assert result is not None
        assert result["issue_number"] == 7
        assert mock_client.post.call_count == 3

    def test_publish_rate_limit_retries(self) -> None:
        """429 once then 201 — succeeds on 2nd attempt."""
        rate_resp = _make_mock_response(429)
        success_resp = _make_mock_response(
            201,
            {"html_url": "https://github.com/test-owner/test-repo/issues/3", "number": 3},
        )

        mock_client = MagicMock()
        mock_client.post.side_effect = [rate_resp, success_resp]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("engine.integrations.github_publish.httpx.Client", return_value=mock_client), patch("engine.integrations.github_publish.time.sleep"):
            result = publish_attestation_to_github(**COMMON_KWARGS)

        assert result is not None
        assert result["issue_number"] == 3
        assert mock_client.post.call_count == 2

    def test_publish_all_retries_exhausted_returns_none(self) -> None:
        """500 three times — all attempts exhausted, returns None."""
        fail_resp = _make_mock_response(500)

        mock_client = MagicMock()
        mock_client.post.return_value = fail_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("engine.integrations.github_publish.httpx.Client", return_value=mock_client), patch("engine.integrations.github_publish.time.sleep"):
            result = publish_attestation_to_github(**COMMON_KWARGS)

        assert result is None
        assert mock_client.post.call_count == 3


class TestPublishTokenSafety:
    def test_publish_token_not_logged_on_failure(self) -> None:
        """Token must not appear in log output on auth failure."""
        mock_resp = _make_mock_response(401)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        secret_token = "ghp_supersecret_SHOULDNOTAPPEAR"
        kwargs = {**COMMON_KWARGS, "token": secret_token}

        log_records: list[logging.LogRecord] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                log_records.append(record)

        handler = CapturingHandler()
        logger = logging.getLogger("engine.integrations.github_publish")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        try:
            with patch("engine.integrations.github_publish.httpx.Client", return_value=mock_client):
                publish_attestation_to_github(**kwargs)
        finally:
            logger.removeHandler(handler)

        all_log_text = " ".join(record.getMessage() for record in log_records)
        assert secret_token not in all_log_text, "Token found in log output!"

    def test_publish_no_token_returns_none(self) -> None:
        """Empty token returns None without making HTTP request."""
        kwargs = {**COMMON_KWARGS, "token": ""}
        mock_client = MagicMock()

        with patch("engine.integrations.github_publish.httpx.Client", return_value=mock_client):
            result = publish_attestation_to_github(**kwargs)

        assert result is None
        mock_client.post.assert_not_called()


def test_from_env_uses_baked_in_defaults_when_env_vars_missing(monkeypatch) -> None:
    monkeypatch.delenv("B1E55ED_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("B1E55ED_GITHUB_INSTALLATION_ID", raising=False)
    monkeypatch.setenv("B1E55ED_GITHUB_APP_KEY", "dummy-private-key")

    auth = GitHubAppAuth.from_env()

    assert auth._app_id == COMMUNITY_APP_ID
    assert auth._installation_id == COMMUNITY_INSTALLATION_ID
