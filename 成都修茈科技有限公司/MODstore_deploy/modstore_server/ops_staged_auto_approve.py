"""低风险 OpsStagedChange 自动审批部署（无需邮件 token）。"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: str = "0") -> bool:
    raw = (os.environ.get(name, default) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _max_files() -> int:
    try:
        return max(1, int(os.environ.get("MODSTORE_OPS_STAGED_AUTO_MAX_FILES", "24")))
    except ValueError:
        return 24


def release_slo_halt_active() -> bool:
    """Block auto-merge/deploy when post-deploy smoke fails (release SLO)."""
    halt = _env_bool("MODSTORE_RELEASE_SLO_HALT", "0") or _env_bool(
        "MODSTORE_SLO_HALT_AUTO_MERGE", "0"
    )
    if not halt:
        return False
    try:
        from modstore_server.post_deploy_smoke import run_post_deploy_smoke

        smoke = run_post_deploy_smoke()
        if smoke.get("skipped"):
            return False
        return not bool(smoke.get("ok"))
    except Exception:
        logger.exception("release_slo_halt smoke check failed")
        return True


# 高风险路径黑名单：命中任一即视为中/高风险，必须走人工 ADMIN 门（对标大厂：
# auto-merge 仅放行真正低风险变更，安全/数据/基础设施/发布管线变更一律人审）。
_BLOCKED_PATTERNS = (
    # 数据/迁移（不可逆）
    "migrations/",
    "alembic/",
    "models.py",
    "catalog_data",
    # 密钥/认证/支付（安全关键）
    ".env",
    "secret",
    "credential",
    "token",
    "auth/",
    "rbac",
    "payment",
    "wallet",
    "/security",
    # 依赖/锁（供应链）
    "requirements",
    "package-lock",
    "pyproject.toml",
    "uv.lock",
    "pom.xml",
    "build.gradle",
    # 基础设施/发布管线（爆炸半径大）
    "dockerfile",
    "/k8s/",
    "charts/",
    "helm",
    "nginx",
    ".github/workflows",
    "deploy",
)


def blocked_pattern_hit(diff_summary: str) -> str:
    """返回命中的高风险路径模式（用于审计/日志），未命中返回空串。"""
    low = (diff_summary or "").lower()
    for pat in _BLOCKED_PATTERNS:
        if pat in low:
            return pat
    return ""


def should_auto_approve_staged(*, files_changed_count: int, diff_summary: str = "") -> bool:
    if not _env_bool("MODSTORE_OPS_STAGED_AUTO_APPROVE", "0"):
        return False
    if release_slo_halt_active():
        logger.warning("ops staged auto-approve blocked: MODSTORE_RELEASE_SLO_HALT / smoke failed")
        return False
    if files_changed_count <= 0 or files_changed_count > _max_files():
        return False
    hit = blocked_pattern_hit(diff_summary)
    if hit:
        logger.info("ops staged auto-approve blocked: high-risk path matched '%s'", hit)
        return False
    return True


def try_auto_deploy_staged_change(staged_id: int) -> Optional[Dict[str, Any]]:
    """若符合低风险策略则直接 deploy_staged_change。"""
    if staged_id <= 0 or not _env_bool("MODSTORE_OPS_STAGED_AUTO_APPROVE", "0"):
        return None
    try:
        from modstore_server.models import OpsStagedChange, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = session.get(OpsStagedChange, int(staged_id))
            if row is None or row.status != "pending":
                return None
            files_n = int(row.files_changed_count or 0)
            diff = str(row.diff_summary or "")
        if not should_auto_approve_staged(files_changed_count=files_n, diff_summary=diff):
            logger.info(
                "ops staged auto-approve skipped id=%s files=%s",
                staged_id,
                files_n,
            )
            return None
        from modstore_server.approval_dispatcher import deploy_staged_change

        out = deploy_staged_change(int(staged_id))
        logger.info("ops staged auto-deploy id=%s ok=%s", staged_id, out.get("ok"))
        return out
    except Exception:
        logger.exception("try_auto_deploy_staged_change failed id=%s", staged_id)
        return {"ok": False, "error": "auto deploy failed"}
