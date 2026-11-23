"""A workspace switch reads its own initialized registry, including cached lists."""

from app.application import agent_tool_lifecycle as service
from app.application import agent_tool_registry_store as store
from app.application.agent_tool_lifecycle import Actor
from tests.fixtures.agent_tool_lifecycle_support import _base_body


def test_registry_switch_and_replaced_database_do_not_reuse_schema_or_tool_cache(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(store, "_DB_OVERRIDE", None)
    monkeypatch.setattr(store, "_SCHEMA_READY", None)
    monkeypatch.setattr(store, "_CACHE", {})
    first, second = tmp_path / "first.sqlite", tmp_path / "second.sqlite"
    actor = Actor(actor_id="admin", role="admin", employee_id=None, tenant_id=11)
    monkeypatch.setenv("XCAGI_AGENT_TOOL_DB", str(first))
    service.create_tool(actor, _base_body("original_only"))
    assert len(service.list_tools(actor, {})["items"]) == 1
    monkeypatch.setenv("XCAGI_AGENT_TOOL_DB", str(second))
    assert service.list_tools(actor, {})["items"] == []
    assert service.list_tools(actor, {})["items"] == []
    monkeypatch.setenv("XCAGI_AGENT_TOOL_DB", str(first))
    assert len(service.list_tools(actor, {})["items"]) == 1
    # Replace only this test's closed database; the empty replacement cannot
    # inherit either the first database's ready flag or its cached tool list.
    replacement = tmp_path / "empty.sqlite"
    replacement.touch()
    replacement.replace(first)
    assert service.list_tools(actor, {})["items"] == []
