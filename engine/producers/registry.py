"""engine.producers.registry

All producers report for duty.

Registry responsibilities:
- @register("name", domain="...") decorator
- lookup/list helpers
- module auto-discovery (import engine.producers.* to trigger decorators)

Discovery is intentionally simple. The contract lives in events; this is just plumbing.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any

from engine.producers.base import Producer


_REGISTRY: dict[str, type[Producer]] = {}
_DISCOVERED = False


def register(name: str, *, domain: str) -> Callable[[type[Any]], type[Any]]:
    def _decorator(cls: type[Any]) -> type[Any]:
        if name in _REGISTRY and _REGISTRY[name] is not cls:
            raise ValueError(f"producer already registered: {name}")

        setattr(cls, "name", name)
        setattr(cls, "domain", domain)
        _REGISTRY[name] = cls  # type: ignore[assignment]
        return cls

    return _decorator


def discover() -> None:
    global _DISCOVERED
    if _DISCOVERED:
        return

    pkg_name = "engine.producers"
    pkg = importlib.import_module(pkg_name)

    for m in pkgutil.iter_modules(pkg.__path__, prefix=f"{pkg_name}."):
        modname = m.name
        if modname.endswith(".base") or modname.endswith(".registry"):
            continue
        importlib.import_module(modname)

    _DISCOVERED = True


def _maybe_discover() -> None:
    """Lazy discovery.

    If something has already registered producers (e.g. tests), don't
    auto-import the entire producer package as a side effect of listing.
    Runtime should call discover() explicitly during startup.
    """

    if _DISCOVERED:
        return
    if _REGISTRY:
        return
    discover()


def get_producer(name: str) -> type[Producer]:
    # If already registered, don't trigger discovery side effects.
    if name in _REGISTRY:
        return _REGISTRY[name]

    _maybe_discover()
    if name not in _REGISTRY:
        raise KeyError(f"unknown producer: {name}")
    return _REGISTRY[name]


def list_producers() -> list[str]:
    _maybe_discover()
    return sorted(_REGISTRY.keys())


def list_by_domain(domain: str) -> list[str]:
    _maybe_discover()
    return sorted([n for n, cls in _REGISTRY.items() if getattr(cls, "domain", None) == domain])


def _reset_for_tests() -> None:
    """Clear registry and unload producer modules so decorators can re-run."""

    import sys

    global _DISCOVERED
    _REGISTRY.clear()
    _DISCOVERED = False

    for key in list(sys.modules.keys()):
        if not key.startswith("engine.producers."):
            continue
        if key.endswith(".registry") or key.endswith(".base"):
            continue
        sys.modules.pop(key, None)
