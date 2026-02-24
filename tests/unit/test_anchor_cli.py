"""tests.unit.test_anchor_cli

Unit tests for `b1e55ed anchor` CLI command.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from engine.cli.main import main
from engine.core.database import Database
from engine.core.events import EventType


def _scaffold_repo(tmp_path: Path) -> Path:
    """Create a minimal repo root layout for CLI tests."""
    repo_root = tmp_path
    src_root = Path(__file__).resolve().parents[2]

    (repo_root / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_root / "config" / "default.yaml", repo_root / "config" / "default.yaml")
    shutil.copytree(src_root / "config" / "presets", repo_root / "config" / "presets")

    (repo_root / "data").mkdir(parents=True, exist_ok=True)
    _ = Database(repo_root / "data" / "brain.db")

    # Create fake forged identity so the identity gate doesn't block CLI tests.
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


def _seed_event(db: Database) -> str:
    """Append a dummy event and return its hash."""
    ev = db.append_event(
        event_type=EventType.SIGNAL_CURATOR_V1,
        payload={"symbol": "BTC", "direction": "bullish", "conviction": 5.0, "rationale": "test", "source": "test"},
        source="test",
    )
    return ev.hash


class TestAnchorPrintsRootHash:
    def test_anchor_prints_root_hash(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo_root = _scaffold_repo(tmp_path)
        monkeypatch.chdir(repo_root)

        db = Database(repo_root / "data" / "brain.db")
        expected_hash = _seed_event(db)
        db.close()

        rc = main(["anchor"])
        assert rc == 0

        out = capsys.readouterr().out
        assert expected_hash in out

    def test_anchor_json_format(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo_root = _scaffold_repo(tmp_path)
        monkeypatch.chdir(repo_root)

        db = Database(repo_root / "data" / "brain.db")
        expected_hash = _seed_event(db)
        db.close()

        rc = main(["anchor", "--format", "json"])
        assert rc == 0

        out = capsys.readouterr().out.strip()
        data = json.loads(out)
        assert data["root"] == expected_hash
        assert "seq" in data
        assert "ts" in data

    def test_anchor_explicit_db_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo_root = _scaffold_repo(tmp_path)
        monkeypatch.chdir(repo_root)

        db_path = repo_root / "data" / "brain.db"
        db = Database(db_path)
        expected_hash = _seed_event(db)
        db.close()

        rc = main(["anchor", "--db", str(db_path)])
        assert rc == 0

        out = capsys.readouterr().out
        assert expected_hash in out


class TestAnchorNoEvents:
    def test_anchor_no_events_exits_cleanly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Empty database should produce a graceful message and exit 0."""
        repo_root = _scaffold_repo(tmp_path)
        monkeypatch.chdir(repo_root)

        rc = main(["anchor"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "no events" in out.lower()

    def test_anchor_no_events_json(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo_root = _scaffold_repo(tmp_path)
        monkeypatch.chdir(repo_root)

        rc = main(["anchor", "--format", "json"])
        assert rc == 0

        out = capsys.readouterr().out.strip()
        data = json.loads(out)
        assert data["status"] == "empty"


class TestAnchorEasNotConfigured:
    def test_anchor_eas_flag_eas_disabled_warns_and_exits_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--eas flag with EAS disabled → warning printed, exit 0 (not an error)."""
        repo_root = _scaffold_repo(tmp_path)
        monkeypatch.chdir(repo_root)

        # Seed at least one event so we don't hit the empty-DB path
        db = Database(repo_root / "data" / "brain.db")
        _seed_event(db)
        db.close()

        rc = main(["anchor", "--eas"])
        assert rc == 0  # not an error

        # Warning should appear on stderr
        captured = capsys.readouterr()
        assert "EAS" in captured.err or "eas" in captured.err.lower()

    def test_anchor_eas_flag_json_format_includes_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--eas flag with EAS disabled + JSON format → eas_warning in output."""
        repo_root = _scaffold_repo(tmp_path)
        monkeypatch.chdir(repo_root)

        db = Database(repo_root / "data" / "brain.db")
        _seed_event(db)
        db.close()

        rc = main(["anchor", "--eas", "--format", "json"])
        assert rc == 0

        out = capsys.readouterr().out.strip()
        data = json.loads(out)
        assert "eas_warning" in data
        assert data["eas_warning"]  # non-empty
