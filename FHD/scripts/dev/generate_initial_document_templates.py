#!/usr/bin/env python3
"""重新生成 resources/templates 下的开箱演示模板（发货单 xlsx + 价格表 docx）。"""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_shipment_xlsx(path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "送货单"
    thin = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    ws["A1"] = "XCMAX 演示送货单"
    ws["A1"].font = Font(name="宋体", size=16, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells("A1:J1")
    ws["A2"] = "购货单位：{{购买单位}}       联系人：              {{日期}}      订单编号："
    ws.merge_cells("A2:J2")
    headers = [
        (1, "产品型号"),
        (4, "产品名称"),
        (5, "数量/件"),
        (6, "规格/KG"),
        (7, "数量/KG"),
        (8, "单价/元"),
        (9, "金额/元"),
        (10, "备注"),
    ]
    for col, text in headers:
        cell = ws.cell(row=3, column=col, value=text)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    for row in range(4, 15):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        for col in range(1, 11):
            ws.cell(row=row, column=col).border = thin
    ws["A15"] = "合计"
    ws.merge_cells("A15:D15")
    ws["E15"] = "=SUM(E4:E14)"
    ws["G15"] = "=SUM(G4:G14)"
    ws["I15"] = "=SUM(I4:I14)"
    ws["A16"] = "大写人民币："
    ws.merge_cells("A16:C16")
    ws["A18"] = "收货人签收："
    ws.merge_cells("A18:E18")
    ws["F18"] = "送货人："
    ws.merge_cells("F18:J18")
    for col, width in {
        "A": 12,
        "B": 8,
        "C": 8,
        "D": 22,
        "E": 10,
        "F": 10,
        "G": 10,
        "H": 10,
        "I": 12,
        "J": 12,
    }.items():
        ws.column_dimensions[col].width = width
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def build_price_list_docx(path: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin = Cm(1.8)
        section.right_margin = Cm(1.8)
    title = doc.add_paragraph("产品价格表")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.runs[0]
    run.font.size = Pt(18)
    run.font.bold = True
    run.font.name = "宋体"
    doc.add_paragraph("客户：{{客户}}　　报价日期：{{报价日期}}")
    table = doc.add_table(rows=3, cols=4)
    table.style = "Table Grid"
    for i, h in enumerate(["型号", "名称", "规格", "单价"]):
        table.rows[0].cells[i].text = h
    for r, sample in enumerate(
        (("DEMO-001", "演示产品A", "28", "12.5"), ("DEMO-002", "演示产品B", "20", "9.8")),
        start=1,
    ):
        for c, val in enumerate(sample):
            table.rows[r].cells[c].text = val
    foot = doc.add_paragraph(
        "说明：本表为 XCMAX 开箱演示模板，可在模板库中替换为企业自有版式。"
    )
    foot.runs[0].font.size = Pt(9)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def main() -> None:
    out = _repo_root() / "resources" / "templates"
    ship = out / "发货单模板.xlsx"
    alias = out / "尹玉华1.xlsx"
    price = out / "price_list_default.docx"
    build_shipment_xlsx(ship)
    alias.write_bytes(ship.read_bytes())
    build_price_list_docx(price)
    print(f"wrote {ship}")
    print(f"wrote {alias}")
    print(f"wrote {price}")


if __name__ == "__main__":
    main()
