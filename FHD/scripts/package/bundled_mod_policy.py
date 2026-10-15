"""Standard installers may contain only explicitly staged, non-private Mods."""

import json
from pathlib import Path


def validated_staged_mods(raw_path: str) -> Path:
    if not raw_path or not Path(raw_path).is_dir():
        raise ValueError("XCAGI_STAGED_MODS_DIR is required; do not bundle the marketplace tree")
    root = Path(raw_path).resolve()
    for manifest_path in root.rglob("manifest.json"):
        if manifest_path.is_symlink():
            raise ValueError("bundled manifest must not be a symlink")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError(f"invalid bundled manifest: {manifest_path}")
        if manifest.get("scope") in {"account", "private", "customer"}:
            raise ValueError(
                f"private Mod cannot be bundled in the standard host: {manifest.get('id')}"
            )
    return root
