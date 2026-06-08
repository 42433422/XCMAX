"""LLM 模型闸门：目录校验、L2 定价策略、预授权倍率；L1 探针与能力表维护。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modstore_server.llm_catalog import get_models_for_provider
from modstore_server.llm_chat_proxy import chat_dispatch
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    resolve_api_key,
    resolve_base_url,
)
from modstore_server.llm_model_taxonomy import classify_model
from modstore_server.models import AiModelPrice, LlmModelCapability

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def platform_catalog_gate_enabled() -> bool:
    """平台代付密钥：要求 model 出现在当前用户目录拉取结果中。"""
    return _env_bool("MODSTORE_LLM_PLATFORM_CATALOG_GATE", True)


def byok_catalog_gate_enabled() -> bool:
    """BYOK：是否同样强制目录命中。"""
    return _env_bool("MODSTORE_LLM_BYOK_CATALOG_GATE", False)


def platform_require_priced_row() -> bool:
    """平台密钥：除目录外还要求 AiModelPrice.enabled 或 L3 已批准。"""
    return _env_bool("MODSTORE_LLM_PLATFORM_REQUIRE_PRICED", False)


def new_model_preauth_multiplier() -> float:
    try:
        return float(os.environ.get("MODSTORE_LLM_NEW_MODEL_PREAUTH_MULT", "1.5") or "1.5")
    except ValueError:
        return 1.5


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def json_loads(raw: str | None, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, ValueError):
        return default


async def catalog_model_ids(session: Session, user_id: int, provider: str) -> Set[str]:
    if provider not in KNOWN_PROVIDERS:
        return set()
    block = await get_models_for_provider(session, user_id, provider, force_refresh=False)
    return {str(x).strip() for x in (block.get("models") or []) if str(x).strip()}


def _get_priced_row(session: Session, provider: str, model: str) -> Optional[AiModelPrice]:
    return (
        session.query(AiModelPrice)
        .filter(
            AiModelPrice.provider == provider,
            AiModelPrice.model == model,
            AiModelPrice.enabled == True,
        )
        .first()
    )


def _get_capability(session: Session, provider: str, model: str) -> Optional[LlmModelCapability]:
    return (
        session.query(LlmModelCapability)
        .filter(LlmModelCapability.provider == provider, LlmModelCapability.model == model)
        .first()
    )


def l3_approved(session: Session, provider: str, model: str) -> bool:
    row = _get_capability(session, provider, model)
    return bool(row and (row.l3_status or "") == "approved")


def l2_platform_billing_allowed(session: Session, provider: str, model: str) -> Tuple[bool, str]:
    """平台代付时 L2：是否允许按平台规则计费（含默认定价）。"""
    if not platform_require_priced_row():
        return True, ""
    if _get_priced_row(session, provider, model):
        return True, ""
    if l3_approved(session, provider, model):
        return True, "l3_approved"
    return False, "需要管理员登记 AiModelPrice 或将该模型 L3 批准后才可用平台密钥调用"


def preauth_multiplier_for_model(
    session: Session, provider: str, model: str, is_byok: bool
) -> float:
    if is_byok:
        return 1.0
    if _get_priced_row(session, provider, model):
        return 1.0
    if l3_approved(session, provider, model):
        return 1.0
    mult = new_model_preauth_multiplier()
    return max(1.0, mult)


async def assert_llm_chat_allowed(
    session: Session,
    user_id: int,
    provider: str,
    model: str,
    *,
    is_byok: bool,
) -> None:
    m = (model or "").strip()
    if not m:
        raise HTTPException(400, "model 不能为空")
    ids = await catalog_model_ids(session, user_id, provider)
    gate_platform = platform_catalog_gate_enabled()
    gate_byok = byok_catalog_gate_enabled()
    if gate_platform and not is_byok and m not in ids:
        raise HTTPException(
            400,
            "该模型不在当前账号的厂商目录中（或缓存未刷新）。请在钱包页「刷新模型列表」后重试，或改用目录内模型。",
        )
    if gate_byok and is_byok and m not in ids:
        raise HTTPException(
            400,
            "BYOK 已启用目录校验：该模型不在当前目录中，请刷新模型列表或选择目录内模型。",
        )
    if not is_byok:
        ok, reason = l2_platform_billing_allowed(session, provider, m)
        if not ok:
            raise HTTPException(403, reason)


async def model_allowed_for_default(
    session: Session,
    user_id: int,
    provider: str,
    model: str,
    *,
    is_byok: bool,
) -> bool:
    try:
        await assert_llm_chat_allowed(session, user_id, provider, model, is_byok=is_byok)
    except HTTPException:
        return False
    if not is_byok:
        ok, _ = l2_platform_billing_allowed(session, provider, model)
        return ok
    return True


def ensure_capability_stubs(session: Session, provider: str, model_ids: List[str]) -> int:
    """为目录中的模型插入占位行（L1 pending），返回新增行数近似。"""
    added = 0
    for mid in model_ids:
        mid = (mid or "").strip()
        if not mid:
            continue
        exists = (
            session.query(LlmModelCapability.id)
            .filter(LlmModelCapability.provider == provider, LlmModelCapability.model == mid)
            .first()
        )
        if exists:
            continue
        cat = classify_model(provider, mid)
        session.add(
            LlmModelCapability(
                provider=provider,
                model=mid,
                l1_status="pending",
                effective_category=cat,
                taxonomy_source="heuristic",
                l3_status="none",
            )
        )
        added += 1
    return added


def capability_public_dict(
    session: Session,
    provider: str,
    model_id: str,
    row: Optional[LlmModelCapability],
    *,
    heuristic_category: str,
) -> Dict[str, Any]:
    l2_ok, _ = l2_platform_billing_allowed(session, provider, model_id)
    if not row:
        return {
            "l1_status": "",
            "l1_score": None,
            "l3_status": "none",
            "effective_category": heuristic_category,
            "gate_tier": "unknown",
            "hint": "",
            "platform_billing_ok": l2_ok,
        }
    eff = (row.effective_category or "").strip() or heuristic_category
    tier = (
        "approved"
        if (row.l3_status or "") == "approved"
        else ("pending" if (row.l3_status or "") == "pending" else "catalog_only")
    )
    hint = ""
    if (row.l1_status or "") == "ok" and tier == "catalog_only":
        hint = "已通过 L1 技术探针；平台代付若需稳定上架请联系管理员登记定价或 L3 批准。"
    elif (row.l1_status or "") == "pending":
        hint = "L1 探针排队中或待触发。"
    elif (row.l1_status or "") == "failed":
        hint = "L1 探针未通过，若仍可选用请确认上游是否支持 chat 接口。"
    if (row.l3_status or "") == "pending":
        hint = "L3 审核中：已提交扩展申请，批准前平台密钥可能受 L2 策略限制。"
    return {
        "l1_status": row.l1_status or "",
        "l1_score": row.l1_score,
        "l3_status": row.l3_status or "none",
        "effective_category": eff,
        "taxonomy_source": row.taxonomy_source or "heuristic",
        "gate_tier": tier,
        "hint": hint,
        "l1_at": row.l1_at.isoformat() if row.l1_at else None,
        "platform_billing_ok": l2_ok,
    }


def merge_catalog_capabilities(session: Session, providers_out: List[Dict[str, Any]]) -> None:
    """就地写入 models_detailed[].capability。"""
    for block in providers_out:
        prov = str(block.get("provider") or "")
        mids = [str(x) for x in (block.get("models") or [])]
        ensure_capability_stubs(session, prov, mids)
        session.flush()
        cmap = load_capabilities_for_provider(session, prov)
        detailed = block.get("models_detailed") or []
        for md in detailed:
            mid = str(md.get("id") or "")
            hcat = str(md.get("category") or "other")
            row = cmap.get(mid)
            md["capability"] = capability_public_dict(
                session, prov, mid, row, heuristic_category=hcat
            )


def load_capabilities_for_provider(
    session: Session, provider: str
) -> Dict[str, LlmModelCapability]:
    rows = session.query(LlmModelCapability).filter(LlmModelCapability.provider == provider).all()
    return {r.model: r for r in rows}


async def run_l1_probe(session: Session, user_id: int, provider: str, model: str) -> None:
    """对单行执行 L1 探针并写回。"""
    row = _get_capability(session, provider, model)
    if not row:
        return
    if row.l1_status in ("ok", "running"):
        return
    row.l1_status = "running"
    session.flush()
    try:
        api_key, _ = resolve_api_key(session, user_id, provider)
        if not api_key:
            row.l1_status = "failed"
            row.l1_error = "no_api_key"
            row.l1_at = datetime.now(timezone.utc)
            session.commit()
            return
        base = (
            resolve_base_url(session, user_id, provider)
            if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
            else None
        )
        result = await chat_dispatch(
            provider,
            api_key=api_key,
            base_url=base,
            model=model,
            messages=[
                {"role": "system", "content": "Reply with OK only."},
                {"role": "user", "content": "ping"},
            ],
            max_tokens=8,
        )
        ok = bool(result.get("ok"))
        row.l1_status = "ok" if ok else "failed"
        row.l1_score = 100.0 if ok else 0.0
        row.l1_error = "" if ok else str(result.get("error") or "upstream")
        row.l1_flags_json = json_dumps(
            {
                "usage": result.get("usage"),
                "ok": ok,
            }
        )
        row.l1_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001
        row.l1_status = "failed"
        row.l1_score = 0.0
        row.l1_error = str(exc)[:500]
        row.l1_at = datetime.now(timezone.utc)
    finally:
        if row.l1_status == "running":
            row.l1_status = "failed"
            row.l1_error = (row.l1_error or "probe_aborted")[:500]
            row.l1_at = datetime.now(timezone.utc)
    session.commit()


async def drain_pending_l1_probes(session: Session, user_id: int, *, limit: int = 12) -> int:
    """处理一批 pending L1（同一请求内顺序执行，避免过多并发）。"""
    rows = (
        session.query(LlmModelCapability)
        .filter(LlmModelCapability.l1_status == "pending")
        .order_by(LlmModelCapability.id.asc())
        .limit(limit)
        .all()
    )
    n = 0
    for row in rows:
        api_key, _ = resolve_api_key(session, user_id, row.provider)
        if not api_key:
            continue
        await run_l1_probe(session, user_id, row.provider, row.model)
        n += 1
    return n


def schedule_l1_followup(user_id: int, *, limit: int = 16) -> None:
    """在事件循环中调度后台 L1 探针（须在 async 请求内调用）。"""

    async def _job() -> None:
        from modstore_server.models import get_session_factory

        sf = get_session_factory()
        db = sf()
        try:
            await drain_pending_l1_probes(db, user_id, limit=limit)
        except Exception:
            logger.exception("background L1 drain failed user_id=%s", user_id)
        finally:
            db.close()

    try:
        asyncio.create_task(_job())
    except RuntimeError:
        logger.debug("schedule_l1_followup: no running loop")


def upsert_l3_proposal(
    session: Session,
    *,
    user_id: int,
    provider: str,
    model: str,
    ticket_id: Optional[int],
    notes: str = "",
) -> LlmModelCapability:
    row = _get_capability(session, provider, model)
    if not row:
        row = LlmModelCapability(
            provider=provider,
            model=model,
            l1_status="pending",
            effective_category=classify_model(provider, model),
            taxonomy_source="heuristic",
            l3_status="pending",
            cs_ticket_id=ticket_id,
            l3_notes=(notes or "")[:2000],
        )
        session.add(row)
    else:
        row.l3_status = "pending"
        row.cs_ticket_id = ticket_id
        if notes:
            row.l3_notes = (notes or "")[:2000]
        row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return row


def apply_l3_review(
    session: Session,
    *,
    provider: str,
    model: str,
    status: str,
    reviewer_id: int,
    notes: str = "",
) -> LlmModelCapability:
    if status not in ("approved", "rejected", "none"):
        raise ValueError("invalid l3 status")
    row = _get_capability(session, provider, model)
    if not row:
        row = LlmModelCapability(
            provider=provider,
            model=model,
            effective_category=classify_model(provider, model),
            taxonomy_source="manual",
            l1_status="skipped",
            l3_status=status,
        )
        session.add(row)
    else:
        row.l3_status = status
        row.l3_reviewer_id = reviewer_id
        row.l3_at = datetime.now(timezone.utc)
        if notes:
            row.l3_notes = (notes or "")[:2000]
    session.flush()
    return row
