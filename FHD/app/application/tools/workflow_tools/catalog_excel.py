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
            "分析 Excel 文件内容，支持读取、结构识别、查询、聚合等操作。在需要处理 Excel 数据时必须先调用此工具获取文件内容。如果用户选中了特定工作表，请使用 sheet_name 参数指定工作表名称。不确定表头或列名时先用 action=structure 获取列名/类型/样例/日期列，再用 action=query 提自然语言问题。read/query/aggregate 单次默认返回 1000 行；当结果 has_more=true 时，用 next_offset 作为 offset 继续分页读取，直到 has_more=false。需要原生坐标、公式或隐藏表时，用 read 的 view=sheets 列举，再用 view=cells 和 sheet_name 读取稀疏原始单元格；分页必须绑定上页 source_sha256。非Excel先read的pages/regions/tables/cells；选定table_id及expected_sha256后，view=table可read/query/aggregate/statistics，按原生坐标列c1、c2使用完整选中数据，不推断表头。非Excel续页须next_cursor，数值转换须column_types显式指定。",
            {
                "file_path": {
                    "type": "string",
                    "description": "当前账号的上传 ID/文件名，或同原任务已核验的文件产物 URI；宿主核对归属和原文件哈希后读取，不需要猜测本机路径。",
                },
                "sheet_name": {
                    "type": "string",
                    "description": "工作表名称（Sheet名），用于读取特定工作表。如果用户选中了某个工作表，请使用此参数指定。",
                },
                "view": {
                    "type": "string",
                    "enum": ["table", "sheets", "cells", "pages", "regions", "tables"],
                    "description": "read默认table保持Excel原数据表；sheets列举工作表；Excel cells必须指定sheet_name。非Excel的pages/regions/tables/cells从data.items回读原生事实；tables仅列元数据，选定table_id后view=table可读取坐标行或查询统计，items.values是派生值。Word没有渲染页，扫描PDF仍partial。",
                },
                "cell_range": {
                    "type": "string",
                    "description": "Excel view=cells可选原生A1范围（如B2:Z100）；稀疏空隙不物化，显式空值/样式空白仍保留。非Excel使用page/table_id/fact_id定位。",
                },
                "expected_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                    "description": "原生事实分页延续时必须传前页source_sha256；源文件变化则拒绝拼接旧页。它不是授权凭据，每次仍校验原账号文件权限。",
                },
                "cursor": {
                    "type": "string",
                    "maxLength": 512,
                    "description": "非Excel续页必须原样携带data.next_cursor及expected_sha256；游标绑定解析版本、当前权限和筛选位置，不能跨账号或源版本复用。",
                },
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "非Excel原生页号（从1开始）；只适用于具有实际页或幻灯片的格式。",
                },
                "table_id": {
                    "type": "string",
                    "maxLength": 128,
                    "description": "非Excel使用先前tables返回的稳定table_id，必须同时传expected_sha256；view=cells读取原事实，view=table按坐标读取/查询/统计整个选中表。",
                },
                "fact_id": {
                    "type": "string",
                    "maxLength": 128,
                    "description": "非Excel精确读取先前返回的page_id/region_id/table_id/cell_id，必须同时传expected_sha256，保持原view。",
                },
                "row_range": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "integer", "minimum": 1, "maximum": 2147483647},
                    "description": "非Excel选中table_id后的原生行号闭区间[start,end]，CSV/TSV按逻辑record号；不会隐式删除首行，请显式排除表头。",
                },
                "native_columns": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 1000,
                    "uniqueItems": True,
                    "items": {"type": "integer", "minimum": 1, "maximum": 2147483647},
                    "description": "非Excel选中表的原生列号（从1开始），顺序即派生表列顺序；查询列名为c<原列号>。",
                },
                "column_types": {
                    "type": "object",
                    "maxProperties": 1000,
                    "propertyNames": {"pattern": "^c[1-9][0-9]{0,9}$"},
                    "additionalProperties": {"enum": ["number"]},
                    "description": "非Excel view=table的显式严格数值转换，如{c2:number}；非法/空字符串/布尔/非有限数和转换精度损失均拒绝，不静默改值或置空。未指定列保留原值。",
                },
                "header_row": EXCEL_HEADER_ROW,
                "offset": {
                    "type": "integer",
                    "description": "分页起始项目（从0开始，默认0）。上一次结果has_more=true时传next_offset；非Excel续页同时传next_cursor与expected_sha256。",
                },
                "max_rows": {
                    "type": "integer",
                    "description": "本次最多返回的数据行数（默认1000，Excel服务端可配置上限）；非Excel原生视图最多1000个项目且受响应字节预算限制。",
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
