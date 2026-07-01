"""Runtime code ownership resolver backed by yuangon employee scopes."""

from __future__ import annotations

import json
import os
import re
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List

from modstore_server.yuangon_paths import resolve_yuangon_repo_root

_PATH_KEYS = {
    "affected_files",
    "changed_files",
    "changed_paths",
    "file",
    "file_path",
    "file_paths",
    "files",
    "files_hint",
    "modified_files",
    "path",
    "paths",
}
_PATH_RE = re.compile(
    r"(?:(?:成都修茈科技有限公司/)?(?:MODstore_deploy|FHD|yuangon|packages)/"
    r"[^\s,;，；。)）\]}】'\"`<>]+)"
)
_ANCHORS = (
    "MODstore_deploy/",
    "FHD/",
    "yuangon/",
    "packages/",
)


def _repo_root() -> Path:
    env = (os.environ.get("MODSTORE_REPO_ROOT") or "").strip()
    if env:
        return resolve_yuangon_repo_root(env)
    return resolve_yuangon_repo_root(Path(__file__).resolve().parents[1])


def _routing_table_path() -> Path:
    override = (os.environ.get("MODSTORE_CODE_OWNERSHIP_TABLE") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent / "data" / "routing_table.json"


def _normalize_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    text = text.strip("'\"`<>")
    for anchor in _ANCHORS:
        idx = text.find(anchor)
        if idx >= 0:
            return text[idx:].lstrip("./")
    if text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def _iter_path_values(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, inner in value.items():
            key_s = str(key or "").strip().lower()
            if key_s in _PATH_KEYS:
                yield from _iter_path_values(inner)
            elif isinstance(inner, (dict, list, tuple, set)):
                yield from _iter_path_values(inner)
            elif key_s in {"summary", "snippet", "message", "error", "details", "description"}:
                yield from _iter_path_values(str(inner or ""))
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_path_values(item)
        return
    if isinstance(value, str):
        normalized = _normalize_path(value)
        if "/" in normalized and not normalized.startswith("{"):
            yield normalized
        for match in _PATH_RE.findall(value):
            yield _normalize_path(match)


def extract_incident_paths(
    payload: Dict[str, Any], *, source: str = "", event_type: str = ""
) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in (payload or {}, source, event_type):
        for path in _iter_path_values(value):
            if not path or path in seen:
                continue
            seen.add(path)
            out.append(path)
    return out


def _specificity(pattern: str) -> int:
    wildcards = pattern.count("*") + pattern.count("?") + pattern.count("[")
    return max(1, len(pattern.replace("*", "").replace("?", "")) - wildcards * 8)


def _matches(pattern: str, path: str) -> bool:
    pat = _normalize_path(pattern)
    p = _normalize_path(path)
    if not pat or not p:
        return False
    if fnmatchcase(p, pat) or (pat.endswith("/**") and p.startswith(pat[:-3].rstrip("/") + "/")):
        return True
    try:
        return re.match(_glob_to_regex(pat), p) is not None
    except re.error:
        return False


def _glob_to_regex(pattern: str) -> str:
    pat = _normalize_path(pattern)
    out: List[str] = []
    i = 0
    while i < len(pat):
        c = pat[i]
        if pat[i : i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif pat[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c in ".+(){}|^$\\":
            out.append("\\" + c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "^" + "".join(out) + "$"


def _load_from_yuangon() -> List[Dict[str, Any]]:
    try:
        import yaml
    except Exception:
        return []

    root = _repo_root()
    ydir = root / "yuangon"
    if not ydir.is_dir():
        return []
    rows: List[Dict[str, Any]] = []
    for path in sorted(ydir.glob("**/employee.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        eid = str(data.get("id") or "").strip()
        if not eid:
            continue
        rows.append(
            {
                "id": eid,
                "area": str(data.get("area") or "").strip(),
                "scope_globs": [
                    str(item).strip()
                    for item in (data.get("scope_globs") or [])
                    if str(item or "").strip()
                ],
                "forbidden_globs": [
                    str(item).strip()
                    for item in (data.get("forbidden_globs") or [])
                    if str(item or "").strip()
                ],
            }
        )
    return rows


def _load_from_routing_table() -> List[Dict[str, Any]]:
    path = _routing_table_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw.get("employees") if isinstance(raw, dict) else None
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict) and row.get("id")]
    except Exception:
        return []
    return []


@lru_cache(maxsize=1)
def load_code_ownership_table() -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for row in _load_from_routing_table():
        eid = str(row.get("id") or "").strip()
        if eid:
            by_id[eid] = row
    for row in _load_from_yuangon():
        eid = str(row.get("id") or "").strip()
        if eid:
            by_id[eid] = row
    return list(by_id.values())


def resolve_code_owners(paths: Iterable[str], *, limit: int = 8) -> Dict[str, Any]:
    normalized_paths = []
    seen_paths = set()
    for item in paths:
        p = _normalize_path(item)
        if p and p not in seen_paths:
            seen_paths.add(p)
            normalized_paths.append(p)

    scores: Dict[str, Dict[str, Any]] = {}
    for row in load_code_ownership_table():
        eid = str(row.get("id") or "").strip()
        if not eid:
            continue
        scope_globs = [str(x) for x in (row.get("scope_globs") or []) if str(x).strip()]
        forbidden_globs = [str(x) for x in (row.get("forbidden_globs") or []) if str(x).strip()]
        for path in normalized_paths:
            if any(_matches(pattern, path) for pattern in forbidden_globs):
                continue
            matched = [pattern for pattern in scope_globs if _matches(pattern, path)]
            if not matched:
                continue
            best = max(matched, key=_specificity)
            entry = scores.setdefault(
                eid,
                {
                    "area": str(row.get("area") or ""),
                    "employee_id": eid,
                    "match_count": 0,
                    "matched_files": [],
                    "matched_globs": [],
                    "match_score": 0,
                },
            )
            entry["match_count"] += 1
            entry["match_score"] += _specificity(best)
            if path not in entry["matched_files"]:
                entry["matched_files"].append(path)
            if best not in entry["matched_globs"]:
                entry["matched_globs"].append(best)

    owners = sorted(
        scores.values(),
        key=lambda item: (int(item.get("match_score") or 0), int(item.get("match_count") or 0)),
        reverse=True,
    )[: max(1, int(limit or 8))]
    return {
        "files": normalized_paths,
        "owners": owners,
        "owner_ids": [str(item.get("employee_id") or "") for item in owners],
        "matched": bool(owners),
    }


def resolve_incident_ownership(
    payload: Dict[str, Any], *, source: str = "", event_type: str = "", limit: int = 8
) -> Dict[str, Any]:
    paths = extract_incident_paths(payload, source=source, event_type=event_type)
    return resolve_code_owners(paths, limit=limit)


__all__ = [
    "extract_incident_paths",
    "load_code_ownership_table",
    "resolve_code_owners",
    "resolve_incident_ownership",
]
