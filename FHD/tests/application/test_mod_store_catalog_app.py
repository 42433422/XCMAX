"""mod_store_catalog_app — 门面 re-export 与可见性委托。"""

from __future__ import annotations

from app.application import mod_store_catalog_app as catalog_app


def test_catalog_app_reexports() -> None:
    assert callable(catalog_app.catalog_base_url)
    assert callable(catalog_app.fetch_market_catalog_page)
    assert callable(catalog_app.is_public_catalog_row)


def test_is_public_catalog_row_public() -> None:
    row = {
        "id": "demo-mod",
        "version": "1.0.0",
        "stored_filename": "demo-mod.zip",
        "public_listing": True,
    }
    assert catalog_app.is_public_catalog_row(row) is True
