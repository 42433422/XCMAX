"""Owner-bound Computer Use adapters for the existing desktop_automation tool.

The Agent runtime owns planning, approval, task status and billing. This boundary
only fences the physical device and retains non-replayable effect receipts.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from filelock import FileLock, Timeout

from app.domain.autonomy.computer_use_policy import normalize_computer_effect
from app.utils.deployment import env_flag, is_desktop_mode
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from app.desktop_automation.computer_desktop import PyAutoGuiComputer

COMPUTER_ACTIONS = frozenset(
    {"computer_status", "computer_observe", "computer_execute", "computer_stop", "computer_result"}
)
_OBSERVATION_FIELDS = (
    "sha256",
    "width",
    "height",
    "input_width",
    "input_height",
    "coordinate_space",
)


def _failure(code: str, message: str, *, uncertain: bool = False) -> dict[str, Any]:
    return {
        "success": False,
        "error_code": code,
        "message": message,
        "status": "outcome_unknown" if uncertain else "blocked",
        "verified": False,
        "retryable": False,
        **({"outcome": "unknown", "reconciliation_required": True} if uncertain else {}),
    }


def _fingerprint(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _metadata(value: Any) -> Any:
    """Keep effect facts, never duplicate screenshots or page contents on disk."""
    if isinstance(value, dict):
        return {
            key: _metadata(item)
            for key, item in value.items()
            if key not in {"data_url", "aria_snapshot", "text", "value", "title", "url"}
        }
    if isinstance(value, list):
        return [_metadata(item) for item in value]
    return value


class ComputerUseService:
    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            from app.utils.path_io.path_utils import get_app_data_dir

            root = Path(get_app_data_dir()) / "computer-use"
        self.root = root

    def _path(self, owner: str, kind: str, identifier: str) -> Path:
        return self.root / owner / f"{kind}-{_fingerprint(identifier)}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid computer-use receipt")
        return value

    @staticmethod
    def _write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                json.dump(value, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
            if os.name != "nt":
                directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _owner(context: dict[str, Any]) -> str:
        from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor

        try:
            actor = _bound_actor(context)
        except AgentModAuthorizationError as exc:
            raise PermissionError("Computer Use requires a bound actor") from exc
        user, tenant = str(actor.id), str(actor.tenant_id or "")
        if (
            not tenant
            or str(context.get("tenant_id") or "") != tenant
            or user != os.environ.get("XCAGI_COMPUTER_USE_USER_ID", "").strip()
            or tenant != os.environ.get("XCAGI_COMPUTER_USE_TENANT_ID", "").strip()
        ):
            raise PermissionError("本机 Computer Use 未授权给当前账号和企业")
        return _fingerprint([tenant, user])

    @staticmethod
    def _approved(params: dict[str, Any], context: dict[str, Any]) -> None:
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository
        from app.application.agent_orchestrator.tool_permission import approval_execution_denial

        run = get_agent_run_repository().get(str(context.get("run_id") or ""))
        step_id = str(context.get("step_id") or "")
        if run is None or not step_id or run.status != "running":
            raise PermissionError("Computer Use 输入只能由已批准的 Agent 任务执行")
        stored = run.metadata.get("runtime_context") or {}
        if any(
            str(stored.get(key) or "") != str(context.get(key) or "")
            for key in ("user_id", "tenant_id")
        ):
            raise PermissionError("Computer Use 执行身份与原任务不一致")
        step = next((item for item in run.steps if item.step_id == step_id), None)
        receipt = run.metadata.get("approval_receipt") or {}
        dispatch = run.metadata.get("dispatch") or {}
        approved = (
            receipt.get("step_id") == step_id
            and receipt.get("tool_id") == "desktop_automation"
            and receipt.get("action") == "computer_execute"
            and bool(receipt.get("approved_by"))
        ) or (dispatch.get("approved_step_id") == step_id and bool(dispatch.get("approved_by")))
        if (
            not approved
            or step is None
            or step.status != "running"
            or (step.tool_id, step.action) != ("desktop_automation", "computer_execute")
            or step.params != params
            or approval_execution_denial("desktop_automation", "computer_execute", context)
        ):
            raise PermissionError("Computer Use 动作与已批准任务不一致")

    @staticmethod
    def _browser():
        from app.desktop_automation.computer_browser import PlaywrightComputer

        origins = json.loads(os.environ.get("XCAGI_COMPUTER_USE_ALLOWED_ORIGINS", "[]"))
        if not isinstance(origins, list) or any(not isinstance(item, str) for item in origins):
            raise ValueError("XCAGI_COMPUTER_USE_ALLOWED_ORIGINS must be a JSON string array")
        return PlaywrightComputer(
            allowed_origins=tuple(origins),
            executable_path=os.environ.get("XCAGI_COMPUTER_USE_BROWSER_EXECUTABLE") or None,
            headless=not env_flag("XCAGI_COMPUTER_USE_HEADFUL"),
        )

    @staticmethod
    def _desktop() -> PyAutoGuiComputer:
        from app.desktop_automation.computer_desktop import PyAutoGuiComputer

        if not is_desktop_mode():
            raise PermissionError("系统桌面控制只能在桌面宿主运行")
        return PyAutoGuiComputer()

    def invoke(
        self, action: str, params: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            owner = self._owner(context)
            if action not in COMPUTER_ACTIONS:
                return _failure("computer_action_invalid", "未知 Computer Use 动作")
            enabled = env_flag("XCAGI_COMPUTER_USE_ENABLED")
            if action == "computer_status":
                return {
                    "success": True,
                    "enabled": enabled,
                    "desktop_mode": is_desktop_mode(),
                    "dependencies": {
                        name: importlib.util.find_spec(name) is not None
                        for name in ("pyautogui", "pyperclip", "playwright")
                    },
                    "runtime_verified": False,
                    "message": "依赖存在不代表录屏权限、输入权限或浏览器启动已经通过",
                }
            if action in {"computer_stop", "computer_result"}:
                return self._control(action, params, owner)
            if not enabled:
                return _failure("computer_use_disabled", "Computer Use 未在本机启用")
            if action == "computer_observe":
                if params:
                    return _failure("computer_params_invalid", "桌面观察不接受执行参数")
                self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
                with FileLock(str(self.root / "device.lock"), timeout=0):
                    observation = self._desktop().observe()
                    if not observation.get("success"):
                        return observation
                    snapshot_id = uuid.uuid4().hex
                    self._write(
                        self._path(owner, "observation", snapshot_id),
                        {
                            "created_at": time.time(),
                            **{key: observation[key] for key in _OBSERVATION_FIELDS},
                        },
                    )
                    return {**observation, "snapshot_id": snapshot_id, "expires_in_seconds": 120}
            return self._execute(params, context, owner)
        except PermissionError:
            return _failure("computer_permission_denied", "Computer Use 的本机授权或任务审批未通过")
        except Timeout:
            return _failure("computer_busy", "另一任务正在使用此执行器，请先读取其结果")
        except (ValueError, TypeError, KeyError):
            return _failure("computer_params_invalid", "Computer Use 参数、来源配置或回执无效")
        except RECOVERABLE_ERRORS:
            return _failure("computer_unavailable", "Computer Use 依赖、身份服务或回执存储不可用")

    def _control(self, action: str, params: dict[str, Any], owner: str) -> dict[str, Any]:
        request_id = params.get("request_id")
        if (
            set(params) != {"request_id"}
            or not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 128
        ):
            raise ValueError("request_id required")
        record = self._read(self._path(owner, "effect", request_id))
        if not record:
            return _failure("computer_receipt_not_found", "当前账号没有此执行回执")
        if action == "computer_stop" and record.get("state") == "running":
            self._write(self._path(owner, "stop", request_id), {"requested_at": time.time()})
            return {
                "success": True,
                "status": "stop_requested",
                "request_id": request_id,
                "stopped": False,
            }
        result = record.get("result")
        if not isinstance(result, dict):
            result = _failure(
                "computer_outcome_unknown",
                "执行中或终态未回写；请核对原执行，禁止自动重放",
                uncertain=True,
            )
        return {
            **result,
            "request_id": request_id,
            "receipt_state": record.get("state"),
            "replayed": True,
        }

    def _execute(
        self, params: dict[str, Any], context: dict[str, Any], owner: str
    ) -> dict[str, Any]:
        if set(params) - {"request_id", "target", "steps", "verification", "snapshot_id"}:
            raise ValueError("unexpected execution fields")
        request_id, target = params.get("request_id"), params.get("target")
        if (
            not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 128
            or target not in {"desktop", "browser"}
        ):
            raise ValueError("request_id and target required")
        steps, verification = params.get("steps"), params.get("verification")
        if (
            not isinstance(steps, list)
            or not 1 <= len(steps) <= 20
            or (verification is not None and not isinstance(verification, dict))
        ):
            raise ValueError("invalid steps or verification")
        fingerprint = _fingerprint(params)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        uses_desktop = target == "desktop" or env_flag("XCAGI_COMPUTER_USE_HEADFUL")
        lock_name = "device.lock" if uses_desktop else f"browser-{owner}.lock"
        path = self._path(owner, "effect", request_id)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (
            FileLock(str(path) + ".lock", timeout=0),
            FileLock(str(self.root / lock_name), timeout=0),
        ):
            prior = self._read(path)
            if prior:
                if prior.get("fingerprint") != fingerprint:
                    return _failure(
                        "computer_request_conflict", "request_id 已绑定其他动作，未执行"
                    )
                return self._control("computer_result", {"request_id": request_id}, owner)
            self._approved(params, context)
            expected = None
            if target == "desktop":
                snapshot_id = params.get("snapshot_id")
                if not isinstance(snapshot_id, str) or not snapshot_id:
                    raise ValueError("snapshot_id required")
                observed_path = self._path(owner, "observation", snapshot_id)
                expected = self._read(observed_path)
                if (
                    not expected
                    or expected.get("used_by")
                    or not 0 <= time.time() - expected.get("created_at", 0) <= 120
                ):
                    return _failure("stale_observation", "请重新观察桌面后再批准动作")
                adapter = self._desktop()
            else:
                if params.get("snapshot_id"):
                    raise ValueError("browser task does not use a desktop snapshot")
                adapter = self._browser()
                adapter.validate(steps, verification)
            record = {
                "fingerprint": fingerprint,
                "state": "running",
                "run_id": context.get("run_id"),
                "step_id": context.get("step_id"),
                "started_at": time.time(),
            }
            from app.application.agent_orchestrator.run_repository import get_agent_run_repository
            from app.application.agent_orchestrator.verification_surface import (
                execution_surface_binding,
            )

            run = get_agent_run_repository().get(str(context.get("run_id") or ""))
            record["binding"] = execution_surface_binding(run, params, context) if run else {}
            self._write(path, record)
            if expected is not None:
                self._write(observed_path, {**expected, "used_by": request_id})

            def cancelled() -> bool:
                from app.application.agent_orchestrator.business_write_guard import (
                    recheck_worker_claim,
                )
                from app.application.agent_orchestrator.run_repository import (
                    get_agent_run_repository,
                )
                from app.application.tool_execution_deadline import check_invocation_deadline

                check_invocation_deadline()
                recheck_worker_claim()
                self._owner(context)
                command = get_agent_run_repository().latest_task_control(
                    str(context.get("run_id") or "")
                )
                return (
                    not env_flag("XCAGI_COMPUTER_USE_ENABLED")
                    or self._path(owner, "stop", request_id).exists()
                    or bool(command and command.action in {"pause", "cancel"})
                )

            try:
                result = adapter.execute(
                    steps,
                    verification,
                    cancelled=cancelled,
                    **({"expected": expected} if expected is not None else {}),
                )
            except BOUNDARY_ERRORS:  # adapter boundary; input may already have occurred
                result = _failure(
                    "computer_outcome_unknown",
                    "输入执行中断，结果须核对，未自动重试",
                    uncertain=True,
                )
            result = normalize_computer_effect(
                {**result, "request_id": request_id, "run_id": context.get("run_id")}
            )
            try:
                self._write(
                    path,
                    {
                        **record,
                        "state": "finished",
                        "finished_at": time.time(),
                        "result": _metadata(result),
                    },
                )
            except OSError:
                return _failure(
                    "computer_receipt_unknown", "动作后回执未持久化，须核对原执行", uncertain=True
                )
            return result


def invoke_computer_use(
    action: str, params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    return ComputerUseService().invoke(action, params, context)
