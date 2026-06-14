"""employee_pack 员工实现（MODstore 生成）。

行为按 manifest.employee_config_v2.actions.handlers 分支：
  - echo     → 直接回显 payload，不调 LLM
  - llm_md   → 调 ctx.call_llm 出 Markdown（默认章节：用途/输入/输出/示例/异常）
  - webhook  → 调 ctx.http_post 转发到 actions.webhook.url
若 handlers 为空或不被支持，run 返回 {ok: False, error: ...}，绝不默认走 LLM。
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EMPLOYEE_ID = "security-secrets-guard"
EMPLOYEE_LABEL = "安全密钥守卫"

SYSTEM_PROMPT = "你是 XCAGI 员工「安全密钥守卫」。按 manifest.employee_config_v2.actions.handlers 选择 echo、llm_md、webhook 或 agent 分支执行；先读取 payload 与 manifest 配置，提取关键字段，再调用 ctx 工具；输出统一返回 {ok, summary, items, warnings, error, meta}；信息不足时如实说明，禁止编造数据、密钥或外部执行结果。"

DEFAULT_README_SECTIONS = (
    '## 用途\n'
    '## 输入\n'
    '## 输出\n'
    '## 示例\n'
    '## 异常与边界\n'
)


def _ok(data: Any, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        'ok': True,
        'summary': '' if data is None else (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))[:4000],
        'items': data if isinstance(data, list) else ([] if data is None else [data] if not isinstance(data, dict) else [data]),
        'warnings': list(warnings or []),
        'error': '',
        'meta': dict(meta or {}),
    }


def _err(msg: str, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        'ok': False,
        'summary': msg[:400],
        'items': [],
        'warnings': list(warnings or []),
        'error': msg[:1000],
        'meta': dict(meta or {}),
    }


def _manifest_path() -> Optional[Path]:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        cand = parent / 'manifest.json'
        if cand.is_file():
            return cand
    return None


def _load_manifest() -> Optional[Dict[str, Any]]:
    mp = _manifest_path()
    if not mp:
        return None
    try:
        data = json.loads(mp.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _v2(manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(manifest, dict):
        return {}
    v2 = manifest.get('employee_config_v2')
    return v2 if isinstance(v2, dict) else {}


def _agent_model(v2: Dict[str, Any]) -> Dict[str, Any]:
    cog = v2.get('cognition') if isinstance(v2.get('cognition'), dict) else {}
    agent = cog.get('agent') if isinstance(cog.get('agent'), dict) else {}
    model = agent.get('model') if isinstance(agent.get('model'), dict) else {}
    return {
        'system_prompt': str(agent.get('system_prompt') or '').strip(),
        'max_tokens': int(model.get('max_tokens') or 4000),
        'temperature': float(model.get('temperature') if model.get('temperature') is not None else 0.2),
    }


def _actions(v2: Dict[str, Any]) -> Dict[str, Any]:
    a = v2.get('actions') if isinstance(v2.get('actions'), dict) else {}
    return a


def _handlers(actions: Dict[str, Any]) -> List[str]:
    raw = actions.get('handlers') if isinstance(actions.get('handlers'), list) else []
    return [str(h).strip() for h in raw if isinstance(h, str) and str(h).strip()]


async def _handle_echo(payload: Dict[str, Any], _ctx: Dict[str, Any], _v2: Dict[str, Any]) -> Dict[str, Any]:
    return _ok({'echo': payload}, meta={'handler': 'echo'})


async def _handle_llm_md(payload: Dict[str, Any], ctx: Dict[str, Any], v2: Dict[str, Any]) -> Dict[str, Any]:
    call_llm = ctx.get('call_llm')
    if not callable(call_llm):
        summary = [
            f'# {EMPLOYEE_LABEL} 执行方案',
            '',
            '宿主未注入 ctx.call_llm，本次以离线方案模式运行。',
            '',
            '## 输入',
            json.dumps(payload or {}, ensure_ascii=False, indent=2)[:3000],
            '',
            '## 下一步',
            '- 在宿主上下文注入 call_llm 后，可由 llm_md 生成完整 Markdown 结果。',
            '- 也可通过 payload.handler=echo 获取原始输入回显。',
        ]
        return _ok('\n'.join(summary), warnings=['ctx.call_llm unavailable; returned offline plan'], meta={'handler': 'llm_md', 'offline': True})
    cfg = _agent_model(v2)
    sys_prompt = cfg['system_prompt'] or SYSTEM_PROMPT
    if '##' not in sys_prompt:
        sys_prompt = sys_prompt + '\n\n请用 Markdown 输出，固定章节：\n' + DEFAULT_README_SECTIONS
    user_msg = json.dumps(payload or {}, ensure_ascii=False)[:6000]
    messages = [
        {'role': 'system', 'content': sys_prompt},
        {'role': 'user', 'content': user_msg},
    ]
    try:
        res = await asyncio.wait_for(
            call_llm(messages, max_tokens=cfg['max_tokens'], temperature=cfg['temperature']),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        return _err('LLM 调用超时（120s）', meta={'handler': 'llm_md'})
    except Exception as e:  # noqa: BLE001
        logger.exception('call_llm raised')
        return _err('LLM 调用异常：' + str(e)[:300], meta={'handler': 'llm_md'})
    if not isinstance(res, dict) or not res.get('ok'):
        return _err(str((res or {}).get('error') or 'LLM 调用失败')[:400], meta={'handler': 'llm_md'})
    content = str(res.get('content') or '').strip()
    return _ok(content, meta={'handler': 'llm_md', 'max_tokens': cfg['max_tokens']})


async def _handle_webhook(payload: Dict[str, Any], ctx: Dict[str, Any], v2: Dict[str, Any]) -> Dict[str, Any]:
    http_post = ctx.get('http_post')
    if not callable(http_post):
        return _err('ctx.http_post 不可用：宿主未注入 HTTP 能力', meta={'handler': 'webhook'})
    cfg = _actions(v2).get('webhook') if isinstance(_actions(v2).get('webhook'), dict) else {}
    url = str(cfg.get('url') or '').strip()
    if not url:
        return _err('actions.webhook.url 未配置', meta={'handler': 'webhook'})
    try:
        r = await asyncio.wait_for(http_post(url, json_body=payload or {}), timeout=30.0)
    except asyncio.TimeoutError:
        return _err('webhook 超时（30s）', meta={'handler': 'webhook', 'url': url})
    except Exception as e:  # noqa: BLE001
        return _err('webhook 异常：' + str(e)[:300], meta={'handler': 'webhook', 'url': url})
    if not isinstance(r, dict) or not r.get('ok'):
        return _err(str((r or {}).get('error') or f"HTTP {(r or {}).get('status')}"), meta={'handler': 'webhook', 'url': url})
    return _ok({'status': r.get('status'), 'text': r.get('text')}, meta={'handler': 'webhook', 'url': url})


async def _handle_agent(payload: Dict[str, Any], ctx: Dict[str, Any], v2: Dict[str, Any]) -> Dict[str, Any]:
    runner = ctx.get('agent_runner')
    if runner is None:
        return _err('ctx.agent_runner 未注入，请确认 modstore_server 版本', meta={'handler': 'agent'})
    cfg = _agent_model(v2)
    task = (
        payload.get('task') or payload.get('message') or payload.get('input')
        or json.dumps(payload or {}, ensure_ascii=False)[:2000]
    )
    sys_prompt = cfg['system_prompt'] or SYSTEM_PROMPT
    try:
        result = await asyncio.wait_for(
            runner.run(task, system_prompt=sys_prompt),
            timeout=300.0,
        )
    except asyncio.TimeoutError:
        return _err('agent 执行超时（300s）', meta={'handler': 'agent'})
    except Exception as e:  # noqa: BLE001
        logger.exception('agent run raised')
        return _err('agent 执行异常：' + str(e)[:300], meta={'handler': 'agent'})
    if not result.get('ok'):
        return _err(str(result.get('error') or 'agent 失败'), meta={'handler': 'agent', 'rounds': result.get('rounds', 0)})
    return _ok(
        result.get('summary') or '',
        meta={'handler': 'agent', 'rounds': result.get('rounds', 0),
              'tools_used': [t.get('tool') for t in (result.get('tool_calls') or [])]},
    )


_DISPATCH = {
    'echo': _handle_echo,
    'llm_md': _handle_llm_md,
    'webhook': _handle_webhook,
    'agent': _handle_agent,
}


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info('[employee:%s] run keys=%s', EMPLOYEE_ID, list((payload or {}).keys())[:12])
    payload = payload or {}
    ctx = ctx or {}
    manifest = _load_manifest()
    v2 = _v2(manifest)
    if not v2:
        return _err('manifest.employee_config_v2 缺失或不可读，无法决定行为',
                    meta={'employee_id': EMPLOYEE_ID})
    handlers = _handlers(_actions(v2))
    if not handlers:
        return _err('manifest.employee_config_v2.actions.handlers 未声明；请在打包时显式声明 echo / llm_md / webhook 之一',
                    meta={'employee_id': EMPLOYEE_ID})
    requested = str(payload.get('handler') or '').strip() if isinstance(payload, dict) else ''
    chosen = requested if requested in handlers else handlers[0]
    fn = _DISPATCH.get(chosen)
    if fn is None:
        return _err(f"不支持的 handler：{chosen}（支持：{sorted(_DISPATCH.keys())}）",
                    meta={'employee_id': EMPLOYEE_ID, 'declared_handlers': handlers})
    out = await fn(payload, ctx, v2)
    if isinstance(out, dict):
        meta = out.setdefault('meta', {})
        if isinstance(meta, dict):
            meta.setdefault('declared_handlers', handlers)
            meta.setdefault('chosen_handler', chosen)
    return out
