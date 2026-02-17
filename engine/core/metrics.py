"""engine.core.metrics

A tiny metrics surface.

No Prometheus dependency here. Just a stable interface that can be wired later.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass
class Counter:
    name: str
    _value: float = 0.0
    _lock: Lock = Lock()

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        with self._lock:
            return float(self._value)


@dataclass
class Gauge:
    name: str
    _value: float = 0.0
    _lock: Lock = Lock()

    def set(self, value: float) -> None:
        with self._lock:
            self._value = float(value)

    @property
    def value(self) -> float:
        with self._lock:
            return float(self._value)


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}

    def counter(self, name: str) -> Counter:
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name=name)
            return self._counters[name]

    def gauge(self, name: str) -> Gauge:
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name=name)
            return self._gauges[name]

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            data: dict[str, float] = {}
            data.update({f"counter.{k}": v.value for k, v in self._counters.items()})
            data.update({f"gauge.{k}": v.value for k, v in self._gauges.items()})
            return data


REGISTRY = MetricsRegistry()
