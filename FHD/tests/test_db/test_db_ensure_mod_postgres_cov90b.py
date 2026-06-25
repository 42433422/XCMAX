"""第二波真实行为测试: app/db/ensure_mod_postgres.py 未覆盖分支。

聚焦:
- _load_bootstrap_module (真实加载 + spec=None 错误分支)
- ensure_postgres_per_mod_databases 内的 clone 分支 / 空后缀跳过 / 两类 except 分支
- 迁移选择阶段的 clone 跳过 + 空后缀跳过
- _migrate_mod_databases 全函数 (alembic.ini 缺失 / 目标过滤 / subprocess 成功与失败)

所有外部依赖 (DB engine、bootstrap 子函数、subprocess) 均 mock。离线、确定、快速。
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.db import ensure_mod_postgres as mod
from app.db.ensure_mod_postgres import (
    _load_bootstrap_module,
    _migrate_mod_databases,
    ensure_postgres_per_mod_databases,
)


def _make_engine(conn):
    """构造一个 admin_engine mock，其 connect() 作为上下文管理器返回 conn。"""
    engine = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    engine.dispose = MagicMock()
    return engine


def _pg_env():
    return {
        "XCAGI_MOD_ISOLATED_DATABASES": "1",
        "DATABASE_URL": "postgresql://user:pass@localhost/xcagi",
    }


# ---------------------------------------------------------------------------
# _load_bootstrap_module  (lines 20-26)
# ---------------------------------------------------------------------------


class TestLoadBootstrapModule:
    def test_real_load_exposes_helpers(self):
        """真实加载 scripts/bootstrap_mod_dbs.py（离线、无 DB），返回带辅助函数的模块。"""
        boot = _load_bootstrap_module()
        assert hasattr(boot, "_normalize_mod_file_suffix")
        assert hasattr(boot, "_discover_mod_ids")
        assert hasattr(boot, "DEFAULT_CLONE_FROM_BASE_MOD_IDS")
        # 真实归一化：非字母数字 -> "_" 再 strip("_")
        assert boot._normalize_mod_file_suffix("My-Mod") == "my_mod"
        assert boot._normalize_mod_file_suffix("!!!") == ""

    def test_spec_none_raises_runtime_error(self):
        """spec_from_file_location 返回 None 时抛 RuntimeError（line 22-23）。"""
        with patch("importlib.util.spec_from_file_location", return_value=None):
            with pytest.raises(RuntimeError, match="cannot load"):
                _load_bootstrap_module()

    def test_spec_loader_none_raises_runtime_error(self):
        """spec.loader 为 None 时同样抛 RuntimeError（line 22-23 的第二个条件）。"""
        fake_spec = MagicMock()
        fake_spec.loader = None
        with patch("importlib.util.spec_from_file_location", return_value=fake_spec):
            with pytest.raises(RuntimeError, match="cannot load"):
                _load_bootstrap_module()


# ---------------------------------------------------------------------------
# ensure_postgres_per_mod_databases —— clone 分支 / 空后缀 / except
# ---------------------------------------------------------------------------


class TestEnsureCloneBranch:
    @patch("app.db.ensure_mod_postgres._migrate_mod_databases")
    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_clone_from_base_template(self, mock_load, mock_migrate):
        """mod 在 clone 集合内 -> 走 _create_db_from_template，且不进入迁移列表（line 102-104, 132-133）。"""
        boot = MagicMock()
        boot._discover_mod_ids.return_value = ["taiyangniao-pro"]
        boot._normalize_mod_file_suffix.return_value = "taiyangniao_pro"
        boot.DEFAULT_CLONE_FROM_BASE_MOD_IDS = ("taiyangniao-pro",)
        # 基库存在，mod 库不存在
        boot._db_exists.side_effect = lambda conn, dbn: dbn == "xcagi"
        boot._create_db_from_template = MagicMock()
        boot._create_db_empty = MagicMock()
        boot._url_for_database.return_value = (
            "postgresql://user:pass@localhost/xcagi__taiyangniao_pro"
        )
        boot._enable_pgvector = MagicMock()

        conn = MagicMock()
        boot._maintenance_engine.return_value = _make_engine(conn)
        mock_load.return_value = boot

        with patch.dict(os.environ, _pg_env(), clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            result = ensure_postgres_per_mod_databases()

        assert result == ["xcagi__taiyangniao_pro"]
        # clone 路径被调用，空库创建未被调用
        boot._create_db_from_template.assert_called_once()
        args = boot._create_db_from_template.call_args[0]
        assert args[1] == "xcagi__taiyangniao_pro"
        assert args[2] == "xcagi"  # 模板基库
        boot._create_db_empty.assert_not_called()
        # pgvector 仍对克隆库启用
        boot._enable_pgvector.assert_called_once()
        # 克隆库已含 schema -> 不进迁移，迁移函数不应被调用（migrate_new 默认 True 但 to_migrate 为空）
        mock_migrate.assert_not_called()

    @patch("app.db.ensure_mod_postgres._migrate_mod_databases")
    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_empty_suffix_skipped_in_create_and_migrate(self, mock_load, mock_migrate):
        """后缀归一化为空的 mod 在创建阶段(line 97-98)与迁移选择阶段(line 135-136)都被跳过。"""
        boot = MagicMock()
        boot._discover_mod_ids.return_value = ["!!!"]
        boot._normalize_mod_file_suffix.return_value = ""  # 空后缀
        boot.DEFAULT_CLONE_FROM_BASE_MOD_IDS = ()
        boot._db_exists.side_effect = lambda conn, dbn: dbn == "xcagi"
        boot._create_db_empty = MagicMock()
        boot._create_db_from_template = MagicMock()

        conn = MagicMock()
        boot._maintenance_engine.return_value = _make_engine(conn)
        mock_load.return_value = boot

        with patch.dict(os.environ, _pg_env(), clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            result = ensure_postgres_per_mod_databases()

        assert result == []
        boot._create_db_empty.assert_not_called()
        boot._create_db_from_template.assert_not_called()
        mock_migrate.assert_not_called()

    @patch("app.db.ensure_mod_postgres._migrate_mod_databases")
    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_empty_db_triggers_migration_call(self, mock_load, mock_migrate):
        """非 clone 的新库 -> 进入 to_migrate -> 调用 _migrate_mod_databases（line 138-142）。"""
        boot = MagicMock()
        boot._discover_mod_ids.return_value = ["mod1"]
        boot._normalize_mod_file_suffix.return_value = "mod1"
        boot.DEFAULT_CLONE_FROM_BASE_MOD_IDS = ()
        boot._db_exists.side_effect = lambda conn, dbn: dbn == "xcagi"
        boot._create_db_empty = MagicMock()
        boot._url_for_database.return_value = "postgresql://user:pass@localhost/xcagi__mod1"
        boot._enable_pgvector = MagicMock()

        conn = MagicMock()
        boot._maintenance_engine.return_value = _make_engine(conn)
        mock_load.return_value = boot

        with patch.dict(os.environ, _pg_env(), clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            result = ensure_postgres_per_mod_databases()

        assert result == ["xcagi__mod1"]
        boot._create_db_empty.assert_called_once()
        mock_migrate.assert_called_once_with(["xcagi__mod1"], mod_ids=["mod1"])

    @patch("app.db.ensure_mod_postgres._migrate_mod_databases")
    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_migrate_new_false_skips_migration(self, mock_load, mock_migrate):
        """migrate_new=False 时即便有新库也不迁移（line 141 条件假分支）。"""
        boot = MagicMock()
        boot._discover_mod_ids.return_value = ["mod1"]
        boot._normalize_mod_file_suffix.return_value = "mod1"
        boot.DEFAULT_CLONE_FROM_BASE_MOD_IDS = ()
        boot._db_exists.side_effect = lambda conn, dbn: dbn == "xcagi"
        boot._create_db_empty = MagicMock()
        boot._url_for_database.return_value = "postgresql://user:pass@localhost/xcagi__mod1"
        boot._enable_pgvector = MagicMock()

        conn = MagicMock()
        boot._maintenance_engine.return_value = _make_engine(conn)
        mock_load.return_value = boot

        with patch.dict(os.environ, _pg_env(), clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            result = ensure_postgres_per_mod_databases(migrate_new=False)

        assert result == ["xcagi__mod1"]
        mock_migrate.assert_not_called()


class TestEnsureExceptionBranches:
    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_recoverable_error_returns_empty(self, mock_load):
        """连接阶段抛 RECOVERABLE_ERRORS（如 OSError）-> 记录 warning 并返回 []（line 109-114）。"""
        boot = MagicMock()
        boot._discover_mod_ids.return_value = ["mod1"]
        boot._normalize_mod_file_suffix.return_value = "mod1"
        boot.DEFAULT_CLONE_FROM_BASE_MOD_IDS = ()

        engine = MagicMock()
        # connect() 进入 with 即抛 OSError（recoverable）
        engine.connect.side_effect = OSError("no CREATEDB / maintenance down")
        engine.dispose = MagicMock()
        boot._maintenance_engine.return_value = engine
        mock_load.return_value = boot

        with patch.dict(os.environ, _pg_env(), clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            result = ensure_postgres_per_mod_databases()

        assert result == []
        # finally 块仍 dispose
        engine.dispose.assert_called_once()

    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_sqlalchemy_error_returns_empty(self, mock_load):
        """非 recoverable 的 SQLAlchemyError（如 ProgrammingError）-> 单独分支返回 []（line 115-121）。"""
        from sqlalchemy.exc import ProgrammingError

        boot = MagicMock()
        boot._discover_mod_ids.return_value = ["mod1"]
        boot._normalize_mod_file_suffix.return_value = "mod1"
        boot.DEFAULT_CLONE_FROM_BASE_MOD_IDS = ()

        # ProgrammingError 是 SQLAlchemyError 子类，但不在 RECOVERABLE_ERRORS 内
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        assert not issubclass(ProgrammingError, RECOVERABLE_ERRORS)

        conn = MagicMock()
        engine = _make_engine(conn)
        # _db_exists 在 with 块内抛 ProgrammingError（权限不足等）
        boot._db_exists.side_effect = ProgrammingError("CREATE", {}, Exception("denied"))
        boot._maintenance_engine.return_value = engine
        mock_load.return_value = boot

        with patch.dict(os.environ, _pg_env(), clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            result = ensure_postgres_per_mod_databases()

        assert result == []
        engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# _migrate_mod_databases  (lines 147-187)
# ---------------------------------------------------------------------------


class TestMigrateModDatabases:
    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_alembic_ini_missing_skips(self, mock_load):
        """alembic.ini 不存在 -> 记录 warning 并直接 return（line 156-158），不跑 subprocess。"""
        boot = MagicMock()
        mock_load.return_value = boot

        fake_ini = MagicMock()
        fake_ini.is_file.return_value = False

        with (
            patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://user:pass@localhost/xcagi"},
                clear=False,
            ),
            patch.object(mod, "_REPO_ROOT") as repo_root,
            patch("subprocess.run") as mock_run,
        ):
            repo_root.__truediv__.return_value = fake_ini
            _migrate_mod_databases(["xcagi__mod1"], mod_ids=["mod1"])

        mock_run.assert_not_called()
        boot._normalize_mod_file_suffix.assert_not_called()

    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_migrate_success_runs_alembic(self, mock_load):
        """alembic.ini 存在 + 目标库匹配 -> 跑 alembic 成功（returncode=0，line 172-187 OK 分支）。"""
        boot = MagicMock()
        boot._normalize_mod_file_suffix.return_value = "mod1"
        boot._url_for_database.return_value = "postgresql://user:pass@localhost/xcagi__mod1"
        mock_load.return_value = boot

        fake_ini = MagicMock()
        fake_ini.is_file.return_value = True

        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "upgrade ok"
        completed.stderr = ""

        with (
            patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://user:pass@localhost/xcagi"},
                clear=False,
            ),
            patch.object(mod, "_REPO_ROOT") as repo_root,
            patch("subprocess.run", return_value=completed) as mock_run,
        ):
            repo_root.__truediv__.return_value = fake_ini
            repo_root.__str__ = MagicMock(return_value="/repo")
            _migrate_mod_databases(["xcagi__mod1"], mod_ids=["mod1"])

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        # 子进程 env 的 DATABASE_URL 被改写为 mod_url
        assert call_kwargs["env"]["DATABASE_URL"] == (
            "postgresql://user:pass@localhost/xcagi__mod1"
        )
        assert call_kwargs["capture_output"] is True
        assert call_kwargs["text"] is True
        # 命令含 alembic upgrade head
        cmd = mock_run.call_args.args[0]
        assert "alembic" in cmd
        assert "upgrade" in cmd
        assert "head" in cmd

    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_migrate_failure_logs_error(self, mock_load):
        """alembic 退出非 0 -> 记录 error（line 179-185），不抛异常。"""
        boot = MagicMock()
        boot._normalize_mod_file_suffix.return_value = "mod1"
        boot._url_for_database.return_value = "postgresql://user:pass@localhost/xcagi__mod1"
        mock_load.return_value = boot

        fake_ini = MagicMock()
        fake_ini.is_file.return_value = True

        completed = MagicMock()
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "boom: migration error"

        with (
            patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://user:pass@localhost/xcagi"},
                clear=False,
            ),
            patch.object(mod, "_REPO_ROOT") as repo_root,
            patch("subprocess.run", return_value=completed) as mock_run,
            patch.object(mod.logger, "error") as mock_err,
        ):
            repo_root.__truediv__.return_value = fake_ini
            repo_root.__str__ = MagicMock(return_value="/repo")
            # 不应抛异常
            _migrate_mod_databases(["xcagi__mod1"], mod_ids=["mod1"])

        mock_run.assert_called_once()
        mock_err.assert_called_once()

    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_empty_suffix_skipped(self, mock_load):
        """后缀为空的 mod 在迁移阶段被跳过（line 162-164），不跑 subprocess。"""
        boot = MagicMock()
        boot._normalize_mod_file_suffix.return_value = ""  # 空
        mock_load.return_value = boot

        fake_ini = MagicMock()
        fake_ini.is_file.return_value = True

        with (
            patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://user:pass@localhost/xcagi"},
                clear=False,
            ),
            patch.object(mod, "_REPO_ROOT") as repo_root,
            patch("subprocess.run") as mock_run,
        ):
            repo_root.__truediv__.return_value = fake_ini
            _migrate_mod_databases(None, mod_ids=["!!!"])

        mock_run.assert_not_called()

    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_target_set_filters_out_non_matching(self, mock_load):
        """only_dbnames 非空且某 mod 库不在集合 -> 该库被过滤掉（line 166-167）。"""
        boot = MagicMock()
        # 两个 mod：mod1 在目标集合，mod2 不在
        boot._normalize_mod_file_suffix.side_effect = lambda mid: mid
        boot._url_for_database.return_value = "postgresql://user:pass@localhost/xcagi__mod1"
        mock_load.return_value = boot

        fake_ini = MagicMock()
        fake_ini.is_file.return_value = True

        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "ok"
        completed.stderr = ""

        with (
            patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://user:pass@localhost/xcagi"},
                clear=False,
            ),
            patch.object(mod, "_REPO_ROOT") as repo_root,
            patch("subprocess.run", return_value=completed) as mock_run,
        ):
            repo_root.__truediv__.return_value = fake_ini
            repo_root.__str__ = MagicMock(return_value="/repo")
            # only_dbnames 仅含 mod1，mod_ids 含 mod1 与 mod2
            _migrate_mod_databases(["xcagi__mod1"], mod_ids=["mod1", "mod2"])

        # 仅 mod1 被迁移，mod2 被过滤
        assert mock_run.call_count == 1
        called_url = boot._url_for_database.call_args[0][1]
        assert called_url == "xcagi__mod1"
