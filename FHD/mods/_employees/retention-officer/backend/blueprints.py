"""employee_pack HTTP 面（MODstore 生成）。"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)

EMPLOYEE_ID = "retention-officer"
STEM = "retention_officer"
LABEL = "档案清理员"


def _resolve_mod_path(mod_id: str) -> Optional[str]:
    try:
        from app.infrastructure.mods import get_mod_registry  # type: ignore

        meta = get_mod_registry().get_mod_metadata(mod_id)
        mp = getattr(meta, 'mod_path', '') or ''
        if mp and os.path.isdir(mp):
            return mp
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    guess = os.path.dirname(here)
    return guess if os.path.isdir(guess) else None


def _load_employee_module(mod_id: str, stem: str):
    try:
        from app.mod_sdk.mods_bus import import_mod_backend_py  # type: ignore
    except ImportError:
        return None
    mod_path = _resolve_mod_path(mod_id)
    if not mod_path:
        return None
    try:
        return import_mod_backend_py(mod_path, mod_id, f"employees/{stem}")
    except Exception:
        logger.exception('load employee module failed stem=%s', stem)
        return None


def _unified_err(msg: str, **meta):
    return {
        'success': False,
        'data': {
            'ok': False,
            'summary': msg[:400],
            'items': [],
            'warnings': [],
            'error': msg[:1000],
            'meta': meta,
        },
        'error': msg[:500],
    }


async def _dispatch_run(mod_id: str, emp_id: str, stem: str, payload: Optional[Dict[str, Any]]):
    module = _load_employee_module(mod_id, stem)
    if module is None or not hasattr(module, 'run'):
        return _unified_err(
            'employee module not loaded：请确认 backend/employees 下存在对应 .py 并实现 async def run',
            employee_id=emp_id, stem=stem,
        )
    ctx = {
        'mod_id': mod_id,
        'employee_id': emp_id,
        'logger': logging.getLogger(f'mod.{mod_id}.emp.{emp_id}'),
        'call_llm': None,
        'http_get': None,
        'http_post': None,
        'secrets': None,
    }
    call_llm_available = False
    try:
        from app.mod_sdk.mod_employee_llm import mod_employee_complete  # type: ignore

        async def _call_llm(messages, *, max_tokens=1024, temperature=0.2, response_format=None):
            return await mod_employee_complete(
                messages, max_tokens=max_tokens, temperature=temperature, response_format=response_format
            )

        ctx['call_llm'] = _call_llm
        call_llm_available = True
    except Exception as _e:
        logger.warning('mod_employee_complete 不可用，call_llm 将使用降级：%s', _e)
    if not call_llm_available:
        async def _call_llm_disabled(messages, **kwargs):
            return {'ok': False, 'content': '', 'error': '宿主 LLM 服务不可用（mod_employee_complete 导入失败），请检查 API Key 与 mod_employee_llm 配置'}
        ctx['call_llm'] = _call_llm_disabled
    try:
        import httpx as _httpx

        async def _http_get(url, *, headers=None, timeout=30):
            try:
                async with _httpx.AsyncClient(timeout=float(timeout)) as _c:
                    r = await _c.get(url, headers=headers or {})
                    return {'ok': r.status_code < 400, 'status': r.status_code, 'text': r.text, 'error': ''}
            except Exception as _e:
                return {'ok': False, 'status': 0, 'text': '', 'error': str(_e)[:500]}

        async def _http_post(url, *, json_body=None, data=None, headers=None, timeout=30):
            try:
                async with _httpx.AsyncClient(timeout=float(timeout)) as _c:
                    r = await _c.post(url, json=json_body, data=data, headers=headers or {})
                    return {'ok': r.status_code < 400, 'status': r.status_code, 'text': r.text, 'error': ''}
            except Exception as _e:
                return {'ok': False, 'status': 0, 'text': '', 'error': str(_e)[:500]}

        ctx['http_get'] = _http_get
        ctx['http_post'] = _http_post
    except ImportError:
        logger.warning('httpx 不可用，http_get/http_post 使用降级')

        async def _http_disabled(url, **kwargs):
            return {'ok': False, 'status': 0, 'text': '', 'error': 'httpx 未安装，HTTP 请求不可用'}

        ctx['http_get'] = _http_disabled
        ctx['http_post'] = _http_disabled
    _workspace_root = (
        os.environ.get('EMPLOYEE_WORKSPACE_ROOT', '')
        or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'workspace'))
    )
    os.makedirs(_workspace_root, exist_ok=True)
    ctx['workspace_root'] = _workspace_root

    def _guard(_p):
        resolved = os.path.normpath(os.path.join(_workspace_root, _p))
        if not resolved.startswith(os.path.abspath(_workspace_root) + os.sep) and resolved != os.path.abspath(_workspace_root):
            return None
        return resolved

    async def _read_workspace_file(path):
        r = _guard(path)
        if r is None:
            return {'ok': False, 'error': '路径越界'}
        if not os.path.isfile(r):
            return {'ok': False, 'error': f'文件不存在: {path!r}'}
        try:
            txt = open(r, encoding='utf-8', errors='replace').read()
            return {'ok': True, 'path': path, 'content': txt[:8000], 'truncated': len(txt) > 8000, 'total_chars': len(txt)}
        except OSError as e:
            return {'ok': False, 'error': str(e)[:300]}

    async def _write_workspace_file(path, content):
        r = _guard(path)
        if r is None:
            return {'ok': False, 'error': '路径越界'}
        try:
            os.makedirs(os.path.dirname(r) or '.', exist_ok=True)
            open(r, 'w', encoding='utf-8').write(content or '')
            return {'ok': True, 'path': path, 'bytes_written': len((content or '').encode())}
        except OSError as e:
            return {'ok': False, 'error': str(e)[:300]}

    async def _list_workspace_dir(path='.'):
        r = _guard(path)
        if r is None:
            return {'ok': False, 'error': '路径越界'}
        if not os.path.isdir(r):
            return {'ok': False, 'error': f'目录不存在: {path!r}'}
        skip = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build'}
        entries = []
        for name in sorted(os.listdir(r))[:50]:
            if name in skip: continue
            full = os.path.join(r, name)
            entries.append({'name': name, 'type': 'dir' if os.path.isdir(full) else 'file',
                            'size': 0 if os.path.isdir(full) else os.path.getsize(full)})
        return {'ok': True, 'path': path, 'entries': entries}

    import subprocess as _sp
    async def _run_sandboxed_python(code, timeout=10.0):
        import re as _re
        if _re.search(r'\b(import\s+subprocess|import\s+socket|open\s*\(|__import__|exec\s*\(|eval\s*\()\b', code):
            return {'ok': False, 'error': '代码包含不允许的操作'}
        try:
            p = _sp.run(['python', '-c', code], capture_output=True, text=True, timeout=float(timeout),
                        env={k: v for k, v in os.environ.items() if k in ('PATH', 'PYTHONPATH', 'TEMP', 'TMP')})
            return {'ok': p.returncode == 0, 'stdout': p.stdout[:2000], 'stderr': p.stderr[:500], 'returncode': p.returncode}
        except _sp.TimeoutExpired:
            return {'ok': False, 'error': f'执行超时（{timeout:.0f}s）'}
        except Exception as e:
            return {'ok': False, 'error': str(e)[:300]}

    ctx['read_workspace_file'] = _read_workspace_file
    ctx['write_workspace_file'] = _write_workspace_file
    ctx['list_workspace_dir'] = _list_workspace_dir
    ctx['run_sandboxed_python'] = _run_sandboxed_python

    try:
        from modstore_server.mod_employee_agent_runner import build_agent_runner  # type: ignore
        ctx['agent_runner'] = build_agent_runner(ctx)
    except Exception as _ar_err:
        logger.warning('agent_runner 不可用：%s', _ar_err)
        ctx['agent_runner'] = None

    try:
        run_fn = getattr(module, 'run')
        out = run_fn(payload or {}, ctx)
        if asyncio.iscoroutine(out):
            out = await out
        return {'success': True, 'data': out}
    except Exception as e:  # noqa: BLE001
        logger.exception('employee run failed')
        return _unified_err('employee run failed: ' + str(e)[:300], employee_id=emp_id)


def register_fastapi_routes(app, mod_id: str) -> None:
    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"emp-pack-{mod_id}"])
    emp_id = EMPLOYEE_ID
    stem = STEM

    @router.get('/employees')
    async def list_employees():
        return {'success': True, 'data': [{'id': emp_id, 'label': LABEL, 'summary': ''}]}

    @router.post('/employees/' + emp_id + '/run')
    async def emp_run(payload: Dict[str, Any] | None = None):
        return await _dispatch_run(mod_id, emp_id, stem, payload)

    @router.get('/employees/' + emp_id + '/status')
    async def emp_status():
        return {'success': True, 'data': {'employee_id': emp_id, 'status': 'ready'}}

    app.include_router(router)
    logger.info("employee_pack routes registered mod_id=%s emp=%s", mod_id, emp_id)


def mod_init():
    logger.info('employee_pack backend init')
