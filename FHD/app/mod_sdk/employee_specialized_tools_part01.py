# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.mod_sdk.employee_specialized_tools')

def _ok(summary: str, **extra: _facade().Any) -> dict[str, _facade().Any]:
    out: dict[str, _facade().Any] = {'ok': True, 'summary': summary[:4000]}
    out.update(extra)
    return out

def _err(error: str, **extra: _facade().Any) -> dict[str, _facade().Any]:
    out: dict[str, _facade().Any] = {'ok': False, 'error': error[:1000]}
    out.update(extra)
    return out

async def _run_cmd(args: list[str], *, cwd: str | _facade().Path | None=None, timeout: int=_facade()._DEFAULT_TIMEOUT, env: dict[str, str] | None=None) -> dict[str, _facade().Any]:
    """执行命令并返回结构化结果。"""
    proc: _facade().asyncio.subprocess.Process | None = None
    try:
        proc = await _facade().asyncio.create_subprocess_exec(*args, cwd=str(cwd) if cwd else None, stdout=_facade().asyncio.subprocess.PIPE, stderr=_facade().asyncio.subprocess.PIPE, env={**_facade().os.environ, **(env or {})})
        communication = proc.communicate()
        try:
            (stdout_b, stderr_b) = await _facade().asyncio.wait_for(communication, timeout=timeout)
        finally:
            if _facade().inspect.iscoroutine(communication):
                communication.close()
        stdout = stdout_b.decode('utf-8', errors='replace') if stdout_b else ''
        stderr = stderr_b.decode('utf-8', errors='replace') if stderr_b else ''
        return {'returncode': proc.returncode, 'stdout': stdout, 'stderr': stderr, 'ok': proc.returncode == 0}
    except TimeoutError:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        return {'returncode': -1, 'stdout': '', 'stderr': f'timeout after {timeout}s', 'ok': False}
    except FileNotFoundError as exc:
        return {'returncode': -1, 'stdout': '', 'stderr': str(exc), 'ok': False}
    except _facade().RECOVERABLE_ERRORS as exc:
        return {'returncode': -1, 'stdout': '', 'stderr': repr(exc), 'ok': False}

async def _run_python_script(script: str | _facade().Path, *extra_args: str, **kw: _facade().Any) -> dict[str, _facade().Any]:
    """用项目 venv python 跑一个脚本。"""
    return await _facade()._run_cmd([_facade()._PYTHON, str(script), *extra_args], **kw)

async def _api_call(method: str, path: str, *, api_base: str | None=None, **kw: _facade().Any) -> dict[str, _facade().Any]:
    if _facade().httpx is None:
        return {'ok': False, 'error': 'httpx 未安装'}
    base = (api_base or _facade()._DEFAULT_API_BASE).rstrip('/')
    url = f'{base}{path}' if path.startswith('/') else f'{base}/{path}'
    try:
        async with _facade().httpx.AsyncClient(timeout=kw.pop('timeout', 30)) as client:
            resp = await client.request(method, url, **kw)
            try:
                body = resp.json()
            except _facade().RECOVERABLE_ERRORS:
                body = resp.text
            return {'ok': resp.is_success, 'status': resp.status_code, 'body': body}
    except _facade().RECOVERABLE_ERRORS as exc:
        return {'ok': False, 'error': repr(exc)}

async def tool_run_pytest(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """运行 pytest 测试套件。"""
    args = params.get('args') or ['tests/', '-q', '--tb=short']
    if isinstance(args, str):
        args = args.split()
    env = {'XCAGI_SKIP_LEGACY_COMPAT_ROUTES': '1'}
    extra_env = params.get('env') or {}
    if isinstance(extra_env, dict):
        env.update(extra_env)
    r = await _facade()._run_cmd([_facade()._PYTHON, '-m', 'pytest', *[str(a) for a in args]], cwd=_facade()._FHD_ROOT, timeout=int(params.get('timeout', 600)), env=env)
    return _facade()._ok(f"pytest exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-8000:], stderr=r['stderr'][-4000:], passed=r['ok'])

async def tool_run_ruff_check(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """运行 ruff lint 检查。"""
    targets = params.get('targets') or ['app/', 'tests/']
    if isinstance(targets, str):
        targets = targets.split()
    r = await _facade()._run_cmd([_facade()._PYTHON, '-m', 'ruff', 'check', *[str(t) for t in targets]], cwd=_facade()._FHD_ROOT)
    return _facade()._ok(f"ruff check exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-6000:], stderr=r['stderr'][-3000:], passed=r['ok'])

async def tool_run_ruff_format(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """运行 ruff format 检查。"""
    targets = params.get('targets') or ['app/', 'tests/']
    if isinstance(targets, str):
        targets = targets.split()
    r = await _facade()._run_cmd([_facade()._PYTHON, '-m', 'ruff', 'format', '--check', *[str(t) for t in targets]], cwd=_facade()._FHD_ROOT)
    return _facade()._ok(f"ruff format exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-4000:], stderr=r['stderr'][-2000:], passed=r['ok'])

async def tool_run_mypy(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """运行 mypy 类型检查。"""
    targets = params.get('targets') or ['app/']
    if isinstance(targets, str):
        targets = targets.split()
    r = await _facade()._run_cmd([_facade()._PYTHON, '-m', 'mypy', *[str(t) for t in targets]], cwd=_facade()._FHD_ROOT, timeout=300)
    return _facade()._ok(f"mypy exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-8000:], stderr=r['stderr'][-4000:], passed=r['ok'])

async def tool_check_coverage(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """检查覆盖率棘轮（只升不降）。"""
    r = await _facade()._run_python_script(_facade()._SCRIPTS / 'dev' / 'coverage_ratchet.py', '--check', cwd=_facade()._FHD_ROOT)
    return _facade()._ok(f"coverage ratchet exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-4000:], stderr=r['stderr'][-2000:], passed=r['ok'])

async def tool_count_type_debt(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """统计类型债务。"""
    r = await _facade()._run_python_script(_facade()._SCRIPTS / 'dev' / 'count_type_debt.py', cwd=_facade()._FHD_ROOT)
    return _facade()._ok(f"type debt exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-4000:], stderr=r['stderr'][-2000:], passed=r['ok'])

async def tool_count_raw_sql(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """统计 SQL 债务。"""
    r = await _facade()._run_python_script(_facade()._SCRIPTS / 'dev' / 'count_raw_sql.py', cwd=_facade()._FHD_ROOT)
    return _facade()._ok(f"raw sql exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-4000:], stderr=r['stderr'][-2000:], passed=r['ok'])

async def tool_run_arch_fitness(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """运行架构适配度检查。"""
    r = await _facade()._run_python_script(_facade()._FHD_ROOT / 'scripts' / 'arch_fitness.py', cwd=_facade()._FHD_ROOT)
    return _facade()._ok(f"arch fitness exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-6000:], stderr=r['stderr'][-3000:], passed=r['ok'])

async def tool_verify_version_anchors(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """校验版本锚点。"""
    r = await _facade()._run_python_script(_facade()._SCRIPTS / 'dev' / 'verify_version_anchors.py', cwd=_facade()._FHD_ROOT)
    return _facade()._ok(f"version anchors exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-4000:], stderr=r['stderr'][-2000:], passed=r['ok'])

async def tool_verify_employee_contract(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """验证员工契约。"""
    r = await _facade()._run_python_script(_facade()._SCRIPTS / 'dev' / 'verify_employee_contract.py', cwd=_facade()._FHD_ROOT)
    return _facade()._ok(f"employee contract exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-6000:], stderr=r['stderr'][-3000:], passed=r['ok'])

async def tool_mutation_kill_report(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """变异测试杀死率报告。"""
    r = await _facade()._run_python_script(_facade()._SCRIPTS / 'dev' / 'mutation_kill_report.py', cwd=_facade()._FHD_ROOT, timeout=600)
    return _facade()._ok(f"mutation kill exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-6000:], stderr=r['stderr'][-3000:], passed=r['ok'])

async def tool_git_status(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """git status --porcelain。"""
    r = await _facade()._run_cmd(['git', 'status', '--porcelain'], cwd=_facade()._FHD_ROOT)
    lines = [l for l in r['stdout'].splitlines() if l.strip()]
    return _facade()._ok(f'{len(lines)} 个变更', files=lines, clean=len(lines) == 0, raw=r['stdout'])

async def tool_git_log(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """git log --oneline。"""
    n = str(params.get('n', 20))
    r = await _facade()._run_cmd(['git', 'log', '--oneline', f'-{n}'], cwd=_facade()._FHD_ROOT)
    commits = [l for l in r['stdout'].splitlines() if l.strip()]
    return _facade()._ok(f'最近 {len(commits)} 条提交', commits=commits)

async def tool_git_diff(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """git diff（unstaged 或指定 ref）。"""
    ref = params.get('ref') or ''
    args = ['git', 'diff', *([ref] if ref else [])]
    if params.get('stat'):
        args.append('--stat')
    r = await _facade()._run_cmd(args, cwd=_facade()._FHD_ROOT)
    return _facade()._ok('git diff', diff=r['stdout'][-8000:], returncode=r['returncode'])

async def tool_git_branch(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """当前分支名。"""
    r = await _facade()._run_cmd(['git', 'branch', '--show-current'], cwd=_facade()._FHD_ROOT)
    return _facade()._ok(f"branch={r['stdout'].strip()}", branch=r['stdout'].strip())

async def tool_pack_release(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """打包发布 tarball（需 confirm）。"""
    if not params.get('confirm'):
        return _facade()._err('pack_release 需 confirm=true 确认', requires_confirm=True)
    script = _facade()._FHD_ROOT / 'scripts' / 'deploy' / 'fhd-pack-release.sh'
    r = await _facade()._run_cmd(['bash', str(script)], cwd=_facade()._FHD_ROOT, timeout=600)
    return _facade()._ok(f"pack exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'][-6000:], stderr=r['stderr'][-3000:], passed=r['ok'])

async def tool_list_deploy_scripts(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """列出部署脚本。"""
    deploy_dir = _facade()._FHD_ROOT / 'scripts' / 'deploy'
    scripts = sorted((p.name for p in deploy_dir.glob('*.sh'))) if deploy_dir.is_dir() else []
    return _facade()._ok(f'{len(scripts)} 个部署脚本', scripts=scripts)

async def tool_trigger_gh_workflow(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """通过 gh CLI 触发 GitHub Actions workflow（需 confirm）。"""
    if not params.get('confirm'):
        return _facade()._err('trigger_gh_workflow 需 confirm=true 确认', requires_confirm=True)
    workflow = str(params.get('workflow') or '').strip()
    if not workflow:
        return _facade()._err('缺少 workflow 参数')
    ref = str(params.get('ref') or 'main')
    r = await _facade()._run_cmd(['gh', 'workflow', 'run', workflow, '--ref', ref], cwd=_facade()._FHD_ROOT)
    return _facade()._ok(f"gh workflow run exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'], stderr=r['stderr'], passed=r['ok'])

async def tool_nginx_test(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """nginx -t 语法检查。"""
    nginx = _facade().shutil.which('nginx')
    if not nginx:
        return _facade()._ok('nginx 未安装（跳过）', skipped=True, syntax_valid=None)
    r = await _facade()._run_cmd([nginx, '-t'])
    return _facade()._ok(f"nginx -t exit={r['returncode']}", returncode=r['returncode'], stdout=r['stdout'], stderr=r['stderr'], syntax_valid=r['ok'])

async def tool_api_health(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """检查本机 API 健康。"""
    api_base = params.get('api_base') or ctx.get('api_base') or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call('GET', '/api/health', api_base=api_base)
    return _facade()._ok(f"health status={r.get('status')}", **r)

async def tool_mod_loading_status(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """查询 mod 加载状态。"""
    api_base = params.get('api_base') or ctx.get('api_base') or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call('GET', '/api/mods/loading-status', api_base=api_base)
    return _facade()._ok(f"loading-status status={r.get('status')}", **r)

async def tool_disk_usage(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """磁盘使用情况。"""
    r = await _facade()._run_cmd(['df', '-h', str(_facade()._FHD_ROOT)])
    return _facade()._ok('df -h', output=r['stdout'])

async def tool_tail_logs(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """读取最近 N 行日志。"""
    log_dir = _facade()._FHD_ROOT / 'logs'
    if not log_dir.is_dir():
        return _facade()._ok('logs 目录不存在', lines=[])
    n = int(params.get('lines', 100))
    log_file = params.get('file') or 'app.log'
    target = log_dir / log_file
    if not target.is_file():
        files = sorted((p.name for p in log_dir.glob('*.log')))
        return _facade()._ok(f'{log_file} 不存在', available_files=files)
    try:
        lines = target.read_text(encoding='utf-8', errors='replace').splitlines()[-n:]
    except OSError as exc:
        return _facade()._err(f'读取日志失败: {exc}')
    return _facade()._ok(f'{len(lines)} 行', lines=lines)

async def tool_performance_status(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """查询性能状态。"""
    api_base = params.get('api_base') or ctx.get('api_base') or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call('GET', '/api/performance/status', api_base=api_base)
    return _facade()._ok(f"performance status={r.get('status')}", **r)

async def tool_list_mods(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """列出已加载 mods。"""
    api_base = params.get('api_base') or ctx.get('api_base') or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call('GET', '/api/mods/', api_base=api_base)
    return _facade()._ok(f"mods status={r.get('status')}", **r)

async def tool_list_employee_packs(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """扫描本地 _employees/ 目录，列出已安装员工包。"""
    packs: list[dict[str, _facade().Any]] = []
    if not _facade()._EMPLOYEES_DIR.is_dir():
        return _facade()._ok('_employees 目录不存在', packs=packs)
    for name in sorted(_facade().os.listdir(_facade()._EMPLOYEES_DIR)):
        mf = _facade()._EMPLOYEES_DIR / name / 'manifest.json'
        if not mf.is_file():
            continue
        try:
            data = _facade().json.loads(mf.read_text(encoding='utf-8'))
        except (OSError, _facade().json.JSONDecodeError):
            continue
        packs.append({'id': data.get('id') or name, 'label': data.get('name') or data.get('employee_label') or name, 'artifact': data.get('artifact'), 'area': (data.get('employee_config_v2') or {}).get('area')})
    return _facade()._ok(f'{len(packs)} 个员工包', packs=packs)

async def tool_validate_employee_pack(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """验证员工包 manifest 完整性。"""
    pack_id = str(params.get('pack_id') or '').strip()
    if not pack_id:
        return _facade()._err('缺少 pack_id 参数')
    mf = _facade()._EMPLOYEES_DIR / pack_id / 'manifest.json'
    if not mf.is_file():
        return _facade()._err(f'manifest 不存在: {mf}')
    try:
        data = _facade().json.loads(mf.read_text(encoding='utf-8'))
    except (OSError, _facade().json.JSONDecodeError) as exc:
        return _facade()._err(f'manifest 解析失败: {exc}')
    issues: list[str] = []
    if data.get('artifact') != 'employee_pack':
        issues.append(f"artifact 应为 employee_pack，实际 {data.get('artifact')!r}")
    if not data.get('id'):
        issues.append('缺少 id')
    v2 = data.get('employee_config_v2') or {}
    if not isinstance(v2, dict):
        issues.append('缺少 employee_config_v2')
    else:
        cog = v2.get('cognition') or {}
        agent = cog.get('agent') or {}
        if not agent.get('system_prompt'):
            issues.append('缺少 system_prompt')
    return _facade()._ok(f"验证 {pack_id}: {('通过' if not issues else '有问题')}", valid=not issues, issues=issues, manifest=data)

async def tool_duty_graph_health(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """查询 duty graph 健康（编制对账）。"""
    api_base = params.get('api_base') or ctx.get('api_base') or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call('GET', '/api/xcmax/ops/duty-health', api_base=api_base)
    return _facade()._ok(f"duty-health status={r.get('status')}", **r)

async def tool_list_docs(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """列出项目文档。"""
    doc_dirs = [_facade()._FHD_ROOT / 'docs', _facade()._FHD_ROOT.parent / 'docs']
    docs: list[str] = []
    for d in doc_dirs:
        if d.is_dir():
            docs.extend((str(p.relative_to(_facade()._FHD_ROOT.parent)) for p in d.rglob('*.md')))
    docs = sorted(set(docs))
    return _facade()._ok(f'{len(docs)} 个文档', docs=docs)

async def tool_read_file(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """读取文件内容（限项目内、限 50KB）。"""
    rel = str(params.get('path') or '').strip()
    if not rel:
        return _facade()._err('缺少 path 参数')
    target = (_facade()._FHD_ROOT / rel).resolve()
    try:
        target.relative_to(_facade()._FHD_ROOT)
    except ValueError:
        return _facade()._err('路径越界（仅限项目内）')
    if not target.is_file():
        return _facade()._err(f'文件不存在: {rel}')
    try:
        content = target.read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        return _facade()._err(f'读取失败: {exc}')
    return _facade()._ok(f'{len(content)} 字符', content=content[:50000], path=rel, truncated=len(content) > 50000)

async def tool_list_scripts(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """列出项目脚本。"""
    scripts_dir = _facade()._FHD_ROOT / 'scripts'
    if not scripts_dir.is_dir():
        return _facade()._ok('scripts 目录不存在', scripts=[])
    category = str(params.get('category') or '').strip()
    search_dir = scripts_dir / category if category else scripts_dir
    if not search_dir.is_dir():
        return _facade()._err(f'目录不存在: scripts/{category}')
    pys = sorted((str(p.relative_to(_facade()._FHD_ROOT)) for p in search_dir.rglob('*.py')))
    shs = sorted((str(p.relative_to(_facade()._FHD_ROOT)) for p in search_dir.rglob('*.sh')))
    return _facade()._ok(f'{len(pys)} py + {len(shs)} sh', python=pys, shell=shs)

async def tool_list_employees(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """列出全部编制员工（duty_roster.json）。"""
    if not _facade()._DUTY_ROSTER.is_file():
        return _facade()._err('duty_roster.json 不存在')
    try:
        roster = _facade().json.loads(_facade()._DUTY_ROSTER.read_text(encoding='utf-8'))
    except (OSError, _facade().json.JSONDecodeError) as exc:
        return _facade()._err(f'解析失败: {exc}')

    def _collect(blocks: dict[str, _facade().Any]) -> list[str]:
        ids: list[str] = []
        for block in blocks.values():
            if not isinstance(block, dict):
                continue
            raw = block.get('ids')
            if isinstance(raw, list):
                ids.extend((str(x).strip() for x in raw if str(x).strip()))
            sub = block.get('subzones')
            if isinstance(sub, dict):
                ids.extend(_collect(sub))
        return ids
    planned: list[str] = []
    for key in ('areas', 'departments'):
        planned.extend(_collect(roster.get(key) or {}))
    planned = sorted(set(planned))
    return _facade()._ok(f'{len(planned)} 个编制员工', employees=planned)

async def tool_employee_status(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """查询某员工状态。"""
    emp_id = str(params.get('employee_id') or ctx.get('employee_id') or '').strip()
    if not emp_id:
        return _facade()._err('缺少 employee_id')
    api_base = params.get('api_base') or ctx.get('api_base') or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call('GET', f'/api/xcmax/local/employees/{emp_id}/status', api_base=api_base)
    return _facade()._ok(f"employee {emp_id} status={r.get('status')}", employee_id=emp_id, **r)

async def tool_list_action_items(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """查询行动项。"""
    api_base = params.get('api_base') or ctx.get('api_base') or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call('GET', '/api/admin/action-items', api_base=api_base)
    return _facade()._ok(f"action-items status={r.get('status')}", **r)

async def tool_employee_autonomy_dashboard(params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """查询员工自治仪表盘。"""
    api_base = params.get('api_base') or ctx.get('api_base') or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call('GET', '/api/admin/employee-autonomy/dashboard', api_base=api_base)
    return _facade()._ok(f"autonomy dashboard status={r.get('status')}", **r)
