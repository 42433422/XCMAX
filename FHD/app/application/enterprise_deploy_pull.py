"""企业端：从 update 站检测并拉取更新（管理端只推送到中转站，企业端在此收取）。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

_DEPLOY_ERRORS = (
    OSError,
    subprocess.SubprocessError,
    RuntimeError,
    ValueError,
    json.JSONDecodeError,
    urllib.error.URLError,
    asyncio.TimeoutError,
)

StepStatus = Literal["pending", "running", "done", "error", "skipped"]

DEPLOY_ROOT = os.environ.get("FHD_DEPLOY_ROOT", "/opt/fhd-full")
MANIFEST_PATH = os.environ.get(
    "FHD_MANIFEST_PATH",
    "/var/www/update/releases/stable/server/fhd-manifest.json",
)
ARTIFACT_DIR = os.environ.get("FHD_ARTIFACT_DIR", str(Path(MANIFEST_PATH).parent))
MANIFEST_URL = (
    os.environ.get("XCMAX_UPDATE_MANIFEST_URL", "").strip()
    or "https://update.xcagi.com/releases/stable/server/fhd-manifest.json"
)
HUB_VUE_DIST = os.path.join(ARTIFACT_DIR, "vue-dist")
LOCAL_VUE_DIST = os.path.join(DEPLOY_ROOT, "templates", "vue-dist")
SERVICE_NAME = os.environ.get("FHD_SERVICE_NAME", "fhd-full.service")


def _read_deployed_sha256() -> str:
    path = Path(DEPLOY_ROOT) / ".deploy-sha256"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except _DEPLOY_ERRORS:
        return ""


def _read_local_manifest_file() -> dict[str, Any] | None:
    path = Path(MANIFEST_PATH)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except _DEPLOY_ERRORS:
        return None


def _fetch_hub_manifest() -> dict[str, Any] | None:
    local = _read_local_manifest_file()
    if local:
        return local
    try:
        req = urllib.request.Request(
            MANIFEST_URL,
            method="GET",
            headers={"User-Agent": "xcmax-enterprise-pull/1.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read(65536).decode("utf-8", errors="replace"))
        return raw if isinstance(raw, dict) else None
    except _DEPLOY_ERRORS as exc:
        logger.debug("hub manifest fetch failed: %s", exc)
        return None


def check_enterprise_updates() -> dict[str, Any]:
    """企业端：对比 update 站 manifest 与本地已部署 sha256。"""
    hub = _fetch_hub_manifest() or {}
    deployed_sha = _read_deployed_sha256()
    hub_sha = str(hub.get("sha256") or "")
    hub_git = str(hub.get("git_sha") or "")
    hub_version = str(hub.get("version") or "")
    hub_built_at = str(hub.get("built_at") or "")

    vue_hub = Path(HUB_VUE_DIST).is_dir()
    vue_local = Path(LOCAL_VUE_DIST).is_dir()

    needs_update = bool(hub_sha and hub_sha != deployed_sha)
    if not deployed_sha and hub_sha:
        needs_update = True

    return {
        "role": "enterprise",
        "update_hub": {
            "manifest_path": MANIFEST_PATH,
            "manifest_url": MANIFEST_URL,
            "artifact_dir": ARTIFACT_DIR,
            "version": hub_version or None,
            "git_sha": hub_git or None,
            "sha256": hub_sha or None,
            "built_at": hub_built_at or None,
            "has_vue_dist": vue_hub,
            "reachable": bool(hub),
        },
        "enterprise": {
            "deploy_root": DEPLOY_ROOT,
            "deployed_sha256": deployed_sha or None,
            "vue_dist_path": LOCAL_VUE_DIST,
            "has_vue_dist": vue_local,
        },
        "flags": {
            "needs_update": needs_update,
            "up_to_date": bool(hub_sha and hub_sha == deployed_sha),
            "hub_has_frontend": vue_hub,
        },
    }


@dataclass
class PullStep:
    id: str
    label: str
    status: StepStatus = "pending"
    detail: str = ""
    started_at: float | None = None
    finished_at: float | None = None


@dataclass
class PullJob:
    job_id: str
    options: dict[str, Any]
    status: Literal["queued", "running", "done", "error"] = "queued"
    steps: list[PullStep] = field(default_factory=list)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "options": self.options,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "steps": [
                {
                    "id": s.id,
                    "label": s.label,
                    "status": s.status,
                    "detail": s.detail,
                    "started_at": s.started_at,
                    "finished_at": s.finished_at,
                }
                for s in self.steps
            ],
        }


_PULL_JOBS: dict[str, PullJob] = {}
_PULL_LOCK = asyncio.Lock()
_ACTIVE_PULL: str | None = None


def get_pull_job(job_id: str) -> PullJob | None:
    return _PULL_JOBS.get(job_id)


async def _run_shell(step: PullStep, cmd: list[str], *, cwd: str | None = None) -> None:
    step.status = "running"
    step.started_at = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        tail = ""
        while True:
            chunk = await proc.stdout.readline()
            if not chunk:
                break
            tail = chunk.decode("utf-8", errors="replace").rstrip()[-240:]
        code = await proc.wait()
        step.detail = tail or f"exit {code}"
        if code != 0:
            raise RuntimeError(step.detail)
        step.status = "done"
    except _DEPLOY_ERRORS as exc:
        step.status = "error"
        step.detail = str(exc)[:500]
        raise
    finally:
        step.finished_at = time.time()


def _build_pull_steps(options: dict[str, Any]) -> list[PullStep]:
    steps = [PullStep("check", "检测 update 站新版本")]
    if options.get("include_backend", True):
        steps.append(PullStep("apply_backend", "拉取并应用后端发布包"))
    if options.get("include_frontend", True):
        steps.append(PullStep("apply_frontend", "同步 update 站前端 vue-dist"))
    steps.append(PullStep("restart", "重启企业服务"))
    steps.append(PullStep("verify", "验证更新结果"))
    return steps


async def _execute_pull_job(job: PullJob) -> None:
    global _ACTIVE_PULL
    opts = job.options
    apply_script = Path(DEPLOY_ROOT) / "scripts" / "deploy" / "fhd-auto-update.sh"
    auto_update = Path("/opt/fhd-full/scripts/deploy/fhd-auto-update.sh")

    try:
        job.status = "running"
        check = job.steps[0]
        check.status = "running"
        check.started_at = time.time()
        snap = check_enterprise_updates()
        if not snap["flags"]["needs_update"] and not opts.get("force"):
            check.detail = "已是最新"
            check.status = "done"
            check.finished_at = time.time()
            job.status = "done"
            for s in job.steps[1:]:
                s.status = "skipped"
            return
        check.detail = f"update 站 {snap['update_hub'].get('git_sha') or '?'}"
        check.status = "done"
        check.finished_at = time.time()

        for step in job.steps[1:]:
            if step.id == "apply_backend":
                script = str(apply_script if apply_script.is_file() else auto_update)
                if not Path(script).is_file():
                    step.status = "skipped"
                    step.detail = "非生产部署路径，跳过后端拉取（开发环境请重启本地服务）"
                    continue
                await _run_shell(step, ["bash", script])
            elif step.id == "apply_frontend":
                hub_vue = Path(HUB_VUE_DIST)
                if not hub_vue.is_dir():
                    step.status = "skipped"
                    step.detail = "update 站暂无 vue-dist"
                    continue
                local_vue = Path(LOCAL_VUE_DIST)
                local_vue.parent.mkdir(parents=True, exist_ok=True)
                await _run_shell(
                    step,
                    ["rsync", "-a", "--delete", f"{hub_vue}/", f"{local_vue}/"],
                )
            elif step.id == "restart":
                if not Path(DEPLOY_ROOT).joinpath("app").is_dir():
                    step.status = "skipped"
                    step.detail = "开发环境跳过 restart"
                    continue
                await _run_shell(step, ["systemctl", "restart", SERVICE_NAME])
            elif step.id == "verify":
                step.status = "running"
                step.started_at = time.time()
                await asyncio.sleep(2)
                snap2 = check_enterprise_updates()
                ok = snap2["flags"].get("up_to_date") or not snap2["flags"].get("needs_update")
                step.detail = "更新完成" if ok else "仍待同步"
                step.status = "done" if ok else "error"
                step.finished_at = time.time()
                if not ok and Path(DEPLOY_ROOT).joinpath("app").is_dir():
                    raise RuntimeError(step.detail)

        job.status = "done"
    except _DEPLOY_ERRORS as exc:
        job.status = "error"
        job.error = str(exc)[:800]
        for s in job.steps:
            if s.status == "running":
                s.status = "error"
                s.finished_at = time.time()
    finally:
        job.finished_at = time.time()
        _ACTIVE_PULL = None


async def start_enterprise_pull(options: dict[str, Any] | None = None) -> PullJob:
    global _ACTIVE_PULL
    opts = dict(options or {})
    opts.setdefault("include_backend", True)
    opts.setdefault("include_frontend", True)
    opts.setdefault("force", False)

    async with _PULL_LOCK:
        if _ACTIVE_PULL and _PULL_JOBS.get(_ACTIVE_PULL, PullJob("", {})).status == "running":
            raise RuntimeError("已有拉取任务进行中")
        job_id = uuid.uuid4().hex[:12]
        job = PullJob(job_id=job_id, options=opts, steps=_build_pull_steps(opts))
        _PULL_JOBS[job_id] = job
        _ACTIVE_PULL = job_id

    asyncio.create_task(_execute_pull_job(job))
    return job
