# MODstore 文档

- **定位（推荐主入口）**：扩展的制作、校验、与 `XCAGI/mods` 同步，以本目录 **独立 MODstore Web**（`MODstore/web` + `modstore_server`）为准；XCAGI 主前端 `/mod-store` 默认嵌入该站点，仅将「本机 .xcmod 简易目录」作为兼容入口。
- **API（自动生成）**：服务启动后访问 Swagger UI `/docs`、ReDoc `/redoc`、OpenAPI JSON `/openapi.json`。
- **制作向导（Web `/author`）**：展示内置 `extension_surface.json`（manifest 与 **FastAPI** `register_fastapi_routes` 约定）；可合并宿主 `openapi.json` 中 `/api*` 路由摘要；各 Mod 详情「蓝图/API」页签静态扫描 `backend/blueprints.py`。
- **工作流员工脚手架**：`POST /api/mods/{mod_id}/workflow-employees/scaffold`（实现见 `modstore_server/workflow_employee_scaffold.py`）— 追加 `manifest.workflow_employees`、生成 `backend/employee_stubs/*.py` 占位路由；骨架级 `blueprints.py` 可由环境变量 `MODSTORE_SCAFFOLD_AUTO_MERGE_BLUEPRINTS`（默认开启）尝试自动插入 `mount_employee_router` 调用。Mod 详情页「工作流 / 员工」卡片内提供表单入口。
- **AI 整包 / 工作台脚手架（未纳入本树）**：修茈完整部署中的 `mod_scaffold_runner.py`、`workbench_api.py`、`/api/mods/ai-scaffold` 等依赖 LLM 与多子域路由；若要在 FHD 侧对齐，需单独评估依赖、鉴权与测试后再移植，不在本次 MODstore 精简包范围内。
- **员工沙箱（上架门禁）**：逻辑在 `modman/employee_sandbox.py`；Mod 详情页可「运行沙箱检查」；`POST /api/mods/{id}/employee-sandbox/run` 返回静态结果与可选 HTTP 结果。环境变量：`MODSTORE_CATALOG_REQUIRE_EMPLOYEE_SANDBOX=1` 时，`POST /v1/packages` 与 CLI `modman publish` 在上传 **含 workflow_employees 的 mod** 前必须通过同一静态规则（占位 `backend/employee_stubs/<stem>.py` + 后端入口源码含对应 stem）；`MODSTORE_CATALOG_SANDBOX_HTTP=1` 时在上传流程中额外尝试 HTTP 探测（需配置可访问的 XCAGI 后端 URL）。
- **架构决策（ADR）**：[docs/adr/](adr/) 目录。
- **公网 Catalog（/v1）**：`modstore_server` 挂载 `GET/POST /v1/*`；数据目录由环境变量 `MODSTORE_CATALOG_DIR` 控制（默认 `modstore_server/catalog_data/`）；上传需 `Authorization: Bearer <MODSTORE_CATALOG_UPLOAD_TOKEN>`。CLI：`modman publish <zip> --catalog-url URL --token TOKEN`（需 `pip install httpx`）。
- **修茈门户 · 充值跳转与密钥同步**：在「路径与同步」可配置 `portal_plans_url`（默认充值页 `https://xiu-ci.com/market/plans`）与可选 `portal_wallet_sync_url`。Mod 详情支持「从剪贴板填入」`manifest.config.wallet_secret`；若已配置同步 URL，可调用 `POST /api/portal/fetch-wallet-secret`，请求体 `{ "sync_url": "", "authorization": "Bearer <一次性令牌>" }`（`sync_url` 非空时可覆盖配置），由服务端 **HTTPS GET** 目标地址并解析 JSON 中的 `wallet_secret` 或 `data.wallet_secret`。**Bearer 不落盘**；目标主机禁止 loopback/私网。修茈侧需提供对应 HTTPS 只读接口文档后再对接。
