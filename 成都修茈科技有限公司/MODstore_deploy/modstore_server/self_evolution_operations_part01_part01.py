# mypy: disable-error-code="attr-defined, index, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_evolution_knowledge")


def _search_docs(
    query: str,
    *,
    docs: _facade().Sequence[_facade().Dict[str, _facade().Any]],
    fields: _facade().Sequence[str],
    kind: str,
    limit: int,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    redisvl_rows, redisvl_meta = _facade()._rank_docs_with_redisvl(
        docs=docs, fields=fields, kind=kind, limit=limit, query=query
    )
    if redisvl_rows:
        return [
            {**row, "kb_search_meta": {**redisvl_meta, "fallback_used": False}}
            for row in redisvl_rows[:limit]
        ]
    fallback = _facade()._rank_docs(query, docs, fields, limit=limit)
    return [
        {
            **row,
            "kb_search_meta": {
                **redisvl_meta,
                "backend": "fhd_rag_plus_lexical",
                "fallback_used": True,
            },
            "search_backend": "fhd_rag_plus_lexical",
        }
        for row in fallback[:limit]
    ]


def record_fix_knowledge(
    *,
    symptom: str,
    root_cause: str,
    fix_diff: str,
    applicability_check: _facade().Optional[str] = None,
    metadata: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    patch_strategy: _facade().Optional[str] = None,
    required_tests: _facade().Optional[_facade().Sequence[str]] = None,
    rollback_plan: _facade().Optional[str] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Persist a symptom -> root cause -> fix diff triad."""
    payload: _facade().Dict[str, _facade().Any] = {
        "created_at": _facade()._iso_now(),
        "executable_template": {
            "applicability_check": _facade()._truncate(
                applicability_check
                or "Check whether the current symptom and changed files match this fix record before applying.",
                4000,
            ),
            "patch_strategy": _facade()._truncate(
                patch_strategy
                or "Apply the minimal equivalent source change; do not copy runtime-only artifacts.",
                4000,
            ),
            "required_tests": [str(item) for item in required_tests or []],
            "rollback_plan": _facade()._truncate(
                rollback_plan
                or "Revert the patch commit or restore the touched files if required tests fail.",
                4000,
            ),
        },
        "fix_diff": _facade()._truncate(fix_diff),
        "kind": "fix",
        "metadata": metadata or {},
        "root_cause": _facade()._truncate(root_cause, 6000),
        "schema_version": 1,
        "symptom": _facade()._truncate(symptom, 4000),
    }
    path = _facade()._write_kb_doc("fixes", "fix", payload)
    payload["_path"] = str(path)
    return payload


def search_fix_knowledge(
    query: str, *, limit: int = _facade().DEFAULT_FIX_LIMIT
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    docs = _facade()._load_kb_docs("fixes")
    return _facade()._search_docs(
        query,
        docs=docs,
        fields=("symptom", "root_cause", "fix_diff"),
        kind="fixes",
        limit=limit,
    )


def record_code_pattern(
    *,
    pattern: str,
    before: str,
    after: str,
    summary: str,
    metadata: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    payload: _facade().Dict[str, _facade().Any] = {
        "after": _facade()._truncate(after, 6000),
        "before": _facade()._truncate(before, 6000),
        "created_at": _facade()._iso_now(),
        "kind": "code_pattern",
        "metadata": metadata or {},
        "pattern": _facade()._truncate(pattern, 1000),
        "schema_version": 1,
        "summary": _facade()._truncate(summary, 4000),
    }
    path = _facade()._write_kb_doc("patterns", "pattern", payload)
    payload["_path"] = str(path)
    return payload


def search_code_patterns(
    query: str, *, limit: int = _facade().DEFAULT_PATTERN_LIMIT
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    docs = _facade()._load_kb_docs("patterns")
    return _facade()._search_docs(
        query,
        docs=docs,
        fields=("pattern", "summary", "before", "after"),
        kind="patterns",
        limit=limit,
    )


def _coverage_candidates(root: _facade().Path) -> _facade().List[_facade().Path]:
    explicit = _facade().os.environ.get("XCMAX_COVERAGE_JSON")
    candidates = [_facade().Path(explicit).expanduser()] if explicit else []
    candidates.extend(
        [
            root / "FHD" / "coverage.json",
            root / "coverage.json",
            _facade().Path.cwd() / "coverage.json",
        ]
    )
    unique: _facade().List[_facade().Path] = []
    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _load_coverage_modules(
    root: _facade().Path, *, limit: int = 10
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    for path in _facade()._coverage_candidates(root):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = _facade().json.load(fh)
        except (OSError, _facade().json.JSONDecodeError):
            continue
        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, dict):
            continue
        modules: _facade().List[_facade().Dict[str, _facade().Any]] = []
        for file_name, info in files.items():
            if not isinstance(info, dict):
                continue
            missing = info.get("missing_lines") or []
            if not isinstance(missing, list) or not missing:
                continue
            modules.append(
                {
                    "file": file_name,
                    "missing_count": len(missing),
                    "missing_lines": missing[:80],
                    "source": str(path),
                }
            )
        modules.sort(key=lambda item: int(item.get("missing_count") or 0), reverse=True)
        return modules[:limit]
    return []


def _dev_script(root: _facade().Path, name: str) -> _facade().Optional[str]:
    path = root / "FHD" / "scripts" / "dev" / name
    return str(path) if path.exists() else None


def collect_proactive_signals(
    *, root: _facade().Optional[_facade().Path] = None, limit: int = 10
) -> _facade().Dict[str, _facade().Any]:
    """Collect proactive self-evolution task candidates without running heavy jobs."""
    root = root or _facade().workspace_root()
    coverage_modules = _facade()._load_coverage_modules(root, limit=limit)
    type_debt_script = _facade()._dev_script(root, "count_type_debt.py")
    raw_sql_script = _facade()._dev_script(root, "count_raw_sql.py")
    coverage_ratchet_script = _facade()._dev_script(root, "coverage_ratchet.py")
    candidates: _facade().List[_facade().Dict[str, _facade().Any]] = [
        {
            "kind": "performance",
            "command": "pytest --durations=10",
            "description": "Find the 10 slowest tests and optimize the source paths they exercise.",
        }
    ]
    if coverage_modules:
        candidates.append(
            {
                "kind": "coverage",
                "description": "Add focused tests for modules with the most missing lines.",
                "modules": coverage_modules,
            }
        )
    debt_commands: _facade().List[str] = []
    if type_debt_script:
        debt_commands.append(f"python {type_debt_script}")
    if raw_sql_script:
        debt_commands.append(f"python {raw_sql_script}")
    if debt_commands:
        candidates.append(
            {
                "kind": "tech_debt",
                "commands": debt_commands,
                "description": "Reduce typed debt and raw SQL debt reported by scripts/dev.",
            }
        )
    workforce_gaps: _facade().List[_facade().Dict[str, _facade().Any]] = []
    try:
        from modstore_server.duty_workforce_learning import load_open_workforce_gaps

        workforce_gaps = load_open_workforce_gaps(limit=limit)
    except RECOVERABLE_ERRORS:
        workforce_gaps = []
    if workforce_gaps:
        candidates.insert(
            0,
            {
                "kind": "workforce_capability_gap",
                "description": "Implement or repair reviewed employee capabilities that failed strict burn-in, then require a later accepted receipt before closing each gap.",
                "gaps": workforce_gaps,
            },
        )
    return {
        "candidates": candidates,
        "coverage_modules": coverage_modules,
        "coverage_ratchet_script": coverage_ratchet_script,
        "root": str(root),
        "raw_sql_script": raw_sql_script,
        "type_debt_script": type_debt_script,
        "workforce_gap_count": len(workforce_gaps),
        "workforce_gaps": workforce_gaps,
    }


def load_evolution_metrics() -> _facade().List[_facade().Dict[str, _facade().Any]]:
    path = _facade().kb_root() / "metrics" / "evolution_metrics.jsonl"
    if not path.exists():
        return []
    records: _facade().List[_facade().Dict[str, _facade().Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = _facade().json.loads(line)
                except _facade().json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    records.append(item)
    except OSError:
        return []
    return records


def record_evolution_metrics(
    *,
    backend_coverage: float,
    pytest_passed: int,
    type_debt: int,
    week: _facade().Optional[str] = None,
    metadata: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    metrics_dir = _facade()._kb_dir("metrics")
    path = metrics_dir / "evolution_metrics.jsonl"
    payload = {
        "backend_coverage": float(backend_coverage),
        "created_at": _facade()._iso_now(),
        "metadata": metadata or {},
        "pytest_passed": int(pytest_passed),
        "type_debt": int(type_debt),
        "week": week or _facade()._utc_now().strftime("%G-W%V"),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_facade().json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return payload


def _metric_float(
    record: _facade().Dict[str, _facade().Any], key: str
) -> _facade().Optional[float]:
    try:
        return float(record[key])
    except (KeyError, TypeError, ValueError):
        return None


def _metric_delta(
    prev: _facade().Dict[str, _facade().Any], cur: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    prev_cov = _facade()._metric_float(prev, "backend_coverage")
    cur_cov = _facade()._metric_float(cur, "backend_coverage")
    prev_passed = _facade()._metric_float(prev, "pytest_passed")
    cur_passed = _facade()._metric_float(cur, "pytest_passed")
    prev_debt = _facade()._metric_float(prev, "type_debt")
    cur_debt = _facade()._metric_float(cur, "type_debt")
    coverage_delta = None if prev_cov is None or cur_cov is None else cur_cov - prev_cov
    passed_delta = None if prev_passed is None or cur_passed is None else cur_passed - prev_passed
    debt_delta = None if prev_debt is None or cur_debt is None else cur_debt - prev_debt
    misses: _facade().List[str] = []
    if coverage_delta is not None and coverage_delta < 0.5:
        misses.append("backend_coverage_target_missed")
    if passed_delta is not None and passed_delta < 0:
        misses.append("pytest_passed_regressed")
    if debt_delta is not None and debt_delta > -5:
        misses.append("type_debt_target_missed")
    return {
        "coverage_delta": coverage_delta,
        "debt_delta": debt_delta,
        "from_week": prev.get("week"),
        "misses": misses,
        "passed_delta": passed_delta,
        "to_week": cur.get("week"),
    }


def evaluate_evolution_regression(
    history: _facade().Sequence[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    """Pause when the last two week-to-week windows miss evolution targets."""
    if len(history) < 3:
        return {"pause": False, "reason": "insufficient_metrics_history", "windows": []}
    last_three = list(history)[-3:]
    windows = [
        _facade()._metric_delta(last_three[0], last_three[1]),
        _facade()._metric_delta(last_three[1], last_three[2]),
    ]
    bad_windows = [window for window in windows if window.get("misses")]
    if len(bad_windows) == 2:
        return {
            "pause": True,
            "reason": "two_consecutive_evolution_metric_regressions",
            "windows": windows,
        }
    return {
        "pause": False,
        "reason": "metrics_not_regressing_consecutively",
        "windows": windows,
    }


def evolution_metrics_gate() -> _facade().Dict[str, _facade().Any]:
    raw_history = _facade().load_evolution_metrics()
    history = [
        item
        for item in raw_history
        if isinstance(item.get("metadata"), dict)
        and item["metadata"].get("evidence_verified") is True
    ]
    result = _facade().evaluate_evolution_regression(history)
    return {
        **result,
        "history_count": len(history),
        "raw_history_count": len(raw_history),
        "verified_history_count": len(history),
        "metrics_path": str(_facade().kb_root() / "metrics" / "evolution_metrics.jsonl"),
    }


def _knowledge_query(
    evaluation: _facade().Dict[str, _facade().Any],
    memory: _facade().Dict[str, _facade().Any],
) -> str:
    payload = {
        "gaps": evaluation.get("gaps"),
        "incident_count": evaluation.get("incident_count"),
        "incident_signals": evaluation.get("incident_signals"),
        "last_policy_decision": (
            memory.get("last_policy_decision") if isinstance(memory, dict) else None
        ),
        "open_items": (
            (memory.get("open_items") if isinstance(memory, dict) else [])[-8:]
            if isinstance(memory.get("open_items") if isinstance(memory, dict) else [], list)
            else []
        ),
        "recent_runs": (
            (memory.get("recent_runs") if isinstance(memory, dict) else [])[-5:]
            if isinstance(memory.get("recent_runs") if isinstance(memory, dict) else [], list)
            else []
        ),
    }
    return _facade().json.dumps(payload, ensure_ascii=False, sort_keys=True)
