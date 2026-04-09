from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel

from api.auth import AuthDep
from api.deps import get_config, get_db
from api.errors import B1e55edError
from api.schemas.positions import (
    PositionResponse,
    PublicPositionResponse,
    PublicPositionsResponse,
    PublicPositionsSummaryResponse,
)
from engine.core.config import Config
from engine.core.database import Database

public_router = APIRouter(prefix="/positions")
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
        horizon_hours=float(r[18]) if len(r) > 18 and r[18] is not None else None,
    )


_OPEN_POSITION_STATUSES = {"open", "monitoring", "degrading", "closing"}


def _to_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _row_to_public_position(r) -> PublicPositionResponse:
    opened_at = _to_utc(_parse_dt(str(r[7]))) or datetime.fromtimestamp(0, tz=UTC)
    closed_at = _to_utc(_parse_dt(str(r[8]))) if r[8] is not None else None

    return PublicPositionResponse(
        id=str(r[0]),
        asset=str(r[1]),
        direction=str(r[2]),
        entry_price=float(r[3]),
        size_notional=float(r[4]),
        stop_loss=float(r[5]) if r[5] is not None else None,
        take_profit=float(r[6]) if r[6] is not None else None,
        opened_at=opened_at,
        closed_at=closed_at,
        status=str(r[9]),
        realized_pnl=float(r[10]) if r[10] is not None else None,
        regime_at_entry=str(r[11]) if r[11] is not None else None,
        pcs_at_entry=float(r[12]) if r[12] is not None else None,
    )


def _build_public_positions_summary(positions: list[PublicPositionResponse]) -> PublicPositionsSummaryResponse:
    open_count = sum(1 for p in positions if p.status in _OPEN_POSITION_STATUSES)
    closed_positions = [p for p in positions if p.status not in _OPEN_POSITION_STATUSES]

    net_pnl = sum(float(p.realized_pnl or 0.0) for p in closed_positions)
    wins = sum(1 for p in closed_positions if p.realized_pnl is not None and p.realized_pnl > 0)
    closed_count = len(closed_positions)

    return PublicPositionsSummaryResponse(
        total_positions=len(positions),
        open=open_count,
        closed=closed_count,
        net_pnl=float(net_pnl),
        win_rate=float(wins / closed_count) if closed_count else 0.0,
    )


def _fetch_row(db: Database, position_id: str):
    return db.execute(
        """
        SELECT id, platform, asset, direction, entry_price, size_notional, leverage, margin_type,
               stop_loss, take_profit, opened_at, closed_at, status, realized_pnl, conviction_id,
               regime_at_entry, pcs_at_entry, cts_at_entry, horizon_hours
        FROM positions
        WHERE id = ?
        LIMIT 1
        """,
        (position_id,),
    ).fetchone()


@public_router.get("/public", response_model=PublicPositionsResponse)
def list_public_positions(
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
) -> PublicPositionsResponse:
    """Read-only public view of paper-trading positions for external verification."""

    rows = db.execute(
        """
        SELECT id, asset, direction, entry_price, size_notional,
               stop_loss, take_profit, opened_at, closed_at,
               status, realized_pnl, regime_at_entry, pcs_at_entry
        FROM positions
        WHERE platform = 'paper'
        ORDER BY opened_at DESC
        """
    ).fetchall()

    cutoff = datetime.now(tz=UTC) - timedelta(days=7)

    public_positions: list[PublicPositionResponse] = []
    for row in rows:
        position = _row_to_public_position(row)
        if position.status in _OPEN_POSITION_STATUSES:
            public_positions.append(position)
            continue

        closed_at = _to_utc(position.closed_at)
        if closed_at is not None and closed_at >= cutoff:
            public_positions.append(position)

    return PublicPositionsResponse(
        mode="paper",
        start_balance=float(config.execution.paper_start_balance),
        positions=public_positions,
        summary=_build_public_positions_summary(public_positions),
    )


@router.get("", response_model=list[PositionResponse])
def list_positions(
    db: Database = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[PositionResponse]:
    rows = db.execute(
        """
        SELECT id, platform, asset, direction, entry_price, size_notional, leverage, margin_type,
               stop_loss, take_profit, opened_at, closed_at, status, realized_pnl, conviction_id,
               regime_at_entry, pcs_at_entry, cts_at_entry, horizon_hours
        FROM positions
        ORDER BY opened_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [_row_to_position(r) for r in rows]


@router.get("/{position_id}", response_model=PositionResponse)
def get_position(
    position_id: str = Path(..., description="Position id"),
    db: Database = Depends(get_db),
) -> PositionResponse:
    r = _fetch_row(db, position_id)

    if r is None:
        raise B1e55edError(code="not_found", message="Position not found", status=404)

    return _row_to_position(r)


# ---- Mutation body schemas ------------------------------------------------


class ClosePositionBody(BaseModel):
    exit_price: float | None = None
    reason: str = "dashboard"


class AdjustStopBody(BaseModel):
    stop_loss: float


class AdjustTargetBody(BaseModel):
    take_profit: float


# ---- Mutation endpoints ---------------------------------------------------


@router.post("/{position_id}/close", response_model=PositionResponse)
def close_position(
    position_id: str = Path(..., description="Position id"),
    body: ClosePositionBody = ClosePositionBody(),
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
) -> PositionResponse:
    """Close an open position, realising P&L."""
    r = _fetch_row(db, position_id)
    if r is None:
        raise B1e55edError(code="not_found", message="Position not found", status=404)

    status = str(r[12])
    if status != "open":
        raise B1e55edError(
            code="position_not_open",
            message=f"Position is already {status}",
            status=409,
        )

    # Resolve exit price: use provided value or fall back to entry price (flat close).
    exit_price = body.exit_price if body.exit_price is not None else float(r[4])

    from engine.execution.pnl import PnLTracker

    tracker = PnLTracker(db=db, config=config)
    try:
        tracker.close_position(
            position_id=position_id,
            exit_price=exit_price,
            reason=body.reason,
        )
    except ValueError as exc:
        raise B1e55edError(code="close_failed", message=str(exc), status=422) from exc

    updated = _fetch_row(db, position_id)
    if updated is None:  # pragma: no cover
        raise B1e55edError(code="not_found", message="Position not found after close", status=404)
    return _row_to_position(updated)


@router.patch("/{position_id}/stop", response_model=PositionResponse)
def adjust_stop(
    position_id: str = Path(..., description="Position id"),
    body: AdjustStopBody = ...,
    db: Database = Depends(get_db),
) -> PositionResponse:
    """Update stop_loss on an open position."""
    r = _fetch_row(db, position_id)
    if r is None:
        raise B1e55edError(code="not_found", message="Position not found", status=404)

    if str(r[12]) != "open":
        raise B1e55edError(
            code="position_not_open",
            message="Can only adjust stop on open positions",
            status=409,
        )

    db.execute(
        "UPDATE positions SET stop_loss = ? WHERE id = ? AND status = 'open'",
        (body.stop_loss, position_id),
    )
    db.conn.commit()

    updated = _fetch_row(db, position_id)
    if updated is None:  # pragma: no cover
        raise B1e55edError(code="not_found", message="Position not found after update", status=404)
    return _row_to_position(updated)


@router.patch("/{position_id}/target", response_model=PositionResponse)
def adjust_target(
    position_id: str = Path(..., description="Position id"),
    body: AdjustTargetBody = ...,
    db: Database = Depends(get_db),
) -> PositionResponse:
    """Update take_profit on an open position."""
    r = _fetch_row(db, position_id)
    if r is None:
        raise B1e55edError(code="not_found", message="Position not found", status=404)

    if str(r[12]) != "open":
        raise B1e55edError(
            code="position_not_open",
            message="Can only adjust target on open positions",
            status=409,
        )

    db.execute(
        "UPDATE positions SET take_profit = ? WHERE id = ? AND status = 'open'",
        (body.take_profit, position_id),
    )
    db.conn.commit()

    updated = _fetch_row(db, position_id)
    if updated is None:  # pragma: no cover
        raise B1e55edError(code="not_found", message="Position not found after update", status=404)
    return _row_to_position(updated)
