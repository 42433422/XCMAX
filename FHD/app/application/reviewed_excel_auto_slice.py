"""Extract model-grouped documents from a previously validated classification result."""

import logging
import re

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

logger = logging.getLogger(__name__)

# One extra model turn for export obstacles. Anything else still stops the file.
_COMPATIBILITY_MARKERS = (
    "过滤条件",
    "过滤器跨界",
    "区域规则无法保真提取",
    "公式无法静态解析",
    "公式函数依赖",
    "派生公式写出后核验失败",
    "支撑数据写出后核验失败",
    "SUBTOTAL",
    "模型区域之外",
)

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import bounded_range
from app.application.reviewed_excel_legacy import ensure_slice_workbook
from app.application.reviewed_excel_template import derive_document_workbook, inspect_workbook
from app.utils.operational_errors import BOUNDARY_ERRORS


def _slice_filename(
    fragments: list[dict], cells: list[dict], used: set[str], reason: str = ""
) -> str:
    """Prefer a Chinese descriptive title from cells; else sheet + short reason (no A1-range codes)."""
    title = ""
    for part in fragments:
        c1, r1, c2, r2 = bounded_range(part["range"])
        for cell in cells:
            if cell["sheet"] != part["sheet"]:
                continue
            col, row = coordinate_from_string(cell["cell"])
            value = cell["value"].strip()
            if (
                c1 <= column_index_from_string(col) <= c2
                and r1 <= row <= min(r2, r1 + 3)
                and len(value) <= 40
                and re.fullmatch(r"[\u4e00-\u9fff\w（）()\- ]*(?:单|表|清单|记录)", value)
            ):
                title = value
                break
        if title:
            break
    if not title:
        raw_sheet = (fragments[0].get("sheet") if fragments else "") or ""
        # Only keep sheet names that already carry Chinese descriptive text.
        sheet = raw_sheet if any("一" <= ch <= "鿿" for ch in raw_sheet) else ""
        ym = re.search(r"(20\d{2}\s*年\s*\d{1,2}\s*月)", reason or "")
        short = re.sub(r"\s+", "", ym.group(1)) if ym else ""
        if not short and reason:
            clause = re.split(r"[，。；;]", reason)[0]
            clause = re.sub(r"[A-Za-z].*", "", clause).strip()
            short = clause[:24] if any("一" <= ch <= "鿿" for ch in clause) else ""
        if sheet and short and short not in sheet and sheet not in short:
            title = f"{sheet}_{short}"
        else:
            title = short or sheet or "切片"
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip(" ._")[:40] or "切片"
    if title.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        title = "切片"
    # At most len(used) candidate names can be occupied; the next one is free.
    # Keep the allocation explicitly bounded for review and denial-of-service safety.
    for number in range(1, len(used) + 2):
        name = f"{title}_{number}.xlsx" if title == "切片" or number > 1 else f"{title}.xlsx"
        if name.casefold() not in used:
            used.add(name.casefold())
            return name
    raise ReviewedExcelError("无法分配唯一切片文件名")


def _model_region_for_fragment(known: dict[tuple[str, str], dict], fragment: dict) -> dict:
    """Resolve a verified fragment to the model region that contains it.

    verify_after_cut may resplit one model region into smaller documents, so an exact
    range lookup is not sufficient; every fragment must still stay inside a model region.
    """
    sheet = fragment.get("sheet")
    c1, r1, c2, r2 = bounded_range(fragment["range"])
    for (region_sheet, region_range), region in known.items():
        if region_sheet != sheet:
            continue
        kc1, kr1, kc2, kr2 = bounded_range(region_range)
        if kc1 <= c1 and c2 <= kc2 and kr1 <= r1 and r2 <= kr2:
            return region
    raise ReviewedExcelError("切后复核产生了模型区域之外的片段，不能保证保真提取")


_HIDDEN_REASON = "隐藏工作表（附表/台账），未经确认不排除；已生成复核副本，需人工确认去向"


def _review_copy(sources: dict, body: bytes, fragment: dict, reason: str) -> bytes:
    """Value copy of one region at source coordinates for manual review."""
    return _review_document(sources, body, [fragment], reason)


def _review_document(sources: dict, body: bytes, fragments: list[dict], reason: str) -> bytes:
    """Value copy of one document's regions. A hidden sheet stays for a person to confirm."""
    from io import BytesIO

    from openpyxl import Workbook, load_workbook

    sheet_name = str(fragments[0]["sheet"])
    if any(str(item.get("sheet")) != sheet_name for item in fragments):
        raise ReviewedExcelError("跨工作表文档暂不能保证保真")
    if not sources:
        sources["values"] = load_workbook(BytesIO(body), data_only=True)
        sources["formulas"] = load_workbook(BytesIO(body), data_only=False)
    values = sources["values"][sheet_name]
    formulas = sources["formulas"][sheet_name]
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = sheet_name[:31]
    for fragment in fragments:
        c1, r1, c2, r2 = bounded_range(fragment["range"])
        for row in range(r1, r2 + 1):
            for column in range(c1, c2 + 1):
                value = values.cell(row, column).value
                if value is None:
                    value = formulas.cell(row, column).value
                if value is None or value == "":
                    continue
                cell = sheet.cell(row, column, value)
                if isinstance(value, str):
                    cell.data_type = "s"
        for merged in formulas.merged_cells.ranges:
            if (
                c1 <= merged.min_col <= merged.max_col <= c2
                and r1 <= merged.min_row <= merged.max_row <= r2
            ):
                sheet.merge_cells(str(merged))
    note = book.create_sheet("切片复核说明")
    note.append(["来源工作表", sheet_name])
    note.append(["来源范围", "；".join(str(item["range"]) for item in fragments)])
    note.append(["状态", "待人工确认"])
    note.append(["原因", reason[:500]])
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def derive_rule_slices(body: bytes, latest: dict) -> list[dict]:
    """Identify sheet regions before any model call. Slices carry no business id.

    Hidden and veryHidden sheets are omitted. Visible regions the faithful
    extractor cannot export keep a value review copy with ``status="pending_review"``.
    """
    source = inspect_workbook(body)
    results: list[dict] = []
    used_names: set[str] = set()
    copy_sources: dict = {}
    sheets = latest.get("sheets")
    if not isinstance(sheets, list):
        return results
    try:
        for sheet in sheets:
            if not isinstance(sheet, dict) or sheet.get("blank"):
                continue
            hidden = sheet.get("sheet_state", "visible") != "visible"
            for region in sheet.get("regions") or []:
                if not isinstance(region, dict) or region.get("data_region") is False:
                    continue
                if hidden or sheet.get("processable") is False:
                    continue
                results.append(
                    _rule_slice(body, source, sheet, region, False, used_names, copy_sources)
                )
    finally:
        for book in copy_sources.values():
            book.close()
    return results


def _rule_slice(body, source, sheet, region, hidden, used_names, copy_sources) -> dict:
    fragment = {"sheet": sheet.get("sheet"), "range": region.get("range")}
    record = {
        "fragments": [fragment],
        "basis": "rule_region",
        "confirmed": False,
        "source_sha256": source["sha256"],
        "slice_id": f"{source['sha256'][:12]}:{fragment['sheet']}:{fragment['range']}",
        "template_type": (sheet.get("labels") or ["unknown"])[0],
        "table_region": fragment["range"],
        "original_row_range": fragment["range"],
        "status": "identified",
        "error": None,
        "review_reason": "",
    }
    reason = _HIDDEN_REASON if hidden else ""
    if not hidden:
        try:
            record["workbook"] = derive_document_workbook(
                body, [fragment], print_area_mode="source"
            )
        except ReviewedExcelError as exc:
            record["error"] = str(exc)
            reason = f"自动保真提取未通过：{exc}；已生成复核副本，需人工确认去向"
    if reason:
        record["status"] = "pending_review"
        record["review_reason"] = reason
        record["workbook"] = _review_copy(copy_sources, body, fragment, reason)
    elif not region.get("header_cells") and set(region.get("labels") or ["unknown"]) == {"unknown"}:
        record["status"] = "pending_review"
        record["review_reason"] = "未识别的业务区域（无可识别表头或单据类型），需人工复核"
    record["filename"] = _slice_filename(
        [fragment], source["cells"], used_names, reason=str(fragment["range"])
    )
    if "business_id" in record:
        raise ReviewedExcelError("切片阶段不能生成业务主键")
    return record


def rule_row_dispositions(body: bytes, latest: dict, slices: list[dict]) -> list[dict]:
    """One outcome per non-empty source row: import, pending_review or rejected, with reason."""
    from io import BytesIO

    from openpyxl import load_workbook

    owners: dict[str, list[tuple[int, int, int, int, dict]]] = {}
    for item in slices:
        part = item["fragments"][0]
        c1, r1, c2, r2 = bounded_range(part["range"])
        owners.setdefault(part["sheet"], []).append((c1, r1, c2, r2, item))
    notes: dict[str, list[tuple[int, int, str]]] = {}
    sheet_messages: dict[str, str] = {}
    for sheet in latest.get("sheets") or []:
        if not isinstance(sheet, dict):
            continue
        sheet_name = str(sheet.get("sheet") or "")
        if not sheet_name:
            continue
        sheet_messages[sheet_name] = sheet.get("processing_message") or ""
        for region in sheet.get("regions") or []:
            if isinstance(region, dict) and region.get("data_region") is False:
                _c1, r1, _c2, r2 = bounded_range(region["range"])
                notes.setdefault(sheet_name, []).append(
                    (r1, r2, region.get("anomaly_reason") or "标题或说明")
                )
    book = load_workbook(BytesIO(body), read_only=True, data_only=False)
    results: list[dict] = []
    try:
        for ws in book.worksheets:
            if (ws.sheet_state or "visible") != "visible":
                continue
            # Stored dimensions can understate the used range; scan the whole sheet.
            ws.reset_dimensions()
            for row_number, values in enumerate(ws.iter_rows(values_only=True), start=1):
                if all(value is None or value == "" for value in values):
                    continue
                parts = []
                covered: set[int] = set()
                for c1, r1, c2, r2, item in owners.get(ws.title, []):
                    if not r1 <= row_number <= r2 or not any(
                        value not in (None, "") for value in values[c1 - 1 : c2]
                    ):
                        continue
                    covered.update(range(c1, c2 + 1))
                    status = (
                        "rejected"
                        if item.get("error")
                        else ("import" if item["status"] == "identified" else "pending_review")
                    )
                    parts.append(
                        {
                            "columns": [c1, c2],
                            "slice_id": item["slice_id"],
                            "status": status,
                            "reason": item.get("review_reason")
                            or item.get("error")
                            or "位于已识别数据切片，确认模板后导入",
                        }
                    )
                uncovered = [
                    c
                    for c, value in enumerate(values, 1)
                    if value not in (None, "") and c not in covered
                ]
                if uncovered and parts:
                    parts.extend(
                        {
                            "columns": [column, column],
                            "slice_id": None,
                            "status": "pending_review",
                            "reason": "切片之外的内容需人工复核",
                        }
                        for column in uncovered
                    )
                note = next(
                    (text for r1, r2, text in notes.get(ws.title, []) if r1 <= row_number <= r2),
                    None,
                )
                if parts:
                    status = (
                        "rejected"
                        if any(p["status"] == "rejected" for p in parts)
                        else "pending_review"
                        if any(p["status"] == "pending_review" for p in parts)
                        else "import"
                    )
                    reason = "；".join(dict.fromkeys(p["reason"] for p in parts))
                elif note is not None:
                    status, reason = "pending_review", f"{note}，未经确认不排除"
                else:
                    message = sheet_messages.get(ws.title) or "未识别为数据区域"
                    status, reason = "pending_review", f"{message}；需人工复核去向"
                results.append(
                    {
                        "sheet": ws.title,
                        "row": row_number,
                        "status": status,
                        "reason": reason,
                        "slice_id": parts[0]["slice_id"] if len(parts) == 1 else None,
                        "parts": parts,
                    }
                )
    finally:
        book.close()
    return results


# Same ceiling as one classification's model calls. Each round sees the last failure.
_COMPATIBILITY_ROUNDS = 4


def _range_inside(c1: int, r1: int, c2: int, r2: int, allowed: list[str]) -> bool:
    for area in allowed:
        try:
            a1, b1, a2, b2 = bounded_range(area)
        except (TypeError, ValueError):
            continue
        if a1 <= c1 and c2 <= a2 and b1 <= r1 and r2 <= b2:
            return True
    return False


def _compatibility_revision(fragments, message, overview, owner_id, earlier, allowed=None):
    """One model turn for this sheet. None means stop this document."""
    from app.application.reviewed_excel_template import _template_llm_complete

    sheet_name = str(fragments[0]["sheet"])
    sheet = next((item for item in overview if item.get("sheet") == sheet_name), {})
    ranges = ", ".join(str(part["range"]) for part in fragments)
    filt = str(sheet.get("auto_filter_ref") or "无")
    history = "\n".join(earlier) or "无"
    limit = ""
    if allowed:
        limit = "新矩形必须完整落在这些模型区域之内，不要伸出：" + "、".join(allowed) + "。"
    messages = [
        {
            "role": "user",
            "content": (
                "这一张表还不能保真导出。只判断这一张表，不要重复已经失败的范围。\n"
                f"工作表：{sheet_name}。状态：{sheet.get('sheet_state') or 'visible'}。\n"
                f"当前范围：{ranges}。筛选区域：{filt}。\n"
                f"本轮障碍：{message}\n"
                f"此前各轮：\n{history}\n"
                "能切就返回新的矩形，把导出依赖放进这些矩形，不要并进无关内容。"
                + limit
                + "不该切则 can_slice 为 false 且 ranges 为空。"
                "顶层只能有 can_slice 和 ranges，ranges 是矩形字符串，不要再包一层。"
            ),
        }
    ]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["can_slice", "ranges"],
        "properties": {
            "can_slice": {"type": "boolean"},
            "ranges": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
        },
    }
    try:
        result = _template_llm_complete(messages, schema, 800, owner_id=owner_id)
    except BOUNDARY_ERRORS as exc:
        logger.info("compatibility round failed")
        text = str(exc)
        if "未自动重试" in text or "结果状态未知" in text:
            return "stop"
        return "again"
    if not getattr(result, "used_llm", False) or getattr(result, "degraded", False):
        return "stop"
    payload = result.data if isinstance(getattr(result, "data", None), dict) else {}
    if payload.get("can_slice") is not True:
        return "stop"
    revised = []
    rows, columns = sheet.get("rows"), sheet.get("columns")
    for raw in payload.get("ranges") or []:
        if not isinstance(raw, str):
            return "again"
        try:
            c1, r1, c2, r2 = bounded_range(raw)
        except (TypeError, ValueError):
            return "again"
        if not (
            isinstance(rows, int)
            and isinstance(columns, int)
            and 1 <= c1 <= c2 <= columns
            and 1 <= r1 <= r2 <= rows
        ):
            return "again"
        if allowed and not _range_inside(c1, r1, c2, r2, allowed):
            return "again"
        revised.append({"sheet": sheet_name, "range": raw})
    return revised or "again"


def derive_classified_documents(body: bytes, classification: dict, *, owner_id: int | None = None) -> list[dict]:
    """Export only documents with explicit model grouping, without inferring missing groups.

    This internal function expects the output of classify_semantic_workbook, not
    arbitrary client data. It does not record user confirmation or modify the source.
    OLE/BIFF8 XLS bodies are converted to XLSX via ensure_slice_workbook before
    openpyxl load and document derivation.
    """
    body, _receipt = ensure_slice_workbook(body)
    source = inspect_workbook(body)
    if classification.get("source_sha256") != source["sha256"]:
        raise ReviewedExcelError("分类结果与原件不一致")
    if source.get("drawing_evidence"):
        from app.application.reviewed_excel_drawing import grouping_drawings

        coverage = classification.get("coverage", [])
        if len(coverage) != len(source["sheets"]) or any(
            row.get("drawing_unread")
            or row.get("drawing_unassigned")
            or row.get("unread")
            or row.get("unassigned")
            or row.get("merged_omitted")
            for row in coverage
        ):
            raise ReviewedExcelError("绘图证据覆盖不完整，暂不能裁切")
        grouping_drawings(source, classification.get("regions", []), [])
    if classification.get("model_status") != "returned":
        raise ReviewedExcelError("模型分类尚未返回")
    regions = classification.get("regions")
    if not isinstance(regions, list) or not regions:
        raise ReviewedExcelError("没有可提取的模型区域")
    known = {}
    for region in regions:
        if region.get("open_fragment"):
            raise ReviewedExcelError("模型片段仍跨越未读边界，不能作为完整单据切片")
        key = (region["sheet"], region["range"])
        if key in known:
            raise ReviewedExcelError("模型区域重复")
        known[key] = region
    assigned = set()
    groups = []
    for document in classification.get("suggested_documents", []):
        fragments = document.get("fragments")
        if not isinstance(fragments, list) or not fragments:
            raise ReviewedExcelError("模型分组无片段")
        group = []
        for fragment in fragments:
            if not isinstance(fragment, dict) or set(fragment) != {"sheet", "range"}:
                raise ReviewedExcelError("模型分组片段无效")
            key = (fragment["sheet"], fragment["range"])
            if key not in known or key in assigned:
                raise ReviewedExcelError("模型分组片段来源无效或重复")
            assigned.add(key)
            group.append(dict(fragment))
        reason = document.get("reason") if isinstance(document.get("reason"), str) else ""
        groups.append((group, "model_group", reason))
    if len(assigned) != len(known):
        raise ReviewedExcelError("模型尚未确定所有区域的独立单据关系，不能自动切片")
    from app.application.reviewed_excel_verify_cut import verify_after_cut

    verified = verify_after_cut(
        source,
        [
            {
                "document_id": f"export-{i}",
                "fragments": frags,
                "evidence": [],
                "reason": reason,
            }
            for i, (frags, _basis, reason) in enumerate(groups)
        ],
        resplit=False,
    )
    groups = [
        (item["fragments"], "model_group", item.get("reason") or "") for item in verified["groups"]
    ]
    results = []
    used_names: set[str] = set()
    hidden_sheets = {
        item.get("sheet")
        for item in source.get("sheet_overview") or []
        if isinstance(item, dict) and item.get("sheet_state") in {"hidden", "veryHidden"}
    }
    for fragments, basis, reason in groups:
        if fragments and all(part.get("sheet") in hidden_sheets for part in fragments):
            logger.info("skip hidden sheet %s", fragments[0]["sheet"])
            continue
        print_area_mode = "source"
        # A print area that crosses this fragment continues as the fragment.
        # The source workbook is not rewritten; the slice records the choice.
        if source.get("drawing_evidence") and source.get("read_only_print_areas"):
            raise ReviewedExcelError("原打印区域无法安全映射，暂不能自动裁切")
        object_receipt: dict = {}
        hidden_hold: str | None = None
        hold_reason = _HIDDEN_REASON
        try:
            for fragment in fragments:
                region = _model_region_for_fragment(known, fragment)
                for ref in region.get("dependencies", []):
                    column, row = coordinate_from_string(ref["cell"])
                    col = column_index_from_string(column)
                    if not any(
                        ref["sheet"] == part["sheet"] and c1 <= col <= c2 and r1 <= row <= r2
                        for part in fragments
                        for c1, r1, c2, r2 in [bounded_range(part["range"])]
                    ):
                        raise ReviewedExcelError("所选文档依赖外部说明或标题，暂不能保证保真提取")
            output = derive_document_workbook(
                body, fragments, print_area_mode=print_area_mode, object_receipt=object_receipt
            )
        except ReviewedExcelError as exc:
            message = str(exc)
            if "所选片段作为派生打印区域" in message:
                print_area_mode = "selected"
                object_receipt = {}
                output = derive_document_workbook(
                    body, fragments, print_area_mode=print_area_mode, object_receipt=object_receipt
                )
            elif "隐藏工作表暂不能作为独立模板提取" in message:
                hidden_hold = message
                output = b""
            elif any(marker in message for marker in _COMPATIBILITY_MARKERS):
                overview = source.get("sheet_overview") or []
                earlier: list[str] = []
                seen = {tuple(part["range"] for part in fragments)}
                obstacle = message
                hidden_hold = message
                hold_reason = "兼容性各轮后仍不能保真导出，已保留复核副本"
                output = b""
                for round_index in range(1, _COMPATIBILITY_ROUNDS + 1):
                    sheet_name = str(fragments[0]["sheet"])
                    allowed = (
                        [area for region_sheet, area in known if region_sheet == sheet_name]
                        if "模型区域之外" in obstacle
                        else None
                    )
                    revised = _compatibility_revision(
                        fragments, obstacle, overview, owner_id, earlier, allowed
                    )
                    logger.info(
                        "compatibility round %s sheet=%s", round_index, fragments[0]["sheet"]
                    )
                    if revised == "stop":
                        break
                    if revised == "again":
                        earlier.append(f"第{round_index}轮回答不能用，没有给出这张表内的新矩形")
                        continue
                    key = tuple(part["range"] for part in revised)
                    if key in seen:
                        earlier.append(f"第{round_index}轮重复了已失败范围：{', '.join(key)}")
                        break
                    seen.add(key)
                    try:
                        output = derive_document_workbook(
                            body,
                            revised,
                            print_area_mode=print_area_mode,
                            object_receipt=object_receipt,
                        )
                        fragments = revised
                        hidden_hold = None
                        break
                    except ReviewedExcelError as again:
                        retry_message = str(again)
                        if "所选片段作为派生打印区域" in retry_message:
                            print_area_mode = "selected"
                            object_receipt = {}
                            output = derive_document_workbook(
                                body,
                                revised,
                                print_area_mode=print_area_mode,
                                object_receipt=object_receipt,
                            )
                            fragments = revised
                            hidden_hold = None
                            break
                        obstacle = retry_message
                        fragments = revised
                        hidden_hold = retry_message
                        earlier.append(
                            f"第{round_index}轮范围 {', '.join(key)} 仍失败：{retry_message}"
                        )
            else:
                raise
        record = {
            "print_area_mode": print_area_mode,
            "range_objects_receipt": object_receipt,
            "fragments": fragments,
            "basis": basis,
            "confirmed": False,
            "source_sha256": source["sha256"],
            "filename": _slice_filename(fragments, source["cells"], used_names, reason=reason),
            "workbook": output,
        }
        if hidden_hold is not None:
            copy_sources: dict = {}
            try:
                record["workbook"] = _review_document(copy_sources, body, fragments, _HIDDEN_REASON)
            finally:
                for book in copy_sources.values():
                    book.close()
            record["status"] = "pending_review"
            record["error"] = hidden_hold
            record["review_reason"] = hold_reason
        results.append(record)
    return results
