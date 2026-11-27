"""Workbook parameter schemas consumed by the canonical ToolActionSpecV2 catalog."""

from __future__ import annotations

from app.application.tools.workflow_tools.contracts import Payload
from app.domain.excel import EXCEL_HEADER_ROW


def tool_spec(name: str, description: str, properties: Payload, required: list[str]) -> Payload:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def excel_tool_specs() -> list[Payload]:
    return [
        tool_spec(
            "excel_analysis",
            "分析 Excel 文件内容，支持读取、结构识别、查询、聚合等操作。在需要处理 Excel 数据时必须先调用此工具获取文件内容。如果用户选中了特定工作表，请使用 sheet_name 参数指定工作表名称。不确定表头或列名时先用 action=structure 获取列名/类型/样例/日期列，再用 action=query 提自然语言问题。read/query/aggregate 单次默认返回 1000 行；当结果 has_more=true 时，用 next_offset 作为 offset 继续分页读取，直到 has_more=false。",
            {
                "file_path": {
                    "type": "string",
                    "description": "当前账号的上传 ID/文件名，或同原任务已核验的工作簿产物 URI；宿主核对归属和原文件哈希后读取，不需要猜测本机路径。",
                },
                "sheet_name": {
                    "type": "string",
                    "description": "工作表名称（Sheet名），用于读取特定工作表。如果用户选中了某个工作表，请使用此参数指定。",
                },
                "header_row": EXCEL_HEADER_ROW,
                "offset": {
                    "type": "integer",
                    "description": "分页起始数据行（从 0 开始，默认 0）。上一次结果 has_more=true 时，传 next_offset 继续读取。",
                },
                "max_rows": {
                    "type": "integer",
                    "description": "本次最多返回的数据行数（默认 1000，服务端可配置上限），不要一次性拉全表。",
                },
                "action": {
                    "type": "string",
                    "enum": ["read", "structure", "query", "aggregate", "statistics"],
                    "description": "操作类型：read读取数据、structure识别表头/列名/类型、query按自然语言或表达式查询、aggregate聚合统计、statistics统计信息",
                },
                "question": {
                    "type": "string",
                    "description": "当 action=query 时用自然语言描述要查什么（如「2026/9/30 之前购货金额合计」）。"
                    "服务端会自动探测表头、解析中文日期与金额，无需写 pandas 语法。",
                },
                "query_expression": {
                    "type": "string",
                    "description": "当 action=query 且已确认列名时可直接给 pandas query 表达式；不确定列名时改用 question。",
                },
                "group_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "当 action=aggregate 时的分组列名；空数组表示全表汇总，指标由 metrics 指定",
                },
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "cell_range": {
                                "type": "string",
                                "maxLength": 23,
                                "description": "无表头的单列 SUM 区域，如 C2:C100。该方式只接受单个指标，且不分组。",
                            },
                            "op": {
                                "type": "string",
                                "enum": ["sum", "mean", "count", "min", "max"],
                            },
                        },
                    },
                    "description": "当 action=aggregate 时的聚合指标",
                },
            },
            ["file_path", "action"],
        ),
        tool_spec(
            "excel_join_compare",
            "合并或对比两个 Excel 文件的数据。支持 join（合并）和 diff（差异对比）两种操作。",
            {
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
            ["action"],
        ),
    ]
