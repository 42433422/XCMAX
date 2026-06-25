"""真实行为测试: app/services/printer_service.py 未覆盖分支补强。

目标未覆盖行: 私有助手 (_load_selection / _save_selection / _resolve_name /
_guess_* )、get_printer_selection / save_printer_selection、classify_printers、
get_document_printer / get_label_printer 的真实选择流程，以及模块级函数。

外部依赖 PrinterUtils / EnhancedPrinterUtils 全部 mock；磁盘读写用 tmp_path
重定向 _selection_file，确定性、离线、快速。
"""

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def service(tmp_path):
    """构造一个 PrinterService，外部 utils 全 mock，选择文件落到 tmp_path。"""
    with (
        patch("app.services.printer_service.PrinterUtils") as mock_pu,
        patch("app.services.printer_service.EnhancedPrinterUtils") as mock_eu,
    ):
        from app.services.printer_service import PrinterService

        mock_pu_inst = MagicMock()
        mock_eu_inst = MagicMock()
        mock_pu.return_value = mock_pu_inst
        mock_eu.return_value = mock_eu_inst

        svc = PrinterService()
        # 把选择文件重定向到临时目录，避免污染真实 app data dir。
        svc._selection_file = str(tmp_path / "printer_selection.json")
        # 暴露 mock 实例方便断言。
        svc._mock_pu = mock_pu_inst
        svc._mock_eu = mock_eu_inst
        yield svc


# --------------------------------------------------------------------------
# _load_selection (lines 22-30)
# --------------------------------------------------------------------------
def test_load_selection_missing_file_returns_empty(service):
    # 文件不存在 -> {}
    assert service._load_selection() == {}


def test_load_selection_reads_valid_dict(service):
    payload = {"document_printer": "Doc", "label_printer": "Lbl"}
    with open(service._selection_file, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    assert service._load_selection() == payload


def test_load_selection_non_dict_json_returns_empty(service):
    # JSON 顶层是 list -> 不是 dict -> {}
    with open(service._selection_file, "w", encoding="utf-8") as f:
        json.dump(["not", "a", "dict"], f)
    assert service._load_selection() == {}


def test_load_selection_invalid_json_returns_empty(service):
    # 损坏 JSON -> JSONDecodeError(属 RECOVERABLE_ERRORS) -> {}
    with open(service._selection_file, "w", encoding="utf-8") as f:
        f.write("{ this is not valid json ")
    assert service._load_selection() == {}


# --------------------------------------------------------------------------
# _save_selection (lines 33-34) + 往返
# --------------------------------------------------------------------------
def test_save_selection_writes_file_roundtrip(service):
    payload = {"document_printer": "针式机", "label_printer": "TSC"}
    service._save_selection(payload)
    with open(service._selection_file, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk == payload
    # 中文非 ASCII 应原样保留(ensure_ascii=False)
    with open(service._selection_file, encoding="utf-8") as f:
        raw = f.read()
    assert "针式机" in raw


# --------------------------------------------------------------------------
# _resolve_name (lines 42-53)
# --------------------------------------------------------------------------
def test_resolve_name_empty_returns_none(service):
    assert service._resolve_name("   ", [{"name": "P1"}]) is None
    assert service._resolve_name(None, [{"name": "P1"}]) is None


def test_resolve_name_exact_match(service):
    printers = [{"name": "HP LaserJet"}, {"name": "TSC TTP"}]
    assert service._resolve_name("HP LaserJet", printers) == "HP LaserJet"


def test_resolve_name_case_insensitive_match(service):
    printers = [{"name": "HP LaserJet"}, {"name": "TSC TTP"}]
    # 大小写不同 -> 走 lower 匹配，返回真实名(带原大小写并 strip)
    assert service._resolve_name("hp laserjet", printers) == "HP LaserJet"


def test_resolve_name_no_match_returns_none(service):
    printers = [{"name": "HP LaserJet"}]
    assert service._resolve_name("Brother", printers) is None


# --------------------------------------------------------------------------
# _guess_document_printer (lines 58, 63, 64)
# --------------------------------------------------------------------------
def test_guess_document_printer_empty_returns_none(service):
    assert service._guess_document_printer([]) is None


def test_guess_document_printer_keyword_hit(service):
    printers = [{"name": "Random"}, {"name": "Canon iP"}]
    # "canon" 命中关键词
    assert service._guess_document_printer(printers) == "Canon iP"


def test_guess_document_printer_fallback_first(service):
    printers = [{"name": "Mystery"}, {"name": "Unknown"}]
    # 无关键词命中 -> 返回第一台
    assert service._guess_document_printer(printers) == "Mystery"


# --------------------------------------------------------------------------
# _guess_label_printer (lines 69, 74, 75)
# --------------------------------------------------------------------------
def test_guess_label_printer_empty_returns_none(service):
    assert service._guess_label_printer([]) is None


def test_guess_label_printer_keyword_hit(service):
    printers = [{"name": "Plain"}, {"name": "Zebra ZD"}, {"name": "Tail"}]
    assert service._guess_label_printer(printers) == "Zebra ZD"


def test_guess_label_printer_fallback_last(service):
    printers = [{"name": "Alpha"}, {"name": "Beta"}]
    # 无关键词 -> 返回最后一台
    assert service._guess_label_printer(printers) == "Beta"


# --------------------------------------------------------------------------
# get_printer_selection (77-82) + save_printer_selection (87-99)
# --------------------------------------------------------------------------
def test_get_printer_selection_empty_when_no_file(service):
    sel = service.get_printer_selection()
    assert sel == {"document_printer": None, "label_printer": None}


def test_save_then_get_printer_selection_roundtrip(service):
    res = service.save_printer_selection("  Doc Printer  ", "Label Printer")
    assert res["success"] is True
    # 保存时做了 strip
    assert res["selection"] == {
        "document_printer": "Doc Printer",
        "label_printer": "Label Printer",
    }
    assert res["message"] == "打印机选择已保存"
    # 重新读取确认落盘后再 normalize
    sel = service.get_printer_selection()
    assert sel == {"document_printer": "Doc Printer", "label_printer": "Label Printer"}


def test_save_printer_selection_blank_becomes_none(service):
    # 空白字符串 normalize 后为空 -> selection 里映射为 None
    res = service.save_printer_selection("   ", None)
    assert res["selection"] == {"document_printer": None, "label_printer": None}


# --------------------------------------------------------------------------
# classify_printers (101-142) — 真实选择 + 兜底 + status_of 各分支
# --------------------------------------------------------------------------
def test_classify_printers_uses_saved_selection(service):
    printers = [
        {"name": "HP Doc", "status": "就绪"},
        {"name": "TSC Label", "status": "空闲"},
    ]
    service.save_printer_selection("HP Doc", "TSC Label")
    result = service.classify_printers(printers)

    doc = result["classified"]["document_printer"]
    lbl = result["classified"]["label_printer"]
    assert doc["name"] == "HP Doc"
    assert doc["status"] == "就绪"
    assert doc["is_connected"] is True
    assert lbl["name"] == "TSC Label"
    assert lbl["status"] == "空闲"

    summary = result["summary"]
    assert summary["total_printers"] == 2
    assert summary["all_ready"] is True
    assert result["selection"] == {
        "document_printer": "HP Doc",
        "label_printer": "TSC Label",
    }


def test_classify_printers_falls_back_to_guess(service):
    # 无保存选择 -> 走 guess。第一台命中 doc 关键词, label 走最后一台。
    printers = [
        {"name": "Epson LQ", "status": "就绪"},
        {"name": "TSC Printer", "status": "就绪"},
    ]
    result = service.classify_printers(printers)
    # doc: epson 命中关键词 -> Epson LQ
    assert result["classified"]["document_printer"]["name"] == "Epson LQ"
    # label: tsc 命中 -> TSC Printer
    assert result["classified"]["label_printer"]["name"] == "TSC Printer"


def test_classify_printers_empty_status_unknown(service):
    # 选了一台名字但 printers 里无 status 字段 -> status_of 返回 "未知"
    printers = [{"name": "NoStatus"}]
    service.save_printer_selection("NoStatus", "NoStatus")
    result = service.classify_printers(printers)
    assert result["classified"]["document_printer"]["status"] == "未知"


def test_classify_printers_no_printers_status_disconnected(service):
    # 空打印机列表 -> selected 都为 None -> status_of(None) = "未连接"
    result = service.classify_printers([])
    assert result["classified"]["document_printer"]["name"] is None
    assert result["classified"]["document_printer"]["status"] == "未连接"
    assert result["classified"]["document_printer"]["is_connected"] is False
    assert result["summary"]["all_ready"] is False


# --------------------------------------------------------------------------
# get_document_printer (170-175) / get_label_printer (181-183) 真实流程
# --------------------------------------------------------------------------
def test_get_document_printer_none_when_no_printers(service):
    service._mock_pu.get_available_printers.return_value = []
    assert service.get_document_printer() is None


def test_get_document_printer_prefers_saved_selection(service):
    service._mock_pu.get_available_printers.return_value = [
        {"name": "Saved Doc"},
        {"name": "Other"},
    ]
    service.save_printer_selection("Saved Doc", "")
    assert service.get_document_printer() == "Saved Doc"


def test_get_document_printer_guess_when_no_selection(service):
    # 无保存选择 -> 走 guess: 第一台无关键词时返回第一台
    service._mock_pu.get_available_printers.return_value = [
        {"name": "First"},
        {"name": "Second"},
    ]
    assert service.get_document_printer() == "First"


def test_get_label_printer_none_when_no_printers(service):
    service._mock_pu.get_available_printers.return_value = []
    assert service.get_label_printer() is None


def test_get_label_printer_prefers_saved_selection(service):
    service._mock_pu.get_available_printers.return_value = [
        {"name": "Lbl A"},
        {"name": "Lbl B"},
    ]
    service.save_printer_selection("", "Lbl B")
    assert service.get_label_printer() == "Lbl B"


def test_get_label_printer_guess_when_no_selection(service):
    # 无保存 -> guess: 无关键词时返回最后一台
    service._mock_pu.get_available_printers.return_value = [
        {"name": "One"},
        {"name": "Two"},
    ]
    assert service.get_label_printer() == "Two"


# --------------------------------------------------------------------------
# 模块级函数 (278-280, 283-284, 287-288, 291-292)
# --------------------------------------------------------------------------
def test_module_get_printers_returns_list():
    import app.services.printer_service as ps

    fake = {"success": True, "printers": [{"name": "X"}], "count": 1}
    with patch.object(ps.printer_service, "get_printers", return_value=fake):
        assert ps.get_printers() == [{"name": "X"}]


def test_module_get_printers_missing_key_defaults_empty():
    import app.services.printer_service as ps

    with patch.object(ps.printer_service, "get_printers", return_value={"success": False}):
        assert ps.get_printers() == []


def test_module_get_document_printer_delegates():
    import app.services.printer_service as ps

    with patch.object(ps.printer_service, "get_document_printer", return_value="DocX"):
        assert ps.get_document_printer() == "DocX"


def test_module_get_label_printer_delegates():
    import app.services.printer_service as ps

    with patch.object(ps.printer_service, "get_label_printer", return_value="LblX"):
        assert ps.get_label_printer() == "LblX"


def test_module_validate_printer_separation_delegates():
    import app.services.printer_service as ps

    expected = {"valid": True, "doc_printer": "D", "label_printer": "L"}
    with patch.object(ps.printer_service, "validate_printer_separation", return_value=expected):
        assert ps.validate_printer_separation() == expected
