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
    default = str(result.get("default_printer") or "未设置")
    return {
        "success": True,
        "response": f"检测到 {len(printers)} 台打印机，默认打印机：{default}。",
        "data": {
            "intent": "printer_list",
            "printers": printers,
            "default_printer": result.get("default_printer"),
        },
        "normal_slot_dispatch": True,
    }
