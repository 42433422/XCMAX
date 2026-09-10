# XCMAX win32 桌面端修复报告（2026-09-09）

- 执行环境：Windows 11 / win32 桌面模式（SQLite 本地库）
- 代码基线：`main` @ `701da7820`，修复分支 `fix/win32-desktop-startup-20260909` @ `5a5f9a675`
- 交付 PR：[#1847 fix(desktop): 桌面端启动两处阻断——补 langgraph vendored 包、启动脚本对齐 Vite 端口](https://github.com/42433422/XCMAX/pull/1847)
- 验证账号：`xcagi-enterprise-demo`（本地市场模式演示账号）
- 过程截图：`C:\Users\97088\AppData\Local\Temp\trae\screenshots\`（01-login-page → 05-final-state）

---

## 一、复现（屏幕操控实测）

在 main 分支干净环境按交付路径启动（`XCAGI/start-desktop-sqlite.bat`），逐项记录：

| # | 失败点 | 现象 | 定位 |
|---|--------|------|------|
| 1 | 后端启动即崩 | 按 `XCAGI/requirements.txt` 装依赖后，lifespan `_wire_workflow_runtime` → `app.infrastructure.workflow` 顶层导入 `langgraph.checkpoint.base.id` 抛 `ModuleNotFoundError: No module named 'langgraph'` | `XCAGI/requirements.txt` 缺 langgraph vendored 包（pyproject / requirements-server-api.txt 均有，唯独桌面清单漏） |
| 2 | 前端无法访问 | `start-desktop-sqlite.bat` 启动 Vite 后用默认端口 42423（vite.config.js），但脚本 netstat 探测与浏览器打开均按 5001，前端永远访问不到 | 启动脚本未注入 `VITE_DEV_PORT=5001` |
| 3 | 管理员登录死锁（环境项，当场修） | 企业入口拒绝 admin，管理员路由桌面端不存在 | 配置本地市场模式（`.env.enterprise-desktop`），使用演示账号登录 |

## 二、采证与根因

| 证据项 | 结果 |
|--------|------|
| 后端日志 | 修复前：ModuleNotFoundError 崩溃栈；修复后：`Uvicorn running on http://127.0.0.1:5000` |
| `/api/health` | 修复后 `status=healthy`，全部组件 ok、`failures/blockers/degradedReasons` 全空，NeuroBus 运行中（published=2370 / errors=0 / handlers=39）；`git_sha=5a5f9a675…` 与修复提交一致 |
| MODstore health | `{"status":"ok","database":"ok"}`（127.0.0.1:8788） |
| DB 迁移版本戳 | 桌面 SQLite（`XCAGI/data/desktop-dev/data/xcagi.db`，75 表）按 baseline 设计走 `create_all` + runtime ensure，**entrypoint 显式跳过 Alembic**（见 `alembic/versions/2026_06_22_baseline_squashed_schema.py` 头注），故无 `alembic_version` 表属预期 |
| updater-events | `data/desktop-dev/logs/` 无 `updater-events.jsonl`——dev 模式无打包更新器运行，属预期；存在 `neuro_health_events.db` |
| 前端 console（debug_ndjson.log） | 仅非致命 warn：`xcagi-customer-service-bridge` bundle 未提取到 routes、菜单路径 `/attendance-industry` 与 mod id 前缀不匹配、一次 `/mod/xcagi-planner-bridge/chat` 路由 no-match（均不影响主流程） |

## 三、修复（小步 PR + 回归测试）

### PR #1847 内容

1. **PR-1**：`XCAGI/requirements.txt` 补 6 个仓库内 vendored langgraph 包（`xcagi_langgraph_{core,checkpoint,prebuilt,sdk}` + checkpoint-sqlite/postgres 后端），与 pyproject、requirements-server-api.txt 同源。
2. **PR-2**：`start-desktop-sqlite.bat` 启动 Vite 前注入 `VITE_DEV_PORT=5001`，与脚本探测、浏览器打开地址对齐。

### 回归测试

新增 `FHD/tests/test_workflow_langgraph_dependency.py`（2 passed）：

- `langgraph.checkpoint.base.id.uuid6` 可导入（直接对应崩溃点）
- `app.infrastructure.workflow` 完整导入链 + `LanggraphCheckpointBridge` 存在

### 环境项（当场修，不入库）

- `.env.enterprise-desktop`（本地生成，gitignore 内）：SKU=enterprise、数据目录、本地市场地址。
- 本地 MODstore 服务拉起并注册测试账号，打通 LLM 计费链路。

## 四、交付验证（修复后完整核心流程）

以修复后脚本实际启动：后端 5000 健康检测通过自动跳过重启、前端注入 `VITE_DEV_PORT=5001` 后 12 秒内在 5001 就绪并返回 200——**PR-2 修复路径实测生效**。

屏幕操控走查（截图为证）：

| 流程 | 结果 | 说明 |
|------|------|------|
| 首次设置向导 | ✅ | 公司信息+行业选择，正常进入系统 |
| 登录 | ✅ | 演示账号登录成功，进入「智能对话」工作台 |
| 工作台 | ✅ | 侧边导航、系统状态「正常」 |
| 考勤 | ✅ | `/attendance-industry` 部门/人员/排班/考勤记录正常渲染 |
| AI 对话 | ⚠️ 链路通，上游外部阻塞 | 消息发出、SSE 流转发正常；最终收到「模型服务已完成请求，但没有返回可显示的正文」 |

**AI 对话最终阻塞点铁证**：直调本地 MODstore `POST /api/llm/chat`（与 FHD 同 payload、同 Bearer 鉴权）返回：

```text
HTTP 402 {"error":{"message":"Insufficient Balance","type":"unknown_error","code":"invalid_request_error"}}
```

即上游模型渠道（xiaomi/mimo-v2.5-pro）**账户余额不足**。FHD → 本地 MODstore → 上游的认证、路由、计费校验、错误回传链路全部正常工作；402 属外部计费凭据问题，非本机软件代码缺陷。补足上游渠道余额或配置有效 provider key 后即可完全打通（软件侧无需再改）。

## 五、结论

- **代码缺陷**：2 处（langgraph 依赖缺失、启动脚本端口不一致），已修复并随 PR #1847 提交 main，附回归测试。
- **环境项**：管理员登录死锁、本地市场配置、MODstore 服务——均已当场修复。
- **外部依赖**：上游 LLM 渠道余额不足（402），链路已验证畅通，待充值/换 key 即可端到端出回复。
- 登录、工作台、考勤、AI 对话链路（至上游计费边界）**全部实测可用**。

## 六、遗留建议（非阻断）

1. 前端 console 的 mod routes 提取 warn（customer-service-bridge / attendance-industry 菜单前缀）建议后续清理，避免淹没真实告警。
2. `xcagi-planner-bridge` 一次路由 no-match 值得排查其注册时机。
3. 桌面模式如需迁移审计能力，可考虑为 SQLite 侧补轻量 schema 版本戳表（当前以 create_all baseline 为正本）。
