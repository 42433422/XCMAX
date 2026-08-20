# mypy: disable-error-code="no-any-return, valid-type"
"""Static workflow registry chunk."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.tools.workflow")


def _base_registry_chunk_01():
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
                "description": "将 Excel 数据导入到数据库。系统会分析 Excel 内容并自动匹配字段进行导入。报价单等多行标题表必须传 header_row（与 extract-grid / excel_analysis 一致），否则列名会变成 Unnamed、映射错乱。可选 last_data_row_1based 截断表尾说明文字；未传时仍会对典型合同/报价表尾条款行做启发式过滤。【重要】参数 unit_name 在本系统中表示「客户公司全称」（与主库 purchase_units / 产品上 unit 字段一致），用于把产品挂到该客户下；不是 SKU 计量单位（件、桶、箱等）。缺省时可从运行时上下文 customer_hint / excel_customer_hint 或 Excel「客户/购买单位」列推断。若上下文已含 excel_customer_hint 或已解析的文档客户名，不要在对话中再向用户索要公司名称，直接调用本工具即可（unit_name 可填该名或留空）。",
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
                "description": "查看、查询或保存 Excel/单据模板。用户要求“保存到模板库”“加入模板”或基于当前 Excel 生成模板时使用 action=create，并传入 file_path/sheet_name/header_row。",
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
                "description": "根据用户自然语言需求**直接生成可下载的 Word（.docx）或 Excel（.xlsx）文件**。适用于：合同/协议（如技术服务合同、AI 服务合同）、报价单、项目清单、排期表、简单报表等。调用后返回一次性下载链接，须完整转告用户该 URL。若用户仅做数据分析而非要独立文件，不要用此工具。",
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
        {
            "type": "function",
            "function": {
                "name": "delete_order",
                "description": "删除单条订单（出货记录）。高危操作，必须传 confirm=true 才会真正执行。若未传 confirm，返回预览信息等待用户二次确认。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_number": {
                            "type": "string",
                            "description": "订单 ID（出货记录主键，与 /api/shipment/orders/{order_number} 同语义）",
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "是否确认执行删除。必须显式传 true 才会执行",
                        },
                    },
                    "required": ["order_number"],
                },
            },
            "risk_level": "high",
        },
        {
            "type": "function",
            "function": {
                "name": "update_order",
                "description": "更新订单（出货记录）字段，如购买单位、产品名、型号、数量、单价、金额、状态等。写操作，必须传 confirm=true 才会执行。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_number": {
                            "type": "string",
                            "description": "订单 ID（出货记录主键）",
                        },
                        "fields": {
                            "type": "object",
                            "description": "待更新字段。支持 unit_name / product_name / model_number / quantity_kg / quantity_tins / tin_spec / unit_price / amount / status / date",
                            "properties": {
                                "unit_name": {"type": "string"},
                                "product_name": {"type": "string"},
                                "model_number": {"type": "string"},
                                "quantity_kg": {"type": "number"},
                                "quantity_tins": {"type": "integer"},
                                "tin_spec": {"type": "string"},
                                "unit_price": {"type": "number"},
                                "amount": {"type": "number"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "printed", "completed", "cancelled"],
                                },
                                "date": {"type": "string", "description": "ISO 日期字符串"},
                            },
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "是否确认执行更新。必须显式传 true 才会执行",
                        },
                    },
                    "required": ["order_number", "fields"],
                },
            },
            "risk_level": "medium",
        },
        {
            "type": "function",
            "function": {
                "name": "list_orders",
                "description": "查询订单（出货记录）列表。支持按购买单位、关键字过滤，返回最近记录。只读操作。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filters": {
                            "type": "object",
                            "description": "过滤条件",
                            "properties": {
                                "unit_name": {"type": "string", "description": "购买单位名"},
                                "keyword": {"type": "string", "description": "搜索关键字"},
                                "start_date": {"type": "string"},
                                "end_date": {"type": "string"},
                            },
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回条数上限，默认 20，最大 200",
                        },
                    },
                },
            },
            "risk_level": "low",
        },
        {
            "type": "function",
            "function": {
                "name": "update_customer",
                "description": "更新客户（购买单位）信息：客户名称、联系人、电话、地址。写操作，必须传 confirm=true 才会执行。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "integer", "description": "客户 ID"},
                        "fields": {
                            "type": "object",
                            "description": "待更新字段。支持 customer_name / contact_person / contact_phone / contact_address",
                            "properties": {
                                "customer_name": {"type": "string"},
                                "contact_person": {"type": "string"},
                                "contact_phone": {"type": "string"},
                                "contact_address": {"type": "string"},
                            },
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "是否确认执行更新。必须显式传 true 才会执行",
                        },
                    },
                    "required": ["customer_id", "fields"],
                },
            },
            "risk_level": "medium",
        },
    ]
