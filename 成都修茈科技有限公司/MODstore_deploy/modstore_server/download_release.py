"""官网下载版本 SSOT 读写 + installer 日推送回写。

单一真相源：``FHD/config/download_release.json``（可用 ``MODSTORE_DOWNLOAD_RELEASE_JSON`` 覆盖）。
- 全产品线 v10 锁：marketing/download/android 锚点恒 ``10.0.0``（见 ``FHD/VERSION.md``）。
- installer/major 日：P5 构建 → P6 推 COS → 调用 :func:`record_installer_push` 回写 ``last_push``，
  并刷新 market SPA 运行时读取的公开清单 ``market/public/download-release.json``（下载页 fetch 后无需重建即生效）。

本模块只动「下载版本元数据」，不改任何营销版本号（仍 10.0.0），不违反 v10 锁。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PUBLIC_KEYS = (
    "version_lock",
    "download_version",
    "android_version",
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
    except Exception:
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
    except Exception:
        # 兜底：与 SSOT 默认一致（v10 锁）
        return {
            "schema": "xcagi.download_release/v1",
            "version_lock": "v10",
            "marketing_version": "10.0.0",
            "download_version": "10.0.0",
            "android_version": "10.0.0",
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
    dv = str(r.get("download_version") or "10.0.0")
    base = str(r.get("cos_base_url") or "https://dl.xiu-ci.com").rstrip("/")
    out: Dict[str, Any] = {
        "schema": "xcagi.download_release.public/v1",
        "version_lock": str(r.get("version_lock") or "v10"),
        "download_version": dv,
        "android_version": str(r.get("android_version") or dv),
        "win_installer_mb": r.get("win_installer_mb") or 212,
        "cos_base_url": base,
        "release_root": f"{base}/xcagi-v{dv}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
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
        except Exception:  # noqa: BLE001
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
    """installer/major 日推送后回写 SSOT ``last_push`` 并刷新公开清单。

    不改 download_version（v10 锁 10.0.0）；只记录「这次 installer 日确实推过」+ 刷新站点清单。
    """
    rel = load_release(path=path)
    rel["last_push"] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "release_train": str(release_train or ""),
        "release_kind": str(release_kind or ""),
        "git_sha": str(git_sha or "") or None,
        "cos_uploaded": bool(cos_uploaded),
        "by": str(actor or ""),
    }
    saved = save_release(rel, path=path)
    written = write_public_manifests(rel)
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
        "last_push": rel["last_push"],
    }
