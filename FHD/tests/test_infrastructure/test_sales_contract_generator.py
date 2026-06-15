"""测试 sales_contract_generator 模块的销售合同生成。"""
import os
import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal

from app.infrastructure.documents.sales_contract_generator import SalesContractGenerator


# ---------------------------------------------------------------------------
# _num_to_chinese_upper
# ---------------------------------------------------------------------------

class TestNumToChineseUpper:
    @pytest.fixture
    def gen(self, tmp_path):
        """创建一个使用临时目录的生成器（不需要真实模板）。"""
        return SalesContractGenerator.__new__(SalesContractGenerator)

    def test_zero(self, gen):
        assert gen._num_to_chinese_upper(0) == "零元整"

    def test_one(self, gen):
        result = gen._num_to_chinese_upper(1)
        assert "壹" in result
        assert "元" in result

    def test_ten(self, gen):
        result = gen._num_to_chinese_upper(10)
        assert "拾" in result

    def test_hundred(self, gen):
        result = gen._num_to_chinese_upper(100)
        assert "佰" in result

    def test_thousand(self, gen):
        result = gen._num_to_chinese_upper(1000)
        assert "仟" in result

    def test_ten_thousand(self, gen):
        result = gen._num_to_chinese_upper(10000)
        assert "万" in result

    def test_decimal_input(self, gen):
        result = gen._num_to_chinese_upper(Decimal(392))
        assert "叁" in result or "玖" in result

    def test_complex_number(self, gen):
        result = gen._num_to_chinese_upper(12345)
        assert "壹" in result
        assert "万" in result

    def test_has_yuan_suffix(self, gen):
        result = gen._num_to_chinese_upper(500)
        assert result.endswith("元零角零分") or result.endswith("元")

    def test_no_double_zero(self, gen):
        result = gen._num_to_chinese_upper(1001)
        assert "零零" not in result


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_custom_output_dir(self, tmp_path):
        gen = SalesContractGenerator(
            template_path=str(tmp_path / "template.docx"),
            output_dir=str(tmp_path / "output"),
        )
        assert gen.output_dir == str(tmp_path / "output")
        assert os.path.isdir(str(tmp_path / "output"))

    def test_default_output_dir(self, tmp_path):
        gen = SalesContractGenerator(
            template_path=str(tmp_path / "template.docx"),
        )
        assert gen.output_dir is not None
        assert os.path.isdir(gen.output_dir)


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

class TestGenerate:
    @pytest.fixture
    def gen(self, tmp_path):
        """创建生成器并 mock Document 以避免需要真实模板文件。"""
        gen = SalesContractGenerator(
            template_path=str(tmp_path / "template.docx"),
            output_dir=str(tmp_path / "output"),
        )
        return gen

    def _make_mock_doc(self):
        """创建一个足够完整的 mock Document 对象。"""
        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        # Create a mock table with enough rows
        mock_table = MagicMock()
        mock_rows = []
        for _ in range(16):
            mock_row = MagicMock()
            mock_cells = [MagicMock() for _ in range(10)]
            mock_row.cells = mock_cells
            mock_rows.append(mock_row)
        mock_table.rows = mock_rows
        mock_doc.tables = [mock_table]
        return mock_doc

    @patch("app.infrastructure.documents.sales_contract_generator.Document")
    def test_generate_with_defaults(self, MockDoc, gen):
        MockDoc.return_value = self._make_mock_doc()

        result = gen.generate("测试客户")
        assert result["success"] is True
        assert result["customer_name"] == "测试客户"
        assert result["contract_id"] is not None
        assert result["filename"] is not None

    @patch("app.infrastructure.documents.sales_contract_generator.Document")
    def test_generate_with_custom_date(self, MockDoc, gen):
        MockDoc.return_value = self._make_mock_doc()

        result = gen.generate("测试客户", contract_date="2024年01月01日")
        assert result["contract_date"] == "2024年01月01日"

    @patch("app.infrastructure.documents.sales_contract_generator.Document")
    def test_generate_with_products(self, MockDoc, gen):
        MockDoc.return_value = self._make_mock_doc()

        products = [
            {"model_number": "306B", "name": "PU亮光硬化剂", "spec": "10KG×1",
             "unit": "桶", "quantity": "10 KG", "unit_price": "39.2", "amount": "392"},
        ]
        result = gen.generate("测试客户", products=products)
        assert result["success"] is True
        assert result["total_amount"] == 392.0

    @patch("app.infrastructure.documents.sales_contract_generator.Document")
    def test_generate_filename_sanitized(self, MockDoc, gen):
        MockDoc.return_value = self._make_mock_doc()

        result = gen.generate("测试/客户")
        assert "/" not in result["filename"]

    @patch("app.infrastructure.documents.sales_contract_generator.Document")
    def test_generate_saves_file(self, MockDoc, gen):
        mock_doc = self._make_mock_doc()
        MockDoc.return_value = mock_doc

        result = gen.generate("测试客户")
        mock_doc.save.assert_called_once()
        assert result["file_path"] is not None


# ---------------------------------------------------------------------------
# _fill_customer
# ---------------------------------------------------------------------------

class TestFillCustomer:
    @pytest.fixture
    def gen(self, tmp_path):
        return SalesContractGenerator(
            template_path=str(tmp_path / "template.docx"),
            output_dir=str(tmp_path / "output"),
        )

    def test_replaces_company_name(self, gen):
        mock_para = MagicMock()
        mock_para.text = "甲方：惠州市宝盈家具有限公司"
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para]

        gen._fill_customer(mock_doc, "新客户公司", "13800138000")
        assert "惠州市宝盈家具有限公司" not in mock_para.text
        assert "新客户公司" in mock_para.text

    def test_no_match_no_change(self, gen):
        mock_para = MagicMock()
        mock_para.text = "其他内容"
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para]

        gen._fill_customer(mock_doc, "新客户", "13800138000")
        assert mock_para.text == "其他内容"


# ---------------------------------------------------------------------------
# _fill_address_date
# ---------------------------------------------------------------------------

class TestFillAddressDate:
    @pytest.fixture
    def gen(self, tmp_path):
        return SalesContractGenerator(
            template_path=str(tmp_path / "template.docx"),
            output_dir=str(tmp_path / "output"),
        )

    def test_replaces_address_and_date(self, gen):
        mock_para = MagicMock()
        mock_para.text = "ADDRESS DATE"
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para]

        gen._fill_address_date(mock_doc, "客户A", "2024年01月01日")
        assert "ADDRESS" not in mock_para.text
        assert "客户A" in mock_para.text
        assert "2024年01月01日" in mock_para.text
