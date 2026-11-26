"""Load Excel vendor runtimes with their production package imports."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_module(name: str, path: Path) -> ModuleType:
    if path.parent.name in {"excel_template_write", "excel_qc"}:
        vendor = str(path.parent.parent)
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        return importlib.import_module(f"{path.parent.name}.{path.stem}")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
