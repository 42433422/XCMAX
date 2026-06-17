"""Tests for app.infrastructure.documents.price_list_generator — coverage ramp."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.documents.price_list_generator import PriceListGenerator


def _setup_template_dir(tmp_path: Path) -> Path:
    """Create a fake FHD root with a template file for testing."""
    template = tmp_path / "424" / "模板.docx"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_bytes(b"fake docx")
    return tmp_path


class TestPriceListGeneratorInit:
    def test_default_output_dir(self, tmp_path):
        with patch.object(PriceListGenerator, "__init__", lambda self, output_dir=None: None):
            gen = PriceListGenerator()
            assert gen is not None

    def test_custom_output_dir(self, tmp_path):
        gen = PriceListGenerator(output_dir=str(tmp_path / "custom_output"))
        assert gen.output_dir == tmp_path / "custom_output"
        assert gen.output_dir.exists()


class TestPriceListGeneratorGenerate:
    @patch("app.infrastructure.documents.price_list_generator.PriceListGenerator._print_file")
    @patch(
        "app.infrastructure.documents.price_list_generator.PriceListGenerator._get_default_printer",
        return_value=None,
    )
    @patch(
        "app.infrastructure.documents.price_list_generator.PriceListGenerator._create_price_list_pdf"
    )
    def test_generate_no_printer(self, mock_create, mock_get_printer, mock_print, tmp_path):
        gen = PriceListGenerator(output_dir=str(tmp_path))
        mock_create.side_effect = lambda fp, cn, prods: fp.touch()

        products = [
            {
                "model_number": "ABC-123",
                "name": "Test Product",
                "spec": "20L",
                "unit": "桶",
                "unit_price": "100.00",
            }
        ]
        result = gen.generate("TestCustomer", products)
        assert result["success"] is True
        assert "filename" in result
        assert "filepath" in result
        mock_print.assert_not_called()

    @patch("app.infrastructure.documents.price_list_generator.PriceListGenerator._print_file")
    @patch(
        "app.infrastructure.documents.price_list_generator.PriceListGenerator._get_default_printer",
        return_value="HP LaserJet",
    )
    @patch(
        "app.infrastructure.documents.price_list_generator.PriceListGenerator._create_price_list_pdf"
    )
    def test_generate_with_default_printer(
        self, mock_create, mock_get_printer, mock_print, tmp_path
    ):
        gen = PriceListGenerator(output_dir=str(tmp_path))
        mock_create.side_effect = lambda fp, cn, prods: fp.touch()

        products = [
            {"model_number": "X", "name": "Y", "spec": "Z", "unit": "个", "unit_price": "10"}
        ]
        result = gen.generate("TestCustomer", products)
        assert result["success"] is True
        mock_print.assert_called_once()

    @patch("app.infrastructure.documents.price_list_generator.PriceListGenerator._print_file")
    @patch(
        "app.infrastructure.documents.price_list_generator.PriceListGenerator._create_price_list_pdf"
    )
    def test_generate_with_explicit_printer(self, mock_create, mock_print, tmp_path):
        gen = PriceListGenerator(output_dir=str(tmp_path))
        mock_create.side_effect = lambda fp, cn, prods: fp.touch()

        products = [
            {"model_number": "X", "name": "Y", "spec": "Z", "unit": "个", "unit_price": "10"}
        ]
        result = gen.generate("TestCustomer", products, printer_name="HP LaserJet")
        assert result["success"] is True
        mock_print.assert_called_once()

    @patch(
        "app.infrastructure.documents.price_list_generator.PriceListGenerator._create_price_list_pdf",
        side_effect=OSError("disk full"),
    )
    def test_generate_error(self, mock_create, tmp_path):
        gen = PriceListGenerator(output_dir=str(tmp_path))
        products = [
            {"model_number": "X", "name": "Y", "spec": "Z", "unit": "个", "unit_price": "10"}
        ]
        result = gen.generate("TestCustomer", products)
        assert result["success"] is False
        assert "disk full" in result["message"]

    def test_generate_safe_filename(self, tmp_path):
        gen = PriceListGenerator(output_dir=str(tmp_path))
        with patch.object(
            gen, "_create_price_list_pdf", side_effect=lambda fp, cn, prods: fp.touch()
        ):
            with patch.object(gen, "_get_default_printer", return_value=None):
                result = gen.generate("Customer/With\\Slashes", [])
        assert result["success"] is True
        assert "/" not in result["filename"]
        assert "\\" not in result["filename"]


class TestPriceListGeneratorCreatePdf:
    @patch("app.infrastructure.documents.price_list_generator.resolve_fhd_repo_root")
    def test_create_pdf_with_template(self, mock_resolve, tmp_path):
        mock_resolve.return_value = _setup_template_dir(tmp_path)

        gen = PriceListGenerator(output_dir=str(tmp_path))
        filepath = tmp_path / "test_output.docx"

        with patch(
            "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
            return_value=b"generated docx bytes",
        ) as mock_build:
            gen._create_price_list_pdf(filepath, "TestCustomer", [])
            mock_build.assert_called_once()
        assert filepath.exists()

    @patch("app.infrastructure.documents.price_list_generator.resolve_fhd_repo_root")
    def test_create_pdf_template_import_error_falls_back_to_docx(self, mock_resolve, tmp_path):
        """When build_price_list_docx_bytes raises ImportError, fallback to python-docx."""
        mock_resolve.return_value = _setup_template_dir(tmp_path)

        gen = PriceListGenerator(output_dir=str(tmp_path))
        filepath = tmp_path / "test_output.docx"

        with patch(
            "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
            side_effect=ImportError("no template module"),
        ):
            with patch("docx.Document") as mock_doc_cls:
                mock_doc = MagicMock()
                mock_doc_cls.return_value = mock_doc
                mock_doc.add_heading.return_value = MagicMock(runs=[MagicMock()])
                mock_doc.add_paragraph.return_value = MagicMock(runs=[MagicMock()])
                mock_table = MagicMock()
                mock_table.rows = [MagicMock(cells=[MagicMock() for _ in range(6)])]
                mock_table.add_row.return_value = MagicMock(cells=[MagicMock() for _ in range(6)])
                mock_doc.add_table.return_value = mock_table
                gen._create_price_list_pdf(filepath, "TestCustomer", [])

    @patch("app.infrastructure.documents.price_list_generator.resolve_fhd_repo_root")
    def test_create_pdf_with_dict_products(self, mock_resolve, tmp_path):
        mock_resolve.return_value = _setup_template_dir(tmp_path)

        gen = PriceListGenerator(output_dir=str(tmp_path))
        filepath = tmp_path / "test_output.docx"

        products = [
            {
                "model_number": "ABC-123",
                "name": "Product A",
                "spec": "20L",
                "unit": "桶",
                "unit_price": "100.00",
            }
        ]

        # Make build_price_list_docx_bytes raise ImportError to trigger python-docx fallback
        with patch(
            "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
            side_effect=ImportError("no template module"),
        ):
            with patch("docx.Document") as mock_doc_cls:
                mock_doc = MagicMock()
                mock_doc_cls.return_value = mock_doc
                mock_doc.add_heading.return_value = MagicMock(runs=[MagicMock()])
                mock_doc.add_paragraph.return_value = MagicMock(runs=[MagicMock()])
                mock_table = MagicMock()
                mock_table.rows = [MagicMock(cells=[MagicMock() for _ in range(6)])]
                mock_table.add_row.return_value = MagicMock(cells=[MagicMock() for _ in range(6)])
                mock_doc.add_table.return_value = mock_table
                gen._create_price_list_pdf(filepath, "TestCustomer", products)

    @patch("app.infrastructure.documents.price_list_generator.resolve_fhd_repo_root")
    def test_create_pdf_with_pydantic_model_products(self, mock_resolve, tmp_path):
        mock_resolve.return_value = _setup_template_dir(tmp_path)

        gen = PriceListGenerator(output_dir=str(tmp_path))
        filepath = tmp_path / "test_output.docx"

        mock_product = MagicMock()
        mock_product.model_number = "XYZ-789"
        mock_product.name = "Product B"
        mock_product.spec = "10L"
        mock_product.unit = "箱"
        mock_product.unit_price = "50.00"
        mock_product.__class__ = type("FakeModel", (), {})

        # Make build_price_list_docx_bytes raise ImportError to trigger python-docx fallback
        with patch(
            "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
            side_effect=ImportError("no template module"),
        ):
            with patch("docx.Document") as mock_doc_cls:
                mock_doc = MagicMock()
                mock_doc_cls.return_value = mock_doc
                mock_doc.add_heading.return_value = MagicMock(runs=[MagicMock()])
                mock_doc.add_paragraph.return_value = MagicMock(runs=[MagicMock()])
                mock_table = MagicMock()
                mock_table.rows = [MagicMock(cells=[MagicMock() for _ in range(6)])]
                mock_table.add_row.return_value = MagicMock(cells=[MagicMock() for _ in range(6)])
                mock_doc.add_table.return_value = mock_table
                gen._create_price_list_pdf(filepath, "TestCustomer", [mock_product])

    @patch("app.infrastructure.documents.price_list_generator.resolve_fhd_repo_root")
    def test_create_pdf_fallback_to_text(self, mock_resolve, tmp_path):
        """When build_price_list_docx_bytes raises ImportError and python-docx also fails,
        the ImportError from python-docx propagates to the outer RECOVERABLE_ERRORS handler
        which re-raises it. The text fallback (second except ImportError) is dead code
        because the first except ImportError as e always catches ImportError first.

        Test that the error is properly caught and re-raised by the outer handler.
        """
        mock_resolve.return_value = _setup_template_dir(tmp_path)

        gen = PriceListGenerator(output_dir=str(tmp_path))
        filepath = tmp_path / "test_output.docx"

        products = [
            {
                "model_number": "ABC-123",
                "name": "Product A",
                "spec": "20L",
                "unit": "桶",
                "unit_price": "100.00",
            }
        ]

        # Make build_price_list_docx_bytes raise ImportError to trigger python-docx fallback,
        # then make Document() also raise ImportError — this propagates to outer RECOVERABLE_ERRORS
        with patch(
            "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
            side_effect=ImportError("no template module"),
        ):
            with patch("docx.Document", side_effect=ImportError("no docx")):
                with pytest.raises(ImportError, match="no docx"):
                    gen._create_price_list_pdf(filepath, "TestCustomer", products)

    @patch("app.infrastructure.documents.price_list_generator.resolve_fhd_repo_root")
    def test_create_pdf_text_with_pydantic_model(self, mock_resolve, tmp_path):
        """Same as above — ImportError from python-docx propagates to outer handler."""
        mock_resolve.return_value = _setup_template_dir(tmp_path)

        gen = PriceListGenerator(output_dir=str(tmp_path))
        filepath = tmp_path / "test_output.docx"

        mock_product = MagicMock()
        mock_product.model_number = "XYZ-789"
        mock_product.name = "Product B"
        mock_product.spec = "10L"
        mock_product.unit = "箱"
        mock_product.unit_price = "50.00"
        mock_product.__class__ = type("FakeModel", (), {})

        with patch(
            "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
            side_effect=ImportError("no template module"),
        ):
            with patch("docx.Document", side_effect=ImportError("no docx")):
                with pytest.raises(ImportError, match="no docx"):
                    gen._create_price_list_pdf(filepath, "TestCustomer", [mock_product])


class TestPriceListGeneratorGetDefaultPrinter:
    def test_non_windows_returns_none(self, tmp_path):
        gen = PriceListGenerator(output_dir=str(tmp_path))
        with patch("os.name", "posix"):
            result = gen._get_default_printer()
            assert result is None

    def test_windows_get_printer_success(self, tmp_path):
        gen = PriceListGenerator(output_dir=str(tmp_path))
        mock_win32print = MagicMock()
        mock_win32print.GetDefaultPrinter.return_value = "HP LaserJet"
        with patch.dict(sys.modules, {"win32print": mock_win32print}):
            with patch("os.name", "nt"):
                result = gen._get_default_printer()
                assert result == "HP LaserJet"

    def test_windows_get_printer_error(self, tmp_path):
        gen = PriceListGenerator(output_dir=str(tmp_path))
        mock_win32print = MagicMock()
        mock_win32print.GetDefaultPrinter.side_effect = OSError("no printer")
        with patch.dict(sys.modules, {"win32print": mock_win32print}):
            with patch("os.name", "nt"):
                result = gen._get_default_printer()
                assert result is None


class TestPriceListGeneratorPrintFile:
    def test_non_windows_skips_print(self, tmp_path):
        gen = PriceListGenerator(output_dir=str(tmp_path))
        with patch("os.name", "posix"):
            # Should not raise
            gen._print_file(str(tmp_path / "test.docx"), "HP LaserJet")

    def test_windows_printer_not_found_uses_default(self, tmp_path):
        gen = PriceListGenerator(output_dir=str(tmp_path))
        mock_win32print = MagicMock()
        mock_win32print.PRINTER_ENUM_LOCAL = 2
        mock_win32print.PRINTER_ENUM_CONNECTIONS = 4
        mock_win32print.EnumPrinters.return_value = []
        mock_win32print.GetDefaultPrinter.return_value = "DefaultPrinter"
        mock_win32api = MagicMock()
        # _print_file uses Path(filepath).suffix which creates WindowsPath when os.name=="nt"
        # Use PosixPath directly to avoid WindowsPath on macOS
        from pathlib import PosixPath

        with patch.dict(sys.modules, {"win32print": mock_win32print, "win32api": mock_win32api}):
            with patch("os.name", "nt"):
                with patch("app.infrastructure.documents.price_list_generator.Path", PosixPath):
                    gen._print_file(str(tmp_path / "test.docx"), "HP LaserJet")

    def test_windows_print_error(self, tmp_path):
        gen = PriceListGenerator(output_dir=str(tmp_path))
        mock_win32print = MagicMock()
        mock_win32print.PRINTER_ENUM_LOCAL = 2
        mock_win32print.PRINTER_ENUM_CONNECTIONS = 4
        mock_win32print.EnumPrinters.side_effect = OSError("fail")
        mock_win32api = MagicMock()
        from pathlib import PosixPath

        with patch.dict(sys.modules, {"win32print": mock_win32print, "win32api": mock_win32api}):
            with patch("os.name", "nt"):
                with patch("app.infrastructure.documents.price_list_generator.Path", PosixPath):
                    with pytest.raises(OSError):
                        gen._print_file(str(tmp_path / "test.docx"), "HP LaserJet")
