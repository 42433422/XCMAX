"""Shared MCP catalog and platform identifiers."""

from typing import Any

AIOPEN_PRODUCT_NAME = "AIOPEN"

AIOPEN_PRODUCT_TAGLINE = "我是 AI 的工具 — MCP / API 开放平台与虚拟光标操控"

MCP_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26")

MCP_DEFAULT_PROTOCOL_VERSION = "2024-11-05"

MCP_SERVER_NAME = "xcagi-aiopen"

CAPABILITY_ROUTE_PREFIXES: tuple[str, ...] = (
    "/api/ai/chat",
    "/api/ai/unified_chat",
    "/api/chat/send",
    "/api/conversations",
    "/api/planner",
    "/api/im",
    "/api/mobile/v1/ai-groups",
    "/api/platform-shell",
    "/api/mods",
    "/api/knowledge",
    "/api/persy/knowledge",
    "/api/system/workflow-employee-catalog",
    "/api/workflow-employee-space",
    "/api/mod",
    "/api/products",
    "/api/customers",
    "/api/materials",
    "/api/orders",
    "/api/shipment",
    "/api/print",
    "/api/wechat_contacts",
    "/api/templates",
    "/api/excel",
    "/api/document-templates",
    "/api/data-sources",
    "/api/auth/me",
)

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "api_catalog",
        "description": "列出 AIOPEN 白名单内可调用的 XCAGI 业务 API 路由及其启用状态。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "api_call",
        "description": "调用白名单内的 XCAGI 业务 API。path 支持精确匹配或已启用前缀的子路径（如启用 /api/products 则可调 /api/products/list）。method 支持 GET/POST/PUT/PATCH/DELETE。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "API 路径，如 /api/products/list；可带 query",
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    "default": "GET",
                },
                "body": {"type": "object", "description": "请求体（JSON，非 GET/DELETE 时使用）"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "knowledge_search",
        "description": (
            "在 AIOPEN 系统地图中检索业务能力：按关键字返回匹配的 operation、"
            "风险等级、scope 与使用时机。替代一次性拉取全量目录。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言或关键字，如「创建订单」"},
                "domain": {
                    "type": "string",
                    "description": "可选：限定业务域，如 products / orders",
                },
                "limit": {"type": "integer", "description": "返回条数，默认 10，最大 50"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "operation_describe",
        "description": "读取单个 operation 的完整语义卡片：方法、路径、风险、scope 与使用时机、副作用、示例。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation_id": {
                    "type": "string",
                    "description": "来自 knowledge_search 的 operation_id",
                }
            },
            "required": ["operation_id"],
        },
    },
    {
        "name": "operation_call",
        "description": (
            "按 operation_id 执行系统地图中的业务接口。params 传路径/查询参数，body 传 JSON 请求体。"
            "危险操作默认返回 APPROVAL_REQUIRED 不执行；写操作需服务端开启 AIOPEN_ENABLE_WRITES，"
            "危险操作另需服务端显式开启 AIOPEN_AUTO_APPROVE_DANGER 才会留痕后自动批准。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation_id": {
                    "type": "string",
                    "description": "来自 knowledge_search / operation_describe 的 operation_id",
                },
                "params": {
                    "type": "object",
                    "description": "路径参数与查询参数，键名与 operation 卡片一致",
                },
                "body": {"type": "object", "description": "JSON 请求体（写操作使用）"},
            },
            "required": ["operation_id"],
        },
    },
    {
        "name": "chat",
        "description": "向 XCAGI AI 助手发送一条消息（unified_chat，source=aiopen），返回助手回复。",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "要发送的消息"}},
            "required": ["message"],
        },
    },
    {
        "name": "capability_loop",
        "description": "全调用闭环自检：api_catalog → 抽样 api_call(GET) → chat → ui_sessions，返回各步成败，供外部 Agent 确认 MCP 已打通。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe_path": {
                    "type": "string",
                    "description": "可选抽样 API，默认自动选已启用白名单路径",
                },
                "message": {"type": "string", "description": "可选 chat 探测文案"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "ui_sessions",
        "description": "列出当前在线的虚拟光标 screen 会话（XCAGI 前端开启远程操控后出现）。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "ui_snapshot",
        "description": (
            "采集当前页面的可访问性树快照：每个可见可交互节点分配本次快照内稳定的 ref，"
            "并给出角色、可访问名称、状态与位置；selector 仅作兼容回退。"
            "后续 ui_click / ui_type / ui_select / ui_upload / ui_verify 优先使用 ref。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "目标会话，缺省取第一个在线会话"}
            },
        },
    },
    {
        "name": "ui_navigate",
        "description": "让 XCAGI 前端跳转到指定路由路径（虚拟光标会话内 router.push）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "前端路由路径，如 /products"},
                "session_id": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "ui_click",
        "description": "虚拟光标移动到指定元素并真实点击（带可视化动画）。优先使用 ui_snapshot 的 ref。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "来自 ui_snapshot 的节点 ref"},
                "selector": {
                    "type": "string",
                    "description": "兼容回退：CSS 选择器（来自 ui_snapshot）",
                },
                "text": {
                    "type": "string",
                    "description": "可选：按可见文本匹配元素（ref/selector 缺省时使用）",
                },
                "session_id": {"type": "string"},
            },
        },
    },
    {
        "name": "ui_type",
        "description": "在指定输入框中输入文本（聚焦 + 写值 + 派发 input/change 事件）。优先使用 ref。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "来自 ui_snapshot 的输入节点 ref"},
                "selector": {"type": "string", "description": "兼容回退：输入框 CSS 选择器"},
                "text": {"type": "string", "description": "要输入的文本"},
                "session_id": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "ui_select",
        "description": (
            "选择下拉项：原生 select 直接按 value 选中；自定义下拉先点开再按可见文本匹配 option。"
            "value/values/label 至少提供一个。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "来自 ui_snapshot 的下拉节点 ref"},
                "selector": {"type": "string", "description": "兼容回退：CSS 选择器"},
                "value": {"type": "string", "description": "单个选项值"},
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "多选值（原生 multiple select）",
                },
                "label": {"type": "string", "description": "自定义下拉的可见文本"},
                "session_id": {"type": "string"},
            },
        },
    },
    {
        "name": "ui_upload",
        "description": (
            "向文件输入框投放文件：files 每项提供 name 以及 url（同源 Agent 文件产物）或 base64/text 内容，"
            "必要时带 type。会派发 input/change 事件。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "来自 ui_snapshot 的 file input ref"},
                "selector": {"type": "string", "description": "兼容回退：CSS 选择器"},
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "url": {
                                "type": "string",
                                "description": "同源 /api/agent/runs/{run_id}/artifacts/{artifact_id}，不接受查询或片段",
                            },
                            "base64": {"type": "string", "description": "文件内容的 base64"},
                            "text": {"type": "string", "description": "纯文本内容"},
                            "type": {"type": "string", "description": "MIME 类型"},
                        },
                        "required": ["name"],
                    },
                },
                "session_id": {"type": "string"},
            },
            "required": ["files"],
        },
    },
    {
        "name": "ui_wait",
        "description": (
            "等待页面条件成立（轮询）：元素出现（ref/selector）、页面文本出现、URL 包含、"
            "或元素消失（gone_ref/gone_selector）。超时返回 success=false 并说明未满足项。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "等待该节点出现"},
                "selector": {"type": "string", "description": "等待该选择器出现"},
                "text": {"type": "string", "description": "等待页面可见文本出现"},
                "url_contains": {"type": "string", "description": "等待 URL 包含该片段"},
                "gone_ref": {"type": "string", "description": "等待该节点消失"},
                "gone_selector": {"type": "string", "description": "等待该选择器消失"},
                "timeout_ms": {
                    "type": "integer",
                    "description": "超时毫秒，默认 5000，最大 15000",
                },
                "session_id": {"type": "string"},
            },
        },
    },
    {
        "name": "ui_verify",
        "description": (
            "校验页面状态并返回逐项结论：元素存在、可见文本包含、输入值等于、URL 包含。"
            "任一失败即 success=false，便于 Agent 判断操作是否生效。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "待校验节点 ref"},
                "selector": {"type": "string", "description": "待校验节点 CSS 选择器"},
                "text": {"type": "string", "description": "页面可见文本应包含的内容"},
                "value": {"type": "string", "description": "ref/selector 指向控件的值应等于"},
                "url_contains": {"type": "string", "description": "URL 应包含的片段"},
                "session_id": {"type": "string"},
            },
        },
    },
    {
        "name": "ui_screenshot",
        "description": (
            "截取当前页面（或 ref/selector 指定区域）为图片，返回 data_url 与尺寸；"
            "基于 DOM 重绘，不含跨域 iframe 与视频画面。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "可选：只截取该节点"},
                "selector": {"type": "string", "description": "可选：只截取该选择器"},
                "max_width": {
                    "type": "integer",
                    "description": "最大像素宽度，默认 1280，超出会等比缩小",
                },
                "session_id": {"type": "string"},
            },
        },
    },
    {
        "name": "ui_scroll",
        "description": "滚动页面或将指定元素滚动到可见区域。优先使用 ref。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "来自 ui_snapshot 的节点 ref"},
                "selector": {"type": "string", "description": "兼容回退：滚动到该元素"},
                "delta_y": {"type": "number", "description": "可选：垂直滚动像素（正值向下）"},
                "session_id": {"type": "string"},
            },
        },
    },
]

_UI_ACTIONS = {
    "ui_snapshot": "snapshot",
    "ui_navigate": "navigate",
    "ui_click": "click",
    "ui_type": "type",
    "ui_select": "select",
    "ui_upload": "upload",
    "ui_wait": "wait",
    "ui_verify": "verify",
    "ui_screenshot": "screenshot",
    "ui_scroll": "scroll",
}

# 等待与截图比普通操作耗时更长，单独放宽虚拟光标回执超时。
_UI_ACTION_TIMEOUTS = {"snapshot": 20.0, "wait": 20.0, "screenshot": 30.0, "upload": 20.0}

_API_CALL_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
