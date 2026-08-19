# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.fastapi_routes.xcmax_admin')

def _collect_codex_usage() -> dict[str, _facade().Any]:
    """Codex 用量（~/.codex/archived_sessions/*.jsonl）。"""
    archived = _facade().os.path.expanduser('~/.codex/archived_sessions')
    if not _facade().os.path.isdir(archived):
        return {'available': False, 'reason': f'目录不存在: {archived}'}
    jsonl_files = sorted((f for f in (_facade().os.path.join(archived, x) for x in _facade().os.listdir(archived)) if f.endswith('.jsonl')))
    total_input = total_cached = total_output = total_reasoning = total_total = 0
    by_model: dict[str, dict[str, _facade().Any]] = {}
    session_count = 0
    for fpath in jsonl_files:
        session_model = 'unknown'
        has_token = False
        try:
            with open(fpath, encoding='utf-8') as f:
                for line in f:
                    try:
                        evt = _facade().json.loads(line)
                    except _facade().RECOVERABLE_ERRORS:
                        continue
                    if evt.get('type') == 'session_meta':
                        payload = evt.get('payload') or {}
                        session_model = payload.get('model') or payload.get('model_provider') or 'unknown'
                    if evt.get('type') == 'event_msg' and (evt.get('payload') or {}).get('type') == 'token_count':
                        info = (evt.get('payload') or {}).get('info') or {}
                        usage = info.get('total_token_usage') or {}
                        i = _facade()._to_int(usage.get('input_tokens'))
                        c = _facade()._to_int(usage.get('cached_input_tokens'))
                        o = _facade()._to_int(usage.get('output_tokens'))
                        r = _facade()._to_int(usage.get('reasoning_output_tokens'))
                        t = _facade()._to_int(usage.get('total_tokens'))
                        total_input += i
                        total_cached += c
                        total_output += o
                        total_reasoning += r
                        total_total += t
                        slot = by_model.setdefault(session_model, {'input': 0, 'cached': 0, 'output': 0, 'reasoning': 0, 'total': 0, 'count': 0})
                        slot['input'] += i
                        slot['cached'] += c
                        slot['output'] += o
                        slot['reasoning'] += r
                        slot['total'] += t
                        slot['count'] += 1
                        has_token = True
        except _facade().RECOVERABLE_ERRORS:
            continue
        if has_token:
            session_count += 1
    return {'available': True, 'source': 'Codex (~/.codex/archived_sessions)', 'jsonl_files': len(jsonl_files), 'sessions_with_tokens': session_count, 'prompt_tokens': total_input, 'cached_tokens': total_cached, 'completion_tokens': total_output, 'reasoning_tokens': total_reasoning, 'total_tokens': total_total, 'by_model': dict(sorted(by_model.items(), key=lambda x: -x[1]['total']))}

def _collect_trae_usage() -> dict[str, _facade().Any]:
    """Trae 用量（state.vscdb，API 403 无法获取精确 token）。"""
    import sqlite3
    state_db = _facade().os.path.expanduser('~/Library/Application Support/Trae CN/User/globalStorage/state.vscdb')
    if not _facade().os.path.exists(state_db):
        return {'available': False, 'reason': f'state.vscdb 不存在: {state_db}'}
    total_turns = 0
    turn_details: dict[str, int] = {}
    current_models: _facade().Any = None
    available_models_count = 0
    try:
        conn = sqlite3.connect(state_db)
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'ai.chat.feedback%.accumulatedTurns'")
        for (key, value) in cur.fetchall():
            n = _facade()._to_int(value)
            total_turns += n
            turn_details[key] = n
        cur.execute("SELECT value FROM ItemTable WHERE key LIKE '%sessionRelation:globalModelMap%' LIMIT 1")
        row = cur.fetchone()
        if row:
            try:
                current_models = _facade().json.loads(row[0])
            except _facade().RECOVERABLE_ERRORS:
                current_models = None
        cur.execute("SELECT value FROM ItemTable WHERE key LIKE '%model_list_map%' LIMIT 1")
        row = cur.fetchone()
        if row:
            try:
                m = _facade().json.loads(row[0])
                if isinstance(m, dict):
                    for (_mode, models) in m.items():
                        if isinstance(models, list):
                            available_models_count += len(models)
            except _facade().RECOVERABLE_ERRORS:
                pass
        conn.close()
    except _facade().RECOVERABLE_ERRORS as exc:
        return {'available': False, 'reason': f'读取 state.vscdb 失败: {exc}'}
    est_prompt_per_turn = 10000000
    est_completion_per_turn = 500000
    est_prompt = total_turns * est_prompt_per_turn
    est_completion = total_turns * est_completion_per_turn
    est_total = est_prompt + est_completion
    return {'available': True, 'source': 'Trae (state.vscdb + 轮次估算)', 'note': f'Trae API 被 WAF 403 拦截，按 {total_turns} 轮 × 1050 万 tokens/轮 估算（prompt 1000 万 + completion 50 万）', 'estimated': True, 'total_chat_turns': total_turns, 'turn_details': turn_details, 'current_models': current_models, 'available_models_count': available_models_count, 'prompt_tokens': est_prompt, 'completion_tokens': est_completion, 'total_tokens': est_total}

def _estimate_cost_usd(source_key: str, data: dict[str, _facade().Any]) -> float:
    """估算费用（美元）。Cursor 用精确 cents，其余按 API 单价估算。"""
    if not data.get('available'):
        return 0.0
    if source_key == 'cursor':
        return _facade()._to_int(data.get('cost_cents')) / 100.0
    if source_key == 'codex':
        prompt = _facade()._to_int(data.get('prompt_tokens'))
        cached = _facade()._to_int(data.get('cache_read_tokens'))
        output = _facade()._to_int(data.get('completion_tokens'))
        reasoning = _facade()._to_int(data.get('reasoning_tokens'))
        uncached = max(0, prompt - cached)
        return uncached * 5 / 1000000 + cached * 1.25 / 1000000 + (output + reasoning) * 10 / 1000000
    if source_key == 'trae':
        prompt = _facade()._to_int(data.get('prompt_tokens'))
        output = _facade()._to_int(data.get('completion_tokens'))
        return (prompt + output) * 5 / 7.2 / 1000000
    if source_key == 'local':
        return _facade()._to_int(data.get('cost_units')) / 100.0
    if source_key == 'mimo':
        return 0.0
    return 0.0

def _collect_mimo_usage() -> dict[str, _facade().Any]:
    """采集 mimo（小米 MiMo）用量。手动输入静态数据。"""
    credits_used = 22070888859
    credits_quota = 38000000000
    actual_tokens = 80621905
    usage_pct = round(credits_used / credits_quota * 100, 1) if credits_quota else 0
    return {'available': True, 'source': 'mimo (小米 MiMo, 手动输入)', 'note': f'Credits {credits_used:,} / {credits_quota:,}（{usage_pct}%），实际 token {actual_tokens:,}', 'total_tokens': actual_tokens, 'prompt_tokens': 0, 'completion_tokens': 0, 'credits_used': credits_used, 'credits_quota': credits_quota, 'usage_percent': usage_pct, 'estimated': True}

def _build_token_usage_summary() -> dict[str, _facade().Any]:
    """聚合 5 个来源的 token 用量（平台制作 Token）。"""
    local = _facade()._collect_local_ledger()
    cursor = _facade()._collect_cursor_usage()
    codex = _facade()._collect_codex_usage()
    trae = _facade()._collect_trae_usage()
    mimo = _facade()._collect_mimo_usage()
    sources = {'local': local, 'cursor': cursor, 'codex': codex, 'trae': trae, 'mimo': mimo}
    for (key, src) in sources.items():
        src['estimated_cost_usd'] = round(_facade()._estimate_cost_usd(key, src), 2)
    grand_total = sum((_facade()._to_int(s.get('total_tokens')) for s in sources.values()))
    grand_prompt = sum((_facade()._to_int(s.get('prompt_tokens')) for s in sources.values()))
    grand_completion = sum((_facade()._to_int(s.get('completion_tokens')) for s in sources.values()))
    grand_cost = round(sum((s.get('estimated_cost_usd', 0.0) for s in sources.values())), 2)
    summary = {'success': True, 'grand_total_tokens': grand_total, 'grand_prompt_tokens': grand_prompt, 'grand_completion_tokens': grand_completion, 'grand_cost_usd': grand_cost, 'sources': sources, 'collected_at': _facade().time.strftime('%Y-%m-%d %H:%M:%S')}
    try:
        from app.infrastructure.billing.platform_made_tokens import write_public_snapshot
        snapshot_path = write_public_snapshot(summary)
        summary['public_snapshot_path'] = str(snapshot_path)
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('platform_made_tokens snapshot write failed: %s', exc)
    return summary

@_facade().router.get('/admin/token-usage', response_model=None)
async def admin_token_usage(request: _facade().Request):
    """平台制作 Token：本地账本 + Cursor + Codex + Trae + mimo。"""
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    if not _session_id_from_request(request):
        return _facade().JSONResponse({'success': False, 'message': '请先登录'}, status_code=401)
    return await _facade().asyncio.to_thread(_facade()._build_token_usage_summary)
