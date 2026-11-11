# 通用化 XCAGI 宿主壳（阶段 4）

## 原则

| 概念 | 放哪里 |
|------|--------|
| **Mod（房子）** | 行业包、桥接包、含菜单/路由的业务扩展 |
| **员工（家具）** | `workflow_employees` 或 `employee_pack` 内单名员工 |
| **宿主壳** | 启动、ModManager、`app/mod_sdk`、本文件所列 API |

新业务 **不得** 再往 `frontend/src/data/workflow-employees.json` 写死员工；应做 Mod 或 `employee_pack`。

## 宿主保留 API（底座）

见 `app/mod_sdk/platform_shell.py` → `PLATFORM_SHELL_API_PREFIXES`。

## 桥接 Mod（边界标记，逻辑仍在宿主）

| Mod id | 宿主 API |
|--------|----------|
| `xcagi-approval-bridge` | `/api/approval/*` |
| `xcagi-lan-license-bridge` | `/api/lan/*` |
| `xcagi-model-payment-bridge` | `/api/model-payment/*` |
| `xcagi-planner-bridge` | `/api/ai/chat`, `/api/ai/intent` |

## 受保护客户 Mod

`taiyangniao-pro`、`sz-qsm-pro` — 见平台 [PROTECTED_MODS.md](../../../成都修茈科技有限公司/mods/PROTECTED_MODS.md)。

## 查询能力清单

```http
GET /api/platform-shell/capabilities
```

前端：`fetchPlatformShellCapabilities()`（`@/utils/platformShellApi`）。

## 客户端与管理端

- 客户端只有企业版完整路由：`cd frontend && npm run build`（等同 `build:full`）
- 管理端是独立网页 SPA（`admin-console`），不打进桌面包
- 通用壳和精简壳不再裁路由。`?shell=1`、`xcagi_platform_shell_mode=1` 都不会拿掉 `tenant-roles` 等企业版页面
- 宿主 API 仍在：`GET /api/platform-shell/capabilities`

## 解耦完成度（2026）

- 核心工作流、横切桥接、Planner 门面、NeuroBus 边界 Mod 已上架源码库
- **主对话**（里程碑 P）：物理视图在 `xcagi-planner-bridge`；安装门面且 `xcagi_planner_mod_facade_enabled=1` 时访问 `/` 重定向到 `/mod/xcagi-planner-bridge/chat`
- 工具**执行**与 NeuroBus **总线**仍在宿主；新业务请走 Mod 或 `employee_pack`
- ERP 领域 API 见 [ERP_DOMAIN_MOD.md](./ERP_DOMAIN_MOD.md)（里程碑 C）
- Repository 装配见 `app/mod_sdk/erp_repository_registry.py`（里程碑 L/L+，`repository_via_mod` + `Mod*RepositoryAdapter`）

## 全量解耦进度

[DECOUPLING_ROADMAP.md](./DECOUPLING_ROADMAP.md)
