"""Public-safe projection and atomic publisher for founder autonomy."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.founder_autonomy_support import _as_dict, _as_float, _as_int, _as_list


def build_public_founder_autonomy_projection(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Return the public-safe subset used by the official World Will page.

    Internal run ids, approval subjects, source paths, error messages and
    finance amounts intentionally never cross this boundary.  The public page
    receives the same calculated progress values as the founder cockpit, plus
    only coarse, non-sensitive proof flags and aggregate alignment coverage.
    """

    dimensions: list[dict[str, Any]] = []
    for raw in _as_list(snapshot.get("dimensions")):
        item = _as_dict(raw)
        gaps = _as_list(item.get("gaps"))
        next_gap = _as_dict(gaps[0]).get("label") if gaps else "继续积累运行证据"
        dimensions.append(
            {
                "id": str(item.get("id") or ""),
                "label": str(item.get("label") or ""),
                "target": str(item.get("target") or ""),
                "progress": _as_int(item.get("progress")),
                "remaining": _as_int(item.get("remaining")),
                "status": str(item.get("status") or "early"),
                "status_label": str(item.get("status_label") or "能力早期"),
                "passed_gate_count": _as_int(item.get("passed_gate_count")),
                "total_gate_count": _as_int(item.get("total_gate_count")),
                "next_gap": str(next_gap or "继续积累运行证据"),
            }
        )

    live = _as_dict(snapshot.get("live_summary"))
    truth = _as_dict(snapshot.get("truth_domains"))
    public_truth = {
        str(key): {
            "label": str(_as_dict(value).get("label") or key),
            "available": bool(_as_dict(value).get("available")),
        }
        for key, value in truth.items()
    }
    uncovered_contracts = [
        {
            "action": str(_as_dict(raw).get("action") or "unknown")[:128],
            "source": str(_as_dict(raw).get("source") or "unknown")[:128],
            "count": _as_int(_as_dict(raw).get("count")),
        }
        for raw in _as_list(live.get("prohibited_posthoc_uncovered_contracts"))[:20]
        if _as_int(_as_dict(raw).get("count")) > 0
    ]
    return {
        "schema": "xcagi.public_founder_autonomy/v1",
        "generated_at": str(snapshot.get("generated_at") or datetime.now(UTC).isoformat()),
        "readonly": True,
        "overall_progress": _as_int(snapshot.get("overall_progress")),
        "overall_remaining": _as_int(snapshot.get("overall_remaining")),
        "target_state": "founder_strategic_only",
        "dimensions": dimensions,
        "human_intervention_rare": bool(
            _as_dict(snapshot.get("attention")).get("human_intervention_rare")
        ),
        "proof": {
            "runtime_fresh": bool(live.get("runtime_fresh")),
            "runtime_provenance_ok": bool(live.get("runtime_provenance_ok")),
            "active_gates_ok": bool(live.get("active_gates_ok")),
            "governance_ok": bool(live.get("governance_ok")),
            "deploy_verified": bool(live.get("deploy_verified")),
            "paid_value_verified": bool(live.get("production_value_verified")),
            "paid_delivery_verified": bool(live.get("outcome_verified")),
            "customer_acceptance_verified": bool(live.get("customer_acceptance_verified")),
            "employee_workforce_ready": bool(live.get("employee_workforce_ready")),
            "alignment_posthoc": {
                "status": str(live.get("prohibited_miss_status") or "unknown"),
                "coverage_rate": _as_float(live.get("prohibited_posthoc_coverage_rate")),
                "allow_count": _as_int(live.get("prohibited_posthoc_allow_count")),
                "conclusive_count": _as_int(live.get("prohibited_posthoc_conclusive_count")),
                "uncovered_count": _as_int(live.get("prohibited_posthoc_uncovered_count")),
                "uncovered_contracts": uncovered_contracts,
            },
        },
        "truth_domains": public_truth,
        "note": "官网仅展示脱敏后的证据评分；完整门禁、审批与 veto 细节只在管理端可见。",
    }


def _public_projection_targets(repo_root: Path | None = None) -> list[Path]:
    root = repo_root
    if root is None:
        configured = str(os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
        root = (
            Path(configured).expanduser().resolve()
            if configured
            else Path(__file__).resolve().parents[3]
        )
    company_root = root / "成都修茈科技有限公司"
    targets = [
        company_root / "download-founder-autonomy.json",
        company_root / "MODstore_deploy" / "market" / "public" / "download-founder-autonomy.json",
    ]
    configured_live_roots = [
        item.strip()
        for item in str(os.environ.get("XCMAX_PUBLIC_SITE_LIVE_ROOTS") or "").split(",")
        if item.strip()
    ]
    if not configured_live_roots:
        configured_live_roots = ["/var/lib/xcmax-public"]
    for raw in configured_live_roots:
        try:
            live_root = Path(raw).expanduser().resolve()
        except OSError:
            continue
        if live_root.is_dir():
            targets.append(live_root / "download-founder-autonomy.json")
    return list(dict.fromkeys(targets))


def write_public_founder_autonomy_projection(
    snapshot: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Atomically publish the sanitized scorecard to official-site targets."""

    payload = build_public_founder_autonomy_projection(snapshot)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    written: list[str] = []
    errors: list[str] = []
    for target in _public_projection_targets(repo_root):
        if not target.parent.is_dir():
            continue
        tmp = target.with_suffix(f"{target.suffix}.tmp")
        try:
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(target)
            written.append(str(target))
        except OSError as exc:
            errors.append(f"{target.name}:{exc.__class__.__name__}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    return {
        "ok": bool(written) and not errors,
        "written": written,
        "errors": errors,
        "payload": payload,
    }
