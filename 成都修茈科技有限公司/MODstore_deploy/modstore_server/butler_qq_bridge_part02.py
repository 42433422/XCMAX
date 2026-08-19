# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.butler_qq_bridge")


def _load_creds_from_pool() -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """从账号池（DB + 密钥文件）拉一份当前生效的 QQ 凭证。

    任何环节出错都吞回 ``None``——让上层自动 fallback 到 ENV。这样即使
    DB 还没建表、字段缺失，也不至于让模块导入或 webhook 处理炸掉。
    """
    try:
        from modstore_server.ai_employee_account_api import lookup_active_account_for

        rec = lookup_active_account_for(_facade()._BUTLER_EMPLOYEE_ID, "qq")
        if not rec:
            return None
        secret = rec.get("secret") or {}
        app_id = str(secret.get("app_id") or rec.get("external_id") or "").strip()
        app_secret = str(secret.get("app_secret") or "").strip()
        bot_token = str(secret.get("bot_token") or "").strip()
        if not (app_id and app_secret and bot_token):
            return None
        return {
            "app_id": app_id,
            "app_secret": app_secret,
            "bot_token": bot_token,
            "sandbox": bool(rec.get("sandbox")),
            "source": "pool",
            "account_id": rec.get("id"),
        }
    except Exception as exc:
        _facade().logger.debug("从账号池读取 QQ 凭证失败，降级到 ENV：%s", exc)
        return None


def _load_creds_from_env() -> _facade().Dict[str, _facade().Any]:
    return {
        "app_id": _facade()._env("BUTLER_QQ_APP_ID"),
        "app_secret": _facade()._env("BUTLER_QQ_APP_SECRET"),
        "bot_token": _facade()._env("BUTLER_QQ_BOT_TOKEN"),
        "sandbox": _facade()._env("BUTLER_QQ_SANDBOX", "0") in ("1", "true", "yes", "on"),
        "source": "env",
        "account_id": None,
    }


def _resolve_creds() -> _facade().Dict[str, _facade().Any]:
    """统一入口：优先账号池、缺则 ENV，30s 一次缓存。"""
    now = _facade().time.time()
    if _facade()._creds_state.data and _facade()._creds_state.expires_at > now:
        return _facade()._creds_state.data
    creds = _facade()._load_creds_from_pool() or _facade()._load_creds_from_env()
    _facade()._creds_state.data = creds
    _facade()._creds_state.expires_at = now + _facade()._CREDS_CACHE_TTL_SECONDS
    return creds


def invalidate_creds_cache() -> None:
    """让下一次 ``_resolve_creds`` 重新查 DB——admin API 改完账号后可调用。"""
    _facade()._creds_state.data = {}
    _facade()._creds_state.expires_at = 0.0


def _qq_app_id() -> str:
    return _facade()._resolve_creds().get("app_id", "")


def _qq_app_secret() -> str:
    return _facade()._resolve_creds().get("app_secret", "")


def _qq_bot_token() -> str:
    return _facade()._resolve_creds().get("bot_token", "")


def _qq_sandbox() -> bool:
    return bool(_facade()._resolve_creds().get("sandbox", False))


def _qq_credential_source() -> str:
    """诊断用：当前凭证从哪来——pool / env / none。"""
    src = _facade()._resolve_creds().get("source") or ""
    if not _facade()._qq_app_id():
        return "none"
    return src


def _qq_api_base() -> str:
    return (
        "https://sandbox.api.sgroup.qq.com"
        if _facade()._qq_sandbox()
        else "https://api.sgroup.qq.com"
    )


def _qq_token_endpoint() -> str:
    return "https://bots.qq.com/app/getAppAccessToken"


def _own_llm() -> _facade().Tuple[str, str, str, _facade().Optional[str]]:
    """数字管家自带的"脑子"——这位 AI 员工的私人 LLM 凭证。

    返回 ``(provider, model, api_key, base_url)``。任一项缺失就返回空串/None；
    上层再决定是回退到 bridge_user 还是直接报错。
    """
    return (
        _facade()._env("BUTLER_QQ_LLM_PROVIDER"),
        _facade()._env("BUTLER_QQ_LLM_MODEL"),
        _facade()._env("BUTLER_QQ_LLM_API_KEY"),
        _facade()._env("BUTLER_QQ_LLM_BASE_URL") or None,
    )


def is_configured() -> bool:
    """是否已经配齐能正常跑的最小凭证集合。"""
    return bool(_facade()._qq_app_id() and _facade()._qq_app_secret() and _facade()._qq_bot_token())


def _derive_seed(secret: str) -> bytes:
    raw = secret.encode("utf-8")
    if not raw:
        raise ValueError("BUTLER_QQ_APP_SECRET 不能为空")
    while len(raw) < 32:
        raw = raw + raw
    return raw[:32]


def _signing_key_for(app_secret: str):
    from nacl.signing import SigningKey

    return SigningKey(_facade()._derive_seed(app_secret))


def _signing_key():
    """默认（数字管家）签名密钥。"""
    return _facade()._signing_key_for(_facade()._qq_app_secret())


def sign_payload(payload: bytes) -> bytes:
    return _facade()._signing_key().sign(payload).signature


def _sign_payload_for(payload: bytes, app_secret: str) -> bytes:
    return _facade()._signing_key_for(app_secret).sign(payload).signature


def verify_inbound(timestamp: str, body: bytes, signature_hex: str) -> bool:
    return _facade()._verify_inbound_for(timestamp, body, signature_hex, _facade()._qq_app_secret())


def _verify_inbound_for(timestamp: str, body: bytes, signature_hex: str, app_secret: str) -> bool:
    from nacl.exceptions import BadSignatureError

    if not (timestamp and signature_hex):
        return False
    try:
        sig = bytes.fromhex(signature_hex)
    except ValueError:
        return False
    msg = timestamp.encode("utf-8") + body
    verify_key = _facade()._signing_key_for(app_secret).verify_key
    try:
        verify_key.verify(msg, sig)
        return True
    except BadSignatureError:
        return False
    except Exception:
        return False


def _all_known_app_secrets() -> _facade().Dict[str, str]:
    """返回 ``{app_id: app_secret}``：ENV 默认 + 账号池中所有 QQ 机器人 +
    两位老员工（``_SPECIFIC_WEBHOOKS``）的静态条目。

    前两个来源已经覆盖大多数情况，第三个来源只是兜底——保证 webhook
    在 DB 没建表 / 账号还没建好时，老员工的 op=13 握手与业务事件
    验签依然能跑通。
    """
    result: _facade().Dict[str, str] = {}
    default_id = _facade()._qq_app_id()
    default_secret = _facade()._qq_app_secret()
    if default_id and default_secret:
        result[default_id] = default_secret
    try:
        from modstore_server.ai_employee_account_secrets import read_secret
        from modstore_server.models import get_session_factory
        from modstore_server.models_ai_accounts import AIEmployeeAccount

        sf = get_session_factory()
        with sf() as session:
            rows = (
                session.query(AIEmployeeAccount)
                .filter(AIEmployeeAccount.platform == "qq", AIEmployeeAccount.status == "active")
                .all()
            )
        for row in rows:
            sec = read_secret(platform="qq", account_id=int(row.id))
            if sec:
                aid = str(sec.get("app_id") or row.external_id or "").strip()
                asecret = str(sec.get("app_secret") or "").strip()
                if aid and asecret:
                    result[aid] = asecret
    except Exception as exc:
        _facade().logger.debug("_all_known_app_secrets 读账号池失败: %s", exc)
    for webhook_key, spec in _facade()._SPECIFIC_WEBHOOKS.items():
        aid = str(spec.get("app_id") or "").strip()
        if not aid:
            continue
        secret = _facade()._specific_app_secret(webhook_key)
        if secret:
            if result.get(aid) and result[aid] != secret:
                _facade().logger.info(
                    "QQ AppSecret 覆盖：app_id=%s 以 ENV/老员工专用解析为准（账号池值已忽略）", aid
                )
            result[aid] = secret
    return result


class _TokenState:
    __slots__ = ("token", "expires_at", "_lock")

    def __init__(self) -> None:
        self.token: str = ""
        self.expires_at: float = 0.0
        self._lock: _facade().Optional[_facade().asyncio.Lock] = None

    def _lock_or_create(self) -> _facade().asyncio.Lock:
        """Defer Lock() until an async caller has a running event loop (Py3.9 import-safe)."""
        if self._lock is None:
            self._lock = _facade().asyncio.Lock()
        return self._lock
