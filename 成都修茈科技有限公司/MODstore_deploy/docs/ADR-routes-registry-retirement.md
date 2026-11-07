# ADR：路由注册表退役与现行入口

## 状态

- `modstore_server.app` 继续使用 [`api.app_factory.create_app`](../modstore_server/api/app_factory.py)。公开 HTTP 路径不随旧 Python 模块删除而退役。
- 删除未被运行入口调用的 `routes_registry.py` 与 `routes_registry_merged.py`。旧表的 27 个 API 声明、2 个条件 UI 声明均已有现行入口；28 个旧 optional 模块全部位于现行工厂的 74 个 optional 模块中。
- 测试改为验证真实工厂的配置鉴权、当前 authoring 审核调用和 OpenAPI 的 27 个原有方法/路径契约，不再导入旧注册表。

## 路由归属

| 原有接口 | 现行 owner（均位于 `modstore_server/api/`） |
| --- | --- |
| `/api/health` | `health.py` |
| Mod 列表、详情、manifest、文件、创建、导入导出、删除 | `catalog.py` |
| 扩展面、蓝图、员工包、工作流节点修补、AI 脚手架、前端再生成 | `authoring.py` / `authoring_merged.py` |
| `/api/sync/*`、`/api/xcagi/installed-mods` | `sync.py` |
| `/api/debug/*`、FHD token 状态、XCAGI 加载状态 | `debug.py` |
| `/`、SPA fallback（需 `web/dist`） | `ui_mount.py` |

## 兼容边界

- 无仓库内导入者的 `market_api`、`payment_api`、`catalog_api` import shim 同步移除；外部 Python 集成应分别导入 `api.market_routes`、`api.payment_routes`、`api.catalog_public_routes`。HTTP 客户端继续使用原 URL。
- Python 支付 fallback、独立 notification 服务以及仍服务编辑/发布的节点图工作流不属于这次代码退役。节点图 JSON 沙盒与脚本文件沙盒保持各自契约。
- 固定商品包路径须先于商品编号参数路由注册。类型注解只负责参数校验，不能纠正路由匹配顺序。

仓库检索不代表生产零流量或无外部脚本。仍有调用证据的 URL 须先迁移调用方，不能按文件名、无前端字面量或 410/501 分支直接删除。
