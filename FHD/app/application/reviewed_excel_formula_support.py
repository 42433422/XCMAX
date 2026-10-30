"""Plan a bounded, source-coordinate formula dependency closure without changing Excel."""

import hashlib
import re
import warnings
from io import BytesIO

from openpyxl import load_workbook
from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string, get_column_letter

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import bounded_range

_SAFE_FUNCTIONS = {"SUM", "AVERAGE", "MIN", "MAX", "ROUND", "IF", "IFERROR", "COUNT", "COUNTA"}
_CELL_RANGE = re.compile(r"\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?\Z")


def plan_formula_support(body: bytes, fragments: list[dict], *, max_cells: int = 20_000) -> dict:
    """Find required same-sheet cells and dependencies; do not rewrite or export a workbook.

    References to other sheets, external files, names, dynamic or unsupported
    functions are explicitly rejected until they can be preserved and verified.
    """
    if not fragments or len(fragments) > 20 or not 1 <= max_cells <= 20_000:
        raise ReviewedExcelError("公式依赖规划范围无效")
    if any(not isinstance(part, dict) or set(part) != {"sheet", "range"} for part in fragments):
        raise ReviewedExcelError("公式依赖片段无效")
    sheets = {part["sheet"] for part in fragments}
    if len(sheets) != 1:
        raise ReviewedExcelError("跨工作表文档暂不能验证")
    from app.application.reviewed_excel_template import inspect_workbook

    info = inspect_workbook(body)
    from app.application.reviewed_excel_template import _read_only_print_area_warnings

    with warnings.catch_warnings(record=True) as found:
        warnings.simplefilter("always")
        book = load_workbook(BytesIO(body), data_only=False, keep_links=True, rich_text=True)
    if found and _read_only_print_area_warnings(body, found) != info["read_only_print_areas"]:
        book.close()
        raise ReviewedExcelError("打印区域来源校验失败")
    try:
        sheet_name = next(iter(sheets))
        if sheet_name not in book.sheetnames:
            raise ReviewedExcelError("公式依赖来源工作表不存在")
        sheet = book[sheet_name]
        rectangles: list[tuple[int, int, int, int]] = []
        for part in fragments:
            try:
                bounds = bounded_range(part["range"])
                c1, r1, c2, r2 = bounds
                if not (1 <= c1 <= c2 <= sheet.max_column and 1 <= r1 <= r2 <= sheet.max_row):
                    raise ValueError("bounds")
            except (TypeError, ValueError):
                raise ReviewedExcelError("公式依赖片段坐标无效") from None
            rectangles.append(bounds)

        def selected(col: int, row: int) -> bool:
            return any(c1 <= col <= c2 and r1 <= row <= r2 for c1, r1, c2, r2 in rectangles)

        pending = [
            cell.coordinate
            for row in sheet.iter_rows()
            for cell in row
            if cell.data_type == "f"
            and isinstance(cell.column, int)
            and isinstance(cell.row, int)
            and selected(cell.column, cell.row)
        ]
        visited: set[str] = set()
        references: dict[str, list[str]] = {}
        outside: set[str] = set()
        inside: set[str] = set()
        proxies: set[str] = set()
        edges: dict[str, set[str]] = {}
        while pending:
            address = pending.pop()
            if address in visited:
                continue
            visited.add(address)
            value = sheet[address].value
            try:
                tokens = Tokenizer(value).items
            except (TypeError, TokenizerError):
                raise ReviewedExcelError("公式无法静态解析") from None
            direct = []
            edges[address] = set()
            for token in tokens:
                if token.type == "OPERAND" and token.subtype == "ERROR":
                    raise ReviewedExcelError("公式含错误引用")
                if (
                    token.type == "FUNC"
                    and token.subtype == "OPEN"
                    and token.value[:-1].upper() not in _SAFE_FUNCTIONS
                ):
                    raise ReviewedExcelError("公式函数依赖尚无法保真")
                if token.type != "OPERAND" or token.subtype != "RANGE":
                    continue
                target = token.value
                if "!" in target or "[" in target:
                    raise ReviewedExcelError("跨工作表或外部公式依赖尚无法保真")
                if not _CELL_RANGE.fullmatch(target):
                    raise ReviewedExcelError("公式含名称或动态范围，暂不能保真")
                c1, r1, c2, r2 = bounded_range(target.replace("$", ""))
                if not (c1 <= c2 and r1 <= r2) or (c2 - c1 + 1) * (r2 - r1 + 1) > max_cells:
                    raise ReviewedExcelError("单个公式引用范围超出安全预算")
                direct.append(target)
                selected_refs: set[str] = set()
                includes_support = False
                for row in range(r1, r2 + 1):
                    for col in range(c1, c2 + 1):
                        ref = f"{get_column_letter(col)}{row}"
                        if selected(col, row):
                            inside.add(ref)
                            selected_refs.add(ref)
                        else:
                            outside.add(ref)
                            includes_support = True
                        if len(inside) + len(outside) > max_cells:
                            raise ReviewedExcelError("公式依赖总量超出安全预算")
                        if sheet[ref].data_type == "f":
                            edges[address].add(ref)
                            if ref not in visited:
                                pending.append(ref)
                source_col, source_row = coordinate_from_string(address)
                if includes_support or not selected(
                    column_index_from_string(source_col), source_row
                ):
                    proxies.update(selected_refs)
            references[address] = direct
        done: set[str] = set()
        for start in edges:
            if start in done:
                continue
            visiting: set[str] = set()
            stack = [(start, False)]
            while stack:
                node, leaving = stack.pop()
                if leaving:
                    visiting.remove(node)
                    done.add(node)
                    continue
                if node in visiting:
                    raise ReviewedExcelError("公式引用存在循环，暂不能保真")
                if node in done:
                    continue
                visiting.add(node)
                stack.append((node, True))
                stack.extend((child, False) for child in edges.get(node, set()))
        return {
            "source_sha256": hashlib.sha256(body).hexdigest(),
            "sheet": sheet_name,
            "fragments": fragments,
            "formula_references": references,
            "support_cells": sorted(outside),
            "selected_reference_cells": sorted(inside),
            "proxy_cells": sorted(proxies),
        }
    finally:
        book.close()


def install_formula_support(book, plan: dict) -> str | None:
    """Install only planned support cells in memory; caller validates and saves the workbook.

    Selected references in a support range become formulas pointing at the
    editable main sheet, rather than frozen copies of the selected values.
    """
    from copy import copy

    from openpyxl.utils.cell import quote_sheetname

    support_cells = plan["support_cells"]
    if not support_cells:
        return None
    sheet = book[plan["sheet"]]
    title = "依赖支撑"
    number = 1
    while title in book.sheetnames:
        number += 1
        title = f"依赖支撑_{number}"
    support = book.create_sheet(title)
    for address in support_cells:
        source = sheet[address]
        if source.hyperlink or source.comment:
            raise ReviewedExcelError("公式支撑单元格含未验证的链接或批注")
        target = support[address]
        target.value = source.value
        target._style = copy(source._style)
    for address in plan["proxy_cells"]:
        source = sheet[address]
        target = support[address]
        target.value = f"={quote_sheetname(sheet.title)}!{address}"
        target._style = copy(source._style)
    rectangles = [bounded_range(item["range"]) for item in plan["fragments"]]

    def selected(col, row):
        return any(c1 <= col <= c2 and r1 <= row <= r2 for c1, r1, c2, r2 in rectangles)

    for address in plan["formula_references"]:
        source = sheet[address]
        if not selected(source.column, source.row):
            continue
        tokens = Tokenizer(source.value).items
        changed = False
        for token in tokens:
            if token.type != "OPERAND" or token.subtype != "RANGE":
                continue
            c1, r1, c2, r2 = bounded_range(token.value.replace("$", ""))
            if any(
                not selected(col, row) for row in range(r1, r2 + 1) for col in range(c1, c2 + 1)
            ):
                token.value = f"{quote_sheetname(title)}!{token.value}"
                changed = True
        if changed:
            source.value = "=" + "".join(token.value for token in tokens)
    if book.calculation is None:
        from openpyxl.workbook.properties import CalcProperties

        book.calculation = CalcProperties()
    book.calculation.fullCalcOnLoad = True
    book.calculation.forceFullCalc = True
    return title
