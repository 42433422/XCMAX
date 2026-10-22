# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""官网下载版本 SSOT 读写 + installer 日推送回写。

单一真相源：``FHD/config/download_release.json``（可用 ``MODSTORE_DOWNLOAD_RELEASE_JSON`` 覆盖）。
- 稳定版本及下载版本以 ``FHD/VERSION.md`` 和下载 SSOT 为准。
- installer/major 日：P5 构建 → P6 推 COS → 调用 :func:`record_installer_push` 记录 ``last_upload``。
  公开发布指针由带版本验收记录与制品哈希核验的发布同步流程单独维护。

本模块只动下载版本元数据，不擅自改变 ``FHD/VERSION.md`` 的稳定版本。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_PUBLIC_KEYS = (
    "version_lock",
    "download_version",
    "android_version",
    "android_git_sha",
    "release_ready",
    "active_skus",
    "frozen_skus",
    "primary_sku",
    "win_installer_mb",
    "cos_base_url",
)


def _repo_root() -> Path:
    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        return Path(mono).expanduser().resolve()
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        return repo_root()
    except RECOVERABLE_ERRORS:
        # modstore_server/ → MODstore_deploy/ → 成都修茈.../ → XCMAX/
        return Path(__file__).resolve().parents[3]


def ssot_path() -> Path:
    """下载版本 SSOT 路径（FHD/config/download_release.json）。"""
    env = (os.environ.get("MODSTORE_DOWNLOAD_RELEASE_JSON") or "").strip()
    if env:
        return Path(env).expanduser().resolve()

    candidates: List[Path] = []
    root = _repo_root()
    candidates.append(root / "FHD" / "config" / "download_release.json")
    candidates.append(root / "config" / "download_release.json")
    candidates.append(Path(__file__).resolve().parent.parent / "config" / "download_release.json")
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def load_release(*, path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or ssot_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS:
        # 兜底：与稳定版本 SSOT 默认一致
        return {
            "schema": "xcagi.download_release/v1",
            "version_lock": "1.0.0.0",
            "marketing_version": "1.0.0.0",
            "download_version": "1.0.0.0",
            "android_version": "1.0.0.0",
            "release_ready": False,
            "win_installer_mb": 212,
            "cos_base_url": "https://dl.xiu-ci.com",
            "last_push": {},
        }


def save_release(rel: Dict[str, Any], *, path: Optional[Path] = None) -> Path:
    p = path or ssot_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rel, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def public_subset(rel: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """市场 SPA 运行时读取的公开子集（/download-release.json）。"""
    r = rel or load_release()
    dv = str(r.get("download_version") or "1.0.0.0")
    base = str(r.get("cos_base_url") or "https://dl.xiu-ci.com").rstrip("/")
    out: Dict[str, Any] = {
        "schema": "xcagi.download_release.public/v1",
        "version_lock": str(r.get("version_lock") or "1.0.0.0"),
        "download_version": dv,
        "android_version": str(r.get("android_version") or dv),
        "android_git_sha": str(r.get("android_git_sha") or ""),
        "release_ready": bool(r.get("release_ready")),
        "active_skus": list(r.get("active_skus") or ["enterprise"]),
        "frozen_skus": list(r.get("frozen_skus") or ["personal"]),
        "primary_sku": str(r.get("primary_sku") or "enterprise"),
        "git_sha": str((r.get("last_push") or {}).get("git_sha") or ""),
        "win_installer_mb": r.get("win_installer_mb") or 212,
        "cos_base_url": base,
        "release_root": f"{base}/xcagi-v{dv}",
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest_url": f"{base}/xcagi-v{dv}/manifest.json",
        "auto_update_base": "https://xiu-ci.com/releases/stable",
    }
    # 官网可视化 /download/releases 依赖版本节点列表；生成公开清单时不得丢弃。
    history = r.get("release_history")
    if isinstance(history, list) and history:
        out["release_history"] = history
    return out


def public_manifest_targets() -> List[Path]:
    """需要写入公开清单的位置（market SPA public 源 + 可选 dist）。"""
    root = _repo_root()
    targets = [
        root
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "market"
        / "public"
        / "download-release.json",
        root / "FHD" / "MODstore" / "market" / "public" / "download-release.json",
    ]
    extra = (os.environ.get("MODSTORE_DOWNLOAD_RELEASE_PUBLIC_EXTRA") or "").strip()
    if extra:
        for raw in extra.split(os.pathsep):
            raw = raw.strip()
            if raw:
                targets.append(Path(raw).expanduser())
    return targets


def write_public_manifests(rel: Optional[Dict[str, Any]] = None) -> List[str]:
    """把公开子集写到所有 market public 目录（仅当父目录已存在，避免误建）。"""
    pub = public_subset(rel)
    written: List[str] = []
    for tgt in public_manifest_targets():
        try:
            if not tgt.parent.is_dir():
                continue
            tgt.write_text(json.dumps(pub, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written.append(str(tgt))
        except BOUNDARY_ERRORS:  # noqa: BLE001
            logger.exception("download_release: write public manifest failed %s", tgt)
    return written


def record_installer_push(
    *,
    release_train: str,
    release_kind: str,
    git_sha: Optional[str] = None,
    cos_uploaded: bool = False,
    actor: str = "installer-chain",
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """记录安装包上传事实，不将它当作发布验收或改写公开清单。

    ``cos_uploaded`` 仅表示上传器报告上传成功；版本、制品身份和客户验收由正式发布同步
    流程核实。这里不得改变 ``release_ready`` 或把候选 SHA 投影到当前公开下载指针。
    """
    rel = load_release(path=path)
    upload = {
        "at": datetime.now(UTC).isoformat(),
        "release_train": str(release_train or ""),
        "release_kind": str(release_kind or ""),
        "git_sha": str(git_sha or "") or None,
        "cos_uploaded": bool(cos_uploaded),
        "by": str(actor or ""),
    }
    # last_push is also the public release identity source; keep it unchanged.
    rel["last_upload"] = upload
    saved = save_release(rel, path=path)
    # Upload telemetry is not the accepted release identity. In particular, do not
    # regenerate the public pointer from this candidate's git_sha and the prior
    # version's release_ready/download URLs.
    written: List[str] = []
    logger.info(
        "download_release: installer push recorded rt=%s kind=%s cos=%s ssot=%s public=%s",
        release_train,
        release_kind,
        cos_uploaded,
        saved,
        len(written),
    )
    return {
        "ok": True,
        "ssot": str(saved),
        "public_written": written,
        "last_push": upload,  # Legacy caller receipt key; not the public SSOT identity.
    }
