"""Tests for Sprint S7 -- paper loop closure + stratification tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from engine.brain.learning import StratificationTracker
from engine.core.config import Config
from engine.core.database import Database
from engine.security.identity import NodeIdentity

UTC = UTC


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
        orch = BrainOrchestrator(config, db, identity)

        mock_conv_result = MagicMock()
        mock_conv_result.score.confidence = 0.75
        mock_conv_result.score.direction = "long"
        mock_conv_result.score.symbol = "BTC"
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
            patch("engine.brain.orchestrator.OMS") as mock_oms_cls,
            patch("engine.brain.orchestrator.default_sizer_from_config"),
            patch("engine.brain.orchestrator.Preflight"),
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

            mock_oms_instance = MagicMock()
            mock_oms_instance.submit.return_value = MagicMock(status="filled")
            mock_oms_cls.return_value = mock_oms_instance

            orch.run_cycle(["BTC"])
            mock_oms_instance.submit.assert_called_once()

    def test_no_auto_trade_on_mid_confidence(self, db, config):
        """0.45-0.65 -> OMS not called."""
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"
        orch = BrainOrchestrator(config, db, identity)

        mock_conv_result = MagicMock()
        mock_conv_result.score.confidence = 0.55
        mock_conv_result.score.direction = "long"
        mock_conv_result.score.symbol = "BTC"
        mock_conv_result.final_conviction = 60.0

        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
            patch("engine.brain.orchestrator.OMS") as mock_oms_cls,
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
            mock_oms_cls.assert_not_called()

    def test_no_auto_trade_on_low_confidence(self, db, config):
        """< 0.45 -> OMS not called."""
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"
        orch = BrainOrchestrator(config, db, identity)

        mock_conv_result = MagicMock()
        mock_conv_result.score.confidence = 0.30
        mock_conv_result.score.direction = "long"
        mock_conv_result.score.symbol = "BTC"
        mock_conv_result.final_conviction = 40.0

        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
            patch("engine.brain.orchestrator.OMS") as mock_oms_cls,
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
            mock_oms_cls.assert_not_called()

    def test_auto_trade_disabled_by_config(self, db, config):
        """auto_paper_trade=False -> no trade."""
        config.brain.auto_paper_trade = False
        from engine.brain.orchestrator import BrainOrchestrator

        identity = MagicMock(spec=NodeIdentity)
        identity.node_id = "test-node"
        orch = BrainOrchestrator(config, db, identity)

        mock_conv_result = MagicMock()
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
            patch("engine.brain.orchestrator.OMS") as mock_oms_cls,
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
            mock_oms_cls.assert_not_called()

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

        with (
            patch.object(orch.data_quality, "evaluate") as mock_dq,
            patch.object(orch.synthesis, "synthesize") as mock_synth,
            patch.object(orch.regime, "detect") as mock_regime,
            patch.object(orch.regime, "emit_if_changed"),
            patch.object(orch.conviction, "compute", return_value=mock_conv_result),
            patch.object(orch.conviction, "emit"),
            patch.object(orch.decision, "decide_and_emit", return_value=None),
            patch("engine.brain.orchestrator.OMS", side_effect=RuntimeError("OMS broken")),
            patch("engine.brain.orchestrator.default_sizer_from_config"),
            patch("engine.brain.orchestrator.Preflight"),
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
