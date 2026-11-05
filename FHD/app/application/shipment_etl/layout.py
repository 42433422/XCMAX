"""Pure worksheet header mapping, role classification and profile scoring."""

from __future__ import annotations

import os
import re
from typing import Any

from app.application.shipment_etl_profile import (
    ShipmentEtlProfile,
    column_rule_matches,
    header_groups_match,
)


def _norm_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u3000", " ").strip()
    return re.sub("\\s+", "", text)


def _norm_header(value: Any) -> str:
    return _norm_cell(value).lower()


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(_to_float(value, float(default))))
    except (TypeError, ValueError):
        return default


def _row_texts(ws, row: int, max_col: int = 16) -> list[str]:
    out: list[str] = []
    for col in range(1, max_col + 1):
        raw = ws.cell(row, col).value
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            out.append(text)
    return out


def _joined_row(ws, row: int, max_col: int = 16) -> str:
    return " ".join(_row_texts(ws, row, max_col))


def _token_in_compact(token: str, compact: str) -> bool:
    """忽略斜杠差异的包含匹配。"""
    t = str(token or "")
    if not t:
        return False
    if t in compact:
        return True
    return t.replace("/", "") in compact.replace("/", "").lower() or t.lower() in compact.lower()


def _header_cell_texts(ws, header_row: int, max_col: int = 16) -> list[str]:
    out: list[str] = []
    for col in range(1, min(max_col, int(ws.max_column or 0) or max_col) + 1):
        raw = ws.cell(header_row, col).value
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            out.append(text)
    return out


def _sample_values(ws, header_row: int, col: int, *, limit: int = 5) -> list[str]:
    out: list[str] = []
    for row in range(header_row + 1, min(header_row + 8, int(ws.max_row or 0) + 1)):
        raw = ws.cell(row, col).value
        if raw is None or str(raw).strip() == "":
            continue
        out.append(str(raw).strip())
        if len(out) >= limit:
            break
    return out


def _pick_best_profile_for_sheet(
    ws, profiles: list[ShipmentEtlProfile]
) -> tuple[ShipmentEtlProfile, int, int, str]:
    """返回 (profile, delivery_score, ledger_score, prefer_kind)."""
    best: tuple[ShipmentEtlProfile, int, int, str] | None = None
    best_score = -1
    for prof in profiles:
        d = _score_delivery_sheet(ws, prof)
        l = _score_ledger_sheet(ws, prof) if prof.has_ledger else 0
        if d >= l and d > best_score:
            best = (prof, d, l, "delivery_note")
            best_score = d
        elif l > best_score:
            best = (prof, d, l, "shipment_ledger")
            best_score = l
    if best is None:
        fallback = profiles[0]
        return (fallback, 0, 0, "delivery_note")
    return best


def _score_delivery_sheet(ws, profile: ShipmentEtlProfile) -> int:
    """内容指纹打分：规则来自 profile.detect.delivery。"""
    cfg = profile.detect.get("delivery") or {}
    probe_n = int(cfg.get("probe_rows") or 8)
    probe_rows = min(probe_n, int(ws.max_row or 0))
    blob = " ".join(_joined_row(ws, r) for r in range(1, probe_rows + 1))
    compact = _norm_cell(blob)
    score = 0
    if profile.meta_patterns.title.search(blob):
        score += int(cfg.get("title_weight") or 50)
    buyer_token = str(cfg.get("buyer_token") or "")
    if buyer_token and buyer_token in compact:
        score += int(cfg.get("buyer_weight") or 25)
    header_hits = 0
    for token in cfg.get("header_hit_tokens") or []:
        if _token_in_compact(str(token), compact):
            header_hits += 1
    score += min(header_hits, int(cfg.get("header_hit_cap") or 5)) * int(
        cfg.get("header_hit_weight") or 6
    )
    for bonus in cfg.get("bonus_tokens") or []:
        if not isinstance(bonus, dict):
            continue
        tok = str(bonus.get("token") or "")
        if tok and tok in compact:
            score += int(bonus.get("weight") or 0)
    return score


def _score_ledger_sheet(ws, profile: ShipmentEtlProfile) -> int:
    """出货流水打分：规则来自 profile.detect.ledger。"""
    cfg = profile.detect.get("ledger") or {}
    suppress_at = int(cfg.get("suppress_if_delivery_score_gte") or 60)
    if _score_delivery_sheet(ws, profile) >= suppress_at:
        return 0
    probe_n = int(cfg.get("probe_rows") or 10)
    probe_rows = min(probe_n, int(ws.max_row or 0))
    blob = " ".join(_joined_row(ws, r) for r in range(1, probe_rows + 1))
    compact = _norm_cell(blob)
    compact_l = compact.lower()
    score = 0
    sheet_hit = bool(profile.meta_patterns.ledger_sheet.search(str(ws.title or "")))
    content_tokens = [str(t) for t in cfg.get("content_tokens") or []]
    if sheet_hit or any(t.lower() in compact_l for t in content_tokens if t):
        score += int(cfg.get("sheet_weight") or 20)
    hits = 0
    for token in cfg.get("hit_tokens") or []:
        tok = str(token)
        if tok and (tok in compact or tok.lower() in compact_l):
            hits += 1
    score += min(hits, int(cfg.get("hit_cap") or 6)) * int(cfg.get("hit_weight") or 10)
    bonus_req = str(cfg.get("bonus_require_token") or "")
    bonus_exc = str(cfg.get("bonus_exclude_token") or "")
    if bonus_req and bonus_req in compact and (not bonus_exc or bonus_exc not in compact):
        score += int(cfg.get("bonus_weight") or 0)
    header_row = _find_ledger_header_row(ws, profile)
    if header_row is not None:
        mapping = _map_headers(ws, header_row, profile)
        if "order_number" in mapping and "客户" not in compact and ("购货单位" not in compact):
            score += 25
    return score


def _find_header_row(ws, profile: ShipmentEtlProfile) -> int | None:
    cfg = profile.header_detect.get("delivery") or {}
    max_scan = int(cfg.get("max_scan_rows") or 12)
    groups = cfg.get("require_groups") or []
    for row in range(1, min(max_scan, int(ws.max_row or 0) + 1)):
        compact = _norm_header(_joined_row(ws, row))
        if header_groups_match(compact, groups):
            return row
    best_row = None
    best_count = 0
    for row in range(1, min(max_scan, int(ws.max_row or 0) + 1)):
        count = 0
        for col in range(1, min(16, int(ws.max_column or 0) or 16) + 1):
            raw = ws.cell(row, col).value
            if raw is not None and str(raw).strip():
                count += 1
        if count >= 3 and count > best_count:
            has_body = False
            for r in range(row + 1, min(row + 4, int(ws.max_row or 0) + 1)):
                if any(
                    ws.cell(r, c).value not in (None, "")
                    for c in range(1, min(8, int(ws.max_column or 0) or 8) + 1)
                ):
                    has_body = True
                    break
            if has_body:
                best_row = row
                best_count = count
    return best_row


def _find_ledger_header_row(ws, profile: ShipmentEtlProfile) -> int | None:
    cfg = profile.header_detect.get("ledger") or {}
    max_scan = int(cfg.get("max_scan_rows") or 16)
    groups = cfg.get("require_groups") or []
    and_any = cfg.get("and_any_groups") or []
    for row in range(1, min(max_scan, int(ws.max_row or 0) + 1)):
        compact = _norm_header(_joined_row(ws, row))
        if not header_groups_match(compact, groups):
            continue
        if and_any:
            if not any(header_groups_match(compact, [g]) for g in and_any):
                continue
        return row
    return None


def _map_headers(ws, header_row: int, profile: ShipmentEtlProfile) -> dict[str, int]:
    mapping: dict[str, int] = {}
    field_order = list(profile.columns.keys())
    for col in range(1, min(16, int(ws.max_column or 0) + 1)):
        key = _norm_header(ws.cell(header_row, col).value)
        if not key:
            continue
        for field_name in field_order:
            if field_name in mapping:
                continue
            for rule in profile.columns.get(field_name) or []:
                only_if_missing = [str(x) for x in rule.get("only_if_missing") or []]
                if only_if_missing and any(f in mapping for f in only_if_missing):
                    continue
                if column_rule_matches(key, rule):
                    mapping[field_name] = col
                    break
    return mapping


def _infer_columns_from_samples(ws, header_row: int, mapping: dict[str, int]) -> dict[str, int]:
    """陌生表头：用样例值类型补列（不编造数值，只猜列位）。"""

    flag = str(os.environ.get("FHD_EXCEL_ETL_HEURISTIC") or "1").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return dict(mapping)
    out = dict(mapping)
    max_col = min(16, int(ws.max_column or 0) or 16)
    candidates: list[tuple[int, list[str], str]] = []
    for col in range(1, max_col + 1):
        if col in out.values():
            continue
        samples = _sample_values(ws, header_row, col)
        if not samples:
            continue
        header = _norm_header(ws.cell(header_row, col).value)
        joined = " ".join(samples)
        kind = "text"
        nums = 0
        for s in samples:
            try:
                float(str(s).replace(",", ""))
                nums += 1
            except ValueError:
                pass
        if nums >= max(1, len(samples) // 2 + 1):
            kind = "number"
        elif re.search("[A-Za-z0-9\\-_/]{2,}", joined) and (
            not re.search("[\\u4e00-\\u9fff]{2,}", joined)
        ):
            kind = "code"
        elif re.search("[\\u4e00-\\u9fff]", joined):
            kind = "name"
        candidates.append((col, samples, kind if not header else f"{kind}:{header}"))

    def _take(field: str, predicate) -> None:
        if field in out:
            return
        for col, samples, kind in candidates:
            if col in out.values():
                continue
            if predicate(col, samples, kind):
                out[field] = col
                return

    _take(
        "model_number",
        lambda c, s, k: (
            k.startswith("code") or (k.startswith("text") and all(len(x) <= 24 for x in s))
        ),
    )
    _take("product_name", lambda c, s, k: k.startswith("name") or k.startswith("text"))
    num_cols = [c for (c, s, k) in candidates if k.startswith("number") and c not in out.values()]
    for field in ("quantity_tins", "tin_spec", "quantity_kg", "unit_price", "amount"):
        if field in out or not num_cols:
            continue
        out[field] = num_cols.pop(0)
    _take(
        "order_number",
        lambda c, s, k: any(re.search("[A-Za-z].*\\d|\\d.*[A-Za-z]", x) for x in s),
    )
    return out


def _classify_sheet_role(ws, profile: ShipmentEtlProfile, *, d_score: int, l_score: int) -> str:
    """多表混排：给工作表打角色 delivery / ledger / ignore / unknown。"""
    title = str(ws.title or "")
    if re.search("报价|价目|cover|目录|说明|readme", title, re.I):
        if d_score < 24 and l_score < 24:
            return "ignore"
    if profile.has_ledger and l_score >= 40 and (l_score > d_score):
        return "ledger"
    if d_score >= 32:
        return "delivery"
    header = _find_header_row(ws, profile)
    ledger_header = _find_ledger_header_row(ws, profile) if profile.has_ledger else None
    if ledger_header and (header is None or l_score >= d_score):
        mapping = _map_headers(ws, ledger_header, profile)
        if "order_number" in mapping:
            return "ledger"
    if header is not None:
        mapping = _map_headers(ws, header, profile)
        if "product_name" in mapping or "model_number" in mapping:
            return "delivery"
    if d_score < 16 and l_score < 16:
        return "ignore"
    return "unknown"
