"""Real backend failures must not register a ready Mod or release its dependents."""

import json
import sys

import pytest

from tests.test_infrastructure.test_mod_dependency_order import runtime as runtime


@pytest.mark.parametrize(
    "source",
    [
        "def initialize():\n    raise TypeError('initialization failed')\n",
        "def initialize(required_unknown):\n    pass\n",
        "initialize = 42\n",
        "# missing declared hook\n",
        None,
    ],
)
def test_failed_initialization_does_not_become_loaded(runtime, tmp_path, monkeypatch, source):
    manager, registry, _, write = runtime
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(
        manager, "_load_mod_backend", type(manager)._load_mod_backend.__get__(manager)
    )
    write("z-failing", {})
    write("a-dependent", {"z-failing": "*"})
    path = tmp_path / "z-failing" / "manifest.json"
    data = json.loads(path.read_text())
    data["backend"] = {"entry": "entry", "init": "initialize"}
    path.write_text(json.dumps(data))
    if source is not None:
        backend = path.parent / "backend"
        backend.mkdir()
        (backend / "entry.py").write_text(source)
    try:
        assert manager.load_all_mods() == []
        assert registry.list_mod_ids() == []
        assert "z-failing" not in manager._backend_entry_modules
        assert manager._loaded_mods == []
        assert len(manager._recent_load_failures) == 2
    finally:
        for name, module in list(sys.modules.items()):
            if str(getattr(module, "__file__", "")).startswith(str(tmp_path)):
                sys.modules.pop(name, None)
