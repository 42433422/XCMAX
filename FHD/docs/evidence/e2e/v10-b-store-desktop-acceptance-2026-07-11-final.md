# v10-B AI 员工商店 ↔ 桌面 · 验收终稿（2026-07-11）

> **状态：技术签字通过（PL2）**  
> **版本锚点**：10.0.0（v10 锁，未 bump）  
> **产品负责人确认**：沙箱/试点 **0.01 元支付已成功**（历史闭环，2026-07-11 口头确认；证据图 `mod/03-payment.png`）  
> **对照**：`specs/tasks.md` PL2 · `specs/product-lines-3-plus-2.md` §v10-B · `docs/evidence/mod/`

---

## 验收矩阵

| # | 边界 | 结果 | 证据 |
|---|------|------|------|
| B1 | Catalog / 上架可见 | **PASS** | `mod/01-listing.png`（2026-07-11 Playwright） |
| B2 | 市场页可浏览 | **PASS** | `mod/02-store-page.png`（2026-07-11 Playwright） |
| B3 | 支付 0.01 → 入账 | **PASS** | `mod/03-payment.png` + 产品负责人确认已付成功 |
| B4 | FHD 宿主安装 / 已安装可见 | **PASS** | `mod/04-activated.png`（2026-07-11，企业登录 + `tab=installed`） |
| B5 | 履约 → 桌面 entitlement | **PASS** | `payment_fulfillment.py` 写 `UserMod`（`pkg_id`）；commit `aa36b62d7` |

## 环境

- MODstore：仓内 `*/MODstore_deploy`，API `:8788`，Market Vite `:5176`
- FHD API `:5000` / Web `:5001`，商家 `modpilot`（enterprise）
- 支付：`PAYMENT_BACKEND=python` + `keys/*.pem`（PKCS#1）

## 签字

| 角色 | 姓名/方式 | 日期 |
|------|-----------|------|
| 产品确认（支付闭环） | 会话确认「之前付款成功」 | 2026-07-11 |
| 工程验收（Catalog/安装/履约代码） | Cursor Agent + Playwright 01/02/04 | 2026-07-11 |

**结论**：v10-B 桌面端联动闭环 **可交付**；`specs/tasks.md` PL2 勾选。  
不升版本号；上线走既有 `10.0.0` 锚点 + git SHA / channel。

## 关联提交（节选）

- `aa36b62d7` — 支付履约同步 `user_mods`
- `ec59a8cc0` — Flutter CI SSOT + 01/02 证据
- `6e9d88b1c` — 04 企业登录证据路径
- `899ddad00` — 人工付路径 / Flutter 签名接线
