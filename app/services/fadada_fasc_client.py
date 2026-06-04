"""法大大 FASC OpenAPI v5.1 客户端（签名算法与 @fddnpm/fasc-openapi-node-sdk 一致）。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FASC_SUCCESS_CODE = "100000"
FASC_SUB_VERSION = "5.1"
DEFAULT_SERVER_URL = "https://api.fadada.com/api/v5"


@dataclass(frozen=True)
class FascConfig:
    app_id: str
    app_secret: str
    server_url: str
    open_corp_id: str
    sign_template_id: str
    sign_actor_id: str = "甲方"
    callback_url: str = ""

    @classmethod
    def from_env(cls) -> FascConfig | None:
        app_id = (os.environ.get("FADADA_APP_ID") or "").strip()
        app_secret = (os.environ.get("FADADA_APP_SECRET") or "").strip()
        open_corp_id = (
            os.environ.get("FADADA_OPEN_CORP_ID") or os.environ.get("FADADA_OPPEN_CORP_ID") or ""
        ).strip()
        sign_template_id = (os.environ.get("FADADA_SIGN_TEMPLATE_ID") or "").strip()
        if not (app_id and app_secret and open_corp_id and sign_template_id):
            return None
        server = (os.environ.get("FADADA_SERVER_URL") or DEFAULT_SERVER_URL).strip().rstrip("/")
        return cls(
            app_id=app_id,
            app_secret=app_secret,
            server_url=server,
            open_corp_id=open_corp_id,
            sign_template_id=sign_template_id,
            sign_actor_id=(os.environ.get("FADADA_SIGN_ACTOR_ID") or "甲方").strip() or "甲方",
            callback_url=(os.environ.get("FADADA_CALLBACK_URL") or "").strip(),
        )


def fasc_configured() -> bool:
    return FascConfig.from_env() is not None


def _compact_json(data: Any) -> str:
    return json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"))


def _format_sign_string(params: dict[str, str]) -> str:
    cleaned = {k: str(v) for k, v in params.items() if v is not None and str(v) != ""}
    parts = [f"{k}={cleaned[k]}" for k in sorted(cleaned)]
    return "&".join(parts)


def fasc_sign(*, sign_str: str, timestamp: str, app_secret: str) -> str:
    """与 fasc-openapi-node-sdk Xn.sign 一致。"""
    sha_hex = hashlib.sha256(sign_str.encode("utf-8")).hexdigest()
    key = hmac.new(app_secret.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(key, sha_hex.encode("utf-8"), hashlib.sha256).hexdigest()


def _sign_headers(
    *,
    cfg: FascConfig,
    timestamp: str,
    nonce: str,
    biz_content: str | None,
    access_token: str | None,
) -> dict[str, str]:
    sign_params: dict[str, str] = {
        "X-FASC-App-Id": cfg.app_id,
        "X-FASC-Sign-Type": "HMAC-SHA256",
        "X-FASC-Timestamp": timestamp,
        "X-FASC-Nonce": nonce,
        "X-FASC-Api-SubVersion": FASC_SUB_VERSION,
    }
    if access_token:
        sign_params["X-FASC-AccessToken"] = access_token
        sign_params["bizContent"] = biz_content or ""
    else:
        sign_params["X-FASC-Grant-Type"] = "client_credential"
    sign = fasc_sign(
        sign_str=_format_sign_string(sign_params),
        timestamp=timestamp,
        app_secret=cfg.app_secret,
    )
    headers = {
        "X-FASC-App-Id": cfg.app_id,
        "X-FASC-Sign-Type": "HMAC-SHA256",
        "X-FASC-Timestamp": timestamp,
        "X-FASC-Nonce": nonce,
        "X-FASC-Api-SubVersion": FASC_SUB_VERSION,
        "X-FASC-Sign": sign,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if access_token:
        headers["X-FASC-AccessToken"] = access_token
    else:
        headers["X-FASC-Grant-Type"] = "client_credential"
    return headers


_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


class FascOpenApiClient:
    def __init__(self, cfg: FascConfig, *, timeout: float = 30.0) -> None:
        self.cfg = cfg
        self.timeout = timeout

    def _post(
        self, path: str, biz: dict[str, Any] | None, *, access_token: str | None
    ) -> dict[str, Any]:
        path = path if path.startswith("/") else f"/{path}"
        url = f"{self.cfg.server_url}{path}"
        timestamp = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex[:32]
        biz_json = _compact_json(biz) if biz is not None else ""
        headers = _sign_headers(
            cfg=self.cfg,
            timestamp=timestamp,
            nonce=nonce,
            biz_content=biz_json if access_token else None,
            access_token=access_token,
        )
        data: dict[str, str] | None = None
        if access_token:
            data = {"bizContent": biz_json}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers, data=data)
        try:
            body = resp.json()
        except Exception as exc:
            raise RuntimeError(f"法大大响应非 JSON: HTTP {resp.status_code}") from exc
        if not isinstance(body, dict):
            raise RuntimeError("法大大响应格式异常")
        code = str(body.get("code") or "")
        if code != FASC_SUCCESS_CODE:
            msg = body.get("msg") or body.get("message") or body
            raise RuntimeError(f"法大大 API 错误 [{code}]: {msg}")
        data_block = body.get("data")
        return data_block if isinstance(data_block, dict) else {}

    def get_access_token(self, *, force: bool = False) -> str:
        now = time.time()
        if (
            not force
            and _token_cache.get("token")
            and float(_token_cache.get("expires_at") or 0) > now + 30
        ):
            return str(_token_cache["token"])
        data = self._post("/service/get-access-token", None, access_token=None)
        token = str(data.get("accessToken") or data.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("法大大未返回 accessToken")
        expires_in = int(data.get("expiresIn") or data.get("expires_in") or 7200)
        _token_cache["token"] = token
        _token_cache["expires_at"] = now + max(60, expires_in - 120)
        return token

    def api_post(self, path: str, biz: dict[str, Any]) -> dict[str, Any]:
        token = self.get_access_token()
        return self._post(path, biz, access_token=token)

    def create_sign_task_with_template(
        self,
        *,
        subject: str,
        party_b_name: str,
        trans_reference_id: str,
        auto_start: bool = True,
    ) -> str:
        biz: dict[str, Any] = {
            "signTaskSubject": subject[:200] or "合同签署",
            "signTemplateId": self.cfg.sign_template_id,
            "autoStart": auto_start,
            "transReferenceId": trans_reference_id,
            "initiator": {"idType": "corp", "openId": self.cfg.open_corp_id},
            "actors": [
                {
                    "actor": {
                        "actorId": self.cfg.sign_actor_id,
                        "actorType": "person",
                        "actorName": party_b_name[:100] or "签署方",
                        "permissions": ["fill", "sign"],
                        "sendNotification": False,
                    },
                    "signConfigInfo": {
                        "blockHere": False,
                        "requestVerifyFree": False,
                    },
                }
            ],
        }
        if self.cfg.callback_url:
            biz["callbackUrl"] = self.cfg.callback_url
        data = self.api_post("/sign-task/create-with-template", biz)
        task_id = str(data.get("signTaskId") or data.get("sign_task_id") or "").strip()
        if not task_id:
            raise RuntimeError(f"法大大未返回 signTaskId: {data}")
        return task_id

    def get_actor_sign_url(self, *, sign_task_id: str, actor_id: str | None = None) -> str:
        aid = (actor_id or self.cfg.sign_actor_id).strip()
        data = self.api_post(
            "/sign-task/actor/get-url",
            {"signTaskId": sign_task_id, "actorId": aid},
        )
        url = str(
            data.get("actorSignTaskUrl")
            or data.get("actorSignTaskEmbedUrl")
            or data.get("actor_sign_task_url")
            or ""
        ).strip()
        if not url:
            raise RuntimeError(f"法大大未返回签署链接: {data}")
        return url


def verify_fadada_callback_signature(
    headers: dict[str, str],
    biz_content: str,
    *,
    app_secret: str | None = None,
) -> bool:
    cfg = FascConfig.from_env()
    secret = (app_secret or (cfg.app_secret if cfg else "") or "").strip()
    if not secret:
        return False
    app_id = (headers.get("X-FASC-App-Id") or headers.get("x-fasc-app-id") or "").strip()
    sign_type = (headers.get("X-FASC-Sign-Type") or "HMAC-SHA256").strip()
    timestamp = (headers.get("X-FASC-Timestamp") or "").strip()
    nonce = (headers.get("X-FASC-Nonce") or "").strip()
    event = (headers.get("X-FASC-Event") or "").strip()
    incoming = (headers.get("X-FASC-Sign") or "").strip()
    if not (app_id and timestamp and nonce and incoming):
        return False
    sign_params = {
        "X-FASC-App-Id": app_id,
        "X-FASC-Sign-Type": sign_type,
        "X-FASC-Timestamp": timestamp,
        "X-FASC-Nonce": nonce,
        "X-FASC-Event": event,
        "bizContent": biz_content or "",
    }
    expected = fasc_sign(
        sign_str=_format_sign_string(sign_params),
        timestamp=timestamp,
        app_secret=secret,
    )
    return hmac.compare_digest(expected, incoming)


def parse_fadada_callback_biz(biz_content: str) -> dict[str, Any]:
    raw = (biz_content or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("fadada callback bizContent 非 JSON")
        return {}


def fadada_event_is_signed(event: str, biz: dict[str, Any]) -> bool:
    ev = (event or "").strip().lower()
    if ev in ("sign-task-signed", "sign_task_signed", "sign-task-finished"):
        return True
    status = str(biz.get("signTaskStatus") or biz.get("sign_task_status") or "").lower()
    return status in ("signed", "finish", "finished", "completed", "complete", "task_finished")
