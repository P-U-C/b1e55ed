from __future__ import annotations

from engine.core.database import Database
from engine.producers.base import BaseProducer
from engine.producers.registry import register


@register("fail-prod", domain="events")
class FailingProducer(BaseProducer):
    schedule = "*/1 * * * *"

    def collect(self):
        raise RuntimeError("boom")

    def normalize(self, raw):
        return []


class DummyClient:
    async def request(self, method: str, url: str, **kwargs):  # pragma: no cover
        raise AssertionError("should not call")


def test_producer_auto_quarantine_after_failures(tmp_path, monkeypatch):
    """After 5 consecutive failures, producer gets quarantined and future runs are skipped."""

    from engine.cli import main

    # Arrange repo layout for CLI
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    # Copy default config from repo is heavy; use defaults via Config() by letting CLI fall back to repo defaults.
    # Easiest: create minimal config/default.yaml in tmp_path.
    (tmp_path / "config" / "default.yaml").write_text("api: {auth_token: 'x'}\nuniverse: {symbols: ['BTC']}\n", encoding="utf-8")

    # Seed DB
    _ = Database(tmp_path / "data" / "brain.db")

    # Monkeypatch discovery/list_producers to only include our failing producer
    import engine.producers.registry as reg

    monkeypatch.setattr(reg, "list_producers", lambda: ["fail-prod"])
    monkeypatch.setattr(reg, "get_producer", lambda name: FailingProducer)

    # Ensure identity bypass so brain can run in test
    monkeypatch.setenv("B1E55ED_DEV_MODE", "1")

    monkeypatch.chdir(tmp_path)

    # Act: run 5 cycles
    for _i in range(5):
        _ = main(["brain", "--json"])  # should not raise

    db = Database(tmp_path / "data" / "brain.db")
    row = db.conn.execute(
        "SELECT consecutive_failures, quarantined_until, quarantined_reason FROM producer_health WHERE name = ?",
        ("fail-prod",),
    ).fetchone()
    assert row is not None
    assert int(row[0]) >= 5
    assert row[1] is not None
    assert str(row[2]) == "consecutive_failures"

    # Next run should be skipped (health=quarantined in output)
    rc = main(["brain", "--json"])
    assert rc == 0

    db.close()
