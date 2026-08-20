# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_chat.excel_import_pipeline")


class __AIChatExcelImportMixinPart01MixinPart02Mixin:
    @staticmethod
    def _model_like_score(value: str) -> float:
        text = str(value or "").strip()
        if not text:
            return 0.0
        has_digit = any(ch.isdigit() for ch in text)
        has_alpha = any(ch.isalpha() for ch in text)
        compact = text.replace("-", "").replace("_", "")
        if len(compact) < 2 or len(compact) > 24:
            return 0.0
        if has_digit and has_alpha:
            return 1.0
        if has_digit and len(compact) <= 12:
            return 0.6
        return 0.0

    @classmethod
    def _packaging_or_measure_ratio(cls, values: list[str]) -> float:
        """列取值多为包装规格/计量单位时接近 1（不应作为客户列）。"""
        nonempty = [str(v or "").strip() for v in values if str(v or "").strip()]
        if not nonempty:
            return 0.0
        hit = 0
        for v in nonempty:
            if cls._PACK_OR_MEASURE_RE.match(v):
                hit += 1
                continue
            if v in {
                "件",
                "个",
                "只",
                "箱",
                "盒",
                "包",
                "袋",
                "瓶",
                "桶",
                "罐",
                "套",
                "组",
                "台",
                "条",
                "张",
                "支",
            }:
                hit += 1
        return hit / float(len(nonempty))

    @staticmethod
    def _header_hint_column_roles(keys: list[str]) -> dict[str, str]:
        """
        表头 → 客户/名称/型号/单价 四角色：词条来自 ``resources/config/ai_db_field_index.json`` 中
        ``products`` 各列的 ``excel_synonyms_zh`` / ``api_aliases``，可按业务增删而无需改 Python。
        """
        empty_roles = {"unit_name": "", "product_name": "", "model_number": "", "unit_price": ""}
        roles = dict(empty_roles)
        roles = {**empty_roles, **dict(roles or {})}
        for key in keys:
            text = str(key or "").strip()
            normalized = _facade().re.sub("[\\s:_：\\-_/（）()]+", "", text).lower()
            if not normalized:
                continue
            if normalized in {
                "客户",
                "客户名",
                "客户名称",
                "客户全称",
                "购买单位",
                "购货单位",
                "单位名称",
                "公司",
                "公司名称",
                "厂名",
            }:
                roles["unit_name"] = text
                continue
            if normalized in {
                "产品",
                "产品名",
                "产品名称",
                "商品",
                "商品名称",
                "品名",
                "名称",
                "物料名称",
            }:
                roles["product_name"] = text
                continue
            if normalized in {"型号", "规格型号", "产品型号", "编码", "产品编码", "model", "sku"}:
                roles["model_number"] = text
                continue
            if normalized in {"单价", "价格", "产品单价", "销售单价", "报价", "unitprice", "price"}:
                roles["unit_price"] = text
        return roles

    def _fallback_excel_product_name_column(
        self, records: list[dict[str, _facade().Any]], reserved: set[str]
    ) -> str:
        """
        推断/LLM 未给出名称列时，从剩余列中选最像「产品描述」的一列，减轻聊天入库丢名称。
        """
        if not records or not isinstance(records[0], dict):
            return ""
        skip_re = _facade().re.compile("(序|序号|行号|单号|单据|^id$|^no\\.?$)", _facade().re.I)
        best_col = ""
        best_score = -1.0
        min_nonempty = max(1, min(3, len(records) // 4))
        for key in records[0].keys():
            sk = str(key or "").strip()
            if not sk or sk in reserved:
                continue
            if skip_re.search(sk):
                continue
            values = [str((row or {}).get(sk) or "").strip() for row in records]
            nonempty = [v for v in values if v]
            if len(nonempty) < min_nonempty:
                continue
            if self._packaging_or_measure_ratio(nonempty) >= 0.45:
                continue
            num_ratio = len([v for v in nonempty if self._is_number_text(v)]) / float(len(nonempty))
            avg_len = sum(len(v) for v in nonempty) / float(len(nonempty) or 1)
            score = (1.0 - num_ratio) * 0.5 + min(avg_len, 48.0) / 48.0 * 0.5
            if score > best_score:
                best_score = score
                best_col = sk
        return best_col if best_score >= 0.35 else ""

    def _fallback_excel_model_number_column(
        self, records: list[dict[str, _facade().Any]], reserved: set[str]
    ) -> str:
        """未识别型号列时，在剩余列上按型号样字符串得分选列，减轻丢型号。"""
        if not records or not isinstance(records[0], dict):
            return ""
        best_col = ""
        best_score = -1.0
        for key in records[0].keys():
            sk = str(key or "").strip()
            if not sk or sk in reserved:
                continue
            values = [str((row or {}).get(sk) or "").strip() for row in records]
            nonempty = [v for v in values if v]
            if not nonempty:
                continue
            mr = sum(self._model_like_score(v) for v in nonempty) / float(len(nonempty))
            if mr > best_score:
                best_score = mr
                best_col = sk
        return best_col if best_score >= 0.22 else ""
