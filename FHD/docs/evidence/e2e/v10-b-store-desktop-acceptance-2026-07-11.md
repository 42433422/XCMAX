# v10-B AI 员工商店 ↔ 桌面 · 验收底稿（2026-07-11 · v10 线内迭代）

> **状态：部分通过，非正式终稿签字。**  
> 对照：`specs/tasks.md` PL2 · `docs/evidence/mod/` 四图。  
> **禁止**在 03 未实付前勾选 PL2 或对外宣称商店闭环已交付。

## 证据

| 项 | 证据 | 结果 |
|----|------|------|
| Catalog / 上架可见 | `mod/01-listing.png` | **通过**（2026-07-11 刷新） |
| 市场页可浏览 | `mod/02-store-page.png` | **通过**（2026-07-11 刷新） |
| 0.01 元支付 → 钱包 | `mod/03-payment.png` | **阻塞**：需沙箱买家或 `MOD_PILOT_ALIPAY_MANUAL=1` 人工付 |
| FHD 宿主安装/已安装 | `mod/04-activated.png` | **通过**（企业登录 + `tab=installed`） |
| 支付履约 → `user_mods` | 代码：`payment_fulfillment.py` | **代码落地**（待 03 实付后联调确认） |

## 复跑

```bash
# 可选：cp FHD/docs/evidence/mod/mod-pilot.env.example ~/.xcmax/mod-pilot.env
export PAYMENT_BACKEND=python
unset ALIPAY_APP_PRIVATE_KEY ALIPAY_ALIPAY_PUBLIC_KEY
# 人工付：export MOD_PILOT_ALIPAY_MANUAL=1
bash FHD/scripts/dev/capture_mod_pilot_evidence.sh
```

## 签字区（终稿时填）

- 验收人：________ 日期：________
- 03 实付订单号：________
- 备注：本文件在 03 绿之前不得升格为 `*-final.md`。
