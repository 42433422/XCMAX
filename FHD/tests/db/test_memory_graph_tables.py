from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.memory_graph import MemoryNode, TypedEdge


def test_tables_created():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = sqlalchemy_inspect(engine)
    assert "persy_memory_nodes" in inspector.get_table_names()
    assert "persy_memory_edges" in inspector.get_table_names()


def test_node_persistence():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        node = MemoryNode(
            type="constraint",
            title="test constraint",
            content="test content",
            scope="project",
            scope_id="XCMAX",
            status="active",
        )
        session.add(node)
        session.commit()
        loaded = session.query(MemoryNode).first()
        assert loaded.title == "test constraint"
        assert loaded.metadata_weight == 1.0


def test_edge_persistence():
    """验证 TypedEdge 也能持久化（额外覆盖 plan 未列出的边持久化路径）。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        node_a = MemoryNode(
            type="constraint",
            title="node A",
            content="a",
            scope="project",
            scope_id="XCMAX",
            status="active",
        )
        node_b = MemoryNode(
            type="constraint",
            title="node B",
            content="b",
            scope="project",
            scope_id="XCMAX",
            status="active",
        )
        session.add_all([node_a, node_b])
        session.commit()
        session.refresh(node_a)
        session.refresh(node_b)

        edge = TypedEdge(
            source_node_id=node_a.node_id,
            target_node_id=node_b.node_id,
            type="supersedes",
            context="版本更新",
        )
        session.add(edge)
        session.commit()
        loaded = session.query(TypedEdge).first()
        assert loaded.type.value == "supersedes"
        assert loaded.bidirectional is False


def sqlalchemy_inspect(engine):
    from sqlalchemy import inspect as sqla_inspect

    return sqla_inspect(engine)
