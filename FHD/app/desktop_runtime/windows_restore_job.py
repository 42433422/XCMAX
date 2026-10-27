"""Windows 受控恢复守护：Job Object + 进程树确认 + 回执核验。

对应需求第 18—21、23 条：

- 子进程先受控（挂起创建 → 加入 Job）再运行，禁止脱离进程组；
- 退出时确认整棵进程树停止；
- 启动前持久化“进行中”记录；守护进程异常退出后保留“结果未知”；
- 只有核实完整成功回执才允许结束恢复状态；
- UNKNOWN 只能显式检查与解除，不得自动清除或盲目重试；
- 应用重启由调用方在恢复进程结束、锁释放之后执行。

非 Windows 平台直接拒绝执行——模拟不能替代实机验证。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .database_generation_registry import (
    assert_integrity,
    canonical_database_path,
    file_sha256,
    new_operation_id,
)

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_INFINITE = 0xFFFFFFFF


class RestoreJobError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


@dataclass
class RestoreJobResult:
    status: str
    operation_id: str
    exit_code: int | None = None
    receipt_path: str | None = None
    record_path: str | None = None
    message: str = ""
    targets: list[dict[str, str]] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "operationId": self.operation_id,
            "exitCode": self.exit_code,
            "receiptPath": self.receipt_path,
            "recordPath": self.record_path,
            "message": self.message,
            "targets": self.targets,
        }


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_operation_record(
    record_path: str | os.PathLike[str],
    *,
    operation_id: str,
    status: str,
    reason: str,
    targets: list[dict[str, str]],
    receipt_path: str,
    message: str = "",
    exit_code: int | None = None,
) -> None:
    """持久化恢复操作记录（in_progress / succeeded / result_unknown）。"""

    path = Path(record_path).resolve()
    existing = _read_json(path) or {}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload: dict[str, object] = {
        "operationId": operation_id,
        "status": status,
        "startedAt": existing.get("startedAt") or now,
        "updatedAt": now,
        "reason": reason,
        "targets": targets,
        "receiptPath": receipt_path,
    }
    if message:
        payload["message"] = message
    if exit_code is not None:
        payload["restoreExitCode"] = exit_code
    _atomic_write_json(path, payload)


def read_operation_record(record_path: str | os.PathLike[str]) -> dict[str, object] | None:
    return _read_json(Path(record_path).resolve())


def verify_restore_receipt(
    receipt_path: str | os.PathLike[str],
    operation_id: str,
    targets: list[dict[str, str]],
    *,
    integrity_check: bool = True,
) -> None:
    """核验回执：operationId、状态、目标登记、sha256 与完整性。

    退出码 0 与“进程消失”都不等于恢复成功。
    """

    path = Path(receipt_path).resolve()
    receipt = _read_json(path)
    if receipt is None:
        raise RestoreJobError("DB_GUARD_UNKNOWN", f"恢复回执缺失或不可解析：{path}")
    if str(receipt.get("operationId") or "") != operation_id:
        raise RestoreJobError("DB_GUARD_UNKNOWN", "恢复回执 operationId 不匹配")
    if str(receipt.get("status") or "") != "succeeded":
        raise RestoreJobError(
            "DB_GUARD_UNKNOWN", f"恢复回执状态不是 succeeded：{receipt.get('status')}"
        )

    recorded: dict[str, str] = {}
    for item in receipt.get("targets") or []:
        if isinstance(item, dict) and item.get("path"):
            recorded[str(Path(str(item["path"])).resolve())] = str(item.get("sha256") or "")
    for target in targets:
        resolved = str(Path(str(target["databasePath"])).resolve())
        expected = recorded.get(resolved)
        if not expected:
            raise RestoreJobError("DB_GUARD_UNKNOWN", f"恢复回执未登记目标：{resolved}")
        database = Path(resolved)
        if not database.is_file():
            raise RestoreJobError("DB_GUARD_UNKNOWN", f"恢复后目标不存在：{resolved}")
        if file_sha256(database) != expected:
            raise RestoreJobError("DB_GUARD_UNKNOWN", f"恢复后目标哈希与回执不一致：{resolved}")
        if integrity_check:
            assert_integrity(database, quick=True)


if sys.platform == "win32":  # pragma: no cover - 仅 Windows 实机执行
    from ctypes import wintypes

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.CreateProcessW.restype = wintypes.BOOL
    _kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class WindowsJob:
    """Job Object 封装：创建即挂起、加入 Job 后才恢复运行。"""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RestoreJobError(
                "DB_GUARD_PLATFORM_UNSUPPORTED",
                "Windows Job Object 只能在 Windows 上使用；Linux 测试不能替代实机验证",
            )
        self._job = _kernel32.CreateJobObjectW(None, None)
        if not self._job:
            raise RestoreJobError(
                "DB_GUARD_JOB_FAILED", f"CreateJobObject 失败：{ctypes.get_last_error()}"
            )
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _kernel32.SetInformationJobObject(
            self._job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            self.close()
            raise RestoreJobError(
                "DB_GUARD_JOB_FAILED",
                f"SetInformationJobObject 失败：{ctypes.get_last_error()}",
            )
        self._process: int | None = None
        self._thread: int | None = None
        self.pid: int | None = None

    def start(self, argv: list[str], cwd: str) -> None:
        """挂起创建子进程 → 加入 Job → 恢复运行。"""

        command_line = subprocess.list2cmdline(argv)
        startup = _STARTUPINFOW()
        startup.cb = ctypes.sizeof(_STARTUPINFOW)
        process_info = _PROCESS_INFORMATION()
        created = _kernel32.CreateProcessW(
            None,
            ctypes.cast(ctypes.c_wchar_p(command_line), wintypes.LPWSTR),
            None,
            None,
            False,
            _CREATE_SUSPENDED | _CREATE_NO_WINDOW,
            None,
            cwd,
            ctypes.byref(startup),
            ctypes.byref(process_info),
        )
        if not created:
            raise RestoreJobError(
                "DB_GUARD_JOB_FAILED", f"CreateProcess 失败：{ctypes.get_last_error()}"
            )
        self._process = process_info.hProcess
        self._thread = process_info.hThread
        self.pid = int(process_info.dwProcessId)
        if not _kernel32.AssignProcessToJobObject(self._job, self._process):
            self.terminate()
            raise RestoreJobError(
                "DB_GUARD_JOB_FAILED",
                f"AssignProcessToJobObject 失败：{ctypes.get_last_error()}",
            )
        if _kernel32.ResumeThread(self._thread) == 0xFFFFFFFF:
            self.terminate()
            raise RestoreJobError(
                "DB_GUARD_JOB_FAILED", f"ResumeThread 失败：{ctypes.get_last_error()}"
            )

    def wait(self, timeout: float) -> bool:
        """等待进程结束；返回 False 表示超时。"""

        assert self._process is not None
        millis = _INFINITE if timeout <= 0 else int(timeout * 1000)
        result = _kernel32.WaitForSingleObject(self._process, millis)
        if result == _WAIT_TIMEOUT:
            return False
        if result != _WAIT_OBJECT_0:
            raise RestoreJobError(
                "DB_GUARD_JOB_FAILED", f"WaitForSingleObject 失败：{result}"
            )
        return True

    def exit_code(self) -> int:
        assert self._process is not None
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(self._process, ctypes.byref(code)):
            raise RestoreJobError(
                "DB_GUARD_JOB_FAILED", f"GetExitCodeProcess 失败：{ctypes.get_last_error()}"
            )
        return int(code.value)

    def active_processes(self) -> int:
        info = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        if not _kernel32.QueryInformationJobObject(
            self._job,
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            raise RestoreJobError(
                "DB_GUARD_JOB_FAILED",
                f"QueryInformationJobObject 失败：{ctypes.get_last_error()}",
            )
        return int(info.ActiveProcesses)

    def wait_tree_stopped(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.active_processes() == 0:
                return True
            time.sleep(0.2)
        return False

    def terminate(self) -> None:
        if self._job:
            _kernel32.TerminateJobObject(self._job, 1)

    def close(self) -> None:
        for handle in (self._thread, self._process):
            if handle:
                _kernel32.CloseHandle(handle)
        self._thread = None
        self._process = None
        if self._job:
            _kernel32.CloseHandle(self._job)
            self._job = None


def run_guarded_restore(
    *,
    helper_argv: list[str],
    operation_id: str,
    record_path: str | os.PathLike[str],
    receipt_path: str | os.PathLike[str],
    targets: list[dict[str, str]],
    reason: str,
    cwd: str | os.PathLike[str],
    timeout: float = 600.0,
    tree_stop_timeout: float = 15.0,
) -> RestoreJobResult:
    """在 Job Object 内执行恢复，并按回执判定结果。"""

    resolved_targets = [
        {
            "databasePath": str(canonical_database_path(item["databasePath"])),
            "databaseBackupPath": str(Path(item["databaseBackupPath"]).resolve()),
        }
        for item in targets
    ]
    write_operation_record(
        record_path,
        operation_id=operation_id,
        status="in_progress",
        reason=reason,
        targets=resolved_targets,
        receipt_path=str(receipt_path),
    )

    job = WindowsJob()
    try:
        job.start(helper_argv, str(Path(cwd).resolve()))
        finished = job.wait(timeout)
        if not finished:
            job.terminate()
            job.wait_tree_stopped(tree_stop_timeout)
            message = "受控恢复程序超时被终止，结果未知"
            write_operation_record(
                record_path,
                operation_id=operation_id,
                status="result_unknown",
                reason=reason,
                targets=resolved_targets,
                receipt_path=str(receipt_path),
                message=message,
            )
            return RestoreJobResult(
                status="unknown",
                operation_id=operation_id,
                receipt_path=str(receipt_path),
                record_path=str(record_path),
                message=message,
                targets=resolved_targets,
            )

        exit_code = job.exit_code()
        tree_stopped = job.wait_tree_stopped(tree_stop_timeout)
        if not tree_stopped:
            message = "恢复进程已退出但进程树未完全停止，结果未知"
            write_operation_record(
                record_path,
                operation_id=operation_id,
                status="result_unknown",
                reason=reason,
                targets=resolved_targets,
                receipt_path=str(receipt_path),
                message=message,
                exit_code=exit_code,
            )
            return RestoreJobResult(
                status="unknown",
                operation_id=operation_id,
                exit_code=exit_code,
                receipt_path=str(receipt_path),
                record_path=str(record_path),
                message=message,
                targets=resolved_targets,
            )

        if exit_code != 0:
            message = f"受控恢复程序退出码 {exit_code}"
            write_operation_record(
                record_path,
                operation_id=operation_id,
                status="result_unknown",
                reason=reason,
                targets=resolved_targets,
                receipt_path=str(receipt_path),
                message=message,
                exit_code=exit_code,
            )
            return RestoreJobResult(
                status="unknown",
                operation_id=operation_id,
                exit_code=exit_code,
                receipt_path=str(receipt_path),
                record_path=str(record_path),
                message=message,
                targets=resolved_targets,
            )

        try:
            verify_restore_receipt(receipt_path, operation_id, resolved_targets)
        except RestoreJobError as exc:
            write_operation_record(
                record_path,
                operation_id=operation_id,
                status="result_unknown",
                reason=reason,
                targets=resolved_targets,
                receipt_path=str(receipt_path),
                message=str(exc),
                exit_code=exit_code,
            )
            return RestoreJobResult(
                status="unknown",
                operation_id=operation_id,
                exit_code=exit_code,
                receipt_path=str(receipt_path),
                record_path=str(record_path),
                message=str(exc),
                targets=resolved_targets,
            )

        write_operation_record(
            record_path,
            operation_id=operation_id,
            status="succeeded",
            reason=reason,
            targets=resolved_targets,
            receipt_path=str(receipt_path),
            exit_code=0,
        )
        return RestoreJobResult(
            status="succeeded",
            operation_id=operation_id,
            exit_code=0,
            receipt_path=str(receipt_path),
            record_path=str(record_path),
            targets=resolved_targets,
        )
    finally:
        job.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows 受控恢复守护")
    parser.add_argument("--mode", choices=["run", "status", "verify"], default="run")
    parser.add_argument("--operation-id", default="")
    parser.add_argument("--record", required=True)
    parser.add_argument("--receipt", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--backup", action="append", default=[])
    parser.add_argument("--helper", default="")
    parser.add_argument("--helper-arg", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.mode == "status":
        record = read_operation_record(args.record)
        print(json.dumps(record, ensure_ascii=False) if args.json else record)
        return 0 if record else 1

    targets = [
        {"databasePath": target, "databaseBackupPath": backup}
        for target, backup in zip(args.target, args.backup, strict=False)
    ]
    if args.mode == "verify":
        try:
            verify_restore_receipt(args.receipt, args.operation_id, targets)
        except RestoreJobError as exc:
            print(json.dumps({"status": "unknown", **exc.to_dict()}, ensure_ascii=False))
            return 3
        print(json.dumps({"status": "succeeded", "operationId": args.operation_id}))
        return 0

    if not args.helper:
        parser.error("--helper 必填")
    operation_id = args.operation_id or new_operation_id("windows-restore")
    result = run_guarded_restore(
        helper_argv=[args.helper, *args.helper_arg],
        operation_id=operation_id,
        record_path=args.record,
        receipt_path=args.receipt,
        targets=targets,
        reason=args.reason,
        cwd=Path(args.record).resolve().parent,
        timeout=args.timeout,
    )
    payload = result.to_dict()
    print(json.dumps(payload, ensure_ascii=False) if args.json else payload)
    return {"succeeded": 0, "unknown": 3, "refused": 2}.get(result.status, 1)


if __name__ == "__main__":
    raise SystemExit(main())
