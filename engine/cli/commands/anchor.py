"""engine.cli.commands.anchor

b1e55ed anchor — post the current hash-chain root to stdout (and optionally EAS).

Usage:
    b1e55ed anchor [--format json|text] [--db PATH] [--eas]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from pathlib import Path
from typing import Any

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def build_anchor_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `anchor` subcommand and return its parser."""
    p = sub.add_parser(
        "anchor",
        help="Print the current hash-chain root (and optionally anchor it to EAS)",
    )
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text).",
    )
    p.add_argument(
        "--db",
        dest="db_path",
        default=None,
        help="Path to brain.db (defaults to data/brain.db relative to repo root).",
    )
    p.add_argument(
        "--eas",
        action="store_true",
        default=False,
        help="Create an off-chain EAS attestation of the root hash (requires eas.enabled).",
    )
    return p


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def run_anchor(args: argparse.Namespace, *, repo_root: Path) -> int:
    """Execute the anchor command.  Returns an exit code."""
    from engine.core.database import Database

    # Resolve DB path
    db_path_arg = getattr(args, "db_path", None)
    if db_path_arg:
        db_path = Path(str(db_path_arg))
    else:
        from engine.cli.main import _resolve_db_path

        db_path = _resolve_db_path(repo_root)

    if not db_path.exists():
        msg = f"anchor: database not found: {db_path}"
        print(msg, file=sys.stderr)
        return 1

    db = Database(db_path)
    now_iso = datetime.now(tz=UTC).isoformat()

    # Query the latest hash-chain root.
    # There is no `seq` column; we use rowid as a monotonic sequence.
    row = db.fetchone("SELECT hash, rowid, created_at FROM events ORDER BY rowid DESC LIMIT 1")

    if row is None:
        out: dict[str, Any] = {
            "status": "empty",
            "message": "no events in database",
            "ts": now_iso,
        }
        output_format = str(getattr(args, "output_format", "text"))
        if output_format == "json":
            print(_json_dumps(out))
        else:
            print("anchor: no events in database")
        return 0

    root_hash = str(row[0])
    seq = int(row[1])
    event_ts = str(row[2] or "")

    attestation_uid: str | None = None
    eas_warning: str | None = None

    use_eas = bool(getattr(args, "eas", False))

    if use_eas:
        try:
            from engine.core.config import Config

            cfg_path = repo_root / "config" / "user.yaml"
            config = Config.from_yaml(cfg_path) if cfg_path.exists() else Config.from_repo_defaults(repo_root)

            if not bool(config.eas.enabled):
                eas_warning = "EAS not enabled (set B1E55ED_EAS__ENABLED=true to use --eas)"
            elif not str(config.eas.schema_uid or "").strip():
                eas_warning = "EAS schema_uid not configured"
            else:
                from engine.integrations.eas import AttestationData, EASClient

                client = EASClient(
                    rpc_url=str(config.eas.rpc_url),
                    eas_address=str(config.eas.eas_contract),
                    schema_registry_address=str(config.eas.schema_registry),
                    private_key=str(config.eas.attester_private_key),
                )
                att = client.create_offchain_attestation(
                    AttestationData(
                        schema_uid=str(config.eas.schema_uid),
                        recipient=ZERO_ADDRESS,
                        data={"root": root_hash, "seq": seq, "ts": now_iso},
                    )
                )
                attestation_uid = str(att.get("uid") or "")
        except Exception as exc:
            eas_warning = f"EAS error: {exc}"

    output_format = str(getattr(args, "output_format", "text"))

    out = {
        "root": root_hash,
        "seq": seq,
        "event_ts": event_ts,
        "ts": now_iso,
    }
    if attestation_uid is not None:
        out["eas_uid"] = attestation_uid
    if eas_warning is not None:
        out["eas_warning"] = eas_warning

    if output_format == "json":
        print(_json_dumps(out))
    else:
        print(f"root:  {root_hash}")
        print(f"seq:   {seq}")
        print(f"ts:    {now_iso}")
        if event_ts:
            print(f"event: {event_ts}")
        if attestation_uid:
            print(f"eas:   {attestation_uid}")
        if eas_warning:
            print(f"warn:  {eas_warning}", file=sys.stderr)

    db.close()
    return 0
