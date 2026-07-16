# Mod 商家试点证据（M0 #2 / v10-B）

> **状态（2026-07-11）**：**PL2 已签字** — 四图齐；支付由产品确认历史成功。  
> 终稿：[`../e2e/v10-b-store-desktop-acceptance-2026-07-11-final.md`](../e2e/v10-b-store-desktop-acceptance-2026-07-11-final.md)

| # | 文件 | 步骤 | 2026-07-11 |
|---|------|------|------------|
| 1 | `01-listing.png` | 商家入驻 / Mod 上架审核通过 | **通过**（Playwright） |
| 2 | `02-store-page.png` | 市场页可见、可安装 | **通过**（Playwright） |
| 3 | `03-payment.png` | 0.01 元支付成功 | **通过**（产品确认已付 + 历史证据图） |
| 4 | `04-activated.png` | FHD 宿主安装并激活 Mod | **通过**（Playwright） |

## 本地复跑

```bash
export PAYMENT_BACKEND=python
unset ALIPAY_APP_PRIVATE_KEY ALIPAY_ALIPAY_PUBLIC_KEY
bash FHD/scripts/dev/capture_mod_pilot_evidence.sh
```

详见 [`mod-merchant-pilot.md`](../../mod-merchant-pilot.md)。
