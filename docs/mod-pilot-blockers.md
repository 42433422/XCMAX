# Mod 试点阻塞清单（自动生成口径）

> **来源**：`bash FHD/MODstore/scripts/mod-pilot-checklist.sh --check-only`（工作区根 `Desktop/XCMAX`）。  
> **SSOT 步骤**：[`mod-merchant-pilot.md`](mod-merchant-pilot.md) · **脚本**：[`MODstore/scripts/mod-pilot-checklist.sh`](../MODstore/scripts/mod-pilot-checklist.sh)  
> **最后核对**：2026-06-05（`MODSTORE_DEPLOY_ROOT` 指向归档；`alipay_package` 经归档 rsync 命令 documented）

## 自动化结论

| 检查 | 结果 |
|------|------|
| `--check-only` | **通过**（`MODSTORE_DEPLOY_ROOT` 指向归档；不要求四张 PNG） |
| `--verify` | **未通过** — 缺 4 张证据 PNG |

**本次复扫命令**（deploy 在工作区外时）：

```bash
export MODSTORE_DEPLOY_ROOT="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy"
cd /Users/a4243342/Desktop/XCMAX/FHD
bash MODstore/scripts/mod-pilot-checklist.sh --check-only
```

> 说明：仓根下无独立 `MODstore/` 目录；可执行脚本在 **`FHD/MODstore/scripts/`**。从 `FHD/` 目录可执行文档中的 `bash MODstore/scripts/mod-pilot-checklist.sh`。

## 已满足（check-only）

- [`mod-merchant-pilot.md`](mod-merchant-pilot.md) 存在
- 证据目录 [`evidence/mod/`](evidence/mod/) 存在（当前仅 `.gitkeep`）
- **MODstore_deploy**（归档实体，经 `MODSTORE_DEPLOY_ROOT`）：`~/XCMAX-archives/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy/`（含 `modstore_server/`、`market/`）

## 缺失 / 待办（按优先级）

### 1. 部署与支付环境（check-only WARN）

| 项 | 期望路径 | 现状 | 解除方式 |
|----|----------|------|----------|
| **MODstore_deploy** | `成都修茈科技有限公司/MODstore_deploy/` | 工作区未检出；**归档已存在**（`m0-fhd-bulk-20260605/…/MODstore_deploy/`）。`MODSTORE_DEPLOY_ROOT` 指向归档时 checklist **不再 WARN deploy** | 方式 B（见下）已可用；或 rsync 方式 A 拉回工作区默认 SSOT 路径 |
| **alipay_package** | `成都修茈科技有限公司/alipay_package/` | 工作区未检出；**归档已存在**（同 bulk 树）。checklist 仍 **WARN**（支付步骤需工作区或 env 内密钥） | rsync 恢复（见下）；或本地配置 **0.01 元** 密钥；**勿** `git add` 密钥 |

#### 恢复 MODstore_deploy（`~/XCMAX-archives` / `ARCHIVE_POINTER`）

M0 已将整棵 **`成都修茈科技有限公司/`**（含 `MODstore_deploy/`、`alipay_package/`）迁出工作区；工作区仅保留指针：

- 姊妹目录：[`成都修茈科技有限公司/ARCHIVE_POINTER.md`](../../成都修茈科技有限公司/ARCHIVE_POINTER.md)
- 仓根索引：[`ARCHIVE_POINTER.md`](../../ARCHIVE_POINTER.md)（`m0-fhd-bulk-20260605`）

**归档实体**（默认根 `~/XCMAX-archives`，可用 `XCMAX_ARCHIVE_ROOT` 覆盖）：

```text
${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy/
```

**方式 A — 恢复默认 SSOT 路径（推荐）**

自任意目录执行；将 `MODstore_deploy` 与 `alipay_package` 等一并拉回 `Desktop/XCMAX/成都修茈科技有限公司/`：

```bash
export AR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605"
rsync -a "$AR/成都修茈科技有限公司/" "/Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/"
```

仅恢复 deploy（不拉整棵姊妹树）：

```bash
export AR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605"
mkdir -p "/Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司"
rsync -a "$AR/成都修茈科技有限公司/MODstore_deploy/" \
  "/Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/MODstore_deploy/"
```

仅恢复 **alipay_package**（归档已存在；解除 checklist 对支付目录的 WARN；**勿** `git add` 密钥）：

```bash
export AR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605"
mkdir -p "/Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司"
rsync -a "$AR/成都修茈科技有限公司/alipay_package/" \
  "/Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/alipay_package/"
# 归档内另有 _local_secrets/ 等敏感目录；仅 rsync alipay_package/，勿整树提交 git
```

**方式 B — 不 rsync，仅让 checklist 指向归档**

```bash
export MODSTORE_DEPLOY_ROOT="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy"
```

**恢复后校验**

```bash
test -d "/Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/MODstore_deploy/modstore_server" \
  -o -d "/Users/a4243342/Desktop/XCMAX/成都修茈科技有限公司/MODstore_deploy/market"
cd /Users/a4243342/Desktop/XCMAX/FHD
bash MODstore/scripts/mod-pilot-checklist.sh --check-only   # 应不再 WARN deploy
```

> `rsync` 会带回 `_local_secrets/`、`.env*` 等本地敏感文件；**勿** `git add` 密钥或生产配置。支付试点仍需 [`alipay_package/`](../../成都修茈科技有限公司/alipay_package/) 内 **0.01 元** 沙箱/生产密钥就位。

### 2. 试点证据（`--verify` 阻塞）

以下文件均 **MISSING**（`FHD/docs/evidence/mod/`）：

| 文件 | 对应步骤 |
|------|----------|
| `01-listing.png` | 商家入驻 / Mod 上架审核通过 |
| `02-store-page.png` | 市场页可见、可安装 |
| `03-payment.png` | 0.01 元支付成功 |
| `04-activated.png` | FHD 安装并激活 Mod |

跑通后：`git add FHD/docs/evidence/mod/*.png`，并事实更新 [`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)「Mod 商店分成」行。

### 3. 商务 / 人工前置（脚本不校验）

- [ ] 1 家友好商家或内部沙箱租户（商务/运营签字）
- [ ] 勿在 `FHD/MODstore/` 做 SSOT 开发（部署 SSOT 在 **MODstore_deploy**）
- [ ] 无真实商家前禁止对外宣称「Mod 商店已跑通」

## 与 M0 / SLO 的边界

- Mod 试点阻塞对应 [`M0-remaining-gaps.md`](M0-remaining-gaps.md) **#2**；与 **T36–T37 staging SLO**（`specs/BLOCKERS.md`）无关，勿混为一谈。

## 建议下次命令

```bash
export MODSTORE_DEPLOY_ROOT="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy"
cd /Users/a4243342/Desktop/XCMAX/FHD
bash MODstore/scripts/mod-pilot-checklist.sh --check-only
bash MODstore/scripts/mod-pilot-checklist.sh --verify   # 四图就位后（禁止伪造 PNG）
```
