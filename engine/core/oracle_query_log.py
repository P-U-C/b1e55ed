"""engine.core.oracle_query_log

Anonymized demand-side query logging for the oracle.
Records what is being queried without revealing who queried it.

NEVER feeds back into karma scoring. This is demand intelligence only.

Privacy contract:
  - producer_id is hashed (first 8 hex chars of SHA-256) before storage.
  - signal_type is kept as-is; it is a category label, not PII.
  - No IP addresses, user-agents, or request identifiers are stored.
  - Log file is append-only JSONL: oracle_queries.jsonl in data_dir.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


def log_oracle_query(
    producer_id: str,
    signal_type: str | None,
    has_provenance: bool,
    data_dir: Path,
) -> None:
    """Append one anonymized query record to oracle_queries.jsonl.

    Parameters
    ----------
    producer_id:
        The raw producer identifier.  Only a short hash prefix is stored.
    signal_type:
        Optional signal-type filter supplied by the caller.
        Stored as-is because it is a category label, not a personal identifier.
    has_provenance:
        Whether the producer had provenance data at the time of the query.
    data_dir:
        Directory where oracle_queries.jsonl will be written.
        Created if it does not exist.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "ts": int(time.time()),
        "producer_id_hash": hashlib.sha256(producer_id.encode()).hexdigest()[:8],
        "signal_type": signal_type,  # category label — not PII
        "has_provenance": has_provenance,
    }

    log_path = data_dir / "oracle_queries.jsonl"
    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")
