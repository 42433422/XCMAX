"""Frozen runtime column repairs; every DDL emitter retains its public policy name.

These repairs only back-fill historical columns. New schema belongs to Alembic.
Engine choice is supplied separately because its proxy policy differs from auth.
"""

from __future__ import annotations

from dataclasses import dataclass
from logging import Logger

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.bootstrap.contracts import InspectorFactory
from app.utils.operational_errors import RECOVERABLE_ERRORS


@dataclass(frozen=True)
class LegacyColumnRepairs:
    inspect: InspectorFactory
    logger: Logger

    def ensure_sessions_market_access_token_column(self, real_engine: Engine) -> None:
        try:
            insp = self.inspect(real_engine)
            tables = set(insp.get_table_names() or [])
            if "sessions" not in tables:
                return
            cols = {c["name"] for c in insp.get_columns("sessions")}
            if "market_access_token" in cols:
                return
            self.logger.info("sessions 缺少 market_access_token 列，正在补齐 …")
            with real_engine.begin() as conn:
                if real_engine.dialect.name == "postgresql":
                    conn.execute(
                        text(
                            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_access_token TEXT"
                        )
                    )
                else:
                    conn.execute(text("ALTER TABLE sessions ADD COLUMN market_access_token TEXT"))
            self.logger.info("sessions.market_access_token 已补齐")
        except RECOVERABLE_ERRORS as exc:
            self.logger.warning(
                "sessions.market_access_token 兼容补列失败（可在仓库根执行 alembic upgrade head）：%s",
                exc,
            )
        try:
            insp = self.inspect(real_engine)
            tables = set(insp.get_table_names() or [])
            if "sessions" not in tables:
                return
            cols = {c["name"] for c in insp.get_columns("sessions")}
            if "market_access_token" not in cols:
                raise RuntimeError(
                    "数据库表 sessions 缺少 market_access_token 列且自动补齐失败。请在 FHD 仓库根执行: alembic upgrade head"
                )
        except RuntimeError:
            raise
        except RECOVERABLE_ERRORS as verify_exc:
            self.logger.warning("sessions.market_access_token 列校验跳过: %s", verify_exc)

    def ensure_sessions_market_refresh_token_column(self, real_engine: Engine) -> None:
        try:
            insp = self.inspect(real_engine)
            tables = set(insp.get_table_names() or [])
            if "sessions" not in tables:
                return
            cols = {c["name"] for c in insp.get_columns("sessions")}
            if "market_refresh_token" in cols:
                return
            self.logger.info("sessions 缺少 market_refresh_token 列，正在补齐 …")
            with real_engine.begin() as conn:
                if real_engine.dialect.name == "postgresql":
                    conn.execute(
                        text(
                            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_refresh_token TEXT"
                        )
                    )
                else:
                    conn.execute(text("ALTER TABLE sessions ADD COLUMN market_refresh_token TEXT"))
            self.logger.info("sessions.market_refresh_token 已补齐")
        except RECOVERABLE_ERRORS as exc:
            self.logger.warning(
                "sessions.market_refresh_token 兼容补列失败（可在仓库根执行 alembic upgrade head）：%s",
                exc,
            )

    def ensure_sessions_enterprise_entitlement_columns(self, real_engine: Engine) -> None:
        try:
            insp = self.inspect(real_engine)
            tables = set(insp.get_table_names() or [])
            if "sessions" not in tables:
                return
            cols = {c["name"] for c in insp.get_columns("sessions")}
            dialect = real_engine.dialect.name
            with real_engine.begin() as conn:
                if "market_user_id" not in cols:
                    self.logger.info("sessions 缺少 market_user_id 列，正在补齐 …")
                    if dialect == "postgresql":
                        conn.execute(
                            text(
                                "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_user_id INTEGER"
                            )
                        )
                    else:
                        conn.execute(text("ALTER TABLE sessions ADD COLUMN market_user_id INTEGER"))
                if "entitled_mod_ids_json" not in cols:
                    self.logger.info("sessions 缺少 entitled_mod_ids_json 列，正在补齐 …")
                    if dialect == "postgresql":
                        conn.execute(
                            text(
                                "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS entitled_mod_ids_json TEXT"
                            )
                        )
                    else:
                        conn.execute(
                            text("ALTER TABLE sessions ADD COLUMN entitled_mod_ids_json TEXT")
                        )
        except RECOVERABLE_ERRORS as exc:
            self.logger.warning(
                "sessions 企业权益列兼容补列失败（可执行 alembic upgrade head）：%s", exc
            )

    def ensure_sessions_account_meta_columns(self, real_engine: Engine) -> None:
        additions = [
            ("account_kind", "VARCHAR(32)", "'enterprise'"),
            ("company_brand", "VARCHAR(256)", "''"),
            ("market_is_admin", "BOOLEAN", "FALSE"),
            ("market_is_enterprise", "BOOLEAN", "FALSE"),
            ("impersonating_market_user_id", "INTEGER", None),
            ("impersonating_username", "VARCHAR(128)", "''"),
            ("tenant_id", "INTEGER", None),
            ("market_membership_tier", "VARCHAR(32)", None),
        ]
        try:
            insp = self.inspect(real_engine)
            tables = set(insp.get_table_names() or [])
            if "sessions" not in tables:
                return
            cols = {c["name"] for c in insp.get_columns("sessions")}
            dialect = real_engine.dialect.name
            with real_engine.begin() as conn:
                for name, col_type, default_sql in additions:
                    if name in cols:
                        continue
                    self.logger.info("sessions 缺少 %s 列，正在补齐 …", name)
                    if dialect == "postgresql":
                        default_clause = f" DEFAULT {default_sql}" if default_sql else ""
                        conn.execute(
                            text(
                                f"ALTER TABLE sessions ADD COLUMN IF NOT EXISTS {name} {col_type}{default_clause}"
                            )
                        )
                    else:
                        default_clause = f" DEFAULT {default_sql}" if default_sql else ""
                        conn.execute(
                            text(
                                f"ALTER TABLE sessions ADD COLUMN {name} {col_type}{default_clause}"
                            )
                        )
        except RECOVERABLE_ERRORS as exc:
            self.logger.warning("sessions 账号元数据列兼容补列失败: %s", exc)

    def ensure_users_tenant_id_column(self, real_engine: Engine) -> None:
        try:
            insp = self.inspect(real_engine)
            tables = set(insp.get_table_names() or [])
            if "users" not in tables:
                return
            cols = {c["name"] for c in insp.get_columns("users")}
            if "tenant_id" in cols:
                return
            self.logger.info("users 缺少 tenant_id 列，正在补齐 …")
            with real_engine.begin() as conn:
                if real_engine.dialect.name == "postgresql":
                    conn.execute(
                        text("ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id INTEGER")
                    )
                else:
                    conn.execute(text("ALTER TABLE users ADD COLUMN tenant_id INTEGER"))
            self.logger.info("users.tenant_id 已补齐")
        except RECOVERABLE_ERRORS as exc:
            self.logger.warning("users.tenant_id 兼容补列失败: %s", exc)

    def ensure_business_tenant_id_columns(self, real_engine: Engine) -> None:
        business_tables = (
            "products",
            "customers",
            "purchase_units",
            "materials",
            "shipment_records",
            "financial_transactions",
            "suppliers",
            "purchase_orders",
            "purchase_order_items",
            "purchase_inbounds",
            "purchase_inbound_items",
            "warehouses",
            "storage_locations",
            "inventory_ledger",
            "inventory_transactions",
            "templates",
        )
        try:
            insp = self.inspect(real_engine)
            existing = set(insp.get_table_names() or [])
            dialect = real_engine.dialect.name
            with real_engine.begin() as conn:
                for table in business_tables:
                    if table not in existing:
                        continue
                    cols = {c["name"] for c in insp.get_columns(table)}
                    if "tenant_id" in cols:
                        continue
                    self.logger.info("%s 缺少 tenant_id 列，正在补齐 …", table)
                    if dialect == "postgresql":
                        conn.execute(
                            text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id INTEGER")
                        )
                    else:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN tenant_id INTEGER"))
        except RECOVERABLE_ERRORS as exc:
            self.logger.warning("业务表 tenant_id 兼容补列失败: %s", exc)

    def ensure_user_profile_columns(self, real_engine: Engine) -> None:
        try:
            insp = self.inspect(real_engine)
            tables = set(insp.get_table_names() or [])
            if "users" not in tables:
                return
            cols = {c["name"] for c in insp.get_columns("users")}
            dialect = real_engine.dialect.name
            json_type = "JSONB" if dialect == "postgresql" else "TEXT"
            additions = [
                ("market_user_id", "INTEGER", None),
                ("tier", "VARCHAR(32)", "'personal'"),
                ("industry_id", "VARCHAR(32)", "'通用'"),
                ("account_tier", "VARCHAR(32)", None),
                ("budget_range", "VARCHAR(32)", None),
                ("entitled_industries", json_type, None),
                ("failed_login_attempts", "INTEGER", "0"),
                ("locked_until", "TIMESTAMP", None),
                ("email_verified", "BOOLEAN", "FALSE"),
            ]
            with real_engine.begin() as conn:
                for name, col_type, default_sql in additions:
                    if name in cols:
                        continue
                    self.logger.info("users 缺少 %s 列，正在补齐 …", name)
                    default_clause = f" DEFAULT {default_sql}" if default_sql else ""
                    if dialect == "postgresql":
                        conn.execute(
                            text(
                                f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {col_type}{default_clause}"
                            )
                        )
                    else:
                        conn.execute(
                            text(f"ALTER TABLE users ADD COLUMN {name} {col_type}{default_clause}")
                        )
                # NULL 可重复，非空市场用户 ID 必须唯一；账号改名后仍能命中同一客户资料。
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_market_user_id "
                        "ON users (market_user_id)"
                    )
                )
            self.logger.info("users 账号/行业列已补齐")
        except RECOVERABLE_ERRORS as exc:
            self.logger.warning("users 账号/行业列兼容补列失败: %s", exc)

    def init_approval_tables(self, real_engine: Engine) -> None:
        try:
            insp = self.inspect(real_engine)
            if "approval_flows" in set(insp.get_table_names() or []):
                cols = {c["name"] for c in insp.get_columns("approval_flows")}
                if "business_type" not in cols:
                    self.logger.info("approval_flows 缺少 business_type 列，开始补列 …")
                    with real_engine.begin() as conn:
                        if real_engine.dialect.name == "postgresql":
                            conn.execute(
                                text(
                                    "ALTER TABLE approval_flows ADD COLUMN IF NOT EXISTS business_type VARCHAR(64) DEFAULT 'general'"
                                )
                            )
                            conn.execute(
                                text(
                                    "CREATE INDEX IF NOT EXISTS ix_approval_flows_business_type ON approval_flows (business_type)"
                                )
                            )
                        else:
                            conn.execute(
                                text(
                                    "ALTER TABLE approval_flows ADD COLUMN business_type VARCHAR(64) DEFAULT 'general'"
                                )
                            )
                    self.logger.info("approval_flows.business_type 已补齐")
        except RECOVERABLE_ERRORS as exc:
            self.logger.warning("approval_flows.business_type 兼容补列失败: %s", exc)

    def ensure_product_query_indexes(self, engine: Engine) -> None:
        try:
            insp = self.inspect(engine)
            names = set(insp.get_table_names() or [])
        except RECOVERABLE_ERRORS:
            names = set()
        if "products" not in names:
            return
        stmts = [
            "CREATE INDEX IF NOT EXISTS ix_products_unit ON products (unit)",
            "CREATE INDEX IF NOT EXISTS ix_products_model_number ON products (model_number)",
        ]
        with engine.begin() as conn:
            for sql in stmts:
                try:
                    conn.execute(text(sql))
                except RECOVERABLE_ERRORS as e:
                    self.logger.debug("创建 products 索引跳过: %s | %s", sql, e)
