"""Workflow tool registry + dispatcher + Excel/import handlers.

Phase 4B 从 ``app.legacy.tools`` 吸收实现。本模块汇总所有工作流工具的:

- 注册表 :func:`get_workflow_tool_registry` / :func:`_base_registry`
- 分派器 :func:`execute_workflow_tool`
- Excel 分析 / 查询 / 聚合 / 统计:`handle_excel_analysis`
- Excel 导入数据库:`_handle_import_excel_to_database` 及推断映射

Phase 4C：Excel 导入已拆至 ``workflow_import_excel.py``（本模块 re-export）。
后续可再拆 ``excel_handlers.py`` / ``registry.py`` / ``dispatcher.py``。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

from app.infrastructure.auth.db_token import configured_db_write_token  # noqa: F401
from app.infrastructure.excel.schema_service import ExcelSchemaUnderstandingService
from app.infrastructure.excel.text_to_pandas import _safe_exec_pandas
from app.utils.operational_errors import RECOVERABLE_ERRORS

_workflow_tool_registry_cache: list[dict[str, Any]] | None = None
_workflow_tool_registry_bulk_token_present: bool | None = None
_workflow_registry_cache_ver: int | None = None
# 递增以使进程内工具注册表缓存失效（新增工具时 bump）
_WORKFLOW_REG_VER = 2


from app.application.tools.workflow_excel_paths import resolve_safe_excel_path


def _parse_excel_header_row_1based(args: dict[str, Any]) -> int | None:
    raw = args.get("header_row")
    if raw is None or raw == "":
        raw = args.get("header_row_index")
    if raw is None or raw == "":
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def _read_excel_dataframe(
    p: Path,
    *,
    sheet_name: Any,
    header_row_1based: int | None,
) -> pd.DataFrame:
    kw: dict[str, Any] = {}
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        kw["engine"] = "openpyxl"
    if sheet_name:
        kw["sheet_name"] = sheet_name
    if header_row_1based is not None:
        kw["header"] = header_row_1based - 1
    return pd.read_excel(p, **kw)


def run_natural_language_pandas(
    df: pd.DataFrame, natural_language: str, **kwargs
) -> dict[str, Any]:
    """将自然语言查询转换为 pandas 操作并执行（接 excel_text_to_pandas）。"""
    generated_code = ""
    error_msg: str | None = None
    result_df = df

    try:
        from app.legacy.excel_text_to_pandas import ExcelTextToPandas

        converter = ExcelTextToPandas()
        code = converter.translate(natural_language, df)
        if code and code.strip():
            generated_code = code
            result_df = _safe_exec_pandas(code, df)
    except ValueError as e:
        error_msg = str(e)
    except RECOVERABLE_ERRORS as e:
        error_msg = str(e)

    records = json.loads(
        result_df.head(200).replace({float("nan"): None}).to_json(orient="records")
    )
    return {
        "generated_code": generated_code,
        "result_kind": "dataframe",
        "row_count": len(result_df),
        "truncated": len(result_df) > 200,
        "returned_rows": min(len(result_df), 200),
        "columns": list(result_df.columns.astype(str)),
        "records": records,
        **({"error": error_msg} if error_msg else {}),
    }


def handle_excel_analysis(
    args: dict[str, Any], workspace_root: str | None = None
) -> dict[str, Any]:
    file_path = str(args.get("file_path") or "")
    action = str(args.get("action") or "read")
    sheet_name = args.get("sheet_name")
    header_1b = _parse_excel_header_row_1based(args)
    if not file_path:
        return {"success": False, "error": "file_path is required"}
    root = workspace_root or str(Path.cwd())
    try:
        p = resolve_safe_excel_path(root, file_path)
    except RECOVERABLE_ERRORS as e:
        return {"success": False, "error": str(e), "workspace_root": root, "file_path": file_path}
    if not p.exists():
        return {
            "success": False,
            "error": "file not found",
            "file_path": file_path,
            "workspace_root": root,
            "resolved_path": str(p),
        }
    try:
        df = _read_excel_dataframe(p, sheet_name=sheet_name, header_row_1based=header_1b)
    except RECOVERABLE_ERRORS as e:
        return {
            "success": False,
            "error": f"read failed: {e}",
            "file_path": file_path,
            "resolved_path": str(p),
            "sheet_name": sheet_name,
            "header_row": header_1b,
        }
    if action == "excel_query":
        nl = str(args.get("natural_language") or "").strip()
        out = run_natural_language_pandas(df, nl, file_path=file_path)
        out["action"] = "excel_query"
        return out
    if action == "read":
        max_return = 200
        slice_df = df.head(max_return)
        out: dict[str, Any] = {
            "success": True,
            "action": action,
            "file_path": file_path,
            "sheet_name": sheet_name,
            "columns": list(df.columns.astype(str)),
            "row_count": int(len(df)),
            "returned_rows": int(len(slice_df)),
            "truncated": len(df) > max_return,
            "records": json.loads(slice_df.replace({float("nan"): None}).to_json(orient="records")),
        }
        try:
            from app.application.template_grid_core import _extract_customer_hint_from_excel

            customer_hint = str(
                _extract_customer_hint_from_excel(str(p), str(sheet_name).strip() or None) or ""
            ).strip()
            if customer_hint:
                out["customer_hint"] = customer_hint
        except RECOVERABLE_ERRORS:
            logger.debug("suppressed exception", exc_info=True)
        if header_1b is not None:
            out["header_row"] = header_1b
        return out
    if action == "query":
        expr = str(args.get("query_expression") or "").strip()
        out_df = df.query(expr) if expr else df
        return {
            "success": True,
            "action": "query",
            "file_path": file_path,
            "row_count": int(len(out_df)),
            "records": json.loads(
                out_df.head(200).replace({float("nan"): None}).to_json(orient="records")
            ),
            "columns": list(out_df.columns.astype(str)),
        }
    if action == "aggregate":
        group_by = [str(x) for x in (args.get("group_by") or []) if str(x)]
        metrics = args.get("metrics") or []
        if group_by and isinstance(metrics, list):
            agg_map: dict[str, list[str]] = {}
            for m in metrics:
                if not isinstance(m, dict):
                    continue
                col = str(m.get("column") or "").strip()
                op = str(m.get("op") or "").strip()
                if col and op:
                    agg_map.setdefault(col, []).append(op)
            if agg_map:
                out_df = df.groupby(group_by, dropna=False).agg(agg_map).reset_index()
                out_df.columns = [
                    (
                        "_".join([str(c) for c in x if str(c) != ""]).strip("_")
                        if isinstance(x, tuple)
                        else str(x)
                    )
                    for x in out_df.columns
                ]
            else:
                out_df = df
        else:
            out_df = df
        return {
            "success": True,
            "action": "aggregate",
            "file_path": file_path,
            "row_count": int(len(out_df)),
            "records": json.loads(
                out_df.head(200).replace({float("nan"): None}).to_json(orient="records")
            ),
            "columns": list(out_df.columns.astype(str)),
        }
    if action == "statistics":
        return {
            "success": True,
            "action": "statistics",
            "file_path": file_path,
            "row_count": int(len(df)),
            "dtypes": {str(k): str(v) for k, v in df.dtypes.items()},
        }
    return {"success": False, "error": f"unsupported_action:{action}"}


def _base_registry() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "excel_analysis",
                "description": "分析 Excel 文件内容，支持读取、查询、聚合等操作。在需要处理 Excel 数据时必须先调用此工具获取文件内容。如果用户选中了特定工作表，请使用 sheet_name 参数指定工作表名称。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Excel 文件路径（相对于工作区的相对路径或绝对路径）",
                        },
                        "sheet_name": {
                            "type": "string",
                            "description": "工作表名称（Sheet名），用于读取特定工作表。如果用户选中了某个工作表，请使用此参数指定。",
                        },
                        "header_row": {
                            "type": "integer",
                            "description": "表头所在行号（Excel 从 1 开始计数）。报价单等多行标题表格必须与上传预览 extract-grid 检测到的 header_row_index / tables[].header_row 一致，否则会出现 Unnamed 列、大量 nan、价格错位。",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["read", "query", "aggregate", "statistics"],
                            "description": "操作类型：read读取数据、query按条件查询、aggregate聚合统计、statistics统计信息",
                        },
                        "query_expression": {
                            "type": "string",
                            "description": "当 action=query 时使用的查询表达式（pandas query 语法）",
                        },
                        "group_by": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "当 action=aggregate 时的分组列名",
                        },
                        "metrics": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "column": {"type": "string"},
                                    "op": {
                                        "type": "string",
                                        "enum": ["sum", "mean", "count", "min", "max"],
                                    },
                                },
                            },
                            "description": "当 action=aggregate 时的聚合指标",
                        },
                    },
                    "required": ["file_path", "action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "excel_schema_understand",
                "description": "理解 Excel 文件的数据结构和 schema，返回列名、数据类型、样本数据等元信息。适合在分析前先了解文件结构。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Excel 文件路径（相对于工作区的相对路径或绝对路径）",
                        },
                        "sheet_name": {
                            "type": "string",
                            "description": "可选：工作表名称，默认第一个表。",
                        },
                        "header_row": {
                            "type": "integer",
                            "description": "可选：表头行号（Excel 从 1 开始）。多行标题表若不填则默认第一行为表头，易产生 Unnamed 列。",
                        },
                    },
                    "required": ["file_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "excel_join_compare",
                "description": "合并或对比两个 Excel 文件的数据。支持 join（合并）和 diff（差异对比）两种操作。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["join", "diff"],
                            "description": "操作类型：join合并、diff差异对比",
                        },
                        "file_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "当 action=join 时，两个文件的路径列表 [file1, file2]",
                        },
                        "file_path_a": {
                            "type": "string",
                            "description": "当 action=diff 时，第一个文件路径",
                        },
                        "file_path_b": {
                            "type": "string",
                            "description": "当 action=diff 时，第二个文件路径",
                        },
                        "join_keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "当 action=join 时，用于合并的列名列表",
                        },
                        "how": {
                            "type": "string",
                            "enum": ["inner", "left", "right", "outer"],
                            "description": "当 action=join 时，合并方式（默认 inner）",
                        },
                        "key_columns": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "当 action=diff 时，用于对比的主键列名列表",
                        },
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "excel_chart_recommend",
                "description": "根据 Excel 数据内容推荐合适的图表类型。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Excel 文件路径"}
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "import_excel_to_database",
                "description": (
                    "将 Excel 数据导入到数据库。系统会分析 Excel 内容并自动匹配字段进行导入。报价单等多行标题表必须传 header_row（与 extract-grid / excel_analysis 一致），否则列名会变成 Unnamed、映射错乱。可选 last_data_row_1based 截断表尾说明文字；未传时仍会对典型合同/报价表尾条款行做启发式过滤。"
                    "【重要】参数 unit_name 在本系统中表示「客户公司全称」（与主库 purchase_units / 产品上 unit 字段一致），用于把产品挂到该客户下；不是 SKU 计量单位（件、桶、箱等）。缺省时可从运行时上下文 customer_hint / excel_customer_hint 或 Excel「客户/购买单位」列推断。"
                    "若上下文已含 excel_customer_hint 或已解析的文档客户名，不要在对话中再向用户索要公司名称，直接调用本工具即可（unit_name 可填该名或留空）。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Excel 文件路径"},
                        "sheet_name": {
                            "type": "string",
                            "description": "工作表名称；与 excel_analysis 所选表一致",
                        },
                        "header_row": {
                            "type": "integer",
                            "description": "表头所在 Excel 行号（从 1 开始）。必须与上传预览检测的 header_row / excel_analysis 一致。",
                        },
                        "last_data_row_1based": {
                            "type": "integer",
                            "description": "可选：数据区最后一行的 Excel 行号（含），用于去掉表尾条款/说明行。与 header_row 同时使用时，保留的数据行数 = last_data_row_1based - header_row。",
                        },
                        "import_type": {
                            "type": "string",
                            "enum": ["products", "customers", "orders"],
                            "description": "导入类型：products产品、customers客户、orders订单",
                        },
                        "unit_name": {
                            "type": "string",
                            "description": "客户公司全称（业务上亦称「购买单位」= 往来客户，非件/桶等计量单位）。导入产品时必须指向该客户；可留空由服务端从 excel_customer_hint / customer_hint 推断",
                        },
                        "price_column": {
                            "type": "string",
                            "description": "可选：用作单价的表头子串（如「调价前」「调价后」）。不传时自动推断；若同时存在调价前/调价后等价类列，默认取调价前列。",
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "是否执行写入。默认 true（直接导入）；仅显式传 false 时返回预览。已配置令牌且请求已携带正确 db_write_token 时，服务端仍按已确认写入处理。",
                        },
                        "preview_only": {
                            "type": "boolean",
                            "description": "可选：是否仅预览不写入。true 时即使未传 confirm 也只返回预览。",
                        },
                        "db_write_token": {
                            "type": "string",
                            "description": "数据库写入授权令牌（如系统要求）",
                        },
                    },
                    "required": ["file_path", "import_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "template_preview",
                "description": (
                    "查看、查询或保存 Excel/单据模板。用户要求“保存到模板库”“加入模板”"
                    "或基于当前 Excel 生成模板时使用 action=create，并传入 file_path/sheet_name/header_row。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["view", "list", "query", "create"],
                            "description": "view=打开模板预览；list/query=查询模板；create=保存当前结构到模板库",
                        },
                        "template_name": {"type": "string", "description": "模板名称"},
                        "name": {"type": "string", "description": "模板名称别名"},
                        "file_path": {"type": "string", "description": "当前 Excel 文件路径"},
                        "sheet_name": {"type": "string", "description": "工作表名称"},
                        "header_row": {"type": "integer", "description": "表头行号，1-based"},
                        "template_type": {"type": "string", "description": "模板类型，默认 Excel"},
                        "business_scope": {"type": "string", "description": "业务范围"},
                    },
                    "required": ["action"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_office_document",
                "description": (
                    "根据用户自然语言需求**直接生成可下载的 Word（.docx）或 Excel（.xlsx）文件**。"
                    "适用于：合同/协议（如技术服务合同、AI 服务合同）、报价单、项目清单、排期表、简单报表等。"
                    "调用后返回一次性下载链接，须完整转告用户该 URL。"
                    "若用户仅做数据分析而非要独立文件，不要用此工具。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_request": {
                            "type": "string",
                            "description": "用户对文档的完整要求（主题、甲乙方角色、关键条款或表格列等）",
                        },
                        "output_format": {
                            "type": "string",
                            "enum": ["docx", "xlsx"],
                            "description": "docx=Word 文书；xlsx=表格",
                        },
                    },
                    "required": ["user_request", "output_format"],
                },
            },
        },
    ]


def invalidate_workflow_tool_registry() -> None:
    """装包/卸载 employee_pack 后使进程内工具注册表缓存失效。"""
    global _WORKFLOW_REG_VER, _workflow_tool_registry_cache
    _WORKFLOW_REG_VER += 1
    _workflow_tool_registry_cache = None
    try:
        from app.mod_sdk.employee_tool_registry import invalidate_employee_tool_cache

        invalidate_employee_tool_cache()
    except RECOVERABLE_ERRORS:
        logger.debug("employee tool cache invalidate skipped", exc_info=True)


def get_workflow_tool_registry() -> list[dict[str, Any]]:
    global \
        _workflow_tool_registry_cache, \
        _workflow_tool_registry_bulk_token_present, \
        _workflow_registry_cache_ver
    bulk_on = True
    if (
        _workflow_tool_registry_cache is not None
        and _workflow_tool_registry_bulk_token_present == bulk_on
        and _workflow_registry_cache_ver == _WORKFLOW_REG_VER
    ):
        return _workflow_tool_registry_cache
    reg = _base_registry()
    try:
        from app.mod_sdk.employee_tool_registry import build_employee_pack_tool_definitions

        emp_tools = build_employee_pack_tool_definitions()
        if emp_tools:
            reg = reg + emp_tools
    except RECOVERABLE_ERRORS:
        logger.debug("employee pack tools merge skipped", exc_info=True)
    if bulk_on:
        reg.append(
            {
                "type": "function",
                "function": {
                    "name": "products_bulk_import",
                    "description": "批量导入产品数据到数据库。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Excel 文件路径"},
                            "sheet_name": {"type": "string", "description": "工作表名称"},
                            "mapping": {"type": "object", "description": "列名映射配置"},
                        },
                        "required": ["file_path"],
                    },
                },
            }
        )
    _workflow_tool_registry_cache = reg
    _workflow_tool_registry_bulk_token_present = bulk_on
    _workflow_registry_cache_ver = _WORKFLOW_REG_VER
    return reg


def execute_workflow_tool(
    name: str,
    args: dict[str, Any] | str,
    workspace_root: str | None = None,
    *,
    db_write_token: str | None = None,
) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except RECOVERABLE_ERRORS:
            args = {}
    try:
        from app.mod_sdk.employee_tool_registry import execute_employee_tool, is_employee_tool

        if is_employee_tool(name):
            return execute_employee_tool(name, args, workspace_root)
    except RECOVERABLE_ERRORS:
        logger.debug("employee tool dispatch skipped", exc_info=True)
    try:
        from app.mod_sdk.planner_native_tools import try_execute_native_planner_tool

        native_raw, _mod = try_execute_native_planner_tool(
            name, args, workspace_root, db_write_token=db_write_token
        )
        if native_raw is not None:
            return native_raw
    except RECOVERABLE_ERRORS:
        logger.debug("planner native tool dispatch skipped", exc_info=True)
    if name == "template_preview":
        from app.services.tools_workflow_registered import execute_registered_workflow_tool

        action = str(args.get("action") or "view").strip() or "view"
        return json.dumps(
            execute_registered_workflow_tool(name, action, args),
            ensure_ascii=False,
        )
    try:
        from app.application.employee_pack_runner import try_execute_employee_planner_tool

        emp_raw = try_execute_employee_planner_tool(
            name, args, workspace_root, db_write_token=db_write_token
        )
        if emp_raw is not None:
            return emp_raw
    except RECOVERABLE_ERRORS:
        logger.debug("legacy employee planner tool dispatch skipped", exc_info=True)
    if name == "excel_analysis":
        return json.dumps(
            handle_excel_analysis(args, workspace_root=workspace_root), ensure_ascii=False
        )
    if name == "excel_chart_recommend":
        return json.dumps(
            {
                "suggestions": [
                    {"chart_type": "bar", "title": "分类对比"},
                    {"chart_type": "line", "title": "趋势分析"},
                ]
            },
            ensure_ascii=False,
        )
    if name == "excel_join_compare":
        try:
            action = str(args.get("action") or "join")
            if action == "join":
                f1, f2 = (args.get("file_paths") or [None, None])[:2]
                p1 = resolve_safe_excel_path(workspace_root or str(Path.cwd()), str(f1))
                p2 = resolve_safe_excel_path(workspace_root or str(Path.cwd()), str(f2))
                if not p1.exists():
                    return json.dumps(
                        {"success": False, "error": f"file not found: {f1}"}, ensure_ascii=False
                    )
                if not p2.exists():
                    return json.dumps(
                        {"success": False, "error": f"file not found: {f2}"}, ensure_ascii=False
                    )
                d1 = pd.read_excel(p1)
                d2 = pd.read_excel(p2)
                keys = [str(x) for x in (args.get("join_keys") or []) if str(x)]
                how = str(args.get("how") or "inner")
                out = d1.merge(d2, on=keys, how=how) if keys else d1
                return json.dumps(
                    {
                        "action": "join",
                        "row_count": int(len(out)),
                        "columns": list(out.columns.astype(str)),
                    },
                    ensure_ascii=False,
                )
            elif action == "diff":
                pa = resolve_safe_excel_path(
                    workspace_root or str(Path.cwd()), str(args.get("file_path_a") or "")
                )
                pb = resolve_safe_excel_path(
                    workspace_root or str(Path.cwd()), str(args.get("file_path_b") or "")
                )
                if not pa.exists():
                    return json.dumps(
                        {"success": False, "error": f"file not found: {args.get('file_path_a')}"},
                        ensure_ascii=False,
                    )
                if not pb.exists():
                    return json.dumps(
                        {"success": False, "error": f"file not found: {args.get('file_path_b')}"},
                        ensure_ascii=False,
                    )
                a = pd.read_excel(pa)
                b = pd.read_excel(pb)
                keys = [str(x) for x in (args.get("key_columns") or []) if str(x)]
                if keys:
                    la = a.set_index(keys)
                    lb = b.set_index(keys)
                    only_l = [idx for idx in la.index if idx not in lb.index]
                    only_r = [idx for idx in lb.index if idx not in la.index]
                    common = [idx for idx in la.index if idx in lb.index]
                    changed = 0
                    for idx in common:
                        if not la.loc[idx].equals(lb.loc[idx]):
                            changed += 1
                    return json.dumps(
                        {
                            "action": "diff",
                            "only_in_left": {"count": len(only_l)},
                            "only_in_right": {"count": len(only_r)},
                            "rows_with_value_changes": {"count": changed},
                        },
                        ensure_ascii=False,
                    )
                else:
                    return json.dumps(
                        {"action": "diff", "row_count": int(len(a))}, ensure_ascii=False
                    )
            else:
                return json.dumps(
                    {"success": False, "error": f"unknown action: {action}"}, ensure_ascii=False
                )
        except RECOVERABLE_ERRORS as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    if name == "excel_prophet":
        try:
            file_path = str(args.get("file_path") or "")
            value_col = str(args.get("value_column") or args.get("y") or "").strip()
            str(args.get("date_column") or args.get("ds") or "").strip()
            periods = max(1, min(30, int(args.get("periods") or 6)))
            root = workspace_root or str(Path.cwd())
            if file_path:
                p = resolve_safe_excel_path(root, file_path)
                df = _read_excel_dataframe(p)
                if not value_col or value_col not in df.columns:
                    num_cols = [
                        c
                        for c in df.columns
                        if pd.to_numeric(df[c], errors="coerce").notna().sum() > 2
                    ]
                    value_col = num_cols[0] if num_cols else ""
                y = (
                    pd.to_numeric(df[value_col], errors="coerce").dropna()
                    if value_col
                    else pd.Series([], dtype=float)
                )
            else:
                y = pd.Series([], dtype=float)
            if len(y) < 2:
                return json.dumps(
                    {
                        "action": "forecast",
                        "future_forecast": [{"yhat": 0.0}] * periods,
                        "note": "数据不足，使用零预测",
                    },
                    ensure_ascii=False,
                )
            x = list(range(len(y)))
            # 简单线性回归预测
            n = len(x)
            sx = sum(x)
            sy = float(y.sum())
            sxy = sum(xi * yi for xi, yi in zip(x, y))
            sxx = sum(xi**2 for xi in x)
            denom = n * sxx - sx * sx
            slope = (n * sxy - sx * sy) / denom if denom else 0
            intercept = (sy - slope * sx) / n
            future = [
                {"period": i + 1, "yhat": round(intercept + slope * (len(y) + i), 4)}
                for i in range(periods)
            ]
            return json.dumps(
                {
                    "action": "forecast",
                    "future_forecast": future,
                    "model": "linear_regression",
                    "periods": periods,
                },
                ensure_ascii=False,
            )
        except RECOVERABLE_ERRORS as e:
            return json.dumps(
                {"action": "forecast", "future_forecast": [], "error": str(e)}, ensure_ascii=False
            )
    if name == "excel_schema_understand":
        try:
            file_path = str(args.get("file_path") or "")
            sheet_n = args.get("sheet_name")
            header_1b = _parse_excel_header_row_1based(args)
            root = workspace_root or str(Path.cwd())
            p = resolve_safe_excel_path(root, file_path)
            if not p.exists():
                return json.dumps(
                    {
                        "success": False,
                        "error": "file_not_found",
                        "message": f"找不到文件: {file_path}",
                        "hint": "请确认文件已正确上传，或重新上传文件。",
                        "workspace_root": root,
                        "resolved_path": str(p),
                    },
                    ensure_ascii=False,
                )
            df = _read_excel_dataframe(p, sheet_name=sheet_n, header_row_1based=header_1b)
            svc = ExcelSchemaUnderstandingService()
            out = svc.understand_dataframe(df, file_path=file_path)
            return json.dumps(out, ensure_ascii=False)
        except RECOVERABLE_ERRORS as e:
            return json.dumps(
                {"success": False, "error": str(e), "message": f"读取 Excel 文件失败: {e}"},
                ensure_ascii=False,
            )
    if name == "products_bulk_import":
        from app.application.excel_imports import run_bulk_import

        out = run_bulk_import(args)
        return json.dumps(out, ensure_ascii=False)
    if name == "excel_vector_index":
        file_path = str(args.get("file_path") or "").strip()
        if not file_path:
            return json.dumps(
                {"success": False, "error": "file_path is required"}, ensure_ascii=False
            )
        root = workspace_root or str(Path.cwd())
        p = resolve_safe_excel_path(root, file_path)
        if not p.exists():
            return json.dumps(
                {
                    "success": False,
                    "error": "file_not_found",
                    "file_path": file_path,
                    "resolved_path": str(p),
                },
                ensure_ascii=False,
            )
        from app.application import get_excel_vector_ingest_app_service

        index_name = str(args.get("index_name") or "").strip() or None
        index_id = str(args.get("index_id") or "").strip() or None
        result = get_excel_vector_ingest_app_service().ingest_excel(
            file_path=str(p),
            index_name=index_name,
            index_id=index_id,
        )
        if isinstance(result, dict) and result.get("success") and result.get("index_id"):
            result["excel_vector_index_id"] = result.get("index_id")
            result["excel_index_id"] = result.get("index_id")
        return json.dumps(result, ensure_ascii=False)
    if name == "import_excel_to_database":
        return _handle_import_excel_to_database(
            args, workspace_root=workspace_root, db_write_token=db_write_token
        )
    if name == "generate_office_document":
        try:
            req = str(
                args.get("user_request")
                or args.get("prompt")
                or args.get("request")
                or args.get("message")
                or ""
            ).strip()
            fmt = str(args.get("output_format") or "docx").lower().strip()
            if fmt not in ("docx", "xlsx"):
                fmt = "docx"
            if not req:
                return json.dumps(
                    {"success": False, "error": "missing_user_request"}, ensure_ascii=False
                )
            from app.services.kitten_ai_document.generate import generate_office_file
            from app.services.kitten_ai_document.pickup import store_document_pickup

            content, fname = generate_office_file(req, fmt)
            mime = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                if fmt == "xlsx"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            token = store_document_pickup(content, fname, mime)
            download_url = f"/api/ai/kitten/document/pickup/{token}"
            return json.dumps(
                {
                    "success": True,
                    "message": f"已生成《{fname}》。请让用户在浏览器打开以下路径下载（一次性有效，勿泄露 token）：",
                    "pickup_token": token,
                    "file_name": fname,
                    "download_url": download_url,
                    "artifacts": [
                        {
                            "artifact_type": "office_document",
                            "name": fname,
                            "source": "generate_office_document",
                            "uri": download_url,
                            "mime_type": mime,
                            "summary": req[:500],
                            "preview": {
                                "file_name": fname,
                                "download_url": download_url,
                                "output_format": fmt,
                            },
                            "metadata": {
                                "pickup_token": token,
                                "generator": "generate_office_document",
                            },
                        }
                    ],
                    "assistant_hint": (
                        "将 download_url 原样写入回复（可做成 Markdown 链接）；"
                        "不要再次调用 generate_office_document，除非用户明确要求重新生成。"
                    ),
                },
                ensure_ascii=False,
            )
        except RECOVERABLE_ERRORS as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    return json.dumps({"success": False, "error": "unknown_tool", "tool": name}, ensure_ascii=False)

from app.application.tools.workflow_import_excel import (  # noqa: E402, I001
    _excel_cell_as_clean_str as _excel_cell_as_clean_str,
    _excel_cell_as_float as _excel_cell_as_float,
    _handle_import_excel_to_database as _handle_import_excel_to_database,
    _import_customers_preview_or_execute as _import_customers_preview_or_execute,
    _import_orders_preview_or_execute as _import_orders_preview_or_execute,
    _import_products_preview_or_execute as _import_products_preview_or_execute,
    _infer_product_field_mapping as _infer_product_field_mapping,
    _looks_like_contract_or_footer_line as _looks_like_contract_or_footer_line,
)
