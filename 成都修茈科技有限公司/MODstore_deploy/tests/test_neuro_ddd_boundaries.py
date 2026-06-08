from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modstore_server"


def _py_files(path: Path):
    return [p for p in path.rglob("*.py") if "__pycache__" not in p.parts]


def test_domain_layer_has_no_framework_or_infra_imports():
    forbidden = ("fastapi", "sqlalchemy", "httpx", "requests")
    offenders = []
    for path in _py_files(ROOT / "domain"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if f"import {token}" in text or f"from {token}" in text:
                offenders.append(f"{path.relative_to(ROOT)} imports {token}")
    assert offenders == []


def test_shared_auth_dependency_is_not_reimplemented_in_legacy_api_modules():
    offenders = []
    for path in _py_files(ROOT):
        text = path.read_text(encoding="utf-8")
        if "from modstore_server.market_api import _get_current_user" in text:
            offenders.append(str(path.relative_to(ROOT)))
        if "def _get_current_user(" in text or "def _require_admin(" in text:
            offenders.append(f"{path.relative_to(ROOT)} reimplements auth dependency")
    assert offenders == []


def test_database_dependency_is_not_reimplemented_in_api_modules():
    offenders = []
    for path in _py_files(ROOT):
        if path.parent.name not in {"modstore_server", "api"} and path.parent != ROOT:
            continue
        text = path.read_text(encoding="utf-8")
        if "def get_db(" in text or "from modstore_server.llm_api import get_db" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_domain_layer_does_not_import_application_or_infrastructure():
    forbidden_prefixes = (
        "from modstore_server.application",
        "from modstore_server.infrastructure",
        "from modstore_server.api",
        "import modstore_server.application",
        "import modstore_server.infrastructure",
        "import modstore_server.api",
    )
    offenders = []
    for path in _py_files(ROOT / "domain"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_prefixes:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)} imports outward via {token}")
    assert offenders == []
