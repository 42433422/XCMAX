# mypy: disable-error-code="index"
from app.application.document_employee_routing import (
    forced_document_tool_choice,
    select_document_employee_tool,
)

OFFICE_TOOLS = [
    {"type": "function", "function": {"name": f"{kind}-{action}-employee"}}
    for kind in ("excel", "csv", "pdf", "ppt", "word")
    for action in ("generate", "full-read")
]


def test_selects_each_built_in_document_employee_for_explicit_requests() -> None:
    cases = {
        "生成一份 Excel 报价单": "excel-generate-employee",
        "读取这个 CSV 文件并总结": "csv-full-read-employee",
        "解析 PDF 合同": "pdf-full-read-employee",
        "制作 PPT 演示稿": "ppt-generate-employee",
        "起草 Word 销售合同": "word-generate-employee",
    }
    names = {tool["function"]["name"] for tool in OFFICE_TOOLS}
    for message, expected in cases.items():
        assert select_document_employee_tool(message, available_tool_names=names) == expected


def test_ambiguous_chat_does_not_force_a_document_tool() -> None:
    assert forced_document_tool_choice("今天有哪些待办", OFFICE_TOOLS) is None


def test_forced_choice_only_targets_an_installed_registered_employee() -> None:
    choice = forced_document_tool_choice("生成 PDF 报告", OFFICE_TOOLS)
    assert choice == {"type": "function", "function": {"name": "pdf-generate-employee"}}
    assert forced_document_tool_choice("生成 PDF 报告", []) is None
