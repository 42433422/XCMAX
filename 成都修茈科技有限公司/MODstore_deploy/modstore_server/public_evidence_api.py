"""能力中心证据原件：私有 COS 桶 + 短时效预签名 URL（无鉴权、只读）。

官网能力中心详情页的截图 / 录像链接指向 ``/api/public/evidence/<name>``：

* ``name`` 必须登记在构建产物 ``data/capabilities/evidence-index.json`` 中（白名单），
  后端绝不按任意路径签名，桶本身保持私有，不开公网读；
* 首次访问时以服务端密钥 HEAD 对象，``x-cos-meta-sha256`` 与大小都和索引一致才签发
  预签名 GET URL（302）；未配置 COS、COS 不可用或哈希不符时 302 到站内副本
  ``/capabilities/assets/evidence/<name>``，页面照常可用；
* ``/verify/<name>`` 返回索引登记值与对象元数据的对照，供页面「核验哈希」展示。

所需环境变量（缺任一 COS 项即视为未启用，全部回退站内副本）::

    XCMAX_EVIDENCE_COS_BUCKET      例 xcagi-evidence-1374207682
    XCMAX_EVIDENCE_COS_REGION      例 ap-chengdu
    XCMAX_EVIDENCE_COS_SECRET_ID   只读子账号（GetObject / HeadObject，限该桶）
    XCMAX_EVIDENCE_COS_SECRET_KEY
    XCMAX_EVIDENCE_URL_TTL_SECONDS 预签名有效期，默认 1800，范围 60–7200
    XCMAX_EVIDENCE_INDEX_PATH      可选，默认 <官网根>/data/capabilities/evidence-index.json
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public/evidence", tags=["public"])

LOCAL_PREFIX = "/capabilities/assets/evidence/"
ALLOWED_KEY_PREFIXES = ("FHD/docs/evidence/", "成都修茈科技有限公司/capabilities/assets/evidence/")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,254}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_INDEX = Path(__file__).resolve().parents[2] / "data" / "capabilities" / "evidence-index.json"
_OK_CACHE_SECONDS = 600
_FAIL_CACHE_SECONDS = 60
_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


@dataclass(frozen=True)
class CosConfig:
    bucket: str
    region: str
    secret_id: str
    secret_key: str
    ttl: int

    @property
    def host(self) -> str:
        return f"{self.bucket}.cos.{self.region}.myqcloud.com"


def cos_config() -> CosConfig | None:
    bucket = os.environ.get("XCMAX_EVIDENCE_COS_BUCKET", "").strip()
    region = os.environ.get("XCMAX_EVIDENCE_COS_REGION", "").strip()
    secret_id = os.environ.get("XCMAX_EVIDENCE_COS_SECRET_ID", "").strip()
    secret_key = os.environ.get("XCMAX_EVIDENCE_COS_SECRET_KEY", "").strip()
    if not (bucket and region and secret_id and secret_key):
        return None
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{1,61}-\d{5,}", bucket) or not re.fullmatch(r"[a-z]{2}-[a-z\-]+", region):
        logger.warning("evidence COS bucket/region malformed; falling back to local copies")
        return None
    try:
        ttl = int(os.environ.get("XCMAX_EVIDENCE_URL_TTL_SECONDS", "1800"))
    except ValueError:
        ttl = 1800
    return CosConfig(bucket, region, secret_id, secret_key, max(60, min(ttl, 7200)))


# ---------------------------------------------------------------- signing


def cos_authorization(
    secret_id: str,
    secret_key: str,
    method: str,
    key: str,
    headers: dict[str, str],
    start: int,
    end: int,
) -> str:
    """腾讯云 COS 请求签名（q-sign-algorithm=sha1），与官方 SDK 的 CosS3Auth 等价。

    ``headers`` 为参与签名的头（小写键）；不签 URL 参数。
    """

    def enc(value: str) -> str:
        return quote(value.encode("utf-8"), safe="-_.~")

    key_time = f"{start};{end}"
    signed = sorted((enc(k).lower(), enc(v)) for k, v in headers.items())
    http_string = "\n".join(
        [method.lower(), "/" + key.lstrip("/"), "", "&".join(f"{k}={v}" for k, v in signed), ""]
    )
    string_to_sign = f"sha1\n{key_time}\n{hashlib.sha1(http_string.encode('utf-8')).hexdigest()}\n"
    sign_key = hmac.new(secret_key.encode(), key_time.encode(), hashlib.sha1).hexdigest()
    signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()
    return (
        f"q-sign-algorithm=sha1&q-ak={secret_id}&q-sign-time={key_time}&q-key-time={key_time}"
        f"&q-header-list={';'.join(k for k, _ in signed)}&q-url-param-list=&q-signature={signature}"
    )


def object_url(cfg: CosConfig, key: str) -> str:
    return f"https://{cfg.host}/{quote(key.encode('utf-8'), safe='/-_.~')}"


def presigned_get_url(cfg: CosConfig, key: str, now: int | None = None) -> str:
    start = int(time.time() if now is None else now) - 60
    auth = cos_authorization(
        cfg.secret_id, cfg.secret_key, "get", key, {"host": cfg.host}, start, start + 60 + cfg.ttl
    )
    return f"{object_url(cfg, key)}?{auth}"


# ---------------------------------------------------------------- index


class _IndexCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: Path | None = None
        self._mtime: float | None = None
        self._assets: dict[str, dict[str, Any]] = {}

    def path(self) -> Path:
        raw = os.environ.get("XCMAX_EVIDENCE_INDEX_PATH", "").strip()
        return Path(raw) if raw else _DEFAULT_INDEX

    def assets(self) -> dict[str, dict[str, Any]]:
        path = self.path()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return {}
        with self._lock:
            if path != self._path or mtime != self._mtime:
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    raw_assets = doc.get("assets", {}) if isinstance(doc, dict) else {}
                except (OSError, ValueError):
                    logger.exception("evidence index unreadable: %s", path)
                    raw_assets = {}
                self._assets = {
                    name: entry
                    for name, entry in raw_assets.items()
                    if _valid_entry(name, entry)
                }
                self._path, self._mtime = path, mtime
            return self._assets


def _valid_entry(name: Any, entry: Any) -> bool:
    return (
        isinstance(name, str)
        and bool(_NAME_RE.match(name))
        and isinstance(entry, dict)
        and isinstance(entry.get("key"), str)
        and entry["key"].startswith(ALLOWED_KEY_PREFIXES)
        and ".." not in entry["key"].split("/")
        and isinstance(entry.get("sha256"), str)
        and bool(_SHA_RE.match(entry["sha256"]))
        and type(entry.get("size")) is int
    )


_INDEX = _IndexCache()


def lookup(name: str) -> dict[str, Any] | None:
    if not _NAME_RE.match(name or ""):
        return None
    return _INDEX.assets().get(name)


# ---------------------------------------------------------------- verification


_VERIFY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_VERIFY_LOCK = threading.Lock()


def _transport() -> httpx.AsyncBaseTransport | None:
    """测试注入点。"""
    return None


async def head_object(cfg: CosConfig, key: str) -> httpx.Response:
    now = int(time.time())
    auth = cos_authorization(cfg.secret_id, cfg.secret_key, "head", key, {"host": cfg.host}, now - 60, now + 300)
    async with httpx.AsyncClient(timeout=5.0, transport=_transport()) as client:
        return await client.head(object_url(cfg, key), headers={"Authorization": auth})


async def verify_object(name: str, entry: dict[str, Any], cfg: CosConfig | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "key": entry["key"],
        "expected_sha256": entry["sha256"],
        "expected_size": entry["size"],
        "cos_configured": cfg is not None,
        "cos_sha256": None,
        "cos_size": None,
        "cos_version_id": None,
        "match": False,
        "reason": None,
    }
    if cfg is None:
        result["reason"] = "对象存储未启用"
        return result
    cache_key = f"{cfg.bucket}/{entry['key']}#{entry['sha256']}"
    now = time.monotonic()
    with _VERIFY_LOCK:
        cached = _VERIFY_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return {**result, **cached[1]}
    found: dict[str, Any] = {}
    try:
        resp = await head_object(cfg, entry["key"])
        if resp.status_code != 200:
            found["reason"] = f"对象存储返回 HTTP {resp.status_code}"
        else:
            sha = (resp.headers.get("x-cos-meta-sha256") or "").strip().lower()
            try:
                size = int(resp.headers.get("content-length", ""))
            except ValueError:
                size = None
            found.update(cos_sha256=sha or None, cos_size=size, cos_version_id=resp.headers.get("x-cos-version-id"))
            if not sha:
                found["reason"] = "对象缺少 x-cos-meta-sha256 元数据"
            elif sha != entry["sha256"]:
                found["reason"] = "对象 SHA-256 与索引登记不一致"
            elif size != entry["size"]:
                found["reason"] = "对象大小与索引登记不一致"
            else:
                found["match"] = True
    except httpx.HTTPError as exc:
        found["reason"] = f"对象存储不可达：{type(exc).__name__}"
    ttl = _OK_CACHE_SECONDS if found.get("match") else _FAIL_CACHE_SECONDS
    with _VERIFY_LOCK:
        _VERIFY_CACHE[cache_key] = (now + ttl, found)
    return {**result, **found}


def _local(name: str) -> RedirectResponse:
    return RedirectResponse(LOCAL_PREFIX + quote(name, safe=""), status_code=302, headers=dict(_NO_STORE))


# ---------------------------------------------------------------- routes


@router.get("/_status", summary="能力中心证据原件服务状态（不含任何密钥）")
async def evidence_status() -> JSONResponse:
    cfg = cos_config()
    return JSONResponse(
        {
            "ok": True,
            "cos_configured": cfg is not None,
            "bucket": cfg.bucket if cfg else None,
            "region": cfg.region if cfg else None,
            "url_ttl_seconds": cfg.ttl if cfg else None,
            "index_assets": len(_INDEX.assets()),
        },
        headers=dict(_NO_STORE),
    )


@router.get("/verify/{name}", summary="对照索引 SHA-256 与 COS 对象元数据")
async def verify_evidence(name: str) -> JSONResponse:
    entry = lookup(name)
    if entry is None:
        raise HTTPException(status_code=404, detail="evidence not registered")
    result = await verify_object(name, entry, cos_config())
    result["ok"] = True
    result["checked_at"] = int(time.time())
    return JSONResponse(result, headers=dict(_NO_STORE))


@router.api_route("/{name}", methods=["GET", "HEAD"], summary="跳转到证据原件（COS 预签名或站内副本）")
async def get_evidence(name: str) -> RedirectResponse:
    entry = lookup(name)
    if entry is None:
        raise HTTPException(status_code=404, detail="evidence not registered")
    cfg = cos_config()
    if cfg is None:
        return _local(name)
    result = await verify_object(name, entry, cfg)
    if not result["match"]:
        logger.warning("evidence %s served from local copy: %s", name, result.get("reason"))
        return _local(name)
    return RedirectResponse(presigned_get_url(cfg, entry["key"]), status_code=302, headers=dict(_NO_STORE))
