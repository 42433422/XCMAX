# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.mod_sdk.employee_specialized_tools")


async def tool_trigger_gh_workflow(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """通过 gh CLI 触发 GitHub Actions workflow（需 confirm）。"""
    if not params.get("confirm"):
        return _facade()._err("trigger_gh_workflow 需 confirm=true 确认", requires_confirm=True)
    workflow = str(params.get("workflow") or "").strip()
    if not workflow:
        return _facade()._err("缺少 workflow 参数")
    ref = str(params.get("ref") or "main")
    r = await _facade()._run_cmd(
        ["gh", "workflow", "run", workflow, "--ref", ref], cwd=_facade()._FHD_ROOT
    )
    return _facade()._ok(
        f"gh workflow run exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"],
        stderr=r["stderr"],
        passed=r["ok"],
    )


async def tool_nginx_test(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """nginx -t 语法检查。"""
    nginx = _facade().shutil.which("nginx")
    if not nginx:
        return _facade()._ok("nginx 未安装（跳过）", skipped=True, syntax_valid=None)
    r = await _facade()._run_cmd([nginx, "-t"])
    return _facade()._ok(
        f"nginx -t exit={r['returncode']}",
        returncode=r["returncode"],
        stdout=r["stdout"],
        stderr=r["stderr"],
        syntax_valid=r["ok"],
    )


async def tool_api_health(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """检查本机 API 健康。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call("GET", "/api/health", api_base=api_base)
    return _facade()._ok(f"health status={r.get('status')}", **r)


async def tool_mod_loading_status(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询 mod 加载状态。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call("GET", "/api/mods/loading-status", api_base=api_base)
    return _facade()._ok(f"loading-status status={r.get('status')}", **r)


async def tool_disk_usage(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """磁盘使用情况。"""
    r = await _facade()._run_cmd(["df", "-h", str(_facade()._FHD_ROOT)])
    return _facade()._ok("df -h", output=r["stdout"])


async def tool_tail_logs(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """读取最近 N 行日志。"""
    log_dir = _facade()._FHD_ROOT / "logs"
    if not log_dir.is_dir():
        return _facade()._ok("logs 目录不存在", lines=[])
    n = int(params.get("lines", 100))
    log_file = params.get("file") or "app.log"
    target = log_dir / log_file
    if not target.is_file():
        files = sorted(p.name for p in log_dir.glob("*.log"))
        return _facade()._ok(f"{log_file} 不存在", available_files=files)
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError as exc:
        return _facade()._err(f"读取日志失败: {exc}")
    return _facade()._ok(f"{len(lines)} 行", lines=lines)


async def tool_performance_status(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询性能状态。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call("GET", "/api/performance/status", api_base=api_base)
    return _facade()._ok(f"performance status={r.get('status')}", **r)


async def tool_list_mods(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """列出已加载 mods。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call("GET", "/api/mods/", api_base=api_base)
    return _facade()._ok(f"mods status={r.get('status')}", **r)


async def tool_list_employee_packs(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """扫描本地 _employees/ 目录，列出已安装员工包。"""
    packs: list[dict[str, _facade().Any]] = []
    if not _facade()._EMPLOYEES_DIR.is_dir():
        return _facade()._ok("_employees 目录不存在", packs=packs)
    for name in sorted(_facade().os.listdir(_facade()._EMPLOYEES_DIR)):
        mf = _facade()._EMPLOYEES_DIR / name / "manifest.json"
        if not mf.is_file():
            continue
        try:
            data = _facade().json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, _facade().json.JSONDecodeError):
            continue
        packs.append(
            {
                "id": data.get("id") or name,
                "label": data.get("name") or data.get("employee_label") or name,
                "artifact": data.get("artifact"),
                "area": (data.get("employee_config_v2") or {}).get("area"),
            }
        )
    return _facade()._ok(f"{len(packs)} 个员工包", packs=packs)


async def tool_validate_employee_pack(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """验证员工包 manifest 完整性。"""
    pack_id = str(params.get("pack_id") or "").strip()
    if not pack_id:
        return _facade()._err("缺少 pack_id 参数")
    mf = _facade()._EMPLOYEES_DIR / pack_id / "manifest.json"
    if not mf.is_file():
        return _facade()._err(f"manifest 不存在: {mf}")
    try:
        data = _facade().json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, _facade().json.JSONDecodeError) as exc:
        return _facade()._err(f"manifest 解析失败: {exc}")
    issues: list[str] = []
    if data.get("artifact") != "employee_pack":
        issues.append(f"artifact 应为 employee_pack，实际 {data.get('artifact')!r}")
    if not data.get("id"):
        issues.append("缺少 id")
    v2 = data.get("employee_config_v2") or {}
    if not isinstance(v2, dict):
        issues.append("缺少 employee_config_v2")
    else:
        cog = v2.get("cognition") or {}
        agent = cog.get("agent") or {}
        if not agent.get("system_prompt"):
            issues.append("缺少 system_prompt")
    return _facade()._ok(
        f"验证 {pack_id}: {('通过' if not issues else '有问题')}",
        valid=not issues,
        issues=issues,
        manifest=data,
    )


async def tool_duty_graph_health(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询 duty graph 健康（编制对账）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call("GET", "/api/xcmax/ops/duty-health", api_base=api_base)
    return _facade()._ok(f"duty-health status={r.get('status')}", **r)


async def tool_list_docs(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """列出项目文档。"""
    doc_dirs = [_facade()._FHD_ROOT / "docs", _facade()._FHD_ROOT.parent / "docs"]
    docs: list[str] = []
    for d in doc_dirs:
        if d.is_dir():
            docs.extend(str(p.relative_to(_facade()._FHD_ROOT.parent)) for p in d.rglob("*.md"))
    docs = sorted(set(docs))
    return _facade()._ok(f"{len(docs)} 个文档", docs=docs)


async def tool_read_file(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """读取文件内容（限项目内、限 50KB）。"""
    rel = str(params.get("path") or "").strip()
    if not rel:
        return _facade()._err("缺少 path 参数")
    target = (_facade()._FHD_ROOT / rel).resolve()
    try:
        target.relative_to(_facade()._FHD_ROOT)
    except ValueError:
        return _facade()._err("路径越界（仅限项目内）")
    if not target.is_file():
        return _facade()._err(f"文件不存在: {rel}")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _facade()._err(f"读取失败: {exc}")
    return _facade()._ok(
        f"{len(content)} 字符", content=content[:50000], path=rel, truncated=len(content) > 50000
    )


async def tool_list_scripts(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """列出项目脚本。"""
    scripts_dir = _facade()._FHD_ROOT / "scripts"
    if not scripts_dir.is_dir():
        return _facade()._ok("scripts 目录不存在", scripts=[])
    category = str(params.get("category") or "").strip()
    search_dir = scripts_dir / category if category else scripts_dir
    if not search_dir.is_dir():
        return _facade()._err(f"目录不存在: scripts/{category}")
    pys = sorted(str(p.relative_to(_facade()._FHD_ROOT)) for p in search_dir.rglob("*.py"))
    shs = sorted(str(p.relative_to(_facade()._FHD_ROOT)) for p in search_dir.rglob("*.sh"))
    return _facade()._ok(f"{len(pys)} py + {len(shs)} sh", python=pys, shell=shs)


async def tool_list_employees(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """列出全部编制员工（duty_roster.json）。"""
    if not _facade()._DUTY_ROSTER.is_file():
        return _facade()._err("duty_roster.json 不存在")
    try:
        roster = _facade().json.loads(_facade()._DUTY_ROSTER.read_text(encoding="utf-8"))
    except (OSError, _facade().json.JSONDecodeError) as exc:
        return _facade()._err(f"解析失败: {exc}")

    def _collect(blocks: dict[str, _facade().Any]) -> list[str]:
        ids: list[str] = []
        for block in blocks.values():
            if not isinstance(block, dict):
                continue
            raw = block.get("ids")
            if isinstance(raw, list):
                ids.extend(str(x).strip() for x in raw if str(x).strip())
            sub = block.get("subzones")
            if isinstance(sub, dict):
                ids.extend(_collect(sub))
        return ids

    planned: list[str] = []
    for key in ("areas", "departments"):
        planned.extend(_collect(roster.get(key) or {}))
    planned = sorted(set(planned))
    return _facade()._ok(f"{len(planned)} 个编制员工", employees=planned)


async def tool_employee_status(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询某员工状态。"""
    emp_id = str(params.get("employee_id") or ctx.get("employee_id") or "").strip()
    if not emp_id:
        return _facade()._err("缺少 employee_id")
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call(
        "GET", f"/api/xcmax/local/employees/{emp_id}/status", api_base=api_base
    )
    return _facade()._ok(f"employee {emp_id} status={r.get('status')}", employee_id=emp_id, **r)


async def tool_list_action_items(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询行动项。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call("GET", "/api/admin/action-items", api_base=api_base)
    return _facade()._ok(f"action-items status={r.get('status')}", **r)


async def tool_employee_autonomy_dashboard(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """查询员工自治仪表盘。"""
    api_base = params.get("api_base") or ctx.get("api_base") or _facade()._DEFAULT_API_BASE
    r = await _facade()._api_call(
        "GET", "/api/admin/employee-autonomy/dashboard", api_base=api_base
    )
    return _facade()._ok(f"autonomy dashboard status={r.get('status')}", **r)
