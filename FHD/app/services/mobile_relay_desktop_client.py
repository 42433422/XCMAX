"""Desktop-side cloud relay client.

The desktop runtime registers itself with the cloud relay, persists the private
desktop token locally, and polls the cloud for tasks submitted by the mobile app.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import socket
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from app.services.relay_gitops import GIT_OP_KINDS, handle_git_op
from app.utils.path_utils import get_app_data_dir, get_desktop_state_dir

logger = logging.getLogger(__name__)

ClaudeSuperEmployeeService: Any | None = None
CodexSuperEmployeeService: Any | None = None
CursorSuperEmployeeService: Any | None = None

_STATE_LOCK = threading.Lock()
_WORKER_THREAD: threading.Thread | None = None
_STOP_EVENT = threading.Event()
# 配对凭证落在稳定的桌面态目录，绝不随源码 cwd 漂移（见 get_desktop_state_dir 文档）。
# 历史上 get_app_data_dir() 源码直跑会回落到仓库根，桌面便以与手机已配对 relay 不同
# 的身份去轮询，任务永远卡在「排队中」。
_CONFIG_FILE = Path(get_desktop_state_dir()) / "mobile_relay_desktop.json"
_LEGACY_CONFIG_FILE = Path(get_app_data_dir()) / "mobile_relay_desktop.json"
_LEGACY_MIGRATION_DONE = False


def _migrate_legacy_config_once() -> None:
    """旧版把配对凭证写到 get_app_data_dir()（可能回落仓库根）。

    若稳定路径尚无配置、而旧路径存在，则一次性迁移过来，避免源码升级后丢失既有配对。
    稳定路径已有配置时**绝不覆盖**（它才是当前权威绑定）。
    """
    global _LEGACY_MIGRATION_DONE
    if _LEGACY_MIGRATION_DONE:
        return
    _LEGACY_MIGRATION_DONE = True
    try:
        if _CONFIG_FILE.is_file() or not _LEGACY_CONFIG_FILE.is_file():
            return
        if _CONFIG_FILE.resolve() == _LEGACY_CONFIG_FILE.resolve():
            return
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(_LEGACY_CONFIG_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info("迁移历史云中继配对凭证 %s -> %s", _LEGACY_CONFIG_FILE, _CONFIG_FILE)
    except OSError:
        logger.warning("云中继配对凭证迁移失败", exc_info=True)


# 并发执行：poll 循环只负责"认领+派发"，每个任务在独立线程里跑，
# 避免单个长任务(开发任务可跑数分钟)堵死整条队列、导致新消息卡住。
_INFLIGHT: set[str] = set()
_INFLIGHT_LOCK = threading.Lock()

_BRANCH_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,179}")
_MERGE_TEXT_MARKERS = ("合并", "merge")
_DIFF_TEXT_MARKERS = ("diff", "查看改动", "看改动")
_DISCARD_TEXT_MARKERS = ("discard", "丢弃", "删除分支", "废弃")
_FAILURE_BODY_MARKERS = (
    "BLOCKED",
    "blocked",
    "未完成",
    "无法完成",
    "不能完成",
    "没有完成",
    "执行失败",
    "失败：",
    "验证未通过",
    "合并有冲突",
    "merge conflict",
    "无改动可提交",
    "未产生可提交改动",
    "先不动代码",
    "只给出执行方案",
    "仅提供方案",
    "不能执行命令",
    "不能执行",
    "不能读工作区",
    "不能读取工作区",
    "不能跑测试",
    "未跑测试",
    "没有跑测试",
    "权限不足",
    "没有真实执行",
    "没有实际改动",
    "未修改文件",
    "无测试证据",
    "没有测试证据",
    "正在搜索",
    "正在实现",
    "正在处理",
    "正在执行",
    "搜索代码库",
    "我只出",
    "只出验收口径",
    "只出风险",
    "只出收口",
    "仅做验收",
    "仅做风险",
    "仅做收口",
    "仅做分析",
    "待回写",
    "等待回写",
    "❌",
)
_EXECUTION_MESSAGE_MARKERS = (
    "修复",
    "实现",
    "开发",
    "添加",
    "新增",
    "更新",
    "删除",
    "改造",
    "优化",
    "测试",
    "验收",
    "构建",
    "编译",
    "安装",
    "合并",
    "bug",
    "功能",
    "页面",
    "接口",
    "代码",
    "apk",
    "branch",
    "merge",
)
_EXECUTION_EVIDENCE_MARKERS = (
    "已修改",
    "修改了",
    "新增",
    "删除了",
    "更新了",
    "改动文件",
    "文件：",
    "测试通过",
    "验证通过",
    "编译通过",
    "构建通过",
    "安装成功",
    "pytest",
    "ruff",
    "gradle",
    "assemble",
    "adb",
    "git diff",
    "commit",
    "changed files",
    "tests passed",
    "test passed",
    "command:",
    "commands:",
    "命令：",
    "运行：",
    "验证：",
    "测试：",
    "构建：",
    "安装：",
    "手机复测",
    "真机复测",
    "群里复测",
)
_EVIDENCE_FILE_RE = re.compile(
    r"(?i)\b[\w./-]+\.(py|kt|java|ts|tsx|js|jsx|json|ya?ml|md|gradle|xml|sql|swift|go|rs)\b"
)
_FAILED_STATUSES = {"failed", "error", "merge_conflict", "cancelled"}
_BLOCKED_STATUSES = {"blocked", "timeout"}
_COMPLETED_STATUSES = {"completed", "done", "merged"}


def _ensure_super_employee_service_classes() -> None:
    global ClaudeSuperEmployeeService, CodexSuperEmployeeService, CursorSuperEmployeeService
    if (
        ClaudeSuperEmployeeService is not None
        and CodexSuperEmployeeService is not None
        and CursorSuperEmployeeService is not None
    ):
        return
    if ClaudeSuperEmployeeService is None:
        from app.application.claude_super_employee_service import (
            ClaudeSuperEmployeeService as _ClaudeSuperEmployeeService,
        )

        ClaudeSuperEmployeeService = _ClaudeSuperEmployeeService
    if CodexSuperEmployeeService is None:
        from app.application.codex_super_employee_service import (
            CodexSuperEmployeeService as _CodexSuperEmployeeService,
        )

        CodexSuperEmployeeService = _CodexSuperEmployeeService
    if CursorSuperEmployeeService is None:
        from app.application.cursor_super_employee_service import (
            CursorSuperEmployeeService as _CursorSuperEmployeeService,
        )

        CursorSuperEmployeeService = _CursorSuperEmployeeService


def _max_concurrent() -> int:
    try:
        return max(1, int(os.environ.get("XCAGI_RELAY_MAX_CONCURRENT") or "3"))
    except (TypeError, ValueError):
        return 3


def _relay_base_url() -> str:
    value = (
        os.environ.get("XCAGI_RELAY_BASE_URL")
        or os.environ.get("XCAGI_PUBLIC_FHD_BASE_URL")
        or "https://xiu-ci.com/fhd-api"
    ).strip()
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/") + "/"


def _api_url(path: str, base_url: str | None = None) -> str:
    base = (base_url or _relay_base_url()).rstrip("/") + "/"
    return f"{base}{path.lstrip('/')}"


def _read_config() -> dict[str, Any]:
    try:
        if not _CONFIG_FILE.is_file():
            return {}
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.warning("mobile relay desktop config is unreadable: %s", _CONFIG_FILE, exc_info=True)
        return {}


def _public_payload_from_config(config: dict[str, Any]) -> dict[str, Any] | None:
    relay_id = str(config.get("relay_id") or "").strip()
    pairing_code = str(config.get("pairing_code") or "").strip()
    if not relay_id or not pairing_code:
        return None
    base_url = str(config.get("relay_base_url") or "").strip() or _relay_base_url()
    exp = int(config.get("exp") or 0)
    if exp <= 0:
        registered_at = int(config.get("registered_at") or 0)
        if registered_at > 0:
            exp = registered_at + int(os.environ.get("XCAGI_RELAY_PAIRING_TTL_SEC") or "86400")
    if exp > 0 and exp <= int(time.time()):
        return None
    expires_at = str(config.get("expires_at") or "").strip()
    return {
        "relay_id": relay_id,
        "pairing_code": pairing_code,
        **({"expires_at": expires_at} if expires_at else {}),
        **({"exp": exp} if exp > 0 else {}),
        "relay_base_url": base_url,
        "qr_json": {
            "v": 3,
            "kind": "xcagi_relay_pairing",
            "relay_id": relay_id,
            "code": pairing_code,
            "t": pairing_code,
            "relay_base_url": base_url,
        },
    }


def cached_desktop_relay_payload() -> dict[str, Any] | None:
    """Return the public part of the persisted relay binding, if available."""
    return _public_payload_from_config(_read_config())


def _write_config(data: dict[str, Any]) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def register_desktop_relay(*, host: str, port: int, label: str = "") -> dict[str, Any] | None:
    """Register this desktop with the public relay and start the poller."""
    base_url = _relay_base_url()
    device_label = label.strip() or f"XCAGI 桌面执行端 - {socket.gethostname()}"
    body = {
        "label": device_label,
        "device_id": f"{socket.gethostname()}:{port}",
        "relay_base_url": base_url,
        "capabilities": {
            "codex": True,
            "codex_cli": True,
            "claude": True,
            "claude_cli": True,
            "cursor": True,
            "cursor_cli": True,
            "desktop": True,
            "host": host,
            "port": int(port),
            "platform": platform.platform(),
        },
    }
    timeout = float(os.environ.get("XCAGI_RELAY_REGISTER_TIMEOUT_SEC") or "5")
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                _api_url("/api/mobile/v1/relay/desktop/register", base_url), json=body
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("mobile relay desktop register failed: %s", exc)
        cached = cached_desktop_relay_payload()
        if cached:
            start_desktop_relay_poller()
            return cached
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("desktop_token") or not data.get("relay_id"):
        logger.warning("mobile relay desktop register returned invalid payload")
        return None
    config = {
        "relay_id": str(data.get("relay_id") or ""),
        "desktop_token": str(data.get("desktop_token") or ""),
        "relay_base_url": str(data.get("relay_base_url") or base_url),
        "pairing_code": str(data.get("pairing_code") or ""),
        "expires_at": str(data.get("expires_at") or ""),
        "exp": int(data.get("exp") or 0),
        "registered_at": int(time.time()),
        "label": device_label,
    }
    _write_config(config)
    start_desktop_relay_poller()
    return data


def start_desktop_relay_poller() -> bool:
    """Start the daemon poller if a relay config exists."""
    config = _read_config()
    if not config.get("relay_id") or not config.get("desktop_token"):
        return False
    # 轮询每 4s 一次、长年累月运行；httpx 默认对每个请求打一行 INFO，会把
    # poll 日志刷成噪音（~2 万行/天），白白撑大桌面端日志文件占满磁盘。降到 WARNING，
    # 真正的失败仍由 _poll_loop 自己的 logger.warning 记录。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    global _WORKER_THREAD
    with _STATE_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return True
        _STOP_EVENT.clear()
        _WORKER_THREAD = threading.Thread(
            target=_poll_loop,
            name="xcagi-mobile-relay-desktop",
            daemon=True,
        )
        _WORKER_THREAD.start()
        return True


def stop_desktop_relay_poller() -> None:
    _STOP_EVENT.set()


def _poll_loop() -> None:
    interval = float(os.environ.get("XCAGI_RELAY_POLL_INTERVAL_SEC") or "4")
    while not _STOP_EVENT.is_set():
        try:
            _poll_once()
        except Exception:  # noqa: BLE001
            logger.warning("mobile relay poll failed", exc_info=True)
        _STOP_EVENT.wait(max(1.0, interval))


def _complete_relay_task(
    task: dict[str, Any],
    relay_id: str,
    desktop_token: str,
    base_url: str,
) -> None:
    """在独立线程里执行单个任务并回写结果；不阻塞 poll 循环。"""
    task_id = str(task.get("task_id") or "")
    try:
        result = _execute_task(task)
        relay_status = str(result.pop("_relay_status", "") or "").strip()
        if not relay_status:
            relay_status = "failed" if result.get("error") else "completed"
        timeout = float(os.environ.get("XCAGI_RELAY_POLL_TIMEOUT_SEC") or "30")
        with httpx.Client(timeout=timeout) as client:
            client.post(
                _api_url(f"/api/mobile/v1/relay/desktop/tasks/{task_id}/complete", base_url),
                json={
                    "relay_id": relay_id,
                    "desktop_token": desktop_token,
                    "status": relay_status,
                    "result": result,
                },
            ).raise_for_status()
    except Exception:  # noqa: BLE001
        logger.warning("mobile relay task %s failed", task_id, exc_info=True)
    finally:
        with _INFLIGHT_LOCK:
            _INFLIGHT.discard(task_id)


def _poll_once() -> None:
    config = _read_config()
    relay_id = str(config.get("relay_id") or "").strip()
    desktop_token = str(config.get("desktop_token") or "").strip()
    base_url = str(config.get("relay_base_url") or "").strip() or _relay_base_url()
    if not relay_id or not desktop_token:
        return
    # 只认领空闲槽位数量的任务：claim 后必须有线程去跑，否则会把任务卡在 running。
    with _INFLIGHT_LOCK:
        free = _max_concurrent() - len(_INFLIGHT)
    if free <= 0:
        return
    timeout = float(os.environ.get("XCAGI_RELAY_POLL_TIMEOUT_SEC") or "30")
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            _api_url("/api/mobile/v1/relay/desktop/poll", base_url),
            json={"relay_id": relay_id, "desktop_token": desktop_token, "max_tasks": free},
        )
        if resp.status_code == 404:
            return
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else {}
        tasks = data.get("tasks") if isinstance(data, dict) else []
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or "")
        if not task_id:
            continue
        with _INFLIGHT_LOCK:
            if task_id in _INFLIGHT:
                continue
            _INFLIGHT.add(task_id)
        threading.Thread(
            target=_complete_relay_task,
            args=(task, relay_id, desktop_token, base_url),
            name=f"relay-task-{task_id[:8]}",
            daemon=True,
        ).start()


def _execute_task(task: dict[str, Any]) -> dict[str, Any]:
    kind = str(task.get("kind") or "codex.invoke").strip()
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    # git 操作（合并/diff/丢弃）：手机底部功能键触发，不需要 message，只需 payload.branch。
    if kind in GIT_OP_KINDS:
        return handle_git_op(kind, payload)
    message = str(
        payload.get("message")
        or payload.get("body")
        or payload.get("prompt")
        or payload.get("task")
        or ""
    ).strip()
    if not message:
        return {"error": "任务缺少 message"}
    parsed_git_op = _git_op_from_message(payload, message)
    if parsed_git_op is not None:
        git_kind, git_payload = parsed_git_op
        return handle_git_op(git_kind, git_payload)
    # 中继泛化：按 kind 前缀选择超级员工(codex.* / claude.* / cursor.*)，本地执行后回写。
    _ensure_super_employee_service_classes()
    if kind.startswith("claude"):
        service: Any = ClaudeSuperEmployeeService()
        tool_label = "Claude"
    elif kind.startswith("cursor"):
        service = CursorSuperEmployeeService()
        tool_label = "Cursor"
    elif kind.startswith("codex"):
        service = CodexSuperEmployeeService()
        tool_label = "Codex"
    else:
        return {"error": f"暂不支持的任务类型：{kind}"}
    user_id = int(task.get("created_by_user_id") or payload.get("user_id") or 1)
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    branch = str(payload.get("branch") or "").strip()
    # 群派工(AI 交流圈/超级开发部群)是**明确工单**，带 work_order_id / assigned_task /
    # client_surface=ai_group；自由聊天面没有这些信号。两者都经中继下发，但只有工单需要真执行。
    orig_surface = str(context.get("client_surface") or "").strip().lower()
    is_work_order = (
        orig_surface == "ai_group"
        or bool(str(context.get("work_order_id") or "").strip())
        or bool(str(context.get("assigned_task") or "").strip())
    )
    context = {
        **context,
        "source": "mobile_relay",
        "relay_task_id": str(task.get("task_id") or ""),
        # 保留原始来源(工单是 ai_group)，自由聊天回落 mobile。
        "client_surface": orig_surface or "mobile",
        "target_devices": ["all"],
        # 中继即执行端：永远本地 CLI 执行，绝不把任务再转发给(不可用的)Para 多设备。
        "force_cli_direct": True,
    }
    if branch and not str(context.get("branch") or "").strip():
        context["branch"] = branch
    if is_work_order:
        # 工单：保持 mode=code，让 _is_task_intent 判为开发任务 → 走 _cli_work_prompt 真改文件，
        # 而不是当成"普通对话通道"回避执行(那正是任务以 blocked 收场的根因)。
        context["mode"] = "code"
    elif str(context.get("mode") or "").strip().lower() in {
        "code",
        "task",
        "dispatch",
        "dev",
        "develop",
    }:
        # 自由聊天面固定下发 mode="code"，剥离交回内容分类器(避免"你好"被当开发任务)。
        context.pop("mode", None)
    try:
        result = service.invoke(
            user_id=user_id,
            message=message,
            context=context,
        )
        dispatch = result.get("dispatch") if isinstance(result.get("dispatch"), dict) else {}
        dispatch_status = str(dispatch.get("status") or "").strip().lower()
        if dispatch_status == "completed":
            assistant = (
                result.get("assistant_message")
                if isinstance(result.get("assistant_message"), dict)
                else {}
            )
            ok, relay_status, error = _classify_terminal_result(assistant, message=message)
            if ok:
                return {"ok": True, "codex": result, "_relay_status": "completed"}
            return {
                "ok": False,
                "error": error or f"{tool_label} 回写显示任务未完成",
                "codex": result,
                "_relay_status": relay_status,
            }
        if dispatch.get("accepted") is not True:
            reason = str(dispatch.get("reason") or f"{tool_label}/MCP 调度器当前不可用").strip()
            return {
                "error": reason,
                "codex": result,
                "_relay_status": "blocked",
            }

        request_id = str(dispatch.get("request_id") or "").strip()
        task_id = str(dispatch.get("task_id") or "").strip()
        timeout = max(0.0, float(os.environ.get("XCAGI_RELAY_CODEX_WAIT_TIMEOUT_SEC") or "300"))
        interval = max(0.05, float(os.environ.get("XCAGI_RELAY_CODEX_WAIT_INTERVAL_SEC") or "2"))
        deadline = time.monotonic() + timeout
        while True:
            terminal = _terminal_codex_message(
                service.list_messages(user_id=user_id, limit=200),
                request_id=request_id,
                task_id=task_id,
            )
            if terminal:
                result["assistant_message"] = terminal
                ok, relay_status, error = _classify_terminal_result(terminal, message=message)
                if ok:
                    return {"ok": True, "codex": result, "_relay_status": "completed"}
                return {
                    "ok": False,
                    "error": error or f"{tool_label} 回写显示任务未完成",
                    "codex": result,
                    "_relay_status": relay_status,
                }
            if time.monotonic() >= deadline:
                break
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
        suffix = f"（task_id={task_id}）" if task_id else ""
        return {
            "error": f"{tool_label} 已派发，但在 {timeout:g} 秒内未回写{suffix}",
            "codex": result,
            "_relay_status": "blocked",
        }
    except Exception as exc:
        logger.exception("mobile relay Codex task failed")
        return {"error": str(exc)[:1000]}


def _git_op_from_message(
    payload: dict[str, Any], message: str
) -> tuple[str, dict[str, Any]] | None:
    text = str(message or "").strip()
    lowered = text.lower()
    explicit = str(payload.get("git_op") or payload.get("op") or "").strip()
    explicit_git_op = explicit in GIT_OP_KINDS
    if explicit in GIT_OP_KINDS:
        git_kind = explicit
    elif any(marker in lowered for marker in _MERGE_TEXT_MARKERS):
        git_kind = "git.merge"
    elif any(marker in lowered for marker in _DIFF_TEXT_MARKERS):
        git_kind = "git.diff"
    elif any(marker in lowered for marker in _DISCARD_TEXT_MARKERS):
        git_kind = "git.discard"
    else:
        return None

    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    text_source = _extract_branch_after(text, "SOURCE_", "_TARGET") or _extract_merge_source(text)
    allow_selected_branch = explicit_git_op or _text_mentions_branch_op(text, lowered)
    source = (
        str(payload.get("source_branch") or "").strip()
        or text_source
        or (str(payload.get("branch") or "").strip() if allow_selected_branch else "")
        or (str(context.get("branch") or "").strip() if allow_selected_branch else "")
    )
    target = str(
        payload.get("target_branch") or payload.get("target") or payload.get("base") or ""
    ).strip() or _extract_target_branch(text)
    if git_kind == "git.merge" and not target:
        target = _extract_merge_target(text)
    if not source:
        return None
    git_payload = {**payload, "branch": source, "message": text}
    if target:
        git_payload["target_branch"] = target
    return git_kind, git_payload


def _text_mentions_branch_op(text: str, lowered: str) -> bool:
    return any(
        marker in text or marker in lowered
        for marker in (
            "合并分支",
            "这个分支",
            "当前分支",
            "待合并分支",
            "merge branch",
            "current branch",
            "source branch",
            "target branch",
            "查看分支",
            "丢弃分支",
            "删除分支",
        )
    )


def _extract_branch_after(text: str, prefix: str, suffix: str) -> str:
    pattern = re.compile(
        rf"{re.escape(prefix)}(?P<branch>[A-Za-z0-9._/-]+?){re.escape(suffix)}",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return _trim_branch_token(match.group("branch")) if match else ""


def _extract_target_branch(text: str) -> str:
    match = re.search(r"TARGET(?:_CURRENT)?_(?P<branch>[A-Za-z0-9._/-]+)", text, re.IGNORECASE)
    return _trim_branch_token(match.group("branch")) if match else ""


def _extract_merge_source(text: str) -> str:
    match = re.search(
        r"(?:合并|merge)\s+(?:分支\s*)?(?P<branch>[A-Za-z0-9._/-]+)",
        text,
        re.IGNORECASE,
    )
    return _trim_branch_token(match.group("branch")) if match else ""


def _extract_merge_target(text: str) -> str:
    match = re.search(
        r"(?:到|至|into|->)\s*(?:分支\s*)?(?P<branch>[A-Za-z0-9._/-]+)",
        text,
        re.IGNORECASE,
    )
    return _trim_branch_token(match.group("branch")) if match else ""


def _trim_branch_token(value: str) -> str:
    branch = str(value or "").strip().strip("，,。.;；")
    for marker in (
        "_CHECK",
        "_IF",
        "_RUN",
        "_REPORT",
        "_DO",
        "_SAFE",
        "_STATUS",
        "_FIRST",
        "_THEN",
    ):
        idx = branch.upper().find(marker)
        if idx > 0:
            branch = branch[:idx]
            break
    match = _BRANCH_TOKEN_RE.search(branch)
    return match.group(0) if match else ""


def _classify_terminal_result(row: dict[str, Any], *, message: str) -> tuple[bool, str, str]:
    status = str(row.get("status") or row.get("task_status") or "").strip().lower()
    body = str(row.get("body") or row.get("summary") or row.get("message") or "").strip()
    if status in _FAILED_STATUSES:
        return False, "failed", _terminal_error_summary(body, "执行端回写失败")
    if status in _BLOCKED_STATUSES:
        return False, "blocked", _terminal_error_summary(body, "执行端回写阻塞")
    if body and _body_indicates_unfinished(body):
        relay_status = "failed" if _body_indicates_failed(body) else "blocked"
        return False, relay_status, _terminal_error_summary(body, "执行端回写显示未完成")
    if _message_requires_execution_evidence(message) and not _body_has_execution_evidence(body):
        return (
            False,
            "blocked",
            _terminal_error_summary(
                body,
                "执行端回写缺少改动文件、命令、测试、构建或手机复测证据",
            ),
        )
    if status in _COMPLETED_STATUSES or body:
        return True, "completed", ""
    return True, "completed", ""


def _body_indicates_unfinished(body: str) -> bool:
    if not body:
        return False
    compact = body.replace(" ", "")
    return any(
        marker in body or marker.replace(" ", "") in compact for marker in _FAILURE_BODY_MARKERS
    )


def _body_indicates_failed(body: str) -> bool:
    return any(
        marker in body
        for marker in (
            "失败",
            "failed",
            "合并有冲突",
            "merge conflict",
            "验证未通过",
            "❌",
            "error",
            "Error",
        )
    )


def _message_requires_execution_evidence(message: str) -> bool:
    text = str(message or "").lower()
    return any(marker.lower() in text for marker in _EXECUTION_MESSAGE_MARKERS)


def _body_has_execution_evidence(body: str) -> bool:
    text = str(body or "")
    if not text or _body_indicates_unfinished(text):
        return False
    lower = text.lower()
    if any(marker.lower() in lower for marker in _EXECUTION_EVIDENCE_MARKERS):
        return True
    return _EVIDENCE_FILE_RE.search(text) is not None


def _terminal_error_summary(body: str, fallback: str) -> str:
    for line in body.splitlines():
        clean = line.strip().strip("-*# ")
        if clean:
            return clean[:500]
    return fallback


def _terminal_codex_message(
    messages: list[dict[str, Any]],
    *,
    request_id: str,
    task_id: str,
) -> dict[str, Any] | None:
    for row in reversed(messages):
        if str(row.get("role") or "").strip().lower() != "assistant":
            continue
        kind = str(row.get("kind") or "").strip().lower()
        # 兼容 codex_result/codex_direct 与 claude_result/claude_direct。
        if not (kind.endswith("_result") or kind.endswith("_direct")):
            continue
        row_request = str(row.get("dispatch_request_id") or row.get("request_id") or "").strip()
        row_task = str(row.get("task_id") or "").strip()
        if request_id and row_request != request_id:
            continue
        if task_id and row_task != task_id:
            continue
        if str(row.get("body") or "").strip():
            return row
    return None
