"""工作流上下文 nodes.prev / 模板解析回归。"""

from __future__ import annotations

from modstore_server.workflow_variables import resolve_value


def test_resolve_nodes_prev_output_path():
    ctx = {
        "nodes": {
            "prev": {
                "id": 1,
                "name": "n1",
                "type": "start",
                "output": {"phone": "13800138000", "name": "Ada"},
            }
        },
        "global": {},
        "result": {},
    }
    assert resolve_value("{{nodes.prev.output.phone}}", ctx) == "13800138000"
