"""Customer list acceptance: bounded rows, tenant isolation and constant SQL cost.

This uses a real SQLite database, not mocked HTTP 200 responses or a fake ORM.
It is a local regression, not a production latency/SLO measurement.
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.application.customer_app_service import CustomerApplicationService
from app.db.models.purchase_unit import PurchaseUnit
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def customer_list_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'customer-list.sqlite'}")
    PurchaseUnit.__table__.create(engine)
    with Session(engine) as session:
        session.add_all(
            PurchaseUnit(tenant_id=11, unit_name=f"Customer-{n:04d}", is_active=True)
            for n in range(200)
        )
        session.add_all(
            PurchaseUnit(tenant_id=22, unit_name=f"Other-{n:04d}", is_active=True)
            for n in range(7)
        )
        session.commit()
    try:
        yield engine
    finally:
        engine.dispose()


def test_customer_pages_are_bounded_stable_and_tenant_scoped(customer_list_engine, monkeypatch):
    service = CustomerApplicationService()
    monkeypatch.setattr(service, "_get_session", lambda: Session(customer_list_engine))
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(customer_list_engine, "before_cursor_execute", capture)
    try:
        with tenant_scope(11):
            first = service.get_all(page=1, per_page=50)
            second = service.get_all(page=2, per_page=50)
            final = service.get_all(page=4, per_page=50)
        # Count and one bounded page query per call: never one query per customer.
        assert len(statements) <= 6, statements
        assert all(item["success"] is True for item in (first, second, final))
        assert all(item["total"] == 200 for item in (first, second, final))
        assert [len(item["data"]) for item in (first, second, final)] == [50, 50, 50]
        ids = [record["id"] for item in (first, second, final) for record in item["data"]]
        assert len(ids) == len(set(ids))
        assert [row["customer_name"] for row in first["data"]] == [
            f"Customer-{n:04d}" for n in range(50)
        ]
        statements.clear()
        with tenant_scope(22):
            other = service.get_all(page=1, per_page=20)
        assert other["success"] is True and other["total"] == 7
        assert len(other["data"]) == 7
        assert all(row["customer_name"].startswith("Other-") for row in other["data"])
        assert len(statements) <= 2, statements
    finally:
        event.remove(customer_list_engine, "before_cursor_execute", capture)


@pytest.mark.parametrize(
    ("page", "per_page"),
    [
        (0, 20),
        (-1, 20),
        (True, 20),
        ("1", 20),
        (1, 0),
        (1, -1),
        (1, 101),
        (1, 100000),
        (1, False),
        (1, 1.5),
    ],
)
def test_invalid_pagination_fails_before_query(monkeypatch, page, per_page):
    service = CustomerApplicationService()

    def forbidden_session():
        pytest.fail("invalid page parameters must not touch a database")

    monkeypatch.setattr(service, "_get_session", forbidden_session)
    result = service.get_all(page=page, per_page=per_page)
    assert result["success"] is False
    assert result["error_code"] == "invalid_pagination"
    assert result["data"] == []
