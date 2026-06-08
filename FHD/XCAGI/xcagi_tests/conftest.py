"""Pytest 入口：在 import app.* 之前固定测试用 SQLite，避免误用开发库。"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

# 仓库根目录（FHD）须在 sys.path 上，以便 import app.*
_XCAGI_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FHD_ROOT = os.path.dirname(_XCAGI_ROOT)
if _FHD_ROOT not in sys.path:
    sys.path.insert(0, _FHD_ROOT)

# ④-B：collect_ignore 已清空；原条目见 _XCAGI_LEGACY_SKIP_FRAGMENTS
collect_ignore: list[str] = []

_XCAGI_LEGACY_SKIP_FRAGMENTS = (
    "neuro_optimization",
    "test_product_neuro_persistence.py",
    "test_e2e_system_industry_flow.py",
    "test_integration_health_api.py",
    "test_templates_routes_and_helpers.py",
    "test_intent.py",
    "test_api_route_sweep.py",
    "test_application/",
    "test_domain/",
    "unit/fastapi_routes/shipment/test_shipment.py",
    "unit/fastapi_routes/test_control.py",
)


def pytest_collection_modifyitems(config, items):
    legacy_skip = pytest.mark.skip(reason="xcagi legacy：原 collect_ignore，见 tests/README.md")
    for item in items:
        nodeid = item.nodeid.replace("\\", "/")
        if any(frag in nodeid for frag in _XCAGI_LEGACY_SKIP_FRAGMENTS):
            item.add_marker(legacy_skip)

_fd, _TEST_DB = tempfile.mkstemp(suffix="_pytest_xcagi.db")
os.close(_fd)
_sqlite_url = "sqlite:///" + _TEST_DB.replace("\\", "/")
os.environ["DATABASE_URL"] = _sqlite_url
_test_db_flag = os.path.join(_XCAGI_ROOT, "test_db_enabled.flag")
if os.path.exists(_test_db_flag):
    try:
        os.remove(_test_db_flag)
    except OSError:
        pass
_PYTEST_PRODUCTS_TEST = f".pytest_products_test_{os.getpid()}.db"
os.environ["XCAGI_PRODUCTS_TEST_DB"] = _PYTEST_PRODUCTS_TEST
_PYTEST_PRODUCTS_TEST_ABS = os.path.join(_XCAGI_ROOT, _PYTEST_PRODUCTS_TEST)
os.environ.setdefault("XCAGI_SKIP_INTENT_LLM", "1")
os.environ.setdefault("SECRET_KEY", "pytest-xcagi-secret-key-not-for-production")
os.environ.setdefault("XCAGI_CLIENT_MODS_OFF", "0")


def pytest_sessionfinish(session, exitstatus):
    for path in (
        _TEST_DB,
        _TEST_DB + "-wal",
        _TEST_DB + "-shm",
        _PYTEST_PRODUCTS_TEST_ABS,
        f"{_PYTEST_PRODUCTS_TEST_ABS}-wal",
        f"{_PYTEST_PRODUCTS_TEST_ABS}-shm",
    ):
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture(scope="session")
def app():
    """FastAPI 应用（与 tests/fixtures/app_factory 一致）。"""
    from tests.fixtures.app_factory import get_test_fastapi_app, prime_test_env

    prime_test_env(sqlite_url=_sqlite_url)
    return get_test_fastapi_app()


@pytest.fixture(scope="function")
def client(app):
    from fastapi.testclient import TestClient

    yield TestClient(app, raise_server_exceptions=False)


class _SampleDataFactory:
    def material(self, overrides: dict | None = None) -> dict:
        base = {
            "name": "pytest-material",
            "quantity": 10.0,
            "specification": "规格A",
            "min_quantity": 0.0,
        }
        if overrides:
            base.update(overrides)
        return base


@pytest.fixture
def sample_data_factory():
    return _SampleDataFactory()


@pytest.fixture
def mock_dispatch():
    def _dispatch(*, tool_id: str, action: str, params: dict):
        return {"success": True, "data": []}

    return _dispatch


@pytest.fixture
def sample_plan_graph():
    from app.application.workflow.types import PlanGraph, WorkflowNode

    return PlanGraph(
        plan_id="sample-linear",
        intent="query",
        nodes=[
            WorkflowNode(
                node_id="n1",
                tool_id="products",
                action="query",
                params={"keyword": "a"},
            ),
            WorkflowNode(
                node_id="n2",
                tool_id="customers",
                action="query",
                params={},
                depends_on=["n1"],
            ),
        ],
    )


@pytest.fixture
def sample_tool_registry():
    return {
        "products": {"query": "ok"},
        "customers": {"query": "ok"},
    }
