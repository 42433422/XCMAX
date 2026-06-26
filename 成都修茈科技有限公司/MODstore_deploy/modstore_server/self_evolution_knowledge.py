"""Self-evolution knowledge base and proactive task signals.

The loop stores durable, file-backed knowledge under FHD/XCAGI/kb so later runs
can retrieve known fixes and approved code patterns before asking employees to
reason from scratch.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_FIX_LIMIT = 5
DEFAULT_PATTERN_LIMIT = 8
MAX_DOC_TEXT = 20000
MAX_CONTEXT_TEXT = 12000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _safe_slug(text: str, fallback: str = "item") -> str:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    slug = "-".join(tokens[:8]).strip("-")
    return slug or fallback


def _truncate(value: Any, limit: int = MAX_DOC_TEXT) -> str:
    text = str(value or "")
    return text[:limit]


def _candidate_workspace_roots() -> List[Path]:
    candidates: List[Path] = []
    for env_name in ("XCMAX_WORKSPACE_ROOT", "MODSTORE_PROJECT_ROOT"):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw).expanduser())

    try:
        current = Path(__file__).resolve()
        candidates.extend(current.parents)
    except OSError:
        pass

    candidates.extend([Path.cwd(), Path.home() / "Desktop" / "XCMAX"])

    seen = set()
    unique: List[Path] = []
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def workspace_root() -> Path:
    for root in _candidate_workspace_roots():
        if (root / "FHD" / "app" / "infrastructure" / "rag").exists():
            return root
        if (root / "FHD").exists() and (root / "成都修茈科技有限公司").exists():
            return root
    return Path(os.environ.get("XCMAX_WORKSPACE_ROOT") or Path.home() / "Desktop" / "XCMAX")


def kb_root() -> Path:
    raw = os.environ.get("XCMAX_SELF_EVOLUTION_KB_ROOT") or os.environ.get("XCMAX_KB_ROOT")
    if raw:
        return Path(raw).expanduser()
    return workspace_root() / "FHD" / "XCAGI" / "kb"


def _kb_dir(kind: str) -> Path:
    path = kb_root() / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _write_kb_doc(kind: str, prefix: str, payload: Dict[str, Any]) -> Path:
    validate_kb_payload(kind, payload)
    directory = _kb_dir(kind)
    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    slug_source = (
        payload.get("symptom")
        or payload.get("pattern")
        or payload.get("summary")
        or payload.get("id")
        or kind
    )
    path = directory / f"{stamp}-{prefix}-{_safe_slug(str(slug_source), kind)}.json"
    counter = 1
    while path.exists():
        path = directory / f"{stamp}-{prefix}-{_safe_slug(str(slug_source), kind)}-{counter}.json"
        counter += 1
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
        fh.write("\n")
    return path


def _validation_error(message: str) -> ValueError:
    return ValueError(f"invalid self-evolution KB payload: {message}")


def _require_non_empty_string(payload: Dict[str, Any], field: str) -> None:
    if not isinstance(payload.get(field), str) or not str(payload.get(field) or "").strip():
        raise _validation_error(f"{field} must be a non-empty string")


def validate_fix_knowledge_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _validation_error("fix payload must be an object")
    if payload.get("schema_version") != 1:
        raise _validation_error("fix schema_version must be 1")
    if payload.get("kind") != "fix":
        raise _validation_error("fix kind must be 'fix'")
    for field in ("created_at", "symptom", "root_cause", "fix_diff"):
        _require_non_empty_string(payload, field)
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise _validation_error("fix metadata must be an object")
    template = payload.get("executable_template")
    if not isinstance(template, dict):
        raise _validation_error("fix executable_template must be an object")
    for field in ("applicability_check", "patch_strategy", "rollback_plan"):
        _require_non_empty_string(template, field)
    required_tests = template.get("required_tests")
    if not isinstance(required_tests, list) or not all(isinstance(item, str) for item in required_tests):
        raise _validation_error("fix executable_template.required_tests must be a string list")
    return payload


def validate_code_pattern_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _validation_error("pattern payload must be an object")
    if payload.get("schema_version") != 1:
        raise _validation_error("pattern schema_version must be 1")
    if payload.get("kind") not in {"code_pattern", "pattern"}:
        raise _validation_error("pattern kind must be 'code_pattern' or 'pattern'")
    for field in ("created_at", "pattern", "summary"):
        _require_non_empty_string(payload, field)
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise _validation_error("pattern metadata must be an object")
    return payload


def validate_kb_payload(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "fixes":
        return validate_fix_knowledge_payload(payload)
    if kind == "patterns":
        return validate_code_pattern_payload(payload)
    return payload


def _load_kb_docs(kind: str) -> List[Dict[str, Any]]:
    directory = kb_root() / kind
    if not directory.exists():
        return []
    docs: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                data.setdefault("_path", str(path))
                docs.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return docs


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_./:-]+|[\u4e00-\u9fff]{2,}", text.lower())


def _lexical_score(query: str, doc: Dict[str, Any], fields: Sequence[str]) -> float:
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return 0.0
    haystack = "\n".join(str(doc.get(field) or "") for field in fields)
    hay_tokens = set(_tokens(haystack))
    if not hay_tokens:
        return 0.0
    overlap = len(query_tokens & hay_tokens)
    phrase_bonus = 2.0 if query.strip() and query.strip().lower() in haystack.lower() else 0.0
    return overlap / max(len(query_tokens), 1) + phrase_bonus


def _format_docs_for_rag(docs: Sequence[Dict[str, Any]]) -> str:
    chunks: List[str] = []
    for idx, doc in enumerate(docs, start=1):
        kind = str(doc.get("kind") or "knowledge")
        title = doc.get("symptom") or doc.get("pattern") or doc.get("summary") or doc.get("id")
        body = json.dumps(doc, ensure_ascii=False, sort_keys=True, default=_json_default)
        chunks.append(f"[{idx}] kind={kind}\ntitle={title}\n{body}")
    return "\n\n---\n\n".join(chunks)[:MAX_CONTEXT_TEXT]


def _retrieve_with_fhd_rag(query: str, docs: Sequence[Dict[str, Any]], limit: int) -> List[str]:
    if not docs:
        return []
    root = workspace_root()
    fhd_root = root / "FHD"
    inserted = False
    try:
        if str(fhd_root) not in sys.path:
            sys.path.insert(0, str(fhd_root))
            inserted = True
        from app.infrastructure.rag import RagService

        service = RagService(embedder=None)
        result = service.answer(
            user_message=query,
            knowledge_text=_format_docs_for_rag(docs),
            llm_call=lambda _message, retrieved: retrieved,
            top_k=limit,
            chunk_strategy="fixed",
        )
        chunks = result.get("chunks") if isinstance(result, dict) else None
        if not isinstance(chunks, list):
            return []
        return [str(chunk.get("text") or "") for chunk in chunks[:limit] if isinstance(chunk, dict)]
    except Exception:
        return []
    finally:
        if inserted:
            try:
                sys.path.remove(str(fhd_root))
            except ValueError:
                pass


def _rank_docs(
    query: str,
    docs: Sequence[Dict[str, Any]],
    fields: Sequence[str],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    rag_chunks = _retrieve_with_fhd_rag(query, docs, limit)
    rag_text = "\n".join(rag_chunks)
    ranked: List[Tuple[float, Dict[str, Any]]] = []
    for doc in docs:
        score = _lexical_score(query, doc, fields)
        doc_text = json.dumps(doc, ensure_ascii=False, sort_keys=True, default=_json_default)
        if rag_text and any(str(doc.get(field) or "")[:80] in rag_text for field in fields):
            score += 0.75
        if score > 0:
            ranked.append((score, {**doc, "score": round(score, 4), "rag_chunks": rag_chunks[:limit]}))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in ranked[:limit]]


def _rank_docs_with_redisvl(
    *,
    docs: Sequence[Dict[str, Any]],
    fields: Sequence[str],
    kind: str,
    limit: int,
    query: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    try:
        from modstore_server.self_evolution_kb_redisvl import query as redisvl_query

        rows, meta = redisvl_query(
            docs=docs,
            fields=fields,
            kind=kind,
            limit=limit,
            query_text=query,
        )
        if rows:
            return rows, meta
        return [], meta
    except Exception as exc:
        return [], {
            "backend": "redisvl",
            "error": str(exc)[:500],
            "ready": False,
        }


def _search_docs(
    query: str,
    *,
    docs: Sequence[Dict[str, Any]],
    fields: Sequence[str],
    kind: str,
    limit: int,
) -> List[Dict[str, Any]]:
    redisvl_rows, redisvl_meta = _rank_docs_with_redisvl(
        docs=docs,
        fields=fields,
        kind=kind,
        limit=limit,
        query=query,
    )
    if redisvl_rows:
        return [
            {
                **row,
                "kb_search_meta": {
                    **redisvl_meta,
                    "fallback_used": False,
                },
            }
            for row in redisvl_rows[:limit]
        ]
    fallback = _rank_docs(query, docs, fields, limit=limit)
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
    applicability_check: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    patch_strategy: Optional[str] = None,
    required_tests: Optional[Sequence[str]] = None,
    rollback_plan: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a symptom -> root cause -> fix diff triad."""

    payload: Dict[str, Any] = {
        "created_at": _iso_now(),
        "executable_template": {
            "applicability_check": _truncate(
                applicability_check
                or "Check whether the current symptom and changed files match this fix record before applying.",
                4000,
            ),
            "patch_strategy": _truncate(
                patch_strategy
                or "Apply the minimal equivalent source change; do not copy runtime-only artifacts.",
                4000,
            ),
            "required_tests": [str(item) for item in (required_tests or [])],
            "rollback_plan": _truncate(
                rollback_plan
                or "Revert the patch commit or restore the touched files if required tests fail.",
                4000,
            ),
        },
        "fix_diff": _truncate(fix_diff),
        "kind": "fix",
        "metadata": metadata or {},
        "root_cause": _truncate(root_cause, 6000),
        "schema_version": 1,
        "symptom": _truncate(symptom, 4000),
    }
    path = _write_kb_doc("fixes", "fix", payload)
    payload["_path"] = str(path)
    return payload


def search_fix_knowledge(query: str, *, limit: int = DEFAULT_FIX_LIMIT) -> List[Dict[str, Any]]:
    docs = _load_kb_docs("fixes")
    return _search_docs(
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
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "after": _truncate(after, 6000),
        "before": _truncate(before, 6000),
        "created_at": _iso_now(),
        "kind": "code_pattern",
        "metadata": metadata or {},
        "pattern": _truncate(pattern, 1000),
        "schema_version": 1,
        "summary": _truncate(summary, 4000),
    }
    path = _write_kb_doc("patterns", "pattern", payload)
    payload["_path"] = str(path)
    return payload


def search_code_patterns(query: str, *, limit: int = DEFAULT_PATTERN_LIMIT) -> List[Dict[str, Any]]:
    docs = _load_kb_docs("patterns")
    return _search_docs(
        query,
        docs=docs,
        fields=("pattern", "summary", "before", "after"),
        kind="patterns",
        limit=limit,
    )


def _coverage_candidates(root: Path) -> List[Path]:
    explicit = os.environ.get("XCMAX_COVERAGE_JSON")
    candidates = [Path(explicit).expanduser()] if explicit else []
    candidates.extend(
        [
            root / "FHD" / "coverage.json",
            root / "coverage.json",
            Path.cwd() / "coverage.json",
        ]
    )
    unique: List[Path] = []
    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _load_coverage_modules(root: Path, *, limit: int = 10) -> List[Dict[str, Any]]:
    for path in _coverage_candidates(root):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, dict):
            continue
        modules: List[Dict[str, Any]] = []
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


def _dev_script(root: Path, name: str) -> Optional[str]:
    path = root / "FHD" / "scripts" / "dev" / name
    return str(path) if path.exists() else None


def collect_proactive_signals(*, root: Optional[Path] = None, limit: int = 10) -> Dict[str, Any]:
    """Collect proactive self-evolution task candidates without running heavy jobs."""

    root = root or workspace_root()
    coverage_modules = _load_coverage_modules(root, limit=limit)
    type_debt_script = _dev_script(root, "count_type_debt.py")
    raw_sql_script = _dev_script(root, "count_raw_sql.py")
    coverage_ratchet_script = _dev_script(root, "coverage_ratchet.py")

    candidates: List[Dict[str, Any]] = [
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
    debt_commands: List[str] = []
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

    return {
        "candidates": candidates,
        "coverage_modules": coverage_modules,
        "coverage_ratchet_script": coverage_ratchet_script,
        "root": str(root),
        "raw_sql_script": raw_sql_script,
        "type_debt_script": type_debt_script,
    }


def load_evolution_metrics() -> List[Dict[str, Any]]:
    path = kb_root() / "metrics" / "evolution_metrics.jsonl"
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
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
    week: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metrics_dir = _kb_dir("metrics")
    path = metrics_dir / "evolution_metrics.jsonl"
    payload = {
        "backend_coverage": float(backend_coverage),
        "created_at": _iso_now(),
        "metadata": metadata or {},
        "pytest_passed": int(pytest_passed),
        "type_debt": int(type_debt),
        "week": week or _utc_now().strftime("%G-W%V"),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return payload


def _metric_float(record: Dict[str, Any], key: str) -> Optional[float]:
    try:
        return float(record[key])
    except (KeyError, TypeError, ValueError):
        return None


def _metric_delta(prev: Dict[str, Any], cur: Dict[str, Any]) -> Dict[str, Any]:
    prev_cov = _metric_float(prev, "backend_coverage")
    cur_cov = _metric_float(cur, "backend_coverage")
    prev_passed = _metric_float(prev, "pytest_passed")
    cur_passed = _metric_float(cur, "pytest_passed")
    prev_debt = _metric_float(prev, "type_debt")
    cur_debt = _metric_float(cur, "type_debt")
    coverage_delta = None if prev_cov is None or cur_cov is None else cur_cov - prev_cov
    passed_delta = None if prev_passed is None or cur_passed is None else cur_passed - prev_passed
    debt_delta = None if prev_debt is None or cur_debt is None else cur_debt - prev_debt
    misses: List[str] = []
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


def evaluate_evolution_regression(history: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Pause when the last two week-to-week windows miss evolution targets."""

    if len(history) < 3:
        return {"pause": False, "reason": "insufficient_metrics_history", "windows": []}
    last_three = list(history)[-3:]
    windows = [
        _metric_delta(last_three[0], last_three[1]),
        _metric_delta(last_three[1], last_three[2]),
    ]
    bad_windows = [window for window in windows if window.get("misses")]
    if len(bad_windows) == 2:
        return {
            "pause": True,
            "reason": "two_consecutive_evolution_metric_regressions",
            "windows": windows,
        }
    return {"pause": False, "reason": "metrics_not_regressing_consecutively", "windows": windows}


def evolution_metrics_gate() -> Dict[str, Any]:
    history = load_evolution_metrics()
    result = evaluate_evolution_regression(history)
    return {
        **result,
        "history_count": len(history),
        "metrics_path": str(kb_root() / "metrics" / "evolution_metrics.jsonl"),
    }


def _knowledge_query(evaluation: Dict[str, Any], memory: Dict[str, Any]) -> str:
    payload = {
        "gaps": evaluation.get("gaps"),
        "incident_count": evaluation.get("incident_count"),
        "incident_signals": evaluation.get("incident_signals"),
        "last_policy_decision": memory.get("last_policy_decision") if isinstance(memory, dict) else None,
        "open_items": (memory.get("open_items") if isinstance(memory, dict) else [])[-8:]
        if isinstance(memory.get("open_items") if isinstance(memory, dict) else [], list)
        else [],
        "recent_runs": (memory.get("recent_runs") if isinstance(memory, dict) else [])[-5:]
        if isinstance(memory.get("recent_runs") if isinstance(memory, dict) else [], list)
        else [],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def build_self_evolution_context(
    *, run_id: str, evaluation: Dict[str, Any], memory: Dict[str, Any]
) -> Dict[str, Any]:
    query = _knowledge_query(evaluation, memory)
    proactive = collect_proactive_signals()
    fix_hits = search_fix_knowledge(query, limit=3)
    pattern_hits = search_code_patterns(query, limit=5)
    try:
        from modstore_server.self_evolution_kb_redisvl import status as redisvl_status

        kb_backend_status = redisvl_status()
    except Exception as exc:
        kb_backend_status = {
            "backend": "redisvl",
            "error": str(exc)[:500],
            "ready": False,
        }
    context = {
        "fix_knowledge_hits": fix_hits,
        "kb_root": str(kb_root()),
        "kb_search": {
            "engine": "redisvl_primary_with_fhd_rag_lexical_fallback",
            "fix_hit_count": len(fix_hits),
            "pattern_hit_count": len(pattern_hits),
            "redisvl_status": kb_backend_status,
        },
        "metrics_gate": evolution_metrics_gate(),
        "pattern_hits": pattern_hits,
        "proactive_signals": proactive,
        "query": query[:3000],
        "run_id": run_id,
    }
    return context


def render_self_evolution_context(context: Dict[str, Any]) -> str:
    return json.dumps(context, ensure_ascii=False, sort_keys=True, default=_json_default)[
        :MAX_CONTEXT_TEXT
    ]


def _step_report_text(final: Dict[str, Any]) -> str:
    steps = final.get("steps")
    if not isinstance(steps, list):
        return ""
    reports = []
    for step in steps:
        if isinstance(step, dict) and step.get("report_excerpt"):
            reports.append(f"[{step.get('step')}] {step.get('report_excerpt')}")
    return "\n".join(reports)


def infer_pattern_from_diff(diff_text: str) -> Dict[str, str]:
    lowered = diff_text.lower()
    if "-time.sleep(" in lowered and "+asyncio.sleep(" in lowered:
        return {
            "pattern": "sync_blocking_sleep_to_async_sleep",
            "summary": "Replace blocking time.sleep calls inside async paths with asyncio.sleep.",
        }
    if re.search(r"^-.*except\s*:\s*$", diff_text, re.MULTILINE) and "logger.exception" in lowered:
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


def record_loop_evolution_knowledge(final: Dict[str, Any], gate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    decision = final.get("policy_decision")
    if not isinstance(decision, dict) or decision.get("action") != "auto_merged_low_risk":
        return None
    merge_result = decision.get("merge_result")
    if not isinstance(merge_result, dict):
        return None
    diff_text = str(merge_result.get("diff_excerpt") or "")
    if not diff_text:
        return None

    reports = _step_report_text(final)
    gaps = gate.get("gaps") if isinstance(gate, dict) else None
    symptom = "; ".join(str(item) for item in gaps) if isinstance(gaps, list) and gaps else ""
    if not symptom:
        symptom = str(decision.get("reason") or final.get("status") or "self-maintenance gap")
    root_cause = reports or json.dumps(decision, ensure_ascii=False, sort_keys=True, default=_json_default)
    metadata = {
        "branch": final.get("branch"),
        "changed_files": merge_result.get("changed_files"),
        "merge_commit_sha": merge_result.get("merge_commit_sha"),
        "para_task_id": final.get("para_task_id"),
        "run_id": final.get("run_id"),
    }
    fix_doc = record_fix_knowledge(
        symptom=symptom,
        root_cause=root_cause,
        fix_diff=diff_text,
        applicability_check=(
            "Match the current loop symptom, policy decision, and changed file scope "
            "against this run before applying an equivalent patch."
        ),
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
    pattern_info = infer_pattern_from_diff(diff_text)
    pattern_doc = record_code_pattern(
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
    src_dir: Path,
    kind: str,
    run_id: str,
    existing_docs: Sequence[Dict[str, Any]],
) -> Tuple[int, int]:
    """Scan src_dir for KB JSON of given kind; validate, dedup, and re-record.

    Returns (salvaged_count, skipped_count). Never raises.
    """
    if not src_dir.exists() or not src_dir.is_dir():
        return 0, 0
    salvaged = 0
    skipped = 0
    for path in sorted(src_dir.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            skipped += 1
            continue
        if not isinstance(payload, dict):
            skipped += 1
            continue
        try:
            validate_kb_payload(kind, payload)
        except ValueError:
            skipped += 1
            continue
        if kind == "fixes":
            symptom = str(payload.get("symptom") or "")
            root_cause = str(payload.get("root_cause") or "")
            if any(
                str(doc.get("symptom") or "") == symptom
                and str(doc.get("root_cause") or "") == root_cause
                for doc in existing_docs
            ):
                skipped += 1
                continue
            template = payload.get("executable_template") if isinstance(
                payload.get("executable_template"), dict
            ) else {}
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            record_fix_knowledge(
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
        else:  # patterns
            pattern = str(payload.get("pattern") or "")
            summary = str(payload.get("summary") or "")
            if any(
                str(doc.get("pattern") or "") == pattern
                and str(doc.get("summary") or "") == summary
                for doc in existing_docs
            ):
                skipped += 1
                continue
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            record_code_pattern(
                pattern=pattern,
                before=str(payload.get("before") or ""),
                after=str(payload.get("after") or ""),
                summary=summary,
                metadata={**metadata, "salvaged_from": str(path), "salvaged_run_id": run_id},
            )
            salvaged += 1
    return salvaged, skipped


def salvage_kb_from_workspace(para_workspace: Path, run_id: str) -> Dict[str, Any]:
    """Salvage KB JSON files from a para workspace into kb_root.

    Defensive: para_workspace missing / KB dir missing / JSON parse failures
    never raise; they are counted as skipped. Returns a summary dict.
    """
    summary: Dict[str, Any] = {
        "salvaged_fixes": 0,
        "salvaged_patterns": 0,
        "skipped": 0,
        "run_id": run_id,
        "workspace": str(para_workspace),
    }
    try:
        workspace = Path(para_workspace)
    except TypeError:
        return summary
    if not workspace.exists() or not workspace.is_dir():
        return summary

    kb_base = workspace / "FHD" / "XCAGI" / "kb"
    if not kb_base.exists():
        return summary

    existing_fixes = _load_kb_docs("fixes")
    salvaged_fixes, skipped_fixes = _salvage_kb_files(
        src_dir=kb_base / "fixes",
        kind="fixes",
        run_id=run_id,
        existing_docs=existing_fixes,
    )
    existing_patterns = _load_kb_docs("patterns")
    salvaged_patterns, skipped_patterns = _salvage_kb_files(
        src_dir=kb_base / "patterns",
        kind="patterns",
        run_id=run_id,
        existing_docs=existing_patterns,
    )
    summary["salvaged_fixes"] = salvaged_fixes
    summary["salvaged_patterns"] = salvaged_patterns
    summary["skipped"] = skipped_fixes + skipped_patterns
    return summary


__all__ = [
    "build_self_evolution_context",
    "collect_proactive_signals",
    "evolution_metrics_gate",
    "evaluate_evolution_regression",
    "infer_pattern_from_diff",
    "kb_root",
    "record_code_pattern",
    "record_evolution_metrics",
    "record_fix_knowledge",
    "record_loop_evolution_knowledge",
    "render_self_evolution_context",
    "salvage_kb_from_workspace",
    "search_code_patterns",
    "search_fix_knowledge",
    "validate_code_pattern_payload",
    "validate_fix_knowledge_payload",
    "validate_kb_payload",
    "workspace_root",
]
