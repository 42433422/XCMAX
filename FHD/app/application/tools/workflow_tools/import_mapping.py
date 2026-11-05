"""Pure Excel row mapping and product cell normalization."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

from app.application.tools.workflow_tools.contracts import Payload
from app.utils.operational_errors import RECOVERABLE_ERRORS

CLAUSE_SUBSTRINGS = (
    "含税价",
    "含税",
    "月结",
    "数期",
    "担保",
    "付款责任",
    "保质保量",
    "验收签名",
    "所送货物",
    "若贵司",
    "未能按时付款",
    "配套使用",
    "我厂产品",
    "所示比例施工",
    "供应方签名",
    "供应方",
    "采购方",
    "盖章",
    "出资人",
    "签名及盖章",
    "以上价格为",
    "以上各种产品",
    "请严格按",
    "请配套",
)


def looks_like_contract_or_footer_line(name: str | None, clauses: tuple[str, ...]) -> bool:
    text = (name or "").strip()
    if len(text) < 6:
        return False
    if any(clause in text for clause in clauses):
        return True
    match = re.match(r"^\s*(\d+)[、．\.]\s*(.+)$", text)
    if match and len(match.group(2)) >= 8:
        rest = match.group(2)
        return any(clause in rest for clause in clauses) or bool(
            re.search("(以上|所送|数期|保质|验收|付款|月结|含税|施工|配套|货物)", rest)
        )
    return False


def infer_product_field_mapping(
    columns: list[str], *, price_column_hint: str | None = None
) -> dict[str, str]:
    def normalize(value: str) -> str:
        return value.replace(" ", "").replace("\u3000", "").strip()

    pairs = [(str(column), normalize(str(column))) for column in columns]
    mapping: dict[str, str] = {}
    taken: set[str] = set()

    def take(field: str, matches: Callable[[str, str], bool]) -> None:
        if field in mapping:
            return
        for column, normalized in pairs:
            if column not in taken and matches(column, normalized):
                mapping[field] = column
                taken.add(column)
                return

    take(
        "model_number",
        lambda c, n: (
            not ("规格" in n and "号" not in n and "编" not in n)
            and (("编" in c and "号" in c) or "编号" in n or "编码" in n or "sku" in c.lower())
        ),
    )
    take("model_number", lambda c, n: "型号" in c or "model" in c.lower())
    take("specification", lambda c, n: "规格" in c or "规格" in n or ("规" in c and "格" in c))
    take("name", lambda c, n: "产品名称" in n or "品名" in n or "名称" in c or "name" in c.lower())
    hint = normalize(price_column_hint) if price_column_hint else ""
    if hint:
        take("price", lambda c, n: hint in n or hint.lower() in n.lower() or hint in c)
    for price_hint in ("调价前", "调价后", "现价", "单价", "价格", "price"):

        def matches_price(c: str, n: str, key: str = price_hint) -> bool:
            return key.lower() in n.lower() or key in c

        take("price", matches_price)
    for field, chinese, english in (
        ("unit", ("单位",), ("unit",)),
        ("quantity", ("数量",), ("quantity", "qty")),
        ("description", ("备注", "描述"), ("description",)),
        ("brand", ("品牌",), ("brand",)),
        ("category", ("类别", "分类"), ("category",)),
    ):

        def matches_field(
            c: str, n: str, cn: tuple[str, ...] = chinese, en: tuple[str, ...] = english
        ) -> bool:
            return any(key in c for key in cn) or any(key in c.lower() for key in en)

        take(field, matches_field)
    return mapping


def excel_cell_as_clean_str(val: Any) -> str:
    if val is None or isinstance(val, bool):
        return ""
    try:
        if pd.isna(val):
            return ""
    except RECOVERABLE_ERRORS:
        pass
    if isinstance(val, float) and val != val:
        return ""
    if isinstance(val, (int, float)):
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        text = str(val).strip()
        return "" if text.lower() in ("nan", "inf", "-inf") else text
    text = str(val).strip()
    return "" if text.lower() in ("nan", "none", "null", "<na>", "nat") else text


def excel_cell_as_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or (isinstance(val, float) and val != val) or pd.isna(val):
            return default
    except RECOVERABLE_ERRORS:
        pass
    try:
        number = float(val)
        return default if number != number else number
    except (TypeError, ValueError):
        return default


class ProductFields(Protocol):
    def __call__(
        self, columns: list[str], *, price_column_hint: str | None = None
    ) -> dict[str, str]: ...


@dataclass(frozen=True)
class ProductRows:
    records: list[Payload]
    fields: dict[str, str]
    unit: str
    skipped_clauses: int


@dataclass(frozen=True)
class ProductMapper:
    fields: ProductFields
    clean: Callable[[Any], str]
    number: Callable[[Any, float], float]
    is_footer: Callable[[str], bool]

    def map(
        self, df: pd.DataFrame, columns: list[str], unit: str, price_hint: str | None
    ) -> ProductRows:
        fields = self.fields(columns, price_column_hint=price_hint)
        detected_unit = unit
        if not detected_unit and "unit" in fields:
            units = df[fields["unit"]].dropna().astype(str).unique()
            if len(units) == 1:
                detected_unit = str(units[0]).strip()
        records: list[Payload] = []
        skipped = 0
        for _, row in df.iterrows():

            def text(field: str) -> str:
                return self.clean(row.get(fields[field], "")) if field in fields else ""

            name = text("name")
            if name and self.is_footer(name):
                skipped += 1
                continue
            quantity = row.get(fields["quantity"], 0) if "quantity" in fields else 0
            try:
                qty = int(self.number(quantity, 0.0))
            except (TypeError, ValueError):
                qty = 0
            record: Payload = {
                "model_number": text("model_number") or None,
                "name": name or None,
                "specification": text(
                    "specification" if "specification" in fields else "model_number"
                )
                or None,
                "price": self.number(row.get(fields["price"], 0), 0.0)
                if "price" in fields
                else 0.0,
                "unit": detected_unit or unit or "件",
                "quantity": qty if "quantity" in fields else 0,
                **{field: text(field) or None for field in ("description", "brand", "category")},
            }
            if name:
                records.append(record)
        return ProductRows(records, fields, detected_unit, skipped)


def customer_records(df: pd.DataFrame, columns: list[str]) -> list[Payload]:
    records: list[Payload] = []
    hints = (
        ("customer_name", ("名称", "客户"), ("name",)),
        ("contact_person", ("联系人",), ("contact", "person")),
        ("contact_phone", ("电话",), ("phone", "mobile")),
        ("contact_address", ("地址",), ("address",)),
    )
    for _, row in df.iterrows():
        record: Payload = {}
        for column in columns:
            value = str(row.get(column, "")).strip()
            for field, chinese, english in hints:
                if any(key in column for key in chinese) or any(
                    key in column.lower() for key in english
                ):
                    record[field] = value
                    break
        if record.get("customer_name"):
            records.append(record)
    return records


def order_columns(columns: list[str]) -> dict[str, str]:
    hints = {
        "product_name": ("产品名称", "product_name", "名称"),
        "model_number": ("型号", "model_number", "产品型号"),
        "quantity": ("数量", "quantity", "qty", "数量(桶)"),
        "unit_name": ("购买单位", "客户", "purchase_unit"),
    }
    mapping: dict[str, str] = {}
    for column in columns:
        for field, aliases in hints.items():
            if str(column).strip().lower() in {alias.lower() for alias in aliases}:
                mapping[column] = field
                break
    return mapping
