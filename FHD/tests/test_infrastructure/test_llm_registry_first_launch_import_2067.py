"""#2067 首启：健康检查与后台线程并发导入 market_account 时不得破坏门面导入。

预验 run1-electron-backend.log：/api/health → LLMPort.is_available →
registry._active_with_conversation 在 market_account 仍在初始化时导入
market_account_part01，得到 _DeadlockError；随后 ``except (RECOVERABLE_ERRORS,
ImportError)`` 因嵌套元组又抛 TypeError，健康检查 500。
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
import types
from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest

from app.domain.neuro.cognition import llm_port
from app.infrastructure.llm.providers import registry

FHD_ROOT = Path(__file__).resolve().parents[2]
FACADE = "app.fastapi_routes.market_account"

_RACE_SCRIPT = textwrap.dedent(
    """
    import importlib.abc, sys, threading, time

    FACADE = "app.fastapi_routes.market_account"

    class _Slow(importlib.abc.Loader):
        # 放大首启冷导入窗口：门面已进 sys.modules、模块体还没执行完。
        def __init__(self, inner):
            self.inner = inner
        def create_module(self, spec):
            return self.inner.create_module(spec)
        def exec_module(self, module):
            time.sleep(0.5)
            self.inner.exec_module(module)

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name != FACADE:
                return None
            for f in sys.meta_path:
                if f is self or not hasattr(f, "find_spec"):
                    continue
                spec = f.find_spec(name, path, target)
                if spec is not None:
                    spec.loader = _Slow(spec.loader)
                    return spec
            return None

    sys.meta_path.insert(0, _Finder())

    import app.infrastructure.llm.providers.registry  # noqa: F401
    from app.domain.neuro.cognition import llm_port

    res = {}

    def background_import():
        try:
            import app.fastapi_routes.market_account  # noqa: F401
            res["import"] = "ok"
        except BaseException as exc:
            res["import"] = f"{type(exc).__name__}: {exc}"

    def health_probe():
        while FACADE not in sys.modules:
            time.sleep(0.0005)
        try:
            llm_port._source.get_active()
            res["health"] = "ok"
        except (TypeError, ImportError) as exc:
            res["health"] = f"{type(exc).__name__}: {exc}"
        except BaseException:
            res["health"] = "ok"  # 测试环境未配置模型等业务异常与本问题无关

    a = threading.Thread(target=background_import)
    b = threading.Thread(target=health_probe)
    b.start(); a.start(); a.join(60); b.join(60)
    mod = sys.modules.get(FACADE)
    loaded = bool(mod and hasattr(mod, "login_market_with_password"))
    print(f"RESULT import={res.get('import')} | health={res.get('health')} | loaded={loaded}")
    """
)


def test_health_probe_during_first_market_account_import_keeps_facade_loadable():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(FHD_ROOT), *[p for p in sys.path if p]])
    proc = subprocess.run(
        [sys.executable, "-c", _RACE_SCRIPT],
        cwd=str(FHD_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, proc.stderr[-4000:]
    assert lines[-1] == "RESULT import=ok | health=ok | loaded=True", lines[-1]


def _fake_facade(*, initializing: bool) -> types.ModuleType:
    mod = types.ModuleType(FACADE)
    spec = ModuleSpec(FACADE, loader=None)
    spec._initializing = initializing  # type: ignore[attr-defined]
    mod.__spec__ = spec
    mod.latest_session_market_token = lambda: "tok"  # type: ignore[attr-defined]
    return mod


def test_token_reader_ignores_facade_still_initializing(monkeypatch):
    monkeypatch.setitem(sys.modules, FACADE, _fake_facade(initializing=True))
    assert registry._initialized_market_token_reader() is None


def test_token_reader_uses_initialized_facade(monkeypatch):
    fake = _fake_facade(initializing=False)
    monkeypatch.setitem(sys.modules, FACADE, fake)
    assert registry._initialized_market_token_reader() is fake.latest_session_market_token


def test_token_reader_never_imports_missing_facade(monkeypatch):
    monkeypatch.delitem(sys.modules, FACADE, raising=False)
    monkeypatch.delitem(sys.modules, FACADE + "_part01", raising=False)
    assert registry._initialized_market_token_reader() is None
    assert FACADE not in sys.modules
    assert FACADE + "_part01" not in sys.modules


def test_import_lock_error_falls_back_instead_of_type_error(monkeypatch):
    """_DeadlockError 是 RuntimeError 子类；必须被吞掉并回退，而不是变成 TypeError。"""
    sentinel = object()

    def _boom():
        raise RuntimeError("deadlock detected by _ModuleLock('app.fastapi_routes.market_account')")

    monkeypatch.setattr(
        "app.services.conversation.manager.get_ai_conversation_service_if_ready",
        lambda: None,
    )
    monkeypatch.setattr(registry, "_initialized_market_token_reader", lambda: _boom)
    monkeypatch.setattr(registry, "get_active_provider", lambda *a, **k: sentinel)
    registry._register_llm_port_source()
    assert llm_port._source is not None
    assert llm_port._source.get_active() is sentinel


def _nested_error_tuple_handlers(root: Path) -> list[str]:
    hits: list[str] = []
    for path in root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or not isinstance(node.type, ast.Tuple):
                continue
            for elt in node.type.elts:
                if isinstance(elt, ast.Name) and elt.id.endswith("_ERRORS"):
                    hits.append(f"{path.relative_to(root.parent)}:{node.lineno}")
    return hits


def test_no_except_clause_nests_an_error_tuple():
    """``except (RECOVERABLE_ERRORS, X)`` 在异常发生时抛 TypeError；应写成元组拼接。"""
    assert _nested_error_tuple_handlers(FHD_ROOT / "app") == []


@pytest.mark.parametrize("snippet", ["except (RECOVERABLE_ERRORS, ImportError):"])
def test_nested_error_tuple_guard_detects_pattern(tmp_path, snippet):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "m.py").write_text(f"try:\n    pass\n{snippet}\n    pass\n", encoding="utf-8")
    assert _nested_error_tuple_handlers(pkg) == ["app/m.py:3"]
