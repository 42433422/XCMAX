"""SQLite INTEGER PK 行为回归（①-C 移除 sqlite_autoincrement 后）。"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.customer import Customer


def test_sqlite_autoincrement_removed_from_customer_model() -> None:
    args = getattr(Customer, "__table_args__", None)
    if isinstance(args, dict):
        assert "sqlite_autoincrement" not in args
    elif isinstance(args, tuple):
        for item in args:
            if isinstance(item, dict):
                assert "sqlite_autoincrement" not in item


def test_sqlite_pk_reused_after_deleting_highest_row() -> None:
    # 移除 sqlite_autoincrement 后的既定行为：删除最高（此处为唯一）行再插入会复用 rowid。
    # 这正是 ①-C 想固化的回归点——无 AUTOINCREMENT 时 SQLite 不维护单调序列。
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Customer.__table__])
    with Session(engine) as session:
        session.add(Customer(customer_name="A"))
        session.commit()
        first_id = session.execute(text("SELECT id FROM customers LIMIT 1")).scalar_one()
        session.execute(text("DELETE FROM customers WHERE id = :id"), {"id": first_id})
        session.commit()
        session.add(Customer(customer_name="B"))
        session.commit()
        second_id = session.execute(
            text("SELECT id FROM customers ORDER BY id DESC LIMIT 1")
        ).scalar_one()
    assert second_id == first_id
