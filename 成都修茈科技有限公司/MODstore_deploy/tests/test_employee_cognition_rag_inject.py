"""验证 employee_executor._cognition_real 在 cognition.knowledge.enabled 时把
RAG 检索结果注入到 LLM 的 system prompt。"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest


def _bootstrap(tmp_path: Path, monkeypatch):
    try:
        import chromadb  # noqa: F401
    except Exception:  # noqa: BLE001
        pytest.skip("chromadb 未安装；跳过员工 RAG 注入测试")

    monkeypatch.setenv("MODSTORE_VECTOR_BACKEND", "chroma")
    monkeypatch.setenv("MODSTORE_VECTOR_DB_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))

    import modstore_server.employee_executor as ee
    import modstore_server.models as models
    import modstore_server.rag_service as rag
    import modstore_server.vector_engine as ve

    models._engine = None
    models._SessionFactory = None
    importlib.reload(ve)
    importlib.reload(rag)
    importlib.reload(ee)
    ve.reset_client_for_tests()
    models.init_db()
    return models, ve, rag, ee


def test_cognition_injects_rag_context_into_system_prompt(tmp_path, monkeypatch):
    models, ve, rag, ee = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.models import KnowledgeCollection, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        coll = KnowledgeCollection(
            owner_kind="employee",
            owner_id="emp-pack-1",
            name="emp-kb",
            visibility="private",
        )
        session.add(coll)
        session.commit()
        session.refresh(coll)

    ve.upsert(
        ve.kb_collection_name(int(coll.id)),
        ids=["d:0"],
        embeddings=[[1.0, 0.0, 0.0]],
        documents=["The deployment secret is XYZ."],
        metadatas=[
            {"doc_id": "d", "filename": "deploy.md", "chunk_id": "d:0"},
        ],
    )

    captured: dict = {}

    async def fake_chat_dispatch(_session, _user_id, provider, model, messages, *, max_tokens=None):
        captured["provider"] = provider
        captured["messages"] = messages
        return {"ok": True, "content": "answered using knowledge", "raw": {}, "usage": {}}

    async def fake_embed(texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(ee, "chat_dispatch_via_session", fake_chat_dispatch)
    import modstore_server.rag_service as rag_module

    monkeypatch.setattr(rag_module, "embed_texts", fake_embed)

    monkeypatch.setattr(
        "modstore_server.llm_key_resolver.resolve_api_key",
        lambda session, uid, prov: ("dummy-key", "test"),
    )
    monkeypatch.setattr(
        "modstore_server.llm_key_resolver.resolve_base_url", lambda session, uid, prov: None
    )

    config = {
        "cognition": {
            "system_prompt": "You are an assistant.",
            "model": {"provider": "openai", "model_name": "gpt-test"},
            "knowledge": {"enabled": True, "top_k": 3},
        }
    }
    perceived = {"normalized_input": {"task": "deploy"}, "type": "text"}
    memory = {"session": {}, "long_term": None}

    out = asyncio.run(
        ee._cognition_real(
            config["cognition"],
            perceived,
            memory,
            session=None,
            user_id=1,
            employee_id="emp-pack-1",
            task="What is the deployment secret?",
        )
    )

    assert out["reasoning"] == "answered using knowledge"
    assert out["knowledge"]["enabled"] is True
    assert out["knowledge"]["count"] == 1

    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    sys_content = msgs[0]["content"]
    assert "You are an assistant." in sys_content
    assert "The deployment secret is XYZ." in sys_content
    assert "[1]" in sys_content
    assert "deploy.md" in sys_content


def test_cognition_disabled_when_knowledge_off(tmp_path, monkeypatch):
    models, ve, rag, ee = _bootstrap(tmp_path, monkeypatch)

    captured: dict = {}

    async def fake_chat_dispatch(
        _session, _user_id, _provider, _model, messages, *, max_tokens=None
    ):
        captured["messages"] = messages
        return {"ok": True, "content": "no knowledge needed", "raw": {}, "usage": {}}

    monkeypatch.setattr(ee, "chat_dispatch_via_session", fake_chat_dispatch)
    monkeypatch.setattr(
        "modstore_server.llm_key_resolver.resolve_api_key",
        lambda session, uid, prov: ("dummy", "test"),
    )
    monkeypatch.setattr(
        "modstore_server.llm_key_resolver.resolve_base_url", lambda session, uid, prov: None
    )

    out = asyncio.run(
        ee._cognition_real(
            {"system_prompt": "p", "model": {"provider": "openai", "model_name": "gpt-test"}},
            {"normalized_input": {}},
            {"session": {}, "long_term": None},
            session=None,
            user_id=1,
            employee_id="emp-x",
            task="hi",
        )
    )
    assert out["knowledge"]["enabled"] is False
    sys_content = captured["messages"][0]["content"]
    assert "资料库片段" not in sys_content
