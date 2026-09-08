"""Explicit business dashboard requests, without swallowing compound actions."""

from .types import WorkflowNode


def dashboard_query_node(message: str) -> WorkflowNode | None:
    text = message.strip().rstrip("。？?")
    for prefix in (
        "帮我查看",
        "帮我看看",
        "请查看",
        "看一下",
        "查看",
        "看看",
        "看下",
        "查询",
        "打开",
    ):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    if text not in {"运营看板", "经营看板", "业务看板", "经营概览"}:
        return None
    return WorkflowNode(
        node_id="business_dashboard",
        tool_id="reports",
        action="dashboard",
        params={},
        risk="low",
        idempotent=True,
        description="查询经营看板",
    )
