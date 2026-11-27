"""The runtime, model gateway and MCP adapter expose the same controlled tools."""

XIAOX_TOOL_NAMES = (
    "capability_search",
    "capability_describe",
    "execute_action",
    "execute_employee",
    "execute_excel_read",
    "execute_excel_structure",
    "task_evidence",
    "request_input",
)

DIRECT_ACTION_TOOLS = {
    "execute_excel_read": ("excel_analysis", "read"),
    "execute_excel_structure": ("excel_analysis", "structure"),
}
