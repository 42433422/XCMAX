"""Compatibility memory APIs share the scoped, confirmed MemoryV2 authority."""

import json

import pytest

from app.application.agent_task_context import scoped_personal_memory_id
from app.application.user_memory.retrieve import build_memory_context, search
from app.application.user_memory.write import normalize_memory_text, remember


@pytest.fixture
def authority(monkeypatch, tmp_path):
    from app.domain.shared_services import user_memory_service as module

    monkeypatch.setenv("XCAGI_USER_MEMORY_JSON_PATH", str(tmp_path / "memory.json"))
    monkeypatch.setenv("XCAGI_LONG_TERM_MEMORY_BACKEND", "legacy")
    monkeypatch.setenv("USER_MEMORY_VECTOR_DB_PATH", str(tmp_path / "vectors.sqlite"))
    module.reset_user_memory_service()
    service = module.get_user_memory_service()
    yield service, tmp_path / "memory.json"
    module.reset_user_memory_service()


def owner(tenant="2"):
    return scoped_personal_memory_id({"actor_id": "7", "tenant_id": tenant, "mod_id": "crm"})


def test_legacy_facade_proposes_pending_and_deduplicates(authority):
    service, path = authority
    first = remember("客户偏好蓝色包装", scope="user", owner_id=owner())
    second = remember("客户偏好蓝色包装", scope="user", owner_id=owner())
    assert first["created"] and second["merged"]
    assert first["id"] == second["id"]
    assert search("蓝色", scope="user", owner_id=owner()) == []
    service.confirm_memory_candidate(owner(), first["id"])
    assert "蓝色" in search("蓝色", scope="user", owner_id=owner())[0]["text"]
    persisted = json.loads(path.read_text())
    assert persisted[owner()]["recall_facts"] == []
    assert persisted[owner()]["memory_v2_records"][0]["status"] == "active"


def test_compat_recall_obeys_correction_and_revocation(authority):
    service, _ = authority
    created = remember("客户偏好蓝色包装", scope="user", owner_id=owner())
    service.confirm_memory_candidate(owner(), created["id"])
    service.correct_memory(owner(), created["id"], value={"statement": "客户偏好绿色包装"})
    assert "绿色" in build_memory_context("客户包装", scope="user", owner_id=owner())
    assert "蓝色" not in build_memory_context("客户包装", scope="user", owner_id=owner())
    service.delete_memory(owner(), created["id"])
    assert build_memory_context("客户包装", scope="user", owner_id=owner()) == ""
    assert service.list_memories(owner())[0]["history"]


def test_compat_recall_cannot_import_bare_actor_or_old_raw_facts(authority):
    service, _ = authority
    assert remember("旧企业秘密", scope="global", owner_id="7")["reason"] == "scoped_owner_required"
    raw = service._store.get_memory("7")
    raw.recall_facts = [{"id": "old", "text": "旧企业秘密", "scope": "global", "importance": 1}]
    service._store.save_memory("7", raw)
    assert search("秘密", scope="global", owner_id="7") == []
    assert search("秘密", scope="user", owner_id=owner()) == []
    assert service._store.get_memory("7").recall_facts


def test_compat_recall_isolates_tenant_and_respects_budget(authority):
    service, _ = authority
    row = remember("客户喜欢蓝色包装", scope="user", owner_id=owner())
    service.confirm_memory_candidate(owner(), row["id"])
    assert search("蓝色", scope="user", owner_id=owner("3")) == []
    text = build_memory_context("蓝色包装", scope="user", owner_id=owner(), max_chars=10)
    assert text and len(text) <= 10


@pytest.mark.parametrize(
    ("raw", "expected"), [("  你好   世界  ", "你好 世界"), ("我喜欢喝咖啡呢。", "我喜欢喝咖啡")]
)
def test_normalization_compatibility(raw, expected):
    assert normalize_memory_text(raw) == expected
