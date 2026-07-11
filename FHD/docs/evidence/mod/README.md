# Mod 商家试点证据（M0 #2 / v10-B）

> **状态（2026-07-11）**：**3/4 跑通** — `01`/`02`/`04` 已刷新；`03` 可用买家账号或人工扫码收口。  
> **禁止**：伪造截图或对外宣称「Mod 商店已完全跑通」。

| # | 文件 | 步骤 | 2026-07-11 |
|---|------|------|------------|
| 1 | `01-listing.png` | 商家入驻 / Mod 上架审核通过 | **已刷新**（Playwright 绿） |
| 2 | `02-store-page.png` | 市场页可见、可安装 | **已刷新**（Playwright 绿） |
| 3 | `03-payment.png` | 0.01 元支付成功 | **待**：`~/.xcmax/mod-pilot.env` 买家，或 `MOD_PILOT_ALIPAY_MANUAL=1` |
| 4 | `04-activated.png` | FHD 宿主安装并激活 Mod | **已刷新**（企业登录 + `/mod-store?tab=installed`） |

## 本地复跑要点

```bash
# 可选密钥（不入库）
# cp FHD/docs/evidence/mod/mod-pilot.env.example ~/.xcmax/mod-pilot.env && chmod 600 ~/.xcmax/mod-pilot.env
# 编辑填入 MOD_PILOT_ALIPAY_BUYER / PASS；或 export MOD_PILOT_ALIPAY_MANUAL=1

export PAYMENT_BACKEND=python
unset ALIPAY_APP_PRIVATE_KEY ALIPAY_ALIPAY_PUBLIC_KEY
bash FHD/scripts/dev/capture_mod_pilot_evidence.sh
```

验收底稿：[`../e2e/v10-b-store-desktop-acceptance-2026-07-11.md`](../e2e/v10-b-store-desktop-acceptance-2026-07-11.md)。

`MODSTORE_DEPLOY_ROOT` 现优先指向仓内 `*/MODstore_deploy`，不再默认 archive。

详见 [`mod-merchant-pilot.md`](../../mod-merchant-pilot.md)。
