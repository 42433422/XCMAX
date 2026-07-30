# XCAGI 1.0.0.0 企业版可交付产品说明

> **产品模型**：每家客户独立部署一份宿主；装平台 MOD 后变为对应垂直系统。供应商不代运营客户业务库。

---

## 交付物清单

| 交付物 | 路径 / 命令 | 验收 |
|--------|-------------|------|
| Windows 企业版安装包 | `build-installer.ps1 -Version 1.0.0.0 -ProductSku enterprise` | `release/xcagi-v1.0.0.0/enterprise/` |
| Windows 安装包（macOS/Linux 交叉构建） | `bash scripts/package/build-windows-installer.sh 1.0.0.0 enterprise` | Docker/Wine 构建，必须包含 `resources/backend/xcagi-backend.exe` |
| macOS 安装包（单 SKU） | `bash scripts/package/build-installer.sh 1.0.0.0 enterprise` | 与 Windows 共用 SKU 资源契约，后端二进制按平台生成 |
| 通用壳前端 | 默认 `npm run build`（generic） | 侧栏仅壳菜单 + Mod |
| 内置 Mod 种子（L1 平台 bridge） | 安装包 `mods/` | 首启自动复制到 userData/mods |
| 行业中性种子池（L2） | 安装包 `industry-seeds/`（仅 enterprise + open 行业） | 引导选行业后单拷，不全量激活 |
| 账号定制 Mod（L3） | **不进安装包** | entitlement + Catalog |
| 客户快速开始 | [QUICK_START.md](QUICK_START.md) | 5 分钟内本地可访问 |
| 客户运维 | [customer/CUSTOMER_SUPPORT.md](customer/CUSTOMER_SUPPORT.md) | 版本/日志/回滚口径一致 |
| 技术验收 API | `GET /api/platform-shell/deliverable-status` | `deliverable: true` |
| 一键装包 API | `POST /api/mod-store/bootstrap-edition-pack?edition=generic` | `success: true` |
| 自动化验收 | `scripts/dev/deliverable_smoke.ps1` | 全部 [OK] |

---

## 当前发行矩阵

| SKU | 命令 | 安装包文件名 | 内置 Mod | ERP |
|-----|------|--------------|----------|-----|
| **enterprise** | `-ProductSku enterprise` | `XCAGI-Enterprise-Setup-{ver}-x64.exe` | `GENERIC_HOST_MOD_IDS` + 辅助 Mod | **是**（`xcagi-erp-domain-bridge`） |

`personal` 仅保留历史兼容构建代码，不进入当前版本目标、正式构建矩阵、上传目录、下载清单或交付验收。

- 打包过滤：`scripts/package/stage-bundled-mods.ps1` / `.sh` → PyInstaller 打入 L1 `mods/` 白名单；**不含** `*-industry`。
- 行业池：`scripts/package/stage-industry-seeds.ps1` / `.sh` → `industry-seeds/`（`onboarding_open_industry_ids` 对应 mod）。
- 运行时：`XCAGI_PRODUCT_SKU=enterprise` / `product-sku.json` 必须与企业版包一致。
- 更新站路径：`https://xiu-ci.com/releases/stable/enterprise/`
- 打包后验收：`pre-release-security.ps1 -Phase post` 硬性检查 Windows 后端 exe、`product-sku.json`、`verify-bundled-mods.ps1`、`verify-industry-seeds.ps1`
- 禁止发布 Electron-only Windows 空壳包：正式 Windows 包必须带内嵌 PyInstaller 后端。

官网下载页（MODstore）环境变量：`VITE_XCAGI_DOWNLOAD_BASE_URL`、`VITE_XCAGI_DOWNLOAD_VERSION`。

---

## 1.0-A 首样板（当前）

| 项 | 口径 |
|----|------|
| **首样板行业** | **通用**（`industry_id=通用`，L2 种子 `xcagi-planner-bridge`） |
| **验收清单** | [customer/ACCEPTANCE_GENERIC_1.0-A.md](customer/ACCEPTANCE_GENERIC_1.0-A.md) |
| **完成线** | L1 九件套 bridge + `deliverable: true` + 对话 / capabilities / neuro-bus 三动作 |
| **非首样板** | 涂料、考勤等垂直包另开清单，不占用本战役对外承诺 |

## 客户标准路径

1. 安装 XCAGI（generic 宿主）
2. 首次打开 → **首次设置向导**（`/onboarding`）：认识宿主 → 宿主包就绪 → **行业定型选「通用」**（可跳过，首样板验收须选通用）
3. 宿主包未齐时：**一键装齐通用包**（或安装包已种子 Mod）
4. 引导 **补基础线**：`POST /api/mod-store/install-industry-seed` 从 `industry-seeds/` 安装所选行业中性 Mod（定制 Mod 仍 entitlement + Catalog）
5. 日常使用：智能对话 + Mod 菜单；数据在客户本机 `userData`

**完整流程说明（必读）**：[guides/PRODUCT_USER_FLOW.md](guides/PRODUCT_USER_FLOW.md)

---

## 供应商发版前自检（必做）

```powershell
cd <repo-root>
powershell -ExecutionPolicy Bypass -File scripts/dev/adcdfg_acceptance.ps1
powershell -ExecutionPolicy Bypass -File scripts/dev/deliverable_smoke.ps1
```

确认 `VERSION.md` 的产品版本为 **1.0.0.0**、工具链映射为 **1.0.0**，并通过版本锚点校验。

---

## 可交付判定（API）

```http
GET /api/platform-shell/deliverable-status
```

| 字段 | 含义 |
|------|------|
| `deliverable` | `true` = 可对外交付该 edition |
| `edition` | `minimal` / `generic` / `full` |
| `generic_pack_installed` | 9 个通用 bridge Mod 是否齐全 |
| `blockers` | 未满足项与 `missing_mod_ids` |
| `next_actions` | 建议操作（装包、打开市场等） |

---

## 环境变量（交付相关）

| 变量 | 默认 | 说明 |
|------|------|------|
| `XCAGI_GENERIC_EDITION` | 桌面 `1` | generic 发行 |
| `XCAGI_PLATFORM_SHELL` | 桌面 `1` | 平台壳模式 |
| `XCAGI_DEFAULT_EDITION` | 桌面 `generic` | Electron 传入 |
| `XCAGI_PRODUCT_SKU` | `enterprise` | 当前正式包固定为企业版；`personal` 仅历史兼容 |
| `XCAGI_AUTO_BOOTSTRAP_EDITION` | `0` | `1` 时启动会从公网 Catalog 补装 |
| `XCAGI_REGISTER_LEGACY_ROUTES` | 非 full 关闭 | full 构建可设 `1` |

---

## 已知非阻断项（后续版本）

- `legacy_gaps_batch*` 按域拆分（full 版专用）
- 覆盖率 80%+
- MOD 签名强制与公网 SLA

*配套：[guides/ADCDFG_COMPLETION_PLAN.md](guides/ADCDFG_COMPLETION_PLAN.md)*
