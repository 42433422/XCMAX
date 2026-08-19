# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.ai_chat.excel_import_pipeline')

class _AIChatExcelImportMixinPart01Mixin:

    @staticmethod
    def _resolve_excel_path_for_import(excel_analysis: dict[str, _facade().Any], preview_data: dict[str, _facade().Any]) -> str:
        fp = str(excel_analysis.get('file_path') or '').strip()
        if not fp and isinstance(preview_data, dict):
            fp = str(preview_data.get('file_path') or '').strip()
        return fp

    @staticmethod
    def _customer_hint_from_preview_grid(preview_data: dict[str, _facade().Any]) -> str:
        """与前端网格预览一致：从 grid_preview.rows[].text 解析抬头里的客户名（合并单元格常见）。"""
        if not isinstance(preview_data, dict):
            return ''
        gp = preview_data.get('grid_preview')
        if not isinstance(gp, dict):
            return ''
        grid_rows = gp.get('rows')
        if not isinstance(grid_rows, list):
            return ''
        try:
            from app.application.template_grid_core import _extract_inline_customer_hits_from_cell
        except _facade().RECOVERABLE_ERRORS:
            return ''
        for row in grid_rows[:22]:
            if not isinstance(row, list):
                continue
            parts: list[str] = []
            for cell in row:
                if not isinstance(cell, dict):
                    continue
                t = str(cell.get('text') or '').strip()
                if not t:
                    continue
                hits = _extract_inline_customer_hits_from_cell(t)
                if hits:
                    return hits[0]
                parts.append(t)
            joined = ' '.join(parts).strip()
            if joined:
                hits = _extract_inline_customer_hits_from_cell(joined)
                if hits:
                    return hits[0]
        return ''

    @staticmethod
    def _excel_cell_looks_like_product_measure_unit(value: _facade().Any) -> bool:
        """单元格是否为 SKU 计量单位（非客户全称），用于入库时避免把「件」当成客户。"""
        t = str(value or '').strip()
        if not t:
            return False
        if t.lower() in _facade()._EXCEL_IMPORT_MEASURE_UNIT_TOKENS:
            return True
        return bool(_facade()._EXCEL_IMPORT_QTY_MEASURE_RE.match(t))

    @classmethod
    def _default_purchase_unit_for_import(cls, excel_analysis: dict[str, _facade().Any], preview_data: dict[str, _facade().Any], request_context: dict[str, _facade().Any] | None=None) -> str:
        """
        默认客户：优先读表内「客户」类标签与标题区公司名；文档没有时再退回文件名推断。
        """
        _facade().logger.debug('[导入调试] _default_purchase_unit_for_import 开始, request_context type: %s', type(request_context).__name__)
        if isinstance(request_context, dict):
            hint = str(request_context.get('excel_customer_hint') or '').strip()
            _facade().logger.debug('[导入调试] request_context.excel_customer_hint = %s', repr(hint))
            if hint:
                return hint
        if isinstance(preview_data, dict):
            hint = str(preview_data.get('customer_hint') or preview_data.get('document_customer') or excel_analysis.get('customer_hint') or '').strip()
            _facade().logger.debug('[导入调试] preview_data/excel_analysis customer_hint = %s', repr(hint))
            if hint:
                return hint
        grid_hint = cls._customer_hint_from_preview_grid(preview_data)
        if grid_hint:
            return grid_hint
        fp = cls._resolve_excel_path_for_import(excel_analysis, preview_data)
        sheet = cls._resolve_sheet_name_for_reimport(excel_analysis, preview_data, request_context)
        if fp:
            path = _facade().Path(fp)
            if path.is_file():
                try:
                    from app.application.template_grid_core import _extract_customer_hint_from_excel
                    doc_unit = str(_extract_customer_hint_from_excel(str(path), sheet) or '').strip()
                    if doc_unit:
                        return doc_unit
                except _facade().RECOVERABLE_ERRORS as err:
                    _facade().logger.debug('从工作簿读取客户提示失败: %s', err)
        return cls._guess_default_purchase_unit(excel_analysis)

    @staticmethod
    def _guess_default_purchase_unit(excel_analysis: dict[str, _facade().Any]) -> str:
        """
        仅作兜底：报价类文件无表内客户信息时，用文件名猜测公司名。
        """
        name = str(excel_analysis.get('file_name') or excel_analysis.get('template_name') or '').strip()
        fp = str(excel_analysis.get('file_path') or '').strip()
        if not name and fp:
            name = _facade().Path(fp).name
        stem = _facade().Path(name).stem if name else ''
        stem = str(stem).strip()
        if not stem:
            return ''
        stem = _facade().re.sub('\\d{2,4}年?$', '', stem).strip()
        for token in ('产品报价表', '报价表', '报价单', '价格表', '产品报价', '报价'):
            if stem.endswith(token):
                stem = stem[:-len(token)].strip()
        company_suffixes = ('股份有限公司', '集团有限公司', '实业有限公司', '有限公司', '科技公司', '集团公司', '公司', '厂', '店')
        for end in range(2, len(stem) + 1):
            prefix = stem[:end]
            if prefix.endswith(company_suffixes):
                return prefix.strip()
        return stem if len(stem) >= 2 else ''

    @staticmethod
    def _sanitize_import_scalar(val: _facade().Any) -> _facade().Any:
        """pandas/openpyxl 空值与 nan，避免参与字段推断时出现字面量 'nan'。"""
        if val is None:
            return None
        if isinstance(val, float) and _facade().math.isnan(val):
            return None
        if isinstance(val, str):
            s = val.strip()
            if s.lower() in ('nan', 'none', 'nat', '<na>', 'null'):
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
    def _resolve_force_header_row_1based(excel_analysis: dict[str, _facade().Any], preview_data: dict[str, _facade().Any]) -> int | None:
        """与前端 slim 上下文中的 grid_preview.header_row_index / tables[].header_row 对齐。"""
        pd = preview_data if isinstance(preview_data, dict) else {}
        gp = pd.get('grid_preview') if isinstance(pd.get('grid_preview'), dict) else {}
        for key in ('header_row_index',):
            if not isinstance(gp, dict):
                gp = {}
            raw = gp.get(key)
            if raw is not None:
                try:
                    n = int(raw)
                    if n >= 1:
                        return n
                except (TypeError, ValueError):
                    pass
        tables = pd.get('tables')
        if isinstance(tables, list):
            for t in tables:
                if not isinstance(t, dict):
                    continue
                raw = t.get('header_row')
                if raw is not None:
                    try:
                        n = int(raw)
                        if n >= 1:
                            return n
                    except (TypeError, ValueError):
                        pass
        sheets = excel_analysis.get('sheets') if isinstance(excel_analysis.get('sheets'), list) else None
        if sheets:
            for s in sheets:
                if not isinstance(s, dict):
                    continue
                st = s.get('tables')
                if isinstance(st, list):
                    for t in st:
                        if not isinstance(t, dict):
                            continue
                        raw = t.get('header_row')
                        if raw is not None:
                            try:
                                n = int(raw)
                                if n >= 1:
                                    return n
                            except (TypeError, ValueError):
                                pass
                sg = s.get('grid_preview') if isinstance(s.get('grid_preview'), dict) else {}
                if not isinstance(sg, dict):
                    sg = {}
                raw = sg.get('header_row_index')
                if raw is not None:
                    try:
                        n = int(raw)
                        if n >= 1:
                            return n
                    except (TypeError, ValueError):
                        pass
        return None

    @staticmethod
    def _resolve_sheet_name_for_reimport(excel_analysis: dict[str, _facade().Any], preview_data: dict[str, _facade().Any], request_context: dict[str, _facade().Any] | None=None) -> str | None:
        if isinstance(request_context, dict):
            sel = request_context.get('excel_analysis_selected_sheet')
            if isinstance(sel, dict):
                sn = str(sel.get('sheet_name') or '').strip()
                if sn:
                    return sn
            ps = str(request_context.get('preferred_sheet_name') or '').strip()
            if ps:
                return ps
        if isinstance(preview_data, dict):
            for key in ('selected_sheet_name', 'sheet_name'):
                v = preview_data.get(key)
                if v and str(v).strip():
                    return str(v).strip()
        sheets = excel_analysis.get('sheets') if isinstance(excel_analysis.get('sheets'), list) else None
        if sheets and isinstance(sheets[0], dict):
            sn = str(sheets[0].get('sheet_name') or '')
            if sn and str(sn).strip():
                return str(sn).strip()
        return None

    @staticmethod
    def _try_structured_reload_records(excel_analysis: dict[str, _facade().Any], preview_data: dict[str, _facade().Any], request_context: dict[str, _facade().Any] | None=None) -> list[dict[str, _facade().Any]] | None:
        """
        聊天上下文里的 sample_rows 常来自 pandas（Unnamed 列）或已被截断；若服务器上仍有原文件，
        默认用 openpyxl 表头识别重读；若 preview_data.parse_mode 为 rectangular，则按矩形区域全读（列键 A/B/…），
        不再依赖推断的数据表头行。
        """
        fp = str(excel_analysis.get('file_path') or '').strip() or (str(preview_data.get('file_path') or '').strip() if isinstance(preview_data, dict) else '')
        if not fp:
            return None
        from fastapi import HTTPException
        from app.infrastructure.workspace import resolve_existing_file_under_root, workspace_root
        from app.utils.path_io.path_utils import get_upload_dir
        normalized = fp.replace('\\', '/')
        workspace_base = workspace_root()
        workspace_text = workspace_base.as_posix().rstrip('/')
        path: _facade().Path | None = None
        root: _facade().Path | None = None
        relative_path = ''
        if normalized.startswith(f'{workspace_text}/'):
            root = workspace_base
            relative_path = normalized[len(workspace_text) + 1:]
        elif not normalized.startswith('/') and (not (len(normalized) >= 3 and normalized[1:3] == ':/')):
            root = workspace_base
            relative_path = normalized
        else:
            upload_base = _facade().Path(get_upload_dir()).resolve()
            upload_text = upload_base.as_posix().rstrip('/')
            if normalized.startswith(f'{upload_text}/'):
                raw_upload_name = normalized[len(upload_text) + 1:]
                if '/' not in raw_upload_name:
                    root = upload_base
                    relative_path = raw_upload_name
        if root is None:
            return None
        try:
            path = resolve_existing_file_under_root(root, relative_path)
        except (ValueError, OSError, HTTPException):
            return None
        sheet = _facade().AIChatExcelImportMixin._resolve_sheet_name_for_reimport(excel_analysis, preview_data, request_context)
        force_hdr = _facade().AIChatExcelImportMixin._resolve_force_header_row_1based(excel_analysis, preview_data)
        try:
            pd0 = preview_data if isinstance(preview_data, dict) else {}
            if str(pd0.get('parse_mode') or '').strip().lower() == 'rectangular':
                from app.application.template_grid_core import _extract_rectangular_excel_preview
                structured = _extract_rectangular_excel_preview(str(path), sheet_name=sheet)
            else:
                from app.application.template_grid_core import _extract_structured_excel_preview
                structured = _extract_structured_excel_preview(str(path), sheet_name=sheet, sample_limit=800, force_header_row_1based=force_hdr)
            rows = structured.get('sample_rows') or []
            if not isinstance(rows, list) or not rows:
                return None
            out: list[dict[str, _facade().Any]] = []
            for row in rows:
                if isinstance(row, dict):
                    out.append({k: _facade().AIChatExcelImportMixin._sanitize_import_scalar(v) for (k, v) in row.items()})
            return out or None
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.debug('结构化重读 Excel 跳过: %s', err)
            return None

    @staticmethod
    def _model_like_score(value: str) -> float:
        text = str(value or '').strip()
        if not text:
            return 0.0
        has_digit = any((ch.isdigit() for ch in text))
        has_alpha = any((ch.isalpha() for ch in text))
        compact = text.replace('-', '').replace('_', '')
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
        nonempty = [str(v or '').strip() for v in values if str(v or '').strip()]
        if not nonempty:
            return 0.0
        hit = 0
        for v in nonempty:
            if cls._PACK_OR_MEASURE_RE.match(v):
                hit += 1
                continue
            if v in {'件', '个', '只', '箱', '盒', '包', '袋', '瓶', '桶', '罐', '套', '组', '台', '条', '张', '支'}:
                hit += 1
        return hit / float(len(nonempty))

    @staticmethod
    def _header_hint_column_roles(keys: list[str]) -> dict[str, str]:
        """
        表头 → 客户/名称/型号/单价 四角色：词条来自 ``resources/config/ai_db_field_index.json`` 中
        ``products`` 各列的 ``excel_synonyms_zh`` / ``api_aliases``，可按业务增删而无需改 Python。
        """
        empty_roles = {'unit_name': '', 'product_name': '', 'model_number': '', 'unit_price': ''}
        roles = dict(empty_roles)
        roles = {**empty_roles, **dict(roles or {})}
        for key in keys:
            text = str(key or '').strip()
            normalized = _facade().re.sub('[\\s:_：\\-_/（）()]+', '', text).lower()
            if not normalized:
                continue
            if normalized in {'客户', '客户名', '客户名称', '客户全称', '购买单位', '购货单位', '单位名称', '公司', '公司名称', '厂名'}:
                roles['unit_name'] = text
                continue
            if normalized in {'产品', '产品名', '产品名称', '商品', '商品名称', '品名', '名称', '物料名称'}:
                roles['product_name'] = text
                continue
            if normalized in {'型号', '规格型号', '产品型号', '编码', '产品编码', 'model', 'sku'}:
                roles['model_number'] = text
                continue
            if normalized in {'单价', '价格', '产品单价', '销售单价', '报价', 'unitprice', 'price'}:
                roles['unit_price'] = text
        return roles

    def _fallback_excel_product_name_column(self, records: list[dict[str, _facade().Any]], reserved: set[str]) -> str:
        """
        推断/LLM 未给出名称列时，从剩余列中选最像「产品描述」的一列，减轻聊天入库丢名称。
        """
        if not records or not isinstance(records[0], dict):
            return ''
        skip_re = _facade().re.compile('(序|序号|行号|单号|单据|^id$|^no\\.?$)', _facade().re.I)
        best_col = ''
        best_score = -1.0
        min_nonempty = max(1, min(3, len(records) // 4))
        for key in records[0].keys():
            sk = str(key or '').strip()
            if not sk or sk in reserved:
                continue
            if skip_re.search(sk):
                continue
            values = [str((row or {}).get(sk) or '').strip() for row in records]
            nonempty = [v for v in values if v]
            if len(nonempty) < min_nonempty:
                continue
            if self._packaging_or_measure_ratio(nonempty) >= 0.45:
                continue
            num_ratio = sum((1 for v in nonempty if self._is_number_text(v))) / float(len(nonempty))
            avg_len = sum((len(v) for v in nonempty)) / float(len(nonempty) or 1)
            score = (1.0 - num_ratio) * 0.5 + min(avg_len, 48.0) / 48.0 * 0.5
            if score > best_score:
                best_score = score
                best_col = sk
        return best_col if best_score >= 0.35 else ''

    def _fallback_excel_model_number_column(self, records: list[dict[str, _facade().Any]], reserved: set[str]) -> str:
        """未识别型号列时，在剩余列上按型号样字符串得分选列，减轻丢型号。"""
        if not records or not isinstance(records[0], dict):
            return ''
        best_col = ''
        best_score = -1.0
        for key in records[0].keys():
            sk = str(key or '').strip()
            if not sk or sk in reserved:
                continue
            values = [str((row or {}).get(sk) or '').strip() for row in records]
            nonempty = [v for v in values if v]
            if not nonempty:
                continue
            mr = sum((self._model_like_score(v) for v in nonempty)) / float(len(nonempty))
            if mr > best_score:
                best_score = mr
                best_col = sk
        return best_col if best_score >= 0.22 else ''
