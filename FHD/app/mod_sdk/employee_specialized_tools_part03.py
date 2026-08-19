# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.mod_sdk.employee_specialized_tools')

async def tool_query_provider_usage(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """查询 provider 账户余额与用量（通用化，支持多家 billing API）。

    真实探测 provider 的 billing endpoint，返回余额/用量。
    可用 params.provider 指定单个 provider，或留空查全部已配置的。
    """
    if _facade().httpx is None:
        return _facade()._err('httpx 未安装')
    target = str(params.get('provider') or '').strip().lower()
    env = dict(_facade().os.environ)
    all_findings: list[dict[str, _facade().Any]] = []
    checked = 0
    supported = 0
    async with _facade().httpx.AsyncClient(timeout=15) as client:
        for profile in _facade()._PROVIDER_PROFILES:
            name = profile['name']
            if target and target != 'all' and (target != name):
                continue
            key = _facade()._provider_has_key(profile, env)
            no_auth = profile.get('no_auth', False)
            if not key and (not no_auth):
                continue
            endpoints = profile.get('billing_endpoints') or []
            if not endpoints:
                all_findings.append({'provider': name, 'endpoint': '(无)', 'status': 0, 'ok': False, 'error': f'{name} 无标准 billing API'})
                continue
            base_url = _facade()._provider_base_url(profile, env)
            headers = {}
            if not no_auth and key:
                headers['Authorization'] = f'Bearer {key}'
            checked += 1
            for ep in endpoints:
                url = ep if str(ep).startswith(('https://', 'http://')) else f"{base_url.rstrip('/')}{ep}"
                try:
                    resp = await client.get(url, headers=headers)
                    body: _facade().Any
                    try:
                        body = resp.json()
                    except _facade().RECOVERABLE_ERRORS:
                        body = resp.text[:300]
                    finding = {'provider': name, 'endpoint': ep, 'status': resp.status_code, 'ok': resp.is_success, 'body': body if isinstance(body, (dict, list)) else str(body)[:300]}
                    all_findings.append(finding)
                    if resp.is_success:
                        supported += 1
                except _facade().RECOVERABLE_ERRORS as exc:
                    all_findings.append({'provider': name, 'endpoint': ep, 'status': 0, 'ok': False, 'error': repr(exc)[:200]})
    return _facade()._ok(f'探测 {checked} 个 provider 的 billing endpoint，{supported} 个可用', findings=all_findings, has_usage_api=supported > 0, checked_providers=checked, supported_count=supported)

async def tool_compare_model_prices(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """对比各 LLM 模型价格（内置价格表，覆盖 10 家 provider）。

    支持按 provider 过滤，按价格排序。标注免费模型。
    """
    provider_filter = str(params.get('provider') or '').strip().lower()
    sort_by = str(params.get('sort_by') or 'output').strip().lower()
    prices = [dict(p) for p in _facade()._MODEL_PRICES]
    if provider_filter:
        prices = [p for p in prices if provider_filter in str(p['provider']).lower()]
    sort_key = 'input_per_1m' if sort_by == 'input' else 'output_per_1m'
    prices.sort(key=lambda x: float(x.get(sort_key, 999)))
    free_models = [p['model'] for p in prices if float(p.get('input_per_1m', 0)) == 0 and float(p.get('output_per_1m', 0)) == 0]
    cheapest = prices[0] if prices else None
    return _facade()._ok(f'对比 {len(prices)} 个模型（按 {sort_key} 升序），{len(free_models)} 个免费', prices=prices, free_models=free_models, cheapest=cheapest, sort_by=sort_key, total_models=len(_facade()._MODEL_PRICES), providers_covered=sorted({p['provider'] for p in _facade()._MODEL_PRICES}))

async def tool_list_vlm_models(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """列出当前环境可推断的 VLM（视觉识别）模型候选。

    供 llm-ops-engineer 盘点「谁能做图文识别」，并指导配置
    ``XCAGI_EMPLOYEE_VLM_PROVIDER`` / ``XCAGI_EMPLOYEE_VLM_MODEL``。
    """
    from app.infrastructure.llm.vlm_route import list_configured_vlm_candidates, resolve_vlm_route
    candidates = list_configured_vlm_candidates()
    route = resolve_vlm_route()
    known_defaults = [{'provider': 'openai', 'model': 'gpt-4o-mini', 'capability': 'vlm'}, {'provider': 'qwen', 'model': 'qwen-vl-plus', 'capability': 'vlm'}, {'provider': 'zhipu', 'model': 'glm-4v-flash', 'capability': 'vlm'}, {'provider': 'siliconflow', 'model': 'Qwen/Qwen2-VL-7B-Instruct', 'capability': 'vlm'}, {'provider': 'openrouter', 'model': 'openai/gpt-4o-mini', 'capability': 'vlm'}]
    return _facade()._ok(f"发现 {len(candidates)} 个已配置 VLM 候选；当前路由 ok={bool(route.get('ok'))}", candidates=candidates, active_route=route, known_defaults=known_defaults, env_hint={'XCAGI_EMPLOYEE_VLM_PROVIDER': _facade().os.environ.get('XCAGI_EMPLOYEE_VLM_PROVIDER', '') or '(未设置)', 'XCAGI_EMPLOYEE_VLM_MODEL': _facade().os.environ.get('XCAGI_EMPLOYEE_VLM_MODEL', '') or '(未设置)', 'FHD_TEMPLATE_VLM_ENRICH': _facade().os.environ.get('FHD_TEMPLATE_VLM_ENRICH', '') or '(未设置)'})

async def tool_get_vlm_route(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """查询当前生效的员工 VLM 路由（模版 PDF/PPT 识图与员工 call_llm 多模态共用）。"""
    from app.infrastructure.llm.vlm_route import resolve_vlm_route
    route = resolve_vlm_route()
    if route.get('ok'):
        return _facade()._ok(f"VLM 路由：{route.get('provider')}/{route.get('model')}（{route.get('source')}）", route=route)
    return _facade()._err(str(route.get('message') or '未配置 VLM'), route=route)

async def tool_query_local_token_usage(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """查询本地 token 用量账本（真实数据，非 LLM 编造）。

    读取 FHD 的 model_usage_ledger.json，返回 token 用量统计。
    b.ai/mimo 等平台不开放 usage 查询 API，但 FHD 在 agent_orchestrator
    路径下会记录每次 LLM 调用的 prompt/completion/total tokens 到本地账本。

    可用 params:
    - user_id: 按用户筛选
    - run_id: 按会话/run 筛选
    - limit: 返回最近 N 条明细（默认 20，0 = 只返回汇总不返回明细）
    - group_by: "model" | "provider" | "none"（默认 model）
    """
    try:
        from app.infrastructure.billing.model_usage import list_model_usage_entries, model_usage_ledger_path
    except ImportError as exc:
        return _facade()._err(f'无法导入 billing 模块: {exc}')
    user_id = str(params.get('user_id') or '').strip()
    run_id = str(params.get('run_id') or '').strip()
    limit = int(str(params.get('limit') if params.get('limit') is not None else 20))
    group_by = str(params.get('group_by') or 'model').strip().lower()
    ledger_path = model_usage_ledger_path()
    entries = list_model_usage_entries(limit=max(limit, 500) if limit > 0 else 500, run_id=run_id, user_id=user_id)
    model_entries = [e for e in entries if str(e.get('entry_type') or 'model_call') == 'model_call']
    total_prompt = sum((int(e.get('prompt_tokens') or 0) for e in model_entries))
    total_completion = sum((int(e.get('completion_tokens') or 0) for e in model_entries))
    total_tokens = sum((int(e.get('total_tokens') or 0) for e in model_entries))
    total_cost = sum((int(e.get('cost_units') or 0) for e in model_entries))
    groups: dict[str, dict[str, _facade().Any]] = {}
    group_key = 'model' if group_by == 'model' else 'provider' if group_by == 'provider' else ''
    for e in model_entries:
        if not group_key:
            continue
        key = str(e.get(group_key) or 'unknown')
        g = groups.setdefault(key, {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0, 'cost_units': 0, 'calls': 0})
        g['prompt_tokens'] += int(e.get('prompt_tokens') or 0)
        g['completion_tokens'] += int(e.get('completion_tokens') or 0)
        g['total_tokens'] += int(e.get('total_tokens') or 0)
        g['cost_units'] += int(e.get('cost_units') or 0)
        g['calls'] += 1
    details = []
    if limit > 0:
        for e in model_entries[:limit]:
            details.append({'created_at': e.get('created_at', ''), 'provider': e.get('provider', ''), 'model': e.get('model', ''), 'prompt_tokens': int(e.get('prompt_tokens') or 0), 'completion_tokens': int(e.get('completion_tokens') or 0), 'total_tokens': int(e.get('total_tokens') or 0), 'cost_units': int(e.get('cost_units') or 0), 'run_id': e.get('run_id', ''), 'user_id': e.get('user_id', '')})
    ledger_exists = ledger_path.is_file()
    return _facade()._ok(f'本地账本 {len(model_entries)} 条 model_call 记录，总 token={total_tokens:,}', ledger_path=str(ledger_path), ledger_exists=ledger_exists, usage_summary={'total_calls': len(model_entries), 'prompt_tokens': total_prompt, 'completion_tokens': total_completion, 'total_tokens': total_tokens, 'cost_units': total_cost}, groups=groups if group_key else {}, group_by=group_by, details=details, detail_count=len(details), note='仅 agent_orchestrator 路径记录；conversation 服务主路径未持久化。b.ai/mimo 平台不开放 usage API，需去各自控制台查看。')

async def tool_query_cursor_usage(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """查询 Cursor 编辑器的使用统计（自动采集，含精确 token 用量）。

    数据源（按精确度从高到低）：
    1. cursor-usage CLI → 调 Cursor Dashboard 内部 API，返回精确的
       inputTokens/outputTokens/cacheReadTokens/totalCents（按 model 分组）
    2. macOS Keychain cursor-access-token → api2.cursor.sh/auth/usage
       获取免费配额（gpt-4）的请求次数
    3. 本地 ~/.cursor/ai-tracking/ai-code-tracking.db（SQLite）
       获取 AI 代码生成次数和 commit 代码比例

    可用 params:
    - days: 统计最近 N 天的数据（默认 30，0 = 当前账单月）
    - detail_limit: 返回最近 N 条明细事件（默认 10，0 = 不返回明细）
    """
    import csv
    import io
    import shutil
    import sqlite3
    import subprocess
    from datetime import UTC, datetime, timedelta
    days = int(str(params.get('days') if params.get('days') is not None else 30))
    detail_limit = int(str(params.get('detail_limit') if params.get('detail_limit') is not None else 10))
    result_data: dict[str, _facade().Any] = {'sources': [], 'cli_usage': None, 'api_usage': None, 'local_db': None, 'cursor_summary': {}}
    cli_bin = shutil.which('cursor-usage') or str(_facade().Path.home() / 'Library' / 'Python' / '3.9' / 'bin' / 'cursor-usage')
    if _facade().Path(cli_bin).is_file():
        result_data['sources'].append('cursor-usage-cli')
        try:
            cmd = [cli_bin, '--json']
            if days > 0:
                cmd.extend(['--days', str(days)])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                raw = _facade().json.loads(proc.stdout)
                aggregations = raw.get('aggregations', [])
                total_input = 0
                total_output = 0
                total_cache_read = 0
                total_cache_write = 0
                total_cents = 0.0
                by_model = []
                for agg in aggregations:
                    inp = int(agg.get('inputTokens') or 0)
                    out = int(agg.get('outputTokens') or 0)
                    cr = int(agg.get('cacheReadTokens') or 0)
                    cw = int(agg.get('cacheWriteTokens') or 0)
                    cents = float(agg.get('totalCents') or 0)
                    total_input += inp
                    total_output += out
                    total_cache_read += cr
                    total_cache_write += cw
                    total_cents += cents
                    by_model.append({'model': agg.get('modelIntent', 'unknown'), 'input_tokens': inp, 'output_tokens': out, 'cache_read_tokens': cr, 'cache_write_tokens': cw, 'total_tokens': inp + out + cr + cw, 'cost_cents': round(cents, 2), 'cost_usd': round(cents / 100, 4), 'tier': agg.get('tier')})
                by_model.sort(key=lambda x: x['cost_cents'], reverse=True)
                result_data['cli_usage'] = {'total_input_tokens': total_input, 'total_output_tokens': total_output, 'total_cache_read_tokens': total_cache_read, 'total_cache_write_tokens': total_cache_write, 'total_tokens': total_input + total_output + total_cache_read + total_cache_write, 'total_cost_cents': round(total_cents, 2), 'total_cost_usd': round(total_cents / 100, 2), 'by_model': by_model, 'model_count': len(by_model), 'days_filter': days if days > 0 else 'current_billing_month'}
                if detail_limit > 0:
                    csv_cmd = [cli_bin]
                    if days > 0:
                        csv_cmd.extend(['--days', str(days)])
                    else:
                        csv_cmd.extend(['--month', datetime.now(UTC).strftime('%Y-%m')])
                    csv_cmd.extend(['--csv', '-'])
                    csv_proc = subprocess.run(csv_cmd, capture_output=True, text=True, timeout=60)
                    if csv_proc.returncode == 0 and csv_proc.stdout:
                        reader = csv.DictReader(io.StringIO(csv_proc.stdout))
                        events = list(reader)
                        events = events[-detail_limit:] if len(events) > detail_limit else events
                        result_data['cli_usage']['recent_events'] = [{'datetime': e.get('datetime_local', ''), 'model': e.get('model', ''), 'input_tokens': int(e.get('input_tokens') or 0), 'output_tokens': int(e.get('output_tokens') or 0), 'cache_read_tokens': int(e.get('cache_read_tokens') or 0), 'value_cents': float(e.get('value_cents') or 0), 'kind': e.get('kind', '')} for e in events]
                        result_data['cli_usage']['total_events'] = len(list(csv.DictReader(io.StringIO(csv_proc.stdout))))
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data['cli_usage'] = {'error': str(exc)}
    api_token = ''
    try:
        proc = subprocess.run(['security', 'find-generic-password', '-s', 'cursor-access-token', '-a', 'cursor-user', '-w'], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            api_token = proc.stdout.strip()
    except _facade().RECOVERABLE_ERRORS:
        pass
    if api_token:
        result_data['sources'].append('cursor-api:auth/usage')
        try:
            import httpx as _httpx
            resp = _httpx.get('https://api2.cursor.sh/auth/usage', headers={'Authorization': f'Bearer {api_token}', 'User-Agent': 'cursor/0.50.0', 'x-cursor-client-version': '0.50.0'}, timeout=10)
            if resp.status_code == 200:
                api_data = resp.json()
                result_data['api_usage'] = {'free_quota': api_data, 'start_of_month': api_data.get('startOfMonth', ''), 'note': '仅返回免费配额(gpt-4)；Pro 版用量由 cursor-usage CLI 提供'}
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data['api_usage'] = {'error': str(exc)}
    db_path = _facade().Path.home() / '.cursor' / 'ai-tracking' / 'ai-code-tracking.db'
    if db_path.is_file():
        result_data['sources'].append(f'local-db:{db_path.name}')
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            since_ts = 0
            if days > 0:
                since_dt = datetime.now(UTC) - timedelta(days=days)
                since_ts = int(since_dt.timestamp() * 1000)
            if since_ts > 0:
                cur.execute('SELECT model, COUNT(*) as count FROM ai_code_hashes WHERE timestamp >= ? GROUP BY model ORDER BY count DESC', (since_ts,))
            else:
                cur.execute('SELECT model, COUNT(*) as count FROM ai_code_hashes GROUP BY model ORDER BY count DESC')
            model_counts = [{'model': r['model'] or '(unknown)', 'count': r['count']} for r in cur.fetchall()]
            cur.execute('SELECT COUNT(*) FROM ai_code_hashes')
            total_hashes = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) as commits, SUM(linesAdded) as total_add, SUM(tabLinesAdded) as tab_add, SUM(composerLinesAdded) as comp_add, SUM(humanLinesAdded) as human_add FROM scored_commits')
            row = cur.fetchone()
            commits_data = {'total_commits': row['commits'], 'total_lines_added': row['total_add'] or 0, 'tab_lines_added': row['tab_add'] or 0, 'composer_lines_added': row['comp_add'] or 0, 'human_lines_added': row['human_add'] or 0}
            ai_lines = commits_data['tab_lines_added'] + commits_data['composer_lines_added']
            total_lines = commits_data['total_lines_added'] or 1
            commits_data['ai_percentage'] = round(ai_lines / total_lines * 100, 1)
            conn.close()
            result_data['local_db'] = {'db_path': str(db_path), 'total_ai_generations': total_hashes, 'by_model': model_counts, 'commits': commits_data, 'days_filter': days if days > 0 else 'all'}
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data['local_db'] = {'error': str(exc)}
    cli = result_data.get('cli_usage') or {}
    total_tokens = cli.get('total_tokens', 0)
    total_cost = cli.get('total_cost_usd', 0)
    total_gen = 0
    if result_data.get('local_db') and 'error' not in result_data['local_db']:
        total_gen = result_data['local_db'].get('total_ai_generations', 0)
    result_data['cursor_summary'] = {'total_tokens': total_tokens, 'total_cost_usd': total_cost, 'total_ai_generations': total_gen, 'has_cli': bool(cli and 'error' not in cli), 'has_api_token': bool(api_token), 'has_local_db': bool(result_data.get('local_db') and 'error' not in result_data.get('local_db', {})), 'note': 'cursor-usage CLI 提供精确 token 和费用（来自 Dashboard API）。本地 DB 提供 AI 生成次数和代码比例。'}
    return _facade()._ok(f"Cursor 使用统计：{total_tokens:,} tokens，${total_cost}，{total_gen} 次 AI 生成，{len(result_data['sources'])} 个数据源", **result_data)

async def tool_query_codex_usage(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """查询 OpenAI Codex CLI 的使用统计（自动从本地数据采集）。

    数据源：
    1. ~/.codex/archived_sessions/*.jsonl — 逐会话的精确 token 用量
       （input/cached/output/reasoning/total tokens + rate_limits）
    2. ~/.codex/goals_1.sqlite 的 thread_goals 表 — 按会话的 tokens_used 和状态
    3. ~/.codex/config.toml — 当前 model 配置

    可用 params:
    - days: 统计最近 N 天的数据（默认 30，0 = 全部）
    """
    import glob
    import sqlite3
    from datetime import UTC, datetime, timedelta
    days = int(str(params.get('days') if params.get('days') is not None else 30))
    codex_dir = _facade().Path.home() / '.codex'
    result_data: dict[str, _facade().Any] = {'sources': [], 'sessions': None, 'goals_db': None, 'config': None, 'codex_summary': {}}
    sessions_dir = codex_dir / 'archived_sessions'
    jsonl_files = sorted(glob.glob(str(sessions_dir / '*.jsonl'))) if sessions_dir.is_dir() else []
    if jsonl_files:
        result_data['sources'].append(f'archived-sessions:{len(jsonl_files)}-files')
        try:
            since_dt = None
            if days > 0:
                since_dt = datetime.now(UTC) - timedelta(days=days)
            sessions_list = []
            total_input = 0
            total_cached = 0
            total_output = 0
            total_reasoning = 0
            total_tokens = 0
            for fpath in jsonl_files:
                session_model = 'unknown'
                session_cwd = ''
                session_ts = ''
                last_usage = None
                rate_limit_used = None
                with open(fpath, encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            evt = _facade().json.loads(line)
                        except _facade().json.JSONDecodeError:
                            continue
                        evt_type = evt.get('type', '')
                        payload = evt.get('payload', {})
                        if evt_type == 'session_meta':
                            session_model = payload.get('model', session_model)
                            session_cwd = payload.get('cwd', '')
                            session_ts = payload.get('timestamp', '')
                        if evt_type == 'event_msg' and payload.get('type') == 'token_count':
                            info = payload.get('info', {})
                            last_usage = info.get('total_token_usage', {})
                            rl = payload.get('rate_limits', {})
                            primary = rl.get('primary', {})
                            rate_limit_used = primary.get('used_percent')
                if last_usage:
                    inp = int(last_usage.get('input_tokens') or 0)
                    cached = int(last_usage.get('cached_input_tokens') or 0)
                    out = int(last_usage.get('output_tokens') or 0)
                    reasoning = int(last_usage.get('reasoning_output_tokens') or 0)
                    tot = int(last_usage.get('total_tokens') or 0)
                    if since_dt and session_ts:
                        try:
                            evt_dt = datetime.fromisoformat(session_ts.replace('Z', '+00:00'))
                            if evt_dt < since_dt:
                                continue
                        except (ValueError, TypeError):
                            pass
                    total_input += inp
                    total_cached += cached
                    total_output += out
                    total_reasoning += reasoning
                    total_tokens += tot
                    sessions_list.append({'file': _facade().Path(fpath).name, 'model': session_model, 'cwd': session_cwd, 'timestamp': session_ts, 'input_tokens': inp, 'cached_input_tokens': cached, 'output_tokens': out, 'reasoning_output_tokens': reasoning, 'total_tokens': tot, 'rate_limit_used_percent': rate_limit_used})
            sessions_list.sort(key=lambda item: str(item.get('timestamp') or ''), reverse=True)
            result_data['sessions'] = {'total_sessions': len(sessions_list), 'total_input_tokens': total_input, 'total_cached_input_tokens': total_cached, 'total_output_tokens': total_output, 'total_reasoning_output_tokens': total_reasoning, 'total_tokens': total_tokens, 'by_session': sessions_list[:20], 'days_filter': days if days > 0 else 'all'}
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data['sessions'] = {'error': str(exc)}
    goals_db = codex_dir / 'goals_1.sqlite'
    if goals_db.is_file():
        result_data['sources'].append('goals-sqlite')
        try:
            conn = sqlite3.connect(str(goals_db))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute('SELECT thread_id, objective, status, token_budget, tokens_used, time_used_seconds, created_at_ms FROM thread_goals ORDER BY created_at_ms DESC')
            goals_list = []
            total_goal_tokens = 0
            total_goal_time = 0
            for r in cur.fetchall():
                tokens = r['tokens_used'] or 0
                total_goal_tokens += tokens
                total_goal_time += r['time_used_seconds'] or 0
                goals_list.append({'thread_id': r['thread_id'], 'objective': (r['objective'] or '')[:80], 'status': r['status'], 'token_budget': r['token_budget'], 'tokens_used': tokens, 'time_used_seconds': r['time_used_seconds'] or 0, 'created_at': datetime.fromtimestamp((r['created_at_ms'] or 0) / 1000).strftime('%Y-%m-%d %H:%M')})
            conn.close()
            result_data['goals_db'] = {'total_threads': len(goals_list), 'total_tokens_used': total_goal_tokens, 'total_time_seconds': total_goal_time, 'by_status': {s: sum((1 for g in goals_list if g['status'] == s)) for s in {g['status'] for g in goals_list}}, 'threads': goals_list}
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data['goals_db'] = {'error': str(exc)}
    config_file = codex_dir / 'config.toml'
    if config_file.is_file():
        result_data['sources'].append('config-toml')
        try:
            config_text = config_file.read_text(encoding='utf-8')
            model = ''
            reasoning_effort = ''
            for line in config_text.splitlines():
                line = line.strip()
                if line.startswith('model') and '=' in line:
                    model = line.split('=', 1)[1].strip().strip('"')
                if line.startswith('model_reasoning_effort') and '=' in line:
                    reasoning_effort = line.split('=', 1)[1].strip().strip('"')
            result_data['config'] = {'model': model, 'reasoning_effort': reasoning_effort}
        except _facade().RECOVERABLE_ERRORS as exc:
            result_data['config'] = {'error': str(exc)}
    sess = result_data.get('sessions') or {}
    goals = result_data.get('goals_db') or {}
    total_tok = sess.get('total_tokens', 0) or goals.get('total_tokens_used', 0)
    result_data['codex_summary'] = {'total_tokens': total_tok, 'total_sessions': sess.get('total_sessions', 0), 'total_threads': goals.get('total_threads', 0), 'total_time_seconds': goals.get('total_time_seconds', 0), 'model': (result_data.get('config') or {}).get('model', 'unknown'), 'note': 'Codex CLI 本地数据。archived_sessions 含精确 token（input/cached/output/reasoning），goals_db 含按会话的 token 和状态。'}
    return _facade()._ok(f"Codex 使用统计：{total_tok:,} tokens，{sess.get('total_sessions', 0)} 个会话，{len(result_data['sources'])} 个数据源", **result_data)
