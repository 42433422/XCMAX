"""Declared governance packages fail closed when missing or broken."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from modstore_server.integrations import repository_packages


def test_source_checkout_loads_declared_governance_and_builder_packages():
    assert callable(
        repository_packages.load_repository_module(
            "retort_engine.intent_alignment"
        ).assess_change_intent_alignment
    )
    assert callable(
        repository_packages.load_repository_module(
            "retort_engine.clarification"
        ).build_clarification_questions
    )
    assert callable(
        repository_packages.load_repository_module("xcagi_common.employee_pack").build_employee_pack
    )


def test_undeclared_package_cannot_extend_the_runtime_import_path():
    original = list(sys.path)
    with pytest.raises(ImportError, match="undeclared"):
        repository_packages.load_repository_module("unlisted_dependency.plugin")
    assert sys.path == original


@pytest.mark.parametrize("missing", ["retort_engine", "internal_crypto_dependency"])
def test_missing_or_broken_governance_dependency_is_not_silently_replaced(
    tmp_path, monkeypatch, missing
):
    def unavailable(_name):
        raise ModuleNotFoundError(f"No module named {missing}", name=missing)

    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(tmp_path))
    monkeypatch.delenv("MODSTORE_RETORT_ENGINE_ROOT", raising=False)
    monkeypatch.setattr(repository_packages.importlib, "import_module", unavailable)
    original = list(sys.path)
    with pytest.raises(ImportError):
        repository_packages.load_repository_module("retort_engine.intent_alignment")
    assert sys.path == original


def test_common_builder_has_no_application_or_retort_runtime_dependency():
    import ast

    module = repository_packages.load_repository_module("xcagi_common.employee_pack")
    tree = ast.parse(Path(module.__file__).read_text())
    imports = {
        name.split(".")[0]
        for node in ast.walk(tree)
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        )
    }
    assert imports <= sys.stdlib_module_names
