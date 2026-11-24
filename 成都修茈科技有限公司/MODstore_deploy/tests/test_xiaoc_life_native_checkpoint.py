"""Native LangGraph saver smoke: restart a saved pre-act thread, never replay an effect."""

from __future__ import annotations

import asyncio
import os
from typing import TypedDict
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from modstore_server import xiaoc_life_store as store
from modstore_server.xiaoc_life_native_checkpoint import (
    native_life_checkpointer,
    native_thread_config,
)


class _State(TypedDict, total=False):
    observed: str
    progress: str


async def _exercise_restart() -> None:
    from langgraph.graph import END, START, StateGraph

    calls = []

    def observe(state: _State) -> _State:
        return {"observed": state.get("observed", "")}

    def effect(_state: _State) -> _State:
        calls.append("only-once")
        return {"progress": "done"}

    def graph(saver):
        builder = StateGraph(_State)
        builder.add_node("observe", observe)
        builder.add_node("effect", effect)
        builder.add_edge(START, "observe")
        builder.add_edge("observe", "effect")
        builder.add_edge("effect", END)
        return builder.compile(checkpointer=saver, interrupt_before=["effect"])

    config = native_thread_config({"cycle_id": uuid4().hex})
    async with native_life_checkpointer() as saver:
        compiled = graph(saver)
        await compiled.ainvoke({"observed": "original"}, config, durability="sync")
        suspended = await compiled.aget_state(config)
        assert tuple(suspended.next) == ("effect",)
        assert not calls
    # A completely fresh connection and graph instance reads the same state.
    async with native_life_checkpointer() as saver:
        compiled = graph(saver)
        recovered = await compiled.aget_state(config)
        assert recovered.values["observed"] == "original"
        assert tuple(recovered.next) == ("effect",)
        completed = await compiled.ainvoke(None, config, durability="sync")
        assert completed["progress"] == "done"
        assert calls == ["only-once"]
    async with native_life_checkpointer() as saver:
        compiled = graph(saver)
        done = await compiled.aget_state(config)
        assert not done.next
        assert (await compiled.ainvoke(None, config, durability="sync"))["progress"] == "done"
        assert calls == ["only-once"]


@pytest.mark.asyncio
async def test_sqlite_native_checkpoint_survives_connection_restart(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'native.sqlite'}")
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(store, "get_session_factory", lambda: factory)
    try:
        await _exercise_restart()
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("MODSTORE_TEST_POSTGRES_URL"),
    reason="requires isolated PostgreSQL fixture",
)
@pytest.mark.asyncio
async def test_postgres_native_checkpoint_reopens_original_thread(monkeypatch):
    url = os.environ["MODSTORE_TEST_POSTGRES_URL"]
    admin = create_engine(url)
    assert admin.dialect.name == "postgresql"
    schema = f"xiaoc_graph_{uuid4().hex}"
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = None
    try:
        engine = create_engine(
            url, connect_args={"options": f"-csearch_path={schema}"}, pool_pre_ping=True
        )
        factory = sessionmaker(bind=engine)
        monkeypatch.setattr(store, "get_session_factory", lambda: factory)
        await _exercise_restart()
        assert engine.pool.checkedout() == 0
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("cycle_id", ["", None, "x" * 97])
def test_native_thread_rejects_invalid_cycle_identity(cycle_id):
    with pytest.raises(ValueError):
        native_thread_config({"cycle_id": cycle_id})
