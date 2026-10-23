"""Private binding persistence, legacy migration and identity-checked updates."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.application.desktop_relay.ports import JsonObject, ReadConfig, RelayBinding, WriteConfig


@dataclass(frozen=True)
class ConfigurationPorts:
    path: Callable[[], Path]
    legacy_path: Callable[[], Path]
    migration_done: Callable[[], bool]
    mark_migrated: Callable[[], None]
    read_config: ReadConfig
    write_config: WriteConfig
    base_url: Callable[[], str]


class RelayConfigStore:
    def __init__(self, ports: ConfigurationPorts, logger: logging.Logger) -> None:
        self.ports = ports
        self.logger = logger
        self._lock = threading.RLock()

    def read(self) -> JsonObject:
        with self._lock:
            path = self.ports.path()
            try:
                if not path.is_file() or path.is_symlink():
                    return {}
                os.chmod(path, 0o600)
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (OSError, json.JSONDecodeError):
                self.logger.warning(
                    "mobile relay desktop config is unreadable: %s", path, exc_info=True
                )
                return {}

    def write(self, data: JsonObject) -> None:
        with self._lock:
            path = self.ports.path()
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    prefix=".mobile_relay_",
                    delete=False,
                ) as stream:
                    temp_path = Path(stream.name)
                    stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
                os.chmod(temp_path, 0o600)
                os.replace(temp_path, path)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)

    def update_if_current(self, expected: RelayBinding, changes: JsonObject) -> JsonObject | None:
        """Apply a response only while its full binding still owns this file."""
        return self._apply_if_current(expected, changes, replace=False)

    def replace_if_current(self, expected: RelayBinding, changes: JsonObject) -> JsonObject | None:
        return self._apply_if_current(expected, changes, replace=True)

    def _apply_if_current(
        self, expected: RelayBinding, changes: JsonObject, *, replace: bool
    ) -> JsonObject | None:
        with self._lock:
            current = self.ports.read_config()
            if RelayBinding.from_config(current, self.ports.base_url()) != expected:
                return None
            updated = dict(changes) if replace else {**current, **changes}
            if updated != current:
                self.ports.write_config(updated)
            return updated

    def migrate_legacy_once(self) -> None:
        with self._lock:
            if self.ports.migration_done():
                return
            self.ports.mark_migrated()
            path, legacy_path = self.ports.path(), self.ports.legacy_path()
            try:
                if path.is_file() or not legacy_path.is_file():
                    return
                if legacy_path.is_symlink():
                    raise OSError("legacy relay config symlink rejected")
                if path.resolve() == legacy_path.resolve():
                    return
                path.parent.mkdir(parents=True, exist_ok=True)
                os.chmod(legacy_path, 0o600)
                legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
                if not isinstance(legacy, dict):
                    raise ValueError("legacy relay config must be an object")
                self.ports.write_config(legacy)
                self.logger.info("迁移历史云中继配对凭证 %s -> %s", legacy_path, path)
            except (OSError, ValueError):
                self.logger.warning("云中继配对凭证迁移失败", exc_info=True)
