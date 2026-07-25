"""送货单 ETL 版式 Profile：YAML 加载 / 校验 / 编译正则。

版式字符串（表头别名、识别 token、写出模板）只来自 profile，
引擎不硬编码行业版式。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_BUILTIN_DIR = Path(__file__).resolve().parents[2] / "resources" / "config" / "shipment_etl" / "profiles"
_DEFAULT_PROFILE_ID = "default"


class ShipmentEtlProfileError(ValueError):
    """Profile 缺失或非法。"""


@dataclass(frozen=True)
class CompiledMetaPatterns:
    title: re.Pattern[str]
    buyer: re.Pattern[str]
    buyer_split: re.Pattern[str]
    buyer_stop: re.Pattern[str]
    contact: re.Pattern[str]
    date: re.Pattern[str]
    order_no: re.Pattern[str]
    stop_row: re.Pattern[str]
    buyer_label: str
    ledger_sheet: re.Pattern[str]


@dataclass
class ShipmentEtlProfile:
    id: str
    kind: str
    raw: dict[str, Any]
    meta_patterns: CompiledMetaPatterns
    detect: dict[str, Any]
    header_detect: dict[str, Any]
    columns: dict[str, list[dict[str, Any]]]
    ledger: dict[str, Any]
    write: dict[str, Any]

    @property
    def delivery_min_score(self) -> int:
        return int((self.detect.get("delivery") or {}).get("min_score") or 60)


def _require(mapping: dict[str, Any], key: str, path: str) -> Any:
    if key not in mapping:
        raise ShipmentEtlProfileError(f"missing required field: {path}.{key}")
    return mapping[key]


def _as_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ShipmentEtlProfileError(f"{path} must be a mapping")
    return value


def _as_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ShipmentEtlProfileError(f"{path} must be a list")
    return value


def _compile(pattern: str, path: str, *, flags: int = 0) -> re.Pattern[str]:
    try:
        return re.compile(str(pattern), flags)
    except re.error as exc:
        raise ShipmentEtlProfileError(f"invalid regex at {path}: {exc}") from exc


def _compile_title_patterns(patterns: list[Any], path: str) -> re.Pattern[str]:
    parts = [str(p) for p in patterns if str(p).strip()]
    if not parts:
        raise ShipmentEtlProfileError(f"{path} must contain at least one pattern")
    joined = "|".join(f"(?:{p})" for p in parts)
    return _compile(joined, path)


def parse_profile_dict(data: dict[str, Any], *, source: str = "<dict>") -> ShipmentEtlProfile:
    if not isinstance(data, dict):
        raise ShipmentEtlProfileError(f"{source}: root must be a mapping")
    profile_id = str(_require(data, "id", source)).strip()
    if not profile_id:
        raise ShipmentEtlProfileError(f"{source}.id must be non-empty")
    kind = str(data.get("kind") or "delivery_note").strip() or "delivery_note"
    detect = _as_dict(_require(data, "detect", source), f"{source}.detect")
    delivery = _as_dict(_require(detect, "delivery", f"{source}.detect"), f"{source}.detect.delivery")
    ledger_detect = _as_dict(_require(detect, "ledger", f"{source}.detect"), f"{source}.detect.ledger")
    meta = _as_dict(_require(data, "meta", source), f"{source}.meta")
    header_detect = _as_dict(_require(data, "header_detect", source), f"{source}.header_detect")
    columns_raw = _as_dict(_require(data, "columns", source), f"{source}.columns")
    ledger = _as_dict(data.get("ledger") or {}, f"{source}.ledger")
    write = _as_dict(_require(data, "write", source), f"{source}.write")

    title_patterns = _as_list(
        _require(delivery, "title_patterns", f"{source}.detect.delivery"),
        f"{source}.detect.delivery.title_patterns",
    )
    meta_patterns = CompiledMetaPatterns(
        title=_compile_title_patterns(title_patterns, f"{source}.detect.delivery.title_patterns"),
        buyer=_compile(
            str(_require(meta, "buyer_pattern", f"{source}.meta")),
            f"{source}.meta.buyer_pattern",
            flags=re.UNICODE,
        ),
        buyer_split=_compile(
            str(_require(meta, "buyer_split_pattern", f"{source}.meta")),
            f"{source}.meta.buyer_split_pattern",
        ),
        buyer_stop=_compile(
            str(_require(meta, "buyer_stop_pattern", f"{source}.meta")),
            f"{source}.meta.buyer_stop_pattern",
        ),
        contact=_compile(
            str(_require(meta, "contact_pattern", f"{source}.meta")),
            f"{source}.meta.contact_pattern",
        ),
        date=_compile(
            str(_require(meta, "date_pattern", f"{source}.meta")),
            f"{source}.meta.date_pattern",
        ),
        order_no=_compile(
            str(_require(meta, "order_no_pattern", f"{source}.meta")),
            f"{source}.meta.order_no_pattern",
        ),
        stop_row=_compile(
            str(_require(meta, "stop_row_pattern", f"{source}.meta")),
            f"{source}.meta.stop_row_pattern",
        ),
        buyer_label=str(_require(meta, "buyer_label", f"{source}.meta")),
        ledger_sheet=_compile(
            str(_require(ledger_detect, "sheet_name_pattern", f"{source}.detect.ledger")),
            f"{source}.detect.ledger.sheet_name_pattern",
        ),
    )

    columns: dict[str, list[dict[str, Any]]] = {}
    for field_name, rules in columns_raw.items():
        rule_list = _as_list(rules, f"{source}.columns.{field_name}")
        normalized: list[dict[str, Any]] = []
        for idx, rule in enumerate(rule_list):
            rule_dict = _as_dict(rule, f"{source}.columns.{field_name}[{idx}]")
            normalized.append(dict(rule_dict))
        columns[str(field_name)] = normalized

    return ShipmentEtlProfile(
        id=profile_id,
        kind=kind,
        raw=data,
        meta_patterns=meta_patterns,
        detect=detect,
        header_detect=header_detect,
        columns=columns,
        ledger=ledger,
        write=write,
    )


def profile_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    override = str(os.environ.get("FHD_SHIPMENT_ETL_PROFILE_DIR") or "").strip()
    if override:
        dirs.append(Path(override).expanduser().resolve())
    dirs.append(_BUILTIN_DIR.resolve())
    # de-dupe
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = str(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _iter_profile_files(directories: list[Path] | None = None) -> list[Path]:
    files: list[Path] = []
    for d in directories or profile_search_dirs():
        if not d.is_dir():
            continue
        files.extend(sorted(d.glob("*.yaml")))
        files.extend(sorted(d.glob("*.yml")))
    return files


def load_profile_from_path(path: str | Path) -> ShipmentEtlProfile:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ShipmentEtlProfileError(f"profile file not found: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ShipmentEtlProfileError(f"invalid YAML {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ShipmentEtlProfileError(f"{p}: root must be a mapping")
    return parse_profile_dict(data, source=str(p))


def _index_profiles() -> dict[str, Path]:
    """id / stem → 文件路径；靠前目录优先。"""
    index: dict[str, Path] = {}
    for path in reversed(_iter_profile_files()):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        stem = path.stem
        index[stem] = path
        # default_delivery.yaml → also register as "default" via id
        pid = str(data.get("id") or "").strip()
        if pid:
            index[pid] = path
        # common alias
        if stem in {"default_delivery", "default-delivery"} and "default" not in index:
            index["default"] = path
    return index


@lru_cache(maxsize=16)
def _cached_load(profile_id: str, dir_key: str) -> ShipmentEtlProfile:
    _ = dir_key  # cache bust when PROFILE_DIR changes
    index = _index_profiles()
    path = index.get(profile_id)
    if path is None:
        available = ", ".join(sorted(index)) or "(none)"
        raise ShipmentEtlProfileError(
            f"unknown shipment etl profile_id={profile_id!r}; available: {available}"
        )
    return load_profile_from_path(path)


def clear_profile_cache() -> None:
    _cached_load.cache_clear()


def resolve_profile_id(explicit: str | None = None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    env = str(os.environ.get("FHD_SHIPMENT_ETL_PROFILE") or "").strip()
    if env:
        return env
    return _DEFAULT_PROFILE_ID


def get_shipment_etl_profile(profile_id: str | None = None) -> ShipmentEtlProfile:
    pid = resolve_profile_id(profile_id)
    dir_key = str(os.environ.get("FHD_SHIPMENT_ETL_PROFILE_DIR") or "").strip()
    return _cached_load(pid, dir_key)


def column_rule_matches(key: str, rule: dict[str, Any]) -> bool:
    """表头规范化 key 是否命中一条 column rule。"""
    if not key:
        return False
    exclude = [str(x) for x in (rule.get("exclude_any") or [])]
    if any(tok in key for tok in exclude if tok):
        return False

    if "exact" in rule:
        exacts = {str(x) for x in (rule.get("exact") or [])}
        return key in exacts

    if "contains_any" in rule:
        tokens = [str(x) for x in (rule.get("contains_any") or [])]
        return any(tok in key for tok in tokens if tok)

    if "contains_all_groups" in rule:
        groups = rule.get("contains_all_groups") or []
        if not isinstance(groups, list) or not groups:
            return False
        for group in groups:
            options = [str(x) for x in (group or [])]
            if not any(tok in key for tok in options if tok):
                return False
        return True

    return False


def header_groups_match(compact: str, groups: list[Any]) -> bool:
    """每一组至少一个 token 命中。"""
    for group in groups or []:
        options = [str(x) for x in (group or [])]
        if not any(tok in compact for tok in options if tok):
            return False
    return True


__all__ = [
    "ShipmentEtlProfile",
    "ShipmentEtlProfileError",
    "CompiledMetaPatterns",
    "clear_profile_cache",
    "column_rule_matches",
    "get_shipment_etl_profile",
    "header_groups_match",
    "load_profile_from_path",
    "parse_profile_dict",
    "profile_search_dirs",
    "resolve_profile_id",
]
