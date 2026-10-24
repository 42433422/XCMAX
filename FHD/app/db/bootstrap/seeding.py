"""Initial administrator and incremental RBAC data, independent of table creation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from logging import Logger

from sqlalchemy.engine import Engine


def seed_admin(
    real_engine: Engine,
    *,
    environment: Mapping[str, str],
    logger: Logger,
    prepare_profile: Callable[[Engine], None],
) -> None:
    from sqlalchemy import text

    from app.utils.security.password_hash import generate_password_hash
    from app.utils.time import utc_now_naive

    with real_engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    if int(n or 0) != 0:
        return
    username = (environment.get("ADMIN_USERNAME") or "admin").strip()
    password = (environment.get("ADMIN_PASSWORD") or "admin123").strip()
    display_name = (environment.get("ADMIN_DISPLAY_NAME") or "管理员").strip() or "管理员"
    if not username or not password:
        logger.warning("auth bootstrap: users 为空但未配置 ADMIN_USERNAME/ADMIN_PASSWORD，跳过种子")
        return
    if real_engine.dialect.name == "postgresql":
        prepare_profile(real_engine)
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
    logger.info("已写入初始管理员账户（username=%s）", username)


def seed_rbac(real_engine: Engine, *, logger: Logger) -> None:
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
    logger.info("SQLite RBAC 默认权限/角色已增量同步")
