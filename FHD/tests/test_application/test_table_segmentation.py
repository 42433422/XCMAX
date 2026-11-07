from __future__ import annotations

from pathlib import Path

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
