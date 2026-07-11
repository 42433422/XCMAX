# Mod 商家试点证据（M0 #2 / v10-B）

> **状态（2026-07-11）**：**部分跑通** — `01`/`02` 已用仓内 MODstore 刷新；`03`/`04` 仍阻塞。  
> **禁止**：伪造截图或对外宣称「Mod 商店已完全跑通」。

| # | 文件 | 步骤 | 2026-07-11 |
|---|------|------|------------|
| 1 | `01-listing.png` | 商家入驻 / Mod 上架审核通过 | **已刷新**（Playwright 绿） |
| 2 | `02-store-page.png` | 市场页可见、可安装 | **已刷新**（Playwright 绿） |
| 3 | `03-payment.png` | 0.01 元支付成功 | **跳过**：需 `MOD_PILOT_ALIPAY_BUYER` / `PASS`；本地支付宝签名链路已验 OK |
| 4 | `04-activated.png` | FHD 宿主安装并激活 Mod | **跳过**：FHD 企业商家登录 403 |

## 本地复跑要点

```bash
# 1) 强制 Python 支付后端（.env.production.synced 默认 java）
# 2) unset 内联 ALIPAY_*_KEY，改用 keys/*.pem（PKCS#1）
export PAYMENT_BACKEND=python
unset ALIPAY_APP_PRIVATE_KEY ALIPAY_ALIPAY_PUBLIC_KEY
bash FHD/scripts/dev/run_mod_pilot_local.sh
bash FHD/scripts/dev/capture_mod_pilot_evidence.sh
```

`MODSTORE_DEPLOY_ROOT` 现优先指向仓内 `*/MODstore_deploy`，不再默认 archive。

详见 [`mod-merchant-pilot.md`](../../mod-merchant-pilot.md)。
