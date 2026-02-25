"""tests.unit.test_export_karma_cli

Tests for `b1e55ed export karma` CLI command.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from engine.cli.commands.export import run_export
from engine.core.database import Database
from engine.core.events import EventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scaffold_repo(tmp_path: Path) -> Path:
    """Create a minimal repo layout for CLI tests."""
    repo_root = tmp_path
    src_root = Path(__file__).resolve().parents[2]

    (repo_root / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_root / "config" / "default.yaml", repo_root / "config" / "default.yaml")
    shutil.copytree(src_root / "config" / "presets", repo_root / "config" / "presets")
    (repo_root / "data").mkdir(parents=True, exist_ok=True)

    # Fake identity so the identity gate doesn't block
    identity_dir = repo_root / ".b1e55ed"
    identity_dir.mkdir(parents=True, exist_ok=True)
    (identity_dir / "identity.json").write_text(
        json.dumps(
            {
                "address": "0xb1e55ed0000000000000000000000000deadbeef",
                "node_id": "eth:0xb1e55ed0000000000000000000000000deadbeef",
                "forged_at": 1700000000,
                "candidates_evaluated": 1,
                "elapsed_ms": 1,
            }
        )
    )

    return repo_root


def _seed_db(db: Database, count: int = 5) -> None:
    """Insert test events into the database."""
    for i in range(count):
        db.append_event(
            event_type=EventType.SIGNAL_CURATOR_V1,
            payload={
                "symbol": "BTC",
                "direction": "bullish",
                "conviction": float(i),
                "rationale": f"test signal {i}",
                "source": "test_producer",
                "pnl_pct": round(0.01 * i, 4),
            },
            source="test_producer",
        )


class _FakeArgs:
    """Minimal argparse.Namespace-like for testing."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __getattr__(self, item):
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExportKarmaJsonl:
    def test_export_karma_jsonl(self, tmp_path):
        repo_root = _scaffold_repo(tmp_path)
        db = Database(repo_root / "data" / "brain.db")
        _seed_db(db, count=5)
        db.close()

        out_path = tmp_path / "out.jsonl"
        args = _FakeArgs(
            export_cmd="karma",
            output_format="jsonl",
            include_chain=False,
            output_path=str(out_path),
            date_from=None,
            date_to=None,
        )

        rc = run_export(args, repo_root=repo_root)
        assert rc == 0
        assert out_path.exists()

        lines = [ln for ln in out_path.read_text().strip().splitlines() if ln]
        assert len(lines) == 5
        for line in lines:
            record = json.loads(line)
            assert "event_id" in record
            assert "source" in record
            assert "signal_type" in record
            assert "outcome" in record
            assert "pnl_pct" in record
            assert "karma_delta" in record
            assert "timestamp" in record

    def test_export_karma_json(self, tmp_path):
        repo_root = _scaffold_repo(tmp_path)
        db = Database(repo_root / "data" / "brain.db")
        _seed_db(db, count=3)
        db.close()

        out_path = tmp_path / "out.json"
        args = _FakeArgs(
            export_cmd="karma",
            output_format="json",
            include_chain=False,
            output_path=str(out_path),
            date_from=None,
            date_to=None,
        )

        rc = run_export(args, repo_root=repo_root)
        assert rc == 0
        data = json.loads(out_path.read_text())
        assert isinstance(data, list)
        assert len(data) == 3


class TestExportKarmaIncludeChain:
    def test_export_karma_include_chain(self, tmp_path):
        repo_root = _scaffold_repo(tmp_path)
        db = Database(repo_root / "data" / "brain.db")
        _seed_db(db, count=3)
        db.close()

        out_path = tmp_path / "chain.jsonl"
        args = _FakeArgs(
            export_cmd="karma",
            output_format="jsonl",
            include_chain=True,
            output_path=str(out_path),
            date_from=None,
            date_to=None,
        )

        rc = run_export(args, repo_root=repo_root)
        assert rc == 0

        lines = [ln for ln in out_path.read_text().strip().splitlines() if ln]
        assert len(lines) == 3
        for line in lines:
            record = json.loads(line)
            # chain fields must be present when --include-chain is set
            assert "chain_hash" in record, "chain_hash missing"
            assert "chain_seq" in record, "chain_seq missing"
            # Values should be non-null for real events
            assert record["chain_hash"] is not None
            assert isinstance(record["chain_seq"], int)

    def test_export_karma_no_chain_fields_without_flag(self, tmp_path):
        repo_root = _scaffold_repo(tmp_path)
        db = Database(repo_root / "data" / "brain.db")
        _seed_db(db, count=2)
        db.close()

        out_path = tmp_path / "nochain.jsonl"
        args = _FakeArgs(
            export_cmd="karma",
            output_format="jsonl",
            include_chain=False,
            output_path=str(out_path),
            date_from=None,
            date_to=None,
        )

        rc = run_export(args, repo_root=repo_root)
        assert rc == 0

        lines = [ln for ln in out_path.read_text().strip().splitlines() if ln]
        for line in lines:
            record = json.loads(line)
            assert "chain_hash" not in record
            assert "chain_seq" not in record


class TestExportKarmaDateFilter:
    def test_export_karma_date_filter_from(self, tmp_path):
        from datetime import UTC, datetime, timedelta

        repo_root = _scaffold_repo(tmp_path)
        db = Database(repo_root / "data" / "brain.db")
        _seed_db(db, count=5)
        db.close()

        # Use a future date so nothing matches
        future = (datetime.now(UTC) + timedelta(days=365)).strftime("%Y-%m-%d")
        out_path = tmp_path / "filtered.jsonl"
        args = _FakeArgs(
            export_cmd="karma",
            output_format="jsonl",
            include_chain=False,
            output_path=str(out_path),
            date_from=future,
            date_to=None,
        )

        rc = run_export(args, repo_root=repo_root)
        assert rc == 0
        lines = [ln for ln in out_path.read_text().strip().splitlines() if ln]
        assert len(lines) == 0, "Future date filter should return zero records"

    def test_export_karma_date_filter_to(self, tmp_path):
        from datetime import UTC, datetime, timedelta

        repo_root = _scaffold_repo(tmp_path)
        db = Database(repo_root / "data" / "brain.db")
        _seed_db(db, count=5)
        db.close()

        # Use a past date so nothing matches
        past = (datetime.now(UTC) - timedelta(days=365)).strftime("%Y-%m-%d")
        out_path = tmp_path / "filtered_to.jsonl"
        args = _FakeArgs(
            export_cmd="karma",
            output_format="jsonl",
            include_chain=False,
            output_path=str(out_path),
            date_from=None,
            date_to=past,
        )

        rc = run_export(args, repo_root=repo_root)
        assert rc == 0
        lines = [ln for ln in out_path.read_text().strip().splitlines() if ln]
        assert len(lines) == 0, "Past --to date filter should return zero records"

    def test_export_karma_date_filter_all_today(self, tmp_path):
        from datetime import UTC, datetime

        repo_root = _scaffold_repo(tmp_path)
        db = Database(repo_root / "data" / "brain.db")
        _seed_db(db, count=4)
        db.close()

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        out_path = tmp_path / "today.jsonl"
        args = _FakeArgs(
            export_cmd="karma",
            output_format="jsonl",
            include_chain=False,
            output_path=str(out_path),
            date_from=today,
            date_to=None,
        )

        rc = run_export(args, repo_root=repo_root)
        assert rc == 0
        lines = [ln for ln in out_path.read_text().strip().splitlines() if ln]
        assert len(lines) == 4
