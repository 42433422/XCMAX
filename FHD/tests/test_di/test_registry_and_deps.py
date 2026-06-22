"""app/di/registry 与 fastapi_deps 单测（Phase 4 长尾）。"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.di.fastapi_deps import get_service_container
from app.di.registry import (
    ServiceContainer,
    get_service_registry,
    reset_service_registry,
    set_service_registry,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    reset_service_registry()
    yield
    reset_service_registry()


class TestServiceRegistry:
    def test_get_creates_singleton(self):
        a = get_service_registry()
        b = get_service_registry()
        assert a is b
        assert isinstance(a, ServiceContainer)

    def test_set_replaces_registry(self):
        custom = ServiceContainer()
        set_service_registry(custom)
        assert get_service_registry() is custom

    def test_reset_drops_then_rebuilds(self):
        first = get_service_registry()
        reset_service_registry()
        second = get_service_registry()
        assert first is not second

    def test_invalidate_shipment_wiring_clears_lazy_attrs(self):
        container = get_service_registry()
        container._shipment_application_service_core = object()  # noqa: SLF001
        container._shipment_event_primary_facade = object()  # noqa: SLF001
        container.invalidate_shipment_wiring()
        assert container._shipment_application_service_core is None  # noqa: SLF001
        assert container._shipment_event_primary_facade is None  # noqa: SLF001


class TestFastapiDeps:
    def test_uses_app_state_services_when_present(self):
        container = ServiceContainer()
        app = SimpleNamespace(state=SimpleNamespace(services=container))
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
        req = Request(scope)
        assert get_service_container(req) is container


class TestRegistryArchitecture:
    def test_bootstrap_facades_delegate_to_service_registry_without_lru_cache(self):
        from app import bootstrap

        container = ServiceContainer()
        container._template_application_service = object()  # noqa: SLF001
        container._materials_service = object()  # noqa: SLF001
        container._products_service = object()  # noqa: SLF001
        container._extract_log_service = object()  # noqa: SLF001
        container._product_import_service = object()  # noqa: SLF001
        set_service_registry(container)

        for name in (
            "get_template_app_service",
            "get_materials_service",
            "get_products_service",
            "get_extract_log_service",
            "get_product_import_service",
        ):
            assert not hasattr(getattr(bootstrap, name), "cache_info")

        assert bootstrap.get_template_app_service() is container._template_application_service  # noqa: SLF001
        assert bootstrap.get_materials_service() is container._materials_service  # noqa: SLF001
        assert bootstrap.get_products_service() is container._products_service  # noqa: SLF001
        assert bootstrap.get_extract_log_service() is container._extract_log_service  # noqa: SLF001
        assert bootstrap.get_product_import_service() is container._product_import_service  # noqa: SLF001

    def test_app_code_has_no_function_scoped_di_registry_imports(self):
        app_root = Path(__file__).resolve().parents[2] / "app"
        offenders: list[str] = []

        def visit(path: Path, node: ast.AST, in_function: bool = False) -> None:
            child_in_function = in_function or isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            )
            if (
                child_in_function
                and isinstance(node, ast.ImportFrom)
                and node.module == "app.di.registry"
            ):
                offenders.append(f"{path.relative_to(app_root.parent)}:{node.lineno}")
            for child in ast.iter_child_nodes(node):
                visit(path, child, child_in_function)

        for path in sorted(app_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            visit(path, tree)

        assert offenders == []

    def test_falls_back_to_global_registry_when_services_missing(self):
        container = get_service_registry()
        app = SimpleNamespace(state=SimpleNamespace())
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "app": app,
        }
        req = Request(scope)
        assert get_service_container(req) is container
