"""work_orders — 派工工单表（调度域 SSOT）

Revision ID: 2026_06_24_work_orders
Revises: 2026_06_22_baseline
Create Date: 2026-06-24

小C(assistant) 派工的规范化工单表。沿用 baseline 的"ORM 即 schema 真相源"哲学：
不手写列 DDL（避免与 ORM 漂移导致 alembic check 报差异），而是直接由
``WorkOrder.__table__`` 实现建表，dialect 无关、幂等（checkfirst=True）。

空库的 ``alembic upgrade head`` 会先经 baseline 的 ``create_all`` 建出本表，
本迁移再 checkfirst 跳过；存量已 stamp 至 baseline 的库则由本迁移补建。
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "2026_06_24_work_orders"
down_revision: str | Sequence[str] | None = "2026_06_22_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    import app.db.models  # noqa: F401  (populates Base.metadata)
    from app.db.models.work_order import WorkOrder

    WorkOrder.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    from app.db.models.work_order import WorkOrder

    WorkOrder.__table__.drop(bind=op.get_bind(), checkfirst=True)
