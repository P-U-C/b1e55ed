from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class B1e55edError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, **extra: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


async def b1e55ed_error_handler(request: Request, exc: B1e55edError) -> JSONResponse:
    body = {"error": {"code": exc.code, "message": exc.message, **exc.extra}}
    return JSONResponse(status_code=exc.status, content=body)
