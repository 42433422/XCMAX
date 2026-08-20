"""CvmAutonomyAdapter：服务器端 AutonomyAdapter 实现（Phase 2）。

职责：
  - collect_truth()：采集服务器端 truth（curl 健康检查、docker compose ps、df 磁盘、
    manifest 存在性、.deploy-last.tar.gz 存在性）
  - subscribe_signals()：服务器端无主动信号（由 watcher tick 派生）
  - execute_action()：8 个 action 实现
      * restart_service：cd $DEPLOY_ROOT && docker compose restart（timeout 60s）
      * rollback_to_last_tarball：FHD_RELEASE_TARBALL=... bash fhd-apply-release.sh
        （timeout 300s）
      * freeze_manifest：touch $MANIFEST.frozen（创建 marker，manifest 不移动）
      * unfreeze_manifest：rm $MANIFEST.frozen（仅 hold_ttl 过期 + health 通过才执行）
      * clear_logs：find $DEPLOY_ROOT/logs -mtime +7 -delete（timeout 60s）
      * escalate / noop：返回 ok=True（仅审计）
      * open_incident_issue：调 GitHub REST API 创建 incident issue（标
        ai-implement + incident + auto-incident 标签），24h 同指纹去重；配合
        ai_issue_implement.py 自动实现修复 PR
  - audit()：写 $DEPLOY_ROOT/autonomy/audit.jsonl

设计：
  - 所有 shell 命令用 subprocess.run(list, timeout=, capture_output=True, text=True)
    禁止 shell=True
  - 失败模式：subprocess 抛错 / 返回非 0 → 返回 ActionResult(ok=False, detail=str(e))
  - 测试隔离：for_test 类方法注入 mock，跳过真实 docker/df 调用
  - GitHub API：urllib.request + GITHUB_TOKEN（与 ai_issue_implement.py / capability_proposal_to_issue.py
    模式一致，不引入 PyGithub 依赖）

frozen marker 与 cron / fhd-deploy.yml 的一致性：
  - fhd-auto-update.sh#L21: FREEZE_MARKER="${MANIFEST}.frozen"
  - fhd-deploy.yml#L171: touch "${MANIFEST}.frozen"
  - fhd-deploy.yml#L173: rm -f "${MANIFEST}.frozen"
  - cvm_adapter.py: 创建/删除 ${MANIFEST}.frozen（与上同源，统一定义 .frozen 后缀）

open_incident_issue 设计要点：
  - 兜底语义：仅当前置 remediation action（同 idempotency_key）在最近 audit 中
    标记为失败时，才真正创建 issue；前置成功则跳过（idempotent skip）
  - 24h 去重：通过 GitHub Search API 查找同 title prefix 的 open issue
  - 触发闭环：issue 标 `ai-implement` 后，ai-issue-implement.yml workflow 自动触发
    生成修复 PR（命中 auto-implement-allowlist.yaml `^incident$` pattern 自动预授权）
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

from .types import (
    Action,
    ActionResult,
    ActionType,
    AuditEntry,
    RiskLevel,
    RuntimeTruthSnapshot,
    Signal,
)

# 健康检查 URL（与 docs/CI_SSOT.md 中 cvm-autonomy-watcher 健康检查一致）
DEFAULT_HEALTH_URL = "https://xiu-ci.com/fhd-api/api/health"

# 默认部署根目录（与 fhd-apply-release.sh FHD_DEPLOY_ROOT 一致）
DEFAULT_DEPLOY_ROOT = "/opt/fhd-full"

# 默认 manifest 路径（与 fhd-deploy.yml production MANIFEST 一致）
DEFAULT_MANIFEST_PATH = "/var/www/update/releases/stable/server/fhd-manifest.json"

# manifest 冻结 marker 后缀（与 fhd-auto-update.sh / fhd-deploy.yml 一致：.frozen）
MANIFEST_FROZEN_SUFFIX = ".frozen"

# frozen marker 默认 hold_ttl（秒）：超过后 watcher 自动解除（health 通过时）
# 可通过 env FHD_MANIFEST_HOLD_TTL_SECONDS 覆盖
DEFAULT_HOLD_TTL_SECONDS = 30 * 60

# action 命令超时（秒）
RESTART_SERVICE_TIMEOUT = 60
ROLLBACK_TIMEOUT = 300
CLEAR_LOGS_TIMEOUT = 60

# docker compose ps 输出中 service 状态关键字
COMPOSE_RUNNING_KEYWORD = "running"

# incident issue 默认 24h 去重窗口（小时）
DEFAULT_INCIDENT_DEDUP_WINDOW_H = 24

# incident issue 标签集合（ai-implement 触发 ai-issue-implement.yml workflow；
# incident + auto-incident 供检索/分类；auto-generated 标识自动创建）
INCIDENT_ISSUE_LABELS = (
    "ai-implement",
    "incident",
    "auto-incident",
    "auto-generated",
)

# incident issue title 前缀（用于 24h 同指纹去重 search）
INCIDENT_TITLE_PREFIX = "[incident"

# GitHub API 请求超时（秒）
GITHUB_API_TIMEOUT = 30


class CvmAutonomyAdapter:
    """服务器端 AutonomyAdapter 实现。

    与桌面端 DesktopAutonomyAdapter 对称，但执行环境不同：
      - 桌面端：electron userData + Node fs
      - 服务器端：/opt/fhd-full + Python subprocess（docker compose / find / mv）
    """

    def __init__(
        self,
        deploy_root: str = DEFAULT_DEPLOY_ROOT,
        manifest_path: str = DEFAULT_MANIFEST_PATH,
        audit_dir: str | None = None,
        health_url: str = DEFAULT_HEALTH_URL,
        hold_ttl: int | None = None,
        github_token: str | None = None,
        github_repo: str | None = None,
        incident_dedup_window_h: int = DEFAULT_INCIDENT_DEDUP_WINDOW_H,
    ) -> None:
        self.deploy_root = deploy_root
        self.manifest_path = manifest_path
        self.audit_dir = audit_dir or os.path.join(deploy_root, "autonomy")
        self.health_url = health_url
        # frozen marker hold_ttl（秒）：env FHD_MANIFEST_HOLD_TTL_SECONDS 优先
        if hold_ttl is None:
            env_ttl = os.environ.get("FHD_MANIFEST_HOLD_TTL_SECONDS")
            hold_ttl = int(env_ttl) if env_ttl and env_ttl.isdigit() else DEFAULT_HOLD_TTL_SECONDS
        self.hold_ttl = hold_ttl
        # GitHub API 配置：env GITHUB_TOKEN / GITHUB_REPOSITORY 优先
        # 注：Actions 自带 GITHUB_TOKEN 不能跨 runner 使用，CVM 部署需用 PAT（secret: CVM_INCIDENT_PAT）
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN") or None
        self.github_repo = github_repo or os.environ.get("GITHUB_REPOSITORY") or None
        self.incident_dedup_window_h = incident_dedup_window_h
        # 创建 audit 目录（不抛错）
        try:
            os.makedirs(self.audit_dir, exist_ok=True)
        except OSError:
            pass
        self.audit_path = os.path.join(self.audit_dir, "audit.jsonl")
        # 测试钩子：若设置则替代真实 subprocess.run / curl 调用
        self._subprocess_runner: Callable[..., subprocess.CompletedProcess] | None = None
        self._health_probe: Callable[[str], bool] | None = None
        self._compose_status_probe: Callable[[str], tuple[str, bool]] | None = None
        # 测试钩子：GitHub API 调用注入（避免真实网络请求）
        self._github_api_get: Callable[[str, str], dict[str, Any]] | None = None
        self._github_api_post: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None

    # ------------------------------------------------------------------ #
    # 测试工厂：注入 mock，跳过真实 docker / df / curl 调用
    # ------------------------------------------------------------------ #

    @classmethod
    def for_test(
        cls,
        deploy_root: str,
        audit_dir: str,
        manifest_path: str | None = None,
        health_url: str = "http://test/health",
        hold_ttl: int = DEFAULT_HOLD_TTL_SECONDS,
        github_token: str | None = None,
        github_repo: str | None = None,
        incident_dedup_window_h: int = DEFAULT_INCIDENT_DEDUP_WINDOW_H,
    ) -> CvmAutonomyAdapter:
        """测试用：创建一个不依赖真实 docker / df / curl 的 adapter 实例。

        测试通过设置 ``_subprocess_runner`` / ``_health_probe`` /
        ``_compose_status_probe`` / ``_github_api_get`` / ``_github_api_post``
        注入 mock 行为。
        """
        inst = cls.__new__(cls)
        inst.deploy_root = deploy_root
        inst.manifest_path = manifest_path or os.path.join(
            deploy_root, "releases", "stable", "server", "fhd-manifest.json"
        )
        inst.audit_dir = audit_dir
        inst.health_url = health_url
        inst.hold_ttl = hold_ttl
        inst.github_token = github_token
        inst.github_repo = github_repo
        inst.incident_dedup_window_h = incident_dedup_window_h
        inst.audit_path = os.path.join(audit_dir, "audit.jsonl")
        try:
            os.makedirs(audit_dir, exist_ok=True)
        except OSError:
            pass
        inst._subprocess_runner = None
        inst._health_probe = None
        inst._compose_status_probe = None
        inst._github_api_get = None
        inst._github_api_post = None
        return inst

    # ------------------------------------------------------------------ #
    # collect_truth：采集服务器端 reality
    # ------------------------------------------------------------------ #

    def collect_truth(self) -> RuntimeTruthSnapshot:
        """采集运行时现实快照。

        容错设计：任何子检查失败不抛错，回退到默认值（health_ok=False / status='unknown'）。
        """
        now_ms = int(time.time() * 1000)

        health_ok = self._probe_health()
        compose_status, service_running = self._probe_compose_status()
        disk_usage_percent = self._probe_disk_usage()
        manifest_exists = os.path.isfile(self.manifest_path)
        manifest_frozen = os.path.isfile(f"{self.manifest_path}{MANIFEST_FROZEN_SUFFIX}")
        rollback_tarball = os.path.join(self.deploy_root, ".deploy-last.tar.gz")
        last_backup_ts = self._probe_last_backup_ts(rollback_tarball)
        pending_rollback_marker = os.path.isfile(
            os.path.join(self.deploy_root, "rollback-marker.json")
        )

        # 服务器端不跟踪配置指纹 / 重启计数（默认 False / 0）
        return RuntimeTruthSnapshot(
            ts=now_ms,
            deploy_root=self.deploy_root,
            manifest_path=self.manifest_path,
            compose_status=compose_status,
            health_ok=health_ok,
            service_running=service_running,
            pending_rollback_marker=pending_rollback_marker,
            disk_usage_percent=disk_usage_percent,
            config_fingerprint_changed=False,
            last_backup_ts=last_backup_ts,
            app_version="",  # 服务器端不在此采集（由 manifest 提供）
            build_sha="",
            restart_count=0,
            manifest_exists=manifest_exists,
            manifest_frozen=manifest_frozen,
        )

    def _probe_health(self) -> bool:
        """curl /api/health → 200 即 ok=True。"""
        if self._health_probe is not None:
            try:
                return bool(self._health_probe(self.health_url))
            except RECOVERABLE_ERRORS:  # noqa: BLE001 - script boundary records arbitrary integration failures
                return False
        # 真实路径：subprocess 调用 curl
        try:
            result = self._run_subprocess(
                [
                    "curl",
                    "-sf",
                    "-o",
                    "/dev/null",
                    "-m",
                    "5",
                    "-w",
                    "%{http_code}",
                    self.health_url,
                ],
                timeout=10,
            )
            return result.returncode == 0 and result.stdout.strip() == "200"
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - script boundary records arbitrary integration failures
            return False

    def _probe_compose_status(self) -> tuple[str, bool]:
        """docker compose ps → (status, service_running)。

        status: 'running' | 'exited' | 'absent' | 'unknown'
        service_running: True 当至少一个服务 running
        """
        if self._compose_status_probe is not None:
            try:
                status, running = self._compose_status_probe(self.deploy_root)
                return status, running
            except RECOVERABLE_ERRORS:  # noqa: BLE001 - script boundary records arbitrary integration failures
                return "unknown", False
        compose_file = self._resolve_compose_file()
        if compose_file is None:
            return "absent", False
        try:
            result = self._run_subprocess(
                ["docker", "compose", "-f", compose_file, "ps", "--format", "json"],
                timeout=15,
                cwd=self.deploy_root,
            )
            if result.returncode != 0:
                return "unknown", False
            # 解析输出：每行一个 JSON 对象
            service_running = False
            status = "exited"
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    state = str(obj.get("State", "")).lower()
                    if state == COMPOSE_RUNNING_KEYWORD:
                        service_running = True
                        status = "running"
                        break
                except json.JSONDecodeError:
                    continue
            return status, service_running
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - script boundary records arbitrary integration failures
            return "unknown", False

    def _resolve_compose_file(self) -> str | None:
        """查找 compose.yml / docker-compose.yml（与 fhd-deploy.yml 顺序一致）。"""
        for name in ("compose.yml", "docker-compose.yml"):
            path = os.path.join(self.deploy_root, name)
            if os.path.isfile(path):
                return path
        return None

    def _probe_disk_usage(self) -> float:
        """df -B1 → 计算百分比。失败返回 0.0。"""
        try:
            result = self._run_subprocess(
                ["df", "-B1", "--output=used,avail", self.deploy_root],
                timeout=10,
            )
            if result.returncode != 0:
                return 0.0
            lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
            if len(lines) < 2:
                return 0.0
            parts = lines[1].split()
            if len(parts) < 2:
                return 0.0
            used = int(parts[0])
            avail = int(parts[1])
            total = used + avail
            if total <= 0:
                return 0.0
            return round((used / total) * 100, 2)
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - script boundary records arbitrary integration failures
            return 0.0

    def _probe_last_backup_ts(self, rollback_tarball: str) -> int | None:
        """读取 .deploy-last.tar.gz mtime（UNIX ms）。文件不存在返回 None。"""
        try:
            if not os.path.isfile(rollback_tarball):
                return None
            return int(os.path.getmtime(rollback_tarball) * 1000)
        except OSError:
            return None

    # ------------------------------------------------------------------ #
    # subscribe_signals：服务器端无主动信号
    # ------------------------------------------------------------------ #

    def subscribe_signals(self, emit: Any) -> None:
        """服务器端无主动信号（由 watcher tick 从 truth 派生）。"""
        # 空实现：与桌面端 desktop-adapter.subscribe_signals 一致
        return None

    # ------------------------------------------------------------------ #
    # execute_action：8 个 action 实现
    # ------------------------------------------------------------------ #

    def execute_action(self, action: Action) -> ActionResult:
        """执行动作。失败不抛错，返回 ok=False + detail。"""
        ts = int(time.time() * 1000)
        try:
            if action.type == ActionType.RESTART_SERVICE:
                return self._action_restart_service(action, ts)
            if action.type == ActionType.ROLLBACK_TO_LAST_TARBALL:
                return self._action_rollback(action, ts)
            if action.type == ActionType.FREEZE_MANIFEST:
                return self._action_freeze_manifest(action, ts)
            if action.type == ActionType.UNFREEZE_MANIFEST:
                return self._action_unfreeze_manifest(action, ts)
            if action.type == ActionType.CLEAR_LOGS:
                return self._action_clear_logs(action, ts)
            if action.type == ActionType.ESCALATE:
                return ActionResult(action=action, ok=True, detail="escalate acknowledged", ts=ts)
            if action.type == ActionType.NOOP:
                return ActionResult(action=action, ok=True, detail="noop acknowledged", ts=ts)
            if action.type == ActionType.OPEN_INCIDENT_ISSUE:
                return self._action_open_incident_issue(action, ts)
            return ActionResult(
                action=action, ok=False, detail=f"not-implemented:{action.type.value}", ts=ts
            )
        except BOUNDARY_ERRORS as e:  # adapter boundary records arbitrary integration failures
            return ActionResult(
                action=action,
                ok=False,
                detail=f"execute_threw: {e}",
                ts=ts,
            )

    def _action_restart_service(self, action: Action, ts: int) -> ActionResult:
        compose_file = self._resolve_compose_file()
        if compose_file is None:
            return ActionResult(
                action=action,
                ok=False,
                detail=f"no compose.yml under {self.deploy_root}",
                ts=ts,
            )
        result = self._run_subprocess(
            ["docker", "compose", "-f", compose_file, "restart"],
            timeout=RESTART_SERVICE_TIMEOUT,
            cwd=self.deploy_root,
        )
        if result.returncode != 0:
            return ActionResult(
                action=action,
                ok=False,
                detail=f"docker compose restart failed: {result.stderr.strip() or result.stdout.strip()}",
                ts=ts,
            )
        return ActionResult(
            action=action,
            ok=True,
            detail=f"docker compose restart ok (compose={os.path.basename(compose_file)})",
            ts=ts,
        )

    def _action_rollback(self, action: Action, ts: int) -> ActionResult:
        rollback_tarball = os.path.join(self.deploy_root, ".deploy-last.tar.gz")
        if not os.path.isfile(rollback_tarball):
            return ActionResult(
                action=action,
                ok=False,
                detail=f"no .deploy-last.tarball under {self.deploy_root}",
                ts=ts,
            )
        apply_script = os.path.join(self.deploy_root, "scripts", "deploy", "fhd-apply-release.sh")
        if not os.path.isfile(apply_script):
            return ActionResult(
                action=action,
                ok=False,
                detail=f"no fhd-apply-release.sh under {self.deploy_root}/scripts/deploy",
                ts=ts,
            )
        env = os.environ.copy()
        env["FHD_RELEASE_TARBALL"] = rollback_tarball
        env["FHD_DEPLOY_ROOT"] = self.deploy_root
        result = self._run_subprocess(
            ["bash", apply_script],
            timeout=ROLLBACK_TIMEOUT,
            env=env,
        )
        if result.returncode != 0:
            return ActionResult(
                action=action,
                ok=False,
                detail=f"fhd-apply-release.sh failed: {result.stderr.strip() or result.stdout.strip()}",
                ts=ts,
            )
        return ActionResult(
            action=action,
            ok=True,
            detail=f"rollback applied: {rollback_tarball}",
            ts=ts,
        )

    def _action_freeze_manifest(self, action: Action, ts: int) -> ActionResult:
        if not os.path.isfile(self.manifest_path):
            return ActionResult(
                action=action,
                ok=False,
                detail=f"manifest not found: {self.manifest_path}",
                ts=ts,
            )
        frozen_path = f"{self.manifest_path}{MANIFEST_FROZEN_SUFFIX}"
        if os.path.isfile(frozen_path):
            return ActionResult(
                action=action,
                ok=False,
                detail=f"manifest already frozen: {frozen_path} exists",
                ts=ts,
            )
        # 与 fhd-deploy.yml#L171 `touch ${MANIFEST}.frozen` 同源：
        # 创建 marker 文件，manifest 原地保留（cron 检测 marker 跳过自动更新）。
        try:
            Path(frozen_path).touch()
        except OSError as e:
            return ActionResult(
                action=action,
                ok=False,
                detail=f"freeze_manifest touch failed: {e}",
                ts=ts,
            )
        return ActionResult(
            action=action,
            ok=True,
            detail=f"manifest frozen: marker={frozen_path} (manifest preserved)",
            ts=ts,
        )

    def _action_unfreeze_manifest(self, action: Action, ts: int) -> ActionResult:
        """解除 frozen marker（hold_ttl 过期 + health 通过 才执行）。

        守护链：
          1. .frozen 不存在 → ok=False, no-op
          2. mtime age < hold_ttl → ok=False, "still within hold_ttl"
          3. health check 失败 → ok=False, "health failed, keep frozen"
          4. 全部通过 → os.remove(.frozen), ok=True

        设计：health 检查放最后（避免在 TTL 未到时浪费 curl 调用）。
        """
        frozen_path = f"{self.manifest_path}{MANIFEST_FROZEN_SUFFIX}"
        if not os.path.isfile(frozen_path):
            return ActionResult(
                action=action,
                ok=False,
                detail=f"no .frozen marker to remove: {frozen_path}",
                ts=ts,
            )
        # 检查 mtime vs hold_ttl
        try:
            mtime = os.path.getmtime(frozen_path)
            age_seconds = int(time.time() - mtime)
        except OSError as e:
            return ActionResult(
                action=action,
                ok=False,
                detail=f"unfreeze_manifest stat failed: {e}",
                ts=ts,
            )
        if age_seconds < self.hold_ttl:
            return ActionResult(
                action=action,
                ok=False,
                detail=(f".frozen age {age_seconds}s < hold_ttl {self.hold_ttl}s, keep frozen"),
                ts=ts,
            )
        # health check 必须通过才解除（health 失败保持冻结）
        if not self._probe_health():
            return ActionResult(
                action=action,
                ok=False,
                detail=f"health check failed, keep frozen (age={age_seconds}s)",
                ts=ts,
            )
        # 全部通过 → rm marker
        try:
            os.remove(frozen_path)
        except OSError as e:
            return ActionResult(
                action=action,
                ok=False,
                detail=f"unfreeze_manifest rm failed: {e}",
                ts=ts,
            )
        return ActionResult(
            action=action,
            ok=True,
            detail=(
                f"manifest unfrozen: marker={frozen_path} removed "
                f"(age={age_seconds}s, ttl={self.hold_ttl}s, health=ok)"
            ),
            ts=ts,
        )

    def check_unfreeze_needed(self) -> tuple[bool, int]:
        """检查是否需要解除 frozen marker（watcher 主循环每次 tick 调用）。

        Returns:
            (needed, age_seconds):
              - needed=True 当 .frozen 存在且 age >= hold_ttl
              - needed=False 其他情况（不存在 / 未过期）
              - age_seconds: .frozen 文件年龄（秒），不存在返回 0

        注：本方法只检查 mtime + ttl，不检查 health（health 检查在
        _action_unfreeze_manifest 内执行，避免重复 curl 调用）。
        """
        frozen_path = f"{self.manifest_path}{MANIFEST_FROZEN_SUFFIX}"
        if not os.path.isfile(frozen_path):
            return False, 0
        try:
            mtime = os.path.getmtime(frozen_path)
            age = int(time.time() - mtime)
        except OSError:
            return False, 0
        if age < self.hold_ttl:
            return False, age
        return True, age

    def _action_clear_logs(self, action: Action, ts: int) -> ActionResult:
        logs_dir = os.path.join(self.deploy_root, "logs")
        if not os.path.isdir(logs_dir):
            return ActionResult(
                action=action,
                ok=False,
                detail=f"no logs dir under {self.deploy_root}",
                ts=ts,
            )
        result = self._run_subprocess(
            ["find", logs_dir, "-mtime", "+7", "-delete"],
            timeout=CLEAR_LOGS_TIMEOUT,
        )
        if result.returncode != 0:
            return ActionResult(
                action=action,
                ok=False,
                detail=f"find -mtime +7 -delete failed: {result.stderr.strip() or result.stdout.strip()}",
                ts=ts,
            )
        return ActionResult(
            action=action,
            ok=True,
            detail=f"logs older than 7d cleared under {logs_dir}",
            ts=ts,
        )

    # ------------------------------------------------------------------ #
    # open_incident_issue：GitHub REST API 创建 incident issue
    # ------------------------------------------------------------------ #

    def _action_open_incident_issue(self, action: Action, ts: int) -> ActionResult:
        """创建 GitHub incident issue（兜底：前置 remediation action 失败时）。

        设计要点：
          1. token / repo 缺失 → ok=False（不阻断 watcher 主流程，仅 audit 记录）
          2. 前置 remediation action 在最近 audit 中成功 → ok=True, idempotent skip
             （通过 action.params.previous_action_key 指定前 action 的 idempotency_key）
          3. 24h 同指纹去重：GitHub Search API 查询 open issue 中同 title prefix
             命中 → ok=True, idempotent skip，detail 含已有 issue URL
          4. 创建 issue：POST /repos/{repo}/issues，labels 含 ai-implement + incident
             + auto-incident + auto-generated；ai-issue-implement.yml workflow 自动触发

        action.params 期望字段：
          - incident_type: str — incident 分类（health_down / disk_full /
            manifest_drift / compose_unhealthy）
          - previous_action_key: str — 前置 remediation action 的 idempotency_key
            （用于读 audit 判定前置是否失败）
          - source_kind: str — 信号 kind（与 incident_type 通常一致）
          - reason: str — incident 描述（用于 issue title）
          - diagnosis_root_cause: str — 根因（issue body 证据）
          - evidence: dict — 证据快照（issue body 证据，可选）
          - truth_snapshot: dict — truth 摘要（issue body 证据，可选）
        """
        # 1. token / repo 缺失 → 跳过（不阻断主流程）
        github_token = self.github_token
        github_repo = self.github_repo
        if not github_token or not github_repo:
            return ActionResult(
                action=action,
                ok=False,
                detail=(
                    "github_token/github_repo not configured "
                    "(env GITHUB_TOKEN/GITHUB_REPOSITORY or constructor arg)"
                ),
                ts=ts,
            )

        params = action.params or {}
        incident_type = str(params.get("incident_type") or "unknown")
        previous_action_key = str(params.get("previous_action_key") or "")

        # 2. 前置 remediation action 成功 → 跳过（idempotent）
        if previous_action_key:
            prev_ok, prev_detail = self._check_previous_action_result(previous_action_key)
            if prev_ok:
                return ActionResult(
                    action=action,
                    ok=True,
                    detail=(
                        f"previous action {previous_action_key} succeeded, "
                        f"skip incident issue (idempotent): {prev_detail}"
                    ),
                    ts=ts,
                )

        # 3. 24h 同指纹去重：GitHub Search API
        title = self._build_incident_title(incident_type, params)
        existing_issue = self._search_recent_incident(incident_type, params)
        if existing_issue is not None:
            issue_url = existing_issue.get("html_url") or ""
            issue_number = existing_issue.get("number") or 0
            return ActionResult(
                action=action,
                ok=True,
                detail=(f"incident issue #{issue_number} already exists (24h dedup): {issue_url}"),
                ts=ts,
            )

        # 4. 创建 issue
        body = self._build_incident_body(action, params)
        resp = self._github_post(
            f"https://api.github.com/repos/{github_repo}/issues",
            github_token,
            {
                "title": title,
                "body": body,
                "labels": list(INCIDENT_ISSUE_LABELS),
            },
        )
        if resp.get("_error"):
            return ActionResult(
                action=action,
                ok=False,
                detail=(
                    f"github create issue failed {resp['_error']}: "
                    f"{str(resp.get('_body') or '')[:200]}"
                ),
                ts=ts,
            )
        issue_url = resp.get("html_url") or ""
        issue_number = resp.get("number") or 0
        return ActionResult(
            action=action,
            ok=True,
            detail=f"incident issue #{issue_number} created: {issue_url}",
            ts=ts,
        )

    def _check_previous_action_result(self, idempotency_key: str) -> tuple[bool, str]:
        """读取 audit.jsonl 找最近的同 idempotency_key action 结果。

        Returns:
            (ok, detail):
              - ok=True 当最近一次同 key action 成功（result.ok=True）
              - ok=False 当最近一次失败、或无记录（视为前置未成功，需创建 issue）
        """
        try:
            entries = list_audit_entries(self.audit_path)
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - script boundary records arbitrary integration failures
            return False, "audit read failed"
        # 倒序找最近的同 key action（跳过 skipped / escalate / open_incident_issue 自身）
        for entry in reversed(entries):
            action_obj = entry.get("action")
            if not isinstance(action_obj, dict):
                continue
            entry_key = action_obj.get("idempotency_key") or ""
            if entry_key != idempotency_key:
                continue
            entry_type = action_obj.get("type") or ""
            # 跳过同 key 的 escalate / open_incident_issue（它们与 remediation 同 key 时
            # 不能视为 remediation 本身的结果）
            if entry_type in (
                ActionType.ESCALATE.value,
                ActionType.OPEN_INCIDENT_ISSUE.value,
            ):
                continue
            result_obj = entry.get("result") or {}
            ok = bool(result_obj.get("ok"))
            detail = str(result_obj.get("detail") or "")
            return ok, detail
        return False, f"no previous action with key={idempotency_key} in audit"

    def _build_incident_title(self, incident_type: str, params: dict[str, Any]) -> str:
        """构造 issue title：[incident:{type}] {reason_short}。

        title 中含 incident_type 用于 24h 同指纹去重 search。
        reason 截断到 60 字符（与 capability_proposal_to_issue._build_issue_title 一致）。
        """
        reason = str(params.get("reason") or incident_type).strip()
        if len(reason) > 60:
            reason = reason[:60] + "..."
        return f"[incident:{incident_type}] {reason}"

    def _build_incident_body(self, action: Action, params: dict[str, Any]) -> str:
        """构造 issue body：含来源、根因、证据快照、truth 摘要、闭环说明。"""
        incident_type = str(params.get("incident_type") or "unknown")
        source_kind = str(params.get("source_kind") or incident_type)
        reason = str(params.get("reason") or "")
        root_cause = str(params.get("diagnosis_root_cause") or "")
        previous_action_key = str(params.get("previous_action_key") or "")
        evidence = params.get("evidence") or {}
        truth_snapshot = params.get("truth_snapshot") or {}
        audit_ts = datetime.now(UTC).isoformat()

        evidence_json = (
            json.dumps(evidence, ensure_ascii=False, indent=2) if evidence else "(无附加证据)"
        )
        truth_json = (
            json.dumps(truth_snapshot, ensure_ascii=False, indent=2, default=str)
            if truth_snapshot
            else "(watcher 未注入 truth 摘要)"
        )

        return (
            "## 来源：CVM 自治 watcher incident\n\n"
            f"- **触发时间**: `{audit_ts}`\n"
            f"- **incident 类型**: `{incident_type}`\n"
            f"- **信号 kind**: `{source_kind}`\n"
            f"- **前置 remediation action**: `{previous_action_key or '-'}`\n"
            f"- **根因**: `{root_cause or '-'}`\n\n"
            "## 触发原因\n\n"
            f"前置 remediation action 失败或耗尽 max_attempts，watcher 兜底创建本 issue。\n\n"
            f"```\n{reason}\n```\n\n"
            "## 证据快照\n\n```json\n"
            f"{evidence_json}\n```\n\n"
            "## RuntimeTruthSnapshot 摘要\n\n```json\n"
            f"{truth_json}\n```\n\n"
            "## 进化状态闭环\n\n"
            "1. 本 issue 由 `cvm-autonomy-watcher.yml` workflow 自动创建\n"
            "2. 已打 `ai-implement` + `incident` + `auto-incident` + `auto-generated` 标签\n"
            "3. 命中 `config/auto-implement-allowlist.yaml` 中 `^incident$` 域预授权 pattern，"
            "`ai-issue-implement.yml` workflow 将自动生成修复 PR（无需 owner 评论确认）\n"
            "4. 修复 PR 标 `needs-human` 待人工 review 合并\n"
            "5. 同 incident_type 的 open issue 在 24h 内去重，避免反复创建\n\n"
            "## 修复建议\n\n"
            "- 检查 `/opt/fhd-full/autonomy/audit.jsonl` 最近条目定位失败链路\n"
            "- 评估是否需要扩展 policy / 调整 max_attempts / 升级 remediation action\n"
            "- 若 incident 由代码 bug 引发 → 在 PR 中补充回归测试\n"
        )

    def _search_recent_incident(
        self, incident_type: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        """GitHub Search API 查询 24h 内同 incident_type 的 open issue。

        查询：repo:{github_repo} label:incident label:auto-incident is:issue is:open
              created:>={24h_ago_iso} "[incident:{type}]" in:title

        Returns:
            命中 issue 的 dict（含 number / html_url），无命中返回 None。
        """
        since_iso = (datetime.now(UTC) - timedelta(hours=self.incident_dedup_window_h)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        # title 中含 [incident:{type}] 前缀
        title_prefix = f"[incident:{incident_type}]"
        # GitHub search query 语法：双引号包裹精确短语
        query = (
            f"repo:{self.github_repo} "
            f"label:incident label:auto-incident "
            f"is:issue is:open "
            f"created:>={since_iso} "
            f'"{title_prefix}" in:title'
        )
        search_url = (
            "https://api.github.com/search/issues?q=" + urllib.parse.quote(query) + "&per_page=5"
        )
        token = self.github_token
        if not token:
            return None
        resp = self._github_get(search_url, token)
        if resp.get("_error"):
            return None
        items = resp.get("items")
        if not isinstance(items, list) or not items:
            return None
        # 取第一个匹配项（search 已按 created desc 排序，最近的在最前）
        first = items[0]
        return first if isinstance(first, dict) else None

    def _github_get(self, url: str, token: str) -> dict[str, Any]:
        """GitHub API GET（与 ai_issue_implement._gh_get 同模式）。"""
        if self._github_api_get is not None:
            try:
                return self._github_api_get(url, token)
            except RECOVERABLE_ERRORS as e:  # noqa: BLE001 - script boundary records arbitrary integration failures
                return {"_error": "mock_threw", "_body": str(e)}
        req = urllib.request.Request(
            url,
            headers=_github_headers(token),
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=GITHUB_API_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload if isinstance(payload, dict) else {"_error": "invalid_json_shape"}
        except urllib.error.HTTPError as exc:
            return {"_error": exc.code, "_body": exc.read().decode("utf-8", errors="replace")}
        except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - script boundary records arbitrary integration failures
            return {"_error": "request_threw", "_body": str(exc)}

    def _github_post(self, url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        """GitHub API POST（与 ai_issue_implement._gh_post 同模式）。"""
        if self._github_api_post is not None:
            try:
                return self._github_api_post(url, token, body)
            except RECOVERABLE_ERRORS as e:  # noqa: BLE001 - script boundary records arbitrary integration failures
                return {"_error": "mock_threw", "_body": str(e)}
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers=_github_headers(token),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=GITHUB_API_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload if isinstance(payload, dict) else {"_error": "invalid_json_shape"}
        except urllib.error.HTTPError as exc:
            return {"_error": exc.code, "_body": exc.read().decode("utf-8", errors="replace")}
        except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - script boundary records arbitrary integration failures
            return {"_error": "request_threw", "_body": str(exc)}

    # ------------------------------------------------------------------ #
    # audit：写 audit.jsonl（不抛错）
    # ------------------------------------------------------------------ #

    def audit(self, entry: AuditEntry) -> None:
        """写审计条目到 audit.jsonl。失败静默，不影响主流程。"""
        try:
            payload = self._serialize_audit_entry(entry)
            os.makedirs(self.audit_dir, exist_ok=True)
            with open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - script boundary records arbitrary integration failures
            # 审计失败不影响主流程
            pass

    @staticmethod
    def _serialize_audit_entry(entry: AuditEntry) -> dict[str, Any]:
        """将 AuditEntry 序列化为 JSON 友好的 dict。

        dataclass / Enum 都转为原生类型；Signal / Diagnosis / Action / ActionResult
        递归转 dict。
        """

        def _convert(obj: Any) -> Any:
            if obj is None:
                return None
            if isinstance(obj, bool | int | float | str):
                return obj
            if isinstance(obj, ActionType | RiskLevel):
                return obj.value
            if isinstance(obj, dict):
                return {k: _convert(v) for k, v in obj.items()}
            if isinstance(obj, list | tuple):
                return [_convert(v) for v in obj]
            # dataclass-like：有 __dict__
            if hasattr(obj, "__dict__"):
                return {k: _convert(v) for k, v in vars(obj).items() if not k.startswith("_")}
            return str(obj)

        return {
            "ts": entry.ts,
            "source_signal": _convert(entry.source_signal),
            "diagnosis": _convert(entry.diagnosis),
            "action": _convert(entry.action),
            "result": _convert(entry.result),
            "truth_snapshot": _convert(entry.truth_snapshot),
        }

    # ------------------------------------------------------------------ #
    # subprocess 包装（便于测试注入 mock）
    # ------------------------------------------------------------------ #

    def _run_subprocess(
        self,
        cmd: list[str],
        timeout: int,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        """运行 subprocess.run(cmd, timeout=, capture_output=True, text=True)。

        测试可通过设置 ``self._subprocess_runner`` 替代真实调用。
        """
        if self._subprocess_runner is not None:
            return self._subprocess_runner(cmd, timeout=timeout, cwd=cwd, env=env)
        return subprocess.run(  # noqa: S603 - cmd 是 list，非 shell=True
            cmd,
            timeout=timeout,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
            check=False,
        )


# 类型别名：避免与 ActionType 冲突（仅用于 _serialize_audit_entry 内部）


def list_audit_entries(audit_path: str) -> list[dict[str, Any]]:
    """读取 audit.jsonl 文件，返回 dict 列表（测试辅助）。"""
    entries: list[dict[str, Any]] = []
    if not os.path.isfile(audit_path):
        return entries
    with open(audit_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def cleanup_old_logs(deploy_root: str, days: int = 7) -> bool:
    """独立工具函数：清理 logs 目录中超过 N 天的日志。

    与 _action_clear_logs 解耦，便于单独测试与运维脚本调用。
    """
    logs_dir = os.path.join(deploy_root, "logs")
    if not os.path.isdir(logs_dir):
        return False
    try:
        result = subprocess.run(  # noqa: S603
            ["find", logs_dir, "-mtime", f"+{days}", "-delete"],
            timeout=CLEAR_LOGS_TIMEOUT,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - script boundary records arbitrary integration failures
        return False


def ensure_audit_dir(audit_dir: str) -> None:
    """确保 audit 目录存在（不抛错）。"""
    try:
        Path(audit_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def copy_audit_to_backup(audit_path: str, backup_path: str) -> bool:
    """复制 audit.jsonl 到备份路径（测试辅助）。"""
    try:
        if not os.path.isfile(audit_path):
            return False
        shutil.copy2(audit_path, backup_path)
        return True
    except OSError:
        return False


def parse_signal_kind(signal: Signal | None) -> str:
    """从 Signal 提取 kind（用于 audit source_signal 简化）。"""
    return signal.kind if signal is not None else ""


def _github_headers(token: str) -> dict[str, str]:
    """GitHub API 请求头（与 ai_issue_implement._github_headers 同模式）。"""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
