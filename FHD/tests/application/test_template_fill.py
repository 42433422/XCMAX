"""模板填充：只用源数据写入租户模板，不编造行列。"""

from __future__ import annotations

from io import BytesIO

import openpyxl
import pytest


def _make_template(path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "生产打印单"
    ws["A1"] = "生产单"
    ws.merge_cells("A1:D2")
    ws["A4"] = "原材料编号"
    ws["B4"] = "原料数量（KG)"
    ws["C4"] = "工艺流程"
    ws["D4"] = "备注"
    ws.merge_cells("C5:C25")
    ws.merge_cells("D5:D25")
    ws["A26"] = "配方总量（KG)："
    ws["C26"] = "包装重量（KG)："
    wb.save(path)


def _make_source(path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "宗南"
    ws.append(["成都国圣工业有限公司（五星花）送货单"])
    ws.append([])
    ws.append(["产 品 型 号", "产 品 名 称", "数量/件", "规格/KG", "数量/KG", "单价/元", "备注"])
    ws.append(["6821AA\n", "PE白底漆", 1, 600, 600, 9, None])
    ws.append(["5559B", "PU净味七分光米白色漆", 2, 26, 52, 18.5, "加急"])
    ws.append(["合计", None, 3, None, 652, None, None])
    ws.append(["大 写 人 民 币", None, None, None, None, None, None])
    ws.append(["销售协议", None, None, None, None, None, None])
    wb.save(path)


def _patch_template(monkeypatch, template_path: str) -> None:
    from app.domain.shared_services.kitten_ai_document import template_fill

    monkeypatch.setattr(
        template_fill,
        "_resolve_template",
        lambda template_id, template_name, tenant_id: {
            "id": "db:46",
            "name": "生产打印单",
            "path": template_path,
        },
    )


def test_fill_uses_source_rows_and_skips_total(tmp_path, monkeypatch):
    from app.domain.shared_services.kitten_ai_document.template_fill import (
        fill_document_from_template,
    )

    template_path = str(tmp_path / "template.xlsx")
    source_path = str(tmp_path / "source.xlsx")
    _make_template(template_path)
    _make_source(source_path)
    _patch_template(monkeypatch, template_path)

    result = fill_document_from_template(
        template_name="生产打印单", file_path=source_path, tenant_id=1
    )

    assert result["row_count"] == 2
    assert result["skipped_rows"] == 0
    assert result["field_mapping"]["原材料编号"] == "产 品 型 号"
    assert result["field_mapping"]["原料数量（KG)"] == "数量/KG"
    assert result["field_mapping"]["备注"] == "备注"
    assert result["unmapped_labels"] == ["工艺流程"]

    wb = openpyxl.load_workbook(BytesIO(result["content"]))
    ws = wb.active
    assert ws["A5"].value == "6821AA\n"
    assert ws["B5"].value == 600
    assert ws["A6"].value == "5559B"
    assert ws["B6"].value == 52
    assert ws["D5"].value == "加急"  # 纵向合并的备注块取第一个非空值
    assert ws["A7"].value is None
    assert all("大写" not in str(ws.cell(row, 1).value or "") for row in range(5, 20))
    assert all("销售协议" not in str(ws.cell(row, 1).value or "") for row in range(5, 20))


def test_fill_requires_data_source(tmp_path, monkeypatch):
    from app.domain.shared_services.kitten_ai_document.template_fill import (
        fill_document_from_template,
    )

    template_path = str(tmp_path / "template.xlsx")
    _make_template(template_path)
    _patch_template(monkeypatch, template_path)

    with pytest.raises(ValueError, match="缺少数据来源"):
        fill_document_from_template(template_name="生产打印单", tenant_id=1)


def test_fill_accepts_inline_rows(tmp_path, monkeypatch):
    from app.domain.shared_services.kitten_ai_document.template_fill import (
        fill_document_from_template,
    )

    template_path = str(tmp_path / "template.xlsx")
    _make_template(template_path)
    _patch_template(monkeypatch, template_path)

    result = fill_document_from_template(
        template_name="生产打印单",
        rows=[{"产品型号": "0018#", "数量/KG": 25}],
        tenant_id=1,
    )
    wb = openpyxl.load_workbook(BytesIO(result["content"]))
    assert wb.active["A5"].value == "0018#"
    assert wb.active["B5"].value == 25


def test_template_preview_list_uses_runtime_tenant(monkeypatch):
    from app.domain.shared_services import tools_workflow_workspace as module

    seen: dict[str, object] = {}

    class _Service:
        def get_templates(self):
            from app.infrastructure.tenant_scope import current_tenant_id

            seen["tenant"] = current_tenant_id()
            return {"templates": [{"id": "db:46", "name": "生产打印单"}]}

    monkeypatch.setattr(
        "app.application.get_template_app_service", lambda: _Service(), raising=False
    )
    out = module._registered_router_template_preview(
        "list", {}, {"tenant_id": "1"}, "normal", ""
    )
    assert seen["tenant"] == 1
    assert out["count"] == 1
    assert out["templates"][0]["id"] == "db:46"
