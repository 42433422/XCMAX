"""Excel import pipeline mixin for AIChatExcelImportMixin."""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from pathlib import Path
from typing import Any, cast

import httpx

from app.application.ai_chat.excel_import_policy import (
    _EXCEL_IMPORT_MEASURE_UNIT_TOKENS,
    _EXCEL_IMPORT_QTY_MEASURE_RE,
    _enrich_confirmation_inner,
)
from app.application.chat_tool_intent import looks_like_explicit_workflow_tool_intent

logger = logging.getLogger(__name__)

from app.utils.operational_errors import RECOVERABLE_ERRORS

OPERATIONAL_ERRORS = RECOVERABLE_ERRORS


class AIChatExcelImportMixin:
    def _resolve_excel_path_for_import(
        excel_analysis: dict[str, Any], preview_data: dict[str, Any]
    ) -> str:
        fp = str(excel_analysis.get("file_path") or "").strip()
        if not fp and isinstance(preview_data, dict):
            fp = str(preview_data.get("file_path") or "").strip()
        return fp

    @staticmethod
    def _customer_hint_from_preview_grid(preview_data: dict[str, Any]) -> str:
        """与前端网格预览一致：从 grid_preview.rows[].text 解析抬头里的客户名（合并单元格常见）。"""
        if not isinstance(preview_data, dict):
            return ""
        gp = preview_data.get("grid_preview")
        if not isinstance(gp, dict):
            return ""
        grid_rows = gp.get("rows")
        if not isinstance(grid_rows, list):
            return ""
        try:
            from app.application.template_grid_core import _extract_inline_customer_hits_from_cell
        except RECOVERABLE_ERRORS:
            return ""
        for row in grid_rows[:22]:
            if not isinstance(row, list):
                continue
            parts: list[str] = []
            for cell in row:
                if not isinstance(cell, dict):
                    continue
                t = str(cell.get("text") or "").strip()
                if not t:
                    continue
                hits = _extract_inline_customer_hits_from_cell(t)
                if hits:
                    return hits[0]
                parts.append(t)
            joined = " ".join(parts).strip()
            if joined:
                hits = _extract_inline_customer_hits_from_cell(joined)
                if hits:
                    return hits[0]
        return ""

    @staticmethod
    def _excel_cell_looks_like_product_measure_unit(value: Any) -> bool:
        """单元格是否为 SKU 计量单位（非客户全称），用于入库时避免把「件」当成客户。"""
        t = str(value or "").strip()
        if not t:
            return False
        if t.lower() in _EXCEL_IMPORT_MEASURE_UNIT_TOKENS:
            return True
        return bool(_EXCEL_IMPORT_QTY_MEASURE_RE.match(t))

    @classmethod
    def _default_purchase_unit_for_import(
        cls,
        excel_analysis: dict[str, Any],
        preview_data: dict[str, Any],
        request_context: dict[str, Any] | None = None,
    ) -> str:
        """
        默认客户：优先读表内「客户」类标签与标题区公司名；文档没有时再退回文件名推断。
        """
        logger.debug(
            "[导入调试] _default_purchase_unit_for_import 开始, request_context type: %s",
            type(request_context).__name__,
        )
        if isinstance(request_context, dict):
            hint = str(request_context.get("excel_customer_hint") or "").strip()
            logger.debug("[导入调试] request_context.excel_customer_hint = %s", repr(hint))
            if hint:
                return hint
        if isinstance(preview_data, dict):
            hint = str(
                preview_data.get("customer_hint")
                or preview_data.get("document_customer")
                or excel_analysis.get("customer_hint")
                or ""
            ).strip()
            logger.debug("[导入调试] preview_data/excel_analysis customer_hint = %s", repr(hint))
            if hint:
                return hint
        grid_hint = cls._customer_hint_from_preview_grid(preview_data)
        if grid_hint:
            return grid_hint
        fp = cls._resolve_excel_path_for_import(excel_analysis, preview_data)
        sheet = cls._resolve_sheet_name_for_reimport(excel_analysis, preview_data, request_context)
        if fp:
            path = Path(fp)
            if path.is_file():
                try:
                    from app.application.template_grid_core import _extract_customer_hint_from_excel

                    doc_unit = str(
                        _extract_customer_hint_from_excel(str(path), sheet) or ""
                    ).strip()
                    if doc_unit:
                        return doc_unit
                except RECOVERABLE_ERRORS as err:
                    logger.debug("从工作簿读取客户提示失败: %s", err)
        return cls._guess_default_purchase_unit(excel_analysis)

    @staticmethod
    def _guess_default_purchase_unit(excel_analysis: dict[str, Any]) -> str:
        """
        仅作兜底：报价类文件无表内客户信息时，用文件名猜测公司名。
        """
        name = str(
            excel_analysis.get("file_name") or excel_analysis.get("template_name") or ""
        ).strip()
        fp = str(excel_analysis.get("file_path") or "").strip()
        if not name and fp:
            name = Path(fp).name
        stem = Path(name).stem if name else ""
        stem = str(stem).strip()
        if not stem:
            return ""
        stem = re.sub(r"\d{2,4}年?$", "", stem).strip()
        for token in ("产品报价表", "报价表", "报价单", "价格表", "产品报价", "报价"):
            if stem.endswith(token):
                stem = stem[: -len(token)].strip()
        company_suffixes = (
            "股份有限公司",
            "集团有限公司",
            "实业有限公司",
            "有限公司",
            "科技公司",
            "集团公司",
            "公司",
            "厂",
            "店",
        )
        for end in range(2, len(stem) + 1):
            prefix = stem[:end]
            if prefix.endswith(company_suffixes):
                return prefix.strip()
        return stem if len(stem) >= 2 else ""

    @staticmethod
    def _sanitize_import_scalar(val: Any) -> Any:
        """pandas/openpyxl 空值与 nan，避免参与字段推断时出现字面量 'nan'。"""
        if val is None:
            return None
        if isinstance(val, float) and math.isnan(val):
            return None
        if isinstance(val, str):
            s = val.strip()
            if s.lower() in ("nan", "none", "nat", "<na>", "null"):
                return None
            return s
        try:
            fv = float(val)
            if fv != fv:
                return None
        except (TypeError, ValueError):
            pass
        return val

    @staticmethod
    def _resolve_force_header_row_1based(
        excel_analysis: dict[str, Any], preview_data: dict[str, Any]
    ) -> int | None:
        """与前端 slim 上下文中的 grid_preview.header_row_index / tables[].header_row 对齐。"""
        pd = preview_data if isinstance(preview_data, dict) else {}
        gp = pd.get("grid_preview") if isinstance(pd.get("grid_preview"), dict) else {}
        for key in ("header_row_index",):
            raw = gp.get(key)
            if raw is not None:
                try:
                    n = int(raw)
                    if n >= 1:
                        return n
                except (TypeError, ValueError):
                    pass
        tables = pd.get("tables")
        if isinstance(tables, list):
            for t in tables:
                if not isinstance(t, dict):
                    continue
                raw = t.get("header_row")
                if raw is not None:
                    try:
                        n = int(raw)
                        if n >= 1:
                            return n
                    except (TypeError, ValueError):
                        pass
        sheets = (
            excel_analysis.get("sheets") if isinstance(excel_analysis.get("sheets"), list) else None
        )
        if sheets:
            for s in sheets:
                if not isinstance(s, dict):
                    continue
                st = s.get("tables")
                if isinstance(st, list):
                    for t in st:
                        if not isinstance(t, dict):
                            continue
                        raw = t.get("header_row")
                        if raw is not None:
                            try:
                                n = int(raw)
                                if n >= 1:
                                    return n
                            except (TypeError, ValueError):
                                pass
                sg = s.get("grid_preview") if isinstance(s.get("grid_preview"), dict) else {}
                raw = sg.get("header_row_index")
                if raw is not None:
                    try:
                        n = int(raw)
                        if n >= 1:
                            return n
                    except (TypeError, ValueError):
                        pass
        return None

    @staticmethod
    def _resolve_sheet_name_for_reimport(
        excel_analysis: dict[str, Any],
        preview_data: dict[str, Any],
        request_context: dict[str, Any] | None = None,
    ) -> str | None:
        if isinstance(request_context, dict):
            sel = request_context.get("excel_analysis_selected_sheet")
            if isinstance(sel, dict):
                sn = str(sel.get("sheet_name") or "").strip()
                if sn:
                    return sn
            ps = str(request_context.get("preferred_sheet_name") or "").strip()
            if ps:
                return ps
        if isinstance(preview_data, dict):
            for key in ("selected_sheet_name", "sheet_name"):
                v = preview_data.get(key)
                if v and str(v).strip():
                    return str(v).strip()
        sheets = (
            excel_analysis.get("sheets") if isinstance(excel_analysis.get("sheets"), list) else None
        )
        if sheets and isinstance(sheets[0], dict):
            sn = sheets[0].get("sheet_name")
            if sn and str(sn).strip():
                return str(sn).strip()
        return None

    @staticmethod
    def _try_structured_reload_records(
        excel_analysis: dict[str, Any],
        preview_data: dict[str, Any],
        request_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        """
        聊天上下文里的 sample_rows 常来自 pandas（Unnamed 列）或已被截断；若服务器上仍有原文件，
        默认用 openpyxl 表头识别重读；若 preview_data.parse_mode 为 rectangular，则按矩形区域全读（列键 A/B/…），
        不再依赖推断的数据表头行。
        """
        fp = str(excel_analysis.get("file_path") or "").strip() or (
            str(preview_data.get("file_path") or "").strip()
            if isinstance(preview_data, dict)
            else ""
        )
        if not fp:
            return None
        from fastapi import HTTPException

        from app.infrastructure.workspace import (
            resolve_existing_file_under_root,
            workspace_root,
        )
        from app.utils.path_utils import get_upload_dir

        normalized = fp.replace("\\", "/")
        workspace_base = workspace_root()
        workspace_text = workspace_base.as_posix().rstrip("/")
        path: Path | None = None
        root: Path | None = None
        relative_path = ""
        if normalized.startswith(f"{workspace_text}/"):
            root = workspace_base
            relative_path = normalized[len(workspace_text) + 1 :]
        elif not normalized.startswith("/") and not (
            len(normalized) >= 3 and normalized[1:3] == ":/"
        ):
            root = workspace_base
            relative_path = normalized
        else:
            upload_base = Path(get_upload_dir()).resolve()
            upload_text = upload_base.as_posix().rstrip("/")
            if normalized.startswith(f"{upload_text}/"):
                raw_upload_name = normalized[len(upload_text) + 1 :]
                if "/" not in raw_upload_name:
                    root = upload_base
                    relative_path = raw_upload_name
        if root is None:
            return None
        try:
            path = resolve_existing_file_under_root(root, relative_path)
        except (ValueError, OSError, HTTPException):
            return None
        sheet = AIChatExcelImportMixin._resolve_sheet_name_for_reimport(
            excel_analysis, preview_data, request_context
        )
        force_hdr = AIChatExcelImportMixin._resolve_force_header_row_1based(
            excel_analysis, preview_data
        )
        try:
            pd0 = preview_data if isinstance(preview_data, dict) else {}
            if str(pd0.get("parse_mode") or "").strip().lower() == "rectangular":
                from app.application.template_grid_core import _extract_rectangular_excel_preview

                structured = _extract_rectangular_excel_preview(str(path), sheet_name=sheet)
            else:
                from app.application.template_grid_core import _extract_structured_excel_preview

                structured = _extract_structured_excel_preview(
                    str(path),
                    sheet_name=sheet,
                    sample_limit=800,
                    force_header_row_1based=force_hdr,
                )
            rows = structured.get("sample_rows") or []
            if not isinstance(rows, list) or not rows:
                return None
            out: list[dict[str, Any]] = []
            for row in rows:
                if isinstance(row, dict):
                    out.append(
                        {
                            k: AIChatExcelImportMixin._sanitize_import_scalar(v)
                            for k, v in row.items()
                        }
                    )
            return out or None
        except RECOVERABLE_ERRORS as err:
            logger.debug("结构化重读 Excel 跳过: %s", err)
            return None

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

    _PACK_OR_MEASURE_RE = re.compile(
        r"^\s*\d+(\.\d+)?\s*[/／]\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|桶|箱|组|套|升|L|l)?\s*$"
        r"|^\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|ml|ML|l|L|升|斤|吨)\s*[/／]\s*(桶|箱|组|套|包|袋|罐|个|只)\s*$"
        r"|^\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|ml|ML|l|L|升|斤|吨|桶|箱|包|袋|罐|套|组|个|只|张|米|㎡|cm|CM|mm|MM)\s*$"
        r"|^\s*(桶|箱|包|袋|罐|套|组|个|只|张|升|公斤|千克|斤)\s*$",
        re.I,
    )

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
        before, after, generic = AIChatExcelImportMixin._price_column_buckets(keyset)
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

    def _extract_excel_import_records(
        self,
        excel_analysis: dict[str, Any],
        request_context: dict[str, Any] | None = None,
        *,
        user_message: str = "",
    ) -> tuple[list[dict[str, Any]], str | None]:
        preview_data = (
            excel_analysis.get("preview_data")
            if isinstance(excel_analysis.get("preview_data"), dict)
            else {}
        )
        preview_data = preview_data or {}
        records: list[dict[str, Any]] = []

        reloaded = self._try_structured_reload_records(
            excel_analysis, preview_data, request_context
        )
        if reloaded:
            records = reloaded
        else:
            sample_rows = preview_data.get("sample_rows") or []
            if isinstance(sample_rows, list):
                for row in sample_rows:
                    if isinstance(row, dict):
                        records.append(dict(row))

            grid_rows = (preview_data.get("grid_preview") or {}).get("rows") or []
            if isinstance(grid_rows, list) and len(grid_rows) >= 2:
                header = grid_rows[0]
                if isinstance(header, list):
                    header_keys = [str(h or "").strip() for h in header]
                    for row in grid_rows[1:]:
                        if not isinstance(row, list):
                            continue
                        item: dict[str, Any] = {}
                        for idx, key in enumerate(header_keys):
                            if not key:
                                continue
                            item[key] = row[idx] if idx < len(row) else None
                        if any(str(v or "").strip() for v in item.values()):
                            records.append(item)

        # 某些表格第一行是“真实表头”，但被解析为数据行（键名为 Unnamed:*）
        if records:
            first = records[0]
            if isinstance(first, dict):
                keys = list(first.keys())
                key_unnamed_ratio = 0.0
                if keys:
                    unnamed_count = sum(1 for k in keys if str(k).startswith("Unnamed:"))
                    key_unnamed_ratio = unnamed_count / len(keys)
                header_values = [str(first.get(k) or "").strip() for k in keys]
                label_like_ratio = sum(
                    1 for v in header_values if v and not self._is_number_text(v)
                ) / float(len(header_values) or 1)
                headerish = self._row_values_look_like_table_headers(header_values)
                should_promote = len(records) >= 2 and (
                    (key_unnamed_ratio >= 0.5 and label_like_ratio >= 0.5)
                    or (key_unnamed_ratio >= 0.35 and headerish)
                )
                if should_promote:
                    rebuilt: list[dict[str, Any]] = []
                    for row in records[1:]:
                        if not isinstance(row, dict):
                            continue
                        mapped: dict[str, Any] = {}
                        for idx, key in enumerate(keys):
                            header = header_values[idx] if idx < len(header_values) else ""
                            if not header:
                                continue
                            mapped[header] = row.get(key)
                        if any(str(v or "").strip() for v in mapped.values()):
                            rebuilt.append(mapped)
                    if rebuilt:
                        records = rebuilt

        records = [
            (
                {k: self._sanitize_import_scalar(v) for k, v in r.items()}
                if isinstance(r, dict)
                else r
            )
            for r in records
        ]

        if not records:
            return [], None

        inferred_roles, role_conf = self._infer_excel_column_roles(records)
        if role_conf < 0.55:
            llm_roles = self._infer_excel_column_roles_with_llm(records)
            # 低置信度时优先采用 LLM 非空结果，空值回退特征推断
            for role in ("unit_name", "product_name", "model_number", "unit_price"):
                if llm_roles.get(role):
                    inferred_roles[role] = llm_roles[role]

        header_roles = self._header_hint_column_roles(
            [str(k).strip() for k in records[0].keys()] if records else []
        )
        for role in ("unit_name", "product_name", "model_number", "unit_price"):
            hk = str(header_roles.get(role) or "").strip()
            if hk:
                inferred_roles[role] = hk

        keys = [str(k).strip() for k in records[0].keys() if str(k).strip()]
        merged_intent = self._merge_user_intent_for_price_resolution(user_message, request_context)
        overrides = (
            request_context.get("excel_import_column_overrides")
            if isinstance(request_context, dict)
            else None
        )
        cur_price = str(inferred_roles.get("unit_price") or "").strip()
        price_col, price_err = self._resolve_unit_price_column(
            keys, cur_price, merged_intent, overrides if isinstance(overrides, dict) else {}
        )
        if price_err:
            return [], price_err
        inferred_roles["unit_price"] = price_col

        unit_key = inferred_roles.get("unit_name", "")
        product_key = inferred_roles.get("product_name", "")
        model_key = inferred_roles.get("model_number", "")
        price_key = inferred_roles.get("unit_price", "")

        default_unit = self._default_purchase_unit_for_import(
            excel_analysis, preview_data, request_context
        )
        logger.debug(
            "[导入调试] _default_purchase_unit_for_import 返回: %s (request_context keys: %s)",
            repr(default_unit),
            (
                list(request_context.keys())
                if isinstance(request_context, dict)
                else type(request_context).__name__
            ),
        )
        if unit_key:
            col_vals = [str((row or {}).get(unit_key) or "").strip() for row in records]
            if self._packaging_or_measure_ratio(col_vals) >= 0.45:
                unit_key = ""
        if unit_key and unit_key == product_key:
            unit_key = ""
        if unit_key and product_key and unit_key == model_key:
            unit_key = ""

        reserved_cols = {c for c in (unit_key, product_key, model_key, price_key) if c}
        if not product_key:
            fb_name = self._fallback_excel_product_name_column(records, reserved_cols)
            if fb_name:
                product_key = fb_name
                reserved_cols.add(fb_name)
        if not model_key:
            fb_model = self._fallback_excel_model_number_column(records, reserved_cols)
            if fb_model:
                model_key = fb_model

        dedup: set[tuple[str, str, str]] = set()
        normalized: list[dict[str, Any]] = []
        for row in records:
            unit_name = str((row or {}).get(unit_key) or "").strip() if unit_key else ""
            if (
                not unit_name
                and default_unit
                or (
                    default_unit
                    and unit_name
                    and self._excel_cell_looks_like_product_measure_unit(unit_name)
                )
            ):
                unit_name = default_unit.strip()
            product_name = str((row or {}).get(product_key) or "").strip() if product_key else ""
            model_number = (
                str((row or {}).get(model_key) or "").strip().upper() if model_key else ""
            )
            price_text = str((row or {}).get(price_key) or "").strip() if price_key else ""
            try:
                unit_price = float(price_text) if price_text else 0.0
            except RECOVERABLE_ERRORS:
                unit_price = 0.0
            if not unit_name:
                continue
            if not product_name and not model_number:
                continue
            dedup_key = (unit_name, product_name, model_number)
            if dedup_key in dedup:
                continue
            dedup.add(dedup_key)
            normalized.append(
                {
                    "unit_name": unit_name,
                    "product_name": product_name or model_number,
                    "model_number": model_number,
                    "unit_price": unit_price,
                }
            )
        return normalized, None

    @staticmethod
    def _excel_analysis_payload_present(context: dict[str, Any] | None) -> bool:
        """请求里是否带有可用的 excel_analysis（与 extract-grid 结构一致）。"""
        ea = (context or {}).get("excel_analysis") if isinstance(context, dict) else None
        if not isinstance(ea, dict) or not ea:
            return False
        if str(ea.get("summary") or "").strip():
            return True
        fields = ea.get("fields")
        if isinstance(fields, list) and len(fields) > 0:
            return True
        pd = ea.get("preview_data") if isinstance(ea.get("preview_data"), dict) else {}
        if isinstance(pd.get("sample_rows"), list) and len(pd.get("sample_rows")) > 0:
            return True
        grid = (pd.get("grid_preview") or {}).get("rows") if isinstance(pd, dict) else None
        return isinstance(grid, list) and len(grid) >= 2

    @staticmethod
    def _looks_like_short_excel_import_command(text: str) -> bool:
        """
        用户常用短指令（如「加入数据库」）。无 excel_analysis 时若落入 DeepSeek / planner 会长时间无响应。
        """
        t = str(text or "").strip()
        if not t:
            return False
        exact = {
            "加入数据库",
            "加入库",
            "入库",
            "添加到库",
            "写入数据库",
            "导入数据库",
        }
        if t in exact:
            return True
        if len(t) > 40:
            return False
        return any(
            k in t
            for k in (
                "加入数据库",
                "导入数据库",
                "添加到库",
                "写入数据库",
            )
        )

    @staticmethod
    def _looks_like_explicit_workflow_tool_intent(text: str) -> bool:
        return looks_like_explicit_workflow_tool_intent(text)

    @staticmethod
    def _looks_like_smart_workflow_intent(text: str, context: dict[str, Any] | None = None) -> bool:
        """Whether a non-pro chat turn should be allowed into executable planning.

        This keeps casual chat on the lightweight path, but lets ordinary
        desktop/mobile chat use the same agentic tool routing as pro mode for
        concrete tool/data/employee/file requests.
        """
        t = str(text or "").strip()
        if not t:
            return False
        if AIChatExcelImportMixin._looks_like_explicit_workflow_tool_intent(t):
            return True

        ctx = context if isinstance(context, dict) else {}
        for key in (
            "excel_analysis",
            "file_analysis",
            "file_context",
            "multimodal_attachments",
            "attachments",
            "files",
            "artifacts",
            "ocr",
            "ocr_result",
            "excel_index_id",
            "excel_vector_index_id",
        ):
            if ctx.get(key):
                return True

        lower = t.lower()
        controlled_db = any(
            k in t
            for k in (
                "数据库",
                "查库",
                "读库",
                "写库",
                "业务库",
                "产品库",
                "客户库",
                "物料库",
                "原材料",
                "发货记录",
                "出货记录",
            )
        ) or any(k in lower for k in ("database", " db ", "business_db", "products table"))
        controlled_action = any(
            k in t
            for k in (
                "查",
                "查询",
                "读取",
                "统计",
                "多少",
                "几条",
                "列出",
                "新增",
                "添加",
                "写入",
                "更新",
                "删除",
                "导入",
                "入库",
            )
        ) or any(k in lower for k in ("read", "query", "count", "list", "write", "update"))
        if controlled_db and controlled_action:
            return True

        employee_request = any(k in t for k in ("员工", "超级员工", "调用", "交给", "执行")) or any(
            k in lower for k in ("employee", "agent", "run", "execute")
        )
        if employee_request and any(k in t for k in ("员工", "超级员工", "调用", "交给")):
            return True

        return False

    @staticmethod
    def _attach_deterministic_workflow_trace(
        payload: dict[str, Any],
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any] | None,
        intent: str,
        file_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run
        except RECOVERABLE_ERRORS:
            logger.exception("AgentRun 追踪模块不可用，跳过 deterministic workflow trace")
            return payload

        runtime_context = dict(context or {}) if isinstance(context, dict) else {}
        runtime_context["workflow_intent"] = intent
        runtime_context["workflow_trace_mode"] = "deterministic_shortcut"
        if isinstance(file_context, dict) and file_context:
            runtime_context["file_context"] = file_context
        return attach_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel="deterministic_workflow",
            intent=intent,
        )

    def _start_deterministic_import_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any] | None,
        file_context: dict[str, Any] | None,
        plan,
        thinking_steps: str,
    ) -> dict[str, Any]:
        from app.application.agent_orchestrator import AgentOrchestrator

        runtime_ctx = self._merge_tool_runtime_context(user_id, message, context)
        runtime_ctx["source"] = str(source or "").strip()
        runtime_ctx["workflow_trace_mode"] = "agent_orchestrator"
        runtime_ctx["deterministic_workflow"] = True
        if isinstance(file_context, dict) and file_context:
            runtime_ctx["file_context"] = dict(file_context)

        agent_run = AgentOrchestrator().start_run_from_plan(
            user_id=user_id,
            message=message,
            plan=plan,
            runtime_context=runtime_ctx,
            auto_execute=True,
        )
        if agent_run.status != "waiting_user":
            return self._format_agent_run_response(
                plan,
                agent_run,
                thinking_steps=thinking_steps,
                user_message=str(message or ""),
            )

        blocking_nodes = [step.node_id for step in agent_run.steps if step.status == "waiting_user"]
        artifact_payloads = [
            artifact.to_dict() for artifact in getattr(agent_run, "artifacts", []) or []
        ]
        self._pending_workflows[user_id] = {
            "plan": plan,
            "runtime_context": runtime_ctx,
            "pending_id": uuid.uuid4().hex,
            "agent_run_id": agent_run.run_id,
            "thinking_steps": thinking_steps,
            "approval_required": False,
            "approval_nodes": [],
        }
        todo_text = "\n".join(f"- {step}" for step in (getattr(plan, "todo_steps", None) or []))
        response_text = (
            "我已生成导入工作流计划：\n"
            f"{thinking_steps}\n\n"
            f"{todo_text}\n\n"
            f"检测到写库步骤（{', '.join(blocking_nodes) or 'import'}），"
            "回复「确认」继续执行，回复「取消」终止。"
        )
        inner = {
            "run_id": agent_run.run_id,
            "agent_run_id": agent_run.run_id,
            "plan_id": plan.plan_id,
            "intent": plan.intent,
            "thinking_steps": thinking_steps,
            "todo": plan.todo_steps,
            "artifact_count": len(artifact_payloads),
            "artifacts": artifact_payloads,
            "blocking_nodes": blocking_nodes,
            "reason": "导入会写入业务数据库，需确认后执行",
            "approval_required": False,
            "approval_nodes": [],
        }
        return {
            "success": True,
            "message": "处理完成",
            "response": response_text,
            "run_id": agent_run.run_id,
            "agent_run_id": agent_run.run_id,
            "data": {
                "text": response_text,
                "action": "workflow_confirmation_required",
                "run_id": agent_run.run_id,
                "agent_run_id": agent_run.run_id,
                "data": _enrich_confirmation_inner(inner, action="workflow_confirmation_required"),
            },
        }
