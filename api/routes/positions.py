from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path

from api.auth import AuthDep
from api.deps import get_db
from api.schemas.positions import PositionResponse
from engine.core.database import Database


router = APIRouter(prefix="/positions", dependencies=[AuthDep])


def _parse_dt(ts: str | None) -> datetime | None:
    if ts is None:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _row_to_position(r) -> PositionResponse:
    return PositionResponse(
        id=str(r[0]),
        platform=str(r[1]),
        asset=str(r[2]),
        direction=str(r[3]),
        entry_price=float(r[4]),
        size_notional=float(r[5]),
        leverage=float(r[6]) if r[6] is not None else None,
        margin_type=str(r[7]) if r[7] is not None else None,
        stop_loss=float(r[8]) if r[8] is not None else None,
        take_profit=float(r[9]) if r[9] is not None else None,
        opened_at=_parse_dt(str(r[10])) or datetime.fromtimestamp(0),
        closed_at=_parse_dt(str(r[11])) if r[11] is not None else None,
        status=str(r[12]),
        realized_pnl=float(r[13]) if r[13] is not None else None,
        conviction_id=int(r[14]) if r[14] is not None else None,
        regime_at_entry=str(r[15]) if r[15] is not None else None,
        pcs_at_entry=float(r[16]) if r[16] is not None else None,
        cts_at_entry=float(r[17]) if r[17] is not None else None,
    )


@router.get("", response_model=list[PositionResponse])
def list_positions(db: Database = Depends(get_db)) -> list[PositionResponse]:
    rows = db.conn.execute(
        """
        SELECT id, platform, asset, direction, entry_price, size_notional, leverage, margin_type,
               stop_loss, take_profit, opened_at, closed_at, status, realized_pnl, conviction_id,
               regime_at_entry, pcs_at_entry, cts_at_entry
        FROM positions
        ORDER BY opened_at DESC
        """
    ).fetchall()
    return [_row_to_position(r) for r in rows]


@router.get("/{position_id}", response_model=PositionResponse)
def get_position(
    position_id: str = Path(..., description="Position id"),
    db: Database = Depends(get_db),
) -> PositionResponse:
    r = db.conn.execute(
        """
        SELECT id, platform, asset, direction, entry_price, size_notional, leverage, margin_type,
               stop_loss, take_profit, opened_at, closed_at, status, realized_pnl, conviction_id,
               regime_at_entry, pcs_at_entry, cts_at_entry
        FROM positions
        WHERE id = ?
        LIMIT 1
        """,
        (position_id,),
    ).fetchone()

    if r is None:
        raise HTTPException(status_code=404, detail="Position not found")

    return _row_to_position(r)
