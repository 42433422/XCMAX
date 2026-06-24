"""真实行为测试（第二波）：覆盖 shipment_document_generator_impl 的缺失分支。

聚焦未覆盖行：
- SimpleLabelGenerator._get_font: not-PIL 短路(50) / win32 字体回退(67,73-77)
- SimpleLabelGenerator.generate_label: PIL 不可用短路(84-86) / has_ratio=False 布局(112-119,145,150)
  / except RECOVERABLE_ERRORS(234-236)
- LegacyShipmentDocumentGenerator._load_products_from_main_db: 真实 DB 循环(280-295)
- LegacyShipmentDocumentGenerator.generate: 无 parsed_products 早返(338)
  / doc 无 to_dict 的 getattr 分支(370-374)

外部依赖（PIL 字体文件、DB、legacy 生成器、文件系统）全部 mock/降级，离线确定。
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.infrastructure.documents.shipment_document_generator_impl as impl
from app.infrastructure.documents.shipment_document_generator_impl import (
    LegacyShipmentDocumentGenerator,
    SimpleLabelGenerator,
)

MOD = "app.infrastructure.documents.shipment_document_generator_impl"

pytestmark = pytest.mark.skipif(
    not impl._PIL_AVAILABLE,
    reason="PIL 不可用，跳过真实绘制相关用例",
)


# ---------------------------------------------------------------------------
# SimpleLabelGenerator._get_font
# ---------------------------------------------------------------------------


def test_get_font_returns_none_when_pil_unavailable():
    """_PIL_AVAILABLE=False 时 _get_font 立即返回 None（行 50）。"""
    gen = SimpleLabelGenerator(output_dir="/tmp/does-not-matter")
    with patch.object(impl, "_PIL_AVAILABLE", False):
        assert gen._get_font(40) is None


def test_get_font_falls_back_to_default_when_all_truetype_fail():
    """所有 truetype 失败且非 win32 → 走 load_default（行 79，覆盖循环 except）。"""
    gen = SimpleLabelGenerator(output_dir="/tmp/x")
    sentinel = object()
    fake_imagefont = MagicMock()
    fake_imagefont.truetype.side_effect = OSError("no such font")
    fake_imagefont.load_default.return_value = sentinel
    with (
        patch.object(impl, "ImageFont", fake_imagefont),
        patch("sys.platform", "linux"),
    ):
        result = gen._get_font(40)
    assert result is sentinel
    fake_imagefont.load_default.assert_called_once()


def test_get_font_win32_branch_first_winfont_succeeds():
    """win32 平台：项目内字体全失败后命中 Windows 系统字体（行 67,73-75）。"""
    gen = SimpleLabelGenerator(output_dir="/tmp/x")
    sentinel_font = object()

    call_log: list[str] = []

    def truetype(path, size):
        call_log.append(path)
        # 项目内相对字体路径全失败；Windows 绝对路径第一个就成功
        if path.startswith("C:\\Windows\\Fonts\\"):
            return sentinel_font
        raise OSError("missing")

    fake_imagefont = MagicMock()
    fake_imagefont.truetype.side_effect = truetype
    with (
        patch.object(impl, "ImageFont", fake_imagefont),
        patch("sys.platform", "win32"),
    ):
        result = gen._get_font(50)
    assert result is sentinel_font
    # 应当先尝试相对字体（至少一个），再尝试 Windows 绝对路径
    assert any(p.startswith("C:\\Windows\\Fonts\\") for p in call_log)
    fake_imagefont.load_default.assert_not_called()


def test_get_font_win32_branch_all_fail_falls_to_default():
    """win32 平台：系统字体也全失败 → 最终 load_default（行 73-77 except + 79）。"""
    gen = SimpleLabelGenerator(output_dir="/tmp/x")
    sentinel = object()
    fake_imagefont = MagicMock()
    fake_imagefont.truetype.side_effect = OSError("missing")
    fake_imagefont.load_default.return_value = sentinel
    with (
        patch.object(impl, "ImageFont", fake_imagefont),
        patch("sys.platform", "win32"),
    ):
        result = gen._get_font(40)
    assert result is sentinel
    fake_imagefont.load_default.assert_called_once()


# ---------------------------------------------------------------------------
# SimpleLabelGenerator.generate_label
# ---------------------------------------------------------------------------


def test_generate_label_returns_none_when_pil_unavailable(tmp_path):
    """PIL 不可用 → 记录 warning 并返回 None（行 84-86）。"""
    gen = SimpleLabelGenerator(output_dir=str(tmp_path))
    with patch.object(impl, "_PIL_AVAILABLE", False):
        result = gen.generate_label({"name": "测试产品"}, "ORD001", 1)
    assert result is None
    # 未写出任何文件
    assert list(tmp_path.iterdir()) == []


def test_generate_label_has_ratio_true_writes_png(tmp_path):
    """常规产品名（无 剂/料）→ has_ratio 分支，真实绘制并写出 PNG（返回文件名）。"""
    gen = SimpleLabelGenerator(output_dir=str(tmp_path))
    product = {
        "name": "环氧树脂",
        "model_number": "9803",
        "tin_spec": 20.0,
        "quantity_tins": 3,
        "ratio": "1 : 0.5 : 0.6",
    }
    filename = gen.generate_label(product, "ORD-RATIO", 2)
    assert filename is not None
    assert filename.startswith("ORD-RATIO_第2项_")
    assert filename.endswith(".png")
    written = tmp_path / filename
    assert written.exists()
    assert written.stat().st_size > 0


def test_generate_label_has_ratio_false_branch_writes_png(tmp_path):
    """产品名含『剂』→ has_ratio=False，走 else 布局分支（行 112-119,145,150）。"""
    gen = SimpleLabelGenerator(output_dir=str(tmp_path))
    product = {
        "name": "固化剂",  # 含『剂』→ has_ratio False
        "model_number": "H-100",
        "tin_spec": 0,  # 触发默认规格分支
    }
    filename = gen.generate_label(product, "ORD-NORATIO", 1)
    assert filename is not None
    assert "第1项" in filename
    assert (tmp_path / filename).exists()


def test_generate_label_uses_product_name_fallback_key(tmp_path):
    """name 缺失时回退 product_name；含『料』同样走 no-ratio 分支。"""
    gen = SimpleLabelGenerator(output_dir=str(tmp_path))
    product = {"product_name": "稀释料", "product_number": "X1"}
    filename = gen.generate_label(product, "ORD-FB", 5)
    assert filename is not None
    assert "稀释料" in filename
    assert (tmp_path / filename).exists()


def test_generate_label_returns_none_on_recoverable_error(tmp_path):
    """绘制过程中抛 RECOVERABLE_ERRORS（OSError）→ except 捕获返回 None（行 234-236）。"""
    gen = SimpleLabelGenerator(output_dir=str(tmp_path))
    fake_image = MagicMock()
    fake_image.new.side_effect = OSError("disk full")
    with patch.object(impl, "Image", fake_image):
        result = gen.generate_label({"name": "环氧树脂"}, "ORD-ERR", 1)
    assert result is None


# ---------------------------------------------------------------------------
# SimpleLabelGenerator.generate_labels_for_order
# ---------------------------------------------------------------------------


def test_generate_labels_for_order_skips_none_results(tmp_path):
    """generate_label 返回 None 的项被过滤；成功项进入结果列表。"""
    gen = SimpleLabelGenerator(output_dir=str(tmp_path))
    # 第一项返回 None，第二项返回文件名
    side = [None, "label_2.png"]

    def fake_generate(product, order_number, idx):
        return side[idx - 1]

    with patch.object(gen, "generate_label", side_effect=fake_generate):
        labels = gen.generate_labels_for_order("ORD-X", [{"a": 1}, {"b": 2}])

    assert len(labels) == 1
    entry = labels[0]
    assert entry["filename"] == "label_2.png"
    assert entry["order_number"] == "ORD-X"
    assert entry["label_number"] == "2"
    assert entry["file_path"].endswith("label_2.png")


# ---------------------------------------------------------------------------
# LegacyShipmentDocumentGenerator._load_products_from_main_db
# ---------------------------------------------------------------------------


def _make_doc_gen() -> LegacyShipmentDocumentGenerator:
    """构造适配器但跳过其 __init__ 的文件系统副作用。"""
    with patch.object(LegacyShipmentDocumentGenerator, "__init__", return_value=None):
        gen = LegacyShipmentDocumentGenerator()
    gen.output_dir = "/tmp/shipment_outputs"
    gen.template_dir = "/tmp/templates"
    return gen


def test_load_products_from_main_db_maps_rows():
    """真实映射 DB 行 → dict（行 280-295）；含 price=None 走 0.0 分支。"""
    gen = _make_doc_gen()

    row_with_price = SimpleNamespace(
        id=1,
        model_number="9803",
        name="环氧树脂",
        price=12.5,
        specification="20KG",
        brand="自有",
        unit="桶",
    )
    row_no_price = SimpleNamespace(
        id=2,
        model_number=None,
        name=None,
        price=None,
        specification=None,
        brand=None,
        unit=None,
    )

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.all.return_value = [
        row_with_price,
        row_no_price,
    ]

    @contextmanager
    def fake_get_db():
        yield fake_db

    with patch(f"{MOD}.get_db", fake_get_db):
        products = gen._load_products_from_main_db()

    assert len(products) == 2
    assert products[0] == {
        "id": 1,
        "model_number": "9803",
        "name": "环氧树脂",
        "price": 12.5,
        "specification": "20KG",
        "brand": "自有",
        "unit": "桶",
    }
    # None 字段全部降级为空串 / 0.0
    assert products[1]["model_number"] == ""
    assert products[1]["name"] == ""
    assert products[1]["price"] == 0.0
    assert products[1]["specification"] == ""
    assert products[1]["brand"] == ""
    assert products[1]["unit"] == ""


def test_load_products_from_main_db_empty():
    """无激活产品时返回空列表。"""
    gen = _make_doc_gen()
    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.all.return_value = []

    @contextmanager
    def fake_get_db():
        yield fake_db

    with patch(f"{MOD}.get_db", fake_get_db):
        products = gen._load_products_from_main_db()
    assert products == []


# ---------------------------------------------------------------------------
# LegacyShipmentDocumentGenerator.generate
# ---------------------------------------------------------------------------


def test_generate_returns_failure_when_no_parsed_products():
    """parsed_products 为空 → 早返失败（行 337-343 / 338）。"""
    gen = _make_doc_gen()

    resolved = SimpleNamespace(
        unit_name="测试单位",
        contact_person="张三",
        contact_phone="13800138000",
        address="地址",
        id=7,
    )
    loader_ns = SimpleNamespace(
        ShipmentDocumentGenerator=MagicMock(),
        PurchaseUnitInfo=MagicMock(),
    )

    with (
        patch(f"{MOD}.resolve_purchase_unit", return_value=resolved),
        patch(f"{MOD}.load_legacy_shipment_document_generator", return_value=loader_ns),
        patch.object(gen, "_load_products_from_main_db", return_value=[]),
        patch(f"{MOD}.prepare_parsed_products", return_value=[]),
    ):
        result = gen.generate(unit_name="测试单位", products=[{"product_name": "x"}])

    assert result["success"] is False
    assert result["message"] == "产品列表为空或无有效产品名称"
    assert result["doc_name"] is None
    assert result["file_path"] is None
    # legacy 生成器不应被实例化调用 generate_document
    loader_ns.ShipmentDocumentGenerator.return_value.generate_document.assert_not_called()


def test_generate_doc_without_to_dict_uses_getattr_branch():
    """legacy doc 无 to_dict → 走 getattr 分支（行 370-374）。"""
    gen = _make_doc_gen()

    resolved = SimpleNamespace(
        unit_name="测试单位",
        contact_person="张三",
        contact_phone="13800138000",
        address="地址",
        id=9,
    )

    # 没有 to_dict 的纯属性对象（用 SimpleNamespace 保证 hasattr(doc,"to_dict") 为 False）
    doc = SimpleNamespace(
        filepath="/tmp/out/dest.xlsx",
        filename="dest.xlsx",
        order_number="ORD-GA",
        total_amount=200.0,
        total_quantity=80.0,
    )
    assert not hasattr(doc, "to_dict")

    ShipmentDocumentGenerator = MagicMock()
    ShipmentDocumentGenerator.return_value.generate_document.return_value = doc
    loader_ns = SimpleNamespace(
        ShipmentDocumentGenerator=ShipmentDocumentGenerator,
        PurchaseUnitInfo=MagicMock(),
    )

    parsed = [{"product_name": "环氧树脂", "quantity": 1}]
    fake_label_gen = MagicMock()
    fake_label_gen.generate_labels_for_order.return_value = [{"filename": "L1.png"}]

    with (
        patch(f"{MOD}.resolve_purchase_unit", return_value=resolved),
        patch(f"{MOD}.load_legacy_shipment_document_generator", return_value=loader_ns),
        patch.object(gen, "_load_products_from_main_db", return_value=[]),
        patch(f"{MOD}.prepare_parsed_products", return_value=parsed),
        patch(f"{MOD}.get_resource_path", return_value="/tmp/labels"),
        patch(f"{MOD}.SimpleLabelGenerator", return_value=fake_label_gen),
        patch("app.db.init_db.get_db_path", return_value="/tmp/products.db"),
    ):
        result = gen.generate(unit_name="测试单位", products=[{"product_name": "x"}])

    assert result["success"] is True
    assert result["doc_name"] == "dest.xlsx"
    assert result["file_path"] == "/tmp/out/dest.xlsx"
    assert result["order_number"] == "ORD-GA"
    assert result["total_amount"] == 200.0
    assert result["total_quantity"] == 80.0
    assert result["labels"] == [{"filename": "L1.png"}]
    fake_label_gen.generate_labels_for_order.assert_called_once()


def test_generate_doc_without_to_dict_filename_from_basename():
    """doc 无 filename 属性时，从 filepath basename 推导（行 371 的 getattr 默认值）。"""
    gen = _make_doc_gen()

    resolved = SimpleNamespace(
        unit_name="测试单位",
        contact_person="李四",
        contact_phone="13900139000",
        address="addr",
        id=3,
    )

    # 仅含 filepath（无 filename/order_number/...）；getattr 默认值生效
    class _Doc:
        filepath = "/tmp/out/auto_name.xlsx"

    doc = _Doc()
    assert not hasattr(doc, "to_dict")
    assert not hasattr(doc, "filename")

    ShipmentDocumentGenerator = MagicMock()
    ShipmentDocumentGenerator.return_value.generate_document.return_value = doc
    loader_ns = SimpleNamespace(
        ShipmentDocumentGenerator=ShipmentDocumentGenerator,
        PurchaseUnitInfo=MagicMock(),
    )

    fake_label_gen = MagicMock()
    fake_label_gen.generate_labels_for_order.return_value = []

    with (
        patch(f"{MOD}.resolve_purchase_unit", return_value=resolved),
        patch(f"{MOD}.load_legacy_shipment_document_generator", return_value=loader_ns),
        patch.object(gen, "_load_products_from_main_db", return_value=[]),
        patch(f"{MOD}.prepare_parsed_products", return_value=[{"product_name": "p"}]),
        patch(f"{MOD}.get_resource_path", return_value="/tmp/labels"),
        patch(f"{MOD}.SimpleLabelGenerator", return_value=fake_label_gen),
        patch("app.db.init_db.get_db_path", return_value="/tmp/products.db"),
    ):
        result = gen.generate(unit_name="测试单位", products=[{"product_name": "x"}])

    assert result["success"] is True
    # filename 由 basename 推导
    assert result["doc_name"] == "auto_name.xlsx"
    assert result["file_path"] == "/tmp/out/auto_name.xlsx"
    assert result["order_number"] is None
    assert result["total_amount"] is None
    assert result["total_quantity"] is None
