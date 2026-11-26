"""Report this interpreter's exact runtime paths to the existing SRT controller."""

from __future__ import annotations

import json
import sys
import sysconfig
from pathlib import Path


def runtime_read_paths() -> list[str]:
    """Include Python code and shared libraries without exposing install parents."""
    readable = [
        sys.executable,
        str(Path(sys.executable).resolve()),
        str(Path(sys.prefix) / "pyvenv.cfg"),
        *(sysconfig.get_path(key) for key in ("stdlib", "platstdlib", "purelib", "platlib")),
    ]
    for parent in (sysconfig.get_config_var("LIBDIR"), str(Path(sys.base_prefix) / "lib")):
        if parent:
            for name in (
                sysconfig.get_config_var("LDLIBRARY"),
                sysconfig.get_config_var("INSTSONAME"),
            ):
                if name:
                    library = Path(parent) / name
                    if library.is_file():
                        readable.extend((str(library), str(library.resolve())))
    framework = sysconfig.get_config_var("PYTHONFRAMEWORK")
    if framework:
        library = Path(sys.base_prefix) / framework
        if library.is_file():
            readable.extend((str(library), str(library.resolve())))
    return sorted({path for path in readable if path and Path(path).exists()})


if __name__ == "__main__":
    print(json.dumps({"executable": sys.executable, "read_paths": runtime_read_paths()}))
