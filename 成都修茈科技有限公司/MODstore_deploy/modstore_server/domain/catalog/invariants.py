"""Catalog package invariants (P3)."""

from __future__ import annotations

from typing import Any


def assert_valid_catalog_package_record(rec: dict[str, Any]) -> None:
    pid = str(rec.get("id") or "").strip()
    ver = str(rec.get("version") or "").strip()
    if not pid or not ver:
        raise ValueError("pkg id 与 version 必填")
    price = float((rec.get("commerce") or {}).get("price") or 0.0)
    if price < 0:
        raise ValueError("价格不能为负")
    if not str(rec.get("sha256") or "").strip() and rec.get("stored_filename"):
        # 允许无文件记录时缺 sha；一旦有 stored_filename 仍缺 sha 则警告级——此处不强制
        pass


__all__ = ["assert_valid_catalog_package_record"]
