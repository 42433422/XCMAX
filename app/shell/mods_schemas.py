from __future__ import annotations

from typing import TypedDict


class ModManifest(TypedDict, total=False):
    id: str
    name: str
    version: str
    author: str
    description: str
