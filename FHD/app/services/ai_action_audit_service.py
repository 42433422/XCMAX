"""
AI 操作审计表（轻量 DDL）。启动时由 fastapi_app 调用 ensure_ai_action_audit_table。
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)


def ensure_ai_action_audit_table() -> None:
    """若不存在则创建 ai_action_audit 表（PostgreSQL / SQLite）。"""
    url = str(engine.url).lower()
    if "postgresql" in url or "postgres" in url:
        ddl = """
        CREATE TABLE IF NOT EXISTS ai_action_audit (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            actor TEXT,
            action TEXT NOT NULL,
            payload JSONB
        );
        """
    else:
        ddl = """
        CREATE TABLE IF NOT EXISTS ai_action_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            actor TEXT,
            action TEXT NOT NULL,
            payload TEXT
        );
        """
    with engine.begin() as conn:
        conn.execute(text(ddl))
    logger.info("ai_action_audit 表已就绪")
