from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "candidate_prune_release_cache", ROOT / "FHD/scripts/deploy/prune_release_cache.py"
)
pruner = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(pruner)


def test_recovery_required_backup_is_not_pruned():
    with tempfile.TemporaryDirectory(prefix="fhd-recovery-prune-") as temp:
        root = Path(temp) / "backups"
        root.mkdir()
        for day in range(1, 5):
            (root / f"pre-2026010{day}-000000").mkdir()
        protected = root / "pre-20260101-000000"
        (protected / ".recovery-required").write_text("recovery/", encoding="utf-8")
        for entry in root.iterdir():
            os.utime(entry, (1000 + int(entry.name[9:11]),) * 2)

        removed = pruner.prune_backups(root, retain_backups=2)

        assert "pre-20260101-000000" not in removed
        assert protected.is_dir()
        assert (protected / ".recovery-required").is_file()
