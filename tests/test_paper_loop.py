"""Tests for Sprint S7 -- paper loop closure + stratification tracking."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.brain.learning import StratificationTracker
from engine.core.config import Config, UniverseBundle
from engine.core.database import Database
from engine.core.events import EventType
from engine.security.identity import NodeIdentity


@pytest.fixture
def db(tmp_path):
    d = Database(db_path=tmp_path / "test.db")
    yield d
    d.close()


@pytest.fixture
def config():
    return Config()


class TestStratificationTracker:
    def test_record_signal_high_bucket(self, db):
        tracker = StratificationTracker(db)
        now = datetime.now(tz=UTC)
        tracker.record_signal("sig1", "BTC", 0.70, "long", now)
        row = db.conn.execute("SELECT * FROM signal_stratification WHERE signal_id = 'sig1'").fetchone()
        assert row is not None
        assert row["bucket"] == "high"

    def test_record_signal_low_bucket(self, db):
        tracker = StratificationTracker(db)
        now = datetime.now(tz=UTC)
        tracker.record_signal("sig2", "ETH", 0.30, "short", now)
        row = db.conn.execute("SELECT * FROM signal_stratification WHERE signal_id = 'sig2'").fetchone()
        assert row is not None
        assert row["bucket"] == "low"

    def test_record_outcome_updates_row(self, db):
        tracker = StratificationTracker(db)
        now = datetime.now(tz=UTC)
        tracker.record_signal("sig3", "BTC", 0.70, "long", now)
        tracker.record_outcome("sig3", 5.50, now)
        row = db.conn.execute("SELECT * FROM signal_stratification WHERE signal_id = 'sig3'").fetchone()
        assert row["outcome_pnl_usd"] == 5.50
        assert row["attributed_at"] is not None

    def test_report_structure(self, db):
        tracker = StratificationTracker(db)
        now = datetime.now(tz=UTC)
        tracker.record_signal("s1", "BTC", 0.70, "long", now)
        tracker.record_signal("s2", "ETH", 0.50, "long", now)
        tracker.record_signal("s3", "SOL", 0.30, "short", now)
        tracker.record_outcome("s1", 10.0, now)

        report = tracker.get_report()
        assert "high" in report
        assert "mid" in report
        assert "low" in report
        assert "as_of" in report
        assert report["high"]["count"] == 1
        assert report["high"]["with_outcome"] == 1
        assert report["high"]["avg_pnl_usd"] == 10.0
        assert report["high"]["win_rate"] == 1.0

    def test_report_cli_stratification(self, db, config, capsys):
        from engine.cli.commands.report import run_report

        tracker = StratificationTracker(db)
        now = datetime.now(tz=UTC)
        tracker.record_signal("s1", "BTC", 0.70, "long", now)

        ctx = MagicMock()
        ctx.db = db
        args = MagicMock()
        args.stratification = True
        args.cockpit_summary = False
        args.json = False

        run_report(ctx, args)
        captured = capsys.readouterr()
        assert "Stratification" in captured.out
        assert "High" in captured.out


class TestAutoPaperTrade:
    def test_auto_paper_trade_on_high_confidence(self, db, config):
        """confidence >= 0.65 + SAFE -> OMS called."""
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"
        mock_oms = MagicMock()
        mock_oms.submit.return_value = MagicMock(status="filled")
        orch = BrainOrchestrator(config, db, identity, oms=mock_oms)

        mock_conv_result = MagicMock()
        mock_conv_result.score.confidence = 0.75
        mock_conv_result.score.direction = "long"
        mock_conv_result.score.symbol = "BTC"
        mock_conv_result.score.magnitude = 8.0
        mock_conv_result.final_conviction = 80.0
        mock_conv_result.pcs = 80.0
        mock_conv_result.cts = 0.0

        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
            patch.object(orch, "_resolve_mid_price", return_value=95000.0),
        ):
            mock_dq.return_value = MagicMock(per_domain_quality={})
            mock_synth_res = MagicMock()
            mock_synth_res.snapshot.cycle_id = "c1"
            mock_synth_res.snapshot.symbol = "BTC"
            mock_synth_res.snapshot.ts = datetime.now(tz=UTC)
            mock_synth_res.snapshot.features = {}
            mock_synth_res.snapshot.source_event_ids = []
            mock_synth_res.snapshot.regime = "BULL"
            mock_synth_res.snapshot.version = "v1"
            mock_synth.return_value = mock_synth_res

            mock_regime_res = MagicMock()
            mock_regime_res.state.regime = "BULL"
            mock_regime.return_value = mock_regime_res

            orch.run_cycle(["BTC"])
            mock_oms.submit.assert_called_once()

    def test_auto_trade_allows_symbol_when_bundle_policy_matches(self, db, config):
        """Bundle policy allows BTC (crypto/global) -> OMS called."""
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"

        config.universe = config.universe.model_copy(
            update={
                "bundles": [
                    UniverseBundle(
                        id="crypto-core",
                        name="Crypto Core",
                        symbols=["BTC"],
                        asset_class="crypto",
                        venue="global",
                        tags=["starter"],
                        enabled=True,
                        source="user",
                    )
                ]
            }
        )

        mock_oms = MagicMock()
        mock_oms.submit.return_value = MagicMock(status="filled")
        orch = BrainOrchestrator(config, db, identity, oms=mock_oms)

        mock_conv_result = MagicMock()
        mock_conv_result.score.confidence = 0.80
        mock_conv_result.score.direction = "long"
        mock_conv_result.score.symbol = "BTC"
        mock_conv_result.score.magnitude = 8.0
        mock_conv_result.final_conviction = 85.0
        mock_conv_result.pcs = 85.0
        mock_conv_result.cts = 0.0

        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
            patch.object(orch, "_resolve_mid_price", return_value=95000.0),
        ):
            mock_dq.return_value = MagicMock(per_domain_quality={})
            mock_synth_res = MagicMock()
            mock_synth_res.snapshot.cycle_id = "c1"
            mock_synth_res.snapshot.symbol = "BTC"
            mock_synth_res.snapshot.ts = datetime.now(tz=UTC)
            mock_synth_res.snapshot.features = {}
            mock_synth_res.snapshot.source_event_ids = []
            mock_synth_res.snapshot.regime = "BULL"
            mock_synth_res.snapshot.version = "v1"
            mock_synth.return_value = mock_synth_res

            mock_regime_res = MagicMock()
            mock_regime_res.state.regime = "BULL"
            mock_regime.return_value = mock_regime_res

            orch.run_cycle(["BTC"])
            mock_oms.submit.assert_called_once()

    def test_auto_trade_skips_symbol_blocked_by_bundle_policy(self, db, config, caplog):
        """Disallowed bundle metadata blocks OMS submit and emits explicit gating reason."""
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"

        config.universe = config.universe.model_copy(
            update={
                "bundles": [
                    UniverseBundle(
                        id="tradfi-only",
                        name="TradFi Only",
                        symbols=["BTC"],
                        asset_class="tradfi",
                        venue="nyse",
                        tags=["starter"],
                        enabled=True,
                        source="user",
                    )
                ]
            }
        )

        mock_oms = MagicMock()
        orch = BrainOrchestrator(config, db, identity, oms=mock_oms)

        mock_conv_result = MagicMock()
        mock_conv_result.score.confidence = 0.80
        mock_conv_result.score.direction = "long"
        mock_conv_result.score.symbol = "BTC"
        mock_conv_result.score.magnitude = 8.0
        mock_conv_result.final_conviction = 85.0
        mock_conv_result.pcs = 85.0
        mock_conv_result.cts = 0.0

        caplog.set_level("INFO", logger="b1e55ed.orchestrator")

        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
            patch.object(orch, "_resolve_mid_price", return_value=95000.0),
        ):
            mock_dq.return_value = MagicMock(per_domain_quality={})
            mock_synth_res = MagicMock()
            mock_synth_res.snapshot.cycle_id = "c1"
            mock_synth_res.snapshot.symbol = "BTC"
            mock_synth_res.snapshot.ts = datetime.now(tz=UTC)
            mock_synth_res.snapshot.features = {}
            mock_synth_res.snapshot.source_event_ids = []
            mock_synth_res.snapshot.regime = "BULL"
            mock_synth_res.snapshot.version = "v1"
            mock_synth.return_value = mock_synth_res

            mock_regime_res = MagicMock()
            mock_regime_res.state.regime = "BULL"
            mock_regime.return_value = mock_regime_res

            orch.run_cycle(["BTC"])

        mock_oms.submit.assert_not_called()
        assert any("execution_gated_by_bundle_policy" in rec.message for rec in caplog.records)

        audit_events = db.get_events(event_type=EventType.AUDIT_V1, limit=10)
        gating = next((ev for ev in audit_events if ev.payload.get("reason") == "execution_gated_by_bundle_policy"), None)
        assert gating is not None
        assert gating.payload.get("gate_reason") == "asset_class_not_allowed"
        assert gating.payload.get("symbol") == "BTC"

    def test_auto_trade_legacy_universe_fallback_without_bundles(self, db, config):
        """No bundles configured -> legacy auto-paper-trade path remains active."""
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"

        config.universe = config.universe.model_copy(update={"symbols": ["BTC"], "bundles": []})

        mock_oms = MagicMock()
        mock_oms.submit.return_value = MagicMock(status="filled")
        orch = BrainOrchestrator(config, db, identity, oms=mock_oms)

        mock_conv_result = MagicMock()
        mock_conv_result.score.confidence = 0.80
        mock_conv_result.score.direction = "long"
        mock_conv_result.score.symbol = "BTC"
        mock_conv_result.score.magnitude = 8.0
        mock_conv_result.final_conviction = 85.0
        mock_conv_result.pcs = 85.0
        mock_conv_result.cts = 0.0

        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
            patch.object(orch, "_resolve_mid_price", return_value=95000.0),
        ):
            mock_dq.return_value = MagicMock(per_domain_quality={})
            mock_synth_res = MagicMock()
            mock_synth_res.snapshot.cycle_id = "c1"
            mock_synth_res.snapshot.symbol = "BTC"
            mock_synth_res.snapshot.ts = datetime.now(tz=UTC)
            mock_synth_res.snapshot.features = {}
            mock_synth_res.snapshot.source_event_ids = []
            mock_synth_res.snapshot.regime = "BULL"
            mock_synth_res.snapshot.version = "v1"
            mock_synth.return_value = mock_synth_res

            mock_regime_res = MagicMock()
            mock_regime_res.state.regime = "BULL"
            mock_regime.return_value = mock_regime_res

            orch.run_cycle(["BTC"])
            mock_oms.submit.assert_called_once()

    def test_no_auto_trade_on_mid_confidence(self, db, config):
        """0.45-0.65 -> OMS not called."""
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"
        config.brain.auto_paper_trade_min_confidence = 0.65
        orch = BrainOrchestrator(config, db, identity)

        mock_conv_result = MagicMock()
        mock_oms_mid = MagicMock()
        orch._oms = mock_oms_mid
        mock_conv_result.score.confidence = 0.55
        mock_conv_result.score.direction = "long"
        mock_conv_result.score.symbol = "BTC"
        mock_conv_result.score.magnitude = 2.0
        mock_conv_result.final_conviction = 60.0

        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
        ):
            mock_dq.return_value = MagicMock(per_domain_quality={})
            mock_synth_res = MagicMock()
            mock_synth_res.snapshot.cycle_id = "c1"
            mock_synth_res.snapshot.symbol = "BTC"
            mock_synth_res.snapshot.ts = datetime.now(tz=UTC)
            mock_synth_res.snapshot.features = {}
            mock_synth_res.snapshot.source_event_ids = []
            mock_synth_res.snapshot.regime = "BULL"
            mock_synth_res.snapshot.version = "v1"
            mock_synth.return_value = mock_synth_res

            mock_regime_res = MagicMock()
            mock_regime_res.state.regime = "BULL"
            mock_regime.return_value = mock_regime_res

            orch.run_cycle(["BTC"])
            mock_oms_mid.submit.assert_not_called()

    def test_no_auto_trade_on_low_confidence(self, db, config):
        """< 0.45 -> OMS not called."""
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"
        orch = BrainOrchestrator(config, db, identity)

        mock_conv_result = MagicMock()
        mock_oms_low = MagicMock()
        orch._oms = mock_oms_low
        mock_conv_result.score.confidence = 0.30
        mock_conv_result.score.direction = "long"
        mock_conv_result.score.symbol = "BTC"
        mock_conv_result.score.magnitude = 2.0
        mock_conv_result.final_conviction = 40.0

        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
        ):
            mock_dq.return_value = MagicMock(per_domain_quality={})
            mock_synth_res = MagicMock()
            mock_synth_res.snapshot.cycle_id = "c1"
            mock_synth_res.snapshot.symbol = "BTC"
            mock_synth_res.snapshot.ts = datetime.now(tz=UTC)
            mock_synth_res.snapshot.features = {}
            mock_synth_res.snapshot.source_event_ids = []
            mock_synth_res.snapshot.regime = "BULL"
            mock_synth_res.snapshot.version = "v1"
            mock_synth.return_value = mock_synth_res

            mock_regime_res = MagicMock()
            mock_regime_res.state.regime = "BULL"
            mock_regime.return_value = mock_regime_res

            orch.run_cycle(["BTC"])
            mock_oms_low.submit.assert_not_called()

    def test_auto_trade_on_strong_directional_fallback(self, db, config):
        """Low confidence can still auto-trade on very strong directional conviction."""
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"
        mock_oms = MagicMock()
        mock_oms.submit.return_value = MagicMock(status="filled")
        orch = BrainOrchestrator(config, db, identity, oms=mock_oms)

        mock_conv_result = MagicMock()
        mock_conv_result.score.confidence = 0.10
        mock_conv_result.score.direction = "short"
        mock_conv_result.score.symbol = "BTC"
        mock_conv_result.score.magnitude = 7.0
        mock_conv_result.final_conviction = 0.0
        mock_conv_result.pcs = 0.0
        mock_conv_result.cts = 0.0

        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
            patch.object(orch, "_resolve_mid_price", return_value=95000.0),
        ):
            mock_dq.return_value = MagicMock(per_domain_quality={})
            mock_synth_res = MagicMock()
            mock_synth_res.snapshot.cycle_id = "c1"
            mock_synth_res.snapshot.symbol = "BTC"
            mock_synth_res.snapshot.ts = datetime.now(tz=UTC)
            mock_synth_res.snapshot.features = {}
            mock_synth_res.snapshot.source_event_ids = []
            mock_synth_res.snapshot.regime = "BULL"
            mock_synth_res.snapshot.version = "v1"
            mock_synth.return_value = mock_synth_res

            mock_regime_res = MagicMock()
            mock_regime_res.state.regime = "BULL"
            mock_regime.return_value = mock_regime_res

            orch.run_cycle(["BTC"])
            mock_oms.submit.assert_called_once()

    def test_auto_trade_disabled_by_config(self, db, config):
        """auto_paper_trade=False -> no trade."""
        config.brain.auto_paper_trade = False
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"
        orch = BrainOrchestrator(config, db, identity)

        mock_conv_result = MagicMock()
        mock_oms_cfg = MagicMock()
        orch._oms = mock_oms_cfg
        mock_conv_result.score.confidence = 0.80
        mock_conv_result.score.direction = "long"
        mock_conv_result.score.symbol = "BTC"
        mock_conv_result.final_conviction = 85.0

        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
        ):
            mock_dq.return_value = MagicMock(per_domain_quality={})
            mock_synth_res = MagicMock()
            mock_synth_res.snapshot.cycle_id = "c1"
            mock_synth_res.snapshot.symbol = "BTC"
            mock_synth_res.snapshot.ts = datetime.now(tz=UTC)
            mock_synth_res.snapshot.features = {}
            mock_synth_res.snapshot.source_event_ids = []
            mock_synth_res.snapshot.regime = "BULL"
            mock_synth_res.snapshot.version = "v1"
            mock_synth.return_value = mock_synth_res

            mock_regime_res = MagicMock()
            mock_regime_res.state.regime = "BULL"
            mock_regime.return_value = mock_regime_res

            orch.run_cycle(["BTC"])
            mock_oms_cfg.submit.assert_not_called()

    def test_auto_trade_nonblocking_on_oms_error(self, db, config):
        """OMS raises -> brain cycle continues."""
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"
        orch = BrainOrchestrator(config, db, identity)

        mock_conv_result = MagicMock()
        mock_conv_result.score.confidence = 0.80
        mock_conv_result.score.direction = "long"
        mock_conv_result.score.symbol = "BTC"
        mock_conv_result.final_conviction = 85.0

        mock_oms_err = MagicMock()
        mock_oms_err.submit.side_effect = RuntimeError("OMS broken")
        orch._oms = mock_oms_err
        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
        ):
            mock_dq.return_value = MagicMock(per_domain_quality={})
            mock_synth_res = MagicMock()
            mock_synth_res.snapshot.cycle_id = "c1"
            mock_synth_res.snapshot.symbol = "BTC"
            mock_synth_res.snapshot.ts = datetime.now(tz=UTC)
            mock_synth_res.snapshot.features = {}
            mock_synth_res.snapshot.source_event_ids = []
            mock_synth_res.snapshot.regime = "BULL"
            mock_synth_res.snapshot.version = "v1"
            mock_synth.return_value = mock_synth_res

            mock_regime_res = MagicMock()
            mock_regime_res.state.regime = "BULL"
            mock_regime.return_value = mock_regime_res

            result = orch.run_cycle(["BTC"])
            assert result is not None
