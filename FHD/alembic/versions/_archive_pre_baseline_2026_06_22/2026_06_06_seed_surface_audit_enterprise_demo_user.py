"""Seed P-S surface-audit enterprise demo user (non-admin).

Revision ID: 2026_06_06_surface_audit_demo
Revises: 2026_06_05_tenant_saas
"""

from __future__ import annotations

import json
from pathlib import Path

from alembic import op
from sqlalchemy import text

from app.utils.password_hash import generate_password_hash
from app.utils.time import utc_now_naive

revision = "2026_06_06_surface_audit_demo"
down_revision = "2026_06_05_tenant_saas"
branch_labels = None
depends_on = None

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "surface_audit_demo_account.json"


def _cfg() -> dict:
    defaults = {
        "username": "xcagi-enterprise-demo",
        "password": "Demo@2026",
        "display_name": "企业版演示",
        "email": "enterprise-demo@local",
    }
    if _CONFIG.is_file():
        try:
            raw = json.loads(_CONFIG.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {**defaults, **raw}
        except Exception:
            pass
    return defaults


def upgrade() -> None:
    cfg = _cfg()
    username = str(cfg.get("username") or "xcagi-enterprise-demo").strip()
    password = str(cfg.get("password") or "Demo@2026")
    display_name = str(cfg.get("display_name") or "企业版演示").strip()
    email = str(cfg.get("email") or "enterprise-demo@local").strip()
    pwd_hash = generate_password_hash(password)
    now = utc_now_naive()
    conn = op.get_bind()
    row = conn.execute(
        text("SELECT id, role FROM users WHERE username = :u"),
        {"u": username},
    ).fetchone()
    if row:
        conn.execute(
            text(
                """
                UPDATE users
                SET password = :password,
                    display_name = :display_name,
                    email = :email,
                    role = 'user',
                    is_active = TRUE
                WHERE username = :username
                """
            ),
            {
                "username": username,
                "password": pwd_hash,
                "display_name": display_name,
                "email": email,
            },
        )
        return
    conn.execute(
        text(
            """
            INSERT INTO users (username, password, display_name, email, role, is_active, created_at)
            VALUES (:username, :password, :display_name, :email, 'user', TRUE, :now)
            """
        ),
        {
            "username": username,
            "password": pwd_hash,
            "display_name": display_name,
            "email": email,
            "now": now,
        },
    )


def downgrade() -> None:
    username = str(_cfg().get("username") or "xcagi-enterprise-demo").strip()
    conn = op.get_bind()
    conn.execute(text("DELETE FROM users WHERE username = :u"), {"u": username})
