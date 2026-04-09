from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PositionResponse(BaseModel):
    id: str
    platform: str
    asset: str
    direction: str
    entry_price: float
    size_notional: float
    leverage: float | None = None
    margin_type: str | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    status: str
    realized_pnl: float | None = None
    conviction_id: int | None = None
    regime_at_entry: str | None = None
    pcs_at_entry: float | None = None
    cts_at_entry: float | None = None
    horizon_hours: float | None = None


class PublicPositionResponse(BaseModel):
    """Redacted, read-only view used by the public judges endpoint."""

    id: str
    asset: str
    direction: str
    entry_price: float
    size_notional: float
    stop_loss: float | None = None
    take_profit: float | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    status: str
    realized_pnl: float | None = None
    regime_at_entry: str | None = None
    pcs_at_entry: float | None = None


class PublicPositionsSummaryResponse(BaseModel):
    total_positions: int
    open: int
    closed: int
    net_pnl: float
    win_rate: float


class PublicPositionsResponse(BaseModel):
    mode: str
    start_balance: float
    positions: list[PublicPositionResponse]
    summary: PublicPositionsSummaryResponse
