"""engine.core._compat

Python version compatibility shims. Import from here instead of
duplicating backports across modules.
"""

from __future__ import annotations

try:
    from enum import StrEnum  # py311+
except ImportError:  # pragma: no cover
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]  # noqa: UP042
        """Backport of Python 3.11's enum.StrEnum for Python 3.10."""

        def __str__(self) -> str:  # pragma: no cover
            return str(self.value)

        def __format__(self, spec: str) -> str:  # pragma: no cover
            return format(str(self), spec)


__all__ = ["StrEnum"]
