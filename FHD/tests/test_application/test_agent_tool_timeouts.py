"""批量工具的超时预算按实际文件数分配。"""

from app.application.agent_orchestrator.tool_timeouts import tool_timeout_seconds


def test_batch_timeout_scales_with_declared_files():
    assert tool_timeout_seconds("elt_import", "preview", {"file_paths": ["a", "b", "c"]}, 60) == 150
    assert tool_timeout_seconds("elt_import", "execute", {"run_ids": "r1,r2"}, 60) == 120


def test_batch_timeout_has_ceiling():
    assert tool_timeout_seconds("elt_import", "preview", {"file_paths": ["x"] * 50}, 60) == 300


def test_other_tools_keep_registered_default():
    assert tool_timeout_seconds("products", "list", {"file_paths": ["a"] * 10}, 60) == 60
    assert tool_timeout_seconds("customers", "create", None, 0) == 60
