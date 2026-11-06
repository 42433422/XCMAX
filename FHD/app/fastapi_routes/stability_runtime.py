"""本机稳定性探针：超时、幂等副作用、租户隔离和实验会话刷新。

只接受回环和稳定性试验网卡上的调用。刷新令牌和口令不写入日志。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from app.application.network_stability import (
    FAILURE_NOTICES,
    OPERATION_TIMEOUT_S,
    RefreshSingleFlight,
    effect_claim,
    effect_finish,
    emit_current_lane,
    failure_payload,
    timeout_outcome,
)

router = APIRouter(tags=["stability-runtime"])
_ALLOWED_HOSTS = {"127.0.0.1", "::1", "10.88.0.2"}
_LANES = {"chat": 8, "erp": 4, "tool": 4}
_QUEUE_CAP = 64
_lane_lock = asyncio.Lock()
_lane_sem = {name: asyncio.Semaphore(limit) for name, limit in _LANES.items()}
_lane_queued = dict.fromkeys(_LANES, 0)
_notice: dict[str, Any] = {}
_refresh_gate = RefreshSingleFlight()
_refresh_box: dict[str, Any] = {}
_refresh_rotations = 0


def _allowed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in _ALLOWED_HOSTS


def _deny() -> JSONResponse:
    return JSONResponse({"success": False, "message": "not found"}, status_code=404)


def _refresh_key() -> bytes:
    from app.application.network_stability import effect_db_path

    path = effect_db_path().with_name("stability_refresh.key")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
        path.chmod(0o600)
    return path.read_bytes()


def _issue_refresh(user_id: int, *, ttl_s: int = 3600) -> str:
    payload = {
        "exp": int(time.time()) + ttl_s,
        "jti": uuid.uuid4().hex,
        "typ": "refresh",
        "uid": int(user_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(_refresh_key(), raw, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + sig


def _read_refresh(token: str) -> dict[str, Any] | None:
    try:
        raw_part, sig = token.split(".", 1)
        padded = raw_part + "=" * (-len(raw_part) % 4)
        raw = base64.urlsafe_b64decode(padded.encode())
        expected = hmac.new(_refresh_key(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        payload = json.loads(raw.decode())
        if payload.get("typ") != "refresh" or int(payload.get("exp") or 0) <= int(time.time()):
            return None
        if not str(payload.get("jti") or "").isalnum():
            return None
        payload["uid"] = int(payload["uid"])
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _consume_refresh(payload: dict[str, Any]) -> bool:
    import sqlite3

    from app.application.network_stability import effect_db_path

    conn = sqlite3.connect(effect_db_path(), timeout=5)
    try:
        conn.execute("create table if not exists refresh_uses (jti text primary key, expires_at integer)")
        conn.execute(
            "insert into refresh_uses(jti, expires_at) values (?, ?)",
            (payload["jti"], int(payload["exp"])),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _lab_user(slot: str) -> dict[str, Any]:
    from app.db.models.tenant import Tenant
    from app.db.models.user import User
    from app.db.session import get_host_db
    from app.infrastructure.session.session_manager import get_session_manager
    from app.utils.security.password_hash import generate_password_hash
    from app.utils.time import utc_now_naive

    code = f"stability-{slot}"
    with get_host_db() as db:
        tenant = db.query(Tenant).filter(Tenant.code == code).first()
        if tenant is None:
            tenant = Tenant(code=code, name=code, is_active=True, created_at=utc_now_naive())
            db.add(tenant)
            db.flush()
        user = db.query(User).filter(User.username == code).first()
        if user is None:
            user = User(
                username=code,
                password=generate_password_hash(secrets.token_urlsafe(18)),
                display_name=code,
                email="",
                role="user",
                is_active=True,
                tenant_id=tenant.id,
                tier="enterprise",
                industry_id="通用",
                created_at=utc_now_naive(),
            )
            db.add(user)
            db.flush()
            tenant.owner_user_id = user.id
        elif user.tenant_id != tenant.id:
            user.tenant_id = tenant.id
        user_id = int(user.id)
        tenant_id = int(tenant.id)
    created = get_session_manager().create_session(user_id)
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "session_id": created["session_id"],
        "refresh_token": _issue_refresh(user_id),
    }


def _session_user(request: Request) -> Any | None:
    from app.infrastructure.session.session_manager import get_session_manager

    session_id = request.cookies.get("session_id") or ""
    if not session_id:
        return None
    return get_session_manager().validate_session(session_id)


@router.get("/api/stability/delay")
async def delay(request: Request, profile: str = "health", sleep_ms: int = 0, hang: int = 0):
    if not _allowed(request):
        return _deny()
    if profile not in OPERATION_TIMEOUT_S:
        return JSONResponse(failure_payload("bad_tool_args"), status_code=400)
    limit = OPERATION_TIMEOUT_S[profile]
    target = limit + 5 if hang else max(0, sleep_ms) / 1000
    started = time.perf_counter()
    await asyncio.sleep(target)
    elapsed = time.perf_counter() - started
    outcome = timeout_outcome(profile, elapsed, hung=bool(hang) or elapsed > limit)
    status = 200 if outcome["success"] else 504
    body = {**outcome, "elapsed_s": round(elapsed, 3), "success": outcome["success"]}
    if not outcome["success"]:
        body.update(failure_payload("timeout"))
    return JSONResponse(body, status_code=status, headers={"X-Error-Code": "" if outcome["success"] else "timeout"})


@router.get("/api/stability/lane")
async def lane(request: Request, lane_name: str = "chat", sleep_ms: int = 0, queue_limit: int = 32):
    if not _allowed(request):
        return _deny()
    if lane_name not in _lane_sem:
        return JSONResponse(failure_payload("bad_tool_args"), status_code=400)
    limit = max(1, min(int(queue_limit or 1), _QUEUE_CAP))
    async with _lane_lock:
        inflight = _LANES[lane_name] - _lane_sem[lane_name]._value
        if _lane_queued[lane_name] + max(inflight, 0) >= limit:
            return JSONResponse(
                {**failure_payload("interrupted"), "error_code": "queue_full", "lane": lane_name},
                status_code=429,
                headers={"X-Error-Code": "queue_full", "X-Stability-Lane": lane_name},
            )
        _lane_queued[lane_name] += 1
    started = time.perf_counter()
    try:
        async with _lane_sem[lane_name]:
            async with _lane_lock:
                _lane_queued[lane_name] -= 1
            await asyncio.sleep(max(0, sleep_ms) / 1000)
    except Exception:
        async with _lane_lock:
            _lane_queued[lane_name] = max(0, _lane_queued[lane_name] - 1)
        raise
    return JSONResponse(
        {"success": True, "lane": lane_name, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)},
        headers={"X-Stability-Lane": lane_name},
    )


def _write_erp(tenant_id: int, key: str) -> dict[str, Any]:
    from app.application.sales_app_service import SalesAppService
    from app.db.session import get_db
    from app.db.models.customer import Customer
    from app.infrastructure.tenant_scope import tenant_scope

    name = f"稳定性客户{tenant_id}"
    with tenant_scope(tenant_id):
        with get_db() as db:
            customer = db.query(Customer).filter(Customer.customer_name == name).first()
            if customer is None:
                customer = Customer(customer_name=name, tenant_id=tenant_id)
                db.add(customer)
                db.commit()
                db.refresh(customer)
            customer_id = int(customer.id)
        quoted = SalesAppService().quote(
            {
                "customer_id": customer_id,
                "customer_name": name,
                "idempotency_key": key,
                "items": [{"product_name": "稳定性探针", "quantity": "1", "unit_price": "1"}],
            }
        )
    return quoted


def _write_chat(user_id: int, key: str, text: str) -> str:
    from app.db.session import get_db
    from app.db.models.ai import AIConversation, AIConversationSession
    from app.utils.time import utc_now_naive

    session_key = f"stab-{key[:24]}"
    with get_db() as db:
        row = db.query(AIConversationSession).filter(AIConversationSession.session_id == session_key).first()
        if row is None:
            row = AIConversationSession(
                session_id=session_key,
                user_id=user_id,
                title="稳定性探针",
                message_count=0,
                created_at=utc_now_naive(),
            )
            db.add(row)
            db.flush()
        db.add(
            AIConversation(
                session_id=session_key,
                user_id=str(user_id),
                role="user",
                content=text[:200],
                intent="stability",
                conversation_metadata=key,
                created_at=utc_now_naive(),
            )
        )
        row.message_count = int(row.message_count or 0) + 1
        row.last_message_at = utc_now_naive()
        db.commit()
    return session_key


@router.post("/api/stability/operations")
async def operations(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    if not _allowed(request):
        return _deny()
    user = _session_user(request)
    if user is None or not str(getattr(user, "username", "")).startswith("stability-"):
        return JSONResponse(failure_payload("token_expired"), status_code=401, headers={"X-Error-Code": "token_expired"})
    from app.db.models.user import User
    from app.db.session import get_host_db

    with get_host_db() as db:
        stored = db.get(User, int(user.id))
        tenant_id = int(stored.tenant_id) if stored is not None and stored.tenant_id else 0
    if tenant_id <= 0:
        return JSONResponse(failure_payload("permission"), status_code=403)
    lane_name = str(body.get("lane") or "")
    if lane_name not in _LANES:
        return JSONResponse(failure_payload("bad_tool_args"), status_code=400)
    key = str(body.get("idempotency_key") or "")
    try:
        claim = effect_claim(key, lane_name, str(tenant_id))
    except ValueError:
        return JSONResponse(failure_payload("bad_tool_args"), status_code=400)
    headers = {"X-Stability-Lane": lane_name}
    if not claim["execute"]:
        if claim["state"] == "succeeded":
            return JSONResponse(
                {"success": True, "idempotent": True, "state": "succeeded", "ref": claim["ref"], "lane": lane_name},
                headers=headers,
            )
        kind = "interrupted" if claim["state"] == "unknown" else "interrupted"
        return JSONResponse(
            {**failure_payload(kind), "state": claim["state"], "lane": lane_name},
            status_code=409,
            headers={**headers, "X-Error-Code": kind},
        )
    try:
        await asyncio.sleep(max(0, int(body.get("hold_before_ms") or 0)) / 1000)
        ref = ""
        if lane_name == "erp":
            quoted = await asyncio.to_thread(_write_erp, tenant_id, claim["key"])
            if not quoted.get("success"):
                effect_finish(claim["key"], "failed", "")
                emit_current_lane("erp", status=400, error_code="bad_tool_args")
                return JSONResponse(
                    {**failure_payload("bad_tool_args"), "message": "销售订单未创建。", "detail": str(quoted.get("message") or "")[:120]},
                    status_code=400,
                    headers={**headers, "X-Error-Code": "bad_tool_args"},
                )
            ref = str((quoted.get("data") or {}).get("id") or "")
        elif lane_name == "chat":
            from app.application.agent_orchestrator.chat_trace import create_chat_trace_run

            text = str(body.get("text") or "稳定性探针")[:200]
            try:
                create_chat_trace_run({"response": text, "success": True}, message=text, user_id=str(user.id))
            except Exception:
                emit_current_lane("chat", status=200)
            ref = await asyncio.to_thread(_write_chat, int(user.id), claim["key"], text)
        else:
            emit_current_lane("tool", status=200)
            ref = f"tool-{claim['key']}"
        await asyncio.sleep(max(0, int(body.get("hold_after_ms") or 0)) / 1000)
        effect_finish(claim["key"], "succeeded", ref)
        return JSONResponse({"success": True, "state": "succeeded", "ref": ref, "lane": lane_name}, headers=headers)
    except Exception:
        import logging

        logging.getLogger("app.stability").exception("stability operation failed lane=%s", lane_name)
        effect_finish(claim["key"], "unknown", "")
        emit_current_lane(lane_name, status=500, error_code="interrupted")
        return JSONResponse(
            failure_payload("interrupted"),
            status_code=500,
            headers={**headers, "X-Error-Code": "interrupted"},
        )


@router.get("/api/stability/orders")
async def orders(request: Request):
    if not _allowed(request):
        return _deny()
    user = _session_user(request)
    if user is None:
        return JSONResponse(failure_payload("token_expired"), status_code=401)
    from app.application.sales_app_service import SalesAppService

    listed = SalesAppService().query(per_page=50)
    rows = listed.get("data") or []
    return {
        "success": True,
        "tenant_id": getattr(user, "tenant_id", None),
        "count": len(rows),
        "order_nos": [str(row.get("order_no") or "") for row in rows],
    }


@router.get("/api/stability/history")
async def history(request: Request):
    if not _allowed(request):
        return _deny()
    user = _session_user(request)
    if user is None:
        return JSONResponse(failure_payload("token_expired"), status_code=401)
    from app.db.session import get_db
    from app.db.models.ai import AIConversation

    with get_db() as db:
        count = db.query(AIConversation).filter(AIConversation.user_id == str(user.id)).count()
    return {"success": True, "count": int(count)}


@router.get("/api/stability/errors/{kind}")
async def errors(kind: str, request: Request):
    if not _allowed(request):
        return _deny()
    if kind not in FAILURE_NOTICES:
        return JSONResponse(failure_payload("bad_tool_args"), status_code=400)
    return JSONResponse(failure_payload(kind), status_code=200, headers={"X-Error-Code": kind})


@router.post("/api/stability/ui-notice")
async def arm_notice(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    if not _allowed(request):
        return _deny()
    raw = str(body.get("raw") or "")
    _notice.clear()
    _notice["raw"] = raw[:180]
    return {"success": True}


@router.get("/api/stability/ui-notice")
async def take_notice(request: Request):
    if not _allowed(request):
        return _deny()
    raw = str(_notice.pop("raw", "") or "")
    return {"success": True, "raw": raw}


@router.post("/api/stability/lab/session")
async def lab_session(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    if not _allowed(request):
        return _deny()
    slot = str(body.get("slot") or "a")
    if slot not in {"a", "b"}:
        return JSONResponse(failure_payload("bad_tool_args"), status_code=400)
    ttl = int(body.get("refresh_ttl_s") or 3600)
    if ttl < -30 or ttl > 86400:
        return JSONResponse(failure_payload("bad_tool_args"), status_code=400)
    issued = _lab_user(slot)
    if ttl != 3600:
        issued["refresh_token"] = _issue_refresh(issued["user_id"], ttl_s=ttl)
    response = JSONResponse({"success": True, "user_id": issued["user_id"], "tenant_id": issued["tenant_id"], "session_id": issued["session_id"], "refresh_token": issued["refresh_token"]})
    response.set_cookie("session_id", issued["session_id"], httponly=True, samesite="lax", path="/")
    return response


@router.post("/api/stability/lab/expire")
async def lab_expire(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    if not _allowed(request):
        return _deny()
    from app.db.models.user import Session as UserSession
    from app.db.session import get_host_db
    from app.utils.time import utc_now_naive

    session_id = str(body.get("session_id") or "")
    with get_host_db() as db:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        user = getattr(row, "user", None)
        if row is None or user is None or not str(user.username).startswith("stability-"):
            return JSONResponse(failure_payload("permission"), status_code=403)
        row.expires_at = utc_now_naive() - timedelta(seconds=5)
    return {"success": True, "expired": True}


@router.post("/api/stability/lab/refresh")
async def lab_refresh(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    global _refresh_rotations
    if not _allowed(request):
        return _deny()
    token = str(body.get("refresh_token") or "")
    payload = _read_refresh(token)
    if payload is None:
        return JSONResponse(failure_payload("token_expired"), status_code=401, headers={"X-Error-Code": "token_expired"})

    def rotate() -> bool:
        global _refresh_rotations
        if not _consume_refresh(payload):
            _refresh_box.clear()
            _refresh_box["error"] = "used"
            return False
        from app.infrastructure.session.session_manager import get_session_manager

        created = get_session_manager().create_session(int(payload["uid"]))
        _refresh_box.clear()
        _refresh_box.update(
            {
                "session_id": created["session_id"],
                "refresh_token": _issue_refresh(int(payload["uid"])),
                "user_id": int(payload["uid"]),
            }
        )
        _refresh_rotations += 1
        return True

    ok = await asyncio.to_thread(_refresh_gate.run, rotate)
    if not ok:
        return JSONResponse(failure_payload("token_expired"), status_code=401, headers={"X-Error-Code": "token_expired"})
    issued = dict(_refresh_box)
    response = JSONResponse({"success": True, "user_id": issued.get("user_id"), "session_id": issued.get("session_id"), "refresh_token": issued.get("refresh_token")})
    if issued.get("session_id"):
        response.set_cookie("session_id", issued["session_id"], httponly=True, samesite="lax", path="/")
    return response


@router.get("/api/stability/lab/metrics")
async def lab_metrics(request: Request):
    if not _allowed(request):
        return _deny()
    return {"success": True, "refresh_rotations": _refresh_rotations}
