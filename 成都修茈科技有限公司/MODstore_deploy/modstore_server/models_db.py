# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from modstore_server.operational_errors import RECOVERABLE_ERRORS

from .models_base import Base
from .models_catalog import UserMod
from .models_cs import CustomerServiceStandard
from .models_db_defaults import (
    DEFAULT_CUSTOMER_SERVICE_STANDARDS,
    DEFAULT_PLAN_TEMPLATES,
)
from .models_order import PlanTemplate, UserPlan
from .models_user import User


def default_db_path() -> Path:
    raw = (os.environ.get("MODSTORE_DB_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parent / "modstore.db"


def database_url(db_path: Optional[Path] = None) -> str:
    if (os.environ.get("MODSTORE_PYTEST_USE_SQLITE") or "").strip() == "1":
        p = db_path or default_db_path()
        return f"sqlite:///{p}"
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if raw:
        if raw.startswith("postgres://"):
            return "postgresql://" + raw[len("postgres://") :]
        return raw
    p = db_path or default_db_path()
    return f"sqlite:///{p}"


_engine = None
_SessionFactory = None


def get_engine(db_path: Optional[Path] = None):
    global _engine
    if _engine is None:
        url = database_url(db_path)
        if url.startswith("sqlite:///"):
            p = Path(url.replace("sqlite:///", "", 1))
            p.parent.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(url, echo=False)
        else:
            _engine = create_engine(
                url,
                echo=False,
                pool_pre_ping=True,
                pool_size=int(os.environ.get("MODSTORE_DB_POOL_SIZE", "10")),
                max_overflow=int(os.environ.get("MODSTORE_DB_MAX_OVERFLOW", "20")),
                pool_recycle=3600,
                pool_timeout=30,
            )
    return _engine


def get_session_factory(db_path: Optional[Path] = None):
    global _SessionFactory
    if _SessionFactory is None:
        engine = get_engine(db_path)
        _SessionFactory = sessionmaker(bind=engine)
    return _SessionFactory


def dispose_engine() -> None:
    """关闭全局 Engine 与连接池（进程优雅退出时调用，避免泄漏到 DB 端）。"""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
        _engine = None
    _SessionFactory = None


def _sqlite_add_column_if_missing(engine, table: str, column: str, ddl_type: str) -> None:
    """SQLite 表结构演进：缺列时 ALTER ADD（幂等）。"""
    with engine.begin() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        if any(row[1] == column for row in rows):
            return
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


def _add_column_if_missing(engine, table: str, column: str, ddl_type: str) -> None:
    """轻量表结构演进：缺列时 ALTER ADD（幂等）。"""
    if engine.dialect.name == "sqlite":
        _sqlite_add_column_if_missing(engine, table, column, ddl_type)
        return
    with engine.begin() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        ).first()
        if exists:
            return
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


def _maybe_bootstrap_first_admin() -> None:
    """空库时按环境变量创建首个管理员（用于 Docker / 一键部署）。

    仅当 ``MODSTORE_BOOTSTRAP_ADMIN`` 为真且 ``users`` 表尚无行时执行。
    生产环境请显式关闭（不设或设为 ``0`` / ``false``）。
    """
    raw = (os.environ.get("MODSTORE_BOOTSTRAP_ADMIN") or "").strip().lower()
    if raw not in ("1", "true", "yes", "on"):
        return
    try:
        from modstore_server.deploy_context import is_production_tier

        if is_production_tier():
            logging.getLogger(__name__).warning(
                "MODSTORE_BOOTSTRAP_ADMIN ignored when MODSTORE_DEPLOY_TIER=production"
            )
            return
    except RECOVERABLE_ERRORS:
        pass
    from modstore_server.auth_service import register_user

    sf = get_session_factory()
    with sf() as session:
        if session.query(User).count() > 0:
            return

    username = (os.environ.get("MODSTORE_BOOTSTRAP_ADMIN_USERNAME") or "admin").strip() or "admin"
    password = (os.environ.get("MODSTORE_BOOTSTRAP_ADMIN_PASSWORD") or "admin123").strip()
    if not password:
        return
    email_raw = (os.environ.get("MODSTORE_BOOTSTRAP_ADMIN_EMAIL") or "admin@localhost").strip()
    email = (email_raw or "admin@localhost").lower()

    try:
        user = register_user(username, password, email)
    except ValueError:
        return

    plan_id = (os.environ.get("MODSTORE_BOOTSTRAP_ADMIN_PLAN") or "plan_pro").strip() or "plan_pro"
    try:
        days = int((os.environ.get("MODSTORE_BOOTSTRAP_ADMIN_PLAN_DAYS") or "365").strip() or "365")
    except ValueError:
        days = 365

    log = logging.getLogger(__name__)
    with sf() as session:
        row = session.query(User).filter(User.id == user.id).first()
        if row:
            row.is_admin = True
        plan = session.query(PlanTemplate).filter(PlanTemplate.id == plan_id).first()
        if plan:
            expires_at = None
            if days > 0:
                expires_at = datetime.now(UTC) + timedelta(days=days)
            session.add(
                UserPlan(
                    user_id=user.id,
                    plan_id=plan_id,
                    started_at=datetime.now(UTC),
                    expires_at=expires_at,
                    is_active=True,
                )
            )
        session.commit()
    log.warning(
        "MODSTORE_BOOTSTRAP_ADMIN: created first user username=%r id=%s (disable in production)",
        username,
        user.id,
    )


def init_db(db_path: Optional[Path] = None):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    try:
        _add_column_if_missing(
            engine,
            "knowledge_collections",
            "embedding_provider",
            "VARCHAR(64) DEFAULT ''",
        )
    except RECOVERABLE_ERRORS:
        pass
    try:
        _add_column_if_missing(
            engine,
            "knowledge_collections",
            "embedding_source",
            "VARCHAR(64) DEFAULT ''",
        )
    except RECOVERABLE_ERRORS:
        pass
    for column, ddl_type in (
        ("material_category", "VARCHAR(64) DEFAULT ''"),
        ("license_scope", "VARCHAR(32) DEFAULT 'personal'"),
        ("origin_type", "VARCHAR(32) DEFAULT 'original'"),
        ("ip_risk_level", "VARCHAR(16) DEFAULT 'low'"),
        ("compliance_status", "VARCHAR(32) DEFAULT 'approved'"),
        ("rank_score", "FLOAT DEFAULT 100.0"),
        ("delist_reason", "TEXT DEFAULT ''"),
    ):
        try:
            _add_column_if_missing(engine, "catalog_items", column, ddl_type)
        except RECOVERABLE_ERRORS:
            pass
    if engine.dialect.name != "sqlite":
        for column, ddl_type in (
            ("migration_status", "TEXT DEFAULT ''"),
            ("migrated_to_id", "INTEGER"),
            ("kind", "TEXT DEFAULT ''"),
        ):
            try:
                _add_column_if_missing(engine, "workflows", column, ddl_type)
            except RECOVERABLE_ERRORS:
                pass
        for column, ddl_type in (
            ("git_branch", "VARCHAR(256) DEFAULT ''"),
            ("base_commit_sha", "VARCHAR(64) DEFAULT ''"),
            ("staged_commit_sha", "VARCHAR(64) DEFAULT ''"),
        ):
            try:
                _add_column_if_missing(engine, "employee_change_requests", column, ddl_type)
            except RECOVERABLE_ERRORS:
                pass
        try:
            _add_column_if_missing(
                engine,
                "employee_trigger_bindings",
                "priority",
                "INTEGER DEFAULT 5 NOT NULL",
            )
        except RECOVERABLE_ERRORS:
            pass
        for column, ddl_type in (
            ("avatar_path", "VARCHAR(512) DEFAULT ''"),
            ("avatar_version", "INTEGER DEFAULT 0 NOT NULL"),
            ("first_login_at", "TIMESTAMP"),
            ("last_login_at", "TIMESTAMP"),
        ):
            try:
                _add_column_if_missing(engine, "users", column, ddl_type)
            except RECOVERABLE_ERRORS:
                pass
        # user_plans：续费字段（缺列会导致 ORM 查询失败并污染客服会话事务）
        for column, ddl_type in (
            ("auto_renew", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("renewal_fail_reason", "TEXT DEFAULT ''"),
            ("source_order_id", "VARCHAR(64) DEFAULT ''"),
        ):
            try:
                _add_column_if_missing(engine, "user_plans", column, ddl_type)
            except RECOVERABLE_ERRORS:
                pass
        init_default_plan_templates()
        init_default_customer_service_standards()
        _maybe_bootstrap_first_admin()
        return
    try:
        _sqlite_add_column_if_missing(engine, "catalog_items", "industry", "TEXT DEFAULT '通用'")
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(engine, "users", "default_llm_json", "TEXT DEFAULT ''")
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(engine, "users", "phone", "TEXT")
    except RECOVERABLE_ERRORS:
        pass
    for column in ("first_login_at", "last_login_at"):
        try:
            _sqlite_add_column_if_missing(engine, "users", column, "DATETIME")
        except RECOVERABLE_ERRORS:
            pass
    try:
        _sqlite_add_column_if_missing(
            engine, "catalog_items", "security_level", "TEXT DEFAULT 'personal'"
        )
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(engine, "catalog_items", "industry_code", "TEXT DEFAULT ''")
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(
            engine, "catalog_items", "industry_secondary", "TEXT DEFAULT ''"
        )
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(
            engine, "catalog_items", "description_embedding", "TEXT DEFAULT ''"
        )
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(
            engine, "catalog_items", "template_category", "TEXT DEFAULT ''"
        )
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(
            engine, "catalog_items", "template_difficulty", "TEXT DEFAULT ''"
        )
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(
            engine, "catalog_items", "install_count", "INTEGER DEFAULT 0 NOT NULL"
        )
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(engine, "catalog_items", "graph_snapshot", "TEXT DEFAULT ''")
    except RECOVERABLE_ERRORS:
        pass
    for column, ddl_type in (
        ("material_category", "TEXT DEFAULT ''"),
        ("license_scope", "TEXT DEFAULT 'personal'"),
        ("origin_type", "TEXT DEFAULT 'original'"),
        ("ip_risk_level", "TEXT DEFAULT 'low'"),
        ("compliance_status", "TEXT DEFAULT 'approved'"),
        ("rank_score", "REAL DEFAULT 100.0"),
        ("delist_reason", "TEXT DEFAULT ''"),
    ):
        try:
            _sqlite_add_column_if_missing(engine, "catalog_items", column, ddl_type)
        except RECOVERABLE_ERRORS:
            pass
    try:
        _sqlite_add_column_if_missing(engine, "users", "experience", "INTEGER DEFAULT 0 NOT NULL")
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(engine, "users", "avatar_path", "TEXT DEFAULT ''")
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(
            engine, "users", "avatar_version", "INTEGER DEFAULT 0 NOT NULL"
        )
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(engine, "workflows", "migration_status", "TEXT DEFAULT ''")
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(engine, "workflows", "migrated_to_id", "INTEGER")
    except RECOVERABLE_ERRORS:
        pass
    try:
        _sqlite_add_column_if_missing(engine, "workflows", "kind", "TEXT DEFAULT ''")
    except RECOVERABLE_ERRORS:
        pass
    for column, ddl_type in (
        ("git_branch", "TEXT DEFAULT ''"),
        ("base_commit_sha", "TEXT DEFAULT ''"),
        ("staged_commit_sha", "TEXT DEFAULT ''"),
    ):
        try:
            _sqlite_add_column_if_missing(engine, "employee_change_requests", column, ddl_type)
        except RECOVERABLE_ERRORS:
            pass
    try:
        _sqlite_add_column_if_missing(
            engine,
            "employee_trigger_bindings",
            "priority",
            "INTEGER DEFAULT 5 NOT NULL",
        )
    except RECOVERABLE_ERRORS:
        pass
    init_default_plan_templates()
    init_default_customer_service_standards()
    _maybe_bootstrap_first_admin()


def init_default_plan_templates() -> None:
    """
    会员体系（与历史 plan_id 保留兼容）：
      - VIP   = plan_basic       入门档
      - VIP+  = plan_pro         进阶档
      - svip  = plan_enterprise  企业级会员入口（展示文案只描述本档）
      - SVIP2..8 = plan_svip2..plan_svip8 进阶 S 级，购买前需已拥有任一 SVIP 档
    旧 plan_id 不变，避免 user_plans / payment_orders 历史数据失效。
    """
    defaults = DEFAULT_PLAN_TEMPLATES
    sf = get_session_factory()
    with sf() as session:
        for row in defaults:
            exists = session.query(PlanTemplate).filter(PlanTemplate.id == row["id"]).first()
            if exists:
                exists.name = row["name"]
                exists.description = row["description"]
                exists.features_json = row["features_json"]
                exists.quotas_json = row["quotas_json"]
                exists.price = row["price"]
                exists.is_active = True
                continue
            session.add(PlanTemplate(**row))
        session.commit()


def init_default_customer_service_standards() -> None:
    """初始化 AI 客服默认审核标准，管理员可在后台继续调整。"""

    defaults = DEFAULT_CUSTOMER_SERVICE_STANDARDS
    sf = get_session_factory()
    with sf() as session:
        for row in defaults:
            exists = (
                session.query(CustomerServiceStandard)
                .filter(CustomerServiceStandard.scenario == row["scenario"])
                .first()
            )
            if exists:
                exists.name = row["name"]
                exists.description = row["description"]
                exists.rules_json = row["rules_json"]
                exists.action_policy_json = row["action_policy_json"]
                exists.risk_level = row["risk_level"]
                exists.priority = row["priority"]
                exists.auto_enabled = True
                continue
            session.add(CustomerServiceStandard(**row))
        session.commit()


def add_user_mod(user_id: int, mod_id: str) -> UserMod:
    """添加用户与 MOD 的关联。"""
    sf = get_session_factory()
    with sf() as session:
        existing = (
            session.query(UserMod)
            .filter(UserMod.user_id == user_id, UserMod.mod_id == mod_id)
            .first()
        )
        if existing:
            return existing
        user_mod = UserMod(user_id=user_id, mod_id=mod_id)
        session.add(user_mod)
        session.commit()
        session.refresh(user_mod)
        return user_mod


def remove_user_mod(user_id: int, mod_id: str) -> bool:
    """删除用户与 MOD 的关联。"""
    sf = get_session_factory()
    with sf() as session:
        user_mod = (
            session.query(UserMod)
            .filter(UserMod.user_id == user_id, UserMod.mod_id == mod_id)
            .first()
        )
        if user_mod:
            session.delete(user_mod)
            session.commit()
            return True
        return False


def get_user_mod_ids(user_id: int) -> list[str]:
    """获取用户拥有的所有 MOD ID 列表。"""
    sf = get_session_factory()
    with sf() as session:
        rows = session.query(UserMod.mod_id).filter(UserMod.user_id == user_id).all()
        return [r[0] for r in rows]


def user_owns_mod(user_id: int, mod_id: str) -> bool:
    """检查用户是否拥有指定 MOD。"""
    sf = get_session_factory()
    with sf() as session:
        return (
            session.query(UserMod)
            .filter(UserMod.user_id == user_id, UserMod.mod_id == mod_id)
            .first()
            is not None
        )
