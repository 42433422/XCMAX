"""管理端：打包并推送到 update 中转站（不直连企业机；企业端自行拉取）。"""

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

PUSH_HOST = os.environ.get("FHD_PUSH_HOST", "119.27.178.147")
PUSH_USER = os.environ.get("FHD_PUSH_USER", "root")
CHANNEL_DEFAULT = os.environ.get("FHD_RELEASE_CHANNEL", "stable")
MANIFEST_URL = (
    os.environ.get("XCMAX_UPDATE_MANIFEST_URL", "").strip()
    or f"https://update.xcagi.com/releases/{CHANNEL_DEFAULT}/server/fhd-manifest.json"
)
ENTERPRISE_HEALTH_HOST = os.environ.get("XCMAX_REMOTE_HOST", PUSH_HOST)
ENTERPRISE_HEALTH_PORT = int(os.environ.get("XCMAX_REMOTE_PORT", "5100"))


def _fhd_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _hub_remote_dir(channel: str) -> str:
    custom = os.environ.get("FHD_PUSH_REMOTE_DIR", "").strip()
    if custom:
        return custom
    return f"/var/www/update/releases/{channel}/server"


def _local_git_sha(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        sha = (out.stdout or "").strip()
        return sha if out.returncode == 0 and sha else "local"
    except _DEPLOY_ERRORS:
        return "local"


def _local_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return "10.0.0"
    try:
        import re

        text = pyproject.read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        return m.group(1) if m else "10.0.0"
    except _DEPLOY_ERRORS:
        return "10.0.0"


def _read_local_manifest(root: Path) -> dict[str, Any] | None:
    path = root / "dist" / "deploy" / "fhd-manifest.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except _DEPLOY_ERRORS:
        return None


def _fetch_json_url(url: str, timeout: float = 8.0) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(
            url, method="GET", headers={"User-Agent": "xcmax-admin-deploy/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read(65536).decode("utf-8", errors="replace"))
        return raw if isinstance(raw, dict) else None
    except _DEPLOY_ERRORS as exc:
        logger.debug("fetch manifest failed url=%s err=%s", url, exc)
        return None


def _probe_enterprise_runtime() -> dict[str, Any]:
    """只读探测企业运行态（管理端不向其写入）。"""
    url = f"http://{ENTERPRISE_HEALTH_HOST}:{ENTERPRISE_HEALTH_PORT}/api/health"
    t0 = time.time()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read(4096).decode("utf-8", errors="replace"))
        return {
            "reachable": True,
            "latency_ms": round((time.time() - t0) * 1000),
            "version": str(body.get("version") or ""),
            "deploy_sha256": str(body.get("deploy_sha256") or ""),
            "host": ENTERPRISE_HEALTH_HOST,
            "port": ENTERPRISE_HEALTH_PORT,
        }
    except _DEPLOY_ERRORS as exc:
        return {
            "reachable": False,
            "latency_ms": None,
            "version": "",
            "deploy_sha256": "",
            "host": ENTERPRISE_HEALTH_HOST,
            "port": ENTERPRISE_HEALTH_PORT,
            "error": str(exc),
        }


def check_deploy_updates(channel: str = CHANNEL_DEFAULT) -> dict[str, Any]:
    """三段对比：管理端本地 → update 站 → 企业运行态（只读）。"""
    root = _fhd_root()
    local_sha = _local_git_sha(root)
    local_version = _local_version(root)
    local_manifest = _read_local_manifest(root)
    manifest_url = (
        MANIFEST_URL.replace("/stable/", f"/{channel}/") if channel != "stable" else MANIFEST_URL
    )
    hub = _fetch_json_url(manifest_url)
    enterprise = _probe_enterprise_runtime()

    hub_sha = str((hub or {}).get("git_sha") or "")
    hub_tar_sha = str((hub or {}).get("sha256") or "")
    hub_version = str((hub or {}).get("version") or "")
    hub_built_at = str((hub or {}).get("built_at") or "")

    local_pack_sha = str((local_manifest or {}).get("git_sha") or "")
    needs_pack = local_sha not in ("local", "") and local_sha != local_pack_sha
    needs_push = bool(local_sha not in ("local", "") and hub_sha != local_sha)
    if not hub_sha and local_sha not in ("local", ""):
        needs_push = True

    ent_deploy_sha = str(enterprise.get("deploy_sha256") or "")
    enterprise_pending = bool(hub_tar_sha and hub_tar_sha != ent_deploy_sha)

    return {
        "pipeline": ["admin_push", "update_hub", "enterprise_pull"],
        "admin_local": {
            "version": local_version,
            "git_sha": local_sha,
            "packed_git_sha": local_pack_sha or None,
            "fhd_root": str(root),
        },
        "update_hub": {
            "host": PUSH_HOST,
            "remote_dir": _hub_remote_dir(channel),
            "manifest_url": manifest_url,
            "version": hub_version or None,
            "git_sha": hub_sha or None,
            "sha256": hub_tar_sha or None,
            "built_at": hub_built_at or None,
            "reachable": hub is not None,
        },
        "enterprise": enterprise,
        "flags": {
            "needs_pack": needs_pack,
            "needs_push": needs_push,
            "enterprise_pending": enterprise_pending,
            "up_to_date": not needs_push and not needs_pack,
        },
    }


@dataclass
class DeployStep:
    id: str
    label: str
    status: StepStatus = "pending"
    detail: str = ""
    started_at: float | None = None
    finished_at: float | None = None


@dataclass
class DeployJob:
    job_id: str
    options: dict[str, Any]
    status: Literal["queued", "running", "done", "error"] = "queued"
    steps: list[DeployStep] = field(default_factory=list)
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


_JOBS: dict[str, DeployJob] = {}
_JOB_LOCK = asyncio.Lock()
_ACTIVE_JOB: str | None = None


def get_deploy_job(job_id: str) -> DeployJob | None:
    return _JOBS.get(job_id)


async def _run_shell_step(
    job: DeployJob,
    step: DeployStep,
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> None:
    step.status = "running"
    step.started_at = time.time()
    step.detail = " ".join(cmd[-3:]) if len(cmd) > 3 else " ".join(cmd)
    merged = {**os.environ, **(env or {})}
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            env=merged,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        tail: list[str] = []
        while True:
            chunk = await proc.stdout.readline()
            if not chunk:
                break
            line = chunk.decode("utf-8", errors="replace").rstrip()
            if line:
                tail.append(line[-240:])
                if len(tail) > 6:
                    tail.pop(0)
        code = await proc.wait()
        step.detail = tail[-1] if tail else f"exit {code}"
        if code != 0:
            raise RuntimeError(step.detail or f"命令失败 exit={code}")
        step.status = "done"
    except _DEPLOY_ERRORS as exc:
        step.status = "error"
        step.detail = str(exc)[:500]
        raise
    finally:
        step.finished_at = time.time()


def _build_steps(options: dict[str, Any]) -> list[DeployStep]:
    steps = [DeployStep("check", "检测管理端本地版本")]
    if options.get("include_backend", True):
        if not options.get("skip_pack"):
            steps.append(DeployStep("pack", "打包后端发布物"))
        steps.append(DeployStep("push", "推送到 update 中转站"))
    if options.get("include_frontend", True):
        steps.append(DeployStep("frontend_build", "构建前端 vue-dist"))
        steps.append(DeployStep("frontend_push", "发布前端到 update 中转站"))
    steps.append(DeployStep("verify", "验证 update 站 manifest"))
    return steps


async def _execute_deploy_job(job: DeployJob) -> None:
    global _ACTIVE_JOB
    root = _fhd_root()
    opts = job.options
    channel = str(opts.get("channel") or "stable").strip() or "stable"
    ssh_key = str(opts.get("ssh_key") or os.environ.get("FHD_PUSH_SSH_KEY") or "").strip()

    deploy_env: dict[str, str] = {
        "FHD_RELEASE_CHANNEL": channel,
        "FHD_PUSH_REMOTE_DIR": _hub_remote_dir(channel),
    }
    if ssh_key:
        deploy_env["FHD_PUSH_SSH_KEY"] = ssh_key

    async def run_step(
        step: DeployStep, cmd: list[str], *, cwd: Path | None = None, env: dict | None = None
    ):
        await _run_shell_step(job, step, cmd, cwd=cwd or root, env=env)

    try:
        job.status = "running"
        check_step = job.steps[0]
        check_step.status = "running"
        check_step.started_at = time.time()
        snap = check_deploy_updates(channel)
        check_step.detail = f"本地 {snap['admin_local']['git_sha']}"
        check_step.status = "done"
        check_step.finished_at = time.time()

        for step in job.steps[1:]:
            if step.id == "pack":
                await run_step(step, ["bash", "scripts/deploy/fhd-pack-release.sh"], env=deploy_env)
            elif step.id == "push":
                push_env = {**deploy_env}
                if opts.get("skip_pack"):
                    push_env["FHD_SKIP_PACK"] = "1"
                await run_step(step, ["bash", "scripts/deploy/fhd-push-release.sh"], env=push_env)
            elif step.id == "frontend_build":
                await run_step(step, ["npm", "run", "build"], cwd=root / "frontend")
            elif step.id == "frontend_push":
                await run_step(
                    step, ["bash", "scripts/deploy/fhd-push-frontend-dist.sh"], env=deploy_env
                )
            elif step.id == "verify":
                step.status = "running"
                step.started_at = time.time()
                await asyncio.sleep(1)
                snap2 = check_deploy_updates(channel)
                hub = snap2.get("update_hub") or {}
                local_sha = snap2["admin_local"]["git_sha"]
                hub_sha = hub.get("git_sha") or ""
                step.detail = f"update 站 {hub_sha or '?'}"
                step.status = "done" if hub_sha == local_sha or not local_sha else "error"
                step.finished_at = time.time()
                if step.status == "error":
                    raise RuntimeError("update 站 manifest 与本地 git 不一致")

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
        _ACTIVE_JOB = None


async def start_deploy_push(options: dict[str, Any] | None = None) -> DeployJob:
    """管理端：仅推送到 update 站，企业端需自行拉取。"""
    global _ACTIVE_JOB
    opts = dict(options or {})
    opts.setdefault("include_backend", True)
    opts.setdefault("include_frontend", True)
    opts.setdefault("skip_pack", False)
    opts.setdefault("channel", "stable")

    async with _JOB_LOCK:
        if _ACTIVE_JOB and _JOBS.get(_ACTIVE_JOB, DeployJob("", {})).status == "running":
            raise RuntimeError("已有推送任务进行中，请稍候")
        job_id = uuid.uuid4().hex[:12]
        job = DeployJob(job_id=job_id, options=opts, steps=_build_steps(opts))
        _JOBS[job_id] = job
        _ACTIVE_JOB = job_id

    asyncio.create_task(_execute_deploy_job(job))
    return job
