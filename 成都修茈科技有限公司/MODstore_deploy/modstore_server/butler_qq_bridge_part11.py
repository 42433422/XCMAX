# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.butler_qq_bridge")


def _specific_app_secret(webhook_key: str) -> str:
    """两位老员工的 AppSecret 解析：先读 ENV，再回退到密钥文件。"""
    spec = _facade()._SPECIFIC_WEBHOOKS.get(webhook_key)
    if not spec:
        return ""
    env_name = spec.get("app_secret_env") or ""
    if env_name:
        v = _facade()._env(env_name)
        if v:
            return v
    employee_id = spec.get("employee_id", "")
    if not employee_id:
        return ""
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(employee_id, "qq")
        if rec:
            secret = rec.get("secret") or {}
            v = str(secret.get("app_secret") or "").strip()
            if v:
                return v
    except Exception as exc:
        _facade().logger.debug("_specific_app_secret 查账号池失败 key=%s: %s", webhook_key, exc)
    return ""


def _specific_bot_token(webhook_key: str) -> str:
    """两位老员工的机器人 Token：先读 ENV，再回退密钥文件 ``secret.bot_token``。"""
    spec = _facade()._SPECIFIC_WEBHOOKS.get(webhook_key)
    if not spec:
        return ""
    env_name = spec.get("bot_token_env") or ""
    if env_name:
        v = _facade()._env(env_name)
        if v:
            return v
    employee_id = spec.get("employee_id", "")
    if not employee_id:
        return ""
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(employee_id, "qq")
        if rec:
            secret = rec.get("secret") or {}
            v = str(secret.get("bot_token") or "").strip()
            if v:
                return v
    except Exception as exc:
        _facade().logger.debug("_specific_bot_token 查账号池失败 key=%s: %s", webhook_key, exc)
    return ""


def _resolve_webhook_app_id(webhook_key: str) -> _facade().Tuple[str, str]:
    """``/api/agent/butler/qq/{webhook_key}/webhook`` → ``(app_id, employee_id)``。

    解析顺序：

    1) ``_SPECIFIC_WEBHOOKS`` 静态表：``task-router`` / ``employee-interview``
       这两位老员工的 webhook URL 已经在 QQ 后台登记，必须保持稳定；
       命中即直接返回 (app_id, employee_id)，让分发器走它们各自的执行器。
    2) 把 ``webhook_key`` 当作 ``employee_id`` 在账号池里查活跃 QQ 账号——
       这样任意新员工只要绑了 QQ 账号，都能用 ``/<employee_id>/webhook`` 收到事件。

    找不到则两个返回值都是空串，由调用方决定走 404 还是兜底。
    """
    spec = _facade()._SPECIFIC_WEBHOOKS.get(webhook_key)
    if spec:
        return (spec.get("app_id", ""), spec.get("employee_id", ""))
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(webhook_key, "qq")
    except Exception as exc:
        _facade().logger.debug(
            "_resolve_webhook_app_id 查 employee 失败 key=%s: %s", webhook_key, exc
        )
        rec = None
    if not rec:
        return ("", "")
    secret = rec.get("secret") or {}
    app_id = str(secret.get("app_id") or rec.get("external_id") or "").strip()
    return (app_id, webhook_key)


@_facade().router.get("/{webhook_key}/webhook")
async def qq_specific_webhook_probe(webhook_key: str) -> _facade().JSONResponse:
    """Per-employee QQ callback probe.

    QQ's validation request is tied to one BotSecret. Dedicated URLs let us know
    which AppSecret to use even if QQ does not send X-Union-Appid during op=13.
    """
    (app_id, employee_id) = _facade()._resolve_webhook_app_id(webhook_key)
    if not app_id:
        raise _facade().HTTPException(404, "unknown webhook")
    return _facade().JSONResponse(
        {"ok": True, "app_id": app_id, "employee_id": employee_id or None}
    )


@_facade().router.post("/{webhook_key}/webhook")
async def qq_specific_webhook(
    webhook_key: str, request: _facade().Request
) -> _facade().JSONResponse:
    (app_id, employee_id) = _facade()._resolve_webhook_app_id(webhook_key)
    if not app_id:
        raise _facade().HTTPException(404, "unknown webhook")
    return await _facade()._qq_webhook_impl(
        request, forced_app_id=app_id, forced_employee_id=employee_id
    )


@_facade().router.get("/by-employee/{employee_id}/webhook")
async def qq_employee_webhook_probe(employee_id: str) -> _facade().JSONResponse:
    """通用版"按员工"探活：admin 给员工绑了 QQ 账号即可立刻有 URL。"""
    rec = None
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(employee_id, "qq")
    except Exception:
        rec = None
    if not rec:
        raise _facade().HTTPException(404, "employee 未绑定 QQ 账号")
    secret = rec.get("secret") or {}
    app_id = str(secret.get("app_id") or rec.get("external_id") or "")
    return _facade().JSONResponse({"ok": True, "employee_id": employee_id, "app_id": app_id})


@_facade().router.post("/by-employee/{employee_id}/webhook")
async def qq_employee_webhook(
    employee_id: str, request: _facade().Request
) -> _facade().JSONResponse:
    """通用入站渠道：``/api/agent/butler/qq/by-employee/{employee_id}/webhook``。

    无需改代码、无需 ENV，只要 admin 在账号池里把 QQ 账号挂到这个员工名下，
    URL 就会自动生效。是 ``/{webhook_key}/webhook`` 的命名空间安全版本，
    避免和静态 ``task-router`` / ``employee-interview`` 撞车。
    """
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(employee_id, "qq")
    except Exception as exc:
        _facade().logger.warning("by-employee webhook 查账号失败 employee=%s: %s", employee_id, exc)
        rec = None
    if not rec:
        raise _facade().HTTPException(404, "employee 未绑定 QQ 账号")
    secret = rec.get("secret") or {}
    app_id = str(secret.get("app_id") or rec.get("external_id") or "").strip()
    if not app_id:
        raise _facade().HTTPException(500, "账号缺 app_id 字段，密钥文件未正确写入")
    return await _facade()._qq_webhook_impl(
        request, forced_app_id=app_id, forced_employee_id=employee_id
    )


@_facade().router.post("/webhook")
async def qq_webhook(request: _facade().Request) -> _facade().JSONResponse:
    return await _facade()._qq_webhook_impl(request, forced_app_id=None, forced_employee_id="")


async def _qq_webhook_impl(
    request: _facade().Request,
    *,
    forced_app_id: _facade().Optional[str],
    forced_employee_id: str = "",
) -> _facade().JSONResponse:
    body_bytes = await request.body()
    timestamp = request.headers.get("X-Signature-Timestamp") or ""
    sig = request.headers.get("X-Signature-Ed25519") or ""
    try:
        envelope = _facade().json.loads(body_bytes or b"{}")
    except _facade().json.JSONDecodeError:
        raise _facade().HTTPException(400, "无效 JSON")
    op = envelope.get("op")
    if op == 13:
        d = envelope.get("d") or {}
        plain_token = str(d.get("plain_token") or "")
        event_ts = str(d.get("event_ts") or "")
        if not (plain_token and event_ts):
            raise _facade().HTTPException(400, "op=13 缺少 plain_token / event_ts")
        secrets_map = _facade()._all_known_app_secrets()
        inbound_app_id_13 = (forced_app_id or request.headers.get("X-Union-Appid") or "").strip()
        if forced_app_id and forced_app_id in secrets_map:
            use_secret = secrets_map[forced_app_id]
            chosen_for = f"forced app_id={forced_app_id}"
        elif inbound_app_id_13 and inbound_app_id_13 in secrets_map:
            use_secret = secrets_map[inbound_app_id_13]
            chosen_for = f"X-Union-Appid={inbound_app_id_13}"
        elif inbound_app_id_13:
            _facade().logger.error(
                "op=13 收到未知 X-Union-Appid=%s；当前已注册 app_id=%s。请在 /admin/ai-accounts 给该机器人补一个 AI 员工账号（platform=qq + 正确的 app_secret），或给两位老员工设置 TASK_ROUTER_QQ_APP_SECRET / EMPLOYEE_INTERVIEW_QQ_APP_SECRET。",
                inbound_app_id_13,
                sorted(secrets_map.keys()),
            )
            raise _facade().HTTPException(
                503,
                f"AppID {inbound_app_id_13} 未在本服务注册凭证；请到管理后台 AI 员工账号池补建账号或配 ENV，再让 QQ 重新校验",
            )
        else:
            _facade().logger.warning(
                "op=13 缺少 X-Union-Appid 头，落回默认管家 AppSecret 签名；若该机器人不是管家会握手失败"
            )
            use_secret = _facade()._qq_app_secret()
            chosen_for = "fallback=butler (no X-Union-Appid)"
        try:
            sig_bytes = _facade()._sign_payload_for(
                (event_ts + plain_token).encode("utf-8"), use_secret
            )
        except Exception as exc:
            _facade().logger.exception("op=13 签名失败 app_id=%s", inbound_app_id_13)
            raise _facade().HTTPException(500, f"签名失败: {exc}")
        _facade().logger.info(
            "op=13 握手成功 app_id=%s chosen_secret=%s", inbound_app_id_13 or "unknown", chosen_for
        )
        return _facade().JSONResponse({"plain_token": plain_token, "signature": sig_bytes.hex()})
    secrets_map = _facade()._all_known_app_secrets()
    verified = (
        any(
            (
                _facade()._verify_inbound_for(timestamp, body_bytes, sig, s)
                for s in secrets_map.values()
            )
        )
        if secrets_map
        else _facade().verify_inbound(timestamp, body_bytes, sig)
    )
    if not verified:
        _facade().logger.warning("QQ webhook 签名校验失败 ts=%s sig=%s", timestamp, sig[:16])
        raise _facade().HTTPException(401, "签名校验失败")
    if op == 0:
        event_type = str(envelope.get("t") or "")
        payload = envelope.get("d") or {}
        inbound_app_id = (
            forced_app_id
            or request.headers.get("X-Union-Appid")
            or str((payload.get("bot") or {}).get("id") or "")
            or _facade()._qq_app_id()
        ).strip()
        _facade().asyncio.create_task(
            _facade().dispatch_to_employee(
                event_type,
                payload,
                app_id=inbound_app_id,
                employee_id_hint=forced_employee_id or "",
            )
        )
    return _facade().JSONResponse({})


@_facade().router.post("/push")
async def qq_push(
    body: _facade()._PushDTO, request: _facade().Request
) -> _facade().Dict[str, _facade().Any]:
    _facade()._check_admin(request)
    return await _facade()._send(
        body.kind, body.target_id, body.content, msg_id=body.msg_id, msg_seq=body.msg_seq
    )


@_facade().router.post("/cache/reload")
async def qq_reload_cache(request: _facade().Request) -> _facade().Dict[str, _facade().Any]:
    """让凭证 / BotContext 缓存立刻失效；admin CRUD 之后会自动调，
    这里也提供手动触发（运维侧排障用）。"""
    _facade()._check_admin(request)
    _facade().invalidate_creds_cache()
    _facade().invalidate_bot_ctx_cache()
    return {"ok": True}


def _ensure_runtime_ready() -> bool:
    try:
        import nacl as _nacl

        _nacl
    except Exception:
        _facade().logger.warning(
            "未安装 pynacl，butler_qq_bridge 不挂载（pip install pynacl 后可启用）"
        )
        return False
    if not _facade().is_configured():
        _facade().logger.info(
            "butler_qq_bridge：当前没有 QQ 凭证（账号池 + ENV 都空）；router 保留，发起请求时再次校验"
        )
    return True
