"""Excel ETL Profile：通用工具 + 知识库，不依赖仓库内置送货单 YAML。

来源优先级：
1. 显式 profile 对象 / profile_id（含 knowledge:* 记忆条目）
2. ``FHD_EXCEL_ETL_PROFILE_DIR`` 用户自定义 YAML（可选）
3. 知识库生成的 ``universal`` 通用 profile（默认）

仓库 ``resources/config/shipment_etl/profiles`` 仅当
``FHD_EXCEL_ETL_ALLOW_BUILTIN=1`` 时才加载（默认关闭）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.application.excel_etl_kb import get_excel_etl_kb

_BUILTIN_DIR = (
    Path(__file__).resolve().parents[2] / "resources" / "config" / "shipment_etl" / "examples"
)
_DEFAULT_PROFILE_ID = "universal"


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
    label: str
    target: str
    raw: dict[str, Any]
    meta_patterns: CompiledMetaPatterns
    detect: dict[str, Any]
    header_detect: dict[str, Any]
    columns: dict[str, list[dict[str, Any]]]
    ledger: dict[str, Any]
    write: dict[str, Any]

    @property
    def delivery_min_score(self) -> int:
        primary = self.detect.get("delivery") or self.detect.get("primary") or {}
        return int(primary.get("min_score") or 40)

    @property
    def has_ledger(self) -> bool:
        return bool(self.detect.get("ledger"))


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
        return _compile(r"(?!)", path)
    joined = "|".join(f"(?:{p})" for p in parts)
    return _compile(joined, path)


def _default_meta_from_kb() -> dict[str, str]:
    kb = get_excel_etl_kb()
    labels = kb.meta_labels()
    unit_alts = "|".join(re.escape(x) for x in (labels.get("unit_name") or ["客户"]) if x)
    contact_alts = "|".join(re.escape(x) for x in (labels.get("contact_person") or ["联系人"]) if x)
    date_alts = "|".join(re.escape(x) for x in (labels.get("order_date") or ["日期"]) if x)
    order_alts = "|".join(re.escape(x) for x in (labels.get("order_number") or ["单号"]) if x)
    unit_label = (labels.get("unit_name") or ["客户"])[0]
    stop = rf"{contact_alts}|{date_alts}|{order_alts}"
    return {
        # 禁止 [^)）]* 跨过首个字段值（会吞掉整行只剩末尾字符）
        "buyer_pattern": rf"(?:{unit_alts})[（(]?[^)）:：]*[)）]?[：:\s]+([^\s]+?)(?=\s*(?:{stop})|$)",
        "buyer_split_pattern": rf"(?:{unit_alts})[（(]?[^)）:：]*[)）]?[：:]",
        "buyer_stop_pattern": stop,
        "buyer_label": unit_label,
        "contact_pattern": rf"(?:{contact_alts})[：:\s]*([^\s]+?)(?=\s*(?:{date_alts}|{order_alts})|$)",
        "date_pattern": (
            r"((?:20)?\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}[-/]\d{1,2}[-/]\d{1,2})"
        ),
        "order_no_pattern": rf"(?:{order_alts})[：:\s]*([A-Za-z0-9\-]+)",
        "stop_row_pattern": r"合计|总计|小计|备注说明|grand\s*total|total",
    }


def parse_profile_dict(data: dict[str, Any], *, source: str = "<dict>") -> ShipmentEtlProfile:
    if not isinstance(data, dict):
        raise ShipmentEtlProfileError(f"{source}: root must be a mapping")
    profile_id = str(_require(data, "id", source)).strip()
    if not profile_id:
        raise ShipmentEtlProfileError(f"{source}.id must be non-empty")
    kind = str(data.get("kind") or "document").strip() or "document"
    label = str(data.get("label") or profile_id).strip() or profile_id
    target = str(data.get("target") or "preview_only").strip() or "preview_only"

    detect = _as_dict(_require(data, "detect", source), f"{source}.detect")
    if "delivery" not in detect and "primary" in detect:
        detect = {**detect, "delivery": detect.get("primary")}
    delivery = _as_dict(_require(detect, "delivery", f"{source}.detect"), f"{source}.detect.delivery")

    ledger_raw = detect.get("ledger")
    if ledger_raw is None:
        ledger_detect: dict[str, Any] = {"sheet_name_pattern": "(?!)"}
    else:
        ledger_detect = _as_dict(ledger_raw, f"{source}.detect.ledger")

    meta_defaults = _default_meta_from_kb()
    meta_in = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    meta = {**meta_defaults, **(meta_in or {})}

    header_detect_default = {
        "delivery": {
            "max_scan_rows": 20,
            "require_groups": [
                ["型号", "编号", "sku", "货号", "model"],
                ["名称", "品名", "name", "产品"],
                ["数量", "qty", "箱数", "件数"],
            ],
        }
    }
    header_detect = _as_dict(
        data.get("header_detect")
        if isinstance(data.get("header_detect"), dict)
        else header_detect_default,
        f"{source}.header_detect",
    )
    if "delivery" not in header_detect and "primary" in header_detect:
        header_detect = {**header_detect, "delivery": header_detect.get("primary")}

    columns_raw = _as_dict(_require(data, "columns", source), f"{source}.columns")
    ledger = _as_dict(data.get("ledger") or {}, f"{source}.ledger")
    write = _as_dict(data.get("write") if isinstance(data.get("write"), dict) else {}, f"{source}.write")

    title_patterns = _as_list(delivery.get("title_patterns") or [], f"{source}.detect.delivery.title_patterns")
    meta_patterns = CompiledMetaPatterns(
        title=_compile_title_patterns(title_patterns, f"{source}.detect.delivery.title_patterns"),
        buyer=_compile(
            str(meta["buyer_pattern"]),
            f"{source}.meta.buyer_pattern",
            flags=re.UNICODE | re.IGNORECASE,
        ),
        buyer_split=_compile(
            str(meta["buyer_split_pattern"]),
            f"{source}.meta.buyer_split_pattern",
            flags=re.IGNORECASE,
        ),
        buyer_stop=_compile(
            str(meta["buyer_stop_pattern"]),
            f"{source}.meta.buyer_stop_pattern",
            flags=re.IGNORECASE,
        ),
        contact=_compile(
            str(meta["contact_pattern"]),
            f"{source}.meta.contact_pattern",
            flags=re.UNICODE | re.IGNORECASE,
        ),
        date=_compile(str(meta["date_pattern"]), f"{source}.meta.date_pattern"),
        order_no=_compile(
            str(meta["order_no_pattern"]),
            f"{source}.meta.order_no_pattern",
            flags=re.IGNORECASE,
        ),
        stop_row=_compile(str(meta["stop_row_pattern"]), f"{source}.meta.stop_row_pattern"),
        buyer_label=str(meta.get("buyer_label") or "客户"),
        ledger_sheet=_compile(
            str(ledger_detect.get("sheet_name_pattern") or "(?!)"),
            f"{source}.detect.ledger.sheet_name_pattern",
            flags=re.IGNORECASE,
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
        label=label,
        target=target,
        raw=data,
        meta_patterns=meta_patterns,
        detect=detect,
        header_detect=header_detect,
        columns=columns,
        ledger=ledger,
        write=write,
    )


def build_universal_profile_from_kb() -> ShipmentEtlProfile:
    from app.application.shipment_etl_profile_universal import (
        build_universal_profile_from_kb as _build,
    )

    return _build()




def profile_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    for env_key in ("FHD_EXCEL_ETL_PROFILE_DIR", "FHD_SHIPMENT_ETL_PROFILE_DIR"):
        override = str(os.environ.get(env_key) or "").strip()
        if override:
            dirs.append(Path(override).expanduser().resolve())
    allow_builtin = str(os.environ.get("FHD_EXCEL_ETL_ALLOW_BUILTIN") or "").strip().lower()
    if allow_builtin in {"1", "true", "yes", "on"}:
        dirs.append(_BUILTIN_DIR.resolve())
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
        pid = str(data.get("id") or "").strip()
        if pid:
            index[pid] = path
    return index


def _dir_cache_key() -> str:
    return "|".join(
        [
            str(os.environ.get("FHD_EXCEL_ETL_PROFILE_DIR") or "").strip(),
            str(os.environ.get("FHD_SHIPMENT_ETL_PROFILE_DIR") or "").strip(),
            str(os.environ.get("FHD_EXCEL_ETL_ALLOW_BUILTIN") or "").strip(),
            str(os.environ.get("FHD_EXCEL_ETL_KB_PATH") or "").strip(),
        ]
    )


@lru_cache(maxsize=32)
def _cached_load(profile_id: str, dir_key: str) -> ShipmentEtlProfile:
    _ = dir_key
    if profile_id in {"universal", "default", "auto"}:
        # default/auto → 通用知识库 profile（不再绑送货单 YAML）
        return build_universal_profile_from_kb()
    if profile_id.startswith("knowledge:"):
        fp = profile_id.split(":", 1)[1]
        mem = get_excel_etl_kb().lookup(fp)
        if mem is None:
            raise ShipmentEtlProfileError(f"unknown knowledge template: {fp}")
        return _profile_from_memory(mem)
    index = _index_profiles()
    path = index.get(profile_id)
    if path is None:
        available = ", ".join(sorted(set(index) | {"universal"})) or "universal"
        raise ShipmentEtlProfileError(
            f"unknown excel etl profile_id={profile_id!r}; available: {available}"
        )
    return load_profile_from_path(path)


def _profile_from_memory(mem: Any) -> ShipmentEtlProfile:
    base = build_universal_profile_from_kb()
    write = dict(base.write)
    write.update(dict(mem.write or {}))
    # keep universal detect/columns; memory used at parse-time for concrete mapping
    return ShipmentEtlProfile(
        id=f"knowledge:{mem.fingerprint}",
        kind="learned_template",
        label=str(mem.label or f"learned:{mem.fingerprint[:8]}"),
        target=str(mem.target or "preview_only"),
        raw={"id": f"knowledge:{mem.fingerprint}", "memory": mem.to_dict()},
        meta_patterns=base.meta_patterns,
        detect=base.detect,
        header_detect=base.header_detect,
        columns=base.columns,
        ledger=base.ledger,
        write=write,
    )


@lru_cache(maxsize=8)
def _cached_all(dir_key: str) -> tuple[ShipmentEtlProfile, ...]:
    _ = dir_key
    out: list[ShipmentEtlProfile] = [build_universal_profile_from_kb()]
    seen = {"universal"}
    for path in _iter_profile_files():
        try:
            prof = load_profile_from_path(path)
        except ShipmentEtlProfileError:
            continue
        if prof.id in seen:
            continue
        seen.add(prof.id)
        out.append(prof)
    return tuple(out)


def clear_profile_cache() -> None:
    _cached_load.cache_clear()
    _cached_all.cache_clear()


def resolve_profile_id(explicit: str | None = None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    for env_key in ("FHD_EXCEL_ETL_PROFILE", "FHD_SHIPMENT_ETL_PROFILE"):
        env = str(os.environ.get(env_key) or "").strip()
        if env:
            return env
    return _DEFAULT_PROFILE_ID


def get_shipment_etl_profile(profile_id: str | None = None) -> ShipmentEtlProfile:
    pid = resolve_profile_id(profile_id)
    if pid.lower() in {"auto", "*"}:
        return build_universal_profile_from_kb()
    return _cached_load(pid, _dir_cache_key())


def load_all_profiles() -> list[ShipmentEtlProfile]:
    return list(_cached_all(_dir_cache_key()))


def list_profiles() -> list[dict[str, Any]]:
    rows = [
        {
            "id": p.id,
            "kind": p.kind,
            "label": p.label,
            "target": p.target,
            "has_ledger": p.has_ledger,
            "min_score": p.delivery_min_score,
            "source": "yaml" if p.id != "universal" else "knowledge_base",
        }
        for p in load_all_profiles()
    ]
    for mem in get_excel_etl_kb().list_templates():
        rows.append(
            {
                "id": f"knowledge:{mem.fingerprint}",
                "kind": "learned_template",
                "label": mem.label or mem.fingerprint,
                "target": mem.target,
                "has_ledger": False,
                "min_score": 0,
                "source": "knowledge_base",
                "hit_count": mem.hit_count,
            }
        )
    return rows


def column_rule_matches(key: str, rule: dict[str, Any]) -> bool:
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
        return any(tok.lower() in key for tok in tokens if tok)
    if "contains_all_groups" in rule:
        groups = rule.get("contains_all_groups") or []
        if not isinstance(groups, list) or not groups:
            return False
        for group in groups:
            options = [str(x) for x in (group or [])]
            if not any(tok.lower() in key for tok in options if tok):
                return False
        return True
    return False


def header_groups_match(compact: str, groups: list[Any]) -> bool:
    low = compact.lower()
    for group in groups or []:
        options = [str(x) for x in (group or [])]
        if not any(tok.lower() in low for tok in options if tok):
            return False
    return True


__all__ = [
    "ShipmentEtlProfile",
    "ShipmentEtlProfileError",
    "CompiledMetaPatterns",
    "build_universal_profile_from_kb",
    "clear_profile_cache",
    "column_rule_matches",
    "get_shipment_etl_profile",
    "header_groups_match",
    "list_profiles",
    "load_all_profiles",
    "load_profile_from_path",
    "parse_profile_dict",
    "profile_search_dirs",
    "resolve_profile_id",
]
