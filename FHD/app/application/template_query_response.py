"""Return registered template data to ordinary chat without a document write."""

from app.services.tools_workflow_registered import execute_registered_workflow_tool


def build_template_query_response() -> dict:
    result = execute_registered_workflow_tool("template_preview", "query", {})
    templates = result.get("templates")
    if result.get("success") is False or not isinstance(templates, list):
        return {
            "success": False,
            "response": "暂时无法读取模板，请稍后重试。",
            "normal_slot_dispatch": True,
        }
    names = [str(row.get("name") or "未命名模板") for row in templates if isinstance(row, dict)]
    response = (
        "可用模板：" + "、".join(names) + "。请指定要查看的模板。"
        if names else "当前没有可用模板。"
    )
    return {
        "success": True,
        "response": response,
        "data": {"intent": "template_preview", "templates": templates},
        "normal_slot_dispatch": True,
    }
