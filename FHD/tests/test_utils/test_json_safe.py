from __future__ import annotations

import builtins
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.utils.json_safe import json_safe


def test_json_safe_scalar_temporal_and_path_values(tmp_path: Path) -> None:
    path = tmp_path / "data.txt"

    assert json_safe(None) is None
    assert json_safe(True) is True
    assert json_safe(7) == 7
    assert json_safe("ok") == "ok"
    assert json_safe(1.25) == 1.25
    assert json_safe(Decimal("2.50")) == 2.5
    assert json_safe(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05"
    assert json_safe(date(2026, 1, 2)) == "2026-01-02"
    assert json_safe(path) == str(path)


def test_json_safe_bytes_success_and_recoverable_failure() -> None:
    class BadBytes(bytes):
        def decode(self, *_args: Any, **_kwargs: Any) -> str:
            raise RuntimeError("decode failed")

    assert json_safe("中文".encode()) == "中文"
    assert json_safe(BadBytes(b"broken")) == ""


def test_json_safe_numpy_generic_without_real_numpy(monkeypatch) -> None:
    class FakeScalar:
        def item(self) -> int:
            return 42

    class FakeNumpy:
        generic = FakeScalar

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "numpy":
            return FakeNumpy
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert json_safe(FakeScalar()) == 42


def test_json_safe_import_error_nested_containers_and_fallback(monkeypatch) -> None:
    class CustomObject:
        def __str__(self) -> str:
            return "custom-object"

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "numpy":
            raise ImportError("numpy unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert json_safe({1: [Decimal("3.5"), (date(2026, 2, 3),), {Path("x")}]}) == {
        "1": [3.5, ["2026-02-03"], ["x"]]
    }
    assert json_safe(CustomObject()) == "custom-object"
