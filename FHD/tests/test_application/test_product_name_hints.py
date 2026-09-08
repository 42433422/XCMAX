"""Real scoped SQL product disambiguation through authenticated AI HTTP calls."""

from contextlib import contextmanager

from sqlalchemy import text

from app.application import product_name_hints
from app.application.aiopen.service import AIOPEN_STATE, _tool_api_call
from app.fastapi_routes import xcagi_compat_product
from app.request_active_mod_ctx import get_request_active_mod_id
from tests.test_application.test_aiopen_api_execution import application as application
from tests.test_application.test_aiopen_api_execution import caller
from tests.test_application.test_aiopen_api_execution import host as host


def test_name_resolution_distinguishes_exact_ambiguous_partial_and_scoped_rows(
    application, monkeypatch
):
    app, factories = application
    for scope, factory in factories.items():
        with factory.begin() as db:
            db.execute(
                text(
                    "CREATE TABLE products (id INTEGER, tenant_id INTEGER, name TEXT, model_number TEXT, specification TEXT, is_active INTEGER)"
                )
            )
            for pid, tenant, name, model, active in [
                (1, 7, "清漆", "A1", 1),
                (2, 7, "清漆", "A2", 1),
                (3, 8, "秘密产品", "PRIVATE", 1),
                (4, 7, "停用产品", "OLD", 0),
                (5, 7, "50%_涂料", "C5", 1),
            ]:
                db.execute(
                    text("INSERT INTO products VALUES (:id,:tenant,:name,:model,:scope,:active)"),
                    {
                        "id": pid,
                        "tenant": tenant,
                        "name": name,
                        "model": model,
                        "scope": scope,
                        "active": active,
                    },
                )
            for pid in range(10, 35):
                db.execute(
                    text("INSERT INTO products VALUES (:id,7,'重名','DUP','',1)"), {"id": pid}
                )

    @contextmanager
    def database():
        with factories[get_request_active_mod_id() or "host-business"]() as db:
            yield db

    monkeypatch.setattr(product_name_hints, "get_db", database)
    monkeypatch.setattr(xcagi_compat_product, "_business_mod_json_block", lambda: None)
    monkeypatch.setitem(AIOPEN_STATE["whitelist"], "/api/products", True)
    app.include_router(xcagi_compat_product.router, prefix="/api")
    path = "/api/products/resolve-name-hints"
    with caller({"X-Session-ID": "login-3"}):
        for scope in ("", "mod-a"):
            result = _tool_api_call(
                app,
                {
                    "path": path,
                    "method": "POST",
                    "mod_id": scope,
                    "body": {"hints": ["A2", "清漆", "涂料", "50%_", "PRIVATE", "OLD", "重名"]},
                },
            )
            assert result["success"], result
            rows = result["data"]["data"]
            assert rows[0]["status"] == "resolved" and rows[0]["product_id"] == 2
            assert rows[0]["candidates"][0]["specification"] == (scope or "host-business")
            assert rows[1]["status"] == "ambiguous" and rows[1]["product_id"] is None
            assert rows[2]["requires_confirmation"] and rows[2]["match_type"] == "partial"
            assert [c["id"] for c in rows[3]["candidates"]] == [5]
            assert rows[4]["status"] == rows[5]["status"] == "not_found"
            assert (
                rows[6]["truncated"]
                and rows[6]["total"] is None
                and len(rows[6]["candidates"]) == 20
            )
        denied = _tool_api_call(
            app, {"path": path, "method": "POST", "mod_id": "mod-b", "body": {"hints": ["A2"]}}
        )
        assert not denied["success"]
        for hints in ([1], ["x" * 201], ["a"] * 101):
            assert not _tool_api_call(
                app, {"path": path, "method": "POST", "body": {"hints": hints}}
            )["success"]
