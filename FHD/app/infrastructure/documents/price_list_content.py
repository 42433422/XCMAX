"""Text normalization and header detection for price-list Word exports."""

from __future__ import annotations

from typing import Any


def format_price_cell(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
        if abs(number - round(number)) < 1e-9:
            return str(int(round(number)))
        return f"{number:.2f}"
    except (TypeError, ValueError):
        return str(value)


def replace_placeholders_in_paragraphs(doc: Any, mapping: dict[str, str]) -> None:
    def replace(text: str) -> str:
        for key, value in mapping.items():
            text = text.replace(key, value)
        return text

    keys = tuple(mapping.keys())

    def fix_paragraph(paragraph: Any) -> None:
        text = (
            "".join(run.text for run in paragraph.runs)
            if paragraph.runs
            else (paragraph.text or "")
        )
        if not text or not any(key in text for key in keys):
            return
        merged = replace(text)
        paragraph.clear()
        if merged:
            paragraph.add_run(merged)

    for paragraph in doc.paragraphs:
        fix_paragraph(paragraph)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    fix_paragraph(paragraph)


def product_row_cell_values(product: dict[str, Any]) -> list[str]:
    model = str(product.get("model_number") or product.get("型号") or "")
    name = str(product.get("name") or product.get("产品名称") or product.get("名称") or "")
    specification = str(
        product.get("specification") or product.get("spec") or product.get("规格") or ""
    )
    price = format_price_cell(
        product.get("price") or product.get("单价") or product.get("unit_price")
    )
    return [model, name, specification, price]


def row_keyword_score(row_cells: Any) -> int:
    blob = "".join((cell.text or "") for cell in row_cells)
    keywords = (
        "型号",
        "名称",
        "规格",
        "单价",
        "数量",
        "金额",
        "产品",
        "序号",
        "单位",
        "售价",
        "定价",
    )
    return sum(1 for keyword in keywords if keyword in blob)


def detect_header_row_count(table: Any) -> int:
    if len(table.rows) < 2:
        return 1
    first_score = row_keyword_score(table.rows[0].cells)
    second_score = row_keyword_score(table.rows[1].cells)
    return 2 if second_score >= 2 and second_score > first_score else 1
