"""拟人 Persy：把按会话分片的人格画像合并到账号级键

Revision ID: 2026_11_16_persona_account_key
Revises: 2026_11_16_local_file_access
Create Date: 2026-11-16

历史行为：对话流把 ``web_normal_<session_id>`` 当人格键，导致每开一个新会话就
从零积累。新代码改为使用稳定的本地账号 ID（users.id）作为人格键；本迁移把
能通过 ``ai_conversation_sessions`` / ``ai_conversations`` 回溯到账号的会话画像，
按互动次数加权合并到对应账号行，并同步迁移事件日志。

无法回溯到账号的孤立会话画像保持原样（不再被读取，但保留数据不删除）。
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "2026_11_16_persona_account_key"
down_revision = "2026_11_16_local_file_access"
branch_labels = None
depends_on = None

_AXIS_FIELDS = ("warmth", "detail", "proactivity", "structure")


def _session_account_map(conn: sa.Connection) -> dict[str, str]:
    """session_id → 账号 ID；优先会话表，其次消息表的数字 user_id。"""
    mapping: dict[str, str] = {}
    rows = conn.execute(
        sa.text(
            "SELECT session_id, user_id FROM ai_conversation_sessions "
            "WHERE user_id IS NOT NULL"
        )
    ).mappings()
    for row in rows:
        session_id = str(row["session_id"] or "").strip()
        if session_id:
            mapping[session_id] = str(row["user_id"]).strip()
    rows = conn.execute(
        sa.text(
            "SELECT session_id, user_id FROM ai_conversations "
            "WHERE user_id IS NOT NULL"
        )
    ).mappings()
    for row in rows:
        session_id = str(row["session_id"] or "").strip()
        account_id = str(row["user_id"] or "").strip()
        if session_id and account_id.isdigit() and session_id not in mapping:
            mapping[session_id] = account_id
    return mapping


def _weighted(rows: list[dict[str, Any]], field: str) -> float:
    total = sum(max(int(row.get("interaction_count") or 0), 0) for row in rows)
    if total <= 0:
        return float(rows[0].get(field) or 0.0)
    return sum(
        float(row.get(field) or 0.0) * max(int(row.get("interaction_count") or 0), 0)
        for row in rows
    ) / total


def _merge_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(rows, key=lambda row: int(row.get("interaction_count") or 0), reverse=True)
    primary = rows[0]
    counts: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        try:
            raw = row.get("business_domain_counts") or "{}"
            parsed = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (TypeError, ValueError):
            parsed = {}
        for key, value in (parsed or {}).items():
            try:
                counts[str(key)] += int(value)
            except (TypeError, ValueError):
                continue
    return {
        "industry": primary.get("industry") or "通用",
        "identity_name": primary.get("identity_name") or "业务管家",
        "identity_brief": primary.get("identity_brief") or "",
        "business_domain": primary.get("business_domain") or "general",
        "rapport_score": _weighted(rows, "rapport_score"),
        "warmth": _weighted(rows, "warmth"),
        "detail": _weighted(rows, "detail"),
        "proactivity": _weighted(rows, "proactivity"),
        "structure": _weighted(rows, "structure"),
        "interaction_count": sum(int(row.get("interaction_count") or 0) for row in rows),
        "business_domain_counts": json.dumps(dict(counts), ensure_ascii=False),
        "emotion_signal_count": sum(int(row.get("emotion_signal_count") or 0) for row in rows),
        "created_at": min(str(row.get("created_at") or "") for row in rows) or None,
        "updated_at": max(str(row.get("updated_at") or "") for row in rows) or None,
    }


def _upsert_profile(conn: sa.Connection, account_id: str, values: dict[str, Any], exists: bool) -> None:
    if exists:
        conn.execute(
            sa.text(
                "UPDATE persona_profile SET industry=:industry, identity_name=:identity_name, "
                "identity_brief=:identity_brief, business_domain=:business_domain, "
                "rapport_score=:rapport_score, warmth=:warmth, detail=:detail, "
                "proactivity=:proactivity, structure=:structure, "
                "interaction_count=:interaction_count, "
                "business_domain_counts=:business_domain_counts, "
                "emotion_signal_count=:emotion_signal_count, "
                "created_at=:created_at, updated_at=:updated_at "
                "WHERE user_id=:account_id"
            ),
            {**values, "account_id": account_id},
        )
        return
    conn.execute(
        sa.text(
            "INSERT INTO persona_profile (user_id, industry, identity_name, identity_brief, "
            "business_domain, rapport_score, warmth, detail, proactivity, structure, "
            "interaction_count, business_domain_counts, emotion_signal_count, "
            "created_at, updated_at) VALUES (:account_id, :industry, :identity_name, "
            ":identity_brief, :business_domain, :rapport_score, :warmth, :detail, "
            ":proactivity, :structure, :interaction_count, :business_domain_counts, "
            ":emotion_signal_count, :created_at, :updated_at)"
        ),
        {**values, "account_id": account_id},
    )


def merge_session_personas(conn: sa.Connection) -> dict[str, int]:
    mapping = _session_account_map(conn)
    if not mapping:
        return {"accounts": 0, "merged": 0}
    profile_rows = {
        str(row["user_id"]): dict(row)
        for row in conn.execute(sa.text("SELECT * FROM persona_profile")).mappings()
    }
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    merged_keys: set[str] = set()
    for session_id, account_id in mapping.items():
        key = f"web_normal_{session_id}"
        row = profile_rows.get(key)
        if row is None:
            continue
        groups[account_id].append(row)
        merged_keys.add(key)
    if not groups:
        return {"accounts": 0, "merged": 0}

    conn.execute(sa.text("DELETE FROM persona_profile WHERE user_id IN :keys").bindparams(
        sa.bindparam("keys", expanding=True)
    ), {"keys": sorted(merged_keys)})
    conn.execute(sa.text("UPDATE persona_event_log SET user_id = :account_id WHERE user_id = :key"), [
        {"account_id": account_id, "key": f"web_normal_{session_id}"}
        for session_id, account_id in mapping.items()
        if f"web_normal_{session_id}" in merged_keys
    ])

    accounts = 0
    for account_id, rows in groups.items():
        existing = profile_rows.get(account_id)
        if existing is not None:
            rows = [existing, *rows]
        _upsert_profile(conn, account_id, _merge_group(rows), existing is not None)
        accounts += 1
    return {"accounts": accounts, "merged": len(merged_keys)}


def upgrade() -> None:
    merge_session_personas(op.get_bind())


def downgrade() -> None:
    # 数据合并不可逆：保留账号级画像，避免破坏已累计的学习结果。
    pass
