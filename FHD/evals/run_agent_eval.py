"""Re-export split modules (debt19). Includes private (_*) names."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _reexport(module) -> None:
    g = globals()
    for name, value in vars(module).items():
        if name.startswith("__") and name.endswith("__"):
            continue
        g[name] = value


if __name__ == "__main__":
    # Preserve historic `python FHD/evals/run_agent_eval.py` entry.
    target = Path(__file__).with_name("run_agent_eval_mod3.py")
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
else:
    from . import run_agent_eval_mod1 as _split_0
    from . import run_agent_eval_mod2 as _split_1
    from . import run_agent_eval_mod3 as _split_2

    _reexport(_split_0)
    _reexport(_split_1)
    _reexport(_split_2)
    del _reexport, _split_0, _split_1, _split_2
