"""打单模版解析：生产级行为单测。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.shipment_template_resolve import (
    _private_layout_rows,
    clear_template_list_cache,
    resolve_products_for_unit,
    resolve_shipment_template,
    shipment_template_strict_enabled,
)
from app.db.models.etl import EtlTemplate, EtlTemplateVersion
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_template_list_cache()
    yield
    clear_template_list_cache()


def test_resolve_by_template_id(tmp_path: Path):
    tpl = tmp_path / "发货单模板.xlsx"
    tpl.write_bytes(b"xlsx")
    store = MagicMock()
    store.resolve_template_file.return_value = str(tpl)
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template(template_id="db:12")
    assert out["ok"] is True
    assert out["path"] == str(tpl)
    assert out["source"] == "template_id"
    store.resolve_template_file.assert_called_once_with("db:12")


def test_resolve_intent_default_prefers_shipment_type(tmp_path: Path):
    good = tmp_path / "客户发货单.xlsx"
    good.write_bytes(b"xlsx")
    other = tmp_path / "杂项.xlsx"
    other.write_bytes(b"xlsx")
    store = MagicMock()
    store.resolve_template_file.return_value = None
    store.list_templates.return_value = [
        {
            "id": "db:1",
            "name": "杂项",
            "path": str(other),
            "template_type": "Excel",
            "source": "db",
            "db_id": 1,
            "is_active": 1,
        },
        {
            "id": "db:9",
            "name": "客户发货单",
            "path": str(good),
            "template_type": "发货单",
            "source": "db",
            "db_id": 9,
            "is_active": 1,
        },
    ]
    store.get_default_for_type.return_value = None
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template(intent="shipment_generate")
    assert out["ok"] is True
    assert out["path"] == str(good)
    assert out["reason"].startswith("intent_default")


def test_resolve_unit_name_match_wins(tmp_path: Path):
    unit_tpl = tmp_path / "星光贸易发货单.xlsx"
    unit_tpl.write_bytes(b"xlsx")
    generic = tmp_path / "通用发货单.xlsx"
    generic.write_bytes(b"xlsx")
    store = MagicMock()
    store.resolve_template_file.return_value = None
    store.list_templates.return_value = [
        {
            "id": "db:1",
            "name": "通用发货单",
            "path": str(generic),
            "template_type": "发货单",
            "source": "db",
            "db_id": 99,
            "is_active": 1,
        },
        {
            "id": "db:2",
            "name": "星光贸易发货单",
            "path": str(unit_tpl),
            "template_type": "发货单",
            "source": "db",
            "db_id": 2,
            "is_active": 1,
        },
    ]
    store.get_default_for_type.return_value = None
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template(unit_name="星光贸易有限公司")
    assert out["ok"] is True
    assert out["path"] == str(unit_tpl)
    assert str(out["reason"]).startswith("unit_match")


def test_resolve_customer_named_etl_layout_from_short_customer_alias(tmp_path: Path):
    customer_tpl = tmp_path / "金汉武家私-发货单版式.xlsx"
    customer_tpl.write_bytes(b"xlsx")
    store = MagicMock()
    store.resolve_template_file.return_value = None
    store.list_templates.return_value = []
    store.get_default_for_type.return_value = None
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ), patch(
        "app.application.shipment_template_resolve._private_layout_rows",
        return_value=[
            {
                "id": "etl:42",
                "name": "金汉武家私-发货单版式",
                "path": str(customer_tpl),
                "template_type": "发货单",
                "source": "etl_private",
                "is_active": 1,
            }
        ],
    ):
        out = resolve_shipment_template(unit_name="金汉武", owner_user_id=9)
    assert out["ok"] is True
    assert out["path"] == str(customer_tpl)
    assert out["template_name"] == "金汉武家私-发货单版式"
    assert str(out["reason"]).startswith("unit_match")


def test_private_etl_template_id_requires_the_current_owner(tmp_path: Path):
    customer_tpl = tmp_path / "金汉武家私-发货单版式.xlsx"
    customer_tpl.write_bytes(b"xlsx")
    store = MagicMock()
    store.resolve_template_file.return_value = None
    store.list_templates.return_value = []
    row = {
        "id": "etl:private-42",
        "name": "金汉武家私-发货单版式",
        "path": str(customer_tpl),
        "template_type": "发货单",
        "source": "etl_private",
        "is_active": 1,
    }

    def private_rows(owner_user_id):
        return [row] if owner_user_id == 9 else []

    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ), patch(
        "app.application.shipment_template_resolve._private_layout_rows",
        side_effect=private_rows,
    ):
        allowed = resolve_shipment_template(template_id="etl:private-42", owner_user_id=9)
        denied = resolve_shipment_template(template_id="etl:private-42", owner_user_id=10)

    assert allowed["ok"] is True
    assert allowed["path"] == str(customer_tpl)
    assert denied["ok"] is False
    assert denied["error_code"] == "ETL_PRIVATE_TEMPLATE_NOT_FOUND"


def test_private_layout_path_cannot_be_selected_by_another_owner(tmp_path: Path):
    root = tmp_path / "runtime"
    foreign = root / "tenants" / "7" / "document_templates" / "9" / "private.xlsx"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"xlsx")
    store = MagicMock()
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ), patch(
        "app.utils.path_utils.get_app_data_dir",
        return_value=str(root),
    ), patch(
        "app.infrastructure.tenant_scope.current_tenant_id",
        return_value=7,
    ):
        out = resolve_shipment_template(template_name=str(foreign), owner_user_id=10)

    assert out["ok"] is False
    assert out["error_code"] == "ETL_PRIVATE_TEMPLATE_FORBIDDEN"


def test_template_list_is_not_cross_request_cached(tmp_path: Path):
    first = tmp_path / "第一份发货单.xlsx"
    second = tmp_path / "第二份发货单.xlsx"
    first.write_bytes(b"xlsx")
    second.write_bytes(b"xlsx")
    store = MagicMock()
    store.resolve_template_file.return_value = None
    store.get_default_for_type.return_value = None
    store.list_templates.side_effect = [
        [{"id": "db:1", "name": "第一份发货单", "path": str(first), "template_type": "发货单"}],
        [{"id": "db:2", "name": "第二份发货单", "path": str(second), "template_type": "发货单"}],
    ]
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        first_out = resolve_shipment_template(template_name="第一份发货单")
        second_out = resolve_shipment_template(template_name="第二份发货单")

    assert first_out["ok"] is True
    assert second_out["ok"] is True
    assert store.list_templates.call_count == 2


def test_private_layout_query_filters_tenant_and_owner_in_database(tmp_path: Path):
    runtime = tmp_path / "runtime"
    own_path = runtime / "tenants" / "7" / "document_templates" / "9" / "own.xlsx"
    other_owner_path = runtime / "tenants" / "7" / "document_templates" / "10" / "other.xlsx"
    other_tenant_path = runtime / "tenants" / "8" / "document_templates" / "9" / "other-tenant.xlsx"
    for path in (own_path, other_owner_path, other_tenant_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"xlsx")

    engine = create_engine("sqlite://")
    EtlTemplate.__table__.create(engine)
    EtlTemplateVersion.__table__.create(engine)
    with Session(engine) as db:
        for template_id, tenant_id, owner_user_id, path in (
            ("own", 7, 9, own_path),
            ("other-owner", 7, 10, other_owner_path),
            ("other-tenant", 8, 9, other_tenant_path),
        ):
            db.add(
                EtlTemplate(
                    id=template_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    name=f"{template_id}-发货单版式",
                    target_type="shipment_records",
                    current_version=1,
                    is_active=True,
                    description="ETL_SHIPMENT_DOCUMENT_TEMPLATE",
                )
            )
            db.add(
                EtlTemplateVersion(
                    id=f"{template_id}-v1",
                    template_id=template_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    version=1,
                    target_type="shipment_records",
                    source_features_json=(
                        '{"shipment_document_template":{"file_path":"' + str(path) + '"}}'
                    ),
                )
            )
        db.commit()

    class _Context:
        def __enter__(self):
            self.session = Session(engine)
            return self.session

        def __exit__(self, *_args):
            self.session.close()

    with patch("app.db.session.get_db", return_value=_Context()), patch(
        "app.utils.path_utils.get_app_data_dir", return_value=str(runtime)
    ), tenant_scope(7):
        rows = _private_layout_rows(9)

    assert [row["id"] for row in rows] == ["etl:own"]
    assert rows[0]["path"] == str(own_path)


def test_resolve_preferred_by_name(tmp_path: Path):
    tpl = tmp_path / "我的默认.xlsx"
    tpl.write_bytes(b"xlsx")
    store = MagicMock()
    store.resolve_template_file.return_value = None
    store.list_templates.return_value = [
        {
            "id": "db:7",
            "name": "我的默认",
            "path": str(tpl),
            "template_type": "发货单",
            "is_active": 1,
        }
    ]
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template(preferred="我的默认")
    assert out["ok"] is True
    assert out["source"] == "user_preference"


def test_resolve_skips_inactive_and_non_layout(tmp_path: Path):
    dead = tmp_path / "旧版.xlsx"
    dead.write_bytes(b"xlsx")
    pdf = tmp_path / "说明书.pdf"
    pdf.write_bytes(b"%PDF")
    store = MagicMock()
    store.resolve_template_file.return_value = None
    store.list_templates.return_value = [
        {
            "id": "db:1",
            "name": "旧版发货单",
            "path": str(dead),
            "template_type": "发货单",
            "is_active": 0,
            "db_id": 1,
        },
        {
            "id": "db:2",
            "name": "说明书",
            "path": str(pdf),
            "template_type": "发货单",
            "is_active": 1,
            "db_id": 2,
        },
    ]
    store.get_default_for_type.return_value = None
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template()
    assert out["ok"] is False
    assert out["error_code"] == "TEMPLATE_NOT_FOUND"


def test_resolve_explicit_path(tmp_path: Path):
    tpl = tmp_path / "自定义.xlsx"
    tpl.write_bytes(b"xlsx")
    store = MagicMock()
    with patch(
        "app.application.shipment_template_resolve._get_template_store",
        return_value=store,
    ):
        out = resolve_shipment_template(template_name=str(tpl))
    assert out["ok"] is True
    assert out["source"] == "explicit_path"
    store.resolve_template_file.assert_not_called()


def test_resolve_products_for_unit_from_orders():
    svc = MagicMock(spec=["get_orders"])
    svc.get_orders.return_value = [
        {"customer_name": "星光贸易", "products": [{"name": "A", "qty": 1}]},
    ]
    with patch("app.bootstrap.get_shipment_app_service", return_value=svc):
        rows = resolve_products_for_unit("星光贸易")
    assert rows == [{"name": "A", "qty": 1}]


def test_strict_env_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XCAGI_SHIPMENT_TEMPLATE_STRICT", raising=False)
    assert shipment_template_strict_enabled() is False
    monkeypatch.setenv("XCAGI_SHIPMENT_TEMPLATE_STRICT", "1")
    assert shipment_template_strict_enabled() is True
    assert shipment_template_strict_enabled(False) is False
