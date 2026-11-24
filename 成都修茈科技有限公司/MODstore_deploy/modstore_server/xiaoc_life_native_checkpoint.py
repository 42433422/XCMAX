"""Native LangGraph persistence for the existing SQL-authorized XiaoC life graph.

The life row owns authorization, CAS and budget. LangGraph checkpoints are
progress snapshots only and must never be used as execution authority.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from modstore_server.xiaoc_life_policy import IDENTITY_ID


def native_thread_config(claim: dict[str, Any]) -> dict[str, Any]:
    """Bind all persisted graph steps to the ORIGINAL immutable cycle."""
    cycle_id = claim["cycle_id"]
    if not isinstance(cycle_id, str) or not 0 < len(cycle_id) <= 96:
        raise ValueError("invalid life checkpoint cycle identity")
    return {
        "configurable": {"thread_id": f"{IDENTITY_ID}:{cycle_id}"},
        "recursion_limit": 8,
    }


@asynccontextmanager
async def native_life_checkpointer() -> AsyncIterator[Any]:
    """Use the already-configured business database, not a new authority.

    sqlite :memory: is only ephemeral test/development storage; file-backed
    SQLite and PostgreSQL use their actual persisted stores.
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    from modstore_server import xiaoc_life_store

    # The forked checkpoint package supports strict msgpack deserialization.
    serde = JsonPlusSerializer(allowed_msgpack_modules=None)
    with xiaoc_life_store.get_session_factory()() as session:
        engine = session.get_bind()
        dialect = engine.dialect.name
        url = engine.url

    if dialect == "postgresql":
        import re

        from sqlalchemy import text

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # The business engine may set search_path through connect_args rather
        # than the URL. Discover the effective schema with the SAME role, then
        # bind the native saver to that schema. Never leak to public by default.
        with xiaoc_life_store.get_session_factory()() as session:
            schema = session.execute(text("SELECT current_schema()")).scalar_one()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,62}", schema):
            raise RuntimeError("life checkpoint schema is not safely addressable")
        conn_string = (
            url.set(drivername="postgresql")
            .update_query_dict({"options": f"-csearch_path={schema}"})
            .render_as_string(hide_password=False)
        )
        async with AsyncPostgresSaver.from_conn_string(
            conn_string, serde=serde
        ) as saver:
            await saver.setup()
            yield saver
    elif dialect == "sqlite":
        import aiosqlite

        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        db_path = url.database or ":memory:"
        async with aiosqlite.connect(db_path) as conn:
            saver = AsyncSqliteSaver(conn, serde=serde)
            await saver.setup()
            yield saver
    else:
        raise RuntimeError("life checkpoint requires PostgreSQL or SQLite")
