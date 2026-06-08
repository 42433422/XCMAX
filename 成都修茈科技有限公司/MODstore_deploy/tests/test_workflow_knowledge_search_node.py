"""验证 workflow_engine 的 knowledge_search 节点：执行 + 沙盒 mock + 校验。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


def _bootstrap(tmp_path: Path, monkeypatch):
    try:
        import chromadb  # noqa: F401
    except Exception:  # noqa: BLE001
        pytest.skip("chromadb 未安装；跳过 knowledge_search 节点测试")

    monkeypatch.setenv("MODSTORE_VECTOR_BACKEND", "chroma")
    monkeypatch.setenv("MODSTORE_VECTOR_DB_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))

    import modstore_server.models as models
    import modstore_server.rag_service as rag
    import modstore_server.vector_engine as ve
    import modstore_server.workflow_engine as we

    models._engine = None
    models._SessionFactory = None
    importlib.reload(ve)
    importlib.reload(rag)
    importlib.reload(we)
    ve.reset_client_for_tests()
    models.init_db()
    return models, ve, rag, we


def test_engine_registers_knowledge_search_executor(tmp_path, monkeypatch):
    models, ve, rag, we = _bootstrap(tmp_path, monkeypatch)
    eng = we.WorkflowEngine()
    assert "knowledge_search" in eng.executors


def test_knowledge_search_node_runs_against_authorized_collection(tmp_path, monkeypatch):
    models, ve, rag, we = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.models import KnowledgeCollection, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        coll = KnowledgeCollection(owner_kind="user", owner_id="1", name="kb", visibility="private")
        session.add(coll)
        session.commit()
        session.refresh(coll)

    ve.upsert(
        ve.kb_collection_name(int(coll.id)),
        ids=["d:0", "d:1"],
        embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        documents=["alpha bravo", "charlie delta"],
        metadatas=[
            {"doc_id": "d", "filename": "n.md", "chunk_id": "d:0"},
            {"doc_id": "d", "filename": "n.md", "chunk_id": "d:1"},
        ],
    )

    import modstore_server.rag_service as rag_module

    async def fake_embed(texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(rag_module, "embed_texts", fake_embed)

    eng = we.WorkflowEngine()

    class _Node:
        node_type = "knowledge_search"
        name = "kb-node"

    config = {
        "query": "alpha",
        "collection_ids": [int(coll.id)],
        "top_k": 2,
        "output_var": "kb_result",
    }
    out = eng._execute_knowledge_search_node(_Node(), {}, config, user_id=1)
    assert "kb_result" in out
    assert out["kb_result"]["count"] >= 1
    assert out["kb_result"]["query"] == "alpha"
    assert "alpha" in out["kb_result"]["items"][0]["content"]


def test_knowledge_search_validator_requires_query(tmp_path, monkeypatch):
    models, ve, rag, we = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.models import (
        User,
        Workflow,
        WorkflowEdge,
        WorkflowNode,
        get_session_factory,
    )
    from modstore_server.workflow_engine import WorkflowValidator

    sf = get_session_factory()
    with sf() as session:
        u = User(username="kb-test", password_hash="x")
        session.add(u)
        session.commit()
        session.refresh(u)
        wf = Workflow(user_id=u.id, name="wf-bad")
        session.add(wf)
        session.commit()
        session.refresh(wf)
        n_start = WorkflowNode(workflow_id=wf.id, node_type="start", name="s", config="{}")
        n_kb_bad = WorkflowNode(
            workflow_id=wf.id,
            node_type="knowledge_search",
            name="kb",
            config=json.dumps({"top_k": 5}),
        )
        n_end = WorkflowNode(workflow_id=wf.id, node_type="end", name="e", config="{}")
        session.add_all([n_start, n_kb_bad, n_end])
        session.commit()

        errs = WorkflowValidator.validate_workflow(wf, session)
        assert any("query" in e for e in errs)

        n_kb_bad.config = json.dumps({"query": "hi", "collection_ids": [1]})
        session.commit()

        errs2 = WorkflowValidator.validate_workflow(wf, session)
        assert not any("knowledge" in e and "query" in e for e in errs2)
