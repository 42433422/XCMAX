from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from app.application.elt.parser_shipment_history import ledger_row_verification
from app.application.elt.parser_types import ParsedRow
from app.application.elt.parsers import parse_file
from app.application.elt.table_segmentation import segment_sheet, worksheet_grid


def _segment(ws):
    return segment_sheet(ws.title, *worksheet_grid(ws))


def _roles(segmentation):
    return {item["row"]: item["role"] for item in segmentation.row_roles}


def test_title_form_header_body_total_and_note_are_located():
    wb = Workbook()
    ws = wb.active
    ws.merge_cells("A1:D1")
    ws["A1"] = "示例公司出库单"
    ws.append(["单号：X-1", None, "日期：2026-01-02"])
    ws.append(["品名", "数量", "单价", "金额"])
    for row in (["甲", 2, 3, 6], ["乙", 1, 5, 5], ["丙", 4, 1, 4]):
        ws.append(row)
    ws.append(["合计", 7, None, 15])
    ws.append(["备注：本单据一式两联，签字后生效"])

    segmentation = _segment(ws)

    assert [table.range_ref() for table in segmentation.tables] == ["A3:D6"]
    assert segmentation.tables[0].data_rows == [4, 5, 6]
    roles = _roles(segmentation)
    assert (roles[1], roles[2], roles[7], roles[8]) == ("title", "form_info", "summary", "note")
    assert segmentation.coverage()["unassigned_cells"] == 0
    assert segmentation.coverage()["nonempty_cells"] == len(segmentation.cells)


def test_side_by_side_tables_are_separate():
    wb = Workbook()
    ws = wb.active
    ws.append(["树脂", "数量", "单价", None, "溶剂", "数量", "单价", "备注"])
    for index in range(4):
        ws.append([f"树脂{index}", index + 1, 10, None, f"溶剂{index}", index + 2, 8, "常用"])

    tables = _segment(ws).tables

    assert [(t.min_col, t.max_col, len(t.data_rows)) for t in tables] == [(1, 3, 4), (5, 8, 4)]


def test_merged_parent_header_is_kept_only_over_its_span():
    wb = Workbook()
    ws = wb.active
    ws.merge_cells("C1:D1")
    ws["C1"] = "销售额"
    ws.append([])
    for col, value in enumerate(["日期", "厂名", "油漆厂", "家具厂", "备注"], start=1):
        ws.cell(2, col, value)
    for index in range(3):
        ws.append([f"2026-01-0{index + 1}", "甲厂", 100 + index, 50, ""])

    table = _segment(ws).tables[0]

    assert table.header_paths == [
        ["日期"],
        ["厂名"],
        ["销售额", "油漆厂"],
        ["销售额", "家具厂"],
        ["备注"],
    ]


def _monthly_blocks(ws):
    for month in (1, 2):
        ws.append([f"2026年{month}月出货"])
        ws.append(["日期", "单号", "品名", "金额"])
        for day in range(1, 4):
            ws.append([f"2026-0{month}-0{day}", f"N{month}{day}", "白漆", day * 10])


def test_repeated_monthly_headers_are_not_business_rows(tmp_path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "出货"
    _monthly_blocks(ws)
    path = tmp_path / "monthly.xlsx"
    wb.save(path)

    segmentation = _segment(ws)
    assert len(segmentation.groups()) == 1
    assert [table.repeated for table in segmentation.tables] == [False, True]
    assert _roles(segmentation)[7] == "repeated_header"

    dataset = parse_file(path, target_type="shipment_records")
    rows = list(dataset.rows)
    assert {row.row_number for row in rows} == {3, 4, 5, 8, 9, 10}
    excluded = {item["row"]: item["role"] for item in dataset.source_features["excluded_rows"]}
    assert excluded == {6: "title", 7: "repeated_header"}


def test_calendar_attendance_yields_one_row_per_employee_month(tmp_path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "考勤"
    # 2026-05-01 is a Friday; weekday index matches the attendance matrix parser.
    weekdays = "一二三四五六日"
    for month, first_weekday, days in ((5, 4, 31), (6, 0, 30)):
        ws.append([f"示例公司2026年{month}月考勤表"])
        ws.append([None, None, *[weekdays[(first_weekday + day) % 7] for day in range(days)]])
        ws.append([None, None, *range(1, days + 1)])
        for name in ("张三", "李四"):
            ws.append([name, None, "✔", "✘"])
        ws.append(["说明：食堂费用已于月底结清"])
    path = tmp_path / "attendance.xlsx"
    wb.save(path)

    dataset = parse_file(path, target_type="attendance")
    rows = list(dataset.rows)

    assert [(row.values["employee_name"], row.values["work_month"]) for row in rows] == [
        ("张三", "2026-05"),
        ("李四", "2026-05"),
        ("张三", "2026-06"),
        ("李四", "2026-06"),
    ]
    assert len({row.values["business_id"] for row in rows}) == 4
    assert rows[0].values["present_marked_dates"] == "2026-05-01"
    assert rows[0].values["absent_dates"] == "2026-05-02"
    assert "食堂费用" in rows[0].values["month_notes"]
    assert all("说明" not in row.values["employee_name"] for row in rows)


def test_ledger_verification_lists_every_row_and_requires_confirmation():
    rows = [
        ParsedRow(
            sheet="台账",
            row_number=index,
            values={"customer_name": "", "name": f"品{index}"},
            provenance={
                "original_fragment": {"quantity_kg": 10, "price": 2, "amount": 20 + index % 2},
                "customer_unresolved": True,
            },
        )
        for index in range(1, 6)
    ]
    state = {id(rows[0]): "duplicate_of_delivery_note"}

    result = ledger_row_verification(rows, state, written_rows=1, target_type="shipment_records")

    assert result["total_rows"] == 5 and result["confirmation_required"]
    assert result["status_counts"] == {
        "duplicate_of_delivery_note": 1,
        "superseded_by_newer_record": 4,
    }
    assert [r["amount_consistent"] for r in result["rows"]] == [False, True, False, True, False]
    assert result["customer_unresolved_rows"] == 5


def test_business_names_containing_total_words_are_not_excluded():
    wb = Workbook()
    ws = wb.active
    ws.append(["客户名称", "数量", "金额"])
    ws.append(["合计科技", 2, 10])
    ws.append(["汇总服务", 3, 15])
    ws.append(["合计", 5, 25])
    result = _segment(ws)
    assert result.tables[0].data_rows == [2, 3]
    assert _roles(result)[4] == "summary"


def test_indented_parallel_tables_keep_source_columns(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append([None, None, "客户名称", "数量", "金额", None, "客户名称", "数量", "金额"])
    ws.append([None, None, "甲", 2, 10, None, "乙", 3, 15])
    path = tmp_path / "indented.xlsx"
    wb.save(path)
    dataset = parse_file(path, target_type="customers")
    try:
        rows = list(dataset.rows)
        assert len(rows) == 2
        assert [row.provenance["columns"]["客户名称"] for row in rows] == [3, 7]
        assert [row.values["客户名称"] for row in rows] == ["甲", "乙"]
    finally:
        dataset.rows.close()


def test_parallel_slice_row_keeps_each_review_status():
    from io import BytesIO

    from app.application.reviewed_excel_auto_slice import rule_row_dispositions

    wb = Workbook()
    ws = wb.active
    ws.append(["甲", 1, None, "乙", 2])
    body = BytesIO()
    wb.save(body)
    slices = [
        {
            "fragments": [{"sheet": ws.title, "range": "A1:B1"}],
            "status": "identified",
            "slice_id": "left",
        },
        {
            "fragments": [{"sheet": ws.title, "range": "D1:E1"}],
            "status": "pending_review",
            "slice_id": "right",
            "review_reason": "需复核",
        },
    ]
    rows = rule_row_dispositions(body.getvalue(), {"sheets": []}, slices)
    assert rows[0]["status"] == "pending_review"
    assert [(p["slice_id"], p["status"]) for p in rows[0]["parts"]] == [
        ("left", "import"),
        ("right", "pending_review"),
    ]


@pytest.mark.parametrize(
    "headers,values",
    [
        (["客户名称", "数量"], ["说明科技", 2]),
        (["客户名称", "数量"], ["备注材料", 3]),
        (
            ["客户名称", "地址"],
            ["甲公司", "某省某市某区某街道某工业园区第十二栋第三单元二楼办公室" * 2],
        ),
        (["客户名称", "地址"], ["一个超过十二个字符的完整合法客户名称", None]),
    ],
)
def test_business_text_is_not_silently_disposed_as_note(headers, values, tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    ws.append(values)
    result = _segment(ws)
    assert result.tables[0].data_rows == [2]
    assert _roles(result)[2] == "data"
    assert result.coverage()["unassigned_cells"] == 0
    path = tmp_path / "synthetic-customer.xlsx"
    wb.save(path)
    dataset = parse_file(path, target_type="customers")
    try:
        rows = list(dataset.rows)
        assert len(rows) == 1
        assert rows[0].values["客户名称"] == values[0]
        if values[1] is not None:
            assert rows[0].values[headers[1]] == values[1]
    finally:
        dataset.rows.close()


def test_explicit_note_label_still_excludes_footer_without_excluding_business_name():
    wb = Workbook()
    ws = wb.active
    ws.append(["客户名称", "地址"])
    ws.append(["说明科技", "某街道"])
    ws.append(["备注", "本页仅供核对"])
    result = _segment(ws)
    assert result.tables[0].data_rows == [2]
    assert _roles(result)[3] == "note"


def test_long_text_record_between_other_business_records_is_preserved(tmp_path):
    wb = Workbook()
    ws = wb.active
    address = "这是一个正常但超过三十个字的客户收货地址北京市朝阳区某某道路第一号楼五层"
    ws.append(["客户名称", "联系人", "地址"])
    ws.append(["甲公司", "张三", "上海"])
    ws.append(["乙公司", "李四", address])
    ws.append(["丙公司", "王五", "深圳"])
    result = _segment(ws)
    assert result.tables[0].data_rows == [2, 3, 4]
    assert _roles(result)[3] == "data"
    path = tmp_path / "long-address.xlsx"
    wb.save(path)
    dataset = parse_file(path, target_type="customers")
    try:
        rows = list(dataset.rows)
        assert [row.values["客户名称"] for row in rows] == ["甲公司", "乙公司", "丙公司"]
        assert rows[1].values["地址"] == address
    finally:
        dataset.rows.close()
