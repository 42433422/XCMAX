"""Route customer-list export requests to customers.query + reports.export.

「导出客户报表」 used to fall through to the terminal ``products.query``
catch-all — a cross-domain misroute: the request targets the customer list,
not the product catalog. Mirrors the sales-export chain: query first, then
hand the rows to the Excel exporter.
"""

import re

from .types import WorkflowNode

_EXPORT_RE = re.compile(
    r"^(?:请|帮我)?导出\s*(?:一下)?\s*(?:客户(?:列表|清单|报表|资料|信息)?|客户)[。\s]*$"
)


def customer_export_nodes(message: str) -> list[WorkflowNode]:
    text = str(message or "").strip()
    if not _EXPORT_RE.match(text):
        return []
    if any(word in text for word in ("不要", "别", "不用", "取消")):
        return []
    query = WorkflowNode(
        node_id="customer_export_query",
        tool_id="customers",
        action="query",
        params={"page": 1, "per_page": 1000},
        risk="low",
        idempotent=True,
        description="查询客户列表",
    )
    export = WorkflowNode(
        node_id="customer_export_excel",
        tool_id="reports",
        action="export",
        params={
            "report_type": "customers",
            "filename": "客户列表",
            "data_node_id": query.node_id,
        },
        depends_on=[query.node_id],
        risk="low",
        idempotent=True,
        description="将客户列表导出为 Excel",
    )
    return [query, export]
