"""Private, account-owned receipts for binary API exports."""

import hashlib
import json
import mimetypes
import re
import time
import uuid
from email.message import Message
from pathlib import Path
from typing import Any

MAX_BYTES = 64 * 1024 * 1024
TTL_SECONDS = 24 * 60 * 60


class ApiArtifactError(ValueError):
    pass


def _root() -> Path:
    from app.utils.path_io.path_utils import get_data_dir

    root = Path(get_data_dir()) / "aiopen-private-artifacts"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def is_export_response(response: Any) -> bool:
    media = response.headers.get("content-type", "")
    disposition = response.headers.get("content-disposition", "")
    media = media.split(";", 1)[0].lower() if isinstance(media, str) else ""
    disposition = disposition if isinstance(disposition, str) else ""
    if disposition:
        return True
    if media == "application/json" or media.endswith("+json"):
        return False
    if media in {"text/csv", "text/tab-separated-values"} or (
        media and not media.startswith("text/")
    ):
        return True
    content = response.content
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8")
            return "\x00" in text or len(text) > 2000
        except UnicodeError:
            return True
    return False


def _prune_expired(root: Path, scope: dict[str, str]) -> None:
    # Only our committed, expired receipts for this account are disposable.
    for manifest in root.glob("*.json"):
        if manifest.is_symlink() or not re.fullmatch(r"[a-f0-9]{32}", manifest.stem):
            continue
        try:
            row = json.loads(manifest.read_text(encoding="utf-8"))
            if (
                row["artifact_id"] == manifest.stem
                and row["expires_at"] <= time.time()
                and all(row[key] == scope[key] for key in ("owner_id", "tenant_id"))
            ):
                manifest.unlink()
                (root / f"{manifest.stem}.bin").unlink(missing_ok=True)
        except (OSError, ValueError, KeyError, TypeError):
            continue


def save_api_export(response: Any, scope: dict[str, str]) -> dict[str, Any]:
    content = response.content
    if not isinstance(content, bytes) or len(content) > MAX_BYTES:
        raise ApiArtifactError("导出文件超过当前 64 MiB 保存限制，未生成完整下载回执")
    if not scope.get("owner_id") or not scope.get("tenant_id"):
        raise ApiArtifactError("导出文件缺少账号作用域")
    message = Message()
    message["Content-Disposition"] = response.headers.get("content-disposition", "")
    name = str(message.get_filename() or "export.bin").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)[:180] or "export.bin"
    media = (
        response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].lower()
    )
    if not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", media):
        media = "application/octet-stream"
    if not message.get_filename():
        name = "export" + (mimetypes.guess_extension(media) or ".bin")
    artifact_id = uuid.uuid4().hex
    metadata = {
        "artifact_id": artifact_id,
        "name": name,
        "mime_type": media,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "owner_id": scope["owner_id"],
        "tenant_id": scope["tenant_id"],
        "mod_id": scope.get("mod_id", ""),
        "expires_at": time.time() + TTL_SECONDS,
    }
    root = _root()
    _prune_expired(root, scope)
    payload = root / f"{artifact_id}.bin"
    manifest = root / f"{artifact_id}.json"
    try:
        with payload.open("xb") as stream:
            payload.chmod(0o600)
            stream.write(content)
        # The manifest is the commit marker. Readers never accept payload alone.
        with manifest.open("x", encoding="utf-8") as stream:
            manifest.chmod(0o600)
            json.dump(metadata, stream, ensure_ascii=False)
    except OSError:
        payload.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        raise
    return {
        "artifact_id": artifact_id,
        "artifact_type": "document_file",
        "name": name,
        "mime_type": media,
        "size": len(content),
        "sha256": metadata["sha256"],
        "expires_at": metadata["expires_at"],
        "uri": f"/api/aiopen/artifacts/{artifact_id}",
        "download_url": f"/api/aiopen/artifacts/{artifact_id}",
        "metadata": {
            "size": len(content),
            "sha256": metadata["sha256"],
            "expires_at": metadata["expires_at"],
            "authenticated_download": True,
        },
    }


def read_api_export(artifact_id: str) -> tuple[bytes, dict[str, Any]]:
    from app.application.aiopen.api_execution import authorized_api_request

    if not re.fullmatch(r"[a-f0-9]{32}", artifact_id):
        raise ApiArtifactError("导出文件不存在或已失效")
    root = _root()
    manifest, payload = root / f"{artifact_id}.json", root / f"{artifact_id}.bin"
    if manifest.is_symlink() or payload.is_symlink():
        raise ApiArtifactError("导出文件不可用")
    try:
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        if metadata["artifact_id"] != artifact_id or metadata["expires_at"] <= time.time():
            raise ApiArtifactError("导出文件不存在或已失效")
        with authorized_api_request({"mod_id": metadata["mod_id"]}) as (_, scope):
            if any(scope[key] != metadata[key] for key in ("owner_id", "tenant_id", "mod_id")):
                raise ApiArtifactError("导出文件不属于当前账号")
            if payload.stat().st_size > MAX_BYTES:
                raise ApiArtifactError("导出文件校验失败")
            content = payload.read_bytes()
            if (
                len(content) != metadata["size"]
                or hashlib.sha256(content).hexdigest() != metadata["sha256"]
            ):
                raise ApiArtifactError("导出文件校验失败")
            return content, metadata
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ApiArtifactError("导出文件不存在或已失效") from exc
