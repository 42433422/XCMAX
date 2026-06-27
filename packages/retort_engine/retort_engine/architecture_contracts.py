from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from retort_engine.codebase_graph import build_codebase_graph


def default_architecture_contracts() -> list[dict[str, Any]]:
    return [
        {
            "name": "codebase_graph_stays_foundational",
            "type": "forbidden_import",
            "source": "retort_engine.codebase_graph",
            "forbidden": ["retort_engine.core", "retort_engine.service", "retort_engine.ui_server", "retort_engine.paibi_llm"],
            "reason": "Code graphing must stay deterministic and below runtime, UI, and LLM boundaries.",
        },
        {
            "name": "contracts_stay_schema_only",
            "type": "forbidden_import",
            "source": "retort_engine.contracts",
            "forbidden": ["retort_engine.core", "retort_engine.service", "retort_engine.paibi_llm"],
            "reason": "Contract schemas should not depend on runtime execution surfaces.",
        },
    ]


def load_architecture_contracts(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("contracts") or []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def evaluate_architecture_contracts(
    project: str | Path,
    *,
    contracts: list[dict[str, Any]] | None = None,
    include_tests: bool = False,
    max_files: int = 400,
) -> dict[str, Any]:
    graph = build_codebase_graph(project, include_tests=include_tests, max_files=max_files)
    active_contracts = contracts if contracts is not None else default_architecture_contracts()
    violations: list[dict[str, Any]] = []
    for contract in active_contracts:
        if str(contract.get("type") or "") == "forbidden_import":
            violations.extend(_forbidden_import_violations(graph, contract))
    return {
        "status": "passed" if not violations and graph["status"] in {"ready", "partial"} else ("failed" if violations else graph["status"]),
        "project": graph["project"],
        "summary": {
            "contract_count": len(active_contracts),
            "violation_count": len(violations),
            "import_edge_count": graph["summary"]["import_edge_count"],
            "graph_status": graph["status"],
            "include_tests": include_tests,
        },
        "contracts": active_contracts,
        "violations": violations,
        "evidence": {
            "style": "import_linter_architecture_contracts",
            "graph_summary": graph["summary"],
        },
    }


def _forbidden_import_violations(graph: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    source_prefixes = _list_value(contract.get("source") or contract.get("sources"))
    forbidden_prefixes = _list_value(contract.get("forbidden"))
    violations: list[dict[str, Any]] = []
    for edge in graph.get("edges") or []:
        if edge.get("kind") != "imports":
            continue
        source_module = _module_from_path(str(edge.get("from") or ""))
        imported = str(edge.get("to") or "")
        if _matches_any(source_module, source_prefixes) and _matches_any(imported, forbidden_prefixes):
            violations.append(
                {
                    "contract": str(contract.get("name") or "forbidden_import"),
                    "source": source_module,
                    "imported": imported,
                    "reason": str(contract.get("reason") or "forbidden import boundary crossed"),
                }
            )
    return violations


def _module_from_path(path: str) -> str:
    module = path.removesuffix(".py").replace("/", ".")
    return module.removesuffix(".__init__")


def _list_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _matches_any(value: str, prefixes: list[str]) -> bool:
    return any(value == prefix or value.startswith(prefix + ".") for prefix in prefixes)
