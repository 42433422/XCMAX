"""Host read models obtained through an injected API request boundary."""

from __future__ import annotations

from .ports import Payload, StatusPorts
from .results import _err, _ok


async def api_health(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """检查本机 API 健康。"""
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    r = await ports.request("GET", "/api/health", api_base=api_base)
    return _ok(f"health status={r.get('status')}", **r)


async def mod_loading_status(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """查询 mod 加载状态。"""
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    r = await ports.request("GET", "/api/mods/loading-status", api_base=api_base)
    return _ok(f"loading-status status={r.get('status')}", **r)


async def performance_status(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """查询性能状态。"""
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    r = await ports.request("GET", "/api/performance/status", api_base=api_base)
    return _ok(f"performance status={r.get('status')}", **r)


async def list_mods(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """列出已加载 mods。"""
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    r = await ports.request("GET", "/api/mods/", api_base=api_base)
    return _ok(f"mods status={r.get('status')}", **r)


async def duty_graph_health(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """查询 duty graph 健康（编制对账）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    r = await ports.request("GET", "/api/xcmax/ops/duty-health", api_base=api_base)
    return _ok(f"duty-health status={r.get('status')}", **r)


async def employee_status(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """查询某员工状态。"""
    emp_id = str(params.get("employee_id") or ctx.get("employee_id") or "").strip()
    if not emp_id:
        return _err("缺少 employee_id")
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    r = await ports.request("GET", f"/api/xcmax/local/employees/{emp_id}/status", api_base=api_base)
    return _ok(f"employee {emp_id} status={r.get('status')}", employee_id=emp_id, **r)


async def list_action_items(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """查询行动项。"""
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    r = await ports.request("GET", "/api/admin/action-items", api_base=api_base)
    return _ok(f"action-items status={r.get('status')}", **r)


async def employee_autonomy_dashboard(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """查询员工自治仪表盘。"""
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    r = await ports.request("GET", "/api/admin/employee-autonomy/dashboard", api_base=api_base)
    return _ok(f"autonomy dashboard status={r.get('status')}", **r)


async def check_transactions(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """查询交易记录（只读，调内部 API）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    limit = int(params.get("limit", 50))
    r = await ports.request("GET", "/api/admin/wallets", api_base=api_base, params={"limit": limit})
    return _ok(f"wallets status={r.get('status')}", **r)


async def list_invoices(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """查询发票记录（只读）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    r = await ports.request("GET", "/api/admin/invoices", api_base=api_base)
    return _ok(f"invoices status={r.get('status')}", **r)


async def list_enterprise_mods(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """查询企业可分配 mods。"""
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    r = await ports.request("GET", "/api/admin/enterprise/assignable-mods", api_base=api_base)
    return _ok(f"enterprise mods status={r.get('status')}", **r)


async def list_users(ports: StatusPorts, params: Payload, ctx: Payload) -> Payload:
    """查询用户列表（只读）。"""
    api_base = params.get("api_base") or ctx.get("api_base") or ports.api_base
    r = await ports.request("GET", "/api/admin/users", api_base=api_base)
    return _ok(f"users status={r.get('status')}", **r)
