"""tests.unit.test_oracle_query_log

Tests for the anonymized oracle query logger.
"""

from __future__ import annotations

import hashlib
import json

from engine.core.oracle_query_log import log_oracle_query


class TestLogAnonymizesProducerId:
    def test_log_anonymizes_producer_id(self, tmp_path):
        """Raw producer_id must NOT appear in the log; only its hash prefix."""
        producer_id = "my_very_secret_producer_abc123"

        log_oracle_query(
            producer_id=producer_id,
            signal_type="long_btc",
            has_provenance=True,
            data_dir=tmp_path,
        )

        log_path = tmp_path / "oracle_queries.jsonl"
        assert log_path.exists()
        content = log_path.read_text()

        # Raw ID must NOT be present
        assert producer_id not in content

        # Hash prefix must be present
        expected_hash = hashlib.sha256(producer_id.encode()).hexdigest()[:8]
        record = json.loads(content.strip())
        assert record["producer_id_hash"] == expected_hash

    def test_hash_is_deterministic(self, tmp_path):
        """Same producer_id always produces the same hash."""
        pid = "deterministic_producer"
        expected = hashlib.sha256(pid.encode()).hexdigest()[:8]

        log_oracle_query(pid, None, False, tmp_path)
        log_oracle_query(pid, None, True, tmp_path)

        log_path = tmp_path / "oracle_queries.jsonl"
        records = [json.loads(line) for line in log_path.read_text().strip().splitlines()]
        for r in records:
            assert r["producer_id_hash"] == expected


class TestLogAppendNotOverwrite:
    def test_log_appends_not_overwrites(self, tmp_path):
        """Multiple calls must append, not truncate."""
        for i in range(5):
            log_oracle_query(
                producer_id=f"producer_{i}",
                signal_type=None,
                has_provenance=bool(i % 2),
                data_dir=tmp_path,
            )

        log_path = tmp_path / "oracle_queries.jsonl"
        lines = [ln for ln in log_path.read_text().strip().splitlines() if ln]
        assert len(lines) == 5, f"Expected 5 records, got {len(lines)}"

    def test_appends_to_existing_file(self, tmp_path):
        """Calling log_oracle_query on a file that already has records appends."""
        log_path = tmp_path / "oracle_queries.jsonl"
        log_path.write_text('{"existing": true}\n')

        log_oracle_query("new_producer", "short_eth", False, tmp_path)

        lines = [ln for ln in log_path.read_text().strip().splitlines() if ln]
        assert len(lines) == 2
        # First line is the pre-existing record
        assert json.loads(lines[0]) == {"existing": True}
        # Second line is the new record
        new_record = json.loads(lines[1])
        assert "producer_id_hash" in new_record


class TestLogNoPii:
    def test_log_no_pii(self, tmp_path):
        """Log file must not contain raw producer IDs or any PII markers."""
        pii_ids = [
            "user@example.com",
            "192.168.1.1",
            "SuperSecretOperator_XYZ",
        ]
        for pid in pii_ids:
            log_oracle_query(pid, "long_btc", True, tmp_path)

        log_content = (tmp_path / "oracle_queries.jsonl").read_text()

        # None of the raw identifiers should appear verbatim
        for pid in pii_ids:
            assert pid not in log_content, f"PII leaked: {pid!r}"

    def test_log_record_schema(self, tmp_path):
        """Each log record must contain exactly the expected keys."""
        log_oracle_query("test_producer", "long_btc", True, tmp_path)

        log_path = tmp_path / "oracle_queries.jsonl"
        record = json.loads(log_path.read_text().strip())

        expected_keys = {"ts", "producer_id_hash", "signal_type", "has_provenance"}
        assert set(record.keys()) == expected_keys

    def test_log_signal_type_kept(self, tmp_path):
        """signal_type (a category label, not PII) is stored as-is."""
        log_oracle_query("any_producer", "long_btc", True, tmp_path)

        log_path = tmp_path / "oracle_queries.jsonl"
        record = json.loads(log_path.read_text().strip())
        assert record["signal_type"] == "long_btc"

    def test_log_signal_type_none_ok(self, tmp_path):
        """signal_type=None must be stored as JSON null."""
        log_oracle_query("any_producer", None, False, tmp_path)

        log_path = tmp_path / "oracle_queries.jsonl"
        record = json.loads(log_path.read_text().strip())
        assert record["signal_type"] is None

    def test_log_creates_data_dir(self, tmp_path):
        """log_oracle_query creates data_dir if it does not exist."""
        new_dir = tmp_path / "nested" / "data" / "dir"
        assert not new_dir.exists()

        log_oracle_query("producer", None, True, new_dir)

        assert new_dir.exists()
        assert (new_dir / "oracle_queries.jsonl").exists()
