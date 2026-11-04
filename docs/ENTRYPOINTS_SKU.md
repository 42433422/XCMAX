# Entry points & SKU inventory

2026-10-25 Asia/Shanghai — debt24

| 级别 | 入口 | 说明 |
|------|------|------|
| 官方主路径 | 桌面私有化 + 单 CVM 云端（见 `DEPLOY_PATH_SSOT.md`） | 签约交付 |
| 官方 Web | FastAPI + Vue SPA（FHD/app） | 签约 |
| 兼容 | `app.legacy.routes.*` mounts/compat | 兼容，待迁 |
| 实验/遗留 | Docker / Compose / K8s 资产 | 非主路径 |
| Mod 副栈 | `MODstore_deploy/modstore_server` | 独立服务 SKU |
| 客户定制客户端 | 多端目录（桌面/移动/管理/定制） | 按合同 SKU，不强制合并 |

禁止宣称「五个入口都在独立生产运行」除非部署核实。

## debt19 entrypoints

| 入口 | 角色 |
|------|------|
| `FHD/run.py` | **API primary entry** |
| `FHD/XCAGI/run.py` / `run_fastapi.py` | 兼容委托 |
| `FHD/desktop` | 官方桌面 |
| `FHD/frontend` | 官方 Web SPA |
| `FHD/admin-console` | 官方管理台 |
| `FHD/sunbird-console` | 客户定制壳（太阳鸟） |
| `FHD/app/desktop_runtime` | 后端运行时包，不是客户端 |
| `FHD/mobile-flutter-poc` | POC，非生产 SKU |
