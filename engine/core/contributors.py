from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from engine.core.database import Database


@dataclass(frozen=True, slots=True)
class Contributor:
    id: str
    node_id: str
    name: str
    role: str
    registered_at: str
    metadata: dict[str, Any]


class ContributorRegistry:
    def __init__(self, db: Database):
        self._db = db

    @staticmethod
    def _row_to_contributor(row: sqlite3.Row) -> Contributor:
        meta_raw = str(row["metadata"] or "{}")
        try:
            meta = json.loads(meta_raw)
        except Exception:
            meta = {}

        return Contributor(
            id=str(row["id"]),
            node_id=str(row["node_id"]),
            name=str(row["name"]),
            role=str(row["role"]),
            registered_at=str(row["registered_at"]),
            metadata=meta,
        )

    def register(self, *, node_id: str, name: str, role: str, metadata: dict | None = None) -> Contributor:
        contributor_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()
        meta = metadata or {}

        try:
            with self._db.conn:
                self._db.conn.execute(
                    """
                    INSERT INTO contributors (id, node_id, name, role, metadata, registered_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (contributor_id, node_id, name, role, json.dumps(meta, sort_keys=True), now, now),
                )
        except sqlite3.IntegrityError as e:
            raise ValueError("contributor.duplicate_node") from e

        return Contributor(
            id=contributor_id,
            node_id=node_id,
            name=name,
            role=role,
            registered_at=now,
            metadata=meta,
        )

    def get(self, contributor_id: str) -> Contributor | None:
        row = self._db.conn.execute(
            "SELECT id, node_id, name, role, registered_at, metadata FROM contributors WHERE id = ?",
            (contributor_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_contributor(row)

    def get_by_node(self, node_id: str) -> Contributor | None:
        row = self._db.conn.execute(
            "SELECT id, node_id, name, role, registered_at, metadata FROM contributors WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_contributor(row)

    def list_all(self) -> list[Contributor]:
        rows = self._db.conn.execute(
            "SELECT id, node_id, name, role, registered_at, metadata FROM contributors ORDER BY registered_at ASC",
        ).fetchall()
        return [self._row_to_contributor(r) for r in rows]

    def update(self, contributor_id: str, *, name: str | None = None, metadata: dict | None = None) -> Contributor | None:
        existing = self.get(contributor_id)
        if existing is None:
            return None

        new_name = name if name is not None else existing.name
        new_meta = metadata if metadata is not None else existing.metadata
        now = datetime.now(tz=UTC).isoformat()

        with self._db.conn:
            self._db.conn.execute(
                """
                UPDATE contributors
                SET name = ?, metadata = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_name, json.dumps(new_meta, sort_keys=True), now, contributor_id),
            )

        updated = self.get(contributor_id)
        return updated

    def deregister(self, contributor_id: str) -> bool:
        with self._db.conn:
            cur = self._db.conn.execute("DELETE FROM contributors WHERE id = ?", (contributor_id,))
        return cur.rowcount > 0
