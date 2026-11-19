"""Device-only workspace. The LAN listener exposes only encrypted replication."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import threading
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import psutil
import uvicorn
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response

from app.application.local_workspace import LocalWorkspace, WorkspaceChanged
from app.desktop_runtime.desktop_runtime_paths import get_desktop_data_dir, is_desktop_mode
from app.fastapi_routes.mobile_extensions.pairing_helpers import _guess_lan_ipv4

router = APIRouter(prefix="/api/local-workspace", tags=["local-workspace"])
logger = logging.getLogger(__name__)
_PEER_PATH = "/api/local-workspace/peer"
_REQUEST_AAD = b"xcagi-local-workspace-request-v1"
_RESPONSE_AAD = b"xcagi-local-workspace-response-v1"
_PACKET_LIMIT = 2 * 1024 * 1024
_BATCH_LIMIT = 100
_PAYLOAD_LIMIT = _PACKET_LIMIT * 3 // 4 - 2048
_LAN_RANGES = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
)


def _private_ipv4(host: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        return False
    return any(ip in network for network in _LAN_RANGES)


def _lan_address() -> str:
    preferred = _guess_lan_ipv4()
    if _private_ipv4(preferred):
        return preferred
    for addresses in psutil.net_if_addrs().values():
        for address in addresses:
            if address.family == socket.AF_INET and _private_ipv4(address.address):
                return address.address
    return ""


def _loopback(host: str | None) -> bool:
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return host == "localhost"


def _desktop_request(request: Request) -> None:
    if not is_desktop_mode() or request.client is None or not _loopback(request.client.host):
        raise HTTPException(404)
    if request.headers.get("x-xcagi-desktop-local") != "1":
        raise HTTPException(403, "请在本机桌面应用中打开工作台")
    try:
        host = urlsplit(f"http://{request.headers.get('host', '')}")
        if not _loopback(host.hostname) or host.username is not None or host.path:
            raise HTTPException(403, "工作区仅接受本机访问")
        origin = request.headers.get("origin")
        if origin:
            source = urlsplit(origin)
            if (
                not _loopback(source.hostname)
                or source.scheme not in {"http", "https"}
                or (
                    source.netloc not in {host.netloc, request.headers.get("x-forwarded-host")}
                    and request.headers.get("sec-fetch-site") != "same-origin"
                )
            ):
                raise HTTPException(403, "工作区仅接受本机访问")
        if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
            raise HTTPException(403, "工作区仅接受同源访问")
    except ValueError as exc:
        raise HTTPException(403, "无效的本机来源") from exc


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value: object) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid envelope")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


async def _bounded_json(request: Request) -> dict:
    buf = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                if len(buf) + len(chunk) > _PACKET_LIMIT:
                    raise HTTPException(413, "工作区批次过大")
                buf.extend(chunk)
    except TimeoutError as exc:
        raise HTTPException(408, "工作区消息接收超时") from exc
    try:
        value = json.loads(buf)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HTTPException(400, "无效的工作区消息") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "无效的工作区消息")
    return value


def _workspace_id(payload: dict) -> str:
    value = payload.get("workspace_id")
    if not isinstance(value, str) or not value:
        raise ValueError("缺少工作区标识")
    return value


def _push(store: LocalWorkspace, payload: dict) -> dict:
    ops = payload.get("operations")
    if not isinstance(ops, list) or not 1 <= len(ops) <= _BATCH_LIMIT:
        raise ValueError("无效的工作区变更批次")
    result = store.apply(ops, workspace_id=_workspace_id(payload))
    return {
        "accepted": [r["op_id"] for r in result["results"] if r["status"] == "applied"],
        "conflicts": [
            {"op_id": r["op_id"], "current": r["record"]}
            for r in result["results"]
            if r["status"] == "conflict"
        ],
    }


class LocalPeer:
    def __init__(self, root: Path) -> None:
        self.store = LocalWorkspace(root / "data" / "local-workspace.sqlite3")
        self.binding_path = root / "config" / "local-workspace-peer.json"
        self.lock = threading.RLock()
        self.invitation: tuple[bytes, float, str] | None = None
        self.binding = self._load_binding()
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self.port = int(self.binding.get("port", 0))

    def _load_binding(self) -> dict:
        if not self.binding_path.is_file():
            return {}
        result = json.loads(self.binding_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or len(_decode(result.get("key"))) != 32:
            raise ValueError("Invalid stored workspace binding")
        return result

    def _save_binding(self, value: dict) -> None:
        if not value:
            self.binding_path.unlink(missing_ok=True)
        else:
            self.binding_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.binding_path.with_suffix(".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.binding_path)
        self.binding = value

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name != "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", self.port))
            listener.listen(16)
            self.port = listener.getsockname()[1]
            app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
            app.add_api_route(_PEER_PATH, self.exchange, methods=["POST"])
            self.server = uvicorn.Server(
                uvicorn.Config(
                    app, access_log=False, proxy_headers=False, lifespan="off", limit_concurrency=16
                )
            )
            self.thread = threading.Thread(
                target=self.server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            self.thread.start()
        except BaseException:
            listener.close()
            raise

    def issue(self) -> dict:
        with self.lock:
            if self.binding:
                raise HTTPException(409, "请先解除当前设备绑定")
            host = _lan_address()
            if not host:
                raise HTTPException(503, "请先将电脑连入局域网")
            self.start()
            key = secrets.token_bytes(32)
            self.invitation = (key, time.monotonic() + 300, self.store.status()["workspace_id"])
            return {
                "kind": "xcagi_local_workspace",
                "v": 1,
                "endpoint": f"http://{host}:{self.port}{_PEER_PATH}",
                "key": _encode(key),
            }

    def revoke(self) -> None:
        with self.lock:
            self._save_binding({})
            self.invitation = None
            # Keep the listener until process shutdown so an immediate re-pair
            # reuses its port. Requests cannot decrypt after key revocation.

    def status(self) -> dict:
        with self.lock:
            return {
                **self.store.status(),
                "paired": bool(self.binding),
                "archives": self.store.archives(),
            }

    def _snapshot(self, workspace_id: str) -> dict:
        snapshot = self.store.snapshot(workspace_id=workspace_id)
        if len(self._serialize(snapshot)) > _PAYLOAD_LIMIT:
            raise ValueError("首次同步的数据过大，请缩小起始工作区后再配对")
        return snapshot

    def _pull(self, payload: dict) -> dict:
        limit = payload.get("limit", _BATCH_LIMIT)
        if not isinstance(limit, int):
            raise ValueError("无效的分页大小")
        while True:
            page = self.store.pull(
                payload.get("after"), limit, workspace_id=self.binding["workspace_id"]
            )
            if len(self._serialize(page)) <= _PAYLOAD_LIMIT:
                return page
            if limit <= 1:
                raise ValueError("单条记录超过同步大小限制")
            limit = max(1, limit // 2)

    def _dispatch(self, payload: dict, key: bytes, invitation_id: str) -> dict:
        action = payload.get("action")
        if action == "bind":
            request_id = payload["request_id"]
            if self.binding:
                if request_id == self.binding.get("bind_request") and hashlib.sha256(
                    self._serialize(payload)
                ).hexdigest() == self.binding.get("bind_digest"):
                    return self._snapshot(self.binding["workspace_id"])
                raise ValueError("该配对码已经使用")
            if not invitation_id:
                raise ValueError("配对码已失效")
            origin = payload.get("origin")
            if origin == "mobile":
                records = payload.get("records")
                if not isinstance(records, list):
                    raise ValueError("缺少手机工作区数据")
                if len(self._serialize({"records": records})) > _PAYLOAD_LIMIT - 4096:
                    raise ValueError("首次同步的数据过大，请缩小起始工作区后再配对")
                snapshot = self.store.replace_from_mobile(records, workspace_id=invitation_id)
            elif origin == "desktop":
                snapshot = self._snapshot(invitation_id)
            else:
                raise ValueError("请选择起始设备")
            self._save_binding(
                {
                    "key": _encode(key),
                    "port": self.port,
                    "workspace_id": snapshot["workspace_id"],
                    "bind_request": request_id,
                    "bind_digest": hashlib.sha256(self._serialize(payload)).hexdigest(),
                }
            )
            self.invitation = None
            return snapshot
        if not self.binding or _workspace_id(payload) != self.binding["workspace_id"]:
            raise WorkspaceChanged("工作区已变化，请重新配对")
        if action == "push":
            return _push(self.store, payload)
        if action == "pull":
            return self._pull(payload)
        if action == "unbind":
            self.revoke()
            return {"unbound": True}
        raise ValueError("未知工作区操作")

    @staticmethod
    def _serialize(payload: dict) -> bytes:
        return json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()

    def process(self, envelope: dict) -> dict:
        with self.lock:
            invitation = self.invitation
            invitation_id = ""
            if self.binding:
                key = _decode(self.binding["key"])
            elif invitation and invitation[1] > time.monotonic():
                key, _, invitation_id = invitation
            else:
                raise HTTPException(401, "工作区未绑定")
            cipher = AESGCM(key)
            try:
                nonce = _decode(envelope.get("nonce"))
                if len(nonce) != 12:
                    raise ValueError("Invalid nonce")
                payload = json.loads(
                    cipher.decrypt(nonce, _decode(envelope.get("box")), _REQUEST_AAD)
                )
                request_id = payload.get("request_id") if isinstance(payload, dict) else None
                if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
                    raise ValueError("Invalid request")
            except (InvalidTag, ValueError, binascii.Error, RecursionError) as exc:
                raise HTTPException(401, "工作区消息认证失败") from exc
            try:
                result = {"success": True, **self._dispatch(payload, key, invitation_id)}
            except ValueError as exc:
                result = {"success": False, "error": str(exc)}
            raw = self._serialize({**result, "request_id": request_id})
            nonce = secrets.token_bytes(12)
            return {
                "nonce": _encode(nonce),
                "box": _encode(cipher.encrypt(nonce, raw, _RESPONSE_AAD)),
            }

    async def exchange(self, request: Request) -> dict:
        if (
            request.client is None
            or not (_private_ipv4(request.client.host) or _loopback(request.client.host))
            or request.headers.get("origin")
        ):
            raise HTTPException(403, "工作区只接受局域网设备直连")
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(self.process, await _bounded_json(request))


@lru_cache(maxsize=4)
def _peer(root: Path) -> LocalPeer:
    return LocalPeer(root)


_peer_cache_lock = threading.Lock()


def _current_peer() -> LocalPeer:
    with _peer_cache_lock:
        return _peer(get_desktop_data_dir())


def resume_local_workspace() -> None:
    if (
        is_desktop_mode()
        and (get_desktop_data_dir() / "config" / "local-workspace-peer.json").is_file()
    ):
        peer = _current_peer()
        with peer.lock:
            peer.start()


@router.get("/status", dependencies=[Depends(_desktop_request)])
def workspace_status() -> dict:
    return _current_peer().status()


@router.get("/records", dependencies=[Depends(_desktop_request)])
def workspace_records() -> dict:
    return _current_peer().store.snapshot()


@router.post("/records", dependencies=[Depends(_desktop_request)])
async def update_records(request: Request) -> dict:
    from starlette.concurrency import run_in_threadpool

    peer = _current_peer()
    payload = await _bounded_json(request)

    def apply() -> dict:
        with peer.lock:
            return _push(peer.store, payload)

    try:
        return await run_in_threadpool(apply)
    except WorkspaceChanged as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/pairing", dependencies=[Depends(_desktop_request)])
def issue_pairing(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return {"qr": _current_peer().issue()}
    except OSError as exc:
        raise HTTPException(503, "局域网监听不可用，请检查本机端口") from exc


@router.delete("/pairing", dependencies=[Depends(_desktop_request)])
def revoke_pairing() -> dict:
    peer = _current_peer()
    peer.revoke()
    return peer.status()


@router.post("/archives/{archive_id}/restore", dependencies=[Depends(_desktop_request)])
async def restore_archive(archive_id: str, request: Request) -> dict:
    peer = _current_peer()
    payload = await _bounded_json(request)
    with peer.lock:
        if peer.binding:
            raise HTTPException(409, "请先解除当前设备绑定")
        try:
            peer.store.restore_archive(archive_id, workspace_id=_workspace_id(payload))
        except WorkspaceChanged as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        peer.invitation = None
        return peer.status()
