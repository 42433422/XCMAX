"""Mod 目录领域模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModCatalogEntry:
    mod_id: str
    display_name: str
