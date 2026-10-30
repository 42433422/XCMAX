from io import BytesIO

import pytest
from openpyxl import Workbook

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_formula_support import plan_formula_support


def workbook(values):
    book = Workbook()
    sheet = book.active
    sheet.title = "表"
    for address, value in values.items():
        sheet[address] = value
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def test_dependency_closure_preserves_formula_graph_and_limits_support_to_required_cells():
    body = workbook({"A1": "=B1+C1", "B1": "=D1*2", "C1": 3, "D1": 4, "E1": "无关"})
    result = plan_formula_support(body, [{"sheet": "表", "range": "A1:C1"}])
    assert result["support_cells"] == ["D1"]
    assert result["selected_reference_cells"] == ["B1", "C1"]
    assert result["formula_references"] == {"A1": ["B1", "C1"], "B1": ["D1"]}
    assert "E1" not in result["support_cells"]


def test_cycles_external_refs_unsupported_functions_and_large_ranges_fail_closed():
    part = [{"sheet": "表", "range": "A1:A1"}]
    with pytest.raises(ReviewedExcelError, match="循环"):
        plan_formula_support(workbook({"A1": "=B1", "B1": "=A1"}), part)
    with pytest.raises(ReviewedExcelError, match="外部"):
        plan_formula_support(workbook({"A1": "='[外部.xlsx]表'!A1"}), part)
    with pytest.raises(ReviewedExcelError, match="函数依赖"):
        plan_formula_support(workbook({"A1": '=INDIRECT("B1")'}), part)
    with pytest.raises(ReviewedExcelError, match="范围超出安全预算"):
        plan_formula_support(workbook({"A1": "=SUM(B1:D1)"}), part, max_cells=2)


def test_support_sheet_keeps_only_needed_values_and_links_back_to_editable_main_cells():
    from openpyxl import load_workbook

    from app.application.reviewed_excel_formula_support import install_formula_support

    original = workbook({"A1": "=SUM(B1:D1)", "B1": 2, "C1": 3, "D1": 4, "E1": "不相关"})
    fragments = [{"sheet": "表", "range": "A1:B1"}]
    plan = plan_formula_support(original, fragments)
    assert plan["support_cells"] == ["C1", "D1"] and plan["proxy_cells"] == ["B1"]
    book = load_workbook(BytesIO(original))
    name = install_formula_support(book, plan)
    assert name == "依赖支撑"
    assert book["表"]["A1"].value == "=SUM('依赖支撑'!B1:D1)"
    assert book[name]["B1"].value == "='表'!B1"
    assert book[name]["C1"].value == 3 and book[name]["D1"].value == 4
    assert book[name]["E1"].value is None
    assert book.calculation.fullCalcOnLoad and book.calculation.forceFullCalc
    stream = BytesIO()
    book.save(stream)
    saved = load_workbook(BytesIO(stream.getvalue()))
    assert saved["表"]["A1"].value == "=SUM('依赖支撑'!B1:D1)"
    assert saved[name]["B1"].value == "='表'!B1"
    assert saved[name]["E1"].value is None


def test_actual_derivation_preserves_needed_formula_support_only():
    from openpyxl import load_workbook

    from app.application.reviewed_excel_template import derive_document_workbook

    original = workbook({"A1": "=SUM(B1:D1)", "B1": 2, "C1": 3, "D1": 4, "E1": "不相关"})
    result = derive_document_workbook(original, [{"sheet": "表", "range": "A1:B1"}])
    saved = load_workbook(BytesIO(result), data_only=False)
    assert saved.sheetnames == ["表", "依赖支撑"]
    assert saved["表"]["A1"].value == "=SUM('依赖支撑'!B1:D1)"
    assert saved["依赖支撑"]["B1"].value == "='表'!B1"
    assert saved["依赖支撑"]["C1"].value == 3
    assert saved["依赖支撑"]["D1"].value == 4
    assert saved["依赖支撑"]["E1"].value is None
    assert saved["表"]["C1"].value is None
