"""Native-plan dispatch reads exact SQL fragments under real session authorization."""

import json
from datetime import timedelta

import pytest

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.task_conversation_store import task_conversation_store as store
from app.application.workflow.llm_plan_generation import _decode_completion, _tool_specs
from app.application.workflow.tool_calling import native_plan_payload, plan_function_tools
from app.application.workflow_registry_app import get_workflow_tool_registry
from app.db.models.user import Session, User
from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope
from app.utils.time import utc_now_naive


@pytest.fixture
def history_runtime(dialogue_db, monkeypatch):
    factory = dialogue_db
    monkeypatch.setattr("app.db.HostSessionLocal", factory)
    Session.__table__.create(factory.kw["bind"])
    with factory.begin() as db:
        for owner in (1, 2):
            db.get(User, owner).tenant_id = owner + 6
            db.add(
                Session(
                    session_id=f"login-{owner}",
                    user_id=owner,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                )
            )
    return factory


def _context(owner=1, conversation="private"):
    return {
        "user_id": str(owner),
        "actor_id": str(owner),
        "local_user_id": owner,
        "tenant_id": str(owner + 6),
        "conversation_id": conversation,
        "session_id": conversation,
        "_actor_authorization": bind_agent_actor_scope(
            session_id=f"login-{owner}", user_id=str(owner)
        ),
        "_conversation_revision": 0,
        "idempotency_key": "same-native-read",
    }


def _execute(context, **arguments):
    envelope = {
        "mode": "workflow",
        "nodes": [
            {
                "node_id": "read",
                "tool_id": "conversation_history",
                "action": "read",
                "params": arguments,
            }
        ],
    }
    native = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "history-plan",
                            "type": "function",
                            "function": {
                                "name": plan_function_tools()[0]["function"]["name"],
                                "arguments": json.dumps(envelope),
                            },
                        }
                    ]
                }
            }
        ],
    }
    parsed, nodes = _decode_completion(native_plan_payload(native))
    assert parsed["mode"] == "workflow"
    node = nodes[0]
    return AgentToolExecutor().execute(
        AgentStep(
            node_id=node.node_id, tool_id=node.tool_id, action=node.action, params=node.params
        ),
        runtime_context=context,
    )


def test_native_tool_reads_exact_unicode_fragment_from_original_sql(history_runtime):
    original = "精确🙂金额￥123.45\n" * 1300
    message_id = store.save_message(session_id="private", user_id=1, role="user", content=original)
    result = _execute(_context(), message_id=message_id, offset=1200, max_chars=97)
    assert result["success"], result
    row = result["data"]["messages"][0]
    assert row == {
        "id": message_id,
        "role": "user",
        "content": original[1200:1297],
        "offset": 1200,
        "total_chars": len(original),
        "next_offset": 1297,
        "content_complete": False,
    }
    assert result["data"]["revision"] == 0
    offset, fragments = 0, []
    while offset is not None:
        fragment = _execute(_context(), message_id=message_id, offset=offset, max_chars=6000)[
            "data"
        ]["messages"][0]
        fragments.append(fragment["content"])
        offset = fragment["next_offset"]
    assert "".join(fragments) == original
    assert (
        store.get_conversation(session_id="private", user_id=1)["messages"][0]["content"]
        == original
    )


def test_native_history_pages_keep_ids_and_return_both_cursor_directions(history_runtime):
    ids = [
        store.save_message(session_id="private", user_id=1, role="user", content=f"message-{i}")
        for i in range(3)
    ]
    first = _execute(_context(), limit=2)["data"]
    assert [row["id"] for row in first["messages"]] == ids[1:]
    assert first["has_more"] and first["next_before_id"] == ids[1]
    earlier = _execute(_context(), before_id=first["next_before_id"], limit=2)["data"]
    assert [row["id"] for row in earlier["messages"]] == ids[:1]
    assert not earlier["has_more"]
    forward = _execute(_context(), after_id=0, limit=2)["data"]
    assert [row["id"] for row in forward["messages"]] == ids[:2]
    assert forward["next_after_id"] == ids[1]


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign_owner",
        "forged_tenant",
        "forged_local_owner",
        "missing_binding",
        "revoked_session",
        "foreign_message",
        "model_scope_override",
    ],
)
def test_history_tool_rejects_foreign_or_unbound_scope(history_runtime, mutation):
    store.save_message(session_id="private", user_id=1, role="user", content="owner-one-secret")
    foreign_id = store.save_message(
        session_id="other", user_id=2, role="user", content="owner-two-secret"
    )
    context, arguments = _context(), {}
    if mutation == "foreign_owner":
        context = _context(owner=2)
    elif mutation == "forged_tenant":
        context["tenant_id"] = "8"
    elif mutation == "missing_binding":
        context.pop("_actor_authorization")
    elif mutation == "forged_local_owner":
        context["local_user_id"] = 2
    elif mutation == "revoked_session":
        with history_runtime.begin() as db:
            db.query(Session).filter(Session.user_id == 1).delete()
    elif mutation == "foreign_message":
        arguments["message_id"] = foreign_id
    else:
        arguments["conversation_id"] = "other"
    result = _execute(context, **arguments)
    assert result["success"] is False, result
    assert "owner-one-secret" not in json.dumps(result) and "owner-two-secret" not in json.dumps(
        result
    )


@pytest.mark.parametrize("action", ["withdraw", "delete"])
def test_read_is_reauthorized_after_lifecycle_change_even_with_same_idempotency_key(
    history_runtime, action
):
    message_id = store.save_message(
        session_id="private", user_id=1, role="user", content="withdrawn secret"
    )
    context = _context()
    assert _execute(context)["data"]["messages"][0]["content"] == "withdrawn secret"
    if action == "withdraw":
        store.delete_messages_from(session_id="private", user_id=1, message_id=message_id)
    else:
        store.delete_session(session_id="private", user_id=1)
    result = _execute(context)
    assert result["success"] is False and result["error_code"] == "conversation_history_changed"
    assert "withdrawn secret" not in json.dumps(result)


def test_history_read_contract_is_available_to_both_profiles_with_no_identity_parameters():
    from app.application.workflow.planner_prompt_profile import select_tools_for_prompt
    from app.application.workflow.planning_graph_policy import filter_registry_for_profile

    registry = get_workflow_tool_registry()
    for profile in ("normal", "pro_default"):
        visible = select_tools_for_prompt(
            filter_registry_for_profile(registry, profile), "你好", {}
        )
        spec = next(
            item for item in _tool_specs(visible) if item["tool_id"] == "conversation_history"
        )
        schema = next(
            action["input_schema"] for action in spec["actions"] if action["action"] == "read"
        )
        assert schema["additionalProperties"] is False
        assert not {"user_id", "tenant_id", "session_id", "conversation_id"}.intersection(
            schema["properties"]
        )
