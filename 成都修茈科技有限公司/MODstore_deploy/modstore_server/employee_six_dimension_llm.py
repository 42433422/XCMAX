"""六维质检：调用 hex-quality-assessor（或平台 LLM 回退）做深度评分。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modstore_server.employee_six_dimension import (
    DIMENSION_LABELS_ZH,
    SIX_DIMENSION_KEYS,
    build_six_dimension_report_from_llm_dimensions,
)

logger = logging.getLogger(__name__)

HEX_QUALITY_ASSESSOR_ID = "hex-quality-assessor"

_LLM_SYSTEM = """你是 MODstore 六维质检员工。根据被测员工包材料，输出六维 JSON 评分（0–100）。

六维键名（必须全部出现）：
requirement_clarity, pack_compliance, code_robustness, executability, workflow_connectivity, domain_delivery

仅输出一个 JSON 对象：
{"dimensions":{"requirement_clarity":{"score":0,"reasons":["…"]},…},"summary":"…","recommend_release":false}
不要 markdown 围栏。"""


def six_dim_llm_enabled(*, explicit: bool = False) -> bool:
    if explicit:
        return True
    flag = (os.environ.get("MODSTORE_SIX_DIM_LLM") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    try:
        from modstore_server.services.llm import resolve_platform_bench_llm

        prov, mdl = resolve_platform_bench_llm()
        return bool(prov and mdl)
    except Exception:  # noqa: BLE001
        return False


def _strip_fence(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            return "\n".join(lines[1:-1]).strip()
    return raw


def parse_llm_six_dimension_json(text: str) -> Optional[Dict[str, Any]]:
    raw = _strip_fence(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        i, j = raw.find("{"), raw.rfind("}")
        if i < 0 or j <= i:
            return None
        try:
            data = json.loads(raw[i : j + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    dims = data.get("dimensions")
    if not isinstance(dims, dict):
        return None
    parsed: Dict[str, Dict[str, Any]] = {}
    for key in SIX_DIMENSION_KEYS:
        entry = dims.get(key)
        if not isinstance(entry, dict):
            return None
        try:
            score = int(entry.get("score", 0))
        except (TypeError, ValueError):
            return None
        reasons = entry.get("reasons")
        if not isinstance(reasons, list):
            reasons = []
        parsed[key] = {
            "score": max(0, min(100, score)),
            "reasons": [str(r)[:200] for r in reasons[:4] if str(r).strip()],
        }
    return {
        "dimensions": parsed,
        "summary": str(data.get("summary") or "").strip()[:500],
        "recommend_release": bool(data.get("recommend_release")),
    }


def _manifest_excerpt(pack_dir: Path, limit: int = 3500) -> Dict[str, Any]:
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        return {"error": "manifest.json missing"}
    try:
        mf = json.loads(mf_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": str(exc)[:200]}
    if not isinstance(mf, dict):
        return {"error": "invalid manifest"}
    ident = mf.get("identity") if isinstance(mf.get("identity"), dict) else {}
    actions = mf.get("actions") if isinstance(mf.get("actions"), dict) else {}
    handlers = actions.get("handlers") or actions.get("actions", {}).get("handlers")
    return {
        "id": str(mf.get("id") or ident.get("id") or "").strip(),
        "name": str(mf.get("name") or ident.get("name") or "").strip()[:200],
        "description": str(mf.get("description") or ident.get("description") or "").strip()[:800],
        "artifact": str(mf.get("artifact") or "").strip(),
        "handlers": handlers if isinstance(handlers, list) else [],
        "capabilities_count": (
            len(mf.get("capabilities") or []) if isinstance(mf.get("capabilities"), list) else 0
        ),
        "skills_count": len(mf.get("skills") or []) if isinstance(mf.get("skills"), list) else 0,
    }


def _mod_checks_summary(mod_sandbox: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(mod_sandbox, dict):
        return []
    out: List[Dict[str, Any]] = []
    for c in mod_sandbox.get("checks") or []:
        if isinstance(c, dict):
            out.append(
                {
                    "id": str(c.get("id") or "")[:80],
                    "ok": bool(c.get("ok")),
                    "message": str(c.get("message") or c.get("detail") or "")[:160],
                }
            )
    return out[:20]


def build_assessment_payload(
    *,
    target_employee_id: str,
    pack_dir: Path,
    pipeline_label: str,
    baseline_report: Dict[str, Any],
    routing_brief: str = "",
    validate_errors: Optional[List[str]] = None,
    mod_sandbox: Optional[Dict[str, Any]] = None,
    bench_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    baseline_dims = {}
    for k in SIX_DIMENSION_KEYS:
        ent = (baseline_report.get("dimensions") or {}).get(k)
        if isinstance(ent, dict):
            baseline_dims[k] = {
                "score": ent.get("score"),
                "grade": ent.get("grade"),
                "reasons": (ent.get("reasons") or [])[:3],
            }
    return {
        "action": "six_dim_assessment",
        "target_employee_id": target_employee_id,
        "pipeline_label": pipeline_label,
        "routing_brief": (routing_brief or "")[:1200],
        "manifest_excerpt": _manifest_excerpt(pack_dir),
        "validate_errors": [str(x)[:200] for x in (validate_errors or [])[:12]],
        "mod_checks_summary": _mod_checks_summary(mod_sandbox),
        "baseline_report": {
            "overall_score": baseline_report.get("overall_score"),
            "overall_grade": baseline_report.get("overall_grade"),
            "dimensions": baseline_dims,
        },
        "bench_summary": bench_summary or {},
        "dimension_labels_zh": DIMENSION_LABELS_ZH,
    }


async def _call_platform_llm_direct(
    payload: Dict[str, Any], provider: str, model: str
) -> Tuple[Optional[str], Optional[str]]:
    from modstore_server.services.llm import chat_dispatch_via_platform_only

    user_msg = json.dumps(payload, ensure_ascii=False)
    result = await chat_dispatch_via_platform_only(
        provider,
        model,
        [{"role": "system", "content": _LLM_SYSTEM}, {"role": "user", "content": user_msg}],
        max_tokens=4000,
    )
    if not result.get("ok"):
        return None, str(result.get("error") or "platform LLM failed")
    return str(result.get("content") or ""), None


async def _call_hex_quality_assessor_employee(
    payload: Dict[str, Any],
    *,
    user_id: int = 0,
    bench_llm_override: Optional[Tuple[str, str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    from modstore_server.employee_executor import execute_employee_task
    from modstore_server.mod_scaffold_runner import materialize_employee_pack_if_missing

    materialize_employee_pack_if_missing(HEX_QUALITY_ASSESSOR_ID)
    task = json.dumps(payload, ensure_ascii=False)
    try:
        result = await asyncio.to_thread(
            execute_employee_task,
            HEX_QUALITY_ASSESSOR_ID,
            task,
            {"assessment": payload},
            user_id,
            bench_llm_override=bench_llm_override,
        )
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)[:300]

    if not isinstance(result, dict):
        return None, "assessor returned non-dict"
    if result.get("status") == "blocked_by_risk_gate":
        return None, str(result.get("reason") or "blocked by risk gate")[:200]

    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    text = str(result.get("reasoning_excerpt") or "")
    outputs = inner.get("outputs") if isinstance(inner, dict) else None
    if isinstance(outputs, list):
        for out in outputs:
            if isinstance(out, dict) and out.get("output"):
                text = str(out["output"])
                break
    if not text.strip() and isinstance(inner, dict):
        text = str(inner.get("reasoning") or inner.get("output") or "")
    if not text.strip():
        return None, "assessor empty output"
    return text, None


async def enrich_six_dimension_report_with_llm(
    baseline_report: Dict[str, Any],
    *,
    pack_dir: Path,
    target_employee_id: str,
    pipeline_label: str,
    routing_brief: str = "",
    validate_errors: Optional[List[str]] = None,
    mod_sandbox: Optional[Dict[str, Any]] = None,
    bench_summary: Optional[Dict[str, Any]] = None,
    user_id: int = 0,
    bench_llm_override: Optional[Tuple[str, str]] = None,
    require_llm: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """在规则基线上调用 LLM 六维评估；失败时回退基线。"""
    meta: Dict[str, Any] = {
        "scoring_source": "deterministic",
        "llm_attempted": False,
        "assessor_id": HEX_QUALITY_ASSESSOR_ID,
    }

    if not six_dim_llm_enabled(explicit=require_llm):
        return dict(baseline_report), meta

    from modstore_server.services.llm import resolve_platform_bench_llm

    prov, mdl = bench_llm_override or resolve_platform_bench_llm()
    if not prov or not mdl:
        meta["llm_error"] = "platform LLM not configured"
        if require_llm:
            raise RuntimeError(meta["llm_error"])
        return dict(baseline_report), meta

    meta["llm_attempted"] = True
    meta["provider"] = prov
    meta["model"] = mdl

    payload = build_assessment_payload(
        target_employee_id=target_employee_id,
        pack_dir=pack_dir,
        pipeline_label=pipeline_label,
        baseline_report=baseline_report,
        routing_brief=routing_brief,
        validate_errors=validate_errors,
        mod_sandbox=mod_sandbox,
        bench_summary=bench_summary,
    )

    raw_text, err = await _call_hex_quality_assessor_employee(
        payload,
        user_id=user_id,
        bench_llm_override=(prov, mdl),
    )
    if err or not raw_text:
        raw_text, direct_err = await _call_platform_llm_direct(payload, prov, mdl)
        if direct_err or not raw_text:
            meta["llm_error"] = err or direct_err or "empty LLM response"
            if require_llm:
                raise RuntimeError(meta["llm_error"])
            return dict(baseline_report), meta
        meta["assessor_fallback"] = "platform_direct"

    parsed = parse_llm_six_dimension_json(raw_text)
    if not parsed:
        meta["llm_error"] = "failed to parse six-dimension JSON"
        if require_llm:
            raise RuntimeError(meta["llm_error"])
        return dict(baseline_report), meta

    report = build_six_dimension_report_from_llm_dimensions(
        parsed["dimensions"],
        pipeline_label=pipeline_label,
        baseline_report=baseline_report,
    )
    report["llm_summary"] = parsed.get("summary") or ""
    report["recommend_release"] = parsed.get("recommend_release")
    report["scoring_source"] = "llm"
    meta["scoring_source"] = "llm"
    meta["recommend_release"] = parsed.get("recommend_release")
    return report, meta
