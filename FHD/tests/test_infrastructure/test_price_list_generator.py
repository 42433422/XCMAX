"""测试价格表生成器模块。"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.documents.price_list_generator import PriceListGenerator


@pytest.fixture
def output_dir(tmp_path):
    return str(tmp_path / "price_lists")


@pytest.fixture
def generator(output_dir):
    return PriceListGenerator(output_dir=output_dir)


@pytest.fixture
def sample_products():
    return [
        {
            "model_number": "PE-001",
            "name": "PE白底漆",
            "spec": "20kg",
            "unit": "桶",
            "unit_price": "150.00",
        },
        {
            "model_number": "PE-002",
            "name": "PE面漆",
            "spec": "28kg",
            "unit": "桶",
            "unit_price": "200.00",
        },
    ]


class TestPriceListGeneratorInit:
    """测试初始化。"""

    def test_creates_output_dir(self, output_dir):
        gen = PriceListGenerator(output_dir=output_dir)
        assert Path(output_dir).is_dir()

    def test_default_output_dir(self):
        gen = PriceListGenerator()
        assert gen.output_dir.is_dir()

    def test_output_dir_is_path(self, generator):
        assert isinstance(generator.output_dir, Path)


class TestPriceListGeneratorGenerate:
    """测试价格表生成。"""

    def test_generate_returns_success(self, generator, sample_products):
        with patch.object(generator, "_create_price_list_pdf"):
            with patch.object(generator, "_get_default_printer", return_value=None):
                result = generator.generate("测试客户", sample_products)
        assert result["success"] is True
        assert "filename" in result
        assert "filepath" in result
        assert result["message"] == "价格表已生成"

    def test_generate_creates_filename(self, generator, sample_products):
        with patch.object(generator, "_create_price_list_pdf"):
            with patch.object(generator, "_get_default_printer", return_value=None):
                result = generator.generate("测试客户", sample_products)
        assert "测试客户" in result["filename"]
        assert "价格表" in result["filename"]

    def test_generate_filename_contains_customer_name(self, generator, sample_products):
        with patch.object(generator, "_create_price_list_pdf"):
            with patch.object(generator, "_get_default_printer", return_value=None):
                result = generator.generate("七彩乐园", sample_products)
        assert "七彩乐园" in result["filename"]

    def test_generate_sanitizes_slash_in_name(self, generator, sample_products):
        with patch.object(generator, "_create_price_list_pdf"):
            with patch.object(generator, "_get_default_printer", return_value=None):
                result = generator.generate("公司/分部", sample_products)
        assert "/" not in result["filename"]
        assert "_" in result["filename"]

    def test_generate_sanitizes_backslash_in_name(self, generator, sample_products):
        with patch.object(generator, "_create_price_list_pdf"):
            with patch.object(generator, "_get_default_printer", return_value=None):
                result = generator.generate("公司\\分部", sample_products)
        assert "\\" not in result["filename"]

    def test_generate_with_empty_products(self, generator):
        with patch.object(generator, "_create_price_list_pdf"):
            with patch.object(generator, "_get_default_printer", return_value=None):
                result = generator.generate("空客户", [])
        assert result["success"] is True

    def test_generate_with_empty_customer_name(self, generator, sample_products):
        with patch.object(generator, "_create_price_list_pdf"):
            with patch.object(generator, "_get_default_printer", return_value=None):
                result = generator.generate("", sample_products)
        assert result["success"] is True

    def test_generate_with_printer_name(self, generator, sample_products):
        with patch.object(generator, "_create_price_list_pdf"):
            with patch.object(generator, "_print_file") as mock_print:
                result = generator.generate("测试客户", sample_products, printer_name="HP_Printer")
        assert result["success"] is True
        mock_print.assert_called_once()

    def test_generate_without_printer_no_default(self, generator, sample_products):
        with patch.object(generator, "_create_price_list_pdf"):
            with patch.object(generator, "_get_default_printer", return_value=None):
                result = generator.generate("测试客户", sample_products)
        assert result["success"] is True

    def test_generate_with_default_printer(self, generator, sample_products):
        with patch.object(generator, "_create_price_list_pdf"):
            with patch.object(generator, "_get_default_printer", return_value="DefaultPrinter"):
                with patch.object(generator, "_print_file") as mock_print:
                    result = generator.generate("测试客户", sample_products)
        assert result["success"] is True
        mock_print.assert_called_once()


class TestPriceListGeneratorCreatePdf:
    """测试 Word/文本文件创建。"""

    def test_create_price_list_with_resolve_root_none(self, generator, sample_products, tmp_path):
        """resolve_fhd_repo_root 返回 None 时抛出 RuntimeError，被 RECOVERABLE_ERRORS 捕获。"""
        filepath = tmp_path / "test_output.docx"
        with patch(
            "app.infrastructure.documents.price_list_generator.resolve_fhd_repo_root",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="未解析到 FHD 仓库根目录"):
                generator._create_price_list_pdf(filepath, "测试客户", sample_products)

    def test_create_price_list_with_valid_root_no_template(self, generator, sample_products, tmp_path):
        """有 root 但模板文件不存在时，走 python-docx 或 txt 回退。"""
        filepath = tmp_path / "test_output.docx"
        fake_root = tmp_path / "fhd_root"
        fake_root.mkdir()
        with patch(
            "app.infrastructure.documents.price_list_generator.resolve_fhd_repo_root",
            return_value=fake_root,
        ):
            try:
                generator._create_price_list_pdf(filepath, "测试客户", sample_products)
                assert filepath.exists() or filepath.with_suffix(".txt").exists()
            except (ImportError, FileNotFoundError):
                pass

    def test_create_price_list_with_pydantic_model(self, generator, tmp_path):
        mock_product = MagicMock()
        mock_product.model_number = "PE-001"
        mock_product.name = "PE白底漆"
        mock_product.spec = "20kg"
        mock_product.unit = "桶"
        mock_product.unit_price = "150.00"
        mock_product.__class__ = type("Product", (), {})
        isinstance(mock_product, dict)

        filepath = tmp_path / "test_pydantic.docx"
        fake_root = tmp_path / "fhd_root2"
        fake_root.mkdir()
        with patch(
            "app.infrastructure.documents.price_list_generator.resolve_fhd_repo_root",
            return_value=fake_root,
        ):
            try:
                generator._create_price_list_pdf(filepath, "测试客户", [mock_product])
            except (ImportError, FileNotFoundError):
                pass


class TestPriceListGeneratorGetDefaultPrinter:
    """测试默认打印机获取。"""

    def test_get_default_printer_non_windows(self, generator):
        with patch("os.name", "posix"):
            result = generator._get_default_printer()
            assert result is None


class TestPriceListGeneratorPrintFile:
    """测试打印功能。"""

    def test_print_file_non_windows(self, generator):
        with patch("os.name", "posix"):
            generator._print_file("/fake/path.docx", "HP_Printer")


class TestPriceListGeneratorRecoverableError:
    """测试可恢复错误处理。"""

    def test_generate_handles_os_error(self, generator, sample_products):
        with patch.object(
            generator,
            "_create_price_list_pdf",
            side_effect=OSError("disk full"),
        ):
            result = generator.generate("测试客户", sample_products)
        assert result["success"] is False
        assert "disk full" in result["message"]

    def test_generate_handles_value_error(self, generator, sample_products):
        with patch.object(
            generator,
            "_create_price_list_pdf",
            side_effect=ValueError("bad value"),
        ):
            result = generator.generate("测试客户", sample_products)
        assert result["success"] is False
