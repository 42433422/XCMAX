from __future__ import annotations

import json
import zipfile
from pathlib import Path

import yaml

from modstore_server.employee_ai_scaffold import _normalize_action_handlers
from modstore_server.employee_runtime import employee_pack_runtime_issues
from modstore_server.integrations.doc_sync_handler import _match_glob
from modstore_server.scripts.onboard_yuangon_employees import _manifest_from_employee_yaml

COMPANY_ROOT = Path(__file__).resolve().parents[2]
YUANGON_ROOT = COMPANY_ROOT / "yuangon"


def _employees() -> dict[str, tuple[Path, dict]]:
    rows: dict[str, tuple[Path, dict]] = {}
    for path in sorted(YUANGON_ROOT.rglob("employee.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        employee_id = str(data.get("id") or "").strip()
        assert employee_id and employee_id not in rows
        rows[employee_id] = (path, data)
    return rows


def _cycle_nodes(graph: dict[str, list[str]]) -> set[str]:
    state: dict[str, int] = {}
    stack: list[str] = []
    cycles: set[str] = set()

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for dep in graph[node]:
            if state.get(dep, 0) == 0:
                visit(dep)
            elif state.get(dep) == 1:
                cycles.update(stack[stack.index(dep) :])
        stack.pop()
        state[node] = 2

    for node in graph:
        if state.get(node, 0) == 0:
            visit(node)
    return cycles


def test_all_yuangon_employees_are_explicit_and_complete():
    rows = _employees()
    assert len(rows) == 54
    known = set(rows)
    for employee_id, (path, data) in rows.items():
        base = path.parent
        assert (base / "README.md").is_file(), employee_id
        assert (base / "runbook.md").is_file(), employee_id
        assert (base / "prompts" / "system.md").is_file(), employee_id
        assert data.get("capabilities"), employee_id
        assert data.get("skills"), employee_id
        assert data.get("actions", {}).get("handlers"), employee_id
        assert data.get("examples"), employee_id
        assert set(data.get("depends_on") or []).issubset(known), employee_id
        for relpath in data["skills"]:
            assert (base / str(relpath)).is_file(), f"{employee_id}: {relpath}"


def test_yuangon_dependency_graph_is_acyclic():
    rows = _employees()
    graph = {
        employee_id: [str(dep) for dep in data.get("depends_on") or []]
        for employee_id, (_path, data) in rows.items()
    }
    assert not _cycle_nodes(graph)


def test_handler_normalizer_keeps_executor_supported_handlers():
    handlers = _normalize_action_handlers(
        ["doc_sync", "direct_python", "openapi_tool", "fhd_business", "shell_exec"]
    )
    assert handlers == [
        "doc_sync",
        "direct_python",
        "openapi_tool",
        "fhd_business",
        "shell_exec",
    ]


def test_yuangon_manifest_generation_preserves_declared_handlers():
    rows = _employees()
    for employee_id, (path, data) in rows.items():
        manifest, error = _manifest_from_employee_yaml(data, pack_dir=path.parent)
        assert error == "", employee_id
        assert manifest is not None, employee_id
        actions = data.get("actions") if isinstance(data.get("actions"), dict) else {}
        yaml_handlers = [str(h).strip() for h in actions.get("handlers", []) if str(h).strip()]
        manifest_handlers = manifest["employee_config_v2"]["actions"]["handlers"]
        assert manifest_handlers == yaml_handlers, employee_id


def test_root_anchored_scope_glob_does_not_match_nested_file():
    assert _match_glob("main.js", ["./main.js"])
    assert not _match_glob("desktop-shell/main.js", ["./main.js"])


def test_yuangon_manifest_without_actions_uses_safe_knowledge_worker_fallback():
    manifest, error = _manifest_from_employee_yaml(
        {
            "id": "sample-role",
            "name": "示例岗位",
            "version": "1.0.0",
            "domain": "只读分析",
            "owner": "admin",
            "capabilities": ["sample.audit"],
            "skills": [],
            "scope_globs": ["docs/**"],
            "forbidden_globs": ["**/*.db"],
        }
    )
    assert error == ""
    assert manifest is not None
    actions = manifest["employee_config_v2"]["actions"]
    assert actions == {"handlers": ["llm_md", "echo"]}


def test_runtime_validator_rejects_generic_dispatch_for_direct_python(tmp_path, monkeypatch):
    import modstore_server.employee_runtime as runtime

    monkeypatch.setattr(runtime, "files_dir", lambda: tmp_path)
    manifest = {
        "id": "broken-worker",
        "employee_config_v2": {
            "actions": {
                "handlers": ["direct_python"],
                "direct_python": {"module": "broken_worker"},
            }
        },
    }
    archive = tmp_path / "broken-worker.xcemp"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("broken-worker/manifest.json", json.dumps(manifest))
        zf.writestr(
            "broken-worker/backend/employees/broken_worker.py",
            "_DISPATCH = {'echo': object()}\n",
        )
    issues = employee_pack_runtime_issues(
        {
            "pack_id": "broken-worker",
            "stored_filename": archive.name,
            "manifest": manifest,
        }
    )
    assert any("通用分发模板" in issue for issue in issues)
    assert any("vendor 运行时缺失" in issue for issue in issues)
