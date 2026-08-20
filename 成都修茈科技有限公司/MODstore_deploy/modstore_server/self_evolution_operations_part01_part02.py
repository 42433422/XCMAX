# mypy: disable-error-code="attr-defined, dict-item, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_evolution_knowledge")


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
    except RECOVERABLE_ERRORS as exc:
        kb_backend_status = {
            "backend": "redisvl",
            "error": str(exc)[:500],
            "ready": False,
        }
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
                metadata={
                    **metadata,
                    "salvaged_from": str(path),
                    "salvaged_run_id": run_id,
                },
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
                metadata={
                    **metadata,
                    "salvaged_from": str(path),
                    "salvaged_run_id": run_id,
                },
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
    salvaged_fixes, skipped_fixes = _facade()._salvage_kb_files(
        src_dir=kb_base / "fixes",
        kind="fixes",
        run_id=run_id,
        existing_docs=existing_fixes,
    )
    existing_patterns = _facade()._load_kb_docs("patterns")
    salvaged_patterns, skipped_patterns = _facade()._salvage_kb_files(
        src_dir=kb_base / "patterns",
        kind="patterns",
        run_id=run_id,
        existing_docs=existing_patterns,
    )
    summary["salvaged_fixes"] = salvaged_fixes
    summary["salvaged_patterns"] = salvaged_patterns
    summary["skipped"] = skipped_fixes + skipped_patterns
    return summary
