"""Lightweight metrics: counters / gauges / histograms.

Designed to power the agent dashboard ("how many skills generated this
hour?", "median sandbox duration?") without dragging Prometheus client
libraries in. The :class:`MetricsRegistry` exposes both an in-memory
read API and a Prometheus-style text dump for the ``/metrics`` endpoint.
"""

from __future__ import annotations

import bisect
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

# Default histogram buckets in milliseconds. Roughly geometric: covers
# fast LLM calls (50ms) up to long heal loops (60s).
DEFAULT_BUCKETS_MS: tuple[float, ...] = (
    5, 10, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 30_000, 60_000,
)


def _label_key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


@dataclass
class Counter:
    """Strictly monotonic counter with optional labels."""

    name: str
    description: str = ""
    _values: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def inc(self, value: float = 1.0, *, labels: dict[str, str] | None = None) -> float:
        if value < 0:
            raise ValueError("counter increments must be non-negative")
        with self._lock:
            key = _label_key(labels)
            self._values[key] = self._values.get(key, 0.0) + float(value)
            return self._values[key]

    def value(self, *, labels: dict[str, str] | None = None) -> float:
        with self._lock:
            return float(self._values.get(_label_key(labels), 0.0))

    def snapshot(self) -> dict[tuple[tuple[str, str], ...], float]:
        with self._lock:
            return dict(self._values)


@dataclass
class Gauge:
    """Arbitrary float that can go up or down."""

    name: str
    description: str = ""
    _values: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set(self, value: float, *, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._values[_label_key(labels)] = float(value)

    def inc(self, value: float = 1.0, *, labels: dict[str, str] | None = None) -> float:
        with self._lock:
            key = _label_key(labels)
            self._values[key] = self._values.get(key, 0.0) + float(value)
            return self._values[key]

    def value(self, *, labels: dict[str, str] | None = None) -> float:
        with self._lock:
            return float(self._values.get(_label_key(labels), 0.0))

    def snapshot(self) -> dict[tuple[tuple[str, str], ...], float]:
        with self._lock:
            return dict(self._values)


@dataclass
class Histogram:
    """Bucketed distribution + count + sum."""

    name: str
    description: str = ""
    buckets: tuple[float, ...] = DEFAULT_BUCKETS_MS
    _data: dict[
        tuple[tuple[str, str], ...],
        dict[str, Any],
    ] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, value: float, *, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            key = _label_key(labels)
            entry = self._data.setdefault(
                key,
                {
                    "count": 0,
                    "sum": 0.0,
                    "buckets": [0] * len(self.buckets),
                    "samples": [],
                },
            )
            entry["count"] += 1
            entry["sum"] += float(value)
            samples: list[float] = entry["samples"]
            bisect.insort(samples, float(value))
            # Keep at most 4096 samples to bound memory. Drop the median
            # element when over the cap so the distribution stays roughly
            # representative.
            if len(samples) > 4096:
                del samples[len(samples) // 2]
            buckets: list[int] = entry["buckets"]
            for i, threshold in enumerate(self.buckets):
                if value <= threshold:
                    buckets[i] += 1
                    break

    def percentile(self, p: float, *, labels: dict[str, str] | None = None) -> float:
        if not (0.0 <= p <= 1.0):
            raise ValueError("p must be in [0, 1]")
        with self._lock:
            entry = self._data.get(_label_key(labels))
            if entry is None or not entry["samples"]:
                return 0.0
            samples = list(entry["samples"])
        idx = max(0, min(len(samples) - 1, int(round(p * (len(samples) - 1)))))
        return float(samples[idx])

    def count(self, *, labels: dict[str, str] | None = None) -> int:
        with self._lock:
            entry = self._data.get(_label_key(labels))
            return int(entry["count"]) if entry else 0

    def snapshot(self) -> dict[tuple[tuple[str, str], ...], dict[str, Any]]:
        with self._lock:
            out: dict[tuple[tuple[str, str], ...], dict[str, Any]] = {}
            for key, entry in self._data.items():
                out[key] = {
                    "count": int(entry["count"]),
                    "sum": float(entry["sum"]),
                    "buckets": list(entry["buckets"]),
                }
            return out


class MetricsRegistry:
    """Container for counters / gauges / histograms; thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.counters: dict[str, Counter] = {}
        self.gauges: dict[str, Gauge] = {}
        self.histograms: dict[str, Histogram] = {}

    def counter(self, name: str, *, description: str = "") -> Counter:
        with self._lock:
            existing = self.counters.get(name)
            if existing is not None:
                return existing
            counter = Counter(name=name, description=description)
            self.counters[name] = counter
            return counter

    def gauge(self, name: str, *, description: str = "") -> Gauge:
        with self._lock:
            existing = self.gauges.get(name)
            if existing is not None:
                return existing
            gauge = Gauge(name=name, description=description)
            self.gauges[name] = gauge
            return gauge

    def histogram(
        self,
        name: str,
        *,
        description: str = "",
        buckets: tuple[float, ...] | None = None,
    ) -> Histogram:
        with self._lock:
            existing = self.histograms.get(name)
            if existing is not None:
                return existing
            histogram = Histogram(
                name=name,
                description=description,
                buckets=tuple(buckets or DEFAULT_BUCKETS_MS),
            )
            self.histograms[name] = histogram
            return histogram

    def observe_duration_ms(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        self.histogram(name, description="duration in ms").observe(value, labels=labels)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": {
                    name: {
                        "description": c.description,
                        "values": [
                            {"labels": dict(k), "value": v} for k, v in c.snapshot().items()
                        ],
                    }
                    for name, c in self.counters.items()
                },
                "gauges": {
                    name: {
                        "description": g.description,
                        "values": [
                            {"labels": dict(k), "value": v} for k, v in g.snapshot().items()
                        ],
                    }
                    for name, g in self.gauges.items()
                },
                "histograms": {
                    name: {
                        "description": h.description,
                        "buckets": list(h.buckets),
                        "values": [
                            {"labels": dict(k), **v}
                            for k, v in h.snapshot().items()
                        ],
                    }
                    for name, h in self.histograms.items()
                },
            }

    def to_prometheus(self) -> str:
        """Render Prometheus text exposition format (v0.0.4)."""
        lines: list[str] = []
        with self._lock:
            for name, counter in self.counters.items():
                lines.append(f"# HELP {name} {counter.description}")
                lines.append(f"# TYPE {name} counter")
                for key, value in counter.snapshot().items():
                    label = _format_labels(key)
                    lines.append(f"{name}{label} {value}")
            for name, gauge in self.gauges.items():
                lines.append(f"# HELP {name} {gauge.description}")
                lines.append(f"# TYPE {name} gauge")
                for key, value in gauge.snapshot().items():
                    label = _format_labels(key)
                    lines.append(f"{name}{label} {value}")
            for name, hist in self.histograms.items():
                lines.append(f"# HELP {name} {hist.description}")
                lines.append(f"# TYPE {name} histogram")
                for key, entry in hist.snapshot().items():
                    base_labels = dict(key)
                    cumulative = 0
                    for i, threshold in enumerate(hist.buckets):
                        cumulative += entry["buckets"][i]
                        bucket_label = _format_labels(
                            tuple(sorted({**base_labels, "le": str(threshold)}.items()))
                        )
                        lines.append(f"{name}_bucket{bucket_label} {cumulative}")
                    inf_label = _format_labels(
                        tuple(sorted({**base_labels, "le": "+Inf"}.items()))
                    )
                    lines.append(f"{name}_bucket{inf_label} {entry['count']}")
                    lines.append(f"{name}_sum{_format_labels(key)} {entry['sum']}")
                    lines.append(f"{name}_count{_format_labels(key)} {entry['count']}")
        return "\n".join(lines) + "\n"


def _format_labels(key: tuple[tuple[str, str], ...]) -> str:
    if not key:
        return ""
    parts = [f'{k}="{_escape(v)}"' for k, v in key]
    return "{" + ",".join(parts) + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\"", "\\\"")


# ----------------------------------------------------- timing helper


class TimerContext:
    """Context manager that observes the elapsed ms into a histogram."""

    def __init__(self, histogram: Histogram, labels: dict[str, str] | None = None) -> None:
        self.histogram = histogram
        self.labels = labels
        self._t0 = 0.0

    def __enter__(self) -> "TimerContext":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        elapsed = (time.perf_counter() - self._t0) * 1000
        self.histogram.observe(elapsed, labels=self.labels)


# ----------------------------------------------------- singleton


_DEFAULT: MetricsRegistry | None = None
_DEFAULT_LOCK = threading.Lock()


def get_default_registry() -> MetricsRegistry:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = MetricsRegistry()
        return _DEFAULT


__all__ = [
    "Counter",
    "DEFAULT_BUCKETS_MS",
    "Gauge",
    "Histogram",
    "MetricsRegistry",
    "TimerContext",
    "get_default_registry",
]
