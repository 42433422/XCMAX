# XCAGI 行业 Mod 模板（SDK 2.0）

本目录提供 4 套**行业 Mod 模板脚手架**，供第三方开发者快速起步。每个模板是一个
SDK 2.0 manifest（`sdk_version: "2.0"`），声明 `release_targets`（支持 mod + ai 双发布）、
`capabilities`、宿主兼容区间（`compat`）与 `industry` 行业配置。

| 模板 | 目录 | 行业 | 双发布 |
|------|------|------|--------|
| ERP | `erp/` | 通用 ERP（产品/客户/订单） | mod + ai |
| 出货 | `shipment/` | 出货 / 物流单据 | mod + ai |
| 客服 | `customer-service/` | 客服工单 / 会话 | mod + ai |
| 财务 | `finance/` | 财务对账 / 开票 | mod |

## 使用方式

1. 复制对应目录到 `mods/<your-mod-id>/`。
2. 修改 `manifest.json` 的 `id` / `name` / `author` 与 `industry.id`。
3. 实现 `backend/` 入口与 `frontend/` 路由（参考 `docs/guides/MOD_AUTHORING_GUIDE.md`）。
4. 若 `release_targets` 含 `ai`，完善 `ai` 段（`employee_id` / `model` / `prompt` / `tools` / `tier`）。
5. 用 `app.mod_sdk.sdk_v2.build_manifest(...)` 也可在代码中生成等价 manifest。

模板由阶段 9（MOD SDK 2.0）提供，配套商店后台（灰度发布 / 评价 / 作者结算）见
`成都修茈科技有限公司/MODstore_deploy/modstore_server/store_lifecycle_api.py`。
