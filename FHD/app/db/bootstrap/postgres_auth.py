"""Minimal PostgreSQL authentication schema for installations without migrations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.bootstrap.contracts import InspectorFactory
from app.utils.operational_errors import RECOVERABLE_ERRORS


@dataclass(frozen=True)
class PostgresAuthBootstrap:
    inspect: InspectorFactory
    seed: Callable[[Engine], None]
    logger: Logger

    def ensure(self, real_engine: Engine | None) -> None:
        if real_engine is None or real_engine.dialect.name != "postgresql":
            return
        try:
            insp = self.inspect(real_engine)
            tables = set(insp.get_table_names() or [])
            if "users" not in tables:
                self.logger.info("PostgreSQL 缺少 users 表，正在创建（空库登录引导）…")
                with real_engine.begin() as conn:
                    conn.execute(
                        text(
                            "\n                        CREATE TABLE users (\n                            id BIGSERIAL PRIMARY KEY,\n                            username VARCHAR NOT NULL UNIQUE,\n                            password VARCHAR NOT NULL,\n                            display_name VARCHAR DEFAULT '',\n                            email VARCHAR DEFAULT '',\n                            role VARCHAR DEFAULT 'user',\n                            is_active BOOLEAN DEFAULT TRUE,\n                            mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,\n                            tier VARCHAR(32) NOT NULL DEFAULT 'personal',\n                            industry_id VARCHAR(32) NOT NULL DEFAULT '通用',\n                            created_by BIGINT REFERENCES users(id),\n                            created_at TIMESTAMP,\n                            last_login TIMESTAMP,\n                            wx_openid VARCHAR(64),\n                            wx_unionid VARCHAR(64),\n                            wx_avatar_url TEXT\n                        )\n                        "
                        )
                    )
                    conn.execute(
                        text("CREATE INDEX IF NOT EXISTS idx_users_is_active ON users (is_active)")
                    )
                    conn.execute(
                        text("CREATE INDEX IF NOT EXISTS ix_users_wx_unionid ON users (wx_unionid)")
                    )
            insp = self.inspect(real_engine)
            tables = set(insp.get_table_names() or [])
            if "sessions" not in tables:
                if "users" not in tables:
                    self.logger.warning(
                        "ensure_postgresql_auth_bootstrap: users 仍不存在，跳过 sessions 创建"
                    )
                    return
                self.logger.info("PostgreSQL 缺少 sessions 表，正在创建 …")
                with real_engine.begin() as conn:
                    conn.execute(
                        text(
                            "\n                        CREATE TABLE sessions (\n                            id BIGSERIAL PRIMARY KEY,\n                            session_id VARCHAR NOT NULL UNIQUE,\n                            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,\n                            created_at TIMESTAMP,\n                            expires_at TIMESTAMP NOT NULL,\n                            market_access_token TEXT,\n                            market_refresh_token TEXT\n                        )\n                        "
                        )
                    )
            self.seed(real_engine)
        except RECOVERABLE_ERRORS as exc:
            self.logger.warning(
                "ensure_postgresql_auth_bootstrap 失败（可改用手工 alembic）：%s",
                exc,
                exc_info=True,
            )
