"""Legacy capture is a thin candidate adapter, with no independent raw fact store."""

from unittest.mock import MagicMock

import pytest

from app.application.agent_task_context import scoped_personal_memory_id
from app.application.user_memory import turn_capture
from app.application.user_memory.retrieve import search


@pytest.fixture
def captured(monkeypatch, tmp_path):
    from app.domain.shared_services import user_memory_service as module

    monkeypatch.setenv("XCAGI_USER_MEMORY_JSON_PATH", str(tmp_path / "memory.json"))
    monkeypatch.delenv("XCAGI_MEMORY_CAPTURE", raising=False)
    module.reset_user_memory_service()
    backend = MagicMock()
    backend.enabled = False
    backend.extract_candidates.return_value = [
        {
            "memory_type": "preference",
            "key": "report",
            "confidence": 0.8,
            "value": {"subject": "用户", "statement": "用户偏好按客户名分类对账单"},
        }
    ]
    monkeypatch.setattr(
        "app.infrastructure.memory.mem0_backend.get_long_term_memory", lambda: backend
    )
    yield module.get_user_memory_service(), backend
    module.reset_user_memory_service()


def owner():
    return scoped_personal_memory_id({"actor_id": "7", "tenant_id": "2"})


def test_capture_is_deduplicated_but_requires_confirmation(captured):
    authority, backend = captured
    first = turn_capture.capture_turn(user_message="以后按客户名分类对账单", owner_id=owner())
    second = turn_capture.capture_turn(user_message="以后按客户名分类对账单", owner_id=owner())
    assert first[0]["created"] and second[0]["merged"]
    assert search("客户名", scope="user", owner_id=owner()) == []
    assert authority._store.get_memory(owner()).recall_facts == []
    authority.confirm_memory_candidate(owner(), first[0]["id"])
    assert search("客户名", scope="user", owner_id=owner())
    backend.remember.assert_not_called()


def test_model_no_fact_does_not_retry_regex(captured):
    _, backend = captured
    backend.extract_candidates.return_value = []
    assert turn_capture.extract_fact_candidates("我喜欢简洁报告") == []


def test_fallback_excludes_questions_and_hypotheses(captured):
    _, backend = captured
    backend.extract_candidates.return_value = None
    assert turn_capture.extract_fact_candidates("我喜欢简洁报告？") == []
    assert turn_capture.extract_fact_candidates("如果我喜欢简洁报告") == []
    assert turn_capture.extract_fact_candidates("我喜欢简洁报告")


def test_capture_requires_scoped_owner_and_honours_opt_out(captured, monkeypatch):
    assert turn_capture.capture_turn(user_message="我喜欢简洁报告", owner_id="7") == []
    assert turn_capture.capture_turn(user_message="我喜欢简洁报告", owner_id="") == []
    monkeypatch.setenv("XCAGI_MEMORY_CAPTURE", "off")
    assert turn_capture.capture_turn(user_message="我喜欢简洁报告", owner_id=owner()) == []
