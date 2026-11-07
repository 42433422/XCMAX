"""Formula text stays separate from the cached value, and phantom columns do not hide rows."""

from io import BytesIO
from zipfile import ZipFile

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.formula import ArrayFormula

from app.application.reviewed_excel_template import inspect_workbook


def _save(book: Workbook) -> bytes:
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def _inject(body: bytes, old: str, new: str) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(body)) as source, ZipFile(output, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = data.replace(old.encode(), new.encode(), 1)
            target.writestr(item, data)
    return output.getvalue()


def test_formula_keeps_text_and_cache_and_marks_a_missing_cache():
    book = Workbook()
    sheet = book.active
    sheet.title = "公式"
    sheet["A1"] = 2
    sheet["A2"] = 3
    sheet["A3"] = "=A1+A2"
    sheet["A4"] = "=SUM(A1:A2)"
    sheet["C1"] = ArrayFormula("C1", "=A1+A2")
    body = _inject(_save(book), "<f>A1+A2</f>", "<f>A1+A2</f><v>5</v>")
    review = inspect_workbook(body)
    cells = {cell["cell"]: cell for cell in review["cells"] if cell["kind"] == "formula"}

    assert cells["A3"]["value"] == "=A1+A2"
    assert cells["A3"]["cached_value"] == "5"
    assert cells["A3"]["cache_missing"] is False
    assert cells["A4"]["value"] == "=SUM(A1:A2)"
    assert cells["A4"]["cached_value"] is None
    assert cells["A4"]["cache_missing"] is True
    assert cells["A4"]["reason"] == "公式保留；缺失缓存"
    assert cells["C1"]["value"] == "=A1+A2"
    assert "object at" not in cells["C1"]["value"]


def test_formula_on_merged_member_and_phantom_column_are_both_read():
    book = Workbook()
    sheet = book.active
    sheet.title = "业务"
    sheet["A1"] = "表头"
    sheet.merge_cells("A1:B1")
    sheet["A20"] = "可见业务行"
    sheet["B20"] = "HIDDEN_ROW_OK"
    sheet.row_dimensions[20].hidden = True
    # A styled empty cell in column XFD used to inflate the used range and
    # hide later business rows behind header-only sampling.
    sheet.cell(1, 16384).font = Font(bold=True)
    body = _inject(
        _save(book),
        'r="A1"',
        'r="B1"><f>SUM(A20)</f><v>6630</v></c><c r="A1"',
    )
    review = inspect_workbook(body)
    cells = {cell["cell"]: cell for cell in review["cells"]}

    assert review["structural_sample_sheets"] == []
    assert cells["A20"]["value"] == "可见业务行"
    assert cells["B20"]["value"] == "HIDDEN_ROW_OK"
    assert cells["B1"]["kind"] == "formula"
    assert cells["B1"]["value"] == "=SUM(A20)"
    assert cells["B1"]["cached_value"] == "6630"
    assert cells["B1"]["cache_missing"] is False
    assert review["sheet_overview"][0]["columns"] == 16384
    assert 20 in review["sheet_overview"][0]["hidden_rows"]
