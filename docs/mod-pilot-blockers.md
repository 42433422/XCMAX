# Mod 试点阻塞清单（自动生成口径）

> **来源**：`bash FHD/MODstore/scripts/mod-pilot-checklist.sh --check-only`（工作区根 `Desktop/XCMAX`）。  
> **SSOT 步骤**：[`mod-merchant-pilot.md`](mod-merchant-pilot.md) · **脚本**：[`MODstore/scripts/mod-pilot-checklist.sh`](../MODstore/scripts/mod-pilot-checklist.sh)  
> **最后核对**：2026-06-05

## 自动化结论

| 检查 | 结果 |
|------|------|
| `--check-only` | **通过**（不要求四张 PNG） |
| `--verify` | **未通过** — 缺 4 张证据 PNG |

> 说明：仓根下无独立 `MODstore/` 目录；可执行脚本在 **`FHD/MODstore/scripts/`**。从 `FHD/` 目录可执行文档中的 `bash MODstore/scripts/mod-pilot-checklist.sh`。

## 已满足（check-only）

- [`mod-merchant-pilot.md`](mod-merchant-pilot.md) 存在
- 证据目录 [`evidence/mod/`](evidence/mod/) 存在（当前仅 `.gitkeep`）

## 缺失 / 待办（按优先级）

### 1. 部署与支付环境（check-only WARN）

| 项 | 期望路径 | 现状 | 解除方式 |
|----|----------|------|----------|
| **MODstore_deploy** | `成都修茈科技有限公司/MODstore_deploy/` | 未检出（姊妹目录仅有 `ARCHIVE_POINTER.md`） | 按指针恢复 SSOT 树，或 `export MODSTORE_DEPLOY_ROOT=/path/to/MODstore_deploy` |
| **alipay_package** | `成都修茈科技有限公司/alipay_package/` | 未检出 | 本地配置支付宝沙箱/生产 **0.01 元** 密钥；**勿** `git add` 密钥 |

恢复 deploy 后建议再跑 `--check-only`，确认树内存在 `modstore_server/` 或 `market/`（否则脚本会 WARN）。

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
cd /Users/a4243342/Desktop/XCMAX/FHD
bash MODstore/scripts/mod-pilot-checklist.sh --check-only
bash MODstore/scripts/mod-pilot-checklist.sh --verify   # 四图就位后
```
