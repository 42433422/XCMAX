from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from app.infrastructure.mods.mod_manager import import_mod_backend_py


def test_import_mod_backend_never_returns_partially_initialized_module(tmp_path: Path) -> None:
    mod_dir = tmp_path / "concurrent-mod"
    backend_dir = mod_dir / "backend"
    backend_dir.mkdir(parents=True)
    started = tmp_path / "started"
    release = tmp_path / "release"
    (backend_dir / "slow_handler.py").write_text(
        "\n".join(
            [
                "from threading import Event",
                "from pathlib import Path",
                f"started = Path({str(started)!r})",
                f"release = Path({str(release)!r})",
                "poll_wait = Event()",
                "started.write_text('1', encoding='utf-8')",
                "while not release.exists():",
                "    poll_wait.wait(0.005)",
                "READY = True",
            ]
        ),
        encoding="utf-8",
    )

    results: list[object] = []
    errors: list[BaseException] = []

    def load_module() -> None:
        try:
            results.append(import_mod_backend_py(str(mod_dir), "concurrent-mod", "slow_handler"))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=load_module)
    first.start()
    deadline = time.monotonic() + 2
    while not started.exists() and time.monotonic() < deadline:
        threading.Event().wait(0.005)
    assert started.exists()

    second = threading.Thread(target=load_module)
    second.start()
    threading.Event().wait(0.05)
    assert second.is_alive(), "second importer observed a partially initialized module"

    release.write_text("1", encoding="utf-8")
    first.join(timeout=2)
    second.join(timeout=2)

    assert not errors
    assert len(results) == 2
    assert results[0] is results[1]
    assert getattr(results[0], "READY", False) is True

    sys.modules.pop(getattr(results[0], "__name__", ""), None)
