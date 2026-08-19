"""Immutable policy constants for duty-workforce burn-in."""

from __future__ import annotations

CAPABILITY_HANDLERS = frozenset({"agent", "direct_python"})
DANGEROUS_HANDLERS = frozenset(
    {
        "http_request",
        "webhook",
        "wechat_notify",
        "voice_output",
        "openapi_tool",
        "fhd_business",
        "shell_exec",
        "ssh_exec",
        "para_delegate",
        "cursor_delegate",
        "vibe_edit",
        "vibe_heal",
        "vibe_code",
        "doc_sync",
    }
)
READ_ONLY_OBSERVATION_TOOLS = frozenset(
    {
        "read_workspace_file",
        "list_workspace_dir",
        "scan_project_tree",
        "identify_file_types",
        "analyze_project_summary",
        "list_platform_llm_models",
        "list_llm_cli_status",
        "list_available_ai_routes",
        "get_platform_llm_route",
    }
)
READ_ONLY_AGENT_TOOLS = READ_ONLY_OBSERVATION_TOOLS | {"call_llm"}
PROHIBITED_SEMANTICS = (
    "payment",
    "billing",
    "refund",
    "revenue-share",
    "revenue_share",
    "deploy",
    "release",
    "publish",
    "message",
    "notify",
    "customer-service",
    "customer_service",
    "webhook",
    "wechat",
    "email",
    "delete",
    "remove",
    "retention",
    "archive",
    "支付",
    "退款",
    "结算",
    "分润",
    "发布",
    "部署",
    "上架",
    "消息",
    "通知",
    "客服",
    "邮件",
    "微信",
    "外部输入",
    "删除",
    "清理",
    "归档",
)
