#!/usr/bin/env python3
"""Validate MODstore_deploy/orchestration/*.yaml against JSON Schema + DAG acyclicity."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise SystemExit("PyYAML is required (pip install PyYAML)") from e

try:
    from jsonschema import Draft202012Validator
except ImportError as e:  # pragma: no cover
    raise SystemExit("jsonschema is required (pip install jsonschema)") from e


ROOT = Path(__file__).resolve().parent.parent  # MODstore_deploy
REPO_ROOT = ROOT.parent


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: root must be a mapping")
    return data


def _load_schema(filename: str) -> Dict[str, Any]:
    p = ROOT / "docs/contracts/orchestration" / filename
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def _validate_schema(instance: Dict[str, Any], schema: Dict[str, Any], label: str) -> None:
    Draft202012Validator(schema).validate(instance)
    print(f"[ok] schema: {label}")


def _deploy_topology_dag_and_refs(data: Dict[str, Any]) -> None:
    comps = data.get("components") or []
    ids: Set[str] = {str(c["id"]) for c in comps if isinstance(c, dict) and c.get("id")}
    edges: List[Dict[str, Any]] = list(data.get("edges") or [])
    for e in edges:
        if not isinstance(e, dict):
            raise SystemExit("deploy_topology: edge entries must be objects")
        f_, t_ = str(e.get("from", "")), str(e.get("to", ""))
        if f_ not in ids or t_ not in ids:
            raise SystemExit(f"deploy_topology: edge references unknown component: {e}")

    adj: Dict[str, List[str]] = {i: [] for i in ids}
    for e in edges:
        adj[str(e["from"])].append(str(e["to"]))

    # Directed cycle detection (DFS recursion stack)
    GRAY, BLACK = 1, 2
    state: Dict[str, int] = {}

    def dfs(u: str) -> bool:
        state[u] = GRAY
        for v in adj.get(u, []):
            sv = state.get(v, 0)
            if sv == GRAY:
                return True
            if sv == 0 and dfs(v):
                return True
        state[u] = BLACK
        return False

    for n in sorted(ids):
        if state.get(n, 0) == 0:
            if dfs(n):
                raise SystemExit("deploy_topology: edges contain a directed cycle")
    print("[ok] deploy_topology: edges are acyclic (DAG)")


def _workflow_files_exist(ci_data: Dict[str, Any]) -> None:
    workflows = ci_data.get("workflows") or []
    for wf in workflows:
        if not isinstance(wf, dict):
            continue
        fn = wf.get("file")
        if not fn:
            continue
        path = REPO_ROOT / str(fn)
        if not path.is_file():
            raise SystemExit(f"ci_pipeline: workflow file missing on disk: {fn}")
    print("[ok] ci_pipeline: workflow files referenced exist")


def main() -> int:
    dt_path = ROOT / "orchestration/deploy_topology.yaml"
    cp_path = ROOT / "orchestration/ci_pipeline.yaml"
    if not dt_path.is_file():
        raise SystemExit(f"missing {dt_path}")
    if not cp_path.is_file():
        raise SystemExit(f"missing {cp_path}")

    dt = _load_yaml(dt_path)
    cp = _load_yaml(cp_path)
    _validate_schema(dt, _load_schema("deploy_topology.schema.json"), "deploy_topology.yaml")
    _validate_schema(cp, _load_schema("ci_pipeline.schema.json"), "ci_pipeline.yaml")
    _deploy_topology_dag_and_refs(dt)
    _workflow_files_exist(cp)
    print("[ok] orchestration YAML validation complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
