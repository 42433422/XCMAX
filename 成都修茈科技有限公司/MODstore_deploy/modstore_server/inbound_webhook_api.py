"""Inbound webhook receivers — 让外部系统把任务推进来给 AI 员工。

支持的入口：
    POST /api/inbound/webhooks/github     — GitHub push / issue / pull_request
    POST /api/inbound/webhooks/feishu     — 飞书自定义机器人 / open platform
    POST /api/inbound/webhooks/dingtalk   — 钉钉自定义机器人 / 工作台
    POST /api/inbound/webhooks/generic    — 任意 JSON（合作方对接前的通用入口）

每个端点都会：
    1. 校验来源签名 / token（环境变量按 provider 分别配置）
    2. 把 payload 摘要成自然语言任务描述
    3. 创建一条 ``OnDemandOrchestrateJob``（pending）
    4. 起 worker 线程调 ``task_router.route_and_dispatch``，并把结果回写

设计要点：
    - 不直接挂死外部账号——通过环境变量开关，未配置 secret 的 provider 直接 503，
      避免被野扫描刷接口。
    - 出错不 raise 给外部（除了 401/403 鉴权错），永远 200 回执 + ``ok``=true/false，
      防止外部系统因 5xx 不停重试。
    - 抽象出 ``_summarize_<provider>_payload`` 把每个平台 payload 的关键字段
      落成简短的中文任务描述（不调 LLM，省 token；下游 task_router 会再拆）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy.orm import Session

from modstore_server.models import OnDemandOrchestrateJob, User, get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inbound/webhooks", tags=["inbound-webhooks"])


# ─── env helpers ─────────────────────────────────────────────────────────────


def _env_secret(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _resolve_actor_user_id() -> int:
    """没有人类用户的 webhook 任务都挂到首位管理员名下，方便审计。"""
    sf = get_session_factory()
    with sf() as session:
        u = session.query(User).filter(User.is_admin.is_(True)).order_by(User.id.asc()).first()
        if u:
            return int(u.id)
        u2 = session.query(User).order_by(User.id.asc()).first()
        return int(u2.id) if u2 else 0


# ─── job persist + worker ────────────────────────────────────────────────────


def _enqueue_orchestrate_job(
    *,
    task_description: str,
    user_id: int,
    use_task_router: bool = True,
    target_employee_id: str = "",
    max_concurrency: int = 3,
    allow_high_risk_real_run: bool = False,
    source_label: str = "",
) -> str:
    """落地 OnDemandOrchestrateJob 并起 worker，返回 job_id。"""
    job_id = str(uuid.uuid4())
    sf = get_session_factory()
    with sf() as session:
        row = OnDemandOrchestrateJob(
            job_id=job_id,
            user_id=int(user_id),
            task_description=(task_description or "")[:8000],
            status="pending",
            use_task_router=bool(use_task_router),
            target_employee_id=(target_employee_id or "")[:128],
            max_concurrency=int(max_concurrency),
            allow_high_risk_real_run=bool(allow_high_risk_real_run),
            llm_provider="auto",
            llm_model="auto",
        )
        session.add(row)
        session.commit()

    def _worker() -> None:
        sf2 = get_session_factory()
        with sf2() as session:
            r = session.query(OnDemandOrchestrateJob).filter_by(job_id=job_id).first()
            if r:
                r.status = "running"
                r.started_at = datetime.now(timezone.utc)
                session.commit()
        try:
            if use_task_router:
                from modstore_server.task_router import route_and_dispatch

                result = route_and_dispatch(
                    task_description,
                    created_by_user_id=user_id,
                    max_concurrency=max_concurrency,
                    allow_high_risk_real_run=allow_high_risk_real_run,
                )
            else:
                from modstore_server.employee_orchestrator import plan_and_dispatch

                result = plan_and_dispatch(
                    task_description,
                    {},
                    target_employee_id=target_employee_id or "daily-orchestrator",
                    created_by_user_id=user_id,
                    max_concurrency=max_concurrency,
                    allow_high_risk_real_run=allow_high_risk_real_run,
                )
            with sf2() as session:
                r = session.query(OnDemandOrchestrateJob).filter_by(job_id=job_id).first()
                if r:
                    r.status = "done"
                    r.completed_at = datetime.now(timezone.utc)
                    r.result_json = json.dumps(
                        {"source": source_label, **(result or {})},
                        ensure_ascii=False,
                    )[:500_000]
                    session.commit()
            try:
                from modstore_server.notification_service import (
                    NotificationType,
                    create_notification,
                )

                create_notification(
                    user_id=user_id,
                    notification_type=NotificationType.EMPLOYEE_EXECUTION_DONE,
                    title=f"[{source_label}] 任务执行完成",
                    content=f"来自 {source_label} 的任务已分派并完成：{(task_description or '')[:120]}",
                    data={"job_id": job_id, "source": source_label},
                )
            except Exception:
                logger.debug("inbound webhook notify skipped", exc_info=True)
        except Exception as exc:
            logger.exception("inbound webhook job %s (%s) failed", job_id, source_label)
            with sf2() as session:
                r = session.query(OnDemandOrchestrateJob).filter_by(job_id=job_id).first()
                if r:
                    r.status = "failed"
                    r.completed_at = datetime.now(timezone.utc)
                    r.error = str(exc)[:4000]
                    session.commit()

    t = threading.Thread(
        target=_worker,
        daemon=True,
        name=f"inbound-{source_label}-{job_id[:8]}",
    )
    t.start()
    return job_id


# ─── provider: GitHub ────────────────────────────────────────────────────────


def _verify_github_signature(secret: str, body: bytes, signature: Optional[str]) -> bool:
    if not secret:
        return True  # 未配置 secret 视为开放（但端点会先检查 secret 存在）
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _summarize_github_payload(event: str, payload: Dict[str, Any]) -> str:
    repo = (payload.get("repository") or {}).get("full_name") or "未知仓库"
    sender = (payload.get("sender") or {}).get("login") or "未知用户"
    if event == "push":
        ref = payload.get("ref") or ""
        commits = payload.get("commits") or []
        first = (commits[0].get("message") if commits else "") or ""
        return (
            f"GitHub 推送：{repo}@{ref}（{sender}） — {len(commits)} commits；"
            f"首条：{first[:200]}"
        )
    if event == "issues":
        action = payload.get("action") or ""
        issue = payload.get("issue") or {}
        return (
            f"GitHub Issue {action}：{repo}#{issue.get('number')} - "
            f"{(issue.get('title') or '')[:200]}（{sender}）\n\n正文：\n"
            f"{(issue.get('body') or '')[:1500]}"
        )
    if event == "pull_request":
        action = payload.get("action") or ""
        pr = payload.get("pull_request") or {}
        return (
            f"GitHub PR {action}：{repo}#{pr.get('number')} - "
            f"{(pr.get('title') or '')[:200]}（{sender}）\n\n描述：\n"
            f"{(pr.get('body') or '')[:1500]}"
        )
    if event == "issue_comment":
        action = payload.get("action") or ""
        c = payload.get("comment") or {}
        issue = payload.get("issue") or {}
        return (
            f"GitHub Issue 评论 {action}：{repo}#{issue.get('number')} - "
            f"{(c.get('body') or '')[:1500]}（{sender}）"
        )
    return f"GitHub {event} 事件：{repo}（{sender}） payload keys={list(payload.keys())[:8]}"


def _resolve_github_target_employee(event: str, payload: Dict[str, Any]) -> tuple[bool, str]:
    """Push 到营销路径时定向 site-content-editor，避免泛化 task_router。"""
    if event != "push":
        return True, ""
    marketing_prefixes = (
        "marketing-site/",
        "index.html",
        "news.html",
        "news.json",
        "styles.css",
        "main.js",
        "assets/",
        "site/",
        "new/",
    )
    for commit in payload.get("commits") or []:
        for key in ("added", "modified", "removed"):
            for path in commit.get(key) or []:
                p = str(path)
                if any(p == pref.rstrip("/") or p.startswith(pref) for pref in marketing_prefixes):
                    return False, "site-content-editor"
    return True, ""


@router.post("/github")
async def receive_github_webhook(
    request: Request,
    x_github_event: str = Header("", alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header("", alias="X-Hub-Signature-256"),
):
    secret = _env_secret("MODSTORE_GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "未配置 MODSTORE_GITHUB_WEBHOOK_SECRET，入口已禁用")
    body = await request.body()
    if not _verify_github_signature(secret, body, x_hub_signature_256):
        raise HTTPException(401, "GitHub 签名校验失败")
    try:
        payload = json.loads(body or b"{}")
    except Exception:
        raise HTTPException(400, "payload 不是合法 JSON")
    event = (x_github_event or "").strip().lower() or "unknown"
    if event == "ping":
        return {"ok": True, "pong": True}
    desc = _summarize_github_payload(event, payload)
    uid = _resolve_actor_user_id()
    if uid <= 0:
        return {"ok": False, "error": "no admin user available"}
    use_router, target_emp = _resolve_github_target_employee(event, payload)
    job_id = _enqueue_orchestrate_job(
        task_description=desc,
        user_id=uid,
        use_task_router=use_router,
        target_employee_id=target_emp,
        source_label=f"github:{event}",
    )
    return {
        "ok": True,
        "job_id": job_id,
        "event": event,
        "target_employee_id": target_emp or None,
    }


# ─── provider: Feishu (Lark) ─────────────────────────────────────────────────


def _summarize_feishu_payload(payload: Dict[str, Any]) -> str:
    header = payload.get("header") or {}
    event_type = header.get("event_type") or "unknown"
    event = payload.get("event") or {}
    if event_type == "im.message.receive_v1":
        msg = event.get("message") or {}
        content = msg.get("content") or "{}"
        try:
            content_obj = json.loads(content)
            text = content_obj.get("text") or content_obj.get("content") or ""
        except Exception:
            text = str(content)[:500]
        return f"飞书消息：{text[:1500]}"
    return f"飞书事件 {event_type}：{json.dumps(event, ensure_ascii=False)[:1500]}"


@router.post("/feishu")
async def receive_feishu_webhook(request: Request):
    expected_token = _env_secret("MODSTORE_FEISHU_VERIFY_TOKEN")
    if not expected_token:
        raise HTTPException(503, "未配置 MODSTORE_FEISHU_VERIFY_TOKEN，入口已禁用")
    body = await request.body()
    try:
        payload = json.loads(body or b"{}")
    except Exception:
        raise HTTPException(400, "payload 不是合法 JSON")
    if payload.get("type") == "url_verification":
        if (payload.get("token") or "") != expected_token:
            raise HTTPException(401, "verify token 不匹配")
        return {"challenge": payload.get("challenge")}
    header = payload.get("header") or {}
    if (header.get("token") or payload.get("token") or "") != expected_token:
        raise HTTPException(401, "飞书 token 校验失败")
    desc = _summarize_feishu_payload(payload)
    uid = _resolve_actor_user_id()
    if uid <= 0:
        return {"ok": False, "error": "no admin user available"}
    job_id = _enqueue_orchestrate_job(
        task_description=desc,
        user_id=uid,
        source_label=f"feishu:{header.get('event_type') or 'unknown'}",
    )
    return {"ok": True, "job_id": job_id}


# ─── provider: DingTalk ──────────────────────────────────────────────────────


def _summarize_dingtalk_payload(payload: Dict[str, Any]) -> str:
    event_type = payload.get("EventType") or payload.get("msgtype") or "unknown"
    text_obj = payload.get("text") or {}
    text = text_obj.get("content") if isinstance(text_obj, dict) else str(text_obj)
    if not text:
        text = json.dumps(payload, ensure_ascii=False)[:1500]
    sender = payload.get("senderNick") or payload.get("senderId") or ""
    return f"钉钉消息 {event_type}（{sender}）：{(text or '')[:1500]}"


@router.post("/dingtalk")
async def receive_dingtalk_webhook(
    request: Request,
    timestamp: str = Header("", alias="timestamp"),
    sign: str = Header("", alias="sign"),
):
    secret = _env_secret("MODSTORE_DINGTALK_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "未配置 MODSTORE_DINGTALK_WEBHOOK_SECRET，入口已禁用")
    if timestamp and sign:
        import base64

        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        if expected != sign:
            raise HTTPException(401, "钉钉签名校验失败")
    body = await request.body()
    try:
        payload = json.loads(body or b"{}")
    except Exception:
        raise HTTPException(400, "payload 不是合法 JSON")
    desc = _summarize_dingtalk_payload(payload)
    uid = _resolve_actor_user_id()
    if uid <= 0:
        return {"ok": False, "error": "no admin user available"}
    job_id = _enqueue_orchestrate_job(
        task_description=desc,
        user_id=uid,
        source_label=f"dingtalk:{payload.get('EventType') or 'msg'}",
    )
    return {"ok": True, "job_id": job_id}


# ─── provider: Generic ───────────────────────────────────────────────────────


@router.post("/generic")
async def receive_generic_webhook(
    request: Request,
    authorization: str = Header("", alias="Authorization"),
    x_modstore_token: str = Header("", alias="X-MODSTORE-TOKEN"),
):
    """通用 JSON 入口，要求 ``Authorization: Bearer <token>`` 或 ``X-MODSTORE-TOKEN: <token>``。

    body 可包含：
        { "task_description": "...", "target_employee_id": "...",
          "use_task_router": true, "max_concurrency": 3,
          "allow_high_risk_real_run": false }
    """
    secret = _env_secret("MODSTORE_GENERIC_WEBHOOK_TOKEN")
    if not secret:
        raise HTTPException(503, "未配置 MODSTORE_GENERIC_WEBHOOK_TOKEN，入口已禁用")
    bearer = ""
    if authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    if bearer != secret and (x_modstore_token or "").strip() != secret:
        raise HTTPException(401, "token 不匹配")
    body = await request.body()
    try:
        payload = json.loads(body or b"{}")
    except Exception:
        raise HTTPException(400, "payload 不是合法 JSON")
    desc = (
        str(payload.get("task_description") or "").strip()
        or json.dumps(payload, ensure_ascii=False)[:1500]
    )
    if not desc:
        raise HTTPException(400, "需要在 task_description 字段里给出任务描述")
    uid = _resolve_actor_user_id()
    if uid <= 0:
        return {"ok": False, "error": "no admin user available"}
    job_id = _enqueue_orchestrate_job(
        task_description=desc,
        user_id=uid,
        use_task_router=bool(payload.get("use_task_router", True)),
        target_employee_id=str(payload.get("target_employee_id") or "")[:128],
        max_concurrency=int(payload.get("max_concurrency") or 3),
        allow_high_risk_real_run=bool(payload.get("allow_high_risk_real_run", False)),
        source_label="generic",
    )
    return {"ok": True, "job_id": job_id}


# ─── status / debug ──────────────────────────────────────────────────────────


@router.get("/status")
def status_overview() -> Dict[str, Any]:
    """无鉴权的入口可用性自检（供运维快速看 4 个 provider 是否打开）。"""
    return {
        "ok": True,
        "providers": {
            "github": bool(_env_secret("MODSTORE_GITHUB_WEBHOOK_SECRET")),
            "feishu": bool(_env_secret("MODSTORE_FEISHU_VERIFY_TOKEN")),
            "dingtalk": bool(_env_secret("MODSTORE_DINGTALK_WEBHOOK_SECRET")),
            "generic": bool(_env_secret("MODSTORE_GENERIC_WEBHOOK_TOKEN")),
        },
    }


__all__ = ["router"]
