# Mod 真实商家试点（M1/M2 分水岭）

> **状态（2026-06）**：**未跑通** — 无真实商家；[`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md) Mod 行保持「未验证」（**非** T36–T37 阻塞）。  
> 路径图：**上架 → 0.01 元支付 → 宿主开通**；证据目录 [`evidence/mod/`](evidence/mod/)（4 张 PNG，禁止空宣称 / 假图）。

## 前置

- [ ] 1 家友好商家或内部沙箱租户（商务/运营签字）
- [ ] **MODstore SSOT**：[`成都修茈科技有限公司/MODstore_deploy/`](../../成都修茈科技有限公司/MODstore_deploy/)（勿在废弃的 `FHD/MODstore/` 开发）
- [ ] 支付宝沙箱/生产 **0.01 元** 密钥（[`alipay_package/`](../../成都修茈科技有限公司/alipay_package/)），**勿**提交密钥入仓
- [ ] 试点完成后仅事实更新 CLAIMED「Mod 商店分成」行

## 自动化

**脚本 SSOT**：[`MODstore/scripts/mod-pilot-checklist.sh`](../MODstore/scripts/mod-pilot-checklist.sh)（`--verify` / `--check-only` / `--paths`）

```bash
bash MODstore/scripts/mod-pilot-checklist.sh          # 步骤 + 证据路径
bash MODstore/scripts/mod-pilot-checklist.sh --verify # 四张 PNG 就位后校验
bash MODstore/scripts/mod-pilot-checklist.sh --check-only # 仅校验目录/文档（无需商家）
```

## 步骤

| # | 动作 | 证据文件 |
|---|------|----------|
| 1 | 商家入驻 / Mod **上架**审核通过 | `evidence/mod/01-listing.png` |
| 2 | 市场页可见、可安装 | `evidence/mod/02-store-page.png` |
| 3 | **0.01 元**支付成功（沙箱或约定环境） | `evidence/mod/03-payment.png` |
| 4 | FHD **开通**：安装并激活 Mod（设置页或 Mod 首页） | `evidence/mod/04-activated.png` |

```bash
git add FHD/docs/evidence/mod/*.png
```

## 禁止

- 无真实商家前对外宣称「Mod 商店已跑通」（[`specs/对标头部SaaS-步骤路径图.md`](../../specs/对标头部SaaS-步骤路径图.md) §8）
- 伪造流水或截图
- 将 Mod 试点与 **staging SLO**（T36–T37）混为一谈

## 参考

- 验收脚本：[`MODstore/scripts/mod-pilot-checklist.sh`](../MODstore/scripts/mod-pilot-checklist.sh)
- M1 对账：[`M1-kickoff-checklist.md`](M1-kickoff-checklist.md)（M2-W4 Mod 四图）
- 部署：[`MODstore_deploy/docs/runbooks/xiu-ci-single-modstore-upstream.md`](../../成都修茈科技有限公司/MODstore_deploy/docs/runbooks/xiu-ci-single-modstore-upstream.md)
- M0 缺口：[`M0-remaining-gaps.md`](M0-remaining-gaps.md) #2
- SLO 阻塞（独立）：[`specs/BLOCKERS.md`](../../specs/BLOCKERS.md) T36–T37
