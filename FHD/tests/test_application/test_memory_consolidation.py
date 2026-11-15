"""记忆单元与事实合并：抽取、有效期、重排、ADD/NOOP/SUPERSEDE。"""

from __future__ import annotations

import importlib.util

import pytest

from app.infrastructure.memory import mem0_backend
from app.infrastructure.memory.consolidation import consolidate, decide
from app.infrastructure.memory.memory_units import (
    extract_facts,
    is_active,
    lexical_overlap,
    rank_hits,
)

_HAS_MEM0 = importlib.util.find_spec("mem0") is not None and (
    importlib.util.find_spec("qdrant_client") is not None
)


class FakeStore:
    """只实现合并所需接口的内存存储。"""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self._seq = 0

    def search_facts(self, user_id: str, fact: dict, limit: int = 5) -> list[dict]:
        return [
            {
                "chunk_id": mid,
                "content": item["content"],
                "metadata": dict(item["metadata"]),
            }
            for mid, item in self.items.items()
            if item["user_id"] == user_id
            and item["metadata"].get("fact_key") == fact.get("key")
            and is_active(item["metadata"])
        ][:limit]

    def add_fact(self, user_id: str, fact: dict, *, supersedes: str = "") -> str:
        self._seq += 1
        memory_id = f"m{self._seq}"
        self.items[memory_id] = {
            "user_id": user_id,
            "content": str(fact.get("text") or ""),
            "metadata": {
                "memory_type": "fact",
                "fact_key": fact.get("key"),
                "fact_value": fact.get("value"),
                "valid_from": "2026-01-01",
                "valid_to": "",
                "superseded_by": "",
            },
        }
        return memory_id

    def supersede_fact(
        self, user_id: str, memory_id: str, *, content: str, new_id: str, today: str
    ) -> bool:
        metadata = self.items[memory_id]["metadata"]
        metadata["valid_to"] = today
        metadata["superseded_by"] = new_id
        return True


_LABELS = {
    "company.name": "公司名称",
    "finance.budget": "预算",
    "logistics.default_warehouse": "默认仓库",
}


def _fact(key: str, value: str) -> dict:
    label = _LABELS.get(key, key)
    return {"key": key, "value": value, "text": f"{label}：{value}", "confidence": 0.8}


def test_extract_company_and_budget() -> None:
    facts = extract_facts("我们公司叫修茈科技，采购预算改成 80 万元")
    keys = {item["key"]: item["value"] for item in facts}
    assert keys["company.name"] == "修茈科技"
    assert keys["finance.budget"] == "80万元"


def test_question_is_not_extracted() -> None:
    assert extract_facts("我们公司的预算是多少？") == []


def test_explicit_memory_note_is_stable() -> None:
    first = extract_facts("记住：报价单默认含运费")
    second = extract_facts("记住：报价单默认含运费")
    assert first[0]["key"].startswith("explicit.")
    assert first[0]["key"] == second[0]["key"]


def test_is_active_filters_superseded_and_expired() -> None:
    assert is_active({"valid_from": "2026-01-01", "valid_to": "", "superseded_by": ""}) is True
    assert is_active({"superseded_by": "m2"}) is False
    assert is_active({"valid_to": "2020-01-01"}) is False
    assert is_active({"expiration_date": "2020-01-01"}) is False


def test_lexical_overlap_rewards_keyword_match() -> None:
    assert lexical_overlap("预算 80", "预算：80万元") > 0
    assert lexical_overlap("预算 80", "仓库：华东") == 0


def test_superseded_fact_never_returned() -> None:
    hits = [
        {
            "chunk_id": "old",
            "content": "预算：50万元",
            "score": 0.9,
            "metadata": {"memory_type": "fact", "superseded_by": "new"},
        },
        {
            "chunk_id": "new",
            "content": "预算：80万元",
            "score": 0.5,
            "metadata": {"memory_type": "fact", "superseded_by": ""},
        },
    ]

    ranked = rank_hits(hits, query="预算 80", limit=3)

    assert [item["chunk_id"] for item in ranked] == ["new"]


def test_decide_add_noop_supersede() -> None:
    assert decide(_fact("finance.budget", "80万元"), [])[0] == "ADD"

    same = [
        {
            "chunk_id": "m1",
            "content": "预算：80万元",
            "metadata": {
                "fact_key": "finance.budget",
                "fact_value": "80万元",
                "valid_to": "",
                "superseded_by": "",
            },
        }
    ]
    assert decide(_fact("finance.budget", "80万元"), same)[0] == "NOOP"

    changed = [{**same[0], "metadata": {**same[0]["metadata"], "fact_value": "50万元"}}]
    action, target = decide(_fact("finance.budget", "80万元"), changed)
    assert action == "SUPERSEDE"
    assert target is not None
    assert target["chunk_id"] == "m1"


def test_consolidate_writes_then_supersedes() -> None:
    store = FakeStore()

    first = consolidate(store, user_id="u1", facts=[_fact("finance.budget", "50万元")])
    assert first[0]["action"] == "ADD"

    repeated = consolidate(store, user_id="u1", facts=[_fact("finance.budget", "50万元")])
    assert repeated[0]["action"] == "NOOP"
    assert len(store.items) == 1

    changed = consolidate(store, user_id="u1", facts=[_fact("finance.budget", "80万元")])
    assert changed[0]["action"] == "SUPERSEDE"
    assert len(store.items) == 2
    old = store.items["m1"]["metadata"]
    assert old["valid_to"]
    assert old["superseded_by"] == "m2"
    assert store.search_facts("u1", _fact("finance.budget", "80万元"))[0]["chunk_id"] == "m2"


def test_consolidate_isolated_by_user() -> None:
    store = FakeStore()
    consolidate(store, user_id="u1", facts=[_fact("finance.budget", "50万元")])
    action, target = decide(
        _fact("finance.budget", "80万元"),
        store.search_facts("u2", _fact("finance.budget", "80万元")),
    )
    assert action == "ADD"
    assert target is None


def test_fact_prompt_is_labelled() -> None:
    prompt = mem0_backend.format_recalled_memories(
        [{"content": "预算：80万元", "score": 0.8, "metadata": {"memory_type": "fact"}}]
    )
    assert "事实：预算：80万元" in prompt


def test_synthetic_recall_at_3_and_stale_misuse() -> None:
    """合成探针：验证失效事实不挤占 top3，且过期值不会被误召回。"""
    rows = [
        ("f1", "预算：50万元", {"fact_key": "finance.budget", "valid_to": "2026-06-01"}),
        ("f2", "预算：80万元", {"fact_key": "finance.budget", "valid_to": ""}),
        ("f3", "公司名称：修茈科技", {"fact_key": "company.name", "valid_to": ""}),
        ("f4", "默认仓库：华东仓", {"fact_key": "logistics.default_warehouse", "valid_to": ""}),
        ("f5", "联系人：王经理", {"fact_key": "sales.contact", "valid_to": ""}),
    ]
    hits = [
        {
            "chunk_id": chunk_id,
            "content": content,
            "score": 0.4,
            "metadata": {
                "memory_type": "fact",
                "superseded_by": "",
                **metadata,
                **({"superseded_by": "f2"} if chunk_id == "f1" else {}),
            },
        }
        for chunk_id, content, metadata in rows
    ]
    probes = [
        ("预算 80万元", "f2"),
        ("公司名称", "f3"),
        ("默认仓库", "f4"),
        ("联系人", "f5"),
    ]
    hit_count = 0
    for query, expected in probes:
        ranked = rank_hits(hits, query=query, limit=3)
        ids = [item["chunk_id"] for item in ranked]
        assert "f1" not in ids
        hit_count += int(expected in ids)
    assert hit_count / len(probes) >= 0.75


@pytest.fixture
def backend(tmp_path, monkeypatch):
    from pathlib import Path

    from app.infrastructure.llm.embedding_service import EmbeddingService

    monkeypatch.setenv("XCAGI_LONG_TERM_MEMORY_DIR", str(Path(tmp_path) / "ltm"))
    monkeypatch.setenv("FHD_EMBEDDING_MODE", "hash")
    EmbeddingService.reset_singleton_for_tests()
    mem0_backend.reset_long_term_memory_for_tests()
    service = mem0_backend.get_long_term_memory()
    yield service
    service.close()
    mem0_backend.reset_long_term_memory_for_tests()
    EmbeddingService.reset_singleton_for_tests()


@pytest.mark.skipif(not _HAS_MEM0, reason="mem0 未安装")
def test_mem0_consolidation_and_recall(backend) -> None:
    assert backend.enabled is True
    old = backend.add_fact("owner-1", _fact("finance.budget", "50万元"))
    assert old
    results = backend.consolidate_facts(
        user_id="owner-1", facts=[_fact("finance.budget", "80万元")]
    )
    assert results[0]["action"] == "SUPERSEDE"

    hits = backend.recall(user_id="owner-1", query="预算", limit=3)
    contents = " ".join(item["content"] for item in hits)
    assert "80万元" in contents
    assert "50万元" not in contents


@pytest.mark.skipif(not _HAS_MEM0, reason="mem0 未安装")
def test_mem0_forget_by_user(backend) -> None:
    assert backend.remember(
        user_id="owner-2", user_message="客户甲 单价 100", assistant_message="已记录"
    )
    assert backend.recall(user_id="owner-2", query="客户甲", limit=3)
    backend.forget(user_id="owner-2")
    assert backend.recall(user_id="owner-2", query="客户甲", limit=3) == []
