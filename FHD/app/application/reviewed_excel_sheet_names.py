"""Ask the template model to name sheets that classification left as unknown."""

from __future__ import annotations

import logging

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_partition import DOCUMENT_LABELS
from app.application.reviewed_excel_template import _template_llm_complete

logger = logging.getLogger(__name__)

_TYPE_WORDS = (
    (("送货", "出货", "发货"), "delivery"),
    (("报价",), "quotation"),
    (("采购",), "purchase"),
    (("借", "还", "台账"), "ledger"),
    (("测算", "计算"), "calculation"),
    (("考勤",), "attendance"),
    (("生产",), "production"),
    (("工艺",), "process"),
    (("原料", "物料"), "material"),
    (("检验",), "inspection"),
    (("模板",), "template"),
)


def label_for_type(text: str) -> str:
    """Map a short type phrase onto the closed document vocabulary."""
    cleaned = str(text or "").strip()
    for words, label in _TYPE_WORDS:
        if any(word in cleaned for word in words):
            return label if label in DOCUMENT_LABELS else "template"
    return "template"


def _sheet_excerpt(cells: list[dict], sheet: str, limit: int = 12) -> str:
    lines: list[str] = []
    for cell in cells:
        if cell.get("sheet") != sheet:
            continue
        value = str(cell.get("value") or "").replace("\n", " ").strip()
        if not value:
            continue
        lines.append(value[:80])
        if len(lines) >= limit:
            break
    return " | ".join(lines)[:1500]


_SHEET_NAME_SCHEMA = {
    "type": "object",
    "required": ["sheets"],
    "properties": {
        "sheets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["sheet", "name", "type"],
                "properties": {
                    "sheet": {"type": "string"},
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                },
            },
        }
    },
}


def _naming_messages(group: list[dict], cells: list[dict], *, retry: bool) -> list[dict]:
    """Require one name per sheet. A retry names only the sheets still missing one."""
    lines = [
        f"{sheet['sheet']}: {_sheet_excerpt(cells, sheet['sheet']) or '（空表）'}"
        for sheet in group
    ]
    count = len(lines)
    titles = "、".join(str(sheet["sheet"]) for sheet in group)
    lead = "这些表上次没有名字。" if retry else "你给每一张工作表起名并定类型。"
    return [
        {
            "role": "system",
            "content": (
                f"{lead}只返回 JSON 数组。"
                f"数组长度必须等于 {count}，每一张表一条，不能少、不能合并、不能跳过。"
                "内容不同的表各自起名，公式多的表、原料表和测算表也要给名。"
                "按输入顺序返回。每条只有 name 和 type。"
                "name 是这张表自己的短名称，不要写 unknown。"
                "type 是短类型，例如送货单、出货明细、借还台账、测算表、报价单。"
                "不要解释，不要 markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"共 {count} 张表，必须按顺序各返回一条。表名依次是：{titles}。\n"
                + "\n".join(lines)
            ),
        },
    ]


def _apply_model_names(
    group: list[dict], cells: list[dict], *, owner_id: int | None, retry: bool
) -> None:
    if not group:
        return
    try:
        result = _template_llm_complete(
            _naming_messages(group, cells, retry=retry),
            _SHEET_NAME_SCHEMA,
            800,
            owner_id=owner_id,
        )
    except ReviewedExcelError:
        logger.info("sheet naming failed: BOUNDARY")
        return
    if not getattr(result, "used_llm", False) or getattr(result, "degraded", False):
        logger.info("sheet naming returned no usable model result")
        return
    payload = result.data if isinstance(getattr(result, "data", None), dict) else {}
    rows = [item for item in payload.get("sheets") or [] if isinstance(item, dict)]
    named = {str(item.get("sheet") or "").strip(): item for item in rows}
    unmatched = [sheet for sheet in group if str(sheet.get("sheet") or "").strip() not in named]
    if rows and len(unmatched) == len(group):
        paired = list(zip(group, rows))
        named = {str(sheet.get("sheet") or "").strip(): item for sheet, item in paired}
        logger.info("sheet naming matched %s of %s rows by reply order", len(paired), len(group))
    for sheet in group:
        item = named.get(str(sheet.get("sheet") or "").strip())
        if not item:
            continue
        name = str(item.get("name") or "").strip()[:40]
        kind = str(item.get("type") or "").strip()[:20]
        if not name or name.lower() == "unknown":
            continue
        sheet["model_name"] = name
        sheet["model_type"] = kind
        if sheet.get("labels") == ["unknown"] and kind:
            label = label_for_type(kind)
            sheet["labels"] = [label]
            for region in sheet.get("regions") or []:
                if region.get("labels") == ["unknown"]:
                    region["labels"] = [label]
                    region["suggested_labels"] = [label]


def apply_unknown_sheet_names(sheets: list[dict], cells: list[dict], *, owner_id: int | None) -> None:
    """Name every processable sheet. Ask once more for any sheet the model left unnamed."""
    pending = [
        sheet
        for sheet in sheets
        if sheet.get("processable") is not False and str(sheet.get("sheet") or "").strip()
    ]
    if not pending:
        return
    asked = pending[:12]
    _apply_model_names(asked, cells, owner_id=owner_id, retry=False)
    missing = [sheet for sheet in asked if not str(sheet.get("model_name") or "").strip()]
    if not missing:
        return
    logger.info("sheet naming retry for %s sheet(s) still missing a name", len(missing))
    _apply_model_names(missing, cells, owner_id=owner_id, retry=True)


def annotate_slice_titles(slices: list[dict], sheets: list[dict]) -> None:
    """Put the model's sheet name and type on each slice, and disambiguate repeats."""
    by_sheet = {str(sheet.get("sheet") or ""): sheet for sheet in sheets}
    bases: list[str] = []
    kinds: list[str] = []
    for item in slices:
        fragments = item.get("fragments") or []
        sheet_name = str(fragments[0].get("sheet") or "") if fragments else ""
        meta = by_sheet.get(sheet_name, {})
        base = str(meta.get("model_name") or "").strip() or str(item.get("filename") or "").rsplit(".", 1)[0]
        kind = str(meta.get("model_type") or "").strip()
        bases.append(base or sheet_name or "切片")
        kinds.append(kind)
    seen: dict[str, int] = {}
    for item, base, kind in zip(slices, bases, kinds, strict=True):
        seen[base] = seen.get(base, 0) + 1
        title = base if bases.count(base) == 1 else f"{base}（{seen[base]}）"
        item["display_name"] = title[:80]
        item["type_label"] = kind[:20]
