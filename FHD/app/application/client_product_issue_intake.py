"""Classify and route confirmed product defects reported in client chat."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import platform
import re
from pathlib import Path
from typing import Any

from app.application.private_mod_delivery_artifacts import custom_delivery_remote_json
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_REPORT_RE = re.compile(
    r"(?i)(问题|故障|缺陷|报错|失败|不能用(?![^。！？\n]{0,40}(?:代替|替代))|没反应|异常|crash|bug)"
)


def looks_like_issue_report(message: str) -> bool:
    return bool(_REPORT_RE.search(str(message or "")))


def classify_report(client: Any, message: str, assistant_reply: str) -> dict[str, Any] | None:
    expected = re.search(r"期望[：:]\s*(.+?)(?:[。；;\n]|$)", message)
    actual = re.search(r"实际[：:]\s*(.+?)(?:[。；;\n]|$)", message)
    if expected and actual and _REPORT_RE.search(message):
        return {
            "type": "product_defect",
            "confidence": 0.9,
            "expected": expected[1][:1000],
            "actual": actual[1][:1000],
            "missing_evidence": [],
        }
    try:
        response = client.chat.completions.create(
            model=client.default_model,
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "依据客户原话及答复（无答复时只看原话）分类，只输出 JSON："
                        '{"type":"usage_question|product_defect|uncertain","confidence":0到1,'
                        '"expected":"...","actual":"...","missing_evidence":["..."]}。'
                        "咨询归 usage_question；明确软件行为错误才归 product_defect；缺失信息列入 missing_evidence。不要补造事实。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"customer": str(message)[:8000], "assistant": str(assistant_reply)[:8000]},
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        raw = response.choices[0].message.content
        triage = json.loads(raw) if isinstance(raw, str) else {}
        confidence = float(triage.get("confidence") or 0)
        if triage.get("type") not in {"usage_question", "product_defect", "uncertain"}:
            return None
        triage.update(
            confidence=max(0.0, min(confidence, 1.0)),
            expected=str(triage.get("expected") or "")[:1000],
            actual=str(triage.get("actual") or "")[:1000],
            missing_evidence=[str(x)[:300] for x in triage.get("missing_evidence", [])[:10]],
        )
        return triage
    except RECOVERABLE_ERRORS + (IndexError, AttributeError, TypeError):
        logger.info("client issue classification unavailable", exc_info=True)
        return None


async def submit_product_issue(
    *,
    request: Any,
    tenant_id: int | None,
    customer_message: str,
    triage: dict[str, Any],
) -> dict[str, Any]:
    """Create one tenant-scoped Work Order and route its redacted bundle to Owner intake."""
    if triage.get("type") != "product_defect" or triage.get("confidence", 0) < 0.8:
        return {"state": "not_confirmed"}
    missing = list(triage.get("missing_evidence") or [])
    if not triage.get("expected"):
        missing.append("expected_behavior")
    if not triage.get("actual"):
        missing.append("actual_behavior")
    if missing:
        return {"state": "NEEDS_MORE_EVIDENCE", "missing_evidence": missing}
    from app.application.desktop_delivery_receipt import desktop_installation_id
    from app.build_identity import build_identity
    from app.desktop_runtime.support_bundle import build_evidence_ref
    from app.fastapi_routes.private_mod_delivery_context import _private_delivery_market_token

    evidence = build_evidence_ref()
    if not evidence:
        return {"state": "NEEDS_MORE_EVIDENCE", "missing_evidence": ["support_bundle"]}
    bundle_path = Path(str(evidence.get("path") or ""))
    try:
        bundle = bundle_path.read_bytes()
    except OSError:
        return {"state": "NEEDS_MORE_EVIDENCE", "missing_evidence": ["support_bundle"]}
    if len(bundle) > 256_000 or hashlib.sha256(bundle).hexdigest() != evidence.get("sha256"):
        return {"state": "NEEDS_MORE_EVIDENCE", "missing_evidence": ["valid_support_bundle"]}
    scope = f"tenant:{int(tenant_id or 0)}"
    digest = hashlib.sha256(
        json.dumps([scope, customer_message.strip()], ensure_ascii=False).encode()
    ).hexdigest()
    reason = customer_message.strip()[:1000]
    token = await _private_delivery_market_token(request)
    if not token:
        return {"state": "OWNER_ROUTE_UNAVAILABLE"}
    identity = build_identity()
    client_id = desktop_installation_id()
    # 市场端建单接口要求 product_version 非空且至少 1 字符。未打包运行、构建身份
    # 文件缺失或损坏的客户端拿不到版本号时也必须能建单，否则客户上报缺陷只会得到
    # 「受理服务尚未送达」，问题再次被挡在闭环之外。
    version_label = identity.get("product_version") or "unknown"
    context = {
        "expected": triage["expected"],
        "actual": triage["actual"],
        "confidence": triage["confidence"],
        "support_bundle_sha256": evidence["sha256"],
        "client_instance_id": client_id,
        "product_version": version_label,
        "git_sha": identity.get("git_sha", ""),
        "platform": platform.platform(),
    }
    candidate = await custom_delivery_remote_json(
        token,
        "/api/work-orders/customer-candidate",
        method="POST",
        payload={
            "source": "client_ai_product_issue",
            "dedup_key": f"client-ai:{digest}",
            "reason": "product_defect",
            **context,
        },
    )
    wo_id = str(candidate.get("wo_id") or "")
    if not wo_id:
        return {"state": "OWNER_ROUTE_UNAVAILABLE"}
    title = f"客户端产品缺陷 · {reason[:100]}"
    # description 是市场端判定「同一需求标识是否绑定同一内容」的一部分：同一工单
    # 重复上报（客户重测、补报）必须原样复用，否则会被判成内容不同而 409，客户
    # 永远拿不到工单编号。每次都变的支持包摘要只经 support_bundle_sha256 字段传递，
    # 市场端也明确把它排除在该身份判定之外。
    description = (
        f"work_order_id：{wo_id}\n客户原话：{reason}\n"
        f"预期：{triage['expected']}\n实际：{triage['actual']}"
    )
    result: dict[str, Any] = {}
    try:
        result = await custom_delivery_remote_json(
            token,
            "/api/customer-service/issues/intake",
            method="POST",
            payload={
                "source": "customer_feedback",
                "source_ref": wo_id,
                "title": title,
                "description": description,
                "issue_domain": "platform",
                "acceptance_criteria": "使用相同客户端操作重现并验证原问题。",
                "work_order_id": wo_id,
                "support_bundle_sha256": evidence["sha256"],
                "support_bundle_base64": base64.b64encode(bundle).decode("ascii"),
                "customer_instance_id": client_id,
                "product_version": version_label,
                "git_sha": identity.get("git_sha", ""),
            },
        )
    except (RuntimeError, ConnectionError):
        # 该 Work Order 已有受理工单但内容摘要不同（客户端格式升级、客户补报），
        # 市场会以 409 拒绝而不是重放。此时必须回查已有工单并复用其编号，否则
        # 客户重复上报同一问题只会得到「受理服务尚未送达」。
        logger.info("client product issue intake not replayed; falling back to lookup")
    if (
        result.get("success") is not True
        or not result.get("ticket_id")
        or not result.get("ticket_no")
    ):
        existing = await _existing_ticket_for_work_order(token, wo_id)
        if not existing:
            return {"state": "OWNER_ROUTE_UNAVAILABLE", "work_order_id": wo_id}
        result = {**existing, "success": True}
    return {
        "state": "ROUTED",
        "work_order_id": wo_id,
        "owner_ticket_id": result["ticket_id"],
        "owner_ticket_no": result["ticket_no"],
        "support_bundle_sha256": evidence["sha256"],
    }


async def _existing_ticket_for_work_order(token: str, wo_id: str) -> dict[str, Any] | None:
    """回查当前账号在该 Work Order 下已有的受理工单编号。"""
    try:
        listing = await custom_delivery_remote_json(token, "/api/customer-service/tickets?limit=50")
    except (RuntimeError, ConnectionError):
        logger.info("client issue ticket lookup unavailable", exc_info=True)
        return None
    for item in listing.get("items") or []:
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence")
        if not isinstance(evidence, dict):
            continue
        if str(evidence.get("source_ref") or "") != wo_id:
            continue
        ticket_id, ticket_no = item.get("id"), str(item.get("ticket_no") or "")
        if ticket_id is None or not ticket_no:
            continue
        return {"ticket_id": ticket_id, "ticket_no": ticket_no}
    return None
