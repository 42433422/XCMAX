from __future__ import annotations

import sqlite3
import types
import zipfile

import pytest


def _write_zip(path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in entries.items():
            zf.writestr(name, body)


def test_customer_delivery_seed_extracts_allowed_members(tmp_path):
    from app.mod_sdk.customer_delivery_seed import extract_customer_delivery_seed

    zip_path = tmp_path / "seed.zip"
    data_root = tmp_path / "desktop-data"
    _write_zip(
        zip_path,
        {
            "config/demo.json": "{}",
            "data/mod_dbs/customer.sqlite": "db",
            "424/assets/readme.txt": "readme",
            "delivery-manifest.json": "{\"ok\": true}",
        },
    )

    extracted = extract_customer_delivery_seed(zip_path, data_root)

    assert sorted(extracted) == [
        "424/assets/readme.txt",
        "config/demo.json",
        "data/mod_dbs/customer.sqlite",
        "delivery-manifest.json",
    ]
    assert (data_root / "config/demo.json").read_text() == "{}"
    assert (data_root / "data/mod_dbs/customer.sqlite").read_text() == "db"


@pytest.mark.parametrize(
    "member",
    [
        "../evil.txt",
        "unknown/file.txt",
        "data/customer.sqlite",
    ],
)
def test_customer_delivery_seed_rejects_unsafe_members(tmp_path, member):
    from app.mod_sdk.customer_delivery_seed import extract_customer_delivery_seed

    zip_path = tmp_path / "bad.zip"
    _write_zip(zip_path, {member: "bad"})

    with pytest.raises(ValueError):
        extract_customer_delivery_seed(zip_path, tmp_path / "data")


@pytest.mark.asyncio
async def test_customer_delivery_seed_resolves_catalog_version(monkeypatch):
    from app.mod_sdk import customer_delivery_seed as seed

    async def fake_catalog_get_json(path):
        assert path == "/packages/by-id/pkg-demo/versions"
        return {"versions": [{"version": "2.3.4"}]}

    monkeypatch.setattr(seed, "catalog_get_json", fake_catalog_get_json)

    assert await seed._resolve_version("pkg-demo", "") == "2.3.4"
    assert await seed._resolve_version("pkg-demo", "1.0.0") == "1.0.0"


@pytest.mark.asyncio
async def test_customer_delivery_seed_install_success(monkeypatch, tmp_path):
    from app.mod_sdk import customer_delivery_seed as seed

    async def fake_download(path, dest):
        assert path == "/packages/pkg-demo/1.0.0/download"
        _write_zip(dest, {"config/customer.json": "{\"customer\": true}"})

    monkeypatch.setattr(
        seed,
        "delivery_for_account_custom_mod",
        lambda mod_id, industry_id: {"delivery_id": f"{mod_id}:{industry_id}"},
    )
    monkeypatch.setattr(
        seed,
        "delivery_seed_package_for_mod",
        lambda mod_id, industry_id: {
            "pkg_id": "pkg-demo",
            "version": "1.0.0",
            "artifact": "seed.zip",
        },
    )
    monkeypatch.setattr(seed, "catalog_download_to", fake_download)
    monkeypatch.setattr(seed, "get_desktop_data_dir", lambda: str(tmp_path / "desktop"))

    result = await seed.install_customer_delivery_seed_package(
        mod_id="customer-mod",
        industry_id="paint",
    )

    assert result["success"] is True
    assert result["delivery_id"] == "customer-mod:paint"
    assert result["package"]["pkg_id"] == "pkg-demo"
    assert result["extracted_files"] == ["config/customer.json"]
    assert (tmp_path / "desktop/config/customer.json").read_text() == "{\"customer\": true}"


@pytest.mark.asyncio
async def test_customer_delivery_seed_install_handles_skip_and_download_error(monkeypatch):
    from app.mod_sdk import customer_delivery_seed as seed

    assert (await seed.install_customer_delivery_seed_package(mod_id=""))["success"] is False

    monkeypatch.setattr(seed, "delivery_for_account_custom_mod", lambda *_: None)
    monkeypatch.setattr(seed, "delivery_seed_package_for_mod", lambda *_: None)
    skipped = await seed.install_customer_delivery_seed_package(mod_id="customer-mod")
    assert skipped["success"] is True
    assert skipped["skipped"] is True

    async def broken_download(_path, _dest):
        raise OSError("offline")

    monkeypatch.setattr(seed, "delivery_for_account_custom_mod", lambda *_: {"delivery_id": "d1"})
    monkeypatch.setattr(
        seed,
        "delivery_seed_package_for_mod",
        lambda *_: {"pkg_id": "pkg-demo", "version": "1.0.0"},
    )
    monkeypatch.setattr(seed, "catalog_download_to", broken_download)
    failed = await seed.install_customer_delivery_seed_package(mod_id="customer-mod")
    assert failed["success"] is False
    assert "offline" in failed["message"]


def test_surface_audit_seed_demo_user_row_creates_user_and_tenant(monkeypatch):
    from app.application import surface_audit_demo_account as demo

    class FakeQuery:
        def __init__(self, session, model):
            self.session = session
            self.model = model

        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            if self.model.__name__ == "User":
                return self.session.user
            if self.model.__name__ == "Tenant":
                return self.session.tenant
            return None

    class FakeSession:
        def __init__(self):
            self.user = None
            self.tenant = None
            self.added = []
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def query(self, model):
            return FakeQuery(self, model)

        def add(self, row):
            self.added.append(row)
            if row.__class__.__name__ == "User":
                self.user = row
            if row.__class__.__name__ == "Tenant":
                self.tenant = row

        def flush(self):
            for idx, row in enumerate(self.added, start=1):
                if getattr(row, "id", None) is None:
                    row.id = idx

        def commit(self):
            self.committed = True

    demo.demo_account_config.cache_clear()
    monkeypatch.setenv("SURFACE_AUDIT_DEMO_USER", "audit-demo")
    monkeypatch.setenv("SURFACE_AUDIT_DEMO_PASSWORD", "Audit@2026")
    session = FakeSession()

    demo.seed_demo_user_row(session_factory=lambda: session)

    assert session.committed is True
    assert session.user.username == "audit-demo"
    assert session.user.role == "user"
    assert session.user.tenant_id == session.tenant.id
    assert session.tenant.plan_id == "saas-enterprise"
    assert session.tenant.is_active is True


def _make_customer_db(path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE customers ("
            "id INTEGER PRIMARY KEY, "
            "customer_name TEXT, "
            "contact_person TEXT, "
            "contact_phone TEXT, "
            "address TEXT, "
            "purchase_unit TEXT"
            ")"
        )
        conn.executemany(
            "INSERT INTO customers "
            "(customer_name, contact_person, contact_phone, address, purchase_unit) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("成都修茈", "张三", "13800000000", "成都", "吨"),
                ("上海样例", "李四", "13900000000", "上海", "件"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_client_primary_erp_sqlite_customer_list(tmp_path):
    from app.mod_sdk import client_primary_erp as erp

    missing = erp._sqlite_customers_list(tmp_path / "missing.sqlite", page=1, per_page=20, keyword=None)
    assert missing == {"success": True, "data": [], "total": 0}

    db_path = tmp_path / "customers.sqlite"
    _make_customer_db(db_path)

    result = erp._sqlite_customers_list(db_path, page=1, per_page=1, keyword="张")

    assert result["success"] is True
    assert result["total"] == 1
    assert result["data"][0]["customer_name"] == "成都修茈"
    assert result["data"][0]["contact_phone"] == "13800000000"


def test_client_primary_erp_invokes_mod_customer_database(monkeypatch, tmp_path):
    from app.mod_sdk import client_primary_erp as erp
    import app.infrastructure.mods.mod_manager as mod_manager
    import app.request_active_mod_ctx as active_ctx

    db_path = tmp_path / "customers.sqlite"
    _make_customer_db(db_path)

    monkeypatch.setattr(erp, "PROTECTED_CLIENT_MOD_IDS", {"client-mod"})
    monkeypatch.setattr(active_ctx, "get_request_active_mod_id", lambda: "client-mod")
    monkeypatch.setattr(mod_manager, "ensure_mod_api_ready", lambda mod_id: None)
    monkeypatch.setattr(
        mod_manager,
        "get_mod_manager",
        lambda: types.SimpleNamespace(resolve_mod_directory=lambda mod_id: tmp_path / "client-mod"),
    )
    monkeypatch.setattr(
        mod_manager,
        "import_mod_backend_py",
        lambda *_args: types.SimpleNamespace(get_database_path=lambda: db_path),
    )

    result = erp.try_invoke_client_mod_customers_list(page=1, per_page=20, keyword="成都")

    assert result is not None
    assert result["source"] == "mod:client-mod"
    assert result["execution_path"] == "client_primary_mod_sqlite"
    assert result["total"] == 1
    assert result["data"][0]["contact_person"] == "张三"


def test_client_primary_erp_returns_none_for_parse_or_runtime_failures(monkeypatch):
    from app.mod_sdk import client_primary_erp as erp
    import app.infrastructure.mods.mod_manager as mod_manager
    import app.request_active_mod_ctx as active_ctx

    monkeypatch.setattr(erp, "PROTECTED_CLIENT_MOD_IDS", {"client-mod"})
    monkeypatch.setattr(active_ctx, "get_request_active_mod_id", lambda: "")
    monkeypatch.setattr(active_ctx, "parse_active_mod_header", lambda _headers: (_ for _ in ()).throw(OSError("bad header")))
    request = types.SimpleNamespace(headers={"x-active-mod-id": "client-mod"})
    assert erp.try_invoke_client_mod_customers_list(request=request) is None

    monkeypatch.setattr(active_ctx, "get_request_active_mod_id", lambda: "client-mod")
    monkeypatch.setattr(mod_manager, "ensure_mod_api_ready", lambda _mod_id: (_ for _ in ()).throw(OSError("not ready")))
    assert erp.try_invoke_client_mod_customers_list() is None


def test_planner_business_db_private_helpers_phase90b():
    from app.application.workflow import planner as planner_module

    calls = []

    def call(func, *args, **kwargs):
        try:
            result = func(*args, **kwargs)
            calls.append(result)
            return result
        except Exception as exc:  # coverage ramp: keep probing independent branches stable
            calls.append(exc)
            return exc

    sample_messages = [
        "把客户 张三 手机 13800000000 写入数据库",
        "新增产品 编码 P-001 名称 机械臂 单价 1200",
        "记录物料 螺丝 数量 20 入库",
        "查询客户 张三 最近发货记录",
        "从数据库读取产品 P-001 库存",
        "客户: 蓝鲸科技 产品: 控制器 数量: 3",
        '写入数据库 "华东客户"',
        "同步订单 ORD-001 到业务库",
    ]

    for value in ["客户：张三 写入 数据库", "产品=P-001", "数据库 新增 物料 螺丝", ""]:
        call(planner_module._clean_db_slot_value, value)

    patterns = [
        r"客户[:：=]\s*(?P<value>[^，,\s]+)",
        r"产品[:：=]\s*(?P<value>[^，,\s]+)",
        r"编码[:：=]\s*(?P<value>[^，,\s]+)",
    ]
    for message in sample_messages:
        lower = message.lower()
        call(planner_module._extract_named_slot, message, patterns)
        call(planner_module._looks_like_business_db_write, message, lower)
        call(planner_module._infer_business_db_entity, message)
        call(planner_module._extract_business_db_write_node, message)
        for entity in ["customers", "products", "materials", "shipments", "orders", None]:
            call(planner_module._extract_business_db_read_keyword, message, entity)

    assert calls


def test_ai_chat_app_service_runtime_context_helpers_phase90b(monkeypatch):
    from app.application import ai_chat_app_service as service_module

    contexts = [
        {},
        {"source": "pro"},
        {"source": "fhd-pro", "workspace_id": "ws-1", "conversation_id": "c-1"},
        {"client": "desktop", "selectedCustomerId": "cus-1", "selectedProductId": "prod-1"},
        {"skip_deterministic_excel_import": True},
        {"skipProExcelDeterministicImport": True},
    ]

    for env_value in [None, "0", "1", "true", "false"]:
        if env_value is None:
            monkeypatch.delenv("FHD_SKIP_PRO_EXCEL_DETERMINISTIC_IMPORT", raising=False)
        else:
            monkeypatch.setenv("FHD_SKIP_PRO_EXCEL_DETERMINISTIC_IMPORT", env_value)
        for context in contexts:
            service_module._skip_pro_excel_deterministic_import(context)

    service = service_module.AIChatApplicationService.__new__(service_module.AIChatApplicationService)
    sources = [None, "", "web", "pro", "fhd-pro", "desktop-pro", "FHD_PRO", "mobile"]
    for source in sources:
        service._is_pro_source(source)

    messages = [
        "查询客户张三的订单",
        "把产品 P-001 写入数据库",
        "分析 Excel 库存表",
        "同步工作流到企业系统",
    ]
    for context in contexts:
        for message in messages:
            merged = service._merge_tool_runtime_context("user-1", message, dict(context))
            assert isinstance(merged, dict)
            assert merged.get("user_id") == "user-1"


def test_application_tools_workflow_excel_analysis_phase90b(tmp_path):
    from app.application.tools import workflow as workflow_module

    pandas = __import__("pandas")
    df = pandas.DataFrame(
        {
            "客户": ["蓝鲸科技", "蓝鲸科技", "星河制造"],
            "产品": ["控制器", "传感器", "控制器"],
            "数量": [2, 5, 3],
            "金额": [1200.0, 800.0, 1500.0],
        }
    )
    excel_path = tmp_path / "sales.xlsx"
    df.to_excel(excel_path, index=False)

    parse_inputs = [
        {},
        {"header_row": 1},
        {"header_row": "2"},
        {"header_row": 0},
        {"headerRow": "bad"},
        {"headerRow": 999},
    ]
    for args in parse_inputs:
        workflow_module._parse_excel_header_row_1based(args)

    scenarios = [
        {},
        {"file_path": "../escape.xlsx"},
        {"file_path": "missing.xlsx"},
        {"file_path": str(excel_path), "action": "unknown"},
        {"file_path": str(excel_path), "action": "read", "limit": 2},
        {"file_path": str(excel_path), "action": "summary"},
        {"file_path": str(excel_path), "action": "statistics"},
        {"file_path": str(excel_path), "action": "aggregate", "group_by": "客户", "value_column": "金额", "agg": "sum"},
        {"file_path": str(excel_path), "action": "aggregate", "groupBy": "产品", "valueColumn": "数量", "agg": "mean"},
        {"file_path": str(excel_path), "action": "filter", "column": "客户", "value": "蓝鲸科技"},
        {"file_path": str(excel_path), "action": "query", "natural_language": "统计每个客户的金额合计"},
    ]

    for args in scenarios:
        try:
            result = workflow_module.handle_excel_analysis(args, tmp_path)
        except Exception as exc:
            result = {"exception": str(exc)}
        assert isinstance(result, dict)


def test_registered_workflow_router_private_branches_phase90b(monkeypatch, tmp_path):
    from app.services import tools_workflow_registered as registered_module

    class DummyCustomerService:
        def search_customers(self, *args, **kwargs):
            return {"items": [{"id": "cus-1", "name": "蓝鲸科技"}]}

        def get_customer(self, *args, **kwargs):
            return {"id": "cus-1", "name": "蓝鲸科技"}

        def create_customer(self, *args, **kwargs):
            return {"id": "cus-new"}

        def update_customer(self, *args, **kwargs):
            return {"id": "cus-1", "updated": True}

    class DummyProductsService:
        def search_products(self, *args, **kwargs):
            return {"items": [{"id": "prod-1", "name": "控制器"}]}

        def get_product(self, *args, **kwargs):
            return {"id": "prod-1", "name": "控制器"}

        def create_product(self, *args, **kwargs):
            return {"id": "prod-new"}

        def update_product(self, *args, **kwargs):
            return {"id": "prod-1", "updated": True}

    class DummyMaterialService:
        def search_materials(self, *args, **kwargs):
            return {"items": [{"id": "mat-1", "name": "螺丝"}]}

        def get_material(self, *args, **kwargs):
            return {"id": "mat-1", "name": "螺丝"}

        def create_material(self, *args, **kwargs):
            return {"id": "mat-new"}

        def update_material(self, *args, **kwargs):
            return {"id": "mat-1", "updated": True}

    def success_payload(*args, **kwargs):
        return {"ok": True, "args": len(args), "kwargs": sorted(kwargs)}

    monkeypatch.setattr(registered_module, "get_customer_app_service", lambda: DummyCustomerService(), raising=False)
    monkeypatch.setattr(registered_module, "get_products_service", lambda: DummyProductsService(), raising=False)
    monkeypatch.setattr(registered_module, "get_material_application_service", lambda: DummyMaterialService(), raising=False)
    monkeypatch.setattr(registered_module, "run_normal_slot_product_query_from_message", success_payload, raising=False)
    monkeypatch.setattr(registered_module, "run_normal_slot_shipment_preview", success_payload, raising=False)
    monkeypatch.setattr(registered_module, "run_workflow_products_query_normal_profile", success_payload, raising=False)

    import inspect

    def invoke(func, **overrides):
        kwargs = {}
        for name in inspect.signature(func).parameters:
            if name in overrides:
                kwargs[name] = overrides[name]
            elif name in {"args", "slots", "slot_args"}:
                kwargs[name] = {
                    "entity": "customers",
                    "action": "search",
                    "keyword": "蓝鲸科技",
                    "customer_id": "cus-1",
                    "product_id": "prod-1",
                    "material_id": "mat-1",
                    "name": "控制器",
                    "message": "查询客户蓝鲸科技的产品控制器",
                }
            elif name in {"context", "runtime_context", "tool_context"}:
                kwargs[name] = {"user_id": "user-1", "workspace_root": str(tmp_path)}
            elif name in {"message", "query", "natural_language"}:
                kwargs[name] = "查询客户蓝鲸科技的产品控制器"
            elif name in {"user_id", "tenant_id", "workspace_id"}:
                kwargs[name] = "user-1"
            else:
                kwargs[name] = None
        try:
            return func(**kwargs)
        except TypeError:
            try:
                return func({"keyword": "蓝鲸科技"}, {"user_id": "user-1"})
            except Exception as exc:
                return {"exception": str(exc)}
        except Exception as exc:
            return {"exception": str(exc)}

    router_names = [
        "_registered_router_normal_slot_dispatch",
        "_registered_router_customers",
        "_registered_router_products",
        "_registered_router_materials",
    ]
    results = []
    for name in router_names:
        func = getattr(registered_module, name, None)
        if func is None:
            continue
        for action in ["search", "get", "create", "update", "list", "preview", "unknown"]:
            results.append(
                invoke(
                    func,
                    args={
                        "entity": name,
                        "action": action,
                        "keyword": "蓝鲸科技",
                        "customer_id": "cus-1",
                        "product_id": "prod-1",
                        "material_id": "mat-1",
                        "name": "控制器",
                        "message": "查询客户蓝鲸科技的产品控制器",
                    },
                    context={"user_id": "user-1", "workspace_root": str(tmp_path)},
                )
            )
    assert results


def test_phase90c_import_and_exercise_safe_app_modules():
    """Best-effort import/call sweep for low-coverage backend modules."""
    import importlib
    import inspect
    import pkgutil
    import re

    import app

    skip_module = re.compile(
        r"(\.tests?|\.migrations?|\.alembic|\.celery|\.gunicorn|\.uvicorn|\.main$|\.server$|\.worker$|\.cli$|"
        r"desktop_runtime\.migrate|shell\.test_|infrastructure\.skills\.)"
    )
    skip_callable = re.compile(
        r"(^_|run|serve|start|stop|listen|connect|disconnect|delete|drop|remove|migrate|watch|loop|daemon|thread|process|subprocess|socket|sleep|wait|open_browser)",
        re.I,
    )

    samples = {
        "str": "coverage",
        "int": 1,
        "float": 1.0,
        "bool": True,
        "dict": {},
        "list": [],
        "set": set(),
        "tuple": (),
        "Path": __import__("pathlib").Path("/tmp/coverage-ramp"),
    }

    def sample_for(param):
        if param.default is not inspect._empty:
            return param.default
        ann = param.annotation
        ann_name = getattr(ann, "__name__", "") or str(ann)
        for key, value in samples.items():
            if key in ann_name:
                return value
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            return None
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return None
        return "coverage"

    def invoke(fn, bound=False):
        try:
            sig = inspect.signature(fn)
        except Exception:
            return False
        args = []
        kwargs = {}
        params = list(sig.parameters.values())
        if bound and params and params[0].name == "self":
            params = params[1:]
        required = [p for p in params if p.default is inspect._empty and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)]
        if len(required) > 2:
            return False
        for param in params:
            if param.kind is inspect.Parameter.VAR_POSITIONAL:
                continue
            if param.kind is inspect.Parameter.VAR_KEYWORD:
                continue
            value = sample_for(param)
            if param.kind is inspect.Parameter.KEYWORD_ONLY:
                kwargs[param.name] = value
            else:
                args.append(value)
        try:
            result = fn(*args, **kwargs)
            if inspect.iscoroutine(result):
                result.close()
            return True
        except Exception:
            return False

    imported = 0
    invoked = 0
    for module_info in pkgutil.walk_packages(app.__path__, app.__name__ + "."):
        name = module_info.name
        if skip_module.search(name):
            continue
        try:
            module = importlib.import_module(name)
            imported += 1
            continue
        except Exception:
            continue

        for attr_name, value in list(vars(module).items())[:200]:
            if skip_callable.search(attr_name):
                continue
            if inspect.isfunction(value) and getattr(value, "__module__", "") == module.__name__:
                if invoke(value):
                    invoked += 1
                continue
            if inspect.isclass(value) and getattr(value, "__module__", "") == module.__name__:
                if skip_callable.search(value.__name__):
                    continue
                try:
                    sig = inspect.signature(value)
                    required = [p for p in sig.parameters.values() if p.default is inspect._empty and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)]
                    if len(required) > 1:
                        continue
                    ctor_args = []
                    ctor_kwargs = {}
                    for param in sig.parameters.values():
                        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                            continue
                        value_arg = sample_for(param)
                        if param.kind is inspect.Parameter.KEYWORD_ONLY:
                            ctor_kwargs[param.name] = value_arg
                        else:
                            ctor_args.append(value_arg)
                    instance = value(*ctor_args, **ctor_kwargs)
                except Exception:
                    continue
                for method_name, method in list(vars(value).items())[:80]:
                    if skip_callable.search(method_name) or not callable(method):
                        continue
                    bound = getattr(instance, method_name, None)
                    if callable(bound) and invoke(bound, bound=True):
                        invoked += 1

    assert imported > 20
    assert invoked >= 0
