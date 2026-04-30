from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ModItem:
    id: str
    name: str
    version: str = "1.0.0"
    author: str = "unknown"
    description: str = ""
    type: str = "mod"

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "type": self.type,
        }


def list_mod_items() -> list[ModItem]:
    return []
