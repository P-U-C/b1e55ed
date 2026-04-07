"""Stub endpoints for dashboard compatibility.

The dashboard requests /api/v1/alerts and /api/v1/conviction directly.
These are aliases/stubs returning valid empty responses until full
implementations land.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import AuthDep
from api.deps import get_db
from engine.core.database import Database

router = APIRouter(dependencies=[AuthDep])


@router.get("/alerts")
def get_alerts(db: Database = Depends(get_db)) -> dict:
    """Stub: returns empty alerts list. Dashboard uses /social/alerts for real data."""
    return {"items": [], "total": 0}


@router.get("/conviction")
def get_conviction(db: Database = Depends(get_db), limit: int = 20) -> list[dict]:
    """Stub: redirects to /brain/convictions logic. Dashboard sometimes hits this path."""
    rows = db.execute(
        """
        SELECT symbol, direction, confidence, magnitude, timeframe, regime, pcs_score, cts_score, ts
        FROM conviction_scores
        WHERE (symbol, ts) IN (
            SELECT symbol, MAX(ts) FROM conviction_scores GROUP BY symbol
        )
          AND ts >= datetime('now', '-48 hours')
        ORDER BY confidence DESC, magnitude DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "symbol": r[0],
            "direction": r[1],
            "confidence": float(r[2]) if r[2] is not None else 0.0,
            "magnitude": float(r[3]) if r[3] is not None else 0.0,
            "timeframe": r[4],
            "regime": r[5],
            "pcs_score": float(r[6]) if r[6] is not None else None,
            "cts_score": float(r[7]) if r[7] is not None else None,
            "ts": r[8],
        }
        for r in rows
    ]
