"""附件工件解析、存储与只读工具测试。"""

from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest

from app.application.attachment_artifacts import tools
from app.application.attachment_artifacts.attachment_parser import (
    TemporaryDocument,
    UnsupportedDocument,
    parse_file,
)
from app.application.attachment_artifacts.models import ArtifactRecord
from app.application.attachment_artifacts.store import ArtifactStore


def _make_xlsx(path: Path) -> Path:
    workbook = openpyxl.Workbook()
    orders = workbook.active
    orders.title = "订单"
    orders.append(["单号", "客户", "金额"])
    orders.append(["A001", "张三", 120])
    orders.append(["A002", "李四", 80])
    orders.append(["A003", "王五", 50])
    orders.append(["A004", "赵六", 30])
    orders.append(["A005", "钱七", "待定"])
    detail = workbook.create_sheet("明细")
    detail.append(["物料", "数量"])
    for index in range(250):
        detail.append([f"物料{index}", index])
    workbook.save(path)
    workbook.close()
    return path


@pytest.fixture()
def record(tmp_path: Path) -> ArtifactRecord:
    return parse_file(_make_xlsx(tmp_path / "订单.xlsx"), name="订单.xlsx")


@pytest.fixture()
def store(tmp_path: Path, record: ArtifactRecord) -> ArtifactStore:
    artifact_store = ArtifactStore(tmp_path)
    artifact_store.save(record)
    return artifact_store


def test_parse_xlsx_sheets(record: ArtifactRecord) -> None:
    assert record.name == "订单.xlsx"
    assert record.suffix == ".xlsx"
    assert record.size > 0
    assert record.sha1 == record.id
    assert [sheet.name for sheet in record.sheets] == ["订单", "明细"]

    orders = record.sheets[0]
    assert orders.columns == ["单号", "客户", "金额"]
    assert orders.row_count == 5
    assert orders.rows_preview[0] == ["A001", "张三", "120"]
    assert len(orders.rows_preview) == 3
    assert orders.truncated is True

    detail = record.sheets[1]
    assert detail.row_count == 250
    assert len(detail.rows_preview) == 3
    assert detail.truncated is True


def test_temporary_and_legacy_xls(tmp_path: Path) -> None:
    with pytest.raises(TemporaryDocument):
        parse_file(tmp_path / "~$订单.xlsx")
    with pytest.raises(TemporaryDocument):
        parse_file(tmp_path / "._订单.xlsx")
    with pytest.raises(UnsupportedDocument):
        parse_file(tmp_path / "旧表.xls")


def test_store_save_get_list_delete(
    store: ArtifactStore, record: ArtifactRecord
) -> None:
    index = json.loads((store.root / "index.json").read_text(encoding="utf-8"))
    assert index["items"][record.id]["sheets"] == 2
    assert index["items"][record.id]["row_count"] == 255
    assert not [path for path in store.root.iterdir() if path.name.endswith(".tmp")]

    loaded = store.get(record.id)
    assert loaded is not None
    assert loaded.name == record.name
    assert len(loaded.sheets) == 2
    assert store.get("../escape") is None

    listed = store.list_all()
    assert [item["id"] for item in listed] == [record.id]

    assert store.delete(record.id) is True
    assert store.get(record.id) is None
    assert store.list_all() == []
    assert store.delete(record.id) is False


def test_read_slice_bounds_and_cap(store: ArtifactStore, record: ArtifactRecord) -> None:
    page = tools.read_slice(store, record.id, "明细", start=0, limit=500)
    assert page["ok"] is True
    assert len(page["rows"]) == tools.MAX_SLICE_ROWS
    assert page["total_rows"] == 250
    assert page["truncated"] is True

    tail = tools.read_slice(store, record.id, "明细", start=999)
    assert tail["rows"] == []
    assert tail["truncated"] is False

    assert len(tools.read_slice(store, record.id, "明细", limit=0)["rows"]) == 1
    assert tools.read_slice(store, record.id, "不存在")["error"] == "sheet_not_found"


def test_search_rows(store: ArtifactStore, record: ArtifactRecord) -> None:
    hit = tools.search_rows(store, record.id, "a001")
    assert hit["ok"] is True
    assert hit["matches"] == [{"sheet": "订单", "row": 2, "values": ["A001", "张三", "120"]}]

    capped = tools.search_rows(store, record.id, "物料", limit=999)
    assert len(capped["matches"]) == tools.MAX_SEARCH_ROWS
    assert capped["truncated"] is True


def test_aggregate_rows(store: ArtifactStore, record: ArtifactRecord) -> None:
    total = tools.aggregate_rows(store, record.id, "订单", "金额", "sum")
    assert total["value"] == 280.0
    assert total["used_rows"] == 4
    assert total["skipped_rows"] == 1

    average = tools.aggregate_rows(store, record.id, "订单", "金额", "avg")
    assert average["value"] == 70.0

    counted = tools.aggregate_rows(store, record.id, "订单", "金额", "count")
    assert counted["value"] == 4.0

    missing = tools.aggregate_rows(store, record.id, "订单", "不存在", "sum")
    assert missing["error"] == "column_not_found"


def test_execute_tool_dispatch(store: ArtifactStore, record: ArtifactRecord) -> None:
    assert tools.execute_tool("unknown_tool", {}, store) == {
        "ok": False,
        "error": "unknown_tool",
    }
    assert tools.execute_tool("list_attachments", {}, store)["attachments"][0]["id"] == record.id
    assert tools.execute_tool("describe_attachment", {"artifact_id": record.id}, store)["ok"] is True
    assert {item["name"] for item in tools.TOOL_SPECS} == {
        "list_attachments",
        "describe_attachment",
        "read_slice",
        "search_rows",
        "aggregate_rows",
    }
