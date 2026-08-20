# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.db.init_db")


def init_template_tables(db_path: str | None = None) -> None:
    """
    初始化模板相关表：
    - templates
    - template_usage_log

    兼容策略：
    - 表不存在时创建
    - 表已存在但缺少新字段时自动补齐
    """
    db_path = db_path or _facade().get_db_path("products.db")
    with _facade().sqlite_conn(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "\n            CREATE TABLE IF NOT EXISTS templates (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                template_key TEXT,\n                template_name TEXT NOT NULL,\n                template_type TEXT,\n                original_file_path TEXT,\n                analyzed_data TEXT,\n                editable_config TEXT,\n                zone_config TEXT,\n                merged_cells_config TEXT,\n                style_config TEXT,\n                business_rules TEXT,\n                is_active INTEGER DEFAULT 1,\n                tenant_id INTEGER,\n                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n            )\n            "
        )
        cur.execute(
            "\n            CREATE TABLE IF NOT EXISTS template_usage_log (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                template_id INTEGER NOT NULL,\n                action TEXT NOT NULL,\n                result TEXT,\n                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n            )\n            "
        )
        cur.execute(
            "\n            CREATE INDEX IF NOT EXISTS idx_templates_type_active\n            ON templates (template_type, is_active)\n            "
        )
        cur.execute(
            "\n            CREATE INDEX IF NOT EXISTS idx_template_usage_log_template_id\n            ON template_usage_log (template_id)\n            "
        )
        cur.execute("PRAGMA table_info(templates)")
        templates_columns = {str(row[1]).strip() for row in cur.fetchall() or []}
        required_templates_columns = {
            "template_key": "ALTER TABLE templates ADD COLUMN template_key TEXT",
            "template_name": "ALTER TABLE templates ADD COLUMN template_name TEXT",
            "template_type": "ALTER TABLE templates ADD COLUMN template_type TEXT",
            "original_file_path": "ALTER TABLE templates ADD COLUMN original_file_path TEXT",
            "analyzed_data": "ALTER TABLE templates ADD COLUMN analyzed_data TEXT",
            "editable_config": "ALTER TABLE templates ADD COLUMN editable_config TEXT",
            "zone_config": "ALTER TABLE templates ADD COLUMN zone_config TEXT",
            "merged_cells_config": "ALTER TABLE templates ADD COLUMN merged_cells_config TEXT",
            "style_config": "ALTER TABLE templates ADD COLUMN style_config TEXT",
            "business_rules": "ALTER TABLE templates ADD COLUMN business_rules TEXT",
            "is_active": "ALTER TABLE templates ADD COLUMN is_active INTEGER DEFAULT 1",
            "created_at": "ALTER TABLE templates ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "ALTER TABLE templates ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "tenant_id": "ALTER TABLE templates ADD COLUMN tenant_id INTEGER",
        }
        for column_name, sql in required_templates_columns.items():
            if column_name not in templates_columns:
                cur.execute(sql)
        cur.execute("PRAGMA table_info(template_usage_log)")
        usage_columns = {str(row[1]).strip() for row in cur.fetchall() or []}
        required_usage_columns = {
            "template_id": "ALTER TABLE template_usage_log ADD COLUMN template_id INTEGER",
            "action": "ALTER TABLE template_usage_log ADD COLUMN action TEXT",
            "result": "ALTER TABLE template_usage_log ADD COLUMN result TEXT",
            "created_at": "ALTER TABLE template_usage_log ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
        for column_name, sql in required_usage_columns.items():
            if column_name not in usage_columns:
                cur.execute(sql)
        conn.commit()


def init_template_tables_for_engine(engine: _facade().Engine) -> None:
    """
    在主库（PostgreSQL）上创建 templates / template_usage_log。
    与 Alembic f0c2a8e1_templates 对齐；启动时幂等补齐，便于未跑迁移的环境。
    """
    from sqlalchemy import inspect, text

    if engine.dialect.name != "postgresql":
        return
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    with engine.begin() as conn:
        if "templates" not in existing:
            conn.execute(
                text(
                    "\n                    CREATE TABLE templates (\n                        id BIGSERIAL PRIMARY KEY,\n                        template_key TEXT,\n                        template_name TEXT NOT NULL,\n                        template_type TEXT,\n                        original_file_path TEXT,\n                        analyzed_data TEXT,\n                        editable_config TEXT,\n                        zone_config TEXT,\n                        merged_cells_config TEXT,\n                        style_config TEXT,\n                        business_rules TEXT,\n                        is_active INTEGER DEFAULT 1,\n                        tenant_id INTEGER,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    "
                )
            )
        if "template_usage_log" not in existing:
            conn.execute(
                text(
                    "\n                    CREATE TABLE template_usage_log (\n                        id BIGSERIAL PRIMARY KEY,\n                        template_id BIGINT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,\n                        action TEXT NOT NULL,\n                        result TEXT,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                    "
                )
            )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_templates_type_active ON templates (template_type, is_active)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_template_usage_log_template_id ON template_usage_log (template_id)"
            )
        )


def _resolve_auth_bootstrap_engine(
    engine: _facade().Engine | None = None, *, database_url: str | None = None
) -> _facade().Engine | None:
    from sqlalchemy.engine import Engine as _Engine

    real_engine: _Engine | None = None
    url = (database_url or "").strip()
    if url:
        try:
            from app.db import _create_engine_for_url

            real_engine = _create_engine_for_url(url)
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("auth bootstrap: 无法按 DATABASE_URL 创建引擎: %s", exc)
    if real_engine is None and engine is not None:
        if isinstance(engine, _Engine):
            real_engine = engine
        else:
            try:
                from app.db import _get_engine as _get_real_engine

                real_engine = _get_real_engine()
            except _facade().RECOVERABLE_ERRORS:
                real_engine = None
    if real_engine is None:
        try:
            from app.db import _get_engine as _get_real_engine

            real_engine = _get_real_engine()
        except _facade().RECOVERABLE_ERRORS:
            return None
    return real_engine


def _seed_default_admin_user(real_engine: _facade().Engine) -> None:
    from sqlalchemy import text

    from app.utils.security.password_hash import generate_password_hash
    from app.utils.time import utc_now_naive

    with real_engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    if int(n or 0) != 0:
        return
    username = (_facade().os.environ.get("ADMIN_USERNAME") or "admin").strip()
    password = (_facade().os.environ.get("ADMIN_PASSWORD") or "admin123").strip()
    display_name = (_facade().os.environ.get("ADMIN_DISPLAY_NAME") or "管理员").strip() or "管理员"
    if not username or not password:
        _facade().logger.warning(
            "auth bootstrap: users 为空但未配置 ADMIN_USERNAME/ADMIN_PASSWORD，跳过种子"
        )
        return
    hp = generate_password_hash(password)
    with real_engine.begin() as conn:
        conn.execute(
            text(
                "\n                INSERT INTO users (\n                    username, password, display_name, email, role,\n                    is_active, mfa_enabled, tier, industry_id, created_at,\n                    failed_login_attempts, email_verified\n                )\n                VALUES (\n                    :username, :password, :display_name, :email, 'admin',\n                    TRUE, FALSE, 'admin', :industry_id, :now,\n                    0, FALSE\n                )\n                "
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
    _facade().logger.info("已写入初始管理员账户（username=%s）", username)


def ensure_sqlite_auth_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """桌面 SQLite 首启：创建 users/sessions 并写入默认管理员，避免 /api/auth/login 500。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.user import Session, User

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "sqlite":
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "users" not in tables or "sessions" not in tables:
            _facade().logger.info("SQLite 缺少 users/sessions，正在通过 ORM 创建 …")
            Base.metadata.create_all(
                real_engine,
                tables=[_facade()._orm_table(User), _facade()._orm_table(Session)],
                checkfirst=True,
            )
        _facade()._seed_default_admin_user(real_engine)
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning("ensure_sqlite_auth_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise


def _seed_sqlite_rbac_defaults(real_engine: _facade().Engine) -> None:
    from sqlalchemy import inspect
    from sqlalchemy.orm import sessionmaker

    from app.db.models.permission import DEFAULT_PERMISSIONS, DEFAULT_ROLES, Permission, Role

    if not {"permissions", "roles", "role_permissions"}.issubset(
        set(inspect(real_engine).get_table_names() or [])
    ):
        return
    SessionLocal = sessionmaker(bind=real_engine)
    with SessionLocal() as session:
        perm_by_code = {perm.code: perm for perm in session.query(Permission).all()}
        for row in DEFAULT_PERMISSIONS:
            perm = perm_by_code.get(row["code"])
            if perm is None:
                perm = Permission(
                    name=row["name"],
                    code=row["code"],
                    description=row.get("description", ""),
                    module=row.get("module", ""),
                )
                session.add(perm)
                perm_by_code[row["code"]] = perm
        session.flush()
        role_by_name = {role.name: role for role in session.query(Role).all()}
        for role_row in DEFAULT_ROLES:
            role = role_by_name.get(role_row["name"])
            if role is None:
                role = Role(
                    name=role_row["name"],
                    description=role_row.get("description", ""),
                    is_system=True,
                )
                session.add(role)
                role_by_name[role.name] = role
            assigned = {permission.code for permission in role.permissions}
            for code in role_row.get("permissions", []):
                perm = perm_by_code.get(code)
                if perm is not None and code not in assigned:
                    role.permissions.append(perm)
                    assigned.add(code)
        session.commit()
    _facade().logger.info("SQLite RBAC 默认权限/角色已增量同步")
