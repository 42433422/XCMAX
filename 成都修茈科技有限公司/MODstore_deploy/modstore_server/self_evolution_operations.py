# ruff: noqa
# mypy: ignore-errors
"""Search, metrics, and salvage operations for self-evolution knowledge."""
from __future__ import annotations
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
    (redisvl_rows, redisvl_meta) = _facade()._rank_docs_with_redisvl(
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
        query, docs=docs, fields=("symptom", "root_cause", "fix_diff"), kind="fixes", limit=limit
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
    except Exception:
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
    history: _facade().Sequence[_facade().Dict[str, _facade().Any]]
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
    return {"pause": False, "reason": "metrics_not_regressing_consecutively", "windows": windows}


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
    evaluation: _facade().Dict[str, _facade().Any], memory: _facade().Dict[str, _facade().Any]
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


def build_self_evolution_context(
    *,
    run_id: str,
    evaluation: _facade().Dict[str, _facade().Any],
    memory: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    query = _facade()._knowledge_query(evaluation, memory)
    proactive = _facade().collect_proactive_signals()
    fix_hits = _facade().search_fix_knowledge(query, limit=3)
    pattern_hits = _facade().search_code_patterns(query, limit=5)
    try:
        from modstore_server.self_evolution_kb_redisvl import status as redisvl_status

        kb_backend_status = redisvl_status()
    except Exception as exc:
        kb_backend_status = {"backend": "redisvl", "error": str(exc)[:500], "ready": False}
    context = {
        "fix_knowledge_hits": fix_hits,
        "inventory": _facade().knowledge_inventory(),
        "kb_root": str(_facade().kb_root()),
        "kb_search": {
            "engine": "redisvl_primary_with_fhd_rag_lexical_fallback",
            "fix_hit_count": len(fix_hits),
            "pattern_hit_count": len(pattern_hits),
            "redisvl_status": kb_backend_status,
        },
        "metrics_gate": _facade().evolution_metrics_gate(),
        "pattern_hits": pattern_hits,
        "proactive_signals": proactive,
        "query": query[:3000],
        "run_id": run_id,
    }
    return context


def render_self_evolution_context(context: _facade().Dict[str, _facade().Any]) -> str:
    return _facade().json.dumps(
        context, ensure_ascii=False, sort_keys=True, default=_facade()._json_default
    )[: _facade().MAX_CONTEXT_TEXT]


def _step_report_text(final: _facade().Dict[str, _facade().Any]) -> str:
    steps = final.get("steps")
    if not isinstance(steps, list):
        return ""
    reports = []
    for step in steps:
        if isinstance(step, dict) and step.get("report_excerpt"):
            reports.append(f"[{step.get('step')}] {step.get('report_excerpt')}")
    return "\n".join(reports)


def infer_pattern_from_diff(diff_text: str) -> _facade().Dict[str, str]:
    lowered = diff_text.lower()
    if "-time.sleep(" in lowered and "+asyncio.sleep(" in lowered:
        return {
            "pattern": "sync_blocking_sleep_to_async_sleep",
            "summary": "Replace blocking time.sleep calls inside async paths with asyncio.sleep.",
        }
    if (
        _facade().re.search("^-.*except\\s*:\\s*$", diff_text, _facade().re.MULTILINE)
        and "logger.exception" in lowered
    ):
        return {
            "pattern": "swallowed_exception_to_logged_exception",
            "summary": "Replace broad swallowed exceptions with logged Exception handlers.",
        }
    if "checkfirst=true" in lowered and "create_all" not in lowered:
        return {
            "pattern": "idempotent_runtime_schema_guard",
            "summary": "Make runtime schema creation idempotent before reads and writes.",
        }
    if "report_only" in lowered or "modstore_report_only" in lowered:
        return {
            "pattern": "report_only_employee_guard",
            "summary": "Keep review and QA employee tasks report-only so they cannot mutate code.",
        }
    return {
        "pattern": "approved_low_risk_self_maintenance_change",
        "summary": "Approved low-risk self-maintenance change that passed review and QA gates.",
    }


def record_loop_evolution_knowledge(
    final: _facade().Dict[str, _facade().Any], gate: _facade().Dict[str, _facade().Any]
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    decision = final.get("policy_decision")
    if not isinstance(decision, dict) or decision.get("action") != "auto_merged_low_risk":
        return None
    merge_result = decision.get("merge_result")
    if not isinstance(merge_result, dict):
        return None
    diff_text = str(merge_result.get("diff_excerpt") or "")
    if not diff_text:
        return None
    reports = _facade()._step_report_text(final)
    gaps = gate.get("gaps") if isinstance(gate, dict) else None
    symptom = "; ".join((str(item) for item in gaps)) if isinstance(gaps, list) and gaps else ""
    if not symptom:
        symptom = str(decision.get("reason") or final.get("status") or "self-maintenance gap")
    root_cause = reports or _facade().json.dumps(
        decision, ensure_ascii=False, sort_keys=True, default=_facade()._json_default
    )
    metadata = {
        "branch": final.get("branch"),
        "changed_files": merge_result.get("changed_files"),
        "merge_commit_sha": merge_result.get("merge_commit_sha"),
        "para_task_id": final.get("para_task_id"),
        "run_id": final.get("run_id"),
    }
    fix_doc = _facade().record_fix_knowledge(
        symptom=symptom,
        root_cause=root_cause,
        fix_diff=diff_text,
        applicability_check="Match the current loop symptom, policy decision, and changed file scope against this run before applying an equivalent patch.",
        metadata=metadata,
        patch_strategy="Reuse the same minimal diff shape on the target branch, then re-run review/QA.",
        required_tests=[
            "git diff --check",
            "focused pytest for changed MODstore modules",
            "report-only review JSON",
            "report-only QA JSON",
        ],
        rollback_plan="Revert the merge commit or close the branch without merging if structured QA fails.",
    )
    pattern_info = _facade().infer_pattern_from_diff(diff_text)
    pattern_doc = _facade().record_code_pattern(
        pattern=pattern_info["pattern"],
        before="See fix_diff in paired fix knowledge document.",
        after=diff_text,
        summary=pattern_info["summary"],
        metadata={**metadata, "fix_path": fix_doc.get("_path")},
    )
    return {
        "fix_path": fix_doc.get("_path"),
        "pattern": pattern_doc.get("pattern"),
        "pattern_path": pattern_doc.get("_path"),
    }


def _salvage_kb_files(
    *,
    src_dir: _facade().Path,
    kind: str,
    run_id: str,
    existing_docs: _facade().Sequence[_facade().Dict[str, _facade().Any]],
) -> _facade().Tuple[int, int]:
    """Scan src_dir for KB JSON of given kind; validate, dedup, and re-record.

    Returns (salvaged_count, skipped_count). Never raises.
    """
    if not src_dir.exists() or not src_dir.is_dir():
        return (0, 0)
    salvaged = 0
    skipped = 0
    for path in sorted(src_dir.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = _facade().json.load(fh)
        except (OSError, _facade().json.JSONDecodeError):
            skipped += 1
            continue
        if not isinstance(payload, dict):
            skipped += 1
            continue
        try:
            _facade().validate_kb_payload(kind, payload)
        except ValueError:
            skipped += 1
            continue
        if kind == "fixes":
            symptom = str(payload.get("symptom") or "")
            root_cause = str(payload.get("root_cause") or "")
            if any(
                (
                    str(doc.get("symptom") or "") == symptom
                    and str(doc.get("root_cause") or "") == root_cause
                    for doc in existing_docs
                )
            ):
                skipped += 1
                continue
            template = (
                payload.get("executable_template")
                if isinstance(payload.get("executable_template"), dict)
                else {}
            )
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            _facade().record_fix_knowledge(
                symptom=symptom,
                root_cause=root_cause,
                fix_diff=str(payload.get("fix_diff") or ""),
                applicability_check=str(template.get("applicability_check") or "") or None,
                patch_strategy=str(template.get("patch_strategy") or "") or None,
                required_tests=template.get("required_tests"),
                rollback_plan=str(template.get("rollback_plan") or "") or None,
                metadata={**metadata, "salvaged_from": str(path), "salvaged_run_id": run_id},
            )
            salvaged += 1
        else:
            pattern = str(payload.get("pattern") or "")
            summary = str(payload.get("summary") or "")
            if any(
                (
                    str(doc.get("pattern") or "") == pattern
                    and str(doc.get("summary") or "") == summary
                    for doc in existing_docs
                )
            ):
                skipped += 1
                continue
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            _facade().record_code_pattern(
                pattern=pattern,
                before=str(payload.get("before") or ""),
                after=str(payload.get("after") or ""),
                summary=summary,
                metadata={**metadata, "salvaged_from": str(path), "salvaged_run_id": run_id},
            )
            salvaged += 1
    return (salvaged, skipped)


def salvage_kb_from_workspace(
    para_workspace: _facade().Path, run_id: str
) -> _facade().Dict[str, _facade().Any]:
    """Salvage KB JSON files from a para workspace into kb_root.

    Defensive: para_workspace missing / KB dir missing / JSON parse failures
    never raise; they are counted as skipped. Returns a summary dict.
    """
    summary: _facade().Dict[str, _facade().Any] = {
        "salvaged_fixes": 0,
        "salvaged_patterns": 0,
        "skipped": 0,
        "run_id": run_id,
        "workspace": str(para_workspace),
    }
    try:
        workspace = _facade().Path(para_workspace)
    except TypeError:
        return summary
    if not workspace.exists() or not workspace.is_dir():
        return summary
    kb_base = workspace / "FHD" / "XCAGI" / "kb"
    if not kb_base.exists():
        return summary
    existing_fixes = _facade()._load_kb_docs("fixes")
    (salvaged_fixes, skipped_fixes) = _facade()._salvage_kb_files(
        src_dir=kb_base / "fixes", kind="fixes", run_id=run_id, existing_docs=existing_fixes
    )
    existing_patterns = _facade()._load_kb_docs("patterns")
    (salvaged_patterns, skipped_patterns) = _facade()._salvage_kb_files(
        src_dir=kb_base / "patterns",
        kind="patterns",
        run_id=run_id,
        existing_docs=existing_patterns,
    )
    summary["salvaged_fixes"] = salvaged_fixes
    summary["salvaged_patterns"] = salvaged_patterns
    summary["skipped"] = skipped_fixes + skipped_patterns
    return summary
