# -*- coding: utf-8 -*-
"""员工感知规格值对象。

把 ``employee_config_v2.perception`` 翻译为「主类型 + 启用模态集合」。
运行时 PerceptionPipeline 据此决定对输入做 document/vision/audio/text 处理。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PERCEPTION_TEXT = "text"
PERCEPTION_DOCUMENT = "document"
PERCEPTION_IMAGE = "image"
PERCEPTION_AUDIO = "audio"

_VALID_TYPES = frozenset({PERCEPTION_TEXT, PERCEPTION_DOCUMENT, PERCEPTION_IMAGE, PERCEPTION_AUDIO})


def _truthy_enabled(obj: Any) -> bool:
    return isinstance(obj, dict) and bool(obj.get("enabled"))


@dataclass(frozen=True)
class PerceptionSpec:
    type: str = PERCEPTION_TEXT
    modalities: tuple[str, ...] = field(default_factory=lambda: (PERCEPTION_TEXT,))

    def has(self, modality: str) -> bool:
        return modality in self.modalities

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> PerceptionSpec:
        perc = {}
        if isinstance(config, dict) and isinstance(config.get("perception"), dict):
            perc = config["perception"]
        modalities: list[str] = []
        if _truthy_enabled(perc.get("document")):
            modalities.append(PERCEPTION_DOCUMENT)
        if _truthy_enabled(perc.get("vision")):
            modalities.append(PERCEPTION_IMAGE)
        if _truthy_enabled(perc.get("audio")):
            modalities.append(PERCEPTION_AUDIO)

        explicit = str(perc.get("type") or "").strip().lower()
        if explicit in _VALID_TYPES:
            primary = explicit
            if explicit not in modalities:
                modalities.insert(0, explicit)
        elif modalities:
            primary = modalities[0]
        else:
            primary = PERCEPTION_TEXT

        if PERCEPTION_TEXT not in modalities:
            modalities.append(PERCEPTION_TEXT)
        return cls(type=primary, modalities=tuple(dict.fromkeys(modalities)))


__all__ = [
    "PERCEPTION_AUDIO",
    "PERCEPTION_DOCUMENT",
    "PERCEPTION_IMAGE",
    "PERCEPTION_TEXT",
    "PerceptionSpec",
]
