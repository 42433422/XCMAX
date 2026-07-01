"""智能对话「一键导入数据库」对钉钉考勤/人员花名册表格的确定性导入。

验收链：上传考勤报表 → 导入 → 人员写 products(人员管理)、部门写 客户(purchase_units)
→ taiyangniao-pro 考勤表转换按该名单重排。
"""

from __future__ import annotations

import json

import openpyxl
import pytest

from app.application.tools import workflow as wf


def _write_dingtalk_style_xlsx(path, *, title_rows: bool = True) -> None:
    """构造钉钉导出风格：前两行标题，第 3 行才是表头。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "打卡时间"
    if title_rows:
        ws.append(["打卡时间 统计日期：2026-06-01 至 2026-06-30"])
        ws.append(["报表生成时间：2026-07-01"])
    ws.append(["姓名", "考勤组", "部门", "工号", "职位", "UserId", "打卡时间"])
    ws.append(["黄川平", "未加入考勤组", "董事会", "", "副总", "137", "11:52"])
    ws.append(["白锐", "公司-考勤", "公司-财务部", "A01", "数据员", "784", "08:59"])
    # 同名同部门重复行（钉钉多日导出常态）→ 应去重
    ws.append(["白锐", "公司-考勤", "公司-财务部", "A01", "数据员", "784", "09:01"])
    wb.save(path)


def _write_quote_style_xlsx(path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["产品名称", "型号", "单价", "数量"])
    ws.append(["外墙漆", "WQ-1", 100, 2])
    wb.save(path)


def test_roster_columns_detection_positive_and_negative():
    assert wf._looks_like_attendance_roster_columns(
        ["姓名", "考勤组", "部门", "工号", "职位", "UserId"]
    )
    # 产品信号列存在 → 不按花名册
    assert not wf._looks_like_attendance_roster_columns(["姓名", "产品名称", "单价"])
    # 无姓名列 → 不按花名册
    assert not wf._looks_like_attendance_roster_columns(["产品名称", "型号", "单价"])


def test_import_auto_switches_to_roster_and_autodetects_header(tmp_path):
    xlsx = tmp_path / "考勤报表.xlsx"
    _write_dingtalk_style_xlsx(xlsx)

    res = json.loads(
        wf._handle_import_excel_to_database(
            {
                "import_type": "products",
                "file_path": "考勤报表.xlsx",
                "preview_only": True,
            },
            workspace_root=str(tmp_path),
        )
    )
    assert res["success"] is True
    assert res["import_type"] == "attendance_roster"
    assert res["row_count"] == 2  # 去重后 2 人
    assert res["department_count"] == 2
    assert res["read_options"]["header_row"] == 3  # 自动定位到第 3 行表头
    names = {item["name"] for item in res["sample_data"]}
    assert names == {"黄川平", "白锐"}


def test_import_execute_writes_products_and_departments(tmp_path, monkeypatch):
    xlsx = tmp_path / "考勤报表.xlsx"
    _write_dingtalk_style_xlsx(xlsx)

    added_products: list[dict] = []
    created_customers: list[dict] = []

    class _FakeProducts:
        def batch_add_products(self, records):
            added_products.extend(records)
            return {"success": True, "data": {"success_count": len(records), "failed_count": 0}}

    class _FakeCustomers:
        def create(self, record):
            created_customers.append(record)
            return {"success": True}

    import app.bootstrap as bootstrap
    import app.services.unified_query_service as uqs

    monkeypatch.setattr(bootstrap, "get_products_service", lambda: _FakeProducts())
    monkeypatch.setattr(bootstrap, "get_customer_app_service", lambda: _FakeCustomers())
    monkeypatch.setattr(uqs, "find_purchase_unit", lambda **kw: None)

    res = json.loads(
        wf._handle_import_excel_to_database(
            {"import_type": "products", "file_path": "考勤报表.xlsx", "confirm": True},
            workspace_root=str(tmp_path),
        )
    )
    assert res["success"] is True
    assert res["import_type"] == "attendance_roster"
    assert res["imported"] == 2
    assert res["departments_created"] == 2

    by_name = {r["name"]: r for r in added_products}
    assert by_name["白锐"]["unit"] == "公司-财务部"
    assert by_name["白锐"]["specification"] == "公司-考勤"
    assert by_name["白锐"]["model_number"] == "公司-财务部::白锐"
    assert by_name["白锐"]["price"] == 0.0
    assert {c["customer_name"] for c in created_customers} == {"董事会", "公司-财务部"}


def test_quote_sheet_still_goes_products_path(tmp_path):
    xlsx = tmp_path / "报价单.xlsx"
    _write_quote_style_xlsx(xlsx)

    res = json.loads(
        wf._handle_import_excel_to_database(
            {"import_type": "products", "file_path": "报价单.xlsx", "preview_only": True},
            workspace_root=str(tmp_path),
        )
    )
    assert res["success"] is True
    assert res["import_type"] == "products"
    assert res["row_count"] == 1


def test_explicit_roster_import_type_alias(tmp_path):
    xlsx = tmp_path / "考勤报表.xlsx"
    _write_dingtalk_style_xlsx(xlsx)

    res = json.loads(
        wf._handle_import_excel_to_database(
            {"import_type": "花名册", "file_path": "考勤报表.xlsx", "preview_only": True},
            workspace_root=str(tmp_path),
        )
    )
    assert res["success"] is True
    assert res["import_type"] == "attendance_roster"
    assert res["row_count"] == 2


@pytest.mark.parametrize("import_type", ["employees", "roster", "人员"])
def test_roster_aliases_accepted(tmp_path, import_type):
    xlsx = tmp_path / "考勤报表.xlsx"
    _write_dingtalk_style_xlsx(xlsx)
    res = json.loads(
        wf._handle_import_excel_to_database(
            {"import_type": import_type, "file_path": "考勤报表.xlsx", "preview_only": True},
            workspace_root=str(tmp_path),
        )
    )
    assert res["import_type"] == "attendance_roster"
