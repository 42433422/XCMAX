"""Read printer configuration through the registered capability boundary."""

from app.services.tools_workflow_registered import execute_registered_workflow_tool


def build_printer_query_response() -> dict:
    result = execute_registered_workflow_tool("printer_list", "query", {})
    if not result.get("success"):
        return {
            "success": False,
            "response": "未能读取打印机配置，请稍后重试。",
            "normal_slot_dispatch": True,
        }
    printers = result.get("printers") or []
    default_value = result.get("default_printer")
    if isinstance(default_value, dict):
        default_value = default_value.get("printer") if default_value.get("success") else None
    default = str(default_value or "未设置")
    return {
        "success": True,
        "response": f"检测到 {len(printers)} 台打印机，默认打印机：{default}。",
        "data": {
            "intent": "printer_list",
            "printers": printers,
            "default_printer": default_value,
        },
        "normal_slot_dispatch": True,
    }
