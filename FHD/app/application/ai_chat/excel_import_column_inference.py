"""Column-role inference for Excel imports."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, cast

import httpx

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ExcelImportColumnInferer:
    _PACK_OR_MEASURE_RE = re.compile(
        r"^\s*\d+(\.\d+)?\s*[/／]\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|桶|箱|组|套|升|L|l)?\s*$"
        r"|^\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|ml|ML|l|L|升|斤|吨)\s*[/／]\s*(桶|箱|组|套|包|袋|罐|个|只)\s*$"
        r"|^\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|ml|ML|l|L|升|斤|吨|桶|箱|包|袋|罐|套|组|个|只|张|米|㎡|cm|CM|mm|MM)\s*$"
        r"|^\s*(桶|箱|包|袋|罐|套|组|个|只|张|升|公斤|千克|斤)\s*$",
        re.I,
    )

    def __init__(
        self,
        *,
        ai_service: Any,
        is_number_text: Callable[[str], bool],
    ) -> None:
        self._ai_service = ai_service
        self._is_number_text = is_number_text

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
        empty_roles = {
            "unit_name": "",
            "product_name": "",
            "model_number": "",
            "unit_price": "",
        }
        try:
            from app.services.ai_db_schema_index import match_excel_import_roles_from_field_index

            roles = cast("dict[str, str]", match_excel_import_roles_from_field_index(list(keys)))
        except RECOVERABLE_ERRORS as err:
            logger.debug("字段索引表头匹配失败，回退空映射: %s", err)
            roles = dict(empty_roles)

        roles = {**empty_roles, **dict(roles or {})}
        for key in keys:
            text = str(key or "").strip()
            normalized = re.sub(r"[\s:_：\-_/（）()]+", "", text).lower()
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
        self,
        records: list[dict[str, Any]],
        reserved: set[str],
    ) -> str:
        """
        推断/LLM 未给出名称列时，从剩余列中选最像「产品描述」的一列，减轻聊天入库丢名称。
        """
        if not records or not isinstance(records[0], dict):
            return ""
        skip_re = re.compile(r"(序|序号|行号|单号|单据|^id$|^no\.?$)", re.I)
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
            num_ratio = sum(1 for v in nonempty if self._is_number_text(v)) / float(len(nonempty))
            avg_len = sum(len(v) for v in nonempty) / float(len(nonempty) or 1)
            score = (1.0 - num_ratio) * 0.5 + min(avg_len, 48.0) / 48.0 * 0.5
            if score > best_score:
                best_score = score
                best_col = sk
        return best_col if best_score >= 0.35 else ""

    def _fallback_excel_model_number_column(
        self,
        records: list[dict[str, Any]],
        reserved: set[str],
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

    def _infer_excel_column_roles(
        self, records: list[dict[str, Any]]
    ) -> tuple[dict[str, str], float]:
        if not records:
            return {}, 0.0
        keys = [k for k in records[0].keys() if str(k).strip()]
        if not keys:
            return {}, 0.0

        stats: dict[str, dict[str, float]] = {}
        for key in keys:
            values = [str((row or {}).get(key) or "").strip() for row in records]
            non_empty = [v for v in values if v]
            if not non_empty:
                continue
            count = float(len(non_empty))
            numeric_ratio = sum(1 for v in non_empty if self._is_number_text(v)) / count
            model_ratio = sum(self._model_like_score(v) for v in non_empty) / count
            unique_ratio = len(set(non_empty)) / count
            avg_len = sum(len(v) for v in non_empty) / count
            repeat_ratio = 1.0 - unique_ratio
            stats[key] = {
                "numeric_ratio": numeric_ratio,
                "model_ratio": model_ratio,
                "unique_ratio": unique_ratio,
                "avg_len": avg_len,
                "repeat_ratio": repeat_ratio,
            }

        if not stats:
            return {}, 0.0

        score_map = {
            "unit_price": lambda s: s["numeric_ratio"] * 0.9 + (1.0 - s["avg_len"] / 20.0) * 0.1,
            "model_number": lambda s: s["model_ratio"] * 0.8 + s["unique_ratio"] * 0.2,
            "unit_name": lambda s: (
                (1.0 - s["numeric_ratio"]) * 0.35
                + s["repeat_ratio"] * 0.5
                + (1.0 - min(s["avg_len"], 20.0) / 20.0) * 0.15
            ),
            "product_name": lambda s: (
                (1.0 - s["numeric_ratio"]) * 0.45
                + s["unique_ratio"] * 0.35
                + min(s["avg_len"], 30.0) / 30.0 * 0.2
            ),
        }

        ranked_by_role: dict[str, list[tuple[str, float]]] = {}
        for role, fn in score_map.items():
            ranked_by_role[role] = sorted(
                [(k, float(fn(v))) for k, v in stats.items()],
                key=lambda x: x[1],
                reverse=True,
            )

        # 避免角色冲突：如果推断冲突，优先保留最强语义的列，其他角色留空。
        used: set[str] = set()
        resolved: dict[str, str] = {}
        confidences: list[float] = []
        for role in ("unit_price", "model_number", "unit_name", "product_name"):
            ranked = ranked_by_role.get(role) or []
            key = str((ranked[0][0] if ranked else "") or "").strip()
            if key and key not in used:
                resolved[role] = key
                used.add(key)
                top_score = ranked[0][1] if ranked else 0.0
                next_score = ranked[1][1] if len(ranked) > 1 else 0.0
                # 置信度由绝对分和领先差共同决定
                role_conf = max(
                    0.0, min(1.0, top_score * 0.7 + max(0.0, top_score - next_score) * 0.3)
                )
                confidences.append(role_conf)
            else:
                resolved[role] = ""
                confidences.append(0.0)
        confidence = sum(confidences) / float(len(confidences) or 1)
        return resolved, confidence

    def _infer_excel_column_roles_with_llm(self, records: list[dict[str, Any]]) -> dict[str, str]:
        if not records:
            return {}
        try:
            from app.infrastructure.llm.providers.credentials import (
                default_chat_completions_url,
                resolve_default_chat_model,
                resolve_openai_env_credentials,
            )

            env_api_key, env_base_url = resolve_openai_env_credentials()
            api_key = str(getattr(self._ai_service, "api_key", "") or env_api_key or "").strip()
            api_url = str(getattr(self._ai_service, "api_url", "") or "").strip()
            if not api_url and env_base_url:
                api_url = f"{env_base_url.rstrip('/')}/chat/completions"
            api_url = api_url or default_chat_completions_url()
            model = str(getattr(self._ai_service, "model", "") or resolve_default_chat_model())
            if not api_key:
                return {}

            keys = [str(k).strip() for k in records[0].keys() if str(k).strip()]
            columns = []
            for key in keys[:30]:
                samples = []
                for row in records[:12]:
                    val = str((row or {}).get(key) or "").strip()
                    if val:
                        samples.append(val[:40])
                    if len(samples) >= 6:
                        break
                columns.append({"column": key, "samples": samples})

            prompt = {
                "task": "判断 Excel 列语义角色",
                "roles": ["unit_name", "product_name", "model_number", "unit_price"],
                "columns": columns,
                "rules": [
                    "只输出 JSON",
                    "每个角色映射一个列名，不确定时填空字符串",
                    "不要编造不存在的列名",
                    "若同时存在「调价前…价」与「调价后…价」两列，unit_price 必须二选一映射到其中一列；"
                    "若无法从列名判断业务应以哪个为准，则 unit_price 填空字符串",
                ],
                "output_schema": {
                    "unit_name": "column_name_or_empty",
                    "product_name": "column_name_or_empty",
                    "model_number": "column_name_or_empty",
                    "unit_price": "column_name_or_empty",
                },
            }
            resp = httpx.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "你是表格列语义识别器，只输出 JSON。"},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 300,
                },
                timeout=10.0,
            )
            if resp.status_code >= 400:
                return {}
            content = (
                ((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            ).strip()
            if not content:
                return {}
            content = (
                content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            )
            parsed = json.loads(content)
            roles = {}
            for role in ("unit_name", "product_name", "model_number", "unit_price"):
                key = str(parsed.get(role) or "").strip()
                roles[role] = key if key in keys else ""
            return roles
        except RECOVERABLE_ERRORS as err:
            logger.debug("LLM 列角色推断失败: %s", err)
            return {}


__all__ = ["ExcelImportColumnInferer"]
