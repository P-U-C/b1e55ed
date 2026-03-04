"""api.routes.signals_validate

Stateless signal payload validation endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ValidationError

from engine.core.events import EventType, payload_model_for

router = APIRouter(prefix="/signals", tags=["signals"])


class ValidateRequest(BaseModel):
    event_type: str
    payload: dict


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[str]


@router.post("/validate", response_model=ValidateResponse)
def validate_signal(req: ValidateRequest) -> ValidateResponse:
    """Validate a signal payload against registered schemas. No DB writes."""
    try:
        et = EventType(req.event_type)
    except ValueError:
        return ValidateResponse(valid=False, errors=[f"Unknown event type: {req.event_type}"])

    model = payload_model_for(et)
    if model is None:
        return ValidateResponse(valid=False, errors=[f"No schema registered for {req.event_type}"])

    try:
        model.model_validate(req.payload)
    except ValidationError as exc:
        errors: list[str] = []
        for e in exc.errors():
            loc = ".".join(str(x) for x in e["loc"])
            errors.append(f"{loc}: {e['msg']}")
        return ValidateResponse(valid=False, errors=errors)

    return ValidateResponse(valid=True, errors=[])
