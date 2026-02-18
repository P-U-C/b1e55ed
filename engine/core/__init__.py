"""engine.core

Core primitives.

If a module needs to exist, it should probably depend only on this package.
"""

from .config import Config
from .database import Database
from .events import EventEnvelope, EventType
from .exceptions import B1e55edError
from .models import Event
from .time import parse_dt, staleness_ms, utc_now

__all__ = [
    "B1e55edError",
    "Config",
    "Database",
    "Event",
    "EventEnvelope",
    "EventType",
    "utc_now",
    "parse_dt",
    "staleness_ms",
]
