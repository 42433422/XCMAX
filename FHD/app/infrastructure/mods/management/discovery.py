"""Discover manifests only in configured roots, with an optional build-index cache."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.utils.operational_errors import RECOVERABLE_ERRORS

from ..manifest import ModMetadata
from .ports import ParseManifest, ScanState, TrustedChild


@dataclass(frozen=True)
class DiscoveryPorts:
    roots: Callable[[], list[str]]
    refresh: Callable[[], None]
    fingerprint: Callable[[], str]
    index: Callable[[str], list[ModMetadata] | None]
    parse: ParseManifest
    child: TrustedChild
    logger: logging.Logger


def _mod_dir_candidates(root: str) -> list[tuple[str, str]]:
    """列出 (entry_name, mod_path)。

    编辑源 ``FHD/mods/`` 按 ``industry/ bridge/ employees/ tools/`` 分层，
    运行时导出目录保持平铺；两种布局都要能发现。
    """
    out: list[tuple[str, str]] = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return out
    for entry in entries:
        if entry.startswith(("_", ".")):
            continue
        mod_path = os.path.join(root, entry)
        if os.path.islink(mod_path) or not os.path.isdir(mod_path):
            continue
        if os.path.isfile(os.path.join(mod_path, "manifest.json")):
            out.append((entry, mod_path))
            continue
        try:
            subs = sorted(os.listdir(mod_path))
        except OSError:
            subs = []
        layered = [
            sub
            for sub in subs
            if not sub.startswith(("_", "."))
            and os.path.isdir(os.path.join(mod_path, sub))
            and os.path.isfile(os.path.join(mod_path, sub, "manifest.json"))
        ]
        if layered:
            out.extend((sub, os.path.join(mod_path, sub)) for sub in layered)
        else:
            # 既非 Mod 也非分层容器：保留原路径，交由解析环节记录告警
            out.append((entry, mod_path))
    return out


class ModDiscovery:
    def __init__(self, state: ScanState, ports: DiscoveryPorts) -> None:
        self._state = state
        self._ports = ports

    def fingerprint(self) -> str:
        parts: list[str] = []
        for root in self._ports.roots():
            parts.append(os.path.abspath(root))
            if not os.path.isdir(root):
                continue
            for entry, mod_path in _mod_dir_candidates(root):
                manifest_path = os.path.join(mod_path, "manifest.json")
                if os.path.isfile(manifest_path):
                    try:
                        parts.append(f"{entry}:{os.path.getmtime(manifest_path):.6f}")
                    except OSError:
                        parts.append(entry)
        return "|".join(parts)

    def resolve_directory(self, mod_id: str) -> str | None:
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
            for root in self._ports.roots():
                mod_path = self._ports.child(root, cid, directory=True)
                if mod_path and self._ports.child(mod_path, "manifest.json", directory=False):
                    return mod_path
                # 分层容器：root/<layer>/<cid>
                for entry, layered_path in _mod_dir_candidates(root):
                    if entry == cid and self._ports.child(
                        layered_path, "manifest.json", directory=False
                    ):
                        return layered_path
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

    def from_index(self, fp: str) -> list[ModMetadata] | None:
        """读取构建时生成的 mods-index.json（指纹一致时）。"""
        import json

        roots = self._ports.roots()
        allowed_roots = {os.path.normcase(os.path.abspath(root)): root for root in roots}
        for root in roots:
            index_path = os.path.join(root, "mods-index.json")
            if not os.path.isfile(index_path):
                continue
            try:
                payload = json.loads(Path(index_path).read_text(encoding="utf-8"))
            except RECOVERABLE_ERRORS:
                continue
            if not isinstance(payload, dict) or str(payload.get("fingerprint") or "") != fp:
                continue
            rows = payload.get("mods")
            if not isinstance(rows, list):
                continue
            mods: list[ModMetadata] = []
            seen: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                mod_path = str(row.get("mod_path") or "").strip()
                if not mod_path:
                    continue
                absolute = os.path.abspath(mod_path)
                entry = os.path.basename(absolute)
                if entry.startswith(("_", ".")):
                    continue
                direct_parent = os.path.dirname(absolute)
                trusted: str | None = None
                if os.path.normcase(direct_parent) in allowed_roots:
                    trusted = self._ports.child(
                        allowed_roots[os.path.normcase(direct_parent)], entry, directory=True
                    )
                else:
                    # 分层：<root>/<layer>/<id>
                    layer_name = os.path.basename(direct_parent)
                    root = allowed_roots.get(os.path.normcase(os.path.dirname(direct_parent)))
                    if root is not None and not layer_name.startswith(("_", ".")):
                        layer = self._ports.child(root, layer_name, directory=True)
                        if layer:
                            trusted = self._ports.child(layer, entry, directory=True)
                if trusted is None or not self._ports.child(
                    trusted, "manifest.json", directory=False
                ):
                    continue
                mod_path = trusted
                metadata = self._ports.parse(mod_path)
                if metadata:
                    from app.mod_sdk.industry_mod_aliases import is_retired_runtime_mod_id

                    if is_retired_runtime_mod_id(metadata.id):
                        continue
                if metadata and metadata.id not in seen:
                    seen.add(metadata.id)
                    mods.append(metadata)
            if mods:
                self._ports.logger.info(
                    "[ModManager] scan_mods via mods-index.json (%s mods)", len(mods)
                )
                return mods
        return None

    def scan(self, *, use_cache: bool = True) -> list[ModMetadata]:
        self._ports.refresh()
        fp = self._ports.fingerprint()
        if use_cache and fp and (fp == self._state._scan_cache_fp) and self._state._scan_cache_mods:
            return list(self._state._scan_cache_mods)
        indexed = self._ports.index(fp) if use_cache else None
        if indexed is not None:
            self._state._scan_cache_fp = fp
            self._state._scan_cache_mods = indexed
            return list(indexed)
        self._ports.logger.debug("[ModManager] Scanning mods roots: %s", self._ports.roots())
        self._state._scan_manifest_errors = []
        mods: list[ModMetadata] = []
        seen_ids: set[str] = set()
        for mods_root in self._ports.roots():
            if not os.path.isdir(mods_root):
                self._ports.logger.warning(
                    "[ModManager] Mods directory does not exist: %s", mods_root
                )
                continue
            for entry, mod_path in _mod_dir_candidates(mods_root):
                if os.path.islink(mod_path) or not os.path.isdir(mod_path):
                    continue
                manifest_path = os.path.join(mod_path, "manifest.json")
                self._ports.logger.debug(
                    "[ModManager] Checking %s/%s, manifest exists: %s",
                    mods_root,
                    entry,
                    os.path.isfile(manifest_path),
                )
                metadata = self._ports.parse(mod_path)
                if metadata:
                    from app.mod_sdk.industry_mod_aliases import is_retired_runtime_mod_id

                    if is_retired_runtime_mod_id(metadata.id):
                        self._ports.logger.info(
                            "[ModManager] Skip retired runtime mod: %s", metadata.id
                        )
                        continue
                    if metadata.id in seen_ids:
                        continue
                    seen_ids.add(metadata.id)
                    mods.append(metadata)
                    self._ports.logger.debug(
                        "[ModManager] Found mod: %s (%s) v%s @ %s",
                        metadata.id,
                        metadata.name,
                        metadata.version,
                        mod_path,
                    )
                else:
                    self._ports.logger.warning(
                        "[ModManager] Failed to parse manifest for mod entry: %s/%s",
                        mods_root,
                        entry,
                    )
                    self._state._scan_manifest_errors.append(
                        {
                            "entry": entry,
                            "mods_root": mods_root,
                            "message": "manifest.json 缺失或无法解析（检查 JSON 与必填字段 id）",
                        }
                    )
        self._ports.logger.info("[ModManager] Total mods found: %s", len(mods))
        self._state._scan_cache_fp = fp
        self._state._scan_cache_mods = mods
        return mods
