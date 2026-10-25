"""Re-export / script entry for split eval modules (debt19)."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path as _Path


def _load_splits_into(g: dict) -> None:
    here = _Path(__file__).resolve().parent
    for name in (
        "run_agent_eval_mod1.py",
        "run_agent_eval_mod2.py",
        "run_agent_eval_mod3.py",
    ):
        path = here / name
        src = path.read_text(encoding="utf-8")
        exec(compile(src, str(path), "exec"), g)


if __name__ == "__main__":
    g = {"__name__": "__main__", "__file__": __file__}
    _load_splits_into(g)
    raise SystemExit(g["main"]())
else:
    _load_splits_into(globals())
