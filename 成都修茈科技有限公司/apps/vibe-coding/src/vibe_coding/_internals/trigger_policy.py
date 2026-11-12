"""``TriggerPolicy`` lifted from eskill.models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class TriggerPolicy:
    on_error: bool = True
    on_quality_below_threshold: bool = True
    force_dynamic: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> TriggerPolicy:
        raw = raw or {}
        return cls(
            on_error=bool(raw.get("on_error", True)),
            on_quality_below_threshold=bool(raw.get("on_quality_below_threshold", True)),
            force_dynamic=bool(raw.get("force_dynamic", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
