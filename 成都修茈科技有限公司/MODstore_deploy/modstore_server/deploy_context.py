"""部署档位（MODSTORE_DEPLOY_TIER）与进程可见的 Git/主机上下文。

三台机器（本地 / Mac mini staging / 生产）各自在环境中显式设置 tier；
可选 ``MODSTORE_GIT_SHA`` / ``GIT_SHA`` 在构建时注入，避免运行 `git`。
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

_VALID_TIERS = frozenset({"local", "staging", "production"})
_ALIASES = {"dev": "local", "sandbox": "staging", "prod": "production"}


def _repo_root() -> Path:
    env = os.environ.get("MODSTORE_REPO_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    p = Path(__file__).resolve()
    for depth in (3, 2, 4):
        if depth <= len(p.parents):
            cand = p.parents[depth - 1]
            if (cand / "MODstore_deploy" / "modstore_server").is_dir():
                return cand
    return p.parents[2]


def normalized_deploy_tier() -> str:
    raw = (
        (os.environ.get("MODSTORE_DEPLOY_TIER") or os.environ.get("DEPLOYMENT_ENV") or "")
        .strip()
        .lower()
    )
    if not raw:
        return "local"
    raw = _ALIASES.get(raw, raw)
    if raw not in _VALID_TIERS:
        logger.warning("unknown MODSTORE_DEPLOY_TIER/DEPLOYMENT_ENV %r — using local", raw)
        return "local"
    return raw


def is_production_tier() -> bool:
    return normalized_deploy_tier() == "production"


def resolve_git_sha() -> str:
    for key in ("MODSTORE_GIT_SHA", "GIT_SHA", "COMMIT_SHA"):
        g = (os.environ.get(key) or "").strip()
        if g:
            return g[:64]
    root = _repo_root()
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout.strip()[:64]
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.debug("git rev-parse unavailable: %s", e)
    return ""


def resolve_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return ""


def health_payload() -> Dict[str, Any]:
    tavily_ok = False
    try:
        from modstore_server.research_tools import tavily_api_key

        tavily_ok = bool(tavily_api_key())
    except Exception:
        pass
    return {
        "deploy_tier": normalized_deploy_tier(),
        "git_sha": resolve_git_sha(),
        "hostname": resolve_hostname(),
        "tavily_configured": tavily_ok,
    }
