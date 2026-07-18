"""CvmAutonomyAdapter：服务器端 AutonomyAdapter 实现（Phase 2）。

职责：
  - collect_truth()：采集服务器端 truth（curl 健康检查、docker compose ps、df 磁盘、
    manifest 存在性、.deploy-last.tar.gz 存在性）
  - subscribe_signals()：服务器端无主动信号（由 watcher tick 派生）
  - execute_action()：6 个 action 实现
      * restart_service：cd $DEPLOY_ROOT && docker compose restart（timeout 60s）
      * rollback_to_last_tarball：FHD_RELEASE_TARBALL=... bash fhd-apply-release.sh
        （timeout 300s）
      * freeze_manifest：mv $MANIFEST $MANIFEST.hold（os.rename）
      * clear_logs：find $DEPLOY_ROOT/logs -mtime +7 -delete（timeout 60s）
      * escalate / noop：返回 ok=True（仅审计）
  - audit()：写 $DEPLOY_ROOT/autonomy/audit.jsonl

设计：
  - 所有 shell 命令用 subprocess.run(list, timeout=, capture_output=True, text=True)
    禁止 shell=True
  - 失败模式：subprocess 抛错 / 返回非 0 → 返回 ActionResult(ok=False, detail=str(e))
  - 测试隔离：for_test 类方法注入 mock，跳过真实 docker/df 调用
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .types import Action, ActionResult, AuditEntry, RuntimeTruthSnapshot, Signal, ActionType

# 健康检查 URL（与 docs/CI_SSOT.md 中 cvm-autonomy-watcher 健康检查一致）
DEFAULT_HEALTH_URL = "https://xiu-ci.com/fhd-api/api/health"

# 默认部署根目录（与 fhd-apply-release.sh FHD_DEPLOY_ROOT 一致）
DEFAULT_DEPLOY_ROOT = "/opt/fhd-full"

# 默认 manifest 路径（与 fhd-deploy.yml production MANIFEST 一致）
DEFAULT_MANIFEST_PATH = "/var/www/update/releases/stable/server/fhd-manifest.json"

# action 命令超时（秒）
RESTART_SERVICE_TIMEOUT = 60
ROLLBACK_TIMEOUT = 300
CLEAR_LOGS_TIMEOUT = 60

# docker compose ps 输出中 service 状态关键字
COMPOSE_RUNNING_KEYWORD = "running"


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
    ) -> None:
        self.deploy_root = deploy_root
        self.manifest_path = manifest_path
        self.audit_dir = audit_dir or os.path.join(deploy_root, "autonomy")
        self.health_url = health_url
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
    ) -> "CvmAutonomyAdapter":
        """测试用：创建一个不依赖真实 docker / df / curl 的 adapter 实例。

        测试通过设置 ``_subprocess_runner`` / ``_health_probe`` /
        ``_compose_status_probe`` 注入 mock 行为。
        """
        inst = cls.__new__(cls)
        inst.deploy_root = deploy_root
        inst.manifest_path = manifest_path or os.path.join(
            deploy_root, "releases", "stable", "server", "fhd-manifest.json"
        )
        inst.audit_dir = audit_dir
        inst.health_url = health_url
        inst.audit_path = os.path.join(audit_dir, "audit.jsonl")
        try:
            os.makedirs(audit_dir, exist_ok=True)
        except OSError:
            pass
        inst._subprocess_runner = None
        inst._health_probe = None
        inst._compose_status_probe = None
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
        manifest_frozen = os.path.isfile(f"{self.manifest_path}.hold")
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
            except Exception:
                return False
        # 真实路径：subprocess 调用 curl
        try:
            result = self._run_subprocess(
                ["curl", "-sf", "-o", "/dev/null", "-m", "5", "-w", "%{http_code}", self.health_url],
                timeout=10,
            )
            return result.returncode == 0 and result.stdout.strip() == "200"
        except Exception:
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
            except Exception:
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
        except Exception:
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
        except Exception:
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
    # execute_action：6 个 action 实现
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
            if action.type == ActionType.CLEAR_LOGS:
                return self._action_clear_logs(action, ts)
            if action.type == ActionType.ESCALATE:
                return ActionResult(action=action, ok=True, detail="escalate acknowledged", ts=ts)
            if action.type == ActionType.NOOP:
                return ActionResult(action=action, ok=True, detail="noop acknowledged", ts=ts)
            return ActionResult(
                action=action, ok=False, detail=f"not-implemented:{action.type.value}", ts=ts
            )
        except Exception as e:
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
        apply_script = os.path.join(
            self.deploy_root, "scripts", "deploy", "fhd-apply-release.sh"
        )
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
        hold_path = f"{self.manifest_path}.hold"
        if os.path.isfile(hold_path):
            return ActionResult(
                action=action,
                ok=False,
                detail=f"manifest already frozen: {hold_path} exists",
                ts=ts,
            )
        try:
            os.rename(self.manifest_path, hold_path)
        except OSError as e:
            return ActionResult(
                action=action,
                ok=False,
                detail=f"freeze_manifest rename failed: {e}",
                ts=ts,
            )
        return ActionResult(
            action=action,
            ok=True,
            detail=f"manifest frozen: {self.manifest_path} → {hold_path}",
            ts=ts,
        )

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
    # audit：写 audit.jsonl（不抛错）
    # ------------------------------------------------------------------ #

    def audit(self, entry: AuditEntry) -> None:
        """写审计条目到 audit.jsonl。失败静默，不影响主流程。"""
        try:
            payload = self._serialize_audit_entry(entry)
            os.makedirs(self.audit_dir, exist_ok=True)
            with open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except Exception:
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
            if isinstance(obj, ActionType | RiskLevelType):
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
RiskLevelType = type  # 占位；实际枚举见 types.RiskLevel


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
    except Exception:
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
