"""Screen-control contracts; execution remains in the authenticated frontend."""

from __future__ import annotations

from typing import Any


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "expected_route": {
                    "type": "string",
                    "description": "最近快照的 route；页面变化时拒绝操作。",
                },
                **properties,
            },
            "required": required,
            "additionalProperties": False,
        },
    }


SCREEN_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _tool(
        "ui_files",
        "列出用户在当前窗口选过且尚未过期的文件编号。仅返回名称/大小/类型，不读取任意磁盘路径。",
        {},
        [],
    ),
    _tool(
        "ui_set_files",
        "将 ui_files 中的文件放入快照中的文件控件；空数组清空选择。上传和导入结果需要另行回读。",
        {
            "selector": {"type": "string"},
            "file_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 32,
            },
        },
        ["selector", "file_ids"],
    ),
    _tool(
        "ui_routes",
        "读取当前窗口实际挂载的全部页面目录，包括已加载的 Mods。页面访问仍由账号权限检查。",
        {},
        [],
    ),
    _tool(
        "ui_select",
        "选择原生下拉框的一个或多个值；选项来自 ui_snapshot。自定义下拉框请点击后重新读取快照。",
        {
            "selector": {"type": "string"},
            "values": {"type": "array", "minItems": 0, "items": {"type": "string"}},
        },
        ["selector", "values"],
    ),
    _tool(
        "ui_check",
        "将复选框、单选框或开关设置为指定状态；已经符合时不重复点击，返回实际状态。",
        {"selector": {"type": "string"}, "checked": {"type": "boolean"}},
        ["selector", "checked"],
    ),
    _tool(
        "ui_press",
        "向控件发送按键，适用于菜单、弹窗、组合框；返回事件回执后必须读取快照验证实际结果。",
        {
            "selector": {"type": "string"},
            "key": {
                "type": "string",
                "enum": [
                    "Enter",
                    "Escape",
                    "ArrowDown",
                    "ArrowUp",
                    "ArrowLeft",
                    "ArrowRight",
                    "Home",
                    "End",
                    " ",
                ],
            },
        },
        ["selector", "key"],
    ),
]
