from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    detail: str


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)
