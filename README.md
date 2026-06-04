# XCAGI v10.0 — 企业 AI 员工平台

> **产品模型**：每家客户部署自己的 XCAGI 宿主（空壳）；安装行业 MOD 后变为垂直系统（ERP、出货、客服等）。  
> **技术形态**：Electron 桌面 + Web 自托管 · Neuro-DDD · FastAPI · Mod 生态 · MOD 商店。

[Release](https://github.com/42433422/xcagi/releases) · [License: AGPL v3](https://www.gnu.org/licenses/agpl-3.0.html) · [Contributing](.github/CONTRIBUTING.md)

**版本说明索引**：下列 **[版本与发布约定](#version-policy)** 与 [`VERSION.md`](VERSION.md) 保持同一套锚点；若两处不一致，**以 VERSION.md 为准**。

## 版本与文档（单一事实来源）

| 文档 | 用途 |
|------|------|
| [`VERSION.md`](VERSION.md) | **版本号锚点**（与 `pyproject.toml` 等同步；冲突时以此为准） |
| [`CHANGELOG.md`](CHANGELOG.md) | 按日期的发布说明与 Unreleased |
| [`docs/DELIVERABLE_PRODUCT.md`](docs/DELIVERABLE_PRODUCT.md) | 交付物清单与发版自检 |

当前 GA：**10.0.0**。v10 架构收口见 [`docs/V10_ROADMAP_COMPLETE.md`](docs/V10_ROADMAP_COMPLETE.md)。

<a id="version-policy"></a>

## 版本与发布约定

| 组件 | 版本 | 锚点文件 |
|------|------|----------|
| XCAGI 总版本 | `10.0.0` | [`VERSION.md`](VERSION.md)、[`CHANGELOG.md`](CHANGELOG.md) |
| Python 包 | `10.0.0` | [`pyproject.toml`](pyproject.toml) |
| 前端 / 桌面壳 | `10.0.0` | `frontend/package.json`、`desktop/package.json` |

发版前：`rg -n '10\.0\.0' VERSION.md pyproject.toml frontend/package.json` 与 [`docs/DELIVERABLE_PRODUCT.md`](docs/DELIVERABLE_PRODUCT.md) 自检清单。

## 快速开始

```bash
git clone https://github.com/42433422/ai-excel-helper.git
cd ai-excel-helper/FHD
pip install -r requirements.txt   # 生产：仅 requirements-base.txt；开发：pip install -e ".[dev,ml]"
alembic upgrade head
cd XCAGI && python run.py
```

- API 文档：<http://127.0.0.1:5000/docs>
- 详细步骤：[`docs/QUICK_START.md`](docs/QUICK_START.md)
- 双 SKU 发版：[`docs/guides/RELEASE_TWO_SKUS.md`](docs/guides/RELEASE_TWO_SKUS.md)

### 桌面安装包

```bash
# Windows
powershell -ExecutionPolicy Bypass -File scripts/package/build-installer.ps1 -Version 10.0.0
# macOS
bash scripts/package/build-installer.sh 10.0.0
```

## 仓库结构（硬规则）

1. **服务端**只写在 `app/`（`backend/` 已下线，见 [`docs/MIGRATION_REGISTRY.md`](docs/MIGRATION_REGISTRY.md)）。
2. **前端**只写在 `frontend/`（`templates/vue-dist/` 为构建产物）。
3. **HTTP 入口**只用 `XCAGI/run.py`（端口 **5000**）。

**文档入口**：[`docs/START_HERE.md`](docs/START_HERE.md)（18 份直达）· 功能边界：[`docs/FEATURE_MAP.md`](docs/FEATURE_MAP.md) · 全文地图：[`docs/DOCUMENTATION_MAP.md`](docs/DOCUMENTATION_MAP.md)

## 架构要点

- **Neuro-DDD**：`application` → `domain` + `infrastructure`，HTTP 层薄；装配在 `app/bootstrap.py`。
- **v10 路由**：`app/fastapi_routes/domains/*` 为 SSOT；禁止重新引入 `legacy_*` shim（CI：`scripts/dev/verify_no_legacy_shims.py`）。
- **神经域 / NeuroBus**：详见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 与 [`XCAGI/README.md`](XCAGI/README.md)。

```
用户 (Vue 3 SPA) → FastAPI (app/fastapi_routes) → application → domain / infrastructure
                              ↘ NeuroBus / LLM Provider Registry
```

## 交付形态

| 形态 | 说明 |
|------|------|
| **桌面** | Windows `.exe` / macOS `.dmg`，Electron 壳 + 本地 FastAPI |
| **Web** | Docker / Nginx 自托管 |
| **扩展** | `mods/`、Mod 商店、Token 钱包（见 [`docs/guides/MOD_AUTHORING_GUIDE.md`](docs/guides/MOD_AUTHORING_GUIDE.md)） |

## 系统要求

Python 3.11+ · PostgreSQL 16+（推荐）· Redis（按场景）· Docker（可选）

## 常用链接

| 主题 | 文档 |
|------|------|
| 架构 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| AI 员工 | [docs/AI_EMPLOYEE.md](docs/AI_EMPLOYEE.md) |
| 迁移登记 | [docs/MIGRATION_REGISTRY.md](docs/MIGRATION_REGISTRY.md) |
| 技术栈演进（历史） | [docs/history/TECH_STACK_EVOLUTION.md](docs/history/TECH_STACK_EVOLUTION.md) |
| 软著材料脚本 | [XCAGI/软著申请/README.md](XCAGI/软著申请/README.md) |
| 安全 | [SECURITY.md](SECURITY.md) |

## Git 与 CI

- 展示仓库：[ai-excel-helper](https://github.com/42433422/ai-excel-helper)，默认分支 **`master`**。
- 推送 **`v10.*`** 标签触发桌面/Web 相关 workflow（见 `.github/workflows/`）。

## 贡献与许可

Fork → `feature/...` → PR。详见 [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md)。

**AGPL-3.0** — 见 [LICENSE](LICENSE)。

---

**XCAGI v10.0** — Neuro-DDD + FastAPI + Mod 生态 + 桌面/Web 并行交付
