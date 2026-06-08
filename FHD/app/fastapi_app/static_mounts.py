"""Vue 产物静态目录挂载。"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.utils.operational_errors import OPERATIONAL_ERRORS
from app.utils.path_utils import get_base_dir, resolve_fhd_repo_root

logger = logging.getLogger(__name__)


def resolve_xcmax_dashboard_dir() -> str | None:
    """XCMAX 仓根目录下的全景静态资源（XCAGI-Full-Pipeline.html 等）。"""
    env = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if env:
        root = os.path.abspath(env)
        if os.path.isfile(os.path.join(root, "XCAGI-Full-Pipeline.html")):
            return root
    fhd = resolve_fhd_repo_root()
    if fhd is not None:
        trial = fhd.parent
        if os.path.isfile(os.path.join(trial, "XCAGI-Full-Pipeline.html")):
            return str(trial)
    return None


def mount_xcmax_dashboard_static(app: FastAPI) -> None:
    """挂载 /xcmax-dashboard -> 仓根全景 HTML/JS/CSS（AutomationPolicy iframe）。"""
    directory = resolve_xcmax_dashboard_dir()
    if not directory:
        logger.warning("xcmax-dashboard 目录未找到，跳过挂载（需 XCAGI-Full-Pipeline.html 于仓根）")
        return
    try:
        app.mount(
            "/xcmax-dashboard",
            StaticFiles(directory=directory, html=True),
            name="xcmax_dashboard",
        )
        logger.info("Mounted xcmax-dashboard: /xcmax-dashboard -> %s", directory)
    except OPERATIONAL_ERRORS as e:
        logger.warning("挂载 /xcmax-dashboard 失败: %s", e)


def mount_vue_dist_public_static(app: FastAPI) -> None:
    """挂载与 Vite ``public/`` 对齐的根路径静态目录（须在 SPA fallback 之前）。"""
    vue_dist = os.path.join(get_base_dir(), "templates", "vue-dist")
    if not os.path.isdir(vue_dist):
        logger.warning("Vue dist 目录不存在，跳过 public 静态挂载: %s", vue_dist)
        return
    for sub in ("font-awesome", "startup", "yuangong", "workflow"):
        directory = os.path.join(vue_dist, sub)
        if not os.path.isdir(directory):
            continue
        mount_path = f"/{sub}"
        try:
            app.mount(mount_path, StaticFiles(directory=directory), name=f"vue-dist-{sub}")
            logger.info("Mounted Vue static: %s -> %s", mount_path, directory)
        except OPERATIONAL_ERRORS as e:
            logger.warning("挂载 %s 失败: %s", mount_path, e)


def mount_vue_dist_assets_dir(app: FastAPI) -> None:
    """挂载 Vite 产物 ``vue-dist/assets`` 到 ``/assets``（须在 SPA fallback 之前）。"""
    vue_dist = os.path.join(get_base_dir(), "templates", "vue-dist")
    assets_dir = os.path.join(vue_dist, "assets")
    if not os.path.isdir(assets_dir):
        logger.warning("Vue dist assets 目录不存在，跳过 /assets 挂载: %s", assets_dir)
        return
    try:
        app.mount("/assets", StaticFiles(directory=assets_dir), name="vue_dist_assets")
        logger.info("Mounted Vue dist assets: /assets -> %s", assets_dir)
    except OPERATIONAL_ERRORS as e:
        logger.warning("挂载 /assets 失败: %s", e)
