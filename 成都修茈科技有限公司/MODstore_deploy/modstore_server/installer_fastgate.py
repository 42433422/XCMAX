"""FASTGATE — installer/major 快路径推 COS/OTA 前的强制门禁。

对齐时间轨 docs/xcagi-dashboard/emp-wf-radial-graph.js 的 FASTGATE 节点：
快路径全量推送（record_installer_push 写 download_release.json.last_push + 刷新官网公开清单）
前置 staging 验收 + /api/health + 市场下载页可达性检查，通过才放行；不过则阻断并标记回滚待审，
避免「即时路径绕过灰度/审批直推全量」与「未上传却虚假写 last_push」。

复用现有 post_deploy_smoke（探测 health + 市场下载页）。
开关 MODSTORE_INSTALLER_FASTGATE_ENABLED（默认 1）；smoke 自身被显式关闭时默认放行并记录。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name, default) or "").strip().lower() in ("1", "true", "yes", "on")


def verify_installer_fastgate(*, release_train: str, release_kind: str) -> Dict[str, Any]:
    """推 COS 前置门禁。返回 {ok, skipped, reason, smoke?, ...}；ok=False 时调用方应阻断推送。"""
    at = datetime.now(timezone.utc).isoformat()
    base = {"release_train": release_train, "release_kind": release_kind, "at": at}

    if not _env_bool("MODSTORE_INSTALLER_FASTGATE_ENABLED", "1"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "MODSTORE_INSTALLER_FASTGATE_ENABLED=0",
            **base,
        }

    try:
        from modstore_server.post_deploy_smoke import run_post_deploy_smoke

        smoke = run_post_deploy_smoke()
    except Exception as exc:  # noqa: BLE001
        logger.exception("installer fastgate: smoke probe error")
        return {"ok": False, "skipped": False, "reason": f"smoke probe error: {exc}", **base}

    if smoke.get("skipped"):
        # smoke 被显式关闭：不阻断（保留旧行为），但留痕
        return {
            "ok": True,
            "skipped": False,
            "reason": "smoke skipped (MODSTORE_POST_DEPLOY_SMOKE_ENABLED=0)",
            "smoke": smoke,
            **base,
        }

    ok = bool(smoke.get("ok"))
    logger.info(
        "installer fastgate release_train=%s kind=%s ok=%s",
        release_train,
        release_kind,
        ok,
    )
    return {
        "ok": ok,
        "skipped": False,
        "reason": (
            "staging/health + 市场下载页可达，放行推 COS"
            if ok
            else "staging/health 或市场下载页探测失败，阻断推 COS（转回滚待审）"
        ),
        "smoke": smoke,
        **base,
    }
