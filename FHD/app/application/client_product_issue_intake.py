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
_EXPLICIT_INTAKE_RE = re.compile(
    r"(提交|上报|反馈|建|创).{0,24}(产品|软件|功能|缺陷).{0,12}(问题|工单|故障|缺陷)"
)
_PLAIN_INTAKE_RE = re.compile(
    r"(?:提交|上报|反馈|建立?|创建|提|登记|报|记)(?:一?[个张条项]|一下)?(?:客服|问题|反馈)?工单"
    r"|(?:刚才|刚|上面|这个|这项|那个).{0,12}(?:记|登记)一?单"
    r"|(?:也给我|也帮我)开一张(?:吧|[。！!\s])*$"
)
_SOFTWARE_CONTEXT_RE = re.compile(
    r"软件|页面|界面|后台|客户端|桌面|功能|模块|交付中心|每日摘要|客服|菜单|侧栏|样式|显示|跨端|审计|自动化|审批|看板|图谱|管理端|市场总览"
)
_IMAGE_DATA_URL = re.compile(r"(?i)^data:image/[\w.+-]+;base64,")


def looks_like_issue_report(message: str) -> bool:
    return not _manufacturing_intake(message) and bool(
        _REPORT_RE.search(str(message or "")) or _plain_intake_match(message)
    )


def _manufacturing_intake(message: str) -> bool:
    return bool(re.search(r"生产|制造|车间|排产|加工|装配", message or "")) and not bool(
        re.search(r"软件|页面|界面|后台|客户端|菜单|侧栏|样式|显示|图谱|看板|列表", message or "")
    )


def _plain_intake_match(message: str):
    # Manufacturing work orders remain business actions, even with a generic title.
    if _manufacturing_intake(message):
        return None
    match = _PLAIN_INTAKE_RE.search(message or "")
    # Asking how to submit is a usage question, not consent to create a ticket.
    if match and not re.search(
        r"(?:怎么|如何|哪里|在哪|能否|能不能|不要|不用|别|无需|不必|不想|暂不|不是要|已经|已)[^。！？\n]{0,12}$",
        message[: match.start()],
    ):
        return match
    return None


def _bare_intake(message: str) -> bool:
    remainder = _PLAIN_INTAKE_RE.sub("", message)
    for prefix in (
        "我要",
        "我想",
        "请",
        "麻烦",
        "帮我",
        "给我",
        "替我",
        "把",
        "按",
        "就",
        "刚才",
        "刚",
        "说的",
        "上面",
        "上述",
        "这个",
        "这项",
        "那个",
        "那项",
        "问题",
        "反馈",
        "的",
    ):
        remainder = remainder.replace(prefix, "")
    return not re.sub(r"[\s，。！？：；,.!?;:]", "", remainder)


def report_message_with_context(message: str, context: dict[str, Any]) -> str:
    """Use only this request's recent customer words for a bare follow-up request."""
    if not _plain_intake_match(message) or not _bare_intake(message):
        return message
    recent = context.get("recent_messages")
    for item in reversed(recent[-6:] if isinstance(recent, list) else []):
        if not isinstance(item, dict):
            continue
        if any(
            item.get(key) is not None and str(item[key]) != str(context.get(key) or "")
            for key in ("conversation_id", "session_id", "actor_id", "local_user_id")
        ):
            continue
        content = str(item.get("content") or "").strip()[:3000]
        if item.get("role") == "assistant" and re.search(
            r"(?:工单.*已(?:受理|登记)|已(?:受理|登记).*工单)", content
        ):
            break
        if item.get("role") != "user" or not content or content == message.strip():
            continue
        if not (_plain_intake_match(content) or _manufacturing_intake(content)) and (
            _REPORT_RE.search(content) or _SOFTWARE_CONTEXT_RE.search(content)
        ):
            return f"此前客户说明：{content}\n本轮客户要求：{message}"
        break
    return message


def _attached_screenshots(attachments: Any) -> list[bytes]:
    """Decode the images the customer attached to the report message."""
    images: list[bytes] = []
    for item in attachments if isinstance(attachments, list) else []:
        url = str(item.get("data_url") or "") if isinstance(item, dict) else ""
        if match := _IMAGE_DATA_URL.match(url):
            try:
                images.append(base64.b64decode(url[match.end() :], validate=True))
            except ValueError:
                logger.info("customer screenshot is not valid base64")
    return images[:6]


def classify_explicit_report(message: str) -> dict[str, Any] | None:
    """Recognize an explicit defect report without requiring a model or credentials."""
    if _manufacturing_intake(message):
        return None
    fields = dict.fromkeys(("expected", "actual"), "")
    for key in fields:
        label = "期望(?:结果|行为)?" if key == "expected" else "实际(?:结果|表现|行为)?"
        if match := re.search(label + "[：:]", message):
            value = message[match.end() :].lstrip()
            fields[key] = re.split(r"[。；;\n]", value, maxsplit=1)[0][:1000]
    plain = _plain_intake_match(message)
    explicit = bool(_EXPLICIT_INTAKE_RE.search(message or "") or plain)
    if explicit or (_REPORT_RE.search(message) and all(fields.values())):
        return {
            "type": "product_defect",
            "confidence": 0.95 if explicit else 0.9,
            **fields,
            "missing_evidence": (["issue_description"] if plain and _bare_intake(message) else [])
            + [f"{key}_behavior" for key, value in fields.items() if not value],
        }
    return None


def classify_report(client: Any, message: str, assistant_reply: str) -> dict[str, Any] | None:
    explicit = classify_explicit_report(message)
    if explicit is not None:
        return explicit
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
                        {
                            "customer": str(message)[:8000],
                            "assistant": str(assistant_reply)[:8000],
                        },
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
    attachments: Any = None,
) -> dict[str, Any]:
    """Create one tenant-scoped Work Order and route its redacted bundle to Owner intake."""
    if triage.get("type") != "product_defect" or triage.get("confidence", 0) < 0.8:
        return {"state": "not_confirmed"}
    missing = list(triage.get("missing_evidence") or [])
    missing.extend(f"{key}_behavior" for key in ("expected", "actual") if not triage.get(key))
    if missing:
        return await _receive_pending_report(request, tenant_id, customer_message, missing)
    from app.application.desktop_delivery_receipt import desktop_installation_id
    from app.build_identity import build_identity
    from app.desktop_runtime.support_bundle import build_evidence_ref
    from app.fastapi_routes.private_mod_delivery_context import (
        _private_delivery_market_token,
    )

    evidence = build_evidence_ref(screenshots=_attached_screenshots(attachments))
    if not evidence:
        return {"state": "NEEDS_MORE_EVIDENCE", "missing_evidence": ["support_bundle"]}
    bundle_path = Path(str(evidence.get("path") or ""))
    try:
        bundle = bundle_path.read_bytes()
    except OSError:
        return {"state": "NEEDS_MORE_EVIDENCE", "missing_evidence": ["support_bundle"]}
    if len(bundle) > 256_000 or hashlib.sha256(bundle).hexdigest() != evidence.get("sha256"):
        return {
            "state": "NEEDS_MORE_EVIDENCE",
            "missing_evidence": ["valid_support_bundle"],
        }
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
    # 市场要求非空版本；未打包/身份损坏时仍可建单。
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
    # 同一需求正文保持稳定；补报附件及运行身份由接收端单独持久化。
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
        # 回查只证明原工单存在，不能证明本次附件已保存。
        logger.info("client product issue intake not replayed; falling back to lookup")
    if (
        result.get("success") is not True
        or not result.get("ticket_id")
        or not result.get("ticket_no")
    ):
        existing = await _existing_ticket_for_source_ref(token, wo_id)
        if not existing:
            return {"state": "OWNER_ROUTE_UNAVAILABLE", "work_order_id": wo_id}
        result = {**existing, "success": True}
    saved = (
        result.get("support_bundle_saved") is True
        and result.get("support_bundle_sha256") == evidence["sha256"]
    )
    return {
        "state": "ROUTED",
        "work_order_id": wo_id,
        "owner_ticket_id": result["ticket_id"],
        "owner_ticket_no": result["ticket_no"],
        "support_bundle_saved": saved,
        "support_bundle_sha256": evidence["sha256"] if saved else "",
        **(
            {"screenshots": evidence["screenshots"]}
            if saved and evidence.get("screenshots")
            else {}
        ),
    }


async def _receive_pending_report(
    request: Any, tenant_id: int | None, message: str, missing: list[str]
) -> dict[str, Any]:
    """Use normal authenticated intake without inventing Work Order evidence."""
    from app.fastapi_routes.private_mod_delivery_context import (
        _private_delivery_market_token,
    )

    token = await _private_delivery_market_token(request)
    if not token:
        return {"state": "OWNER_ROUTE_UNAVAILABLE"}
    reason = message.strip()[:1000]
    digest = hashlib.sha256(
        json.dumps([f"tenant:{int(tenant_id or 0)}", message.strip()], ensure_ascii=False).encode()
    ).hexdigest()
    source_ref = f"client-pending:{digest}"
    try:
        result = await custom_delivery_remote_json(
            token,
            "/api/customer-service/issues/intake",
            method="POST",
            payload={
                "source": "customer_feedback",
                "source_ref": source_ref,
                "title": f"客户端产品问题 · {reason[:100]}",
                "description": f"客户原话：{reason}",
                "issue_domain": "platform",
                "acceptance_criteria": "在原工单补充期望、实际与诊断证据后复现验证。",
            },
        )
    except (RuntimeError, ConnectionError):
        result = {}
    if (
        result.get("success") is not True
        or not result.get("ticket_id")
        or not result.get("ticket_no")
    ):
        result = await _existing_ticket_for_source_ref(token, source_ref) or {}
    if not result.get("ticket_id") or not result.get("ticket_no"):
        return {"state": "OWNER_ROUTE_UNAVAILABLE"}
    return {
        "state": "RECEIVED",
        "owner_ticket_id": result["ticket_id"],
        "owner_ticket_no": result["ticket_no"],
        "missing_evidence": sorted(set(missing)),
    }


async def _existing_ticket_for_source_ref(token: str, source_ref: str) -> dict[str, Any] | None:
    """Read back an existing formal ticket within the authenticated account."""
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
        if str(evidence.get("source_ref") or "") != source_ref:
            continue
        ticket_id, ticket_no = item.get("id"), str(item.get("ticket_no") or "")
        if ticket_id is None or not ticket_no:
            continue
        return {"ticket_id": ticket_id, "ticket_no": ticket_no}
    return None
