"""受保护的 SQLite 恢复引擎与独立命令行入口。

所有恢复入口（DatabaseService、损坏库启动恢复、维护 CLI、Windows 守护、
PowerShell 包装）都必须经由本模块，不允许再直接 ``copy`` 主库后删除 WAL。

命令示例::

    python -m app.desktop_runtime.restore_helper \\
        --mode restore --operation-id restore-... \\
        --data-dir "%APPDATA%\\XCAGI" \\
        --allowed-root "%APPDATA%\\XCAGI" \\
        --target "%APPDATA%\\XCAGI\\data\\xcagi.db" \\
        --backup "%APPDATA%\\XCAGI\\backups\\xcagi-1.0.0.5-....db"

退出码：0 成功；1 失败但已补偿；2 拒绝执行（未修改）；3 结果未知。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from app.desktop_runtime.database_generation_registry import (
    DatabaseGuard,
    GuardError,
    GuardErrorCode,
    assert_integrity,
    assert_no_alias,
    assert_within,
    canonical_database_path,
    file_sha256,
    new_operation_id,
)


@dataclass(frozen=True)
class RestoreTarget:
    database: Path
    backup: Path
    allowed_root: Path


@dataclass
class TargetResult:
    database: str
    backup: str
    status: str
    sha256: str = ""
    safety_backup: str = ""
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.database,
            "backup": self.backup,
            "status": self.status,
            "sha256": self.sha256,
            "safetyBackup": self.safety_backup,
            "error": self.error,
        }


@dataclass
class RestoreReport:
    operation_id: str
    status: str
    targets: list[TargetResult] = field(default_factory=list)
    receipt_path: str = ""
    error: dict[str, str] | None = None
    started_at: str = ""
    finished_at: str = ""

    @property
    def exit_code(self) -> int:
        if self.status == "succeeded":
            return 0
        if self.status in {"failed_compensated"}:
            return 1
        if self.status in {"refused", "duplicate"}:
            return 2
        return 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "operationId": self.operation_id,
            "status": self.status,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "receiptPath": self.receipt_path,
            "targets": [item.to_dict() for item in self.targets],
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# SQLite 一致性复制
# ---------------------------------------------------------------------------


def sqlite_clone(source: Path, destination: Path) -> None:
    """用 SQLite 在线备份 API 复制（自动包含 WAL 中的已提交数据）。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    src_conn = None
    dst_conn = None
    try:
        src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        dst_conn = sqlite3.connect(str(destination))
        src_conn.backup(dst_conn)
    finally:
        if dst_conn is not None:
            dst_conn.close()
        if src_conn is not None:
            src_conn.close()
    with open(destination, "rb") as handle:
        os.fsync(handle.fileno())


def _quarantine_sidecars(target: Path, stamp: str) -> list[str]:
    """把旧的 -wal/-shm/-journal 移出而不是删除，保留失败证据。"""
    moved: list[str] = []
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = target.with_name(target.name + suffix)
        if not sidecar.exists():
            continue
        quarantine = target.with_name(f"{target.name}.pre-restore-{stamp}{suffix}")
        os.replace(sidecar, quarantine)
        moved.append(str(quarantine))
    return moved


def replace_from_backup(
    target: Path,
    backup: Path,
    *,
    stamp: str,
) -> str:
    """把 ``backup`` 写回 ``target``：先写同目录临时库并校验，再原子替换。"""
    temp = target.with_name(f".{target.name}.restore-{uuid.uuid4().hex}.tmp")
    try:
        sqlite_clone(backup, temp)
        assert_integrity(temp, quick=False)
        os.replace(temp, target)
        _quarantine_sidecars(target, stamp)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass
    assert_integrity(target, quick=False)
    return file_sha256(target)


def _safe_safety_backup(source: Path, destination: Path) -> None:
    sqlite_clone(source, destination)
    assert_integrity(destination, quick=False)


# ---------------------------------------------------------------------------
# 恢复编排
# ---------------------------------------------------------------------------


def _validate_targets(targets: Iterable[RestoreTarget]) -> list[RestoreTarget]:
    normalized: list[RestoreTarget] = []
    seen: set[str] = set()
    for item in targets:
        database = assert_within(item.allowed_root, item.database)
        backup = canonical_database_path(item.backup)
        if not backup.is_file() or backup.is_symlink():
            raise GuardError(
                GuardErrorCode.BAD_REQUEST,
                f"备份文件不存在或为软链接：{backup}",
            )
        assert_no_alias(backup, database)
        assert_integrity(backup)
        key = str(database)
        if key in seen:
            raise GuardError(GuardErrorCode.BAD_REQUEST, f"重复目标：{database}")
        seen.add(key)
        normalized.append(RestoreTarget(database, backup, canonical_database_path(item.allowed_root)))
    if not normalized:
        raise GuardError(GuardErrorCode.BAD_REQUEST, "没有登记任何恢复目标")
    return sorted(normalized, key=lambda item: str(item.database))


def guarded_restore(
    targets: Iterable[RestoreTarget],
    *,
    operation_id: str | None = None,
    safety_root: Path,
    before_replace: Callable[[], None] | None = None,
    verifier: Callable[[Path], None] | None = None,
) -> RestoreReport:
    """按固定顺序持锁、全部准备成功后再修改，失败必须补偿或保留 UNKNOWN。"""
    op_id = new_operation_id() if operation_id is None else operation_id
    report = RestoreReport(
        operation_id=op_id,
        status="refused",
        started_at=_now(),
    )
    ordered: list[RestoreTarget] = []
    sessions: list[tuple[RestoreTarget, Any, DatabaseGuard]] = []
    modified: list[tuple[RestoreTarget, Any, DatabaseGuard]] = []
    safety: dict[str, Path] = {}
    stamp = op_id.replace(":", "-")
    try:
        ordered = _validate_targets(targets)
    except GuardError as exc:
        report.error = exc.to_dict()
        report.finished_at = _now()
        return report

    report.targets = [
        TargetResult(database=str(item.database), backup=str(item.backup), status="pending")
        for item in ordered
    ]
    by_path = {item.database: result for item, result in zip(ordered, report.targets)}

    try:
        for item in ordered:
            guard = DatabaseGuard(item.database)
            session = guard.begin_restore(op_id, targets=[item.database])
            sessions.append((item, session, guard))

        operation_dir = safety_root / op_id.replace("/", "_").replace("\\", "_")
        operation_dir.mkdir(parents=True, exist_ok=True)
        for item in ordered:
            destination = operation_dir / f"{item.database.name}.pre-restore.db"
            if item.database.exists():
                _safe_safety_backup(item.database, destination)
                by_path[item.database].safety_backup = str(destination)
            safety[str(item.database)] = destination

        if before_replace is not None:
            before_replace()

        for item in ordered:
            session = next(s for t, s, _ in sessions if t.database == item.database)
            guard = next(g for t, _, g in sessions if t.database == item.database)
            # 先登记再替换：即使替换中途失败，也按“可能已修改”走补偿。
            session.mark_modified(item.database)
            modified.append((item, session, guard))
            sha = replace_from_backup(item.database, item.backup, stamp=stamp)
            for entry in session.modified:
                if entry["path"] == str(item.database):
                    entry["sha256"] = sha
            by_path[item.database].sha256 = sha
            by_path[item.database].status = "restored"
            if verifier is not None:
                verifier(item.database)

        for item, session, _ in modified:
            result = by_path[item.database]
            session.commit(
                details={
                    "targets": [
                        {
                            "path": str(item.database),
                            "sha256": result.sha256,
                        }
                    ],
                    "backup": str(item.backup),
                    "safetyBackup": result.safety_backup,
                }
            )
            result.status = "verified"

        reopened = True
        for item, _, guard in modified:
            try:
                guard.reopen(op_id, verifier=verifier)
            except GuardError as exc:
                reopened = False
                by_path[item.database].status = "unknown"
                by_path[item.database].error = exc.to_dict()
        if not reopened:
            report.status = "unknown"
            report.error = {
                "code": GuardErrorCode.VERIFY_FAILED.value,
                "message": "恢复回执已生成，但重新开放写入核验失败，保持 UNKNOWN",
            }
            report.finished_at = _now()
            report.receipt_path = _write_aggregate_receipt(report)
            return report

        report.status = "succeeded"
        report.finished_at = _now()
        report.receipt_path = _write_aggregate_receipt(report)
        return report

    except GuardError as exc:
        report.error = exc.to_dict()
    except OSError as exc:
        report.error = {"code": GuardErrorCode.BAD_REQUEST.value, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - 恢复边界必须落成回执
        report.error = {"code": GuardErrorCode.PARTIAL_RESTORE.value, "message": str(exc)}

    # 失败路径：未修改的目标释放回 OPEN；已修改的用安全备份补偿。
    all_compensated = True
    for item, session, _ in modified:
        try:
            compensated_sha = replace_from_backup(
                item.database,
                safety[str(item.database)],
                stamp=f"{stamp}-comp",
            )
            for entry in session.modified:
                if entry["path"] == str(item.database):
                    entry["sha256"] = compensated_sha
            session.fail_compensated(
                code=(report.error or {}).get("code", GuardErrorCode.PARTIAL_RESTORE.value),
                message=(report.error or {}).get("message", "restore failed"),
                details={
                    "targets": [
                        {"path": str(item.database), "sha256": compensated_sha}
                    ],
                    "safetyBackup": str(safety[str(item.database)]),
                },
            )
            guard = next(g for t, _, g in modified if t.database == item.database)
            try:
                guard.reopen(op_id, verifier=verifier)
                by_path[item.database].status = "compensated"
                by_path[item.database].sha256 = compensated_sha
            except GuardError as reopen_exc:
                all_compensated = False
                by_path[item.database].status = "unknown"
                by_path[item.database].error = reopen_exc.to_dict()
        except Exception as comp_exc:  # noqa: BLE001 - 补偿失败必须保持 UNKNOWN
            all_compensated = False
            try:
                session.fail_unknown(
                    code=GuardErrorCode.PARTIAL_RESTORE.value,
                    message=f"补偿失败：{comp_exc}",
                )
            except Exception:
                pass
            by_path[item.database].status = "compensate_failed"
            by_path[item.database].error = {"code": "COMPENSATION_FAILED", "message": str(comp_exc)}

    for item, session, _ in sessions:
        if any(item.database == mod.database for mod, _, _ in modified):
            continue
        try:
            session.abort("restore_failed_before_modification")
        except Exception:
            pass
        by_path[item.database].status = "not_modified"

    if not modified:
        report.status = "refused"
    elif all_compensated:
        report.status = "failed_compensated"
    else:
        report.status = "compensate_failed"
    report.finished_at = _now()
    report.receipt_path = _write_aggregate_receipt(report)
    return report


def _write_aggregate_receipt(report: RestoreReport) -> str:
    """在恢复目标所在数据根的日志目录写一份总回执。"""
    roots = {Path(item.database).parent.parent for item in report.targets if item.database}
    if not roots:
        return ""
    root = sorted(roots)[0]
    receipt_dir = root / "logs" / "restore-receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / f"{report.operation_id.replace(':', '-')}.json"
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temp, path)
    return str(path)


def _now() -> str:
    from app.utils.time import utc_now_naive

    return utc_now_naive().isoformat()


# ---------------------------------------------------------------------------
# 解除 UNKNOWN / 启动门禁
# ---------------------------------------------------------------------------


def resolve_unknown(
    database: Path,
    *,
    operation_id: str,
    decision: str,
    evidence: str,
    safety_root: Path,
) -> dict[str, Any]:
    """显式解除 UNKNOWN；补偿只使用操作登记过的安全备份。"""
    guard = DatabaseGuard(database)
    intent = guard.read_intent()

    def _compensate() -> dict[str, Any]:
        receipt = guard.read_receipt(operation_id) or {}
        safety = Path(str(receipt.get("safetyBackup") or ""))
        if not safety.is_file():
            operation_dir = safety_root / operation_id.replace("/", "_").replace("\\", "_")
            candidate = operation_dir / f"{Path(database).name}.pre-restore.db"
            safety = candidate if candidate.is_file() else Path("")
        if not safety.is_file():
            return {"status": "failed", "message": "找不到安全备份，禁止盲目重试"}
        if intent is not None:
            guard.clear_intent(operation_id)
        replace_from_backup(Path(database), safety, stamp=f"{operation_id}-resolve")
        return {"status": "compensated", "source": str(safety)}

    status = guard.resolve_unknown(
        operation_id,
        decision=decision,
        evidence=evidence,
        compensation=_compensate if decision == "abandon_restore" else None,
    )
    return status.to_dict()


def startup_gate(database: Path) -> dict[str, Any]:
    """启动时调用：状态非 OPEN 或存在恢复意图时抛出 GuardError。"""
    return DatabaseGuard(database).require_startable().to_dict()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="受保护的 XCAGI SQLite 恢复助手")
    parser.add_argument("--mode", choices=["status", "restore", "intent", "resolve", "gate"], default="restore")
    parser.add_argument("--operation-id", default="")
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--allowed-root", action="append", default=[])
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--backup", action="append", default=[])
    parser.add_argument("--receipt", default="")
    parser.add_argument("--decision", choices=["accept_restored", "abandon_restore"], default="")
    parser.add_argument("--evidence", default="")
    parser.add_argument("--json", action="store_true")
    return parser


def _resolve_paths(args: argparse.Namespace) -> tuple[list[RestoreTarget], list[Path]]:
    roots = [Path(item) for item in args.allowed_root]
    if not roots and args.data_dir:
        roots = [Path(args.data_dir)]
    if not roots:
        raise GuardError(GuardErrorCode.BAD_REQUEST, "必须提供 --allowed-root 或 --data-dir")
    if len(args.target) != len(args.backup):
        raise GuardError(GuardErrorCode.BAD_REQUEST, "--target 与 --backup 数量必须一致")
    targets: list[RestoreTarget] = []
    for target, backup in zip(args.target, args.backup):
        root = next(
            (
                candidate
                for candidate in roots
                if _is_within(candidate, target)
            ),
            roots[0],
        )
        targets.append(RestoreTarget(Path(target), Path(backup), root))
    return targets, roots


def _is_within(root: Path, candidate: str) -> bool:
    try:
        assert_within(root, candidate)
    except GuardError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        targets, roots = _resolve_paths(args)
        op_id = args.operation_id or new_operation_id()
        if args.mode == "status":
            database = targets[0].database if targets else Path(args.data_dir) / "data" / "xcagi.db"
            payload = DatabaseGuard(database).status().to_dict()
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.mode == "gate":
            payload = startup_gate(targets[0].database)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.mode == "intent":
            for item in targets:
                DatabaseGuard(item.database).write_intent(op_id, targets=[item.database])
            print(json.dumps({"operationId": op_id, "status": "intent-recorded"}, ensure_ascii=False))
            return 0
        if args.mode == "resolve":
            if not args.decision:
                raise GuardError(GuardErrorCode.BAD_REQUEST, "resolve 需要 --decision")
            receipt = resolve_unknown(
                targets[0].database,
                operation_id=op_id,
                decision=args.decision,
                evidence=args.evidence,
                safety_root=Path(args.data_dir or roots[0]) / "backups" / "pre-restore",
            )
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return 0

        safety_root = Path(args.data_dir or roots[0]) / "backups" / "pre-restore"
        report = guarded_restore(
            targets,
            operation_id=op_id,
            safety_root=safety_root,
        )
        if args.receipt:
            receipt_path = Path(args.receipt)
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return report.exit_code
    except GuardError as exc:
        payload = exc.to_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI 边界必须返回稳定退出码
        print(json.dumps({"code": "DB_GUARD_INTERNAL", "message": str(exc)}, ensure_ascii=False))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
