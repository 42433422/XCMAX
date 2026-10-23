"""Age-based cleanup restricted to known, non-symlink temporary directories."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CleanupPorts:
    temporary_root: Callable[[], Path]
    max_age: Callable[[], float]
    now: Callable[[], float]
    remove_tree: Callable[[Path], None]


class WorkspaceCollector:
    def __init__(self, ports: CleanupPorts, logger: logging.Logger) -> None:
        self.ports = ports
        self.logger = logger

    def collect(self) -> int:
        try:
            max_age = self.ports.max_age()
        except (TypeError, ValueError):
            max_age = 6 * 3600.0
        now = self.ports.now()
        root = self.ports.temporary_root().resolve()
        targets = [(path, root) for path in root.glob("xcagi-wt-*")]
        scratch = root / "xcmax_product_scratch"
        if not scratch.is_symlink() and scratch.is_dir():
            targets.extend((path, scratch) for path in scratch.iterdir())
        removed = 0
        for path, parent in targets:
            try:
                if path.is_symlink() or parent.is_symlink() or not path.is_dir():
                    continue
                if path.resolve().parent != parent or now - path.stat().st_mtime < max_age:
                    continue
            except OSError:
                continue
            self.ports.remove_tree(path)
            if not path.exists():
                removed += 1
        if removed:
            self.logger.info("relay 工作区 GC：清理 %d 个超期残留目录", removed)
        return removed
