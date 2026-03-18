"""Tests for engine.producers.deerflow_research_trigger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import engine.producers.deerflow_research_trigger as _trigger_module
from engine.producers.deerflow_research_trigger import (
    poll_for_artifact,
    resolve_universe,
    run_cycle,
    trigger_deerflow,
)


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def mock_store():
    return MagicMock()


# --- Universe resolution ---


@pytest.mark.anyio
async def test_resolve_universe_returns_top_tokens(mock_db):
    mock_db.fetchall.return_value = [
        ("BTC",),
        ("ETH",),
        ("SOL",),
    ]
    result = await resolve_universe(mock_db, size=3)
    assert result == ["BTC", "ETH", "SOL"]
    mock_db.fetchall.assert_called_once()


@pytest.mark.anyio
async def test_resolve_universe_empty_on_error(mock_db):
    mock_db.fetchall.side_effect = Exception("db error")
    result = await resolve_universe(mock_db, size=5)
    assert result == []


# --- Trigger ---


@pytest.mark.anyio
async def test_trigger_sends_correct_mcp_payload():
    with patch("engine.producers.deerflow_research_trigger.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = await trigger_deerflow(["BTC", "ETH"], "http://localhost:7338", "test-key")
        assert result is True

        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["method"] == "tools/call"
        assert payload["params"]["name"] == "run_watchlist_research"
        assert payload["params"]["arguments"]["tokens"] == ["BTC", "ETH"]


@pytest.mark.anyio
async def test_trigger_returns_false_on_http_error():
    with patch("engine.producers.deerflow_research_trigger.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = await trigger_deerflow(["BTC"], "http://bad:7338", None)
        assert result is False


# --- Artifact poll ---


@pytest.mark.anyio
async def test_poll_times_out():
    watcher = MagicMock()
    watcher.scan_once.return_value = []

    result = await poll_for_artifact(watcher, timeout=2, poll_interval=1)
    assert result is None


@pytest.mark.anyio
async def test_poll_returns_first_artifact():
    artifact = {"artifact_id": "abc123", "permalink": "/artifacts/abc123"}
    watcher = MagicMock()
    watcher.scan_once.return_value = [artifact]

    result = await poll_for_artifact(watcher, timeout=10, poll_interval=1)
    assert result == artifact


@pytest.mark.anyio
async def test_poll_skips_stale_artifact():
    """Artifacts ingested before the trigger timestamp must be skipped."""
    triggered_at = datetime.now(UTC)
    stale_ts = (triggered_at - timedelta(minutes=5)).isoformat()
    fresh_ts = (triggered_at + timedelta(seconds=1)).isoformat()

    stale = {"artifact_id": "stale", "permalink": "/a/stale", "ingested_at": stale_ts}
    fresh = {"artifact_id": "fresh", "permalink": "/a/fresh", "ingested_at": fresh_ts}

    watcher = MagicMock()
    watcher.scan_once.return_value = [stale, fresh]

    result = await poll_for_artifact(watcher, timeout=10, poll_interval=1, triggered_at=triggered_at)
    assert result is not None
    assert result["artifact_id"] == "fresh"


@pytest.mark.anyio
async def test_poll_all_stale_returns_none():
    """If all available artifacts are stale, poll should time out."""
    triggered_at = datetime.now(UTC)
    stale_ts = (triggered_at - timedelta(minutes=10)).isoformat()
    stale = {"artifact_id": "old", "permalink": "/a/old", "ingested_at": stale_ts}

    watcher = MagicMock()
    watcher.scan_once.return_value = [stale]

    result = await poll_for_artifact(watcher, timeout=2, poll_interval=1, triggered_at=triggered_at)
    assert result is None


# --- Full cycle ---


@pytest.mark.anyio
async def test_full_cycle_success(mock_db, mock_store, tmp_path):
    mock_db.fetchall.return_value = [("BTC",), ("ETH",)]
    artifact = {"artifact_id": "a1", "permalink": "/a/a1", "event_id": "e1"}

    with (
        patch.object(_trigger_module, "trigger_deerflow", new_callable=AsyncMock) as mock_trigger,
        patch.object(_trigger_module, "poll_for_artifact", new_callable=AsyncMock) as mock_poll,
        patch.object(_trigger_module, "DeerflowResearchProducer") as mock_watcher_cls,
    ):
        mock_trigger.return_value = True
        mock_poll.return_value = artifact
        mock_watcher_cls.return_value.setup = MagicMock()

        result = await run_cycle(
            mock_db,
            mock_store,
            gateway_url="http://localhost:7338",
            timeout=10,
            poll_interval=1,
            universe_size=2,
            sandbox_dir=tmp_path,
        )

    assert result["status"] == "success"
    assert result["universe"] == ["BTC", "ETH"]
    assert result["artifact"] == artifact
    assert result["signal_event_id"] == "e1"
    # Signal must be emitted to DB
    mock_db.append_event.assert_called_once()
    call_kwargs = mock_db.append_event.call_args.kwargs
    assert call_kwargs["event_type"].value == "signal.research.v1"
    assert "BTC" in call_kwargs["payload"]["symbol"]
    assert call_kwargs["dedupe_key"].startswith("deerflow:cycle:")


@pytest.mark.anyio
async def test_full_cycle_triggered_at_passed_to_poll(mock_db, mock_store, tmp_path):
    """run_cycle must pass triggered_at to poll_for_artifact to prevent stale-artifact race."""
    mock_db.fetchall.return_value = [("SOL",)]
    artifact = {"artifact_id": "b1", "permalink": "/a/b1", "event_id": "e2"}

    with (
        patch.object(_trigger_module, "trigger_deerflow", new_callable=AsyncMock) as mock_trigger,
        patch.object(_trigger_module, "poll_for_artifact", new_callable=AsyncMock) as mock_poll,
        patch.object(_trigger_module, "DeerflowResearchProducer") as mock_watcher_cls,
    ):
        mock_trigger.return_value = True
        mock_poll.return_value = artifact
        mock_watcher_cls.return_value.setup = MagicMock()

        await run_cycle(mock_db, mock_store, gateway_url="http://localhost:7338", sandbox_dir=tmp_path)

    _, poll_kwargs = mock_poll.call_args
    assert "triggered_at" in poll_kwargs
    assert isinstance(poll_kwargs["triggered_at"], datetime)


def test_deerflow_trigger_producer_is_registered():
    """DeerflowTriggerProducer must be discoverable via the producer registry."""
    from engine.producers.registry import get_producer

    cls = get_producer("deerflow-trigger")
    assert cls.__name__ == "DeerflowTriggerProducer"
    assert cls.schedule == "0 */6 * * *"


@pytest.mark.anyio
async def test_cycle_trigger_failed(mock_db, mock_store, tmp_path):
    mock_db.fetchall.return_value = [("SOL",)]

    with patch("engine.producers.deerflow_research_trigger.trigger_deerflow", new_callable=AsyncMock) as mock_trigger:
        mock_trigger.return_value = False

        result = await run_cycle(
            mock_db,
            mock_store,
            gateway_url="http://localhost:7338",
            timeout=5,
            sandbox_dir=tmp_path,
        )

    assert result["status"] == "trigger_failed"
    assert result["universe"] == ["SOL"]


@pytest.mark.anyio
async def test_cycle_artifact_timeout(mock_db, mock_store, tmp_path):
    mock_db.fetchall.return_value = [("BTC",)]

    with (
        patch.object(_trigger_module, "trigger_deerflow", new_callable=AsyncMock) as mock_trigger,
        patch.object(_trigger_module, "poll_for_artifact", new_callable=AsyncMock) as mock_poll,
        patch.object(_trigger_module, "DeerflowResearchProducer") as mock_watcher_cls,
    ):
        mock_trigger.return_value = True
        mock_poll.return_value = None
        mock_watcher_cls.return_value.setup = MagicMock()

        result = await run_cycle(
            mock_db,
            mock_store,
            gateway_url="http://localhost:7338",
            timeout=2,
            poll_interval=1,
            sandbox_dir=tmp_path,
        )

    assert result["status"] == "artifact_timeout"


@pytest.mark.anyio
async def test_cycle_empty_universe(mock_db, mock_store, tmp_path):
    mock_db.fetchall.return_value = []

    result = await run_cycle(
        mock_db,
        mock_store,
        gateway_url="http://localhost:7338",
        sandbox_dir=tmp_path,
    )

    assert result["status"] == "empty_universe"
    assert result["universe"] == []
