"""Compatibility entry for the maintained FHD/rasa trainer."""

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    trainer = here.parents[1] / "rasa" / "train_rasa_model.py"
    sys.argv = [str(trainer), "--output", str(here / "models"), *sys.argv[1:]]
    runpy.run_path(str(trainer), run_name="__main__")
