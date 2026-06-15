# 拆仓后新仓库的工作流模板

每个目录对应一个目标仓库。把目录下的 `.github/workflows/` 原样拷到新仓库根，
即可获得一套干净的独立 CI/部署（路径前缀已去掉 `MODstore_deploy/`）。

| 目录 | 对应仓库 |
| --- | --- |
| `modstore-payment-java/` | Java 支付子服务 |
| `modstore-backend/` | Python 后端（FastAPI / modstore_server） |
| `modstore-frontend/` | market 前端 |
| `xiuci-marketing-site/` | 营销官网静态页 |
| `vibe-coding/` | vibe-coding 独立 Python 包 |

工作流命名与发布契约保持与 monorepo 一致，详见：
- [`.github/workflows/README.md`](../../../.github/workflows/README.md)
- [`MODstore_deploy/docs/migrations/release-contracts.md`](../../../MODstore_deploy/docs/migrations/release-contracts.md)
