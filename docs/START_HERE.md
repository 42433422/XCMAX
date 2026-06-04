# 从这里开始（唯一入口）

> **问题**：仓库内 Markdown 很多，但日常只需下面 **18 份**。其余为迁移报告、验收纪要、历史修复笔记——**默认不读**。  
> 完整分层见 [`DOCUMENTATION_MAP.md`](DOCUMENTATION_MAP.md)。  
> Tier 1 路径清单（CI 校验）：[`../config/tier1_docs.json`](../config/tier1_docs.json) · Tier 2：[`../config/tier2_docs.json`](../config/tier2_docs.json)  
> 公开文档站（仅 Tier 1/2）：<https://docs.xiu-ci.com/> · 本地：`cd FHD && mkdocs serve`

**版本锚点**：[`../VERSION.md`](../VERSION.md)（与 README 冲突时以此为准）

---

## 5 分钟跑通（开发 / 验收）

```bash
cd FHD
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# 桌面 SQLite（无需 PostgreSQL）：
./start-desktop-sqlite.bat   # 或 start-dev.bat
# 入口：XCAGI/run.py → http://127.0.0.1:5000
```

| 步骤 | 文档 |
|------|------|
| 产品模型（宿主 + MOD） | [QUICK_START.md](QUICK_START.md) |
| 生产依赖最小集 | [guides/PROD_INSTALL.md](guides/PROD_INSTALL.md) |
| 桌面 SQLite 交付 | [guides/DESKTOP_DATABASE_DELIVERY.md](guides/DESKTOP_DATABASE_DELIVERY.md) |
| 中文一键脚本说明 | [guides/快速启动说明.md](guides/快速启动说明.md) |

验收：`GET http://127.0.0.1:5000/api/platform-shell/deliverable-status` → `"deliverable": true`（见 [DELIVERABLE_PRODUCT.md](DELIVERABLE_PRODUCT.md)）。

---

## 覆盖率快照（从 CI artifact 下载）

仓根 `coverage.json` / `coverage-full.xml` 等**本地 pytest 产物**已加入 `.gitignore`，不再入库。需要对照发版或 ramp 门禁时，从 GitHub Actions 下载权威快照：

1. 打开仓库 **Actions** → 工作流 **Test**（`.github/workflows/test.yml`）→ 选择最近一次 **backend full-app coverage** 通过的 run。
2. 在 **Artifacts** 区域下载 **`backend-full-app-coverage`**（保留 14 天）。
3. 解压后可得：
   - `coverage-full.xml` / `coverage.json` — 全量后端覆盖率
   - `coverage-full-summary.txt` — 单行摘要（CI 门禁读此文件）
   - `metrics/coverage-dual-summary.json` — 双口径汇总（与 [COVERAGE_RAMP](../reports/_completed/COVERAGE_RAMP.md) 一致）

本地如需复现同一快照，在 `FHD/` 下执行 `./scripts/coverage_snapshot.sh`（会写入仓根上述文件，仍保持 git 忽略）。

前端覆盖率 artifact 名称：**`frontend-coverage`**（同 workflow 的 frontend job）。

---

## 按角色选读（18 份直达清单）

### 客户 / 实施 / 支持（6）

| # | 文档 | 何时用 |
|---|------|--------|
| 1 | [QUICK_START.md](QUICK_START.md) | 安装包或源码首次启动 |
| 2 | [guides/PRODUCT_USER_FLOW.md](guides/PRODUCT_USER_FLOW.md) | 安装→首启→装 MOD→日常使用 |
| 3 | [customer/CUSTOMER_SUPPORT.md](customer/CUSTOMER_SUPPORT.md) | 升级、回滚、诊断包、话术 |
| 4 | [DELIVERABLE_PRODUCT.md](DELIVERABLE_PRODUCT.md) | 发版自检与交付物清单 |
| 5 | [guides/PROD_INSTALL.md](guides/PROD_INSTALL.md) | 生产机依赖与最小安装 |
| 6 | [guides/DESKTOP_DATABASE_DELIVERY.md](guides/DESKTOP_DATABASE_DELIVERY.md) | 桌面本地库策略 |

### 研发（7）

| # | 文档 | 何时用 |
|---|------|--------|
| 7 | [ARCHITECTURE.md](ARCHITECTURE.md) | 分层、NeuroBus、路由 SSOT |
| 8 | [FEATURE_MAP.md](FEATURE_MAP.md) | 功能与目录职责边界 |
| 9 | [MIGRATION_REGISTRY.md](MIGRATION_REGISTRY.md) | 入口/路径迁移登记 |
| 10 | [TECH_STACK.md](TECH_STACK.md) | 运行时与依赖摘要 |
| 11 | [guides/MOD_AUTHORING_GUIDE.md](guides/MOD_AUTHORING_GUIDE.md) | 写 Mod 包 |
| 12 | [DEVELOPER_PORTAL.md](DEVELOPER_PORTAL.md) | 第三方上架与 SDK 2.0 |
| 13 | [AI_PROVIDER_MATRIX.md](AI_PROVIDER_MATRIX.md) | LLM Provider 配置 |

### 运维 / 发版（5）

| # | 文档 | 何时用 |
|---|------|--------|
| 14 | [DEPLOYMENT.md](DEPLOYMENT.md) | Web / Docker / Nginx 部署 |
| 15 | [guides/RELEASE_TWO_SKUS.md](guides/RELEASE_TWO_SKUS.md) | 企业版 / 个人版双 SKU |
| 16 | [guides/RELEASE_QUALITY_GATE.md](guides/RELEASE_QUALITY_GATE.md) | 发版质量门 |
| 17 | [SLO.md](SLO.md) | API / 业务链路 SLO |
| 18 | [guides/DR_RUNBOOK.md](guides/DR_RUNBOOK.md) | 灾备与演练 |

### MOD 商店（姊妹仓，另入口）

| 文档 | 何时用 |
|------|--------|
| [../../成都修茈科技有限公司/MODstore_deploy/docs/developer/README.md](../../成都修茈科技有限公司/MODstore_deploy/docs/developer/README.md) | 商店 API、PAT、上架 |

---

## 不要从这里开始

| 类型 | 位置 | 说明 |
|------|------|------|
| 迁移/验收考古 | `docs/reports/`、`docs/reports/_completed/` | 阶段报告，非操作手册 |
| 小程序修复笔记 | `docs/wxcc/` | 历史 FIX，非架构总览 |
| 软著材料 | `docs/legal/`、`XCAGI/软著申请/` | 合规产出，非运行指南 |
| 工作区归档 | 仓库根 `_archive/` | 只读快照，禁止日常 build |
| 重复/过期启动说明 | 与 `QUICK_START` 矛盾的旧路径 | 以 **START_HERE + QUICK_START** 为准 |

---

## 工作区其它文档

| 入口 | 说明 |
|------|------|
| [../../README.md](../../README.md) | XCMAX  monorepo 地图（FHD + 成都修茈 + specs） |
| [../../成都修茈科技有限公司/docs/README.md](../../成都修茈科技有限公司/docs/README.md) | 姊妹项目 ADR / roadmap |
| [../README.md](../README.md) | FHD 产品 README |
