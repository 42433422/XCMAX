"""Catalog domain types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModShellUiRow:
    """Aggregated shell UI row for one installed Mod (value object)."""

    id: str
    name: str
    primary: bool
    frontend: dict[str, Any]
    industry: dict[str, Any]
    industry_card: dict[str, Any]
    ui_shell: dict[str, Any]
    sidebar_menu: list[Any]
    menu_overrides: list[Any]
    industry_options: list[str]
    config_paths: dict[str, Any]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "primary": self.primary,
            "frontend": self.frontend,
            "industry": self.industry,
            "industry_card": self.industry_card,
            "ui_shell": self.ui_shell,
            "sidebar_menu": self.sidebar_menu,
            "menu_overrides": self.menu_overrides,
            "industry_options": self.industry_options,
            "config_paths": self.config_paths,
        }


@dataclass(frozen=True)
class CatalogItem:
    """Aggregate root for a published catalog package."""

    pkg_id: str
    author_id: int
    version: str
    artifact: str
    name: str
    description: str = ""
    industry: str = "通用"
    sha256: str = ""
    stored_filename: str = ""
