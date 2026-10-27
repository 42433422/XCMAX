"""测试 database_service 模块 - 数据库管理服务。"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.engine import make_url

import app.domain.shared_services.database_service as db_mod
from app.domain.shared_services.database_service import DatabaseService


@pytest.fixture
def service(tmp_path, monkeypatch):
    service = DatabaseService()
    monkeypatch.setattr(service, "_get_db_path", lambda: str(tmp_path / "live.db"))
    monkeypatch.setattr(service, "_get_backup_dir", lambda: str(tmp_path / "backups"))
    return service


class TestGetDbPath:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("sqlite:///relative.db", os.path.join(os.getcwd(), "relative.db")),
            ("sqlite:////absolute/path/test.db", "/absolute/path/test.db"),
            ("postgresql://test@localhost/test", None),
            ("sqlite://", None),
        ],
    )
    def test_runtime_engine_path(self, url, expected):
        with patch("app.db.get_runtime_engine", return_value=SimpleNamespace(url=make_url(url))):
            assert DatabaseService()._get_db_path() == expected


class TestGetBackupDir:
    def test_creates_backup_dir(self, tmp_path):
        svc = DatabaseService()
        with patch("app.utils.path_io.path_utils.get_data_dir", return_value=str(tmp_path)):
            backup_dir = svc._get_backup_dir()
            assert os.path.isdir(backup_dir)
            assert "database_backups" in backup_dir


class TestBackupDatabase:
    @pytest.mark.parametrize(
        "path,message", [(None, "仅支持 SQLite"), ("/nonexistent/path/test.db", "不存在")]
    )
    def test_backup_unavailable(self, path, message):
        with patch.object(DatabaseService, "_get_db_path", return_value=path):
            result = DatabaseService().backup_database()
        assert result["success"] is False
        assert message in result["message"]

    def test_backup_copies_content(self, tmp_path, service):
        """sqlite3.backup() API 备份出来的库必须包含全部已提交数据。"""
        db_file = tmp_path / "live.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('important data')")
        conn.commit()
        conn.close()
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        result = service.backup_database()

        assert result["success"] is True
        assert os.path.exists(result["file_path"])
        assert result["filename"].endswith(".bak")
        verify_conn = sqlite3.connect(result["file_path"])
        rows = verify_conn.execute("SELECT v FROM t").fetchall()
        verify_conn.close()
        assert rows == [("important data",)]


class TestRestoreDatabase:
    @pytest.mark.parametrize(
        "case",
        [
            "workflow-parent",
            "missing-actor",
            "business-orphan",
            "audit-orphan",
            "same-row-orphan",
            "market-mismatch",
            "tenant-mismatch",
            "market-missing",
            "tenant-missing",
            "legacy-created",
            "tenant-local-created",
            "legacy-unknown",
            "legacy-mismatch",
            "tenant-local-mismatch",
            "legacy-time-missing",
            "legacy-tag-collision",
            "old-identity-schema",
            "composite-parent",
            "implicit-parent",
        ],
    )
    def test_restore_preserves_parent_chain_or_refuses_orphaned_audit(
        self, tmp_path, service, case
    ):
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from app.db.db_base import Base
        from app.db.models import User
        from app.db.models.approval import ApprovalFlow, ApprovalFlowNode, ApprovalRequest
        from app.db.models.workflow import WorkflowDefinition, WorkflowRun, WorkflowRunStep

        live, backup = tmp_path / "live.db", tmp_path / "snapshot.bak"
        engine = create_engine(f"sqlite:///{live}")
        audit = (WorkflowDefinition, WorkflowRun, WorkflowRunStep, ApprovalRequest)
        Base.metadata.create_all(
            engine,
            tables=[model.__table__ for model in (*audit, User, ApprovalFlow, ApprovalFlowNode)],
        )
        birth = datetime(2026, 10, 1, 9, 0, 0)
        changes = {
            "market-mismatch": {"market_user_id": 202},
            "tenant-mismatch": {"tenant_id": 20},
            "market-missing": {"market_user_id": None},
            "tenant-missing": {"tenant_id": None},
            "legacy-mismatch": {"created_at": datetime(2026, 10, 2, 9, 0, 0)},
            "tenant-local-mismatch": {"created_at": datetime(2026, 10, 2, 9, 0, 0)},
            "legacy-time-missing": {"created_at": None},
            "legacy-tag-collision": {
                "market_user_id": "legacy",
                "tenant_id": "2026-10-01 09:00:00.000000",
            },
        }
        try:
            with Session(engine) as db:
                db.add(
                    User(
                        id=1,
                        username="actor",
                        password="test",
                        role="user",
                        market_user_id=None
                        if case.startswith(("legacy-", "tenant-local-"))
                        else 101,
                        tenant_id=None if case.startswith("legacy-") else 10,
                        created_at=None if case == "legacy-unknown" else birth,
                    )
                )
                db.add(
                    User(
                        id=3,
                        username="unreferenced",
                        password="test",
                        market_user_id=303,
                        tenant_id=30,
                        created_at=birth,
                    )
                )
                db.add(ApprovalFlow(id=1, flow_key="restore", flow_name="Restore"))
                if case in {"audit-orphan", "same-row-orphan"}:
                    db.add(
                        ApprovalRequest(
                            id=1,
                            request_no="old-orphan",
                            flow_id=1,
                            applicant_id=1,
                            business_type="workflow_tool",
                            title="Old",
                        )
                    )
                db.commit()
            with sqlite3.connect(live) as db:
                db.execute("pragma journal_mode=wal")
                db.execute("create table products(price real)")
                db.execute("insert into products values(12.5)")
                if case == "composite-parent":
                    db.execute("create unique index restore_actor on users(id, tenant_id)")
                    db.execute(
                        "create table ai_action_audit(actor_id integer, actor_tenant integer, foreign key(actor_id, actor_tenant) references users(id, tenant_id))"
                    )
                if case == "implicit-parent":
                    db.execute("create table ai_action_audit(actor_id integer references users)")
                if case == "business-orphan":
                    db.execute("update users set created_by=99")
                if case in {"audit-orphan", "same-row-orphan"}:
                    db.execute("update approval_requests set applicant_id=99")
            with sqlite3.connect(live) as db, sqlite3.connect(backup) as target:
                db.backup(target)
                if case == "old-identity-schema":
                    target.execute("drop index ix_users_market_user_id")
                    target.execute("alter table users drop column market_user_id")
            original_backup = backup.read_bytes()
            with Session(engine) as db:
                actor = db.get(User, 1)
                actor.role, actor.username, actor.password = (
                    "admin",
                    "current-actor",
                    "new-password",
                )
                for field, value in changes.get(case, {}).items():
                    setattr(actor, field, value)
                db.get(User, 3).market_user_id, db.get(User, 3).tenant_id = 404, 40
                if case in {"missing-actor", "same-row-orphan"}:
                    db.add(User(id=2, username="new-actor", password="test"))
                db.add(WorkflowDefinition(id=2, name="Created after backup", nodes="[]"))
                db.add(WorkflowRun(id=2, definition_id=2, status="succeeded"))
                db.add(WorkflowRunStep(id=2, run_id=2, node_id="done", status="succeeded"))
                db.add(
                    ApprovalRequest(
                        id=2,
                        request_no="new-request",
                        flow_id=1,
                        applicant_id=2 if case == "missing-actor" else 1,
                        business_type="workflow_tool",
                        title="New",
                    )
                )
                db.commit()
            with sqlite3.connect(live) as db:
                db.execute("update products set price=13.75")
                if case == "composite-parent":
                    db.execute("insert into ai_action_audit values(1,10)")
                if case == "implicit-parent":
                    db.execute("insert into ai_action_audit values(1)")
                if case == "same-row-orphan":
                    db.execute("update approval_requests set applicant_id=2 where id=1")
                prior_violations = db.execute("pragma foreign_key_check").fetchall()
            with engine.connect() as db:
                receipts = [db.execute(select(model.__table__)).fetchall() for model in audit]
            restored = case in {
                "workflow-parent",
                "business-orphan",
                "legacy-created",
                "tenant-local-created",
                "composite-parent",
                "implicit-parent",
            }
            result = service.restore_database(str(backup))
            assert result["success"] is restored
            if not restored:
                assert "审计关联" in result["message"]
            with engine.connect() as db:
                assert [
                    db.execute(select(model.__table__)).fetchall() for model in audit
                ] == receipts
            with sqlite3.connect(live) as db:
                assert db.execute("select price from products").fetchone()[0] == (
                    12.5 if restored else 13.75
                )
                assert db.execute("select role from users where id=1").fetchone()[0] == (
                    "user" if restored else "admin"
                )
                assert db.execute("select username, password from users where id=1").fetchone() == (
                    ("actor", "test") if restored else ("current-actor", "new-password")
                )
                assert db.execute("select tenant_id from users where id=3").fetchone()[0] == (
                    30 if restored else 40
                )
                assert db.execute("pragma foreign_key_check").fetchall() == prior_violations
                if case in {"composite-parent", "implicit-parent"}:
                    assert db.execute("select actor_id from ai_action_audit").fetchall() == [(1,)]
                assert db.execute("pragma integrity_check").fetchone() == ("ok",)
            assert backup.read_bytes() == original_backup
            assert not list(tmp_path.glob("xcagi-restore-*"))
        finally:
            engine.dispose()

    @pytest.mark.parametrize(
        "case", ["new-audit", "schema-mismatch", "concurrent-write", "slow-copy"]
    )
    def test_restore_preserves_live_audit_or_refuses_before_commit(
        self, tmp_path, monkeypatch, service, case
    ):
        live, backup = tmp_path / "live.db", tmp_path / "snapshot.bak"
        with sqlite3.connect(backup) as db:
            db.execute("create table products(price real)")
            db.execute("insert into products values(12.5)")
            if case != "new-audit":
                db.execute(
                    "create table ai_action_audit(id integer primary key autoincrement, result text)"
                )
                db.execute("insert into ai_action_audit values(1, 'old')")
        with sqlite3.connect(live) as db:
            db.execute("pragma journal_mode=wal")
            db.execute("create table products(price real)")
            db.execute("insert into products values(13.75)")
            db.execute(
                "create table ai_action_audit(id integer primary key autoincrement, result text)"
            )
            db.execute("create unique index audit_unique_result on ai_action_audit(result)")
            db.execute(
                "create trigger audit_no_blank before insert on ai_action_audit when new.result='' begin select raise(abort, 'blank receipt'); end"
            )
            db.execute("insert into ai_action_audit values(1, 'completed')")
            db.execute("insert into ai_action_audit values(3, 'retired receipt')")
            db.execute("delete from ai_action_audit where id=3")
            if case == "schema-mismatch":
                db.execute("alter table ai_action_audit add column actor text")
            audit_schema = db.execute(
                "select sql from sqlite_master where name='ai_action_audit'"
            ).fetchone()[0]
        original_backup = backup.read_bytes()
        stage = service._stage_restore

        def stage_then_write(*args):
            version = stage(*args)
            with sqlite3.connect(live) as writer:
                writer.execute("insert into ai_action_audit values(2, 'late receipt')")
            return version

        if case == "concurrent-write":
            monkeypatch.setattr(service, "_stage_restore", stage_then_write)
        if case == "slow-copy":
            monkeypatch.setattr(db_mod, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 3])))
        result = service.restore_database(str(backup))
        restored = case != "concurrent-write"
        assert result["success"] is restored
        with sqlite3.connect(live) as reopened:
            assert reopened.execute("select price from products").fetchone()[0] == (
                12.5 if restored else 13.75
            )
            assert reopened.execute(
                "select result from ai_action_audit order by id"
            ).fetchall() == (
                [("completed",), ("late receipt",)]
                if case == "concurrent-write"
                else [("completed",)]
            )
            assert reopened.execute("pragma integrity_check").fetchone()[0] == "ok"
            assert (
                reopened.execute(
                    "select sql from sqlite_master where name='ai_action_audit'"
                ).fetchone()[0]
                == audit_schema
            )
            if restored:
                assert (
                    reopened.execute(
                        "insert into ai_action_audit(result) values('after restore')"
                    ).lastrowid
                    == 4
                )
                with pytest.raises(sqlite3.IntegrityError):
                    reopened.execute("insert into ai_action_audit(result) values('completed')")
                with pytest.raises(sqlite3.IntegrityError):
                    reopened.execute("insert into ai_action_audit(result) values('')")
        assert backup.read_bytes() == original_backup
        assert not list(tmp_path.glob("xcagi-restore-*"))

    @pytest.mark.parametrize("path,message", [(None, "仅支持 SQLite"), ("live.db", "不存在")])
    def test_restore_unavailable(self, service, path, message):
        with patch.object(service, "_get_db_path", return_value=path):
            result = service.restore_database("nonexistent.bak")
        assert result["success"] is False
        assert message in result["message"]

    @pytest.mark.parametrize("absolute", [False, True])
    def test_restore_success_with_live_wal_connection(
        self, tmp_path, service, absolute, monkeypatch
    ):
        root = tmp_path / "userdata"
        db_file = root / "data" / "xcagi.db"
        db_file.parent.mkdir(parents=True)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        backup_file = backup_dir / "test.db.20240101_000000.bak"
        with sqlite3.connect(backup_file) as snapshot:
            snapshot.execute("create table products(price real)")
            snapshot.execute("insert into products values (12.50)")
        marker = root / "config" / "database-recovery-required"
        marker.parent.mkdir(parents=True)
        marker.write_text("corrupt_no_backup\n", encoding="utf-8")
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
        monkeypatch.setenv("XCAGI_DATA_DIR", str(root))
        monkeypatch.setenv("XCAGI_DESKTOP_DB_RECOVERY", "corrupt_no_backup")
        monkeypatch.setattr(service, "_get_db_path", lambda: str(db_file))
        live = sqlite3.connect(db_file)
        try:
            live.execute("pragma journal_mode=wal")
            live.execute("create table products(price real)")
            live.execute("insert into products values (13.50)")
            live.commit()
            result = service.restore_database(str(backup_file) if absolute else backup_file.name)
            assert result["success"] is True
            assert not marker.exists()
            assert os.environ["XCAGI_DESKTOP_DB_RECOVERY"] == f"restored:{backup_file.name}"
            assert live.execute("select price from products").fetchone()[0] == 12.50
            assert live.execute("pragma integrity_check").fetchone()[0] == "ok"
        finally:
            live.close()
        with sqlite3.connect(db_file) as reopened:
            assert reopened.execute("select price from products").fetchone()[0] == 12.50
            assert reopened.execute("pragma integrity_check").fetchone()[0] == "ok"

    def test_restore_invalid_backup_preserves_database(self, tmp_path, service):
        db_file = tmp_path / "live.db"
        with sqlite3.connect(db_file) as db:
            db.execute("create table products(price real)")
            db.execute("insert into products values (13.50)")
        original = db_file.read_bytes()
        backup_file = tmp_path / "custom_backup.bak"
        backup_file.write_text("new")

        result = service.restore_database(str(backup_file))

        assert result["success"] is False
        assert db_file.read_bytes() == original

    def test_restore_locked_database_fails_without_overwriting_or_hanging(self, tmp_path, service):
        live_path, backup = tmp_path / "live.db", tmp_path / "snapshot.bak"
        with sqlite3.connect(backup) as snapshot:
            snapshot.execute("create table products(price real)")
            snapshot.execute("insert into products values (12.50)")
        writer = sqlite3.connect(live_path)
        try:
            writer.execute("pragma journal_mode=wal")
            writer.execute("create table products(price real)")
            writer.execute("insert into products values (13.50)")
            writer.commit()
            writer.execute("update products set price=14.50")
            result = service.restore_database(str(backup))
            assert result["success"] is False
            assert writer.execute("select price from products").fetchone()[0] == 14.50
            writer.rollback()
            assert writer.execute("select price from products").fetchone()[0] == 13.50
            assert writer.execute("pragma integrity_check").fetchone()[0] == "ok"
        finally:
            writer.close()


class TestListBackups:
    @pytest.mark.parametrize("exists", [False, True])
    def test_list_empty_or_missing_dir(self, tmp_path, service, exists):
        folder = tmp_path / "backups"
        if exists:
            folder.mkdir()
        result = service.list_backups()
        assert result["success"] is True
        assert result["count"] == 0

    def test_list_finds_bak_files(self, tmp_path, service):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "test1.bak").write_text("b1")
        (backup_dir / "test2.bak").write_text("b2")
        (backup_dir / "other.txt").write_text("not a backup")

        result = service.list_backups()

        assert result["success"] is True
        assert result["count"] == 2
        filenames = [b["filename"] for b in result["backups"]]
        assert "test1.bak" in filenames
        assert "test2.bak" in filenames
        assert "other.txt" not in filenames
        for backup in result["backups"]:
            assert {"filename", "file_path", "size", "created_at"} <= backup.keys()
        dates = [backup["created_at"] for backup in result["backups"]]
        assert dates == sorted(dates, reverse=True)


class TestDeleteBackup:
    def test_delete_nonexistent_returns_failure(self, service):
        result = service.delete_backup("nonexistent.bak")
        assert result["success"] is False

    @pytest.mark.parametrize("absolute", [False, True])
    def test_delete_success(self, tmp_path, absolute):
        backup_file = tmp_path / "test.bak"
        backup_file.write_text("backup data")
        with patch.object(DatabaseService, "_get_backup_dir", return_value=str(tmp_path)):
            result = DatabaseService().delete_backup(
                str(backup_file) if absolute else backup_file.name
            )
        assert result["success"] is True
        assert not backup_file.exists()


class TestServiceReExportGuard:
    def test_reexports_services_version_not_utils(self):
        import app.domain.shared_services.database_service as correct_mod
        import app.services as services_pkg

        assert services_pkg.get_database_service is correct_mod.get_database_service
        assert isinstance(services_pkg.get_database_service(), DatabaseService)

    def test_backup_database_uses_hot_backup_not_shutil_copy(self, tmp_path, service):
        db_file = tmp_path / "live.db"
        with sqlite3.connect(db_file) as db:
            db.execute("CREATE TABLE t (id INTEGER)")
        with patch.object(DatabaseService, "_hot_backup", return_value=False) as mock_hot:
            result = service.backup_database()
        assert result["success"] is False
        assert "热备份失败" in result["message"]
        mock_hot.assert_called_once()
