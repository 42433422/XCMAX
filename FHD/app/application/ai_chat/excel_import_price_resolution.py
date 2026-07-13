"""Unit-price intent and ambiguity resolution for Excel imports."""

from __future__ import annotations

import logging
import re
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ExcelImportPriceResolver:
    @staticmethod
    def _price_column_buckets(keys: list[str]) -> tuple[list[str], list[str], list[str]]:
        """将列名划分为 调价前类 / 调价后类 / 其它价格类（词条与 ``ai_db_field_index.json`` 同步）。"""
        try:
            from app.services.ai_db_schema_index import price_column_buckets_for_keys

            return cast(
                "tuple[list[str], list[str], list[str]]", price_column_buckets_for_keys(list(keys))
            )
        except RECOVERABLE_ERRORS as err:
            logger.debug("价格列分桶失败，回退启发式: %s", err)
            before: list[str] = []
            after: list[str] = []
            generic: list[str] = []
            for raw in keys:
                cn = str(raw or "").strip()
                if not cn or "数量" in cn or "计量" in cn or "件数" in cn:
                    continue
                if not re.search(r"(单价|价格|报价|含税价|含税单价|金额)", cn):
                    continue
                if re.search(r"(调价\s*前|调价前|调整前|原价)", cn):
                    before.append(cn)
                elif re.search(r"(调价\s*后|调价后|折后|执行价|现用)", cn):
                    after.append(cn)
                else:
                    generic.append(cn)
            return before, after, generic

    @staticmethod
    def _merge_user_intent_for_price_resolution(
        user_message: str,
        request_context: dict[str, Any] | None,
    ) -> str:
        """
        合并「最近对话」与当前用户句，用于识别「调价前/后」单价列偏好。

        - 含 ``recent_messages`` 中 **user** 与 **assistant / ai**（前端气泡角色为 ``ai``）：
          否则助手已写「导入调价前数据」而用户只回「确认/导入」时，规则入库读不到承诺列。
        - 当前 ``user_message`` 放在 **末尾**，避免与历史中同一句重复时覆盖最新意图。
        """
        chunks: list[str] = []
        cur = str(user_message or "").strip()

        def _strip_htmlish(s: str) -> str:
            t = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
            return re.sub(r"<[^>]+>", "", t).strip()

        if isinstance(request_context, dict):
            rm = request_context.get("recent_messages")
            if isinstance(rm, list):
                for item in rm:
                    if not isinstance(item, dict):
                        continue
                    role = str(item.get("role") or "").strip().lower()
                    if role not in ("user", "assistant", "ai"):
                        continue
                    c = _strip_htmlish(str(item.get("content") or ""))
                    if not c or c in chunks:
                        continue
                    chunks.append(c)
            for k in ("message", "user_message"):
                extra = _strip_htmlish(str(request_context.get(k) or ""))
                if extra and extra not in chunks:
                    chunks.append(extra)
        cur_clean = _strip_htmlish(cur) if cur else ""
        if cur_clean:
            chunks.append(cur_clean)
        merged = "\n".join(chunks)
        if len(merged) > 8000:
            merged = merged[-8000:]
        return merged

    @staticmethod
    def _resolve_unit_price_column(
        keys: list[str],
        current: str,
        user_message: str,
        overrides: dict[str, Any] | None,
    ) -> tuple[str, str | None]:
        """
        结合列名与用户话术确定入库单价列。
        返回 (column_name, error_code)；error_code 为 ambiguous_price_columns 时应中止自动入库。
        user_message 建议传入 _merge_user_intent_for_price_resolution 的结果（含最近用户轮次）。
        """
        ov = overrides if isinstance(overrides, dict) else {}
        forced = str(ov.get("unit_price") or ov.get("price") or "").strip()
        if forced:
            for k in keys:
                if str(k).strip() == forced:
                    return str(k), None

        keyset = [str(k).strip() for k in keys if str(k).strip()]
        if not keyset:
            return "", None

        um = str(user_message or "").strip()
        before, after, generic = ExcelImportPriceResolver._price_column_buckets(keyset)
        has_tension = bool(before and after)
        # 分桶漏检（表头含空格/异体等）时，只要键名上同时出现「调价前」「调价后」仍视为双价列，须话术或覆盖项
        if not has_tension:
            pres = [k for k in keyset if "调价前" in str(k).replace(" ", "")]
            posts = [k for k in keyset if "调价后" in str(k).replace(" ", "")]
            if pres and posts:
                has_tension = True

        def _first(opts: list[str]) -> str:
            return str(opts[0]).strip() if opts else ""

        # 长句里「导入 …（文件名/说明）… 调价前」可能远超 12 字距，放宽窗口并允许跨行
        _gap = r"[\s\S]{0,360}?"
        prefer_before = bool(
            re.search(
                rf"(用|取|要|导入|写入|入库){_gap}调价\s*前|调价\s*前{_gap}(?:价|单价|列|数据)|"
                rf"价格{_gap}调价\s*前|单价{_gap}调价\s*前|"
                rf"(?:按|以|采用|使用|选用|取){_gap}调价\s*前",
                um,
                re.I,
            )
        )
        prefer_after = bool(
            re.search(
                rf"(用|取|要|导入|写入|入库){_gap}调价\s*后|调价\s*后{_gap}(?:价|单价|列|数据)|"
                rf"价格{_gap}调价\s*后|单价{_gap}调价\s*后|"
                rf"(?:按|以|采用|使用|选用|取){_gap}调价\s*后",
                um,
                re.I,
            )
        )
        # 整段话里仅出现一侧字样时的强提示（助手整段说明常用）
        if "调价前" in um and "调价后" not in um:
            prefer_before = True
        if "调价后" in um and "调价前" not in um:
            prefer_after = True

        if has_tension:
            if prefer_before and not prefer_after:
                return _first(before), None
            if prefer_after and not prefer_before:
                return _first(after), None
            if prefer_before and prefer_after:
                return "", "ambiguous_price_columns"
            # 未从话术判断时：报价类表格默认以「调价前」为入库单价（与 import_excel_to_database 工具侧一致）
            return _first(before), None

        cur = str(current or "").strip()
        if cur and cur in keyset:
            return cur, None
        if before and not after:
            return _first(before), None
        if after and not before:
            return _first(after), None
        if generic:
            if len(generic) == 1:
                return generic[0], None
            if cur and cur in generic:
                return cur, None
            if len(generic) >= 2:
                return "", "ambiguous_price_columns"
        return "", None


__all__ = ["ExcelImportPriceResolver"]
