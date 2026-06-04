"""Mod 商店 Catalog 应用层门面。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.infrastructure.gateways.catalog import (
    catalog_base_url,
    catalog_download_to,
    catalog_get_json,
    iter_catalog_packages,
)
from app.infrastructure.gateways.catalog import normalize_package_zip_path, sync_modstore_library_to_local

__all__ = [
    "catalog_base_url",
    "catalog_download_to",
    "catalog_get_json",
    "iter_catalog_packages",
    "normalize_package_zip_path",
    "sync_modstore_library_to_local",
]
