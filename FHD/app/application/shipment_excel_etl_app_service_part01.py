# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.shipment_excel_etl_app_service')

def _resolve_profile(profile: _facade().ShipmentEtlProfile | None=None, profile_id: str | None=None) -> _facade().ShipmentEtlProfile:
    if profile is not None:
        return profile
    return _facade().get_shipment_etl_profile(profile_id)

def _profiles_for_parse(profile: _facade().ShipmentEtlProfile | None=None, profile_id: str | None=None) -> list[_facade().ShipmentEtlProfile]:
    """解析用 profile 列表：显式指定则单 profile；否则加载全部做竞分。"""
    if profile is not None:
        return [profile]
    raw = str(profile_id or '').strip()
    if not raw:
        import os
        raw = str(os.environ.get('FHD_EXCEL_ETL_PROFILE') or '').strip() or str(os.environ.get('FHD_SHIPMENT_ETL_PROFILE') or '').strip()
    if raw and raw.lower() not in {'auto', '*'}:
        return [_facade().get_shipment_etl_profile(raw)]
    from app.application.shipment_etl_profile import load_all_profiles
    profiles = load_all_profiles()
    return profiles or [_facade().get_shipment_etl_profile('universal')]

def _pick_best_profile_for_sheet(ws, profiles: list[_facade().ShipmentEtlProfile]) -> tuple[_facade().ShipmentEtlProfile, int, int, str]:
    """返回 (profile, delivery_score, ledger_score, prefer_kind)."""
    best: tuple[_facade().ShipmentEtlProfile, int, int, str] | None = None
    best_score = -1
    for prof in profiles:
        d = _facade()._score_delivery_sheet(ws, prof)
        l = _facade()._score_ledger_sheet(ws, prof) if prof.has_ledger else 0
        if d >= l and d > best_score:
            best = (prof, d, l, 'delivery_note')
            best_score = d
        elif l > best_score:
            best = (prof, d, l, 'shipment_ledger')
            best_score = l
    if best is None:
        fallback = profiles[0]
        return (fallback, 0, 0, 'delivery_note')
    return best

def _norm_cell(value: _facade().Any) -> str:
    if value is None:
        return ''
    text = str(value).replace('\u3000', ' ').strip()
    return _facade().re.sub('\\s+', '', text)

def _norm_header(value: _facade().Any) -> str:
    return _facade()._norm_cell(value).lower()

def _to_float(value: _facade().Any, default: float=0.0) -> float:
    if value is None or value == '':
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(',', '')
    try:
        return float(text)
    except ValueError:
        return default

def _to_int(value: _facade().Any, default: int=0) -> int:
    try:
        return int(round(_facade()._to_float(value, float(default))))
    except (TypeError, ValueError):
        return default

def _row_texts(ws, row: int, max_col: int=16) -> list[str]:
    out: list[str] = []
    for col in range(1, max_col + 1):
        raw = ws.cell(row, col).value
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            out.append(text)
    return out

def _joined_row(ws, row: int, max_col: int=16) -> str:
    return ' '.join(_facade()._row_texts(ws, row, max_col))

def _token_in_compact(token: str, compact: str) -> bool:
    """忽略斜杠差异的包含匹配。"""
    t = str(token or '')
    if not t:
        return False
    if t in compact:
        return True
    return t.replace('/', '') in compact.replace('/', '').lower() or t.lower() in compact.lower()

def _header_cell_texts(ws, header_row: int, max_col: int=16) -> list[str]:
    out: list[str] = []
    for col in range(1, min(max_col, int(ws.max_column or 0) or max_col) + 1):
        raw = ws.cell(header_row, col).value
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            out.append(text)
    return out

def _kb_resolve_layout(ws) -> tuple[int | None, dict[str, int], str]:
    """按表头指纹查知识库；命中则返回 (header_row, columns, fingerprint)。"""
    kb = _facade().get_excel_etl_kb()
    max_row = int(ws.max_row or 0)
    max_col = min(16, int(ws.max_column or 0) or 16)
    for row in range(1, min(20, max_row) + 1):
        headers = _facade()._header_cell_texts(ws, row, max_col=max_col)
        if len(headers) < 2:
            continue
        fp = _facade().sheet_layout_fingerprint(sheet_title=str(ws.title or ''), header_cells=headers)
        mem = kb.get_template(fp)
        if mem is None or not mem.columns:
            continue
        if mem.header_row is not None and int(mem.header_row) != row:
            pass
        if 'product_name' not in mem.columns and 'model_number' not in mem.columns:
            continue
        kb.touch(fp)
        return (row, {str(k): int(v) for (k, v) in mem.columns.items()}, fp)
    return (None, {}, '')

def _remember_sheet_layout(ws, *, header_row: int, mapping: dict[str, int], profile: _facade().ShipmentEtlProfile, source: str='learned') -> str:
    """解析成功后把表头映射写入知识库。"""
    if not mapping or header_row is None:
        return ''
    headers = _facade()._header_cell_texts(ws, header_row)
    if len(headers) < 2:
        return ''
    fp = _facade().sheet_layout_fingerprint(sheet_title=str(ws.title or ''), header_cells=headers)
    try:
        _facade().get_excel_etl_kb().remember(_facade().TemplateMemory(fingerprint=fp, label=str(profile.label or profile.id), target=str(profile.target or 'preview_only'), header_row=int(header_row), columns={str(k): int(v) for (k, v) in mapping.items()}, meta={}, write=dict(profile.write or {}), source=source))
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug('excel etl kb remember skipped', exc_info=True)
        return ''
    return fp

def _score_delivery_sheet(ws, profile: _facade().ShipmentEtlProfile) -> int:
    """内容指纹打分：规则来自 profile.detect.delivery。"""
    cfg = profile.detect.get('delivery') or {}
    probe_n = int(cfg.get('probe_rows') or 8)
    probe_rows = min(probe_n, int(ws.max_row or 0))
    blob = ' '.join((_facade()._joined_row(ws, r) for r in range(1, probe_rows + 1)))
    compact = _facade()._norm_cell(blob)
    score = 0
    if profile.meta_patterns.title.search(blob):
        score += int(cfg.get('title_weight') or 50)
    buyer_token = str(cfg.get('buyer_token') or '')
    if buyer_token and buyer_token in compact:
        score += int(cfg.get('buyer_weight') or 25)
    header_hits = 0
    for token in cfg.get('header_hit_tokens') or []:
        if _facade()._token_in_compact(str(token), compact):
            header_hits += 1
    score += min(header_hits, int(cfg.get('header_hit_cap') or 5)) * int(cfg.get('header_hit_weight') or 6)
    for bonus in cfg.get('bonus_tokens') or []:
        if not isinstance(bonus, dict):
            continue
        tok = str(bonus.get('token') or '')
        if tok and tok in compact:
            score += int(bonus.get('weight') or 0)
    return score

def _score_ledger_sheet(ws, profile: _facade().ShipmentEtlProfile) -> int:
    """出货流水打分：规则来自 profile.detect.ledger。"""
    cfg = profile.detect.get('ledger') or {}
    suppress_at = int(cfg.get('suppress_if_delivery_score_gte') or 60)
    if _facade()._score_delivery_sheet(ws, profile) >= suppress_at:
        return 0
    probe_n = int(cfg.get('probe_rows') or 10)
    probe_rows = min(probe_n, int(ws.max_row or 0))
    blob = ' '.join((_facade()._joined_row(ws, r) for r in range(1, probe_rows + 1)))
    compact = _facade()._norm_cell(blob)
    compact_l = compact.lower()
    score = 0
    sheet_hit = bool(profile.meta_patterns.ledger_sheet.search(str(ws.title or '')))
    content_tokens = [str(t) for t in cfg.get('content_tokens') or []]
    if sheet_hit or any((t.lower() in compact_l for t in content_tokens if t)):
        score += int(cfg.get('sheet_weight') or 20)
    hits = 0
    for token in cfg.get('hit_tokens') or []:
        tok = str(token)
        if tok and (tok in compact or tok.lower() in compact_l):
            hits += 1
    score += min(hits, int(cfg.get('hit_cap') or 6)) * int(cfg.get('hit_weight') or 10)
    bonus_req = str(cfg.get('bonus_require_token') or '')
    bonus_exc = str(cfg.get('bonus_exclude_token') or '')
    if bonus_req and bonus_req in compact and (not bonus_exc or bonus_exc not in compact):
        score += int(cfg.get('bonus_weight') or 0)
    header_row = _facade()._find_ledger_header_row(ws, profile)
    if header_row is not None:
        mapping = _facade()._map_headers(ws, header_row, profile)
        if 'order_number' in mapping and '客户' not in compact and ('购货单位' not in compact):
            score += 25
    return score

def _find_header_row(ws, profile: _facade().ShipmentEtlProfile) -> int | None:
    cfg = profile.header_detect.get('delivery') or {}
    max_scan = int(cfg.get('max_scan_rows') or 12)
    groups = cfg.get('require_groups') or []
    for row in range(1, min(max_scan, int(ws.max_row or 0) + 1)):
        compact = _facade()._norm_header(_facade()._joined_row(ws, row))
        if _facade().header_groups_match(compact, groups):
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
                if any((ws.cell(r, c).value not in (None, '') for c in range(1, min(8, int(ws.max_column or 0) or 8) + 1))):
                    has_body = True
                    break
            if has_body:
                best_row = row
                best_count = count
    return best_row

def _find_ledger_header_row(ws, profile: _facade().ShipmentEtlProfile) -> int | None:
    cfg = profile.header_detect.get('ledger') or {}
    max_scan = int(cfg.get('max_scan_rows') or 16)
    groups = cfg.get('require_groups') or []
    and_any = cfg.get('and_any_groups') or []
    for row in range(1, min(max_scan, int(ws.max_row or 0) + 1)):
        compact = _facade()._norm_header(_facade()._joined_row(ws, row))
        if not _facade().header_groups_match(compact, groups):
            continue
        if and_any:
            if not any((_facade().header_groups_match(compact, [g]) for g in and_any)):
                continue
        return row
    return None

def _map_headers(ws, header_row: int, profile: _facade().ShipmentEtlProfile) -> dict[str, int]:
    mapping: dict[str, int] = {}
    field_order = list(profile.columns.keys())
    for col in range(1, min(16, int(ws.max_column or 0) + 1)):
        key = _facade()._norm_header(ws.cell(header_row, col).value)
        if not key:
            continue
        for field_name in field_order:
            if field_name in mapping:
                continue
            for rule in profile.columns.get(field_name) or []:
                only_if_missing = [str(x) for x in rule.get('only_if_missing') or []]
                if only_if_missing and any((f in mapping for f in only_if_missing)):
                    continue
                if _facade().column_rule_matches(key, rule):
                    mapping[field_name] = col
                    break
    return mapping

def _sample_values(ws, header_row: int, col: int, *, limit: int=5) -> list[str]:
    out: list[str] = []
    for row in range(header_row + 1, min(header_row + 8, int(ws.max_row or 0) + 1)):
        raw = ws.cell(row, col).value
        if raw is None or str(raw).strip() == '':
            continue
        out.append(str(raw).strip())
        if len(out) >= limit:
            break
    return out

def _infer_columns_from_samples(ws, header_row: int, mapping: dict[str, int]) -> dict[str, int]:
    """陌生表头：用样例值类型补列（不编造数值，只猜列位）。"""
    import os
    flag = str(os.environ.get('FHD_EXCEL_ETL_HEURISTIC') or '1').strip().lower()
    if flag in {'0', 'false', 'no', 'off'}:
        return dict(mapping)
    out = dict(mapping)
    max_col = min(16, int(ws.max_column or 0) or 16)
    candidates: list[tuple[int, list[str], str]] = []
    for col in range(1, max_col + 1):
        if col in out.values():
            continue
        samples = _facade()._sample_values(ws, header_row, col)
        if not samples:
            continue
        header = _facade()._norm_header(ws.cell(header_row, col).value)
        joined = ' '.join(samples)
        kind = 'text'
        nums = 0
        for s in samples:
            try:
                float(str(s).replace(',', ''))
                nums += 1
            except ValueError:
                pass
        if nums >= max(1, len(samples) // 2 + 1):
            kind = 'number'
        elif _facade().re.search('[A-Za-z0-9\\-_/]{2,}', joined) and (not _facade().re.search('[\\u4e00-\\u9fff]{2,}', joined)):
            kind = 'code'
        elif _facade().re.search('[\\u4e00-\\u9fff]', joined):
            kind = 'name'
        candidates.append((col, samples, kind if not header else f'{kind}:{header}'))

    def _take(field: str, predicate) -> None:
        if field in out:
            return
        for (col, samples, kind) in candidates:
            if col in out.values():
                continue
            if predicate(col, samples, kind):
                out[field] = col
                return
    _take('model_number', lambda c, s, k: k.startswith('code') or (k.startswith('text') and all((len(x) <= 24 for x in s))))
    _take('product_name', lambda c, s, k: k.startswith('name') or k.startswith('text'))
    num_cols = [c for (c, s, k) in candidates if k.startswith('number') and c not in out.values()]
    for field in ('quantity_tins', 'tin_spec', 'quantity_kg', 'unit_price', 'amount'):
        if field in out or not num_cols:
            continue
        out[field] = num_cols.pop(0)
    _take('order_number', lambda c, s, k: any((_facade().re.search('[A-Za-z].*\\d|\\d.*[A-Za-z]', x) for x in s)))
    return out

def _classify_sheet_role(ws, profile: _facade().ShipmentEtlProfile, *, d_score: int, l_score: int) -> str:
    """多表混排：给工作表打角色 delivery / ledger / ignore / unknown。"""
    title = str(ws.title or '')
    if _facade().re.search('报价|价目|cover|目录|说明|readme', title, _facade().re.I):
        if d_score < 24 and l_score < 24:
            return 'ignore'
    if profile.has_ledger and l_score >= 40 and (l_score > d_score):
        return 'ledger'
    if d_score >= 32:
        return 'delivery'
    header = _facade()._find_header_row(ws, profile)
    ledger_header = _facade()._find_ledger_header_row(ws, profile) if profile.has_ledger else None
    if ledger_header and (header is None or l_score >= d_score):
        mapping = _facade()._map_headers(ws, ledger_header, profile)
        if 'order_number' in mapping:
            return 'ledger'
    if header is not None:
        mapping = _facade()._map_headers(ws, header, profile)
        if 'product_name' in mapping or 'model_number' in mapping:
            return 'delivery'
    if d_score < 16 and l_score < 16:
        return 'ignore'
    return 'unknown'

def _parse_buyer_meta(ws, header_row: int, profile: _facade().ShipmentEtlProfile) -> dict[str, str]:
    meta = {'unit_name': '', 'contact_person': '', 'order_date': '', 'order_number': '', 'title': ''}
    mp = profile.meta_patterns
    for row in range(1, header_row):
        text = _facade()._joined_row(ws, row)
        if not text:
            continue
        if not meta['title'] and mp.title.search(text):
            meta['title'] = text.strip()
        buyer = mp.buyer.search(text.replace('\u3000', ' '))
        if buyer and (not meta['unit_name']):
            candidate = buyer.group(1).strip(' ：:\u3000')
            candidate = _facade().re.sub('\\s*\\([^)]*\\)\\s*$', '', candidate).strip()
            if candidate and (not _facade()._unit_name_looks_truncated(candidate)):
                meta['unit_name'] = candidate
        contact = mp.contact.search(text)
        if contact and (not meta['contact_person']):
            meta['contact_person'] = contact.group(1).strip(' ：:\u3000')
        date_m = mp.date.search(text)
        if date_m and (not meta['order_date']):
            meta['order_date'] = date_m.group(1).replace(' ', '')
        order_m = mp.order_no.search(text)
        if order_m and (not meta['order_number']):
            meta['order_number'] = order_m.group(1).strip()
    if not meta['unit_name']:
        label = mp.buyer_label
        for row in range(1, header_row):
            text = _facade()._joined_row(ws, row)
            if label not in text:
                continue
            after = mp.buyer_split.split(text, maxsplit=1)
            if len(after) > 1:
                chunk = mp.buyer_stop.split(after[1], maxsplit=1)[0]
                meta['unit_name'] = chunk.strip(' ：:\u3000')
                break
    adjacent = _facade()._extract_adjacent_buyer_meta(ws, header_row)
    from app.application.shipment_excel_etl_llm import unit_name_is_weak
    if adjacent.get('unit_name'):
        meta['unit_name'] = adjacent['unit_name']
    if not meta['contact_person'] and adjacent.get('contact_person'):
        meta['contact_person'] = adjacent['contact_person']
    if not meta['order_number'] and adjacent.get('order_number'):
        meta['order_number'] = adjacent['order_number']
    if meta['unit_name']:
        meta['unit_name'] = _facade().re.sub('\\s*\\([^)]*\\)\\s*$', '', meta['unit_name']).strip()
        meta['unit_name'] = _facade().re.split('(?i)\\s{2,}|\\s+(?:Incoterms|Payment|Tel|Phone|地址|电话)\\b', meta['unit_name'], maxsplit=1)[0].strip()
    if meta['unit_name'] and (_facade()._unit_name_looks_truncated(meta['unit_name']) or unit_name_is_weak(meta['unit_name'])):
        meta['unit_name'] = ''
    return meta
