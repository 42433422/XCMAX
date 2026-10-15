from __future__ import annotations

"""Branch coverage for app/legacy/documents/legacy_shipment_document.py."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.legacy.documents.legacy_shipment_document import (
    LegacyGeneratorLoadResult,
    load_legacy_shipment_document_generator,
)


class TestLegacyGeneratorLoadResult:
    def test_dataclass_frozen(self):
        r = LegacyGeneratorLoadResult(
            ShipmentDocumentGenerator=object,
            PurchaseUnitInfo=object,
            legacy_dir="/tmp/legacy",
        )
        assert r.legacy_dir == "/tmp/legacy"
        # frozen → mutations raise
        with pytest.raises((AttributeError, TypeError)):
            r.legacy_dir = "/other"  # type: ignore[misc]


class TestLoadLegacyShipmentDocumentGenerator:
    def test_raises_import_error_when_no_dir(self, tmp_path):
        """No AI助手 directory anywhere → ImportError raised."""
        with (
            patch(
                "app.utils.path_io.path_utils.get_resource_path",
                return_value=str(tmp_path / "nonexistent"),
            ),
            patch("os.path.isdir", return_value=False),
            patch("os.path.exists", return_value=False),
        ):
            with pytest.raises(ImportError, match="shipment_document.py"):
                load_legacy_shipment_document_generator(caller_file=__file__)

    def test_raises_when_get_resource_path_fails(self, tmp_path):
        """get_resource_path raises → fallback dirs used, still no dir → ImportError."""
        with (
            patch(
                "app.utils.path_io.path_utils.get_resource_path",
                side_effect=RuntimeError("no resource"),
            ),
            patch("os.path.isdir", return_value=False),
            patch("os.path.exists", return_value=False),
        ):
            with pytest.raises(ImportError):
                load_legacy_shipment_document_generator(caller_file=__file__)

    def test_success_via_sys_path(self, tmp_path):
        """Happy path: directory found + import via sys.path succeeds."""
        legacy_dir = tmp_path / "AI助手"
        legacy_dir.mkdir()
        doc_py = legacy_dir / "shipment_document.py"
        doc_py.write_text("class ShipmentDocumentGenerator: pass\nclass PurchaseUnitInfo: pass\n")

        with (
            patch("app.utils.path_io.path_utils.get_resource_path", return_value=str(legacy_dir)),
            patch("os.path.isdir", side_effect=lambda p: str(p) == str(legacy_dir)),
            patch(
                "os.path.exists",
                side_effect=lambda p: str(p) == str(doc_py) or os.path.exists(p),
            ),
        ):
            result = load_legacy_shipment_document_generator(caller_file=__file__)

        assert result.legacy_dir == str(legacy_dir)
        assert result.ShipmentDocumentGenerator is not None
        assert result.PurchaseUnitInfo is not None

    @pytest.mark.parametrize(
        "cached", [None, SimpleNamespace(__file__="/wrong/shipment_document.py")]
    )
    def test_success_via_importlib_fallback(self, tmp_path, monkeypatch, cached):
        doc_py = tmp_path / "shipment_document.py"
        doc_py.write_text("class ShipmentDocumentGenerator: pass\nclass PurchaseUnitInfo: pass\n")
        monkeypatch.setattr(sys, "path", list(sys.path))
        monkeypatch.setitem(sys.modules, "shipment_document", cached)
        monkeypatch.setattr(
            "app.utils.path_io.path_utils.get_resource_path", lambda *args: str(tmp_path)
        )
        result = load_legacy_shipment_document_generator(caller_file=__file__)
        assert result.legacy_dir == str(tmp_path)
        assert result.ShipmentDocumentGenerator.__name__ == "ShipmentDocumentGenerator"
        assert result.PurchaseUnitInfo.__name__ == "PurchaseUnitInfo"

    def test_importlib_file_not_found(self, tmp_path):
        """importlib path raises ImportError when spec file doesn't exist."""
        legacy_dir = tmp_path / "AI助手"
        legacy_dir.mkdir()

        import builtins

        original_import = builtins.__import__

        def fail_import(name, *args, **kwargs):
            if name == "shipment_document":
                raise ImportError("not available")
            return original_import(name, *args, **kwargs)

        with (
            patch("app.utils.path_io.path_utils.get_resource_path", return_value=str(legacy_dir)),
            patch("os.path.isdir", side_effect=lambda p: str(p) == str(legacy_dir)),
            patch("os.path.exists", side_effect=lambda p: str(p).endswith("AI助手")),
            patch("builtins.__import__", side_effect=fail_import),
        ):
            with pytest.raises(ImportError):
                load_legacy_shipment_document_generator(caller_file=__file__)
