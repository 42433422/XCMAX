# 路由注册与兼容契约 SSOT

宿主入口由 `app/fastapi_routes/mounts/*`、`RouteRegistry` 与 `app/legacy/routes/legacy_compat.py` 装配；Mod 入口按当前账号授权动态挂载。云端唯一工厂为 `modstore_server.api.app_factory`。

## 注册与检查

- 固定路径先于同方法的参数/通配路径：打印标签、客户导出、宿主基础员工包下载均有 HTTP 分发回归。
- 产品域自带 `/api`，独立裸挂载；compat 聚合器仍使用 `/api`。debug gap 不再重复挂载该产品域。
- `RouteRegistry.detect_conflicts()` 按实际挂载优先级、prefix 与嵌套路由检查重复及参数路由、ASGI Mount 对后续固定路径的遮挡；不声称穷尽参数路由之间的重叠。deferred 阶段在 SPA fallback 归位后检查整个宿主；`detect_app_route_conflicts(app)` 可对后续 Mod 挂载快照复查。
- `python scripts/route_inventory_diff.py --json-out /tmp/routes.json` 同步装配宿主、等待 Mod 注册，不运行 lifespan；仅在隔离测试配置中执行。未完成注册会失败，宿主注册或 Mod 扫描/加载/挂载失败写入报告并返回非零；重试成功会清除对应宿主失败状态。报告包含当前配置、完整快照和重复/遮挡问题；它不包含登录后新增的授权入口或其他独立服务，不能作为线上无调用的证明。

## 兼容入口生命周期（2026-11-07）

下列 URL 保留原有权限与租户边界。没有生产访问与客户端版本证据前，不指定虚构的移除日期；兼容入口禁止新增业务实现，调用方迁移到当前能力。

| 入口 | 当前行为 | 当前能力或迁移方向 |
| --- | --- | --- |
| `POST /api/system/industry` | 410，行业切换已退役 | 行业来自账号资料；GET 仅查询 |
| `POST /api/print-last` | 501，显式退役代码 | `/api/print/{filename}` 指定文件 |
| `POST /api/print/pdf_labels` | 501，批量 PDF 标签未实现 | 单张标签使用 `/api/print/single_label`，不承诺等价批量替代 |
| `GET /api/customers/export[/]` | 501，旧导出未实现 | 当前账号已授权 ERP Mod 的客户页导出；Mod 路径动态解析 |
| `POST /api/products/resolve-name-hints[/]` | 有效请求 501，保留参数与授权检查 | 销售合同流程的 `name_hint` 解析 |
| 短信验证码发送/登录（云、桌面、移动端） | 501，`SMS_AUTH_UNAVAILABLE`；`SMS_PROVIDER` 不会开启未实现功能 | 现有密码、邮箱或扫码流程；当前客户端收起短信操作入口 |
| 旧侧栏知识库、员工、数据源、模板探测别名 | 保留真实兼容响应，标记 deprecated 并提供替代路径 | 探测直接调用真实 health/catalog/sources/templates API |
| `GET /api/print/jobs` | 501，`PRINT_JOBS_UNSUPPORTED` | 通过真实打印任务的 `job_id` 查询进度，不再返回假空成功 |
| Java `POST /api/webhooks/admin/replay-legacy` | 与 `/replay` 共用控制器，保留旧事件 ID 与订单推导语义 | 新调用使用 `/api/webhooks/admin/replay`，权限与支付状态检查不变 |
| 云端 `POST /api/workflow/{workflow_id}/sandbox-run` | 当前 graph 工作流仍受支持，不再错误标记 deprecated | script 工作流是不同数据模型，不能只替换 URL |

## 已清理源码

未挂载的旧产品实现（SDK DOCX 导出已迁到现行 compat）、旧 shipment ETL HTTP 模块、工作流定义 HTTP 模块、six-line webhook HTTP 模块、空库存 router 和 misc 空 router 已移除。工作流模型/应用服务、事件服务与现行入口保留。旧 AI 冒烟测试改为直接挂载当前 `ai_intent`，不再因导入已删除模块而永久跳过。

云端旧 routes_registry、market/payment/catalog import shim 已退出运行源码；权限、作者注册与删除路由测试针对当前工厂。`alipay_package` 仅删除三个孤立 Python 副本，FHD 支付接口、外部支付回调、证书与业务数据不受影响。语音测试专属包装已收敛，现行转写与指令后端保留。

每次改动需验证实际 HTTP 分发、权限/租户边界与 SDK 绑定，再执行仓库 push preflight。兼容面清理不代表生产下线、部署或发布已完成。
