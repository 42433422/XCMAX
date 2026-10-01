"""import_mod_backend_py 按物理路径隔离 sys.modules 缓存。"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from importlib.machinery import SourceFileLoader
from pathlib import Path
from threading import Event

import pytest

REPO = Path(__file__).resolve().parents[2]
ADMIN_MOD = REPO / "XCAGI" / "mods" / "xcagi-erp-domain-bridge"
SSOT_MOD = REPO / "mods" / "xcagi-erp-domain-bridge"
MOD_ID = "xcagi-erp-domain-bridge"
STEM = "domain_handlers"


@pytest.fixture(autouse=True)
def _purge_cached_modules():
    def purge():
        for key in list(sys.modules):
            if key.startswith("_xcagi_mod_") and STEM in key:
                sys.modules.pop(key, None)

    purge()
    yield
    purge()


def test_same_mod_id_different_paths_load_distinct_modules():
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    if not ADMIN_MOD.is_dir() or not SSOT_MOD.is_dir():
        pytest.skip("erp bridge mods not present")
    a = import_mod_backend_py(str(ADMIN_MOD), MOD_ID, STEM)
    b = import_mod_backend_py(str(SSOT_MOD), MOD_ID, STEM)
    assert a is not b
    assert a.__name__ != b.__name__
    assert Path(a.__file__).resolve() != Path(b.__file__).resolve()


def test_concurrent_import_waits_for_initialized_handler(tmp_path, monkeypatch):
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / f"{STEM}.py").write_text("def run_domain_handler(*args): return {'success': True}\n")
    entered, release, second_entered = Event(), Event(), Event()
    original = SourceFileLoader.exec_module

    def delayed_exec(loader, module):
        entered.set()
        assert release.wait(5)
        original(loader, module)

    def second_import():
        second_entered.set()
        return import_mod_backend_py(str(tmp_path), MOD_ID, STEM)

    monkeypatch.setattr(SourceFileLoader, "exec_module", delayed_exec)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(import_mod_backend_py, str(tmp_path), MOD_ID, STEM)
        assert entered.wait(5)
        second = pool.submit(second_import)
        try:
            assert second_entered.wait(5)
            with pytest.raises(TimeoutError):
                second.result(timeout=0.1)
        finally:
            release.set()
        loaded = first.result(timeout=5)
        assert second.result(timeout=5) is loaded
        assert loaded.run_domain_handler() == {"success": True}


def test_failed_import_does_not_poison_retry(tmp_path):
    from app.infrastructure.mods.mod_manager import import_mod_backend_py

    backend = tmp_path / "backend"
    backend.mkdir()
    source = backend / f"{STEM}.py"
    source.write_text("raise RuntimeError('initialization failed')\n")
    with pytest.raises(RuntimeError, match="initialization failed"):
        import_mod_backend_py(str(tmp_path), MOD_ID, STEM)
    source.write_text("def run_domain_handler(*args): return {'success': True}\n")
    assert import_mod_backend_py(str(tmp_path), MOD_ID, STEM).run_domain_handler() == {
        "success": True
    }
