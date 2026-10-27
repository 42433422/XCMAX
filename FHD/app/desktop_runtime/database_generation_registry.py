"""SQLite 数据库代次、恢复锁与可写状态协议（业务层共享边界）。

本模块只负责保护协议，不执行具体恢复动作（恢复动作见 ``restore_helper``）。
设计约束：

* 一个数据库同一时刻只允许一把有效恢复锁，路径大小写、短路径、软链接等
  别名必须映射到同一把锁；
* 恢复前必须先持久化 ``CLOSING``/``RESTORING`` 意图，进程异常退出后保留
  ``UNKNOWN``，不能因为文件锁被操作系统释放就允许下一次写入；
* ``OPEN`` 只能通过 ``reopen`` 显式恢复，且必须核验目标身份、完整性、
  成功回执与旧进程隔离；不存在“手工删标记即恢复”的路径；
* 普通写入通过 ``write_lease`` 取得代次令牌，恢复完成后旧令牌立即失效。

状态机::

    OPEN -> CLOSING -> RESTORING -> VERIFYING -> OPEN（代次 +1）
                            |             |
                            +-> UNKNOWN <-+

错误返回约定（业务层按 ``code`` 映射 HTTP）：``GuardError.to_dict()`` 返回
``code/message/state/generation/operationId/retryable``。写入被拒绝时应返回
503（临时不可写）或 409（需要人工处置），不得吞掉错误继续写库。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

from app.utils.process_lock import exclusive_file_lock
from app.utils.time import utc_now_naive

GUARD_DIRNAME = ".xcagi-db-guard"
STATE_SCHEMA = 1
_DEFAULT_RESTORE_TIMEOUT = 30.0
_DEFAULT_WRITER_DRAIN_TIMEOUT = 60.0
_DEFAULT_ADMISSION_TIMEOUT = 30.0


class GuardState(str, Enum):
    """数据库可写状态。除 ``OPEN`` 外一律拒绝普通写入。"""

    OPEN = "OPEN"
    CLOSING = "CLOSING"
    RESTORING = "RESTORING"
    VERIFYING = "VERIFYING"
    UNKNOWN = "UNKNOWN"


class GuardErrorCode(str, Enum):
    CLOSED = "DB_GUARD_CLOSED"
    RESTORING = "DB_GUARD_RESTORING"
    UNKNOWN = "DB_GUARD_UNKNOWN"
    LOCK_TIMEOUT = "DB_GUARD_LOCK_TIMEOUT"
    WRITER_DRAIN_TIMEOUT = "DB_GUARD_WRITER_DRAIN_TIMEOUT"
    STALE_GENERATION = "DB_GUARD_STALE_GENERATION"
    PATH_ESCAPE = "DB_GUARD_PATH_ESCAPE"
    ALIAS = "DB_GUARD_ALIAS"
    TARGET_OVERLAP = "DB_GUARD_TARGET_OVERLAP"
    VERIFY_FAILED = "DB_GUARD_VERIFY_FAILED"
    DUPLICATE_OPERATION = "DB_GUARD_DUPLICATE_OPERATION"
    PARTIAL_RESTORE = "DB_GUARD_PARTIAL_RESTORE"
    BAD_REQUEST = "DB_GUARD_BAD_REQUEST"
    INTENT_PENDING = "DB_GUARD_RESTORE_INTENT_PENDING"


_RETRYABLE_CODES = {
    GuardErrorCode.CLOSED,
    GuardErrorCode.RESTORING,
    GuardErrorCode.LOCK_TIMEOUT,
    GuardErrorCode.WRITER_DRAIN_TIMEOUT,
}


class GuardError(RuntimeError):
    """带稳定错误码的保护协议异常。"""

    def __init__(
        self,
        code: GuardErrorCode,
        message: str,
        *,
        state: GuardState | None = None,
        generation: int | None = None,
        operation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.state = state
        self.generation = generation
        self.operation_id = operation_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "state": self.state.value if self.state else None,
            "generation": self.generation,
            "operationId": self.operation_id,
            "retryable": self.code in _RETRYABLE_CODES,
        }


# ---------------------------------------------------------------------------
# 路径与身份
# ---------------------------------------------------------------------------


def canonical_database_path(path: str | os.PathLike[str]) -> Path:
    """返回数据库真实路径：解析软链接、``..``，Windows 下归一化为长路径。"""
    raw = os.path.abspath(os.path.expanduser(str(path)))
    return Path(os.path.realpath(raw))


def _normcase(value: str) -> str:
    return os.path.normcase(value) if sys.platform == "win32" else value


def _file_identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    if not stat.st_ino:
        return None
    return (int(stat.st_dev), int(stat.st_ino))


def database_identity(path: str | os.PathLike[str]) -> str:
    """稳定身份：归一化真实路径的哈希。

    不能用 inode 作为长期身份：恢复会原子替换数据库文件，inode 随之改变，
    代次状态就会“换钥匙”，旧代次令牌失效判断全部失真。路径身份在替换前后
    保持一致；硬链接别名由 ``assert_no_alias`` 在执行恢复前拒绝。
    """
    resolved = canonical_database_path(path)
    material = f"path:{_normcase(str(resolved))}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def assert_within(root: str | os.PathLike[str], candidate: str | os.PathLike[str]) -> Path:
    """目标必须位于 ``root`` 之内，拒绝越界与软链接逃逸。"""
    root_path = canonical_database_path(root)
    target = canonical_database_path(candidate)
    root_key = _normcase(str(root_path))
    target_key = _normcase(str(target))
    if target_key != root_key and not target_key.startswith(root_key + os.sep):
        raise GuardError(
            GuardErrorCode.PATH_ESCAPE,
            f"目标路径越界：{target} 不在 {root_path} 内",
        )
    return target


def assert_no_alias(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str],
) -> None:
    """拒绝源与目标为同一文件（含硬链接、大小写/短路径别名）。"""
    source_path = canonical_database_path(source)
    target_path = canonical_database_path(target)
    if _normcase(str(source_path)) == _normcase(str(target_path)):
        raise GuardError(
            GuardErrorCode.ALIAS,
            f"源与目标是同一路径：{source_path}",
        )
    source_id = _file_identity(source_path)
    target_id = _file_identity(target_path)
    if source_id is not None and source_id == target_id:
        raise GuardError(
            GuardErrorCode.TARGET_OVERLAP,
            f"源与目标是同一文件（硬链接/别名）：{source_path} -> {target_path}",
        )


# ---------------------------------------------------------------------------
# 跨平台进程存活检测
# ---------------------------------------------------------------------------


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _windows_pid_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


# ---------------------------------------------------------------------------
# 状态持久化
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    with temp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    if hasattr(os, "O_DIRECTORY"):
        try:
            dir_fd = os.open(path.parent, os.O_DIRECTORY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _safe_operation_id(operation_id: str) -> str:
    cleaned = "".join(ch for ch in operation_id if ch.isalnum() or ch in "-_.:")[:120]
    if not cleaned:
        raise GuardError(GuardErrorCode.BAD_REQUEST, "operationId 为空或非法")
    return cleaned


def new_operation_id(prefix: str = "restore") -> str:
    stamp = utc_now_naive().strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:10]}"


@dataclass(frozen=True)
class GuardStatus:
    database: str
    identity: str
    state: GuardState
    generation: int
    operation_id: str | None
    owner_pid: int | None
    updated_at: str

    @property
    def writable(self) -> bool:
        return self.state is GuardState.OPEN

    def to_dict(self) -> dict[str, Any]:
        return {
            "database": self.database,
            "identity": self.identity,
            "state": self.state.value,
            "generation": self.generation,
            "operationId": self.operation_id,
            "ownerPid": self.owner_pid,
            "updatedAt": self.updated_at,
            "writable": self.writable,
        }


@dataclass
class _StateRecord:
    schema: int
    database: str
    identity: str
    state: GuardState
    generation: int
    operation_id: str | None = None
    owner_pid: int | None = None
    updated_at: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "database": self.database,
            "identity": self.identity,
            "state": self.state.value,
            "generation": self.generation,
            "operationId": self.operation_id,
            "ownerPid": self.owner_pid,
            "updatedAt": self.updated_at,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# 守卫
# ---------------------------------------------------------------------------


class DatabaseGuard:
    """单个数据库的保护协议入口。"""

    def __init__(self, database: str | os.PathLike[str]) -> None:
        self.database = canonical_database_path(database)
        self.identity = database_identity(self.database)
        self.guard_dir = self.database.parent / GUARD_DIRNAME
        self._state_path = self.guard_dir / f"state-{self.identity}.json"
        self._restore_lock_path = self.guard_dir / f"restore-{self.identity}.lock"
        self._admission_lock_path = self.guard_dir / f"admission-{self.identity}.lock"
        self._writers_dir = self.guard_dir / f"writers-{self.identity}"
        self._receipts_dir = self.guard_dir / f"receipts-{self.identity}"
        self._audit_path = self.guard_dir / f"audit-{self.identity}.jsonl"
        self._intent_path = self.guard_dir / f"intent-{self.identity}.json"
        self._active_session: RestoreSession | None = None

    # -- 读取 ---------------------------------------------------------------

    def _read_record(self) -> _StateRecord | None:
        try:
            raw = self._state_path.read_bytes()
        except FileNotFoundError:
            return None
        payload = json.loads(raw.decode("utf-8"))
        return _StateRecord(
            schema=int(payload.get("schema", STATE_SCHEMA)),
            database=str(payload.get("database") or ""),
            identity=str(payload.get("identity") or ""),
            state=GuardState(str(payload.get("state") or GuardState.OPEN.value)),
            generation=int(payload.get("generation") or 0),
            operation_id=payload.get("operationId"),
            owner_pid=payload.get("ownerPid"),
            updated_at=str(payload.get("updatedAt") or ""),
            detail=dict(payload.get("detail") or {}),
        )

    def _write_record(self, record: _StateRecord) -> None:
        record.schema = STATE_SCHEMA
        record.database = str(self.database)
        record.identity = self.identity
        record.updated_at = utc_now_naive().isoformat()
        _atomic_write_json(self._state_path, record.to_payload())

    def _default_record(self) -> _StateRecord:
        return _StateRecord(
            schema=STATE_SCHEMA,
            database=str(self.database),
            identity=self.identity,
            state=GuardState.OPEN,
            generation=0,
        )

    def _effective_record(self) -> _StateRecord:
        """读取状态；租约型状态的所有者已消失时立即降级为 ``UNKNOWN``。"""
        record = self._read_record() or self._default_record()
        if record.state in {
            GuardState.CLOSING,
            GuardState.RESTORING,
            GuardState.VERIFYING,
        } and record.owner_pid and not pid_alive(record.owner_pid):
            previous_state = record.state
            operation_id = record.operation_id
            record.state = GuardState.UNKNOWN
            record.detail = {
                **record.detail,
                "unknownReason": "owner_process_gone",
                "previousState": previous_state.value,
                "detectedAt": utc_now_naive().isoformat(),
            }
            self._write_record(record)
            self._audit(
                "state_unknown",
                operation_id=operation_id,
                generation=record.generation,
                extra={"reason": "owner_process_gone"},
            )
        return record

    def status(self) -> GuardStatus:
        record = self._effective_record()
        return GuardStatus(
            database=str(self.database),
            identity=self.identity,
            state=record.state,
            generation=record.generation,
            operation_id=record.operation_id,
            owner_pid=record.owner_pid,
            updated_at=record.updated_at,
        )

    def require_writable(self) -> GuardStatus:
        status = self.status()
        if status.state is GuardState.OPEN:
            return status
        raise self._state_error(status)

    def require_startable(self) -> GuardStatus:
        """启动时门禁：状态必须 OPEN，且不存在未完成的恢复意图。"""
        status = self.status()
        if status.state is not GuardState.OPEN:
            raise self._state_error(status)
        intent = self.read_intent()
        if intent is not None:
            raise GuardError(
                GuardErrorCode.INTENT_PENDING,
                f"存在未完成的恢复意图：{intent.get('operationId')}",
                state=status.state,
                generation=status.generation,
                operation_id=intent.get("operationId"),
            )
        return status

    # -- 恢复意图（在真正启动恢复前落盘） ----------------------------------

    def write_intent(
        self,
        operation_id: str,
        *,
        targets: Iterable[str | os.PathLike[str]] = (),
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        op_id = _safe_operation_id(operation_id)
        payload = {
            "schema": STATE_SCHEMA,
            "operationId": op_id,
            "database": str(self.database),
            "identity": self.identity,
            "targets": [str(canonical_database_path(item)) for item in targets],
            "ownerPid": os.getpid(),
            "createdAt": utc_now_naive().isoformat(),
            "metadata": metadata or {},
        }
        _atomic_write_json(self._intent_path, payload)
        self._audit(
            "restore_intent",
            operation_id=op_id,
            generation=None,
            extra={"targets": payload["targets"]},
        )
        return self._intent_path

    def read_intent(self) -> dict[str, Any] | None:
        try:
            return json.loads(self._intent_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def clear_intent(self, operation_id: str | None = None) -> None:
        intent = self.read_intent()
        if intent is None:
            return
        if operation_id and intent.get("operationId") != operation_id:
            raise GuardError(
                GuardErrorCode.BAD_REQUEST,
                f"恢复意图不匹配：期望 {operation_id}，实际 {intent.get('operationId')}",
            )
        try:
            self._intent_path.unlink()
        except FileNotFoundError:
            pass
        self._audit(
            "restore_intent_cleared",
            operation_id=intent.get("operationId"),
            generation=None,
        )

    def _state_error(self, status: GuardStatus, message: str | None = None) -> GuardError:
        if status.state is GuardState.UNKNOWN:
            code = GuardErrorCode.UNKNOWN
        elif status.state in {GuardState.CLOSING, GuardState.VERIFYING}:
            code = GuardErrorCode.CLOSED
        else:
            code = GuardErrorCode.RESTORING
        return GuardError(
            code,
            message or f"数据库当前不可写：{status.state.value}",
            state=status.state,
            generation=status.generation,
            operation_id=status.operation_id,
        )

    # -- 审计与回执 ---------------------------------------------------------

    def _audit(self, event: str, **fields: Any) -> None:
        record = {
            "event": event,
            "at": utc_now_naive().isoformat(),
            "database": str(self.database),
            "identity": self.identity,
            "pid": os.getpid(),
            **{key: value for key, value in fields.items() if value is not None},
        }
        try:
            self.guard_dir.mkdir(parents=True, exist_ok=True)
            with self._audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            # 审计落盘失败不能反过来放行写入；调用方仍受状态机约束。
            pass

    def write_receipt(self, receipt: dict[str, Any]) -> Path:
        operation_id = _safe_operation_id(str(receipt.get("operationId") or ""))
        payload = {
            "schema": STATE_SCHEMA,
            "database": str(self.database),
            "identity": self.identity,
            **receipt,
        }
        target = self._receipts_dir / f"{operation_id}.json"
        _atomic_write_json(target, payload)
        self._audit(
            "receipt",
            operation_id=operation_id,
            generation=payload.get("generationAfter"),
            extra=None,
            status=payload.get("status"),
        )
        return target

    def read_receipt(self, operation_id: str) -> dict[str, Any] | None:
        safe = _safe_operation_id(operation_id)
        try:
            return json.loads((self._receipts_dir / f"{safe}.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    # -- 普通写入租约 -------------------------------------------------------

    def write_lease(
        self,
        *,
        timeout: float = _DEFAULT_ADMISSION_TIMEOUT,
    ) -> "WriteLease":
        """为一次普通写事务取得代次令牌。

        租约只在事务期间持有写者槽位；恢复流程在 ``CLOSING`` 之后会等待这些
        槽位排空，因此不会出现“恢复文件换到一半仍有事务提交”的窗口。
        """
        slot: Path | None = None
        with exclusive_file_lock(
            self._admission_lock_path,
            blocking=True,
            timeout=timeout,
            reject_symlink=True,
        ):
            status = self.status()
            if status.state is not GuardState.OPEN:
                raise self._state_error(status)
            self._writers_dir.mkdir(parents=True, exist_ok=True)
            slot = self._writers_dir / f"{os.getpid()}-{uuid.uuid4().hex}.slot"
            slot.write_text(
                json.dumps({"pid": os.getpid(), "at": utc_now_naive().isoformat()}),
                encoding="utf-8",
            )
            generation = status.generation
        return WriteLease(self, generation, slot)

    def _active_writer_slots(self) -> list[Path]:
        if not self._writers_dir.is_dir():
            return []
        alive: list[Path] = []
        for slot in self._writers_dir.glob("*.slot"):
            pid = _slot_pid(slot)
            if pid and pid_alive(pid):
                alive.append(slot)
            else:
                # 只有确认进程已死才清理，避免把正在启动的写者误删。
                try:
                    slot.unlink()
                except OSError:
                    pass
        return alive

    def _drain_writers(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            if not self._active_writer_slots():
                return
            if time.monotonic() >= deadline:
                raise GuardError(
                    GuardErrorCode.WRITER_DRAIN_TIMEOUT,
                    f"等待在途写入超时（{timeout:.0f}s）",
                    state=GuardState.CLOSING,
                )
            time.sleep(0.1)

    # -- 恢复 ---------------------------------------------------------------

    def begin_restore(
        self,
        operation_id: str | None = None,
        *,
        timeout: float = _DEFAULT_RESTORE_TIMEOUT,
        writer_drain_timeout: float = _DEFAULT_WRITER_DRAIN_TIMEOUT,
        targets: Iterable[str | os.PathLike[str]] = (),
    ) -> "RestoreSession":
        """进入 ``CLOSING -> RESTORING``，返回受控恢复会话。

        ``RESTORING`` 意图在真正修改目标前落盘；会话未正常结束即释放锁时，
        下一次读取会把状态降级为 ``UNKNOWN``。
        """
        op_id = _safe_operation_id(operation_id or new_operation_id())
        intent = self.read_intent()
        if intent is not None and intent.get("operationId") != op_id:
            raise GuardError(
                GuardErrorCode.INTENT_PENDING,
                "存在其它未完成的恢复意图，拒绝启动新的恢复",
                operation_id=intent.get("operationId"),
            )
        existing = self.read_receipt(op_id)
        if existing and existing.get("status") == "succeeded":
            raise GuardError(
                GuardErrorCode.DUPLICATE_OPERATION,
                f"operationId 已成功执行过：{op_id}",
                operation_id=op_id,
            )
        admission_timeout = max(1.0, min(timeout, _DEFAULT_ADMISSION_TIMEOUT))
        lock_cm = exclusive_file_lock(
            self._restore_lock_path,
            blocking=timeout > 0,
            timeout=timeout,
            reject_symlink=True,
        )
        try:
            lock_cm.__enter__()
        except OSError as exc:
            raise GuardError(
                GuardErrorCode.LOCK_TIMEOUT,
                f"恢复锁被占用：{exc}",
            ) from exc
        except TimeoutError as exc:
            raise GuardError(
                GuardErrorCode.LOCK_TIMEOUT,
                f"等待恢复锁超时（{timeout:.0f}s）",
            ) from exc

        session = RestoreSession(
            guard=self,
            operation_id=op_id,
            generation_before=0,
            lock_cm=lock_cm,
            targets=[str(canonical_database_path(item)) for item in targets],
        )
        try:
            with exclusive_file_lock(
                self._admission_lock_path,
                blocking=True,
                timeout=admission_timeout,
                reject_symlink=True,
            ):
                record = self._effective_record()
                if record.state is not GuardState.OPEN:
                    raise self._state_error(
                        GuardStatus(
                            database=str(self.database),
                            identity=self.identity,
                            state=record.state,
                            generation=record.generation,
                            operation_id=record.operation_id,
                            owner_pid=record.owner_pid,
                            updated_at=record.updated_at,
                        )
                    )
                session.generation_before = record.generation
                record.state = GuardState.CLOSING
                record.operation_id = op_id
                record.owner_pid = os.getpid()
                record.detail = {
                    "phase": "closing",
                    "targets": session.targets,
                    "startedAt": utc_now_naive().isoformat(),
                }
                self._write_record(record)
            self._audit(
                "restore_begin",
                operation_id=op_id,
                generation=session.generation_before,
                extra={"targets": session.targets},
            )
            self._drain_writers(writer_drain_timeout)
            record = self._read_record() or self._default_record()
            record.state = GuardState.RESTORING
            record.operation_id = op_id
            record.owner_pid = os.getpid()
            record.detail = {
                **(record.detail or {}),
                "phase": "restoring",
                "targets": session.targets,
            }
            self._write_record(record)
            self.clear_intent(op_id)
            session._entered = True
            self._active_session = session
            return session
        except Exception:
            session._restore_open_state_without_modification("begin_failed")
            session._close_lock()
            raise

    def mark_unknown(
        self,
        *,
        reason: str,
        operation_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> GuardStatus:
        """把数据库标记为结果未知，必须显式核验后才能重新开放写入。"""
        record = self._effective_record()
        self._set_state(
            GuardState.UNKNOWN,
            operation_id=operation_id,
            generation=record.generation,
            detail={"unknownReason": reason, **(detail or {})},
            owner_pid=os.getpid(),
        )
        self._audit(
            "state_unknown",
            operation_id=operation_id,
            generation=record.generation,
            extra={"reason": reason},
        )
        return self.status()

    def _set_state(
        self,
        state: GuardState,
        *,
        operation_id: str | None,
        generation: int,
        detail: dict[str, Any] | None = None,
        owner_pid: int | None = None,
    ) -> None:
        record = self._read_record() or self._default_record()
        record.state = state
        record.operation_id = operation_id
        record.generation = generation
        record.owner_pid = owner_pid
        record.detail = detail or {}
        self._write_record(record)

    def reopen(
        self,
        operation_id: str,
        *,
        expected_generation: int | None = None,
        verifier: Callable[[Path], None] | None = None,
    ) -> GuardStatus:
        """核验成功后重新允许写入（代次 +1）。

        以下任一条件不满足都会保持不可写并降级 ``UNKNOWN``：
        目标身份一致、数据库完整性通过、成功回执存在且匹配、恢复锁已释放。
        """
        record = self._effective_record()
        if record.state is GuardState.UNKNOWN:
            raise GuardError(
                GuardErrorCode.UNKNOWN,
                "数据库处于 UNKNOWN，需显式解除后才能重新开放写入",
                state=record.state,
                generation=record.generation,
                operation_id=record.operation_id,
            )
        if record.state is not GuardState.VERIFYING:
            raise GuardError(
                GuardErrorCode.CLOSED,
                f"当前状态 {record.state.value} 不允许直接重新开放写入",
                state=record.state,
                generation=record.generation,
                operation_id=record.operation_id,
            )
        if record.operation_id != operation_id:
            raise GuardError(
                GuardErrorCode.DUPLICATE_OPERATION,
                f"操作不匹配：期望 {record.operation_id}，实际 {operation_id}",
                state=record.state,
                generation=record.generation,
                operation_id=operation_id,
            )
        if expected_generation is not None and record.generation != expected_generation:
            raise GuardError(
                GuardErrorCode.STALE_GENERATION,
                f"代次不匹配：期望 {expected_generation}，实际 {record.generation}",
                state=record.state,
                generation=record.generation,
                operation_id=operation_id,
            )

        try:
            self._assert_restore_lock_free()
            self._verify_reopen(operation_id, record, verifier)
        except GuardError as exc:
            self._set_state(
                GuardState.UNKNOWN,
                operation_id=operation_id,
                generation=record.generation,
                detail={
                    **(record.detail or {}),
                    "unknownReason": "reopen_verification_failed",
                    "error": exc.to_dict(),
                },
            )
            self._audit(
                "reopen_refused",
                operation_id=operation_id,
                generation=record.generation,
                extra={"code": exc.code.value, "message": exc.message},
            )
            raise

        new_generation = record.generation + 1
        self._set_state(
            GuardState.OPEN,
            operation_id=None,
            generation=new_generation,
            detail={
                "lastOperationId": operation_id,
                "reopenedAt": utc_now_naive().isoformat(),
            },
            owner_pid=None,
        )
        self._audit(
            "reopen",
            operation_id=operation_id,
            generation=new_generation,
            extra={"previousGeneration": record.generation},
        )
        return self.status()

    def _assert_restore_lock_free(self) -> None:
        if self._active_session is not None:
            raise GuardError(
                GuardErrorCode.RESTORING,
                "本进程仍有未结束的恢复会话，禁止开放写入",
                state=GuardState.RESTORING,
            )
        try:
            with exclusive_file_lock(
                self._restore_lock_path,
                blocking=False,
                reject_symlink=True,
            ):
                return
        except OSError as exc:
            raise GuardError(
                GuardErrorCode.RESTORING,
                f"恢复锁仍被持有，禁止开放写入：{exc}",
            ) from exc

    def _verify_reopen(
        self,
        operation_id: str,
        record: _StateRecord,
        verifier: Callable[[Path], None] | None,
    ) -> None:
        receipt = self.read_receipt(operation_id)
        if not receipt or receipt.get("status") not in {"succeeded", "compensated"}:
            raise GuardError(
                GuardErrorCode.VERIFY_FAILED,
                f"缺少可核验的成功回执：{operation_id}",
            )
        if _normcase(str(canonical_database_path(receipt.get("database")))) != _normcase(
            str(self.database)
        ):
            raise GuardError(
                GuardErrorCode.VERIFY_FAILED,
                "回执目标与当前数据库不一致",
            )
        raw_targets = record.detail.get("targets") or receipt.get("targets") or []
        targets = [
            str(item.get("path")) if isinstance(item, dict) else str(item)
            for item in raw_targets
        ]
        expected_hashes = {
            str(item.get("path")): item.get("sha256")
            for item in receipt.get("targets", [])
            if isinstance(item, dict)
        }
        if not targets or not self.database.exists():
            raise GuardError(GuardErrorCode.VERIFY_FAILED, "目标数据库不存在，无法开放写入")
        registered = {_normcase(str(canonical_database_path(item))) for item in targets}
        if _normcase(str(self.database)) not in registered:
            raise GuardError(
                GuardErrorCode.VERIFY_FAILED,
                "回执未登记当前数据库目标",
            )
        expected = expected_hashes.get(str(self.database))
        if expected and file_sha256(self.database) != expected:
            raise GuardError(
                GuardErrorCode.VERIFY_FAILED,
                "数据库文件哈希与恢复回执不一致",
            )
        assert_integrity(self.database)
        if verifier is not None:
            verifier(self.database)

    def resolve_unknown(
        self,
        operation_id: str,
        *,
        decision: str,
        evidence: str,
        compensation: Callable[[], dict[str, Any]] | None = None,
        verifier: Callable[[Path], None] | None = None,
    ) -> GuardStatus:
        """显式解除 ``UNKNOWN``。不存在自动清除路径。

        ``decision``:
        * ``accept_restored``：接受磁盘上的恢复结果，要求成功回执与完整性核验；
        * ``abandon_restore``：调用补偿把安全备份写回，再按补偿回执核验。

        ``evidence`` 必须说明是谁、基于什么证据做出的决定，写入审计。
        """
        if decision not in {"accept_restored", "abandon_restore"}:
            raise GuardError(GuardErrorCode.BAD_REQUEST, f"未知的解除决定：{decision}")
        if not evidence.strip():
            raise GuardError(GuardErrorCode.BAD_REQUEST, "解除 UNKNOWN 必须提供证据说明")
        record = self._effective_record()
        if record.state is not GuardState.UNKNOWN:
            raise GuardError(
                GuardErrorCode.BAD_REQUEST,
                f"当前状态 {record.state.value} 不是 UNKNOWN",
                state=record.state,
                generation=record.generation,
            )
        self._audit(
            "unknown_resolve",
            operation_id=operation_id,
            generation=record.generation,
            extra={"decision": decision, "evidence": evidence.strip()[:500]},
        )
        try:
            with exclusive_file_lock(
                self._restore_lock_path,
                blocking=False,
                reject_symlink=True,
            ):
                if decision == "abandon_restore":
                    if compensation is None:
                        raise GuardError(
                            GuardErrorCode.BAD_REQUEST,
                            "abandon_restore 需要补偿回调",
                        )
                    result = compensation()
                    if result.get("status") != "compensated":
                        raise GuardError(
                            GuardErrorCode.VERIFY_FAILED,
                            f"补偿未成功：{result.get('message') or result}",
                        )
                receipt = self.read_receipt(operation_id)
                if receipt is None:
                    raise GuardError(
                        GuardErrorCode.VERIFY_FAILED,
                        f"找不到操作回执：{operation_id}",
                    )
                assert_integrity(self.database)
                if verifier is not None:
                    verifier(self.database)
                new_generation = record.generation + 1
                self._set_state(
                    GuardState.OPEN,
                    operation_id=None,
                    generation=new_generation,
                    detail={
                        "lastOperationId": operation_id,
                        "unknownResolution": decision,
                        "resolvedAt": utc_now_naive().isoformat(),
                    },
                    owner_pid=None,
                )
                self._audit(
                    "unknown_resolved",
                    operation_id=operation_id,
                    generation=new_generation,
                    extra={"decision": decision},
                )
                return self.status()
        except Exception:
            raise

    # -- 供恢复会话使用 -----------------------------------------------------


class WriteLease:
    """普通写事务令牌；释放后恢复流程即可继续。"""

    def __init__(self, guard: DatabaseGuard, generation: int, slot: Path) -> None:
        self.guard = guard
        self.generation = generation
        self._slot = slot
        self._released = False

    def still_valid(self) -> bool:
        status = self.guard.status()
        return status.state is GuardState.OPEN and status.generation == self.generation

    def assert_valid(self) -> None:
        status = self.guard.status()
        if status.state is not GuardState.OPEN:
            raise self.guard._state_error(status)
        if status.generation != self.generation:
            raise GuardError(
                GuardErrorCode.STALE_GENERATION,
                f"写租约代次已失效：{self.generation} -> {status.generation}",
                state=status.state,
                generation=status.generation,
            )

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            self._slot.unlink()
        except OSError:
            pass

    def __enter__(self) -> "WriteLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class RestoreSession:
    """受控恢复会话：``commit`` 只表示“已写入并留下回执”，不表示可写。"""

    def __init__(
        self,
        guard: DatabaseGuard,
        operation_id: str,
        generation_before: int,
        lock_cm: Any,
        targets: list[str],
    ) -> None:
        self.guard = guard
        self.operation_id = operation_id
        self.generation_before = generation_before
        self.targets = targets
        self.modified: list[dict[str, Any]] = []
        self._lock_cm = lock_cm
        self._entered = False
        self._closed = False

    # -- 生命周期 -----------------------------------------------------------

    def mark_modified(self, path: str | os.PathLike[str], *, sha256: str | None = None) -> None:
        resolved = str(canonical_database_path(path))
        if resolved not in self.targets:
            raise GuardError(
                GuardErrorCode.PARTIAL_RESTORE,
                f"未登记的目标禁止修改：{resolved}",
            )
        entry = {"path": resolved, "sha256": sha256 or ""}
        self.modified.append(entry)

    def commit(self, *, details: dict[str, Any] | None = None) -> Path:
        """写入成功回执并进入 ``VERIFYING``，等待 ``reopen``。"""
        if not self._entered:
            raise GuardError(GuardErrorCode.BAD_REQUEST, "恢复会话未成功启动")
        targets = details.get("targets") if details else None
        receipt = {
            "operationId": self.operation_id,
            "status": "succeeded",
            "database": str(self.guard.database),
            "generationBefore": self.generation_before,
            "generationAfter": self.generation_before,
            "startedAt": utc_now_naive().isoformat(),
            "finishedAt": utc_now_naive().isoformat(),
            "targets": targets or self.modified,
        }
        if details:
            receipt.update({k: v for k, v in details.items() if k not in {"targets"}})
        receipt_path = self.guard.write_receipt(receipt)
        self.guard._set_state(
            GuardState.VERIFYING,
            operation_id=self.operation_id,
            generation=self.generation_before,
            detail={
                "phase": "verifying",
                "targets": [item["path"] for item in self.modified],
                "receipt": str(receipt_path),
            },
            owner_pid=os.getpid(),
        )
        self._close_lock()
        self.guard._audit(
            "restore_commit",
            operation_id=self.operation_id,
            generation=self.generation_before,
            extra={"targets": [item["path"] for item in self.modified]},
        )
        self._closed = True
        return receipt_path

    def abort(self, reason: str) -> None:
        """尚未修改任何目标：回到 OPEN，代次不变。"""
        if self.modified:
            raise GuardError(
                GuardErrorCode.PARTIAL_RESTORE,
                "已修改目标，不能直接 abort；必须补偿或标记 UNKNOWN",
            )
        self._restore_open_state_without_modification(reason)
        self._close_lock()

    def fail_compensated(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> Path:
        """目标已修改并完成补偿：进入 ``VERIFYING``，仍需 reopen 核验。"""
        receipt = {
            "operationId": self.operation_id,
            "status": "compensated",
            "database": str(self.guard.database),
            "generationBefore": self.generation_before,
            "generationAfter": self.generation_before,
            "finishedAt": utc_now_naive().isoformat(),
            "targets": self.modified,
            "error": {"code": code, "message": message},
        }
        if details:
            receipt.update(details)
        receipt_path = self.guard.write_receipt(receipt)
        self.guard._set_state(
            GuardState.VERIFYING,
            operation_id=self.operation_id,
            generation=self.generation_before,
            detail={
                "phase": "verifying",
                "receipt": str(receipt_path),
                "compensated": True,
                "targets": [item["path"] for item in self.modified],
            },
            owner_pid=os.getpid(),
        )
        self._close_lock()
        self._closed = True
        return receipt_path

    def fail_unknown(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> Path:
        """已修改且补偿失败/结果不明：必须保留 ``UNKNOWN``。"""
        receipt = {
            "operationId": self.operation_id,
            "status": "compensate_failed" if self.modified else "unknown",
            "database": str(self.guard.database),
            "generationBefore": self.generation_before,
            "generationAfter": self.generation_before,
            "finishedAt": utc_now_naive().isoformat(),
            "targets": self.modified,
            "error": {"code": code, "message": message},
        }
        if details:
            receipt.update(details)
        receipt_path = self.guard.write_receipt(receipt)
        self.guard._set_state(
            GuardState.UNKNOWN,
            operation_id=self.operation_id,
            generation=self.generation_before,
            detail={
                "phase": "unknown",
                "receipt": str(receipt_path),
                "reason": code,
            },
            owner_pid=os.getpid(),
        )
        self._close_lock()
        self._audit_unknown(code, message)
        self._closed = True
        return receipt_path

    def _audit_unknown(self, code: str, message: str) -> None:
        self.guard._audit(
            "restore_unknown",
            operation_id=self.operation_id,
            generation=self.generation_before,
            extra={"code": code, "message": message[:300]},
        )

    # -- 内部 ---------------------------------------------------------------

    def _restore_open_state_without_modification(self, reason: str) -> None:
        record = self.guard._read_record() or self.guard._default_record()
        if record.operation_id != self.operation_id:
            return
        record.state = GuardState.OPEN
        record.operation_id = None
        record.owner_pid = None
        record.generation = self.generation_before
        record.detail = {"abortedReason": reason, "abortedAt": utc_now_naive().isoformat()}
        self.guard._write_record(record)
        self.guard._audit(
            "restore_aborted",
            operation_id=self.operation_id,
            generation=self.generation_before,
            extra={"reason": reason},
        )

    def _close_lock(self) -> None:
        if self.guard._active_session is self:
            self.guard._active_session = None
        if self._lock_cm is None:
            return
        try:
            self._lock_cm.__exit__(None, None, None)
        except (RuntimeError, OSError):
            pass
        self._lock_cm = None

    def __enter__(self) -> "RestoreSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None and not self._closed:
            # 调用方没有显式收尾：结果不可信，保留 UNKNOWN。
            try:
                self.fail_unknown(
                    code=GuardErrorCode.PARTIAL_RESTORE.value,
                    message=f"恢复会话异常退出：{exc_type.__name__}: {exc}",
                )
            except Exception:
                pass
        if not self._closed:
            self._close_lock()


# ---------------------------------------------------------------------------
# 文件校验工具（恢复引擎共同使用）
# ---------------------------------------------------------------------------


def file_sha256(path: str | os.PathLike[str], *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def assert_integrity(path: str | os.PathLike[str], *, quick: bool = True) -> None:
    """对 SQLite 库做完整性检查，失败即拒绝后续动作。"""
    db_path = canonical_database_path(path)
    if not db_path.is_file():
        raise GuardError(GuardErrorCode.VERIFY_FAILED, f"数据库不存在：{db_path}")
    if db_path.stat().st_size <= 0:
        raise GuardError(GuardErrorCode.VERIFY_FAILED, f"数据库为空：{db_path}")
    pragma = "PRAGMA quick_check" if quick else "PRAGMA integrity_check"
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = conn.execute(pragma).fetchone()
    except sqlite3.Error as exc:
        raise GuardError(
            GuardErrorCode.VERIFY_FAILED,
            f"数据库完整性检查无法执行：{exc}",
        ) from exc
    finally:
        if conn is not None:
            conn.close()
    if not row or row[0] != "ok":
        raise GuardError(
            GuardErrorCode.VERIFY_FAILED,
            f"数据库完整性检查失败：{row[0] if row else 'no result'}",
        )


def _slot_pid(slot: Path) -> int | None:
    try:
        payload = json.loads(slot.read_text(encoding="utf-8"))
        return int(payload.get("pid") or 0) or None
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return None
