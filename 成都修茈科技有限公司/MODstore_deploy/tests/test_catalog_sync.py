from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modstore_server.catalog_sync import (
    _commerce_price,
    market_catalog_files_dir,
    upsert_catalog_item_from_xc_package_dict,
)


class TestCommercePrice:
    def test_free_mode(self):
        assert _commerce_price({"mode": "free"}) == 0.0

    def test_paid_mode(self):
        assert _commerce_price({"mode": "paid", "price": 9.99}) == 9.99

    def test_paid_mode_with_amount(self):
        assert _commerce_price({"mode": "paid", "amount": 19.99}) == 19.99

    def test_none_input(self):
        assert _commerce_price(None) == 0.0

    def test_non_dict_input(self):
        assert _commerce_price("not a dict") == 0.0

    def test_empty_dict(self):
        assert _commerce_price({}) == 0.0

    def test_invalid_price(self):
        assert _commerce_price({"mode": "paid", "price": "abc"}) == 0.0

    def test_zero_price(self):
        assert _commerce_price({"mode": "paid", "price": 0}) == 0.0


class TestUpsertCatalogItem:
    def test_skip_when_no_pkg_id(self):
        session = MagicMock()
        upsert_catalog_item_from_xc_package_dict(session, {"version": "1.0"})
        session.add.assert_not_called()

    def test_skip_when_no_version(self):
        session = MagicMock()
        upsert_catalog_item_from_xc_package_dict(session, {"id": "pkg1"})
        session.add.assert_not_called()

    def test_create_new_item(self):
        session = MagicMock()
        session.query().filter().first.return_value = None

        record = {
            "id": "test-pkg",
            "version": "1.0.0",
            "name": "Test Package",
            "description": "A test package",
            "artifact": "mod",
            "industry": "测试",
            "commerce": {"mode": "free"},
            "stored_filename": "test.zip",
            "sha256": "abc123",
        }
        upsert_catalog_item_from_xc_package_dict(session, record)
        session.add.assert_called_once()

    def test_update_existing_item(self):
        existing = MagicMock()
        session = MagicMock()
        session.query().filter().first.return_value = existing

        record = {
            "id": "existing-pkg",
            "version": "2.0.0",
            "name": "Updated Package",
            "description": "Updated description",
            "commerce": {"mode": "paid", "price": 5.0},
        }
        upsert_catalog_item_from_xc_package_dict(session, record)
        assert existing.version == "2.0.0"
        assert existing.name == "Updated Package"

    def test_name_defaults_to_pkg_id(self):
        session = MagicMock()
        session.query().filter().first.return_value = None

        record = {"id": "my-pkg", "version": "1.0"}
        upsert_catalog_item_from_xc_package_dict(session, record)
        added = session.add.call_args[0][0]
        assert added.name == "my-pkg"

    def test_with_author_id(self):
        session = MagicMock()
        session.query().filter().first.return_value = None

        record = {"id": "authored-pkg", "version": "1.0"}
        upsert_catalog_item_from_xc_package_dict(session, record, author_id=42)
        added = session.add.call_args[0][0]
        assert added.author_id == 42


class TestMarketCatalogFilesDir:
    def test_returns_path(self):
        result = market_catalog_files_dir()
        assert isinstance(result, Path)
