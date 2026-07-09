"""
Database seed copy and auth/bootstrap helpers.

Split from ``init_db.py`` (v10 线内迭代 · 巨石拆分).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from app.db._init_db_facade import module as _init_db_facade
from app.utils.operational_errors import RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

DEFAULT_DB_FILES: tuple[str, ...] = (
    "products.db",
    "inventory.db",
    "voice_learning.db",
    "error_collection.db",
)
def _iter_seed_dirs() -> Iterable[str]:
    """
    返回可能的种子 db 来源目录（按优先级）。
    - resources/db_seed（推荐）
    - base_dir（兼容旧行为）
    - _MEIPASS（打包时解包目录）
    """
    yield _init_db_facade().get_resource_path("db_seed")
    yield _init_db_facade().get_base_dir()
    if hasattr(sys, "_MEIPASS"):
        yield sys._MEIPASS


def initialize_databases(db_files: Iterable[str] = DEFAULT_DB_FILES) -> None:
    """
    初始化数据库文件（主要用于首次运行/打包环境）。
    规则：如果目标目录已存在同名 db，则不覆盖。
    """
    work_dir = _init_db_facade().get_app_data_dir()
    os.makedirs(work_dir, exist_ok=True)

    for db_file in db_files:
        target_path = os.path.join(work_dir, db_file)
        if os.path.exists(target_path):
            continue

        source_path = None
        for seed_dir in _init_db_facade()._iter_seed_dirs():
            cand = os.path.join(seed_dir, db_file)
            if os.path.exists(cand):
                source_path = cand
                break

        if not source_path:
            logger.warning("未找到种子数据库文件：%s（将由 ORM/运行时创建）", db_file)
            continue

        try:
            _init_db_facade().shutil.copy2(source_path, target_path)
            # 轻量检查
            with _init_db_facade().sqlite_conn(target_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                _ = cur.fetchall()
        except RECOVERABLE_ERRORS as e:
            logger.warning("复制数据库失败 %s -> %s: %s", source_path, target_path, e)


def ensure_sqlite_per_mod_database_copies(
    mod_ids: Sequence[str],
    db_files: Iterable[str] = DEFAULT_DB_FILES,
) -> None:
    """
    为每个扩展从「母库」复制出带 Mod 后缀的 SQLite 文件（若目标尚不存在）。

    母库即数据目录下无后缀的 ``products.db`` 等（由 ``initialize_databases`` 从
    ``resources/db_seed`` 首次复制而来）。这样 ``DATABASE_URL`` 按请求头改写为
    ``products__<mod>.db`` 时，各包有独立文件，不会在空文件上直接建表导致与母库「串数据」。
    """
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix

    work_dir = _init_db_facade().get_app_data_dir()
    os.makedirs(work_dir, exist_ok=True)
    seen: set[str] = set()
    for raw_id in mod_ids:
        mod_id = str(raw_id or "").strip()
        if not mod_id or mod_id in seen:
            continue
        seen.add(mod_id)
        for db_name in db_files:
            base_path = os.path.join(work_dir, db_name)
            dest_name = sqlite_filename_with_mod_suffix(db_name, mod_id)
            dest_path = os.path.join(work_dir, dest_name)
            if dest_name == db_name or os.path.exists(dest_path):
                continue
            if not os.path.exists(base_path):
                logger.warning(
                    "无法为 Mod %s 准备专用库：母库不存在 %s（跳过 %s）",
                    mod_id,
                    base_path,
                    dest_name,
                )
                continue
            try:
                _init_db_facade().shutil.copy2(base_path, dest_path)
                logger.info("已为 Mod %s 从母库复制专用 SQLite：%s", mod_id, dest_name)
            except RECOVERABLE_ERRORS as e:
                logger.warning(
                    "复制 Mod 专用库失败 mod=%s %s -> %s: %s",
                    mod_id,
                    base_path,
                    dest_path,
                    e,
                )


def build_mod_database_seed_plan() -> dict[str, Any]:
    """
    供设置页 ``/api/system/test-db/status`` 展示：各扩展对应的 SQLite 文件路径与说明。
    与 manifest 可选字段 ``database.seed_files`` / ``database.notes_zh`` 对齐（若存在）。
    """
    from app.db.sqlite_mod_paths import sqlite_filename_with_mod_suffix

    work_dir = _init_db_facade().get_app_data_dir()
    architecture_note_zh = (
        "SQLite：先有母库（如 products.db，来自 resources/db_seed），"
        "每个扩展使用独立文件名（如 products__<mod>.db）；"
        "启动时若专用文件不存在，会从母库复制一份作为初始种子，之后各包数据互不影响。"
        "PostgreSQL 默认仍共用 DATABASE_URL 中的库；需要一包一库时请设置 "
        "XCAGI_MOD_ISOLATED_DATABASES=1 或为各包配置 XCAGI_MOD_DATABASE_URL_*。"
    )
    mods_out: list[dict[str, Any]] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mm = get_mod_manager()
        metas = mm.list_loaded_mods() or mm.scan_mods()
    except RECOVERABLE_ERRORS:
        metas = []

    for m in metas:
        mid = str(getattr(m, "id", "") or "").strip()
        if not mid:
            continue
        notes = ""
        extra_seeds: list[dict[str, str]] = []
        mod_path = str(getattr(m, "mod_path", "") or "").strip()
        if mod_path:
            man = os.path.join(mod_path, "manifest.json")
            if os.path.isfile(man):
                try:
                    with open(man, encoding="utf-8") as fh:
                        data = json.load(fh)
                    db = data.get("database") if isinstance(data.get("database"), dict) else {}
                    notes = str(db.get("notes_zh") or data.get("database_notes_zh") or "").strip()
                    raw_files = db.get("seed_files") or data.get("database_seed_files") or []
                    if isinstance(raw_files, list):
                        for rel in raw_files:
                            rp = str(rel or "").strip()
                            if not rp:
                                continue
                            ap = os.path.normpath(os.path.join(mod_path, rp))
                            extra_seeds.append({"path": ap})
                    raw_sql = db.get("seed_sql") or data.get("database_seed_sql")
                    if raw_sql:
                        sp = os.path.normpath(os.path.join(mod_path, str(raw_sql).strip()))
                        if os.path.isfile(sp):
                            extra_seeds.append({"path": sp})
                except RECOVERABLE_ERRORS:
                    pass

        seeds: list[dict[str, str]] = [
            {"path": os.path.join(work_dir, "products.db"), "role": "sqlite_mother_products"},
            {
                "path": os.path.join(work_dir, sqlite_filename_with_mod_suffix("products.db", mid)),
                "role": "sqlite_per_mod_products",
            },
        ]
        seeds.extend(extra_seeds)
        mods_out.append(
            {
                "mod_id": mid,
                "database_notes": notes,
                "seeds": seeds,
            }
        )

    return {"architecture_note_zh": architecture_note_zh, "mods": mods_out}

def _resolve_auth_bootstrap_engine(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
) -> Engine | None:
    from sqlalchemy.engine import Engine as _Engine

    real_engine: _Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("auth bootstrap: 无法按 DATABASE_URL 创建引擎: %s", exc)
    if real_engine is None and engine is not None:
        if isinstance(engine, _Engine):
            real_engine = engine
        else:
            try:
                from app.db import _get_engine as _get_real_engine

                real_engine = _get_real_engine()
            except RECOVERABLE_ERRORS:
                real_engine = None
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except RECOVERABLE_ERRORS:
            return None
    return real_engine


def _seed_default_admin_user(real_engine: Engine) -> None:
    from sqlalchemy import text

    from app.utils.password_hash import generate_password_hash
    from app.utils.time import utc_now_naive

    with real_engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    if int(n or 0) != 0:
        return

    username = (os.environ.get("ADMIN_USERNAME") or "admin").strip()
    password = (os.environ.get("ADMIN_PASSWORD") or "admin123").strip()
    display_name = (os.environ.get("ADMIN_DISPLAY_NAME") or "管理员").strip() or "管理员"
    if not username or not password:
        logger.warning("auth bootstrap: users 为空但未配置 ADMIN_USERNAME/ADMIN_PASSWORD，跳过种子")
        return
    hp = generate_password_hash(password)
    with real_engine.begin() as conn:
        # 注意：User 模型多个列为 NOT NULL 但仅有 Python 端 default（无 SQL 服务端默认）：
        # tier / industry_id / failed_login_attempts / email_verified。原生 INSERT 绕过 ORM
        # 不会套用 Python default，必须显式提供，否则空库播种管理员会触发
        # NOT NULL constraint failed（如 users.tier / users.failed_login_attempts）。
        conn.execute(
            text(
                """
                INSERT INTO users (
                    username, password, display_name, email, role,
                    is_active, mfa_enabled, tier, industry_id, created_at,
                    failed_login_attempts, email_verified
                )
                VALUES (
                    :username, :password, :display_name, :email, 'admin',
                    TRUE, FALSE, 'admin', :industry_id, :now,
                    0, FALSE
                )
                """
            ),
            {
                "username": username,
                "password": hp,
                "display_name": display_name,
                "email": f"{username}@local",
                "industry_id": "通用",
                "now": utc_now_naive(),
            },
        )
    logger.info("已写入初始管理员账户（username=%s）", username)


def ensure_sqlite_auth_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """桌面 SQLite 首启：创建 users/sessions 并写入默认管理员，避免 /api/auth/login 500。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.user import Session, User

    real_engine = _init_db_facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "sqlite":
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "users" not in tables or "sessions" not in tables:
            logger.info("SQLite 缺少 users/sessions，正在通过 ORM 创建 …")
            Base.metadata.create_all(
                real_engine,
                tables=[User.__table__, Session.__table__],
                checkfirst=True,
            )
        _init_db_facade()._seed_default_admin_user(real_engine)
    except RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            logger.warning("ensure_sqlite_auth_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise


def _seed_sqlite_rbac_defaults(real_engine: Engine) -> None:
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from app.db.models.permission import DEFAULT_PERMISSIONS, DEFAULT_ROLES, Permission, Role

    with real_engine.connect() as conn:
        perm_count = conn.execute(text("SELECT COUNT(*) FROM permissions")).scalar()
    if int(perm_count or 0) > 0:
        return

    SessionLocal = sessionmaker(bind=real_engine)
    with SessionLocal() as session:
        perm_by_code: dict[str, Permission] = {}
        for row in DEFAULT_PERMISSIONS:
            perm = Permission(
                name=row["name"],
                code=row["code"],
                description=row.get("description", ""),
                module=row.get("module", ""),
            )
            session.add(perm)
            perm_by_code[row["code"]] = perm
        session.flush()
        for role_row in DEFAULT_ROLES:
            role = Role(
                name=role_row["name"],
                description=role_row.get("description", ""),
                is_system=True,
            )
            for code in role_row.get("permissions", []):
                perm = perm_by_code.get(code)
                if perm is not None:
                    role.permissions.append(perm)
            session.add(role)
        session.commit()
    logger.info("SQLite RBAC 默认权限/角色已写入")


def ensure_sqlite_rbac_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """桌面 SQLite：补齐 permissions/roles（/api/auth/me 管理员权限列表依赖）。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.permission import Permission, Role, role_permissions

    real_engine = _init_db_facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "sqlite":
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        needed = {"permissions", "roles", "role_permissions"}
        if not needed.issubset(tables):
            logger.info("SQLite 缺少 RBAC 表，正在通过 ORM 创建 …")
            Base.metadata.create_all(
                real_engine,
                tables=[Permission.__table__, Role.__table__, role_permissions],
                checkfirst=True,
            )
        _init_db_facade()._seed_sqlite_rbac_defaults(real_engine)
    except RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            logger.warning("ensure_sqlite_rbac_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise


def ensure_sqlite_inventory_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """桌面 SQLite 基库：补齐库存、采购、出货和财务汇总相关表。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.finance import FinancialTransaction
    from app.db.models.inventory import (
        InventoryLedger,
        InventoryTransaction,
        StorageLocation,
        Warehouse,
    )
    from app.db.models.product import Product
    from app.db.models.purchase import (
        PurchaseInbound,
        PurchaseInboundItem,
        PurchaseOrder,
        PurchaseOrderItem,
        Supplier,
    )
    from app.db.models.shipment import ShipmentRecord

    real_engine = _init_db_facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "sqlite":
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        needed = {
            "products",
            "warehouses",
            "storage_locations",
            "inventory_ledger",
            "inventory_transactions",
            "suppliers",
            "purchase_orders",
            "purchase_order_items",
            "purchase_inbounds",
            "purchase_inbound_items",
            "shipment_records",
            "financial_transactions",
        }
        if not needed.issubset(tables):
            missing = ", ".join(sorted(needed - tables))
            logger.info("SQLite 缺少业务汇总表，正在通过 ORM 创建: %s", missing)
            Base.metadata.create_all(
                real_engine,
                tables=[
                    Product.__table__,
                    Warehouse.__table__,
                    StorageLocation.__table__,
                    InventoryLedger.__table__,
                    InventoryTransaction.__table__,
                    Supplier.__table__,
                    PurchaseOrder.__table__,
                    PurchaseOrderItem.__table__,
                    PurchaseInbound.__table__,
                    PurchaseInboundItem.__table__,
                    ShipmentRecord.__table__,
                    FinancialTransaction.__table__,
                ],
                checkfirst=True,
            )
    except RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            logger.warning("ensure_sqlite_inventory_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise


def ensure_sqlite_enterprise_business_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """桌面 SQLite 旧库：补齐企业登录/太阳鸟交付依赖的基础业务表。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.customer import Customer
    from app.db.models.product import Product
    from app.db.models.purchase_unit import PurchaseUnit
    from app.db.models.tenant import Tenant

    real_engine = _init_db_facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "sqlite":
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        needed = {"tenants", "customers", "products", "purchase_units"}
        if not needed.issubset(tables):
            logger.info("SQLite 缺少企业业务基础表，正在通过 ORM 创建 …")
            Base.metadata.create_all(
                real_engine,
                tables=[
                    Tenant.__table__,
                    Product.__table__,
                    Customer.__table__,
                    PurchaseUnit.__table__,
                ],
                checkfirst=True,
            )
    except RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            logger.warning(
                "ensure_sqlite_enterprise_business_bootstrap 失败: %s", exc, exc_info=True
            )
            return
        raise


def ensure_user_preferences_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """补齐 user_preferences 表（工作区 prefs 跨设备同步依赖）。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.ai import UserPreference

    real_engine = _init_db_facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None:
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "user_preferences" not in tables:
            logger.info("缺少 user_preferences 表，正在通过 ORM 创建 …")
            Base.metadata.create_all(
                real_engine,
                tables=[UserPreference.__table__],
                checkfirst=True,
            )
    except RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            logger.warning("ensure_user_preferences_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise


def ensure_neuro_event_log_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """补齐 neuro_event_log 表（NeuroBus 核心 app service 消费者的持久落地副作用）。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.neuro_event_log import NeuroEventLog

    real_engine = _init_db_facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None:
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "neuro_event_log" not in tables:
            logger.info("缺少 neuro_event_log 表，正在通过 ORM 创建 …")
            Base.metadata.create_all(
                real_engine,
                tables=[NeuroEventLog.__table__],
                checkfirst=True,
            )
    except RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            logger.warning("ensure_neuro_event_log_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise


def ensure_sqlite_im_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """桌面 SQLite：补齐 IM 三张表 + AI 员工虚拟用户档案表。

    IM 表（im_conversations / im_conversation_members / im_messages）和
    ai_employee_profiles 在 Alembic 迁移链里建；SQLite 桌面模式不跑 Alembic，
    需要这里显式建出来，否则员工主动 IM 推送链路会因缺表 500。
    """
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.ai_employee import AiEmployeeProfile
    from app.db.models.im import ImConversation, ImConversationMember, ImMessage

    real_engine = _init_db_facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "sqlite":
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        needed = {
            "im_conversations",
            "im_conversation_members",
            "im_messages",
            "ai_employee_profiles",
        }
        missing = needed - tables
        if missing:
            logger.info("SQLite 缺少 IM/员工档案表 %s，正在通过 ORM 创建 …", sorted(missing))
            Base.metadata.create_all(
                real_engine,
                tables=[
                    ImConversation.__table__,
                    ImConversationMember.__table__,
                    ImMessage.__table__,
                    AiEmployeeProfile.__table__,
                ],
                checkfirst=True,
            )
    except RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            logger.warning("ensure_sqlite_im_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise


def ensure_runtime_auth_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = False,
) -> None:
    """按运行时 DATABASE_URL 幂等补齐 users/sessions/RBAC/库存表（SQLite 或 PostgreSQL）。"""
    from app.fastapi_app.sqlite_paths import is_sqlite_url, resolve_effective_database_url

    url = (database_url or resolve_effective_database_url() or "").strip()
    if not url:
        return
    if is_sqlite_url(url):
        _init_db_facade().ensure_sqlite_auth_bootstrap(
            engine,
            database_url=url,
            swallow_errors=swallow_errors,
        )
        _init_db_facade().ensure_sqlite_rbac_bootstrap(
            engine,
            database_url=url,
            swallow_errors=swallow_errors,
        )
        _init_db_facade().ensure_sqlite_inventory_bootstrap(
            engine,
            database_url=url,
            swallow_errors=swallow_errors,
        )
        _init_db_facade().ensure_sqlite_enterprise_business_bootstrap(
            engine,
            database_url=url,
            swallow_errors=swallow_errors,
        )
        _init_db_facade().ensure_user_preferences_bootstrap(
            engine,
            database_url=url,
            swallow_errors=swallow_errors,
        )
        _init_db_facade().ensure_neuro_event_log_bootstrap(
            engine,
            database_url=url,
            swallow_errors=swallow_errors,
        )
        _init_db_facade().ensure_sqlite_im_bootstrap(
            engine,
            database_url=url,
            swallow_errors=swallow_errors,
        )
    else:
        _init_db_facade().ensure_postgresql_auth_bootstrap(engine, database_url=url)
        _init_db_facade().ensure_user_preferences_bootstrap(
            engine,
            database_url=url,
            swallow_errors=swallow_errors,
        )
        _init_db_facade().ensure_neuro_event_log_bootstrap(
            engine,
            database_url=url,
            swallow_errors=swallow_errors,
        )
        _init_db_facade().ensure_sqlite_im_bootstrap(
            engine,
            database_url=url,
            swallow_errors=swallow_errors,
        )


def ensure_postgresql_auth_bootstrap(
    engine: Engine | None = None,
    *,
    database_url: str | None = None,
) -> None:
    """空 PostgreSQL 库在未跑 Alembic 时缺少 users/sessions，登录会抛出异常并带上 error_id。

    幂等创建最小表结构；仅在 ``users`` 表无任何行时写入管理员（优先 ``ADMIN_*`` 环境变量，
    否则 ``admin`` / ``admin123``，与 ``d8f5e2a1c9b3_add_rbac_tables`` 种子行为一致。
    业务表仍应通过 ``alembic upgrade head`` 补齐。
    """
    from sqlalchemy import inspect, text

    real_engine = _init_db_facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "postgresql":
        return

    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])

        if "users" not in tables:
            logger.info("PostgreSQL 缺少 users 表，正在创建（空库登录引导）…")
            with real_engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE users (
                            id BIGSERIAL PRIMARY KEY,
                            username VARCHAR NOT NULL UNIQUE,
                            password VARCHAR NOT NULL,
                            display_name VARCHAR DEFAULT '',
                            email VARCHAR DEFAULT '',
                            role VARCHAR DEFAULT 'user',
                            is_active BOOLEAN DEFAULT TRUE,
                            mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                            tier VARCHAR(32) NOT NULL DEFAULT 'personal',
                            industry_id VARCHAR(32) NOT NULL DEFAULT '通用',
                            created_by BIGINT REFERENCES users(id),
                            created_at TIMESTAMP,
                            last_login TIMESTAMP,
                            wx_openid VARCHAR(64),
                            wx_unionid VARCHAR(64),
                            wx_avatar_url TEXT
                        )
                        """
                    )
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS idx_users_is_active ON users (is_active)")
                )
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_users_wx_unionid ON users (wx_unionid)")
                )

        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])

        if "sessions" not in tables:
            if "users" not in tables:
                logger.warning(
                    "ensure_postgresql_auth_bootstrap: users 仍不存在，跳过 sessions 创建"
                )
                return
            logger.info("PostgreSQL 缺少 sessions 表，正在创建 …")
            with real_engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE sessions (
                            id BIGSERIAL PRIMARY KEY,
                            session_id VARCHAR NOT NULL UNIQUE,
                            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                            created_at TIMESTAMP,
                            expires_at TIMESTAMP NOT NULL,
                            market_access_token TEXT,
                            market_refresh_token TEXT
                        )
                        """
                    )
                )

        _init_db_facade()._seed_default_admin_user(real_engine)
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "ensure_postgresql_auth_bootstrap 失败（可改用手工 alembic）：%s", exc, exc_info=True
        )

