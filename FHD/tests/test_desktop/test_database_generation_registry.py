"""保护协议核心测试：代次、锁、状态机、回执与 UNKNOWN 解除。

覆盖需求第 10—15、19—21、29、33 条中可在 Linux 复现的部分。
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from app.desktop_runtime.database_generation_registry import (
    DatabaseGuard,
    GuardError,
    GuardErrorCode,
    GuardState,
    assert_no_alias,
    assert_within,
    new_operation_id,
)
from app.desktop_runtime.restore_helper import (
    RestoreTarget,
    guarded_restore,
    replace_from_backup,
    resolve_unknown,
    sqlite_clone,
)


def _make_db(path: Path, rows: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    conn.executemany(
        "INSERT INTO items (value) VALUES (?)", [(f"row-{index}",) for index in range(rows)]
    )
    conn.commit()
    conn.close()
    return path


def _rows(path: Path) -> list[str]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [row[0] for row in conn.execute("SELECT value FROM items ORDER BY id")]
    finally:
        conn.close()


def _force_dead_owner(guard: DatabaseGuard, *, operation_id: str) -> None:
    if guard._state_path.exists():
        payload = json.loads(guard._state_path.read_text(encoding="utf-8"))
    else:
        payload = guard._default_record().to_payload()
    payload["state"] = GuardState.RESTORING.value
    payload["operationId"] = operation_id
    # 一个几乎不可能存在的 pid，模拟恢复进程被强杀。
    payload["ownerPid"] = 2_000_000_000
    guard._state_path.parent.mkdir(parents=True, exist_ok=True)
    guard._state_path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# 路径身份
# ---------------------------------------------------------------------------


def test_assert_within_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(GuardError) as exc:
        assert_within(root, tmp_path / "outside.db")
    assert exc.value.code is GuardErrorCode.PATH_ESCAPE


def test_assert_no_alias_rejects_symlink(tmp_path: Path) -> None:
    real = _make_db(tmp_path / "data" / "xcagi.db")
    alias = tmp_path / "alias.db"
    alias.symlink_to(real)
    with pytest.raises(GuardError) as exc:
        assert_no_alias(alias, real)
    assert exc.value.code is GuardErrorCode.ALIAS


# ---------------------------------------------------------------------------
# WAL 数据与 sidecar 隔离
# ---------------------------------------------------------------------------


def test_clone_includes_unmerged_wal_rows(tmp_path: Path) -> None:
    source = tmp_path / "src.db"
    conn = sqlite3.connect(str(source))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.executemany(
        "INSERT INTO items (value) VALUES (?)", [(f"wal-{index}",) for index in range(4)]
    )
    conn.commit()  # WAL 中已有已提交但未 checkpoint 的数据
    try:
        cloned = tmp_path / "clone.db"
        sqlite_clone(source, cloned)
        assert _rows(cloned) == [f"wal-{index}" for index in range(4)]
    finally:
        conn.close()


def test_replace_quarantines_sidecars_instead_of_deleting(tmp_path: Path) -> None:
    target = _make_db(tmp_path / "data" / "xcagi.db")
    wal = target.with_name(target.name + "-wal")
    shm = target.with_name(target.name + "-shm")
    wal.write_bytes(b"old-wal")
    shm.write_bytes(b"old-shm")
    backup = _make_db(tmp_path / "backups" / "snapshot.db", rows=7)

    replace_from_backup(target, backup, stamp="op1")

    assert _rows(target) == [f"row-{index}" for index in range(7)]
    assert not wal.exists()
    assert not shm.exists()
    quarantined = sorted(path.name for path in target.parent.iterdir())
    assert f"{target.name}.pre-restore-op1-wal" in quarantined
    assert f"{target.name}.pre-restore-op1-shm" in quarantined


# ---------------------------------------------------------------------------
# 代次与写租约
# ---------------------------------------------------------------------------


def test_write_lease_invalidated_by_restore_and_generation(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db")
    backup = _make_db(tmp_path / "backups" / "snapshot.db")
    guard = DatabaseGuard(database)
    old_lease = guard.write_lease()
    assert old_lease.still_valid()
    old_lease.release()

    report = guarded_restore(
        [RestoreTarget(database, backup, tmp_path)],
        operation_id=new_operation_id(),
        safety_root=tmp_path / "backups" / "pre-restore",
    )
    assert report.status == "succeeded", report.error
    status = guard.status()
    assert status.state is GuardState.OPEN
    assert status.generation == 1

    with guard.write_lease() as lease:
        with pytest.raises(GuardError) as exc:
            old_lease.assert_valid()
        assert exc.value.code is GuardErrorCode.STALE_GENERATION
        assert lease.generation == 1


def test_write_rejected_while_restoring(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db")
    guard = DatabaseGuard(database)
    session = guard.begin_restore(new_operation_id(), targets=[database])
    try:
        with pytest.raises(GuardError) as exc:
            guard.write_lease()
        assert exc.value.code is GuardErrorCode.RESTORING
        session.abort("test")
    finally:
        if not session._closed:
            session.abort("cleanup")
    assert guard.status().state is GuardState.OPEN
    guard.write_lease().release()


def test_writer_drain_timeout_returns_closed_without_modification(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db")
    guard = DatabaseGuard(database)
    guard._writers_dir.mkdir(parents=True, exist_ok=True)
    slot = guard._writers_dir / "alive.slot"
    slot.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

    with pytest.raises(GuardError) as exc:
        guard.begin_restore(new_operation_id(), writer_drain_timeout=0.3)
    assert exc.value.code is GuardErrorCode.WRITER_DRAIN_TIMEOUT
    assert guard.status().state is GuardState.OPEN
    slot.unlink()


def test_duplicate_operation_rejected(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db")
    backup = _make_db(tmp_path / "backups" / "snapshot.db")
    operation_id = new_operation_id()
    first = guarded_restore(
        [RestoreTarget(database, backup, tmp_path)],
        operation_id=operation_id,
        safety_root=tmp_path / "backups" / "pre-restore",
    )
    assert first.status == "succeeded", first.error
    second = guarded_restore(
        [RestoreTarget(database, backup, tmp_path)],
        operation_id=operation_id,
        safety_root=tmp_path / "backups" / "pre-restore",
    )
    assert second.status == "refused"
    assert second.error and second.error["code"] == GuardErrorCode.DUPLICATE_OPERATION.value


# ---------------------------------------------------------------------------
# 多目标
# ---------------------------------------------------------------------------


def test_multi_target_partial_failure_compensates_first_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _make_db(tmp_path / "data" / "one.db", rows=2)
    second = _make_db(tmp_path / "data" / "two.db", rows=2)
    first_backup = _make_db(tmp_path / "backups" / "one.db", rows=9)
    second_backup = _make_db(tmp_path / "backups" / "two.db", rows=9)
    from app.desktop_runtime import restore_helper

    original = restore_helper.replace_from_backup

    def failing_replace(target: Path, backup: Path, *, stamp: str) -> str:
        if Path(target).name == "two.db" and "comp" not in stamp:
            raise OSError("injected disk failure")
        return original(target, backup, stamp=stamp)

    monkeypatch.setattr(restore_helper, "replace_from_backup", failing_replace)
    report = guarded_restore(
        [
            RestoreTarget(first, first_backup, tmp_path),
            RestoreTarget(second, second_backup, tmp_path),
        ],
        operation_id=new_operation_id(),
        safety_root=tmp_path / "backups" / "pre-restore",
    )
    assert report.status == "failed_compensated", report.error
    # 第一个目标已替换后补偿回原内容
    assert _rows(first) == ["row-0", "row-1"]
    assert _rows(second) == ["row-0", "row-1"]
    assert DatabaseGuard(first).status().state is GuardState.OPEN
    assert DatabaseGuard(second).status().state is GuardState.OPEN


def test_multi_target_validation_failure_modifies_nothing(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db", rows=2)
    backup = tmp_path / "backups" / "broken.db"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"not a sqlite database")
    report = guarded_restore(
        [RestoreTarget(database, backup, tmp_path)],
        operation_id=new_operation_id(),
        safety_root=tmp_path / "backups" / "pre-restore",
    )
    assert report.status == "refused"
    assert _rows(database) == ["row-0", "row-1"]
    assert DatabaseGuard(database).status().state is GuardState.OPEN


# ---------------------------------------------------------------------------
# UNKNOWN 保留与显式解除
# ---------------------------------------------------------------------------


def test_dead_owner_downgrades_to_unknown_and_blocks_writes(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db")
    guard = DatabaseGuard(database)
    operation_id = new_operation_id()
    _force_dead_owner(guard, operation_id=operation_id)

    status = guard.status()
    assert status.state is GuardState.UNKNOWN
    assert status.operation_id == operation_id
    with pytest.raises(GuardError) as exc:
        guard.write_lease()
    assert exc.value.code is GuardErrorCode.UNKNOWN
    with pytest.raises(GuardError):
        guard.require_startable()


def test_resolve_unknown_requires_evidence_and_receipt(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db")
    guard = DatabaseGuard(database)
    operation_id = new_operation_id()
    _force_dead_owner(guard, operation_id=operation_id)

    with pytest.raises(GuardError) as exc:
        guard.resolve_unknown(operation_id, decision="accept_restored", evidence="  ")
    assert exc.value.code is GuardErrorCode.BAD_REQUEST

    with pytest.raises(GuardError) as exc:
        guard.resolve_unknown(operation_id, decision="accept_restored", evidence="人工确认文件完整")
    assert exc.value.code is GuardErrorCode.VERIFY_FAILED
    assert guard.status().state is GuardState.UNKNOWN


def test_resolve_unknown_accept_restored_reopens(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db")
    backup = _make_db(tmp_path / "backups" / "snapshot.db", rows=5)
    guard = DatabaseGuard(database)
    operation_id = new_operation_id()
    session = guard.begin_restore(operation_id, targets=[database])
    session.mark_modified(database)
    from app.desktop_runtime.database_generation_registry import file_sha256

    guard.write_receipt(
        {
            "operationId": operation_id,
            "status": "succeeded",
            "generationAfter": 0,
            "targets": [{"path": str(database), "sha256": file_sha256(database)}],
        }
    )
    _force_dead_owner(guard, operation_id=operation_id)
    assert guard.status().state is GuardState.UNKNOWN

    status = guard.resolve_unknown(
        operation_id,
        decision="accept_restored",
        evidence="核对回执哈希与磁盘一致",
    )
    assert status.state is GuardState.OPEN
    assert status.generation == 1


def test_unknown_abandon_requires_successful_compensation(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db")
    guard = DatabaseGuard(database)
    operation_id = new_operation_id()
    _force_dead_owner(guard, operation_id=operation_id)
    guard.write_receipt(
        {
            "operationId": operation_id,
            "status": "unknown",
            "targets": [],
        }
    )

    with pytest.raises(GuardError) as exc:
        guard.resolve_unknown(
            operation_id,
            decision="abandon_restore",
            evidence="回退到安全备份",
            compensation=lambda: {"status": "failed", "message": "备份缺失"},
        )
    assert exc.value.code is GuardErrorCode.VERIFY_FAILED
    assert guard.status().state is GuardState.UNKNOWN


def test_startup_gate_blocks_pending_intent(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db")
    guard = DatabaseGuard(database)
    operation_id = new_operation_id()
    guard.write_intent(operation_id, targets=[database])
    with pytest.raises(GuardError) as exc:
        guard.require_startable()
    assert exc.value.code is GuardErrorCode.INTENT_PENDING
    guard.clear_intent(operation_id)
    assert guard.require_startable().state is GuardState.OPEN


def test_reopen_refused_when_receipt_hash_mismatch(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db")
    guard = DatabaseGuard(database)
    operation_id = new_operation_id()
    session = guard.begin_restore(operation_id, targets=[database])
    session.mark_modified(database, sha256="0" * 64)
    session.commit()
    with pytest.raises(GuardError) as exc:
        guard.reopen(operation_id)
    assert exc.value.code is GuardErrorCode.VERIFY_FAILED
    assert guard.status().state is GuardState.UNKNOWN


def test_resolve_unknown_helper_uses_registered_safety_backup(tmp_path: Path) -> None:
    database = _make_db(tmp_path / "data" / "xcagi.db", rows=2)
    backup = _make_db(tmp_path / "backups" / "snapshot.db", rows=6)
    operation_id = new_operation_id()
    report = guarded_restore(
        [RestoreTarget(database, backup, tmp_path)],
        operation_id=operation_id,
        safety_root=tmp_path / "backups" / "pre-restore",
    )
    assert report.status == "succeeded", report.error
    guard = DatabaseGuard(database)
    _force_dead_owner(guard, operation_id=operation_id)

    result = resolve_unknown(
        database,
        operation_id=operation_id,
        decision="abandon_restore",
        evidence="回滚到恢复前安全备份",
        safety_root=tmp_path / "backups" / "pre-restore",
    )
    assert result["state"] == GuardState.OPEN.value
    assert _rows(database) == ["row-0", "row-1"]
