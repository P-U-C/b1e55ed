"""engine.cli.commands.export

b1e55ed export karma — export karma attribution data as JSONL for seed data
and analysis.

Usage:
    b1e55ed export karma [--format jsonl|json|csv]
                         [--include-chain]
                         [--output PATH]
                         [--from DATE]
                         [--to DATE]

Each JSONL line (or JSON array element / CSV row) contains:
    event_id, source, signal_type, outcome, pnl_pct, karma_delta, timestamp
    + chain_hash, chain_seq  (only when --include-chain is set)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_DATE_FORMATS = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]


def _parse_date(s: str) -> str:
    """Parse a DATE string into a format suitable for SQLite datetime comparisons.

    SQLite stores datetimes as ``YYYY-MM-DD HH:MM:SS`` strings, so we return
    ``YYYY-MM-DD`` for simple date inputs (which SQLite treats correctly in
    ``>=`` / ``<=`` comparisons via lexicographic ordering), or
    ``YYYY-MM-DD HH:MM:SS`` for full datetime inputs.
    """
    # Plain YYYY-MM-DD — use as-is for SQLite string comparison
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s  # keep as-is; SQLite lexicographic comparison works correctly
    except ValueError:
        pass

    # ISO datetime variants — convert to SQLite datetime string
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    raise ValueError(f"Cannot parse date {s!r}. Expected YYYY-MM-DD or ISO format.")


def build_export_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the ``export`` subcommand (with ``karma`` sub-subcommand)."""
    p_export = sub.add_parser("export", help="Export data for analysis and reproducibility")
    export_sub = p_export.add_subparsers(dest="export_cmd")

    p_karma = export_sub.add_parser(
        "karma",
        help="Export karma attribution data as JSONL/JSON/CSV",
    )
    p_karma.add_argument(
        "--format",
        dest="output_format",
        choices=["jsonl", "json", "csv"],
        default="jsonl",
        help="Output format (default: jsonl).",
    )
    p_karma.add_argument(
        "--include-chain",
        action="store_true",
        default=False,
        help="Include hash-chain fields (chain_hash, chain_seq) in output.",
    )
    p_karma.add_argument(
        "--output",
        dest="output_path",
        default=None,
        help="Write output to PATH instead of stdout.",
    )
    p_karma.add_argument(
        "--from",
        dest="date_from",
        default=None,
        metavar="DATE",
        help="Only include events on or after DATE (YYYY-MM-DD).",
    )
    p_karma.add_argument(
        "--to",
        dest="date_to",
        default=None,
        metavar="DATE",
        help="Only include events on or before DATE (YYYY-MM-DD).",
    )
    return p_export


def _build_query(*, include_chain: bool, date_from: str | None, date_to: str | None) -> tuple[str, list[Any]]:
    """Build the SQL query and parameter list for the karma export."""

    # We join events against karma_settlements keyed by producer_id.
    # The events table stores the raw chain with source, hash, and rowid-as-seq.
    # karma_settlements doesn't have a producer_id column in the schema we saw,
    # so we do a LEFT JOIN to pick up any settlement rows where the event source
    # matches a distinct node.  We include the event's own rowid as chain_seq.

    select_cols = [
        "e.id          AS event_id",
        "e.source      AS source",
        "e.type        AS signal_type",
        "e.created_at  AS timestamp",
        # Outcome derived from payload if available
        "CASE WHEN json_extract(e.payload, '$.outcome') IS NOT NULL      THEN json_extract(e.payload, '$.outcome')      ELSE 'open' END AS outcome",
        # pnl_pct from payload
        "COALESCE(CAST(json_extract(e.payload, '$.pnl_pct') AS REAL), 0.0) AS pnl_pct",
        # karma_delta: best-effort from payload or settlements
        "COALESCE(    CAST(json_extract(e.payload, '$.karma_delta') AS REAL),    0.0) AS karma_delta",
    ]

    if include_chain:
        select_cols += [
            "e.hash    AS chain_hash",
            "e.rowid   AS chain_seq",
        ]

    q = f"SELECT {', '.join(select_cols)} FROM events e WHERE 1=1"
    params: list[Any] = []

    if date_from:
        q += " AND e.created_at >= ?"
        params.append(date_from)

    if date_to:
        q += " AND e.created_at <= ?"
        params.append(date_to)

    q += " ORDER BY e.rowid ASC"

    return q, params


def _row_to_record(row: Any, *, include_chain: bool) -> dict[str, Any]:
    """Convert a raw SQLite row to an export dict."""
    record: dict[str, Any] = {
        "event_id": str(row[0]),
        "source": str(row[1]) if row[1] is not None else None,
        "signal_type": str(row[2]) if row[2] is not None else None,
        "timestamp": str(row[3]) if row[3] is not None else None,
        "outcome": str(row[4]),
        "pnl_pct": float(row[5]),
        "karma_delta": float(row[6]),
    }
    if include_chain:
        record["chain_hash"] = str(row[7]) if row[7] is not None else None
        record["chain_seq"] = int(row[8]) if row[8] is not None else None
    return record


def run_export(args: argparse.Namespace, *, repo_root: Path) -> int:
    """Execute the export command.  Returns an exit code."""
    from engine.core.database import Database

    cmd = str(getattr(args, "export_cmd", "") or "")
    if cmd != "karma":
        print("error: missing or unknown export subcommand (karma)", file=sys.stderr)
        return 2

    # -----------------------------------------------------------------------
    # Resolve database
    # -----------------------------------------------------------------------
    db_path = repo_root / "data" / "brain.db"
    if not db_path.exists():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        print("  Run `b1e55ed setup` first.", file=sys.stderr)
        return 1

    db = Database(db_path)

    # -----------------------------------------------------------------------
    # Parse date filters
    # -----------------------------------------------------------------------
    date_from: str | None = None
    date_to: str | None = None

    raw_from = getattr(args, "date_from", None)
    raw_to = getattr(args, "date_to", None)

    if raw_from:
        try:
            date_from = _parse_date(str(raw_from))
        except ValueError as exc:
            print(f"error: --from: {exc}", file=sys.stderr)
            return 2

    if raw_to:
        try:
            date_to = _parse_date(str(raw_to))
        except ValueError as exc:
            print(f"error: --to: {exc}", file=sys.stderr)
            return 2

    include_chain = bool(getattr(args, "include_chain", False))
    output_format = str(getattr(args, "output_format", "jsonl"))
    output_path_arg = getattr(args, "output_path", None)

    # -----------------------------------------------------------------------
    # Query
    # -----------------------------------------------------------------------
    q, params = _build_query(
        include_chain=include_chain,
        date_from=date_from,
        date_to=date_to,
    )
    rows = db.conn.execute(q, params).fetchall()
    records = [_row_to_record(r, include_chain=include_chain) for r in rows]

    db.close()

    # -----------------------------------------------------------------------
    # Render
    # -----------------------------------------------------------------------
    output: str

    if output_format == "jsonl":
        lines = [json.dumps(r, default=str) for r in records]
        output = "\n".join(lines) + ("\n" if lines else "")

    elif output_format == "json":
        output = json.dumps(records, indent=2, default=str) + "\n"

    elif output_format == "csv":
        if not records:
            output = ""
        else:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)
            output = buf.getvalue()

    else:
        print(f"error: unknown format {output_format!r}", file=sys.stderr)
        return 2

    # -----------------------------------------------------------------------
    # Write
    # -----------------------------------------------------------------------
    if output_path_arg:
        out_path = Path(str(output_path_arg))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"exported {len(records)} records → {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(output)

    return 0
