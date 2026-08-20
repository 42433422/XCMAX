# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_chat.excel_import_pipeline")


class __AIChatExcelImportMixinPart02MixinPart01Mixin:
    def _infer_excel_column_roles(
        self, records: list[dict[str, _facade().Any]]
    ) -> tuple[dict[str, str], float]:
        if not records:
            return ({}, 0.0)
        keys = [k for k in records[0].keys() if str(k).strip()]
        if not keys:
            return ({}, 0.0)
        stats: dict[str, dict[str, float]] = {}
        for key in keys:
            values = [str((row or {}).get(key) or "").strip() for row in records]
            non_empty = [v for v in values if v]
            if not non_empty:
                continue
            count = float(len(non_empty))
            numeric_ratio = len([v for v in non_empty if self._is_number_text(v)]) / count
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
            return ({}, 0.0)
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
                [(k, float(fn(v))) for k, v in stats.items()], key=lambda x: x[1], reverse=True
            )
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
                role_conf = max(
                    0.0, min(1.0, top_score * 0.7 + max(0.0, top_score - next_score) * 0.3)
                )
                confidences.append(role_conf)
            else:
                resolved[role] = ""
                confidences.append(0.0)
        confidence = sum(confidences) / float(len(confidences) or 1)
        return (resolved, confidence)

    def _infer_excel_column_roles_with_llm(
        self, records: list[dict[str, _facade().Any]]
    ) -> dict[str, str]:
        if not records:
            return {}
        try:
            from app.infrastructure.llm.providers.credentials import (
                default_chat_completions_url,
                resolve_default_chat_model,
                resolve_openai_env_credentials,
            )

            env_api_key, env_base_url = resolve_openai_env_credentials()
            api_key = str(getattr(self.ai_service, "api_key", "") or env_api_key or "").strip()
            api_url = str(getattr(self.ai_service, "api_url", "") or "").strip()
            if not api_url and env_base_url:
                api_url = f"{env_base_url.rstrip('/')}/chat/completions"
            api_url = api_url or default_chat_completions_url()
            model = str(getattr(self.ai_service, "model", "") or resolve_default_chat_model())
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
                    "若同时存在「调价前…价」与「调价后…价」两列，unit_price 必须二选一映射到其中一列；若无法从列名判断业务应以哪个为准，则 unit_price 填空字符串",
                ],
                "output_schema": {
                    "unit_name": "column_name_or_empty",
                    "product_name": "column_name_or_empty",
                    "model_number": "column_name_or_empty",
                    "unit_price": "column_name_or_empty",
                },
            }
            resp = _facade().httpx.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "你是表格列语义识别器，只输出 JSON。"},
                        {
                            "role": "user",
                            "content": _facade().json.dumps(prompt, ensure_ascii=False),
                        },
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
            parsed = _facade().json.loads(content)
            roles = {}
            for role in ("unit_name", "product_name", "model_number", "unit_price"):
                key = str(parsed.get(role) or "").strip()
                roles[role] = key if key in keys else ""
            return roles
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.debug("LLM 列角色推断失败: %s", err)
            return {}

    @staticmethod
    def _price_column_buckets(keys: list[str]) -> tuple[list[str], list[str], list[str]]:
        """将列名划分为 调价前类 / 调价后类 / 其它价格类（词条与 ``ai_db_field_index.json`` 同步）。"""
        before: list[str] = []
        after: list[str] = []
        generic: list[str] = []
        for raw in keys:
            cn = str(raw or "").strip()
            if not cn or "数量" in cn or "计量" in cn or ("件数" in cn):
                continue
            if not _facade().re.search("(单价|价格|报价|含税价|含税单价|金额)", cn):
                continue
            if _facade().re.search("(调价\\s*前|调价前|调整前|原价)", cn):
                before.append(cn)
            elif _facade().re.search("(调价\\s*后|调价后|折后|执行价|现用)", cn):
                after.append(cn)
            else:
                generic.append(cn)
        return (before, after, generic)

    @staticmethod
    def _merge_user_intent_for_price_resolution(
        user_message: str, request_context: dict[str, _facade().Any] | None
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
            source = str(s or "")
            plain: list[str] = []
            index = 0
            while index < len(source):
                if source[index] == "<":
                    tag_end = source.find(">", index + 1)
                    if tag_end < 0:
                        plain.append(source[index:])
                        break
                    tag_name = source[index + 1 : tag_end].strip().lower()
                    if tag_name in {"br", "br/"} or tag_name.startswith("br "):
                        plain.append("\n")
                    index = tag_end + 1
                    continue
                plain.append(source[index])
                index += 1
            return "".join(plain).replace("&nbsp;", " ").replace("&amp;", "&").strip()

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
        keys: list[str], current: str, user_message: str, overrides: dict[str, _facade().Any] | None
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
                    return (str(k), None)
        keyset = [str(k).strip() for k in keys if str(k).strip()]
        if not keyset:
            return ("", None)
        um = str(user_message or "").strip()
        before, after, generic = _facade().AIChatExcelImportMixin._price_column_buckets(keyset)
        has_tension = bool(before and after)
        if not has_tension:
            pres = [k for k in keyset if "调价前" in str(k).replace(" ", "")]
            posts = [k for k in keyset if "调价后" in str(k).replace(" ", "")]
            if pres and posts:
                has_tension = True

        def _first(opts: list[str]) -> str:
            return str(opts[0]).strip() if opts else ""

        _gap = "[\\s\\S]{0,360}?"
        prefer_before = bool(
            _facade().re.search(
                f"(用|取|要|导入|写入|入库){_gap}调价\\s*前|调价\\s*前{_gap}(?:价|单价|列|数据)|价格{_gap}调价\\s*前|单价{_gap}调价\\s*前|(?:按|以|采用|使用|选用|取){_gap}调价\\s*前",
                um,
                _facade().re.I,
            )
        )
        prefer_after = bool(
            _facade().re.search(
                f"(用|取|要|导入|写入|入库){_gap}调价\\s*后|调价\\s*后{_gap}(?:价|单价|列|数据)|价格{_gap}调价\\s*后|单价{_gap}调价\\s*后|(?:按|以|采用|使用|选用|取){_gap}调价\\s*后",
                um,
                _facade().re.I,
            )
        )
        if "调价前" in um and "调价后" not in um:
            prefer_before = True
        if "调价后" in um and "调价前" not in um:
            prefer_after = True
        if has_tension:
            if prefer_before and (not prefer_after):
                return (_first(before), None)
            if prefer_after and (not prefer_before):
                return (_first(after), None)
            if prefer_before and prefer_after:
                return ("", "ambiguous_price_columns")
            return (_first(before), None)
        cur = str(current or "").strip()
        if cur and cur in keyset:
            return (cur, None)
        if before and (not after):
            return (_first(before), None)
        if after and (not before):
            return (_first(after), None)
        if generic:
            if len(generic) == 1:
                return (generic[0], None)
            if cur and cur in generic:
                return (cur, None)
            if len(generic) >= 2:
                return ("", "ambiguous_price_columns")
        return ("", None)
