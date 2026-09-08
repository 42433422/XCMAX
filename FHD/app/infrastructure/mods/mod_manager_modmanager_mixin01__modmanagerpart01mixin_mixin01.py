# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.infrastructure.mods.mod_manager")


class __ModManagerPart01MixinPart01Mixin:
    def __init__(self, mods_root: str | None = None):
        self._explicit_mods_root = mods_root is not None
        if mods_root is None:
            mods_root = _facade()._default_mods_root()
        else:
            if not _facade().os.fspath(mods_root).strip():
                raise ValueError("Explicit mods_root must not be empty")
            mods_root = _facade().os.path.abspath(mods_root)
            _facade().os.makedirs(mods_root, exist_ok=True)
        self.mods_root = mods_root
        self._loaded_mods: list[str] = []
        self._mod_import_cache: dict = {}
        self._recent_load_failures: list[dict[str, str]] = []
        self._blueprint_failures: list[dict[str, str]] = []
        self._scan_manifest_errors: list[dict[str, str]] = []
        self._last_ensure_at: float = 0.0
        self._ensure_attempts: int = 0
        self._http_routes_registered: set[str] = set()
        self._scan_cache_fp: str = ""
        self._scan_cache_mods: list = []
        self._backend_entry_modules: dict[str, object] = {}

    def invalidate_scan_cache(self) -> None:
        self._scan_cache_fp = ""
        self._scan_cache_mods = []

    def _mods_scan_fingerprint(self) -> str:
        parts: list[str] = []
        for root in self.all_mods_roots():
            parts.append(_facade().os.path.abspath(root))
            if not _facade().os.path.isdir(root):
                continue
            try:
                entries = sorted(_facade().os.listdir(root))
            except OSError:
                continue
            for entry in entries:
                if entry.startswith("_"):
                    continue
                manifest_path = _facade().os.path.join(root, entry, "manifest.json")
                if _facade().os.path.isfile(manifest_path):
                    try:
                        parts.append(f"{entry}:{_facade().os.path.getmtime(manifest_path):.6f}")
                    except OSError:
                        parts.append(entry)
        return "|".join(parts)

    def _refresh_mods_root_if_needed(self) -> None:
        """
        显式指定的目录始终固定，创建失败时向调用方报告，禁止回退到其它库。
        未指定目录时：优先采用有效的 XCAGI_MODS_ROOT / XCAGI_MODS_DIR；
        若当前路径不存在则重新 _default_mods_root()。
        避免进程早期 import 顺序或 cwd 导致单例锁死在空目录，之后即使用户改环境变量也无法加载。
        """
        if self._explicit_mods_root:
            _facade().os.makedirs(self.mods_root, exist_ok=True)
            return
        env_raw = (
            _facade().os.environ.get("XCAGI_MODS_ROOT")
            or _facade().os.environ.get("XCAGI_MODS_DIR")
            or ""
        ).strip()
        if env_raw:
            p = _facade().os.path.abspath(env_raw)
            if _facade().os.path.isdir(p):
                if self.mods_root != p:
                    _facade().logger.info(
                        "[ModManager] Updating mods_root from env: %s -> %s", self.mods_root, p
                    )
                    self.mods_root = p
                    self._ensure_attempts = 0
                return
            _facade().logger.warning(
                "[ModManager] XCAGI_MODS_ROOT / XCAGI_MODS_DIR is set but not a directory: %s (keeping %s)",
                p,
                self.mods_root,
            )
        if not _facade().os.path.isdir(self.mods_root):
            fb = _facade()._default_mods_root()
            if fb != self.mods_root:
                _facade().logger.warning(
                    "[ModManager] mods_root was missing or invalid (%s), re-resolved -> %s",
                    self.mods_root,
                    fb,
                )
                self.mods_root = fb
                self._ensure_attempts = 0

    def _record_load_failure(self, mod_id: str, stage: str, message: str) -> None:
        self._recent_load_failures.append(
            {"mod_id": mod_id, "stage": stage, "message": message[:500]}
        )

    def record_blueprint_failure(self, mod_id: str, message: str) -> None:
        self._blueprint_failures.append({"mod_id": mod_id, "message": message[:500]})

    def get_recent_load_failures(self) -> list[dict[str, str]]:
        return list(self._recent_load_failures)

    def get_blueprint_failures(self) -> list[dict[str, str]]:
        return list(self._blueprint_failures)

    def get_scan_manifest_errors(self) -> list[dict[str, str]]:
        return list(self._scan_manifest_errors)

    def ensure_mods_loaded(self, app: _facade().Any) -> None:
        """若注册表中尚无 Mod，但 mods 目录下存在合法 manifest，则再执行 load_all_mods + load_mod_routes。"""
        try:
            if _facade().is_mods_disabled():
                return
            self._refresh_mods_root_if_needed()
            if self.list_loaded_mods():
                return
            discovered = self.scan_mods()
            if not discovered:
                return
            now = _facade().time.monotonic()
            if self._last_ensure_at and now - self._last_ensure_at < 1.5:
                return
            if self._ensure_attempts >= 20:
                return
            self._last_ensure_at = now
            self._ensure_attempts += 1
            _facade().logger.warning(
                "[ModManager] 注册表无 Mod 但磁盘有 manifest，第 %s 次尝试加载：mods_root=%s，manifest 数=%s",
                self._ensure_attempts,
                self.mods_root,
                len(discovered),
            )
            self.load_all_mods()
            _facade().load_mod_routes(app, self)
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.exception(
                "[ModManager] ensure_mods_loaded failed (mods_root=%s): %s",
                getattr(self, "mods_root", None),
                e,
            )

    def all_mods_roots(self) -> list[str]:
        self._refresh_mods_root_if_needed()
        return _facade()._all_mods_roots(self.mods_root)

    def resolve_mod_directory(self, mod_id: str) -> str | None:
        """在全部 mods 根目录中定位 Mod 目录（主根优先）；支持 legacy → 中性 id 别名。"""
        from app.mod_sdk.industry_mod_aliases import (
            canonical_mod_id,
            is_retired_runtime_mod_id,
            legacy_mod_ids_for,
        )

        mid = (mod_id or "").strip()
        if not mid:
            return None

        def _direct(candidate: str) -> str | None:
            cid = (candidate or "").strip()
            if not cid:
                return None
            for root in self.all_mods_roots():
                mod_path = _facade()._trusted_child_path(root, cid, directory=True)
                if mod_path and _facade()._trusted_child_path(
                    mod_path, "manifest.json", directory=False
                ):
                    return mod_path
            return None

        canonical = canonical_mod_id(mid)
        if is_retired_runtime_mod_id(mid) and canonical != mid:
            return _direct(canonical)
        hit = _direct(mid)
        if hit:
            return hit
        if canonical != mid:
            hit = _direct(canonical)
            if hit:
                return hit
        for leg in legacy_mod_ids_for(canonical):
            hit = _direct(leg)
            if hit:
                return hit
        return None

    def _scan_mods_from_build_index(self, fp: str) -> list[_facade().ModMetadata] | None:
        """读取构建时生成的 mods-index.json（指纹一致时）。"""
        import json

        for root in self.all_mods_roots():
            index_path = _facade().os.path.join(root, "mods-index.json")
            if not _facade().os.path.isfile(index_path):
                continue
            try:
                payload = json.loads(_facade().Path(index_path).read_text(encoding="utf-8"))
            except _facade().RECOVERABLE_ERRORS:
                continue
            if str(payload.get("fingerprint") or "") != fp:
                continue
            rows = payload.get("mods")
            if not isinstance(rows, list):
                continue
            mods: list[_facade().ModMetadata] = []
            seen: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                mod_path = str(row.get("mod_path") or "").strip()
                if not mod_path or not _facade().os.path.isfile(
                    _facade().os.path.join(mod_path, "manifest.json")
                ):
                    continue
                metadata = _facade().parse_manifest(mod_path)
                if metadata:
                    from app.mod_sdk.industry_mod_aliases import is_retired_runtime_mod_id

                    if is_retired_runtime_mod_id(metadata.id):
                        continue
                if metadata and metadata.id not in seen:
                    seen.add(metadata.id)
                    mods.append(metadata)
            if mods:
                _facade().logger.info(
                    "[ModManager] scan_mods via mods-index.json (%s mods)", len(mods)
                )
                return mods
        return None

    def scan_mods(self, *, use_cache: bool = True) -> list[_facade().ModMetadata]:
        self._refresh_mods_root_if_needed()
        fp = self._mods_scan_fingerprint()
        if use_cache and fp and (fp == self._scan_cache_fp) and self._scan_cache_mods:
            return list(self._scan_cache_mods)
        indexed = self._scan_mods_from_build_index(fp) if use_cache else None
        if indexed is not None:
            self._scan_cache_fp = fp
            self._scan_cache_mods = indexed
            return list(indexed)
        _facade().logger.debug("[ModManager] Scanning mods roots: %s", self.all_mods_roots())
        self._scan_manifest_errors = []
        mods: list[_facade().ModMetadata] = []
        seen_ids: set[str] = set()
        for mods_root in self.all_mods_roots():
            if not _facade().os.path.isdir(mods_root):
                _facade().logger.warning(
                    "[ModManager] Mods directory does not exist: %s", mods_root
                )
                continue
            for entry in _facade().os.listdir(mods_root):
                if entry.startswith("_"):
                    continue
                mod_path = _facade().os.path.join(mods_root, entry)
                if not _facade().os.path.isdir(mod_path):
                    continue
                manifest_path = _facade().os.path.join(mod_path, "manifest.json")
                _facade().logger.debug(
                    "[ModManager] Checking %s/%s, manifest exists: %s",
                    mods_root,
                    entry,
                    _facade().os.path.isfile(manifest_path),
                )
                metadata = _facade().parse_manifest(mod_path)
                if metadata:
                    from app.mod_sdk.industry_mod_aliases import is_retired_runtime_mod_id

                    if is_retired_runtime_mod_id(metadata.id):
                        _facade().logger.info(
                            "[ModManager] Skip retired runtime mod: %s", metadata.id
                        )
                        continue
                    if metadata.id in seen_ids:
                        continue
                    seen_ids.add(metadata.id)
                    mods.append(metadata)
                    _facade().logger.debug(
                        "[ModManager] Found mod: %s (%s) v%s @ %s",
                        metadata.id,
                        metadata.name,
                        metadata.version,
                        mod_path,
                    )
                else:
                    _facade().logger.warning(
                        "[ModManager] Failed to parse manifest for mod entry: %s/%s",
                        mods_root,
                        entry,
                    )
                    self._scan_manifest_errors.append(
                        {
                            "entry": entry,
                            "mods_root": mods_root,
                            "message": "manifest.json 缺失或无法解析（检查 JSON 与必填字段 id）",
                        }
                    )
        _facade().logger.info("[ModManager] Total mods found: %s", len(mods))
        self._scan_cache_fp = fp
        self._scan_cache_mods = mods
        return mods

    def load_mod(self, mod_id: str) -> bool:
        from app.mod_sdk.industry_mod_aliases import canonical_mod_id, is_retired_runtime_mod_id

        requested_mod_id = str(mod_id or "").strip()
        if is_retired_runtime_mod_id(requested_mod_id):
            mod_id = canonical_mod_id(requested_mod_id)
            _facade().logger.info(
                "[ModManager] Redirect retired runtime mod %s -> %s",
                requested_mod_id,
                mod_id,
            )
        try:
            from app.mod_sdk.product_skus import assert_mod_allowed_for_sku

            assert_mod_allowed_for_sku(mod_id)
        except PermissionError as exc:
            _facade().logger.warning("[ModManager] Mod blocked for SKU: %s — %s", mod_id, exc)
            self._record_load_failure(mod_id, "sku_policy", str(exc))
            return False
        registry = _facade().get_mod_registry()
        _facade().logger.info("[ModManager] Attempting to load mod: %s", mod_id)
        if registry.get_mod_metadata(mod_id):
            _facade().logger.info("[ModManager] Mod %s is already loaded", mod_id)
            if mod_id not in self._loaded_mods:
                _facade().logger.warning(
                    "[ModManager] Mod %s in registry but missing from _loaded_mods; syncing list",
                    mod_id,
                )
                self._loaded_mods.append(mod_id)
            return True
        from app.infrastructure.mods.install_receipts import activate_pending_install

        if not activate_pending_install(mod_id, mods_root=self.mods_root):
            self._record_load_failure(mod_id, "restart_required", "Mod 更新需要重启后加载")
            return False
        mod_path = self.resolve_mod_directory(mod_id)
        _facade().logger.info("[ModManager] Mod path: %s", mod_path)
        if not mod_path:
            self._record_load_failure(
                mod_id, "fs", f"目录不存在（已搜索 mods 根: {self.all_mods_roots()}）"
            )
            return False
        metadata = _facade().parse_manifest(mod_path)
        if not metadata:
            _facade().logger.error("[ModManager] Failed to parse manifest for mod: %s", mod_id)
            self._record_load_failure(mod_id, "manifest", "manifest.json 无效或缺少 id")
            return False
        _facade().logger.info(
            "[ModManager] Mod metadata parsed: id=%s, name=%s, version=%s",
            metadata.id,
            metadata.name,
            metadata.version,
        )
        if (
            _facade().normalize_artifact({"artifact": metadata.artifact})
            == _facade().ARTIFACT_BUNDLE
        ):
            if registry.get_mod_metadata(mod_id):
                return True
            if registry.register_mod(metadata):
                self._loaded_mods.append(mod_id)
                _facade().logger.info(
                    "[ModManager] Registered bundle metadata only (no backend): %s", mod_id
                )
                return True
            _facade().logger.warning("[ModManager] Bundle %s register_mod returned False", mod_id)
            return True
        deps = registry.list_mod_ids()
        _facade().logger.info("[ModManager] Current loaded mods for dependency check: %s", deps)
        if not _facade().validate_dependencies(metadata, deps):
            _facade().logger.warning("[ModManager] Dependencies not satisfied for mod: %s", mod_id)
            self._record_load_failure(
                mod_id,
                "dependencies",
                "依赖未满足（需先加载所依赖的 mod，或检查 manifest dependencies）",
            )
            return False
        try:
            effective_id = (metadata.id or mod_id).strip()
            self._load_mod_backend(effective_id, mod_path, metadata)
            registry.register_mod(metadata)
            from app.infrastructure.mods.install_receipts import mark_runtime_loaded

            mark_runtime_loaded(effective_id, mods_root=self.mods_root)
            if effective_id not in self._loaded_mods:
                self._loaded_mods.append(effective_id)
            _facade().logger.info(
                "[ModManager] Mod loaded successfully: %s%s",
                effective_id,
                f" (requested {mod_id})" if effective_id != mod_id else "",
            )
            return True
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.error(
                "[ModManager] Failed to load mod %s: %s", mod_id, e, exc_info=True
            )
            self._record_load_failure(mod_id, "backend", _facade()._short_exc_message(e))
            return False
