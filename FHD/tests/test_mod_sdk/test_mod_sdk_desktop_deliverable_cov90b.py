"""真实行为测试：app/mod_sdk/desktop_deliverable.ensure_deliverable_runtime。

覆盖未覆盖行：早退分支、seed 成功/失败、load 跳过/成功/失败、status
就绪、auto-bootstrap 关闭/开启(成功/失败)。所有外部依赖（is_desktop_mode、
resolve_edition、seed、mod_manager、build_deliverable_status、bootstrap）
均在其真实模块路径处 patch。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk.desktop_deliverable import ensure_deliverable_runtime


def _make_app() -> MagicMock:
    """构造一个 FastAPI 替身，app.state 是可读写属性的命名空间。"""
    app = MagicMock()
    app.state = SimpleNamespace()
    return app


def _patch(**overrides):
    """集中 patch ensure_deliverable_runtime 内部函数级 import 的真实模块路径。

    返回一个 dict，键为逻辑名 → MagicMock，便于断言调用。
    overrides 可覆盖默认行为。
    """
    patchers = {}
    mocks: dict[str, MagicMock] = {}

    def add(name, target, **kw):
        p = patch(target, **kw)
        patchers[name] = p
        mocks[name] = p.start()

    # 默认：desktop 模式、edition=lite、seed 返回若干、status 就绪
    add(
        "is_desktop_mode",
        "app.desktop_runtime.paths.is_desktop_mode",
        return_value=overrides.get("is_desktop_mode", True),
    )
    add(
        "resolve_edition",
        "app.mod_sdk.edition_policy.resolve_edition",
        return_value=overrides.get("edition", "lite"),
    )
    add(
        "seed",
        "app.mod_sdk.edition_policy.seed_edition_mods_from_bundle",
        side_effect=overrides.get("seed_side_effect"),
        return_value=overrides.get("seed_return", ["mod-a"]),
    )
    add(
        "build_status",
        "app.mod_sdk.deliverable_status.build_deliverable_status",
        return_value=overrides.get("status", {"deliverable": True, "edition": "lite"}),
    )
    return patchers, mocks


def _stop(patchers):
    for p in patchers.values():
        p.stop()


class TestEarlyReturns:
    async def test_non_desktop_full_edition_returns_early(self):
        """非桌面 + full：第一个守卫即 return，seed 不应被调用。"""
        patchers, mocks = _patch(is_desktop_mode=False, edition="full")
        try:
            app = _make_app()
            await ensure_deliverable_runtime(app)
            mocks["seed"].assert_not_called()
            assert not hasattr(app.state, "deliverable_status")
        finally:
            _stop(patchers)

    async def test_desktop_full_edition_returns_after_second_guard(self):
        """桌面 + full：跳过第一守卫，但 edition=='full' 第二守卫 return。"""
        # is_desktop_mode True 让第一守卫 (not desktop and ...) 为 False，
        # 进入函数体后 edition=='full' 再次 return。
        patchers, mocks = _patch(is_desktop_mode=True, edition="full")
        try:
            app = _make_app()
            await ensure_deliverable_runtime(app)
            mocks["seed"].assert_not_called()
            assert not hasattr(app.state, "deliverable_status")
        finally:
            _stop(patchers)


class TestSeedBranch:
    async def test_seed_success_logs_and_continues(self):
        """seed 返回非空 → 走 logger.info 分支，流程继续到 status。"""
        patchers, mocks = _patch(
            seed_return=["mod-a", "mod-b"],
            status={"deliverable": True, "edition": "lite"},
        )
        try:
            app = _make_app()
            await ensure_deliverable_runtime(app)
            mocks["seed"].assert_called_once_with("lite")
            assert app.state.deliverable_status == {
                "deliverable": True,
                "edition": "lite",
            }
        finally:
            _stop(patchers)

    async def test_seed_empty_result_skips_log_continues(self):
        """seed 返回空列表 → 不进 if seeded，但流程继续。"""
        patchers, mocks = _patch(
            seed_return=[],
            status={"deliverable": True, "edition": "lite"},
        )
        try:
            app = _make_app()
            await ensure_deliverable_runtime(app)
            assert app.state.deliverable_status["deliverable"] is True
        finally:
            _stop(patchers)

    async def test_seed_recoverable_error_swallowed(self):
        """seed 抛 RECOVERABLE_ERRORS(RuntimeError) → 被捕获，流程继续。"""
        patchers, mocks = _patch(
            seed_side_effect=RuntimeError("disk busy"),
            status={"deliverable": True, "edition": "lite"},
        )
        try:
            app = _make_app()
            # 不应抛异常
            await ensure_deliverable_runtime(app)
            assert app.state.deliverable_status["deliverable"] is True
        finally:
            _stop(patchers)


class TestLoadSkipBranches:
    async def test_skip_when_full_load_done(self):
        """mods_full_load_done=True → 跳过 load，不导入 mod_manager。"""
        patchers, mocks = _patch(status={"deliverable": True, "edition": "lite"})
        try:
            app = _make_app()
            app.state.mods_full_load_done = True
            with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as gmm:
                await ensure_deliverable_runtime(app)
                gmm.assert_not_called()
            assert app.state.deliverable_status["deliverable"] is True
        finally:
            _stop(patchers)

    async def test_skip_when_background_load_scheduled(self):
        """mods_background_load_scheduled=True → 同样跳过 load。"""
        patchers, mocks = _patch(status={"deliverable": True, "edition": "lite"})
        try:
            app = _make_app()
            app.state.mods_background_load_scheduled = True
            with patch("app.infrastructure.mods.mod_manager.get_mod_manager") as gmm:
                await ensure_deliverable_runtime(app)
                gmm.assert_not_called()
            assert app.state.deliverable_status["deliverable"] is True
        finally:
            _stop(patchers)


class TestLoadActiveBranch:
    async def test_load_success_routes_not_yet_loaded(self):
        """无跳过标志 → 真正 load：load_all_mods + load_mod_routes + 置标志。"""
        patchers, mocks = _patch(status={"deliverable": True, "edition": "lite"})
        try:
            app = _make_app()
            mm = MagicMock()
            with (
                patch(
                    "app.infrastructure.mods.mod_manager.get_mod_manager",
                    return_value=mm,
                ),
                patch("app.infrastructure.mods.mod_manager.load_mod_routes") as load_routes,
            ):
                await ensure_deliverable_runtime(app)
                mm.load_all_mods.assert_called_once()
                load_routes.assert_called_once_with(app, mm)
            assert app.state.mods_routes_loaded is True
            assert app.state.mods_full_load_done is True
            assert app.state.deliverable_status["deliverable"] is True
        finally:
            _stop(patchers)

    async def test_load_success_routes_already_loaded(self):
        """mods_routes_loaded 已为 True → 不再调用 load_mod_routes。"""
        patchers, mocks = _patch(status={"deliverable": True, "edition": "lite"})
        try:
            app = _make_app()
            app.state.mods_routes_loaded = True
            mm = MagicMock()
            with (
                patch(
                    "app.infrastructure.mods.mod_manager.get_mod_manager",
                    return_value=mm,
                ),
                patch("app.infrastructure.mods.mod_manager.load_mod_routes") as load_routes,
            ):
                await ensure_deliverable_runtime(app)
                mm.load_all_mods.assert_called_once()
                load_routes.assert_not_called()
            assert app.state.mods_full_load_done is True
        finally:
            _stop(patchers)

    async def test_load_recoverable_error_returns_early(self):
        """load 抛 RECOVERABLE_ERRORS → except 内 return，不构建 status。"""
        patchers, mocks = _patch()
        try:
            app = _make_app()
            mm = MagicMock()
            mm.load_all_mods.side_effect = RuntimeError("load boom")
            with (
                patch(
                    "app.infrastructure.mods.mod_manager.get_mod_manager",
                    return_value=mm,
                ),
                patch("app.infrastructure.mods.mod_manager.load_mod_routes"),
            ):
                await ensure_deliverable_runtime(app)
            # 提前 return：build_deliverable_status 不被调用，state 无 deliverable_status
            mocks["build_status"].assert_not_called()
            assert not hasattr(app.state, "deliverable_status")
        finally:
            _stop(patchers)


class TestStatusAndBootstrap:
    async def test_status_ready_returns_before_bootstrap(self):
        """status.deliverable=True → 设置 state 后 return，不读 env/不 bootstrap。"""
        patchers, mocks = _patch(status={"deliverable": True, "edition": "lite"})
        try:
            app = _make_app()
            app.state.mods_full_load_done = True
            with patch("app.mod_sdk.edition_bootstrap.bootstrap_edition_pack") as boot:
                await ensure_deliverable_runtime(app)
                boot.assert_not_called()
            assert app.state.deliverable_status["deliverable"] is True
            assert not hasattr(app.state, "deliverable_bootstrap")
        finally:
            _stop(patchers)

    async def test_not_ready_auto_off_returns(self, monkeypatch):
        """status 未就绪 + 环境变量未开 → 记录日志后 return，不 bootstrap。"""
        monkeypatch.delenv("XCAGI_AUTO_BOOTSTRAP_EDITION", raising=False)
        patchers, mocks = _patch(status={"deliverable": False, "edition": "lite"})
        try:
            app = _make_app()
            app.state.mods_full_load_done = True
            with patch("app.mod_sdk.edition_bootstrap.bootstrap_edition_pack") as boot:
                await ensure_deliverable_runtime(app)
                boot.assert_not_called()
            assert app.state.deliverable_status["deliverable"] is False
            assert not hasattr(app.state, "deliverable_bootstrap")
        finally:
            _stop(patchers)

    async def test_not_ready_auto_on_bootstrap_success(self, monkeypatch):
        """status 未就绪 + 环境变量=1 → 调用 bootstrap，结果写入 state。"""
        monkeypatch.setenv("XCAGI_AUTO_BOOTSTRAP_EDITION", "1")
        patchers, mocks = _patch(status={"deliverable": False, "edition": "lite"})
        try:
            app = _make_app()
            app.state.mods_full_load_done = True

            async def _boot(edition):
                assert edition == "lite"
                return {"ready": True, "edition": edition}

            with patch(
                "app.mod_sdk.edition_bootstrap.bootstrap_edition_pack",
                side_effect=_boot,
            ) as boot:
                await ensure_deliverable_runtime(app)
                boot.assert_called_once_with("lite")
            assert app.state.deliverable_bootstrap == {
                "ready": True,
                "edition": "lite",
            }
        finally:
            _stop(patchers)

    async def test_not_ready_auto_on_bootstrap_recoverable_error(self, monkeypatch):
        """bootstrap 抛 RECOVERABLE_ERRORS → 被捕获，state 不写 bootstrap。"""
        monkeypatch.setenv("XCAGI_AUTO_BOOTSTRAP_EDITION", "true")
        patchers, mocks = _patch(status={"deliverable": False, "edition": "lite"})
        try:
            app = _make_app()
            app.state.mods_full_load_done = True

            async def _boom(edition):
                raise ValueError("catalog unreachable")

            with patch(
                "app.mod_sdk.edition_bootstrap.bootstrap_edition_pack",
                side_effect=_boom,
            ):
                # 不应向外抛
                await ensure_deliverable_runtime(app)
            assert not hasattr(app.state, "deliverable_bootstrap")
        finally:
            _stop(patchers)
