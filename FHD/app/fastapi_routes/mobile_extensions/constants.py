"""移动端 API 扩展 — 常量定义。"""

from __future__ import annotations

from typing import Any

ADMIN_MOBILE_FEATURES: list[dict[str, str]] = [
    {
        "id": "admin-status",
        "title": "管理驾驶舱",
        "description": "查看管理端运行状态、市场服务和关键健康指标。",
        "category": "overview",
        "method": "GET",
        "api_path": "/api/admin/status",
    },
    {
        "id": "admin-catalog",
        "title": "能力包目录",
        "description": "维护 MOD 与员工包上架、删除和目录同步。",
        "category": "catalog",
        "method": "GET",
        "api_path": "/api/admin/catalog",
    },
    {
        "id": "admin-duty-employees",
        "title": "值班员工池",
        "description": "查看管理端内部 duty AI 员工和岗位分区。",
        "category": "employees",
        "method": "GET",
        "api_path": "/api/mobile/v1/admin/employees",
    },
    {
        "id": "admin-duty-graph",
        "title": "值班拓扑",
        "description": "检查员工密钥、执行拓扑和 duty graph 健康状态。",
        "category": "employees",
        "method": "GET",
        "api_path": "/api/admin/duty-graph/health",
    },
    {
        "id": "admin-execution-capability",
        "title": "执行能力矩阵",
        "description": "汇总 AI 员工的执行能力、工具权限和运行边界。",
        "category": "employees",
        "method": "POST",
        "api_path": "/api/admin/employees/execution-capabilities",
    },
    {
        "id": "admin-autonomy-dashboard",
        "title": "自治任务看板",
        "description": "查看员工自治建议、简报任务和最近调度结果。",
        "category": "automation",
        "method": "GET",
        "api_path": "/api/admin/employee-autonomy/dashboard",
    },
    {
        "id": "admin-autonomy-suggestions",
        "title": "自治建议审核",
        "description": "审核员工提出的自动化建议和派发结果。",
        "category": "automation",
        "method": "GET",
        "api_path": "/api/admin/employee-autonomy/suggestions",
    },
    {
        "id": "admin-change-requests",
        "title": "变更请求",
        "description": "审批管理端变更请求并追踪执行状态。",
        "category": "governance",
        "method": "GET",
        "api_path": "/api/admin/change-requests",
    },
    {
        "id": "admin-ai-accounts",
        "title": "AI 账号池",
        "description": "管理模型账号、密钥轮换和可用性标记。",
        "category": "accounts",
        "method": "GET",
        "api_path": "/api/admin/ai-accounts",
    },
    {
        "id": "admin-users",
        "title": "用户与企业授权",
        "description": "管理用户、企业标记、管理员权限与可分配 MOD。",
        "category": "users",
        "method": "GET",
        "api_path": "/api/admin/users",
    },
    {
        "id": "admin-user-mods",
        "title": "企业 MOD 授权",
        "description": "查看和调整企业用户可用的 MOD 与能力包。",
        "category": "users",
        "method": "GET",
        "api_path": "/api/admin/users/{user_id}/mods",
    },
    {
        "id": "admin-wallets",
        "title": "钱包与交易",
        "description": "查看钱包余额、交易流水和账单核对状态。",
        "category": "billing",
        "method": "GET",
        "api_path": "/api/admin/wallets",
    },
    {
        "id": "admin-action-items",
        "title": "运维待办",
        "description": "跟踪管理端待办、Digest 事项和处理统计。",
        "category": "ops",
        "method": "GET",
        "api_path": "/api/admin/action-items",
    },
    {
        "id": "admin-ops-audit",
        "title": "操作审计",
        "description": "查看管理端关键操作、审批令牌和 staged changes。",
        "category": "ops",
        "method": "GET",
        "api_path": "/api/admin/ops/audit",
    },
]

_MARKET_AI_EMPLOYEE_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "profiles": {},
    "connected": False,
    "error": "",
}
