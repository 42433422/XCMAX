"""Resolve the repository root that directly contains the yuangon directory."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def resolve_yuangon_repo_root(
    repo_root: Path | str,
    *,
    extra_roots: Iterable[Path | str] = (),
) -> Path:
    """Return a root whose direct child is ``yuangon``.

    Local XCMAX checkouts use an outer Git root with the MODstore sources under
    ``成都修茈科技有限公司/``. Production and older checkouts may place
    ``yuangon`` directly beside ``MODstore_deploy``. Support both layouts while
    keeping the supplied root as the fallback so callers retain a useful error
    path when no employee source is present.
    """

    root = Path(repo_root).expanduser().resolve()
    base_roots = [
        Path(value).expanduser().resolve()
        for value in extra_roots
        if str(value or "").strip()
    ]
    base_roots.append(root)

    candidates: list[Path] = []
    for base_root in base_roots:
        candidates.append(base_root)
        if base_root.name == "MODstore_deploy":
            candidates.append(base_root.parent)
        candidates.append(base_root / "成都修茈科技有限公司")

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "yuangon").is_dir():
            return candidate

    for base_root in base_roots:
        try:
            children = sorted(path for path in base_root.iterdir() if path.is_dir())
        except OSError:
            children = []
        structural_matches = [
            child
            for child in children
            if (child / "yuangon").is_dir()
            and (child / "MODstore_deploy" / "modstore_server").is_dir()
        ]
        if len(structural_matches) == 1:
            return structural_matches[0].resolve()
    return root


__all__ = ["resolve_yuangon_repo_root"]
