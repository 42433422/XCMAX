from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from modstore_server import templates_api
from modstore_server.api import market_catalog_admin
from modstore_server.market_shared import _catalog_item_payload
from modstore_server.models import CatalogItem, Purchase, User, Workflow, WorkflowEdge, WorkflowNode
from modstore_server.models_base import Base

SNAPSHOT = {
    "nodes": [
        {"local_id": 10, "node_type": "start", "name": "开始", "config": {"token": "private"}},
        {"local_id": 20, "node_type": "end", "name": "结束", "config": {}},
    ],
    "edges": [{"source_local_id": 10, "target_local_id": 20, "condition": "private condition"}],
}


@pytest.fixture
def template_market(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(market_catalog_admin, "get_session_factory", lambda: sessionmaker(engine))
    Base.metadata.create_all(
        engine,
        tables=[
            model.__table__
            for model in (User, CatalogItem, Purchase, Workflow, WorkflowNode, WorkflowEdge)
        ],
    )
    with Session(engine) as db:
        users = [
            User(username=f"user-{i}", password_hash="test-only", is_admin=i == 4)
            for i in range(1, 5)
        ]
        db.add_all(users)
        db.commit()
        app = FastAPI()
        app.include_router(templates_api.router)
        app.include_router(market_catalog_admin.router, prefix="/api")

        def request_db():
            with Session(engine) as session:
                yield session

        app.dependency_overrides[templates_api.get_db] = request_db
        app.dependency_overrides[templates_api._get_current_user] = lambda: users[1]
        with TestClient(app) as client:
            yield client, db, app, users
    engine.dispose()


def add_template(db, **values):
    attrs = dict(
        pkg_id=f"template-{uuid4().hex}",
        version="1.0.0",
        name="测试模板",
        artifact="workflow_template",
        author_id=1,
        price=0,
        is_public=True,
        compliance_status="approved",
        template_category="客服",
        graph_snapshot=json.dumps(SNAPSHOT),
    )
    attrs.update(values)
    row = CatalogItem(**attrs)
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize(
    "status", ["under_review", "reviewing", "restricted", "delisted", "private"]
)
def test_discovery_detail_and_install_share_public_catalog_policy(template_market, status):
    client, db, _, _ = template_market
    approved = add_template(db)
    hidden = add_template(
        db,
        compliance_status="approved" if status == "private" else status,
        is_public=status != "private",
    )
    listing = client.get("/api/templates").json()
    assert listing["total"] == 1
    assert [item["id"] for item in listing["items"]] == [approved.id]
    categories = client.get("/api/templates/categories").json()["categories"]
    assert sum(category["count"] for category in categories) == 1
    assert client.get(f"/api/templates/{hidden.id}").status_code == 404
    assert client.post(f"/api/templates/{hidden.id}/install").status_code == 404
    assert db.query(Workflow).count() == 0
    assert hidden.install_count == 0


def test_public_preview_does_not_disclose_executable_configuration(template_market):
    client, db, _, _ = template_market
    row = add_template(db, price=12, template_difficulty="advanced", install_count=3)
    catalog = _catalog_item_payload(row)
    assert catalog["is_public"] is True
    assert (
        catalog["template_category"],
        catalog["template_difficulty"],
        catalog["install_count"],
    ) == ("客服", "advanced", 3)
    response = client.get(f"/api/templates/{row.id}")
    assert response.status_code == 200
    graph = response.json()["graph"]
    assert graph["node_count"] == 2 and graph["edge_count"] == 1
    assert graph["nodes"][0]["name"] == "开始"
    assert all("config" not in node for node in graph["nodes"])
    assert all("condition" not in edge for edge in graph["edges"])
    assert "private" not in response.text
    assert json.loads(row.graph_snapshot) == SNAPSHOT


def test_paid_install_requires_purchase_owned_by_current_user(template_market):
    client, db, _, users = template_market
    row = add_template(db, price=12)
    db.add(Purchase(user_id=users[2].id, catalog_id=row.id, amount=12))
    db.commit()
    assert client.post(f"/api/templates/{row.id}/install").status_code == 403
    assert db.query(Workflow).count() == 0
    assert row.install_count == 0
    db.add(Purchase(user_id=users[1].id, catalog_id=row.id, amount=12))
    db.commit()
    response = client.post(f"/api/templates/{row.id}/install")
    assert response.status_code == 200, response.text
    workflow = db.get(Workflow, response.json()["workflow_id"])
    assert workflow.user_id == users[1].id
    nodes = (
        db.query(WorkflowNode).filter_by(workflow_id=workflow.id).order_by(WorkflowNode.id).all()
    )
    assert json.loads(nodes[0].config) == SNAPSHOT["nodes"][0]["config"]
    edge = db.query(WorkflowEdge).filter_by(workflow_id=workflow.id).one()
    assert (edge.source_node_id, edge.target_node_id) == (nodes[0].id, nodes[1].id)
    assert edge.condition == SNAPSHOT["edges"][0]["condition"]
    db.refresh(row)
    assert row.install_count == 1
    assert json.loads(row.graph_snapshot) == SNAPSHOT


@pytest.mark.parametrize("actor,price", [(0, 12), (3, 12), (1, 0)])
def test_author_admin_and_free_template_access(template_market, actor, price):
    client, db, app, users = template_market
    app.dependency_overrides[templates_api._get_current_user] = lambda: users[actor]
    row = add_template(db, price=price)
    response = client.post(f"/api/templates/{row.id}/install")
    assert response.status_code == 200, response.text
    assert db.get(Workflow, response.json()["workflow_id"]).user_id == users[actor].id
    assert db.query(Purchase).count() == 0


@pytest.mark.parametrize("is_public", [False, True])
def test_save_template_requires_review_before_public_discovery(template_market, is_public):
    client, db, app, users = template_market
    workflow = Workflow(user_id=users[1].id, name="我的流程")
    db.add(workflow)
    db.flush()
    db.add(WorkflowNode(workflow_id=workflow.id, name="开始", node_type="start", config="{}"))
    db.commit()
    response = client.post(
        f"/api/templates/from-workflow/{workflow.id}",
        json={"name": "新模板", "is_public": is_public},
    )
    assert response.status_code == 200, response.text
    row = db.get(CatalogItem, response.json()["id"])
    assert row.author_id == users[1].id
    assert row.compliance_status == ("under_review" if is_public else "approved")
    assert response.json()["compliance_status"] == row.compliance_status
    assert _catalog_item_payload(row)["is_public"] is is_public
    assert client.get("/api/templates").json()["total"] == 0
    assert client.get(f"/api/templates/{row.id}").status_code == 404
    if is_public:
        review_url = f"/api/admin/catalog/{row.id}/review"
        assert client.post(review_url, json={"action": "approve"}).status_code == 403
        app.dependency_overrides[templates_api._get_current_user] = lambda: users[3]
        assert client.post(review_url, json={"action": "approve"}).status_code == 200
        assert client.get("/api/templates").json()["total"] == 1
        assert client.get(f"/api/templates/{row.id}").status_code == 200
