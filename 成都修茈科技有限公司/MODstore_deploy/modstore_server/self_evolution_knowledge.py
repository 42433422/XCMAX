# isort: skip_file
"""Self-evolution knowledge base and proactive task signals.

The loop stores durable, file-backed knowledge under FHD/XCAGI/kb so later runs
can retrieve known fixes and approved code patterns before asking employees to
reason from scratch.
"""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS

import json
import os
import re
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional as Optional, Sequence, Tuple

DEFAULT_FIX_LIMIT = 5
DEFAULT_PATTERN_LIMIT = 8
MAX_DOC_TEXT = 20000
MAX_CONTEXT_TEXT = 12000


def _utc_now() -> datetime:
    return datetime.now(UTC)


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
        json.dump(
            payload,
            fh,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
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
    if not isinstance(required_tests, list) or not all(
        isinstance(item, str) for item in required_tests
    ):
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


def knowledge_inventory() -> Dict[str, Any]:
    """Return counts of schema-valid reusable knowledge documents.

    The founder score consumes these counts as evidence.  Invalid or unreadable
    JSON is reported separately and never counted as reusable knowledge.
    """

    counts: Dict[str, int] = {}
    invalid_count = 0
    for kind, count_key in (("fixes", "fix_count"), ("patterns", "pattern_count")):
        valid_count = 0
        directory = kb_root() / kind
        if directory.exists():
            for path in sorted(directory.glob("*.json")):
                try:
                    with path.open("r", encoding="utf-8") as fh:
                        payload = json.load(fh)
                    if not isinstance(payload, dict):
                        raise _validation_error(f"{kind} document must be an object")
                    validate_kb_payload(kind, payload)
                except (OSError, json.JSONDecodeError, ValueError):
                    invalid_count += 1
                    continue
                valid_count += 1
        counts[count_key] = valid_count
    total = counts.get("fix_count", 0) + counts.get("pattern_count", 0)
    return {
        **counts,
        "invalid_count": invalid_count,
        "total": total,
    }


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
    except RECOVERABLE_ERRORS:
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
        if rag_text and any(str(doc.get(field) or "")[:80] in rag_text for field in fields):
            score += 0.75
        if score > 0:
            ranked.append(
                (
                    score,
                    {**doc, "score": round(score, 4), "rag_chunks": rag_chunks[:limit]},
                )
            )
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
    except RECOVERABLE_ERRORS as exc:
        return [], {
            "backend": "redisvl",
            "error": str(exc)[:500],
            "ready": False,
        }


from modstore_server.self_evolution_operations import (  # noqa: E402
    _coverage_candidates as _coverage_candidates,
    _dev_script as _dev_script,
    _knowledge_query as _knowledge_query,
    _load_coverage_modules as _load_coverage_modules,
    _metric_delta as _metric_delta,
    _metric_float as _metric_float,
    _salvage_kb_files as _salvage_kb_files,
    _search_docs as _search_docs,
    _step_report_text as _step_report_text,
    build_self_evolution_context as build_self_evolution_context,
    collect_proactive_signals as collect_proactive_signals,
    evaluate_evolution_regression as evaluate_evolution_regression,
    evolution_metrics_gate as evolution_metrics_gate,
    infer_pattern_from_diff as infer_pattern_from_diff,
    load_evolution_metrics as load_evolution_metrics,
    record_code_pattern as record_code_pattern,
    record_evolution_metrics as record_evolution_metrics,
    record_fix_knowledge as record_fix_knowledge,
    record_loop_evolution_knowledge as record_loop_evolution_knowledge,
    render_self_evolution_context as render_self_evolution_context,
    salvage_kb_from_workspace as salvage_kb_from_workspace,
    search_code_patterns as search_code_patterns,
    search_fix_knowledge as search_fix_knowledge,
)

__all__ = [
    "build_self_evolution_context",
    "collect_proactive_signals",
    "evolution_metrics_gate",
    "evaluate_evolution_regression",
    "infer_pattern_from_diff",
    "kb_root",
    "knowledge_inventory",
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
