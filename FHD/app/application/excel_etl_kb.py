"""Excel ETL 兼容知识库（生产运行时只读，非送货单硬编码）。

存储：
- synonyms / meta_labels：共享只读字段同义词
- templates：旧表头指纹兼容预设；新的确认结果写入个人 ETL 模板

默认不读仓库内 YAML 版式；自定义可走 PROFILE_DIR 或本 KB。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()

# 知识库种子：语义同义词，不是「送货单模板」
_SEED: dict[str, Any] = {
    "version": 1,
    "synonyms": {
        "model_number": ["型号", "货号", "sku", "SKU", "编号", "编码", "model", "Model", "料号"],
        "product_name": ["名称", "品名", "产品名称", "品名规格", "name", "Name", "商品", "物料"],
        "quantity_tins": ["数量", "数量/件", "件数", "箱数", "桶数", "qty", "Qty", "数量件"],
        "tin_spec": ["规格", "规格/KG", "规格kg", "单重", "spec"],
        "quantity_kg": ["数量/KG", "数量kg", "公斤", "重量", "kg"],
        "unit_price": ["单价", "单价/元", "价格", "price", "Price", "售价"],
        "amount": ["金额", "金额/元", "合计", "amount", "Amount", "小计"],
        "order_number": ["单号", "订单编号", "订单号", "编号", "order", "OrderNo"],
        "order_date": ["日期", "下单日", "打单日", "购货日", "date", "Date"],
        "remark": ["备注", "说明", "remark", "Remark"],
    },
    "meta_labels": {
        "unit_name": [
            "客户",
            "客户名称",
            "购货单位",
            "采购单位",
            "收货单位",
            "收货方",
            "买方",
            # 勿用裸 buyer/customer：会误吃 "Buyer PO:"
            "Bill To",
            "Sold To",
            "Ship To",
            "Consignee",
            # 裸 "To" 易误匹配 Technologies；由相邻格识别 To:
        ],
        "contact_person": ["联系人", "经办人", "Attn", "Attention", "contact"],
        "order_date": ["日期", "下单日", "date", "Date"],
        "order_number": [
            "订单编号",
            "单号",
            "订单号",
            "DO No",
            "Invoice No",
            "Buyer PO",
            "PO Ref",
            "order",
        ],
    },
    "write_layouts": {
        "universal_table": {
            "seller_title": "Document",
            "default_sheet_name": "Sheet1",
            "sheet_name_prefix": "S",
            "meta_line_template": (
                "客户：{unit}     联系人：{contact}        "
                "日期：{order_date}         单号：{order_no}"
            ),
            "demo_meta_line": (
                "客户：示例客户     联系人：测试        日期：2026年07月25日         单号：DEMO-1"
            ),
            "header_row": ["型号", "名称", "数量", "规格", "数量KG", "单价", "金额"],
            "footer_label": "",
            "date_format": "%Y年%m月%d日",
            "item_columns": {
                "model_number": 1,
                "product_name": 2,
                "quantity_tins": 3,
                "tin_spec": 4,
                "quantity_kg": 5,
                "unit_price": 6,
                "amount": 7,
            },
            "demo_item": {
                "model_number": "SKU-1",
                "product_name": "示例产品",
                "quantity_tins": 1,
                "tin_spec": 1,
                "quantity_kg": 1,
                "unit_price": 10,
                "amount": 10,
            },
            "ledger_sheet_name": "Ledger",
            "ledger_extra_sheet": "",
            "ledger_default_unit": "unit",
            "ledger_header_row": [
                "日期",
                "单号",
                "型号",
                "名称",
                "数量",
                "规格",
                "数量KG",
                "单价",
                "金额",
            ],
            "ledger_item_columns": {
                "order_date": 1,
                "order_number": 2,
                "model_number": 3,
                "product_name": 4,
                "quantity_tins": 5,
                "tin_spec": 6,
                "quantity_kg": 7,
                "unit_price": 8,
                "amount": 9,
            },
            "ledger_sample_rows": [
                {
                    "order_date": "2026-07-01",
                    "order_number": "L-001",
                    "model_number": "DEMO-A",
                    "product_name": "示例物料A",
                    "quantity_tins": 2,
                    "tin_spec": 25,
                    "quantity_kg": 50,
                    "unit_price": 8.5,
                    "amount": 425,
                },
                {
                    "order_date": "2026-07-02",
                    "order_number": "L-002",
                    "model_number": "DEMO-B",
                    "product_name": "示例物料B",
                    "quantity_tins": 1,
                    "tin_spec": 20,
                    "quantity_kg": 20,
                    "unit_price": 17,
                    "amount": 340,
                },
            ],
        }
    },
    "templates": {},
}


def _kb_path() -> Path:
    override = str(os.environ.get("FHD_EXCEL_ETL_KB_PATH") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    try:
        from app.utils.path_utils import get_data_dir

        root = Path(get_data_dir())
    except RECOVERABLE_ERRORS:
        root = Path.cwd() / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root / "excel_etl_kb.json"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class TemplateMemory:
    fingerprint: str
    label: str = ""
    target: str = "preview_only"
    header_row: int | None = None
    columns: dict[str, int] = field(default_factory=dict)
    meta: dict[str, str] = field(default_factory=dict)
    write: dict[str, Any] = field(default_factory=dict)
    hit_count: int = 0
    source: str = "learned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "label": self.label,
            "target": self.target,
            "header_row": self.header_row,
            "columns": dict(self.columns),
            "meta": dict(self.meta),
            "write": dict(self.write),
            "hit_count": self.hit_count,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateMemory:
        return cls(
            fingerprint=str(data.get("fingerprint") or ""),
            label=str(data.get("label") or ""),
            target=str(data.get("target") or "preview_only"),
            header_row=(
                int(data["header_row"])
                if data.get("header_row") is not None and str(data.get("header_row")).isdigit()
                else data.get("header_row")
                if isinstance(data.get("header_row"), int)
                else None
            ),
            columns={str(k): int(v) for k, v in (data.get("columns") or {}).items()},
            meta={str(k): str(v) for k, v in (data.get("meta") or {}).items()},
            write=dict(data.get("write") or {}),
            hit_count=int(data.get("hit_count") or 0),
            source=str(data.get("source") or "learned"),
        )


class ExcelEtlKnowledgeBase:
    def __init__(self, path: Path | None = None, *, mutable_for_tests: bool = False) -> None:
        self.path = path or _kb_path()
        # 通用 ETL 上线后，全局知识库仅作为兼容种子读取。用户确认的学习结果
        # 必须进入带 tenant_id + owner_user_id 的个人模板，不能再污染全局 JSON。
        self._mutable_for_tests = mutable_for_tests
        self._data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        data = json.loads(json.dumps(_SEED))
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = _deep_merge(data, loaded)
            except RECOVERABLE_ERRORS:
                logger.warning("excel etl kb load failed: %s", self.path, exc_info=True)
        if not isinstance(data.get("templates"), dict):
            data["templates"] = {}
        self._data = data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def synonyms(self) -> dict[str, list[str]]:
        raw = self._data.get("synonyms") or {}
        return {str(k): [str(x) for x in (v or [])] for k, v in raw.items()}

    def meta_labels(self) -> dict[str, list[str]]:
        seed = (_SEED.get("meta_labels") or {}) if isinstance(_SEED, dict) else {}
        raw = self._data.get("meta_labels") or {}
        out: dict[str, list[str]] = {}
        keys = {str(k) for k in seed} | {str(k) for k in raw}
        for key in keys:
            merged: list[str] = []
            seen: set[str] = set()
            for src in (seed.get(key) or [], raw.get(key) or []):
                for item in src:
                    text = str(item or "").strip()
                    low = text.lower()
                    if not text or low in seen:
                        continue
                    seen.add(low)
                    merged.append(text)
            out[str(key)] = merged
        return out

    def write_layout(self, name: str = "universal_table") -> dict[str, Any]:
        layouts = self._data.get("write_layouts") or {}
        layout = layouts.get(name) or layouts.get("universal_table") or {}
        return dict(layout)

    def list_templates(self) -> list[TemplateMemory]:
        out: list[TemplateMemory] = []
        for key, raw in (self._data.get("templates") or {}).items():
            if not isinstance(raw, dict):
                continue
            item = TemplateMemory.from_dict({**raw, "fingerprint": raw.get("fingerprint") or key})
            if item.fingerprint:
                out.append(item)
        return out

    def get_template(self, fingerprint: str) -> TemplateMemory | None:
        """只读查询，不改 hit_count。"""
        fp = str(fingerprint or "").strip()
        if not fp:
            return None
        raw = (self._data.get("templates") or {}).get(fp)
        if not isinstance(raw, dict):
            return None
        return TemplateMemory.from_dict({**raw, "fingerprint": fp})

    def touch(self, fingerprint: str) -> TemplateMemory | None:
        """兼容只读查询；生产运行时不再把命中次数写回全局文件。"""
        mem = self.get_template(fingerprint)
        if mem is None:
            return None
        if not self._mutable_for_tests:
            return mem
        mem.hit_count = int(mem.hit_count) + 1
        with _LOCK:
            templates = self._data.setdefault("templates", {})
            templates[mem.fingerprint] = mem.to_dict()
            try:
                self.save()
            except RECOVERABLE_ERRORS:
                logger.debug("excel etl kb hit_count persist skipped", exc_info=True)
        return mem

    def lookup(self, fingerprint: str) -> TemplateMemory | None:
        return self.touch(fingerprint)

    def remember(self, memory: TemplateMemory) -> None:
        fp = str(memory.fingerprint or "").strip()
        if not fp or not self._mutable_for_tests:
            return
        with _LOCK:
            templates = self._data.setdefault("templates", {})
            prev = templates.get(fp) if isinstance(templates.get(fp), dict) else {}
            merged = TemplateMemory.from_dict(
                {**(prev or {}), **memory.to_dict(), "fingerprint": fp}
            )
            if prev:
                merged.hit_count = max(int(prev.get("hit_count") or 0), merged.hit_count)
            templates[fp] = merged.to_dict()
            self.save()

    def forget(self, fingerprint: str) -> bool:
        if not self._mutable_for_tests:
            return False
        fp = str(fingerprint or "").strip()
        with _LOCK:
            templates = self._data.setdefault("templates", {})
            if fp not in templates:
                return False
            del templates[fp]
            self.save()
            return True


_KB: ExcelEtlKnowledgeBase | None = None


def get_excel_etl_kb() -> ExcelEtlKnowledgeBase:
    global _KB
    if _KB is None:
        _KB = ExcelEtlKnowledgeBase()
    return _KB


def reset_excel_etl_kb_for_tests(path: Path | None = None) -> ExcelEtlKnowledgeBase:
    global _KB
    _KB = ExcelEtlKnowledgeBase(path=path, mutable_for_tests=True)
    return _KB


def normalize_header_token(value: Any) -> str:
    text = str(value or "").replace("\u3000", " ").strip().lower()
    return re.sub(r"[\s/_\-]+", "", text)


def sheet_layout_fingerprint(
    *,
    sheet_title: str,
    header_cells: list[str],
    meta_blob: str = "",
) -> str:
    """表头指纹（默认不含业务 meta 值，避免客户名污染模板记忆）。"""
    _ = meta_blob  # 保留参数兼容；版式学习只看 sheet+headers
    payload = {
        "title": normalize_header_token(sheet_title),
        "headers": [normalize_header_token(h) for h in header_cells if str(h or "").strip()],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:28]


__all__ = [
    "ExcelEtlKnowledgeBase",
    "TemplateMemory",
    "get_excel_etl_kb",
    "normalize_header_token",
    "reset_excel_etl_kb_for_tests",
    "sheet_layout_fingerprint",
]
