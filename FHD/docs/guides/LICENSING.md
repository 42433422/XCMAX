# XCAGI 许可证与商业化指南

> **目的**：帮助用户、Mod 作者、集成商、销售准确理解 XCAGI 的 **许可边界** 与商业化路径。
>
> **定价 SSOT（运行时，销售/实现必读）**：
> - 企业宿主授权（体验/永久）：[`config/saas_plans.json`](../../config/saas_plans.json)
> - 市场会员（VIP / SVIP）：MODstore `PlanTemplate`（[`init_default_plan_templates`](../../../成都修茈科技有限公司/MODstore_deploy/modstore_server/db/base.py)）
> - 账号体系与两层定价关系：[`account_system_ssot.md`](../account_system_ssot.md) §2.2 / §2.4
>
> **勿引用本文旧版 FAQ 中的年费/实例价**；已退役，以 SSOT 为准。
>
> **关联文档**：[`LICENSE`](../../LICENSE) · [`COMMERCIAL_LICENSE.md`](../../COMMERCIAL_LICENSE.md) · [`MOD_AUTHORING_GUIDE.md`](MOD_AUTHORING_GUIDE.md)
>
> **版本**：1.1.0 · 2026-07-07

---

## 1. 一图看懂：选择哪个许可证

```
                    ┌─────────────────────────────────┐
                    │  你准备如何使用 XCAGI？          │
                    └────────────┬────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
  个人学习 / 评估          中小企业（年收入<¥10万    大企业 / SaaS 转售 /
  开源贡献                且<50人）/ Mod 作者        合规审计 / SLA
        │                        │                        │
        ▼                        ▼                        ▼
  Apache-2.0              Apache-2.0              Commercial EULA
  (LICENSE)               (LICENSE)               (COMMERCIAL_LICENSE.md)
  ✅ 免费使用             ✅ 免费使用              💰 按 SSOT 套餐收费
  ✅ 可商用               ✅ 可商用（限规模）       📜 签署 EULA
  ❌ 无 SLA               ❌ 无 SLA                ✅ 99.5-99.9% SLA（套餐约定）
  ❌ 无商标授权           ❌ 无商标授权             ✅ 商标授权可选
  ✅ 可贡献 Mod           ✅ 可发布 Mod 收费        ✅ 可发布 Mod 收费
```

---

## 2. 许可证矩阵（不含具体金额）

| 使用场景 | 适用许可 | 是否需要付费 | 是否需要 EULA | 是否需要 Token |
|---------|---------|--------------|---------------|----------------|
| 个人学习 / 技术评估 | Apache-2.0 | ❌ | ❌ | 可选（基础功能本地可用） |
| 个人开发者构建小工具 | Apache-2.0 | ❌ | ❌ | 可选 |
| 中小企业内部使用（< ¥10万/年 且 < 50 人） | Apache-2.0 | ❌ | ❌ | 可选 |
| 中小企业 Mod 作者发布免费 Mod | Apache-2.0 | ❌ | ❌ | ❌ |
| Mod 作者发布付费 Mod | Apache-2.0 + Mod 商店协议 | 平台抽成 30% | ❌ | ✓ 销售用 |
| 大企业（年收入 ≥ ¥10万 或 ≥ 50 人） | Commercial EULA | ✓ | ✓ 必签 | ✓ |
| SaaS / PaaS 转售 | Commercial EULA OEM 版 | ✓ OEM 费 | ✓ 必签 | ✓ |
| 合规审计（等保三级 / HIPAA / PCI-DSS） | Commercial EULA | ✓ | ✓ 必签 | ✓ |
| 金融 / 医疗 / 政府客户 | Commercial EULA + 行业附加 | ✓ | ✓ | ✓ |
| 完全离线部署（无云端依赖） | Commercial EULA Offline Bundle | ✓（商务订单） | ✓ | ❌（关闭） |

---

## 3. 定价 SSOT（两层，已同步）

### 3.1 企业宿主授权（FHD / 桌面交付）

机器配置：[`config/saas_plans.json`](../../config/saas_plans.json)

| 套餐 ID | 对外名 | 价格（CNY） | 说明 |
|---------|--------|-------------|------|
| `saas-trial-30` | 30 天体验账户 | **¥99**（含 ¥100 额度） | 30 天到期后冻结，可购永久授权 |
| `saas-permanent-starter` | 永久 · 1–5 万预算 | **¥49,999** | `account_tier`: normal |
| `saas-permanent-growth` | 永久 · 5–10 万 | **¥99,999** | `account_tier`: pro |
| `saas-permanent-max` | 永久 · 10–50 万 | **¥499,999** | `account_tier`: max |
| `saas-permanent-ultra` | 永久 · 50–100 万 | **¥999,999** | `account_tier`: ultra |

预算档与 `account_tier` 派生规则见 [`account_system_ssot.md`](../account_system_ssot.md) §2.2。

### 3.2 市场会员（MODstore / 网站 AI 市场）

机器配置：MODstore `PlanTemplate`，种子数据 [`init_default_plan_templates`](../../../成都修茈科技有限公司/MODstore_deploy/modstore_server/db/base.py)

| 套餐 ID | 名称 | 价格（CNY/月计划） |
|---------|------|-------------------|
| `plan_basic` | VIP | **¥9.9** |
| `plan_pro` | VIP+ | **¥29.9** |
| `plan_enterprise` | svip | **¥99.9** |
| `plan_svip2` … `plan_svip8` | SVIP2–8 | **¥199** … **¥4,999** |

会员权益（额度、BYOK、存储等）以运行时 `PlanTemplate.features_json` / `quotas_json` 为准。

**关系**：企业永久授权与 VIP/SVIP **并列存在**；AI 额度消耗 **不反向** 升降 `account_tier` 或会员档（见 `account_system_ssot.md` §2.4）。

---

## 4. Mod 商店与第三方 Mod 的许可证

4.1 **平台默认**：[`manifest.json`](../../MODstore/modman/catalog_publish.md) 中 `license.type` 字段默认 `Apache-2.0`；Mod 作者可选择 `MIT` / `BSD-3-Clause` / `GPL-2.0` / `MPL-2.0` / `商业专有` / `自定义` 等。

4.2 **官方认证 Mod（OAC）**：由许可方（成都修茈科技）进行安全审计与兼容性测试，提供有限瑕疵担保（详见 EULA 附件 B）；OAC 状态显示在 Mod 商店页面徽标上。

4.3 **第三方 Mod 风险**：许可方**不对**第三方 Mod 的内容、可用性、安全性、合规性承担责任；Mod 作者在发布时须遵守 [`MOD_AUTHORING_GUIDE.md`](MOD_AUTHORING_GUIDE.md) 第 4 节的安全基线。

4.4 **GPL 类 Mod 特殊条款**：

- GPL-2.0 / GPL-3.0 Mod 不得用于闭源商业产品；
- AGPL Mod 不得在 XCAGI 商业版中分发（已与 Apache-2.0 协议冲突）；
- 商业专有 Mod 由 Mod 作者单独定价，分成比例按 EULA 附件 A。

4.5 **Mod 商店分成**（仍有效）：默认 **70% 开发者 / 30% 平台**；OAC 认证 Mod **80% / 20%**；月结 T+5。

---

## 5. Token 网关与云端 AI 核心

| 组件 | 部署位置 | 许可证 | 说明 |
|------|----------|--------|------|
| **XCAGI 本体** | 自托管 / 桌面 / Web | Apache-2.0 / Commercial EULA | 本仓库代码 |
| **Token 钱包** | 自托管 | Apache-2.0 | 钱包逻辑开源 |
| **Token 网关**（云端） | XCAGI Cloud | **闭源** | 许可证验证、用量计费、防绕过 |
| **云端意图识别** | XCAGI Cloud | **闭源** | 高准确率 LLM 推理 |
| **LLM Provider Registry** | 本地 + 云端双部署 | Apache-2.0（本地）/ 闭源（云端） | 注册表 schema 开源，云端调度闭源 |
| **离线 Bundle** | 纯本地 | Commercial EULA Offline | 关闭云端依赖；价格与功能子集以 **EULA 附件 A** 为准 |

---

## 6. 完全离线模式（Offline Bundle）

6.1 **适用场景**：金融、政府、军工、医疗等**严禁数据出网**的客户。

6.2 **启用条件**：签署 Commercial EULA + Offline Bundle 附加条款；**具体费用不在本文列价**，以商务订单 / EULA 附件 A 为准。

6.3 **功能差异**：

| 功能 | 在线模式 | 离线模式 |
|------|----------|----------|
| 本地 AI 推理（本地模型） | ✓ | ✓（需客户自备模型） |
| 云端 AI 推理 | ✓ | ❌ |
| Token 计费 | ✓ | ❌（一次性授权） |
| Mod 商店在线浏览 | ✓ | ❌ |
| Mod 商店离线导入 | ✓ | ✓（客户线下采购后导入） |
| 远程更新 | ✓ | ❌（客户线下升级包） |
| 多端协同 | ✓ | 仅同局域网 |

---

## 7. 商标与品牌使用

7.1 "XCAGI" 文字商标、XCAGI 徽标、XCAGI Cloud 标识、Neuro-DDD 标识均为许可方注册商标或申请中商标。

7.2 社区版用户使用商标须遵守《[品牌使用指南](https://xcagi.com/legal/brand-guidelines)》（"Powered by XCAGI" 横幅、链接规范等）。

7.3 Commercial EULA 客户可在书面授权后使用商标进行二次营销；OEM 客户可使用 "XCAGI Inside" 标识。

---

## 8. 常见问题（FAQ）

**Q1：我是个人开发者，能用 XCAGI 做商业项目吗？**
A：可以。年收入 < ¥10 万 且 < 50 员工的小型组织（含个体工商户）适用 Apache-2.0 社区版；超出阈值需签 EULA。

**Q2：我做了一个 Mod 卖给客户，分成怎么算？**
A：Mod 商店默认 70%（开发者）/ 30%（平台）；OAC 认证 Mod 分成 80% / 20%。月结，T+5。

**Q3：企业客户买永久授权多少钱？**
A：以 [`saas_plans.json`](../../config/saas_plans.json) 为准：体验 **¥99**；永久授权 **¥49,999 – ¥999,999**（按预算档）。详见 §3.1。

**Q4：VIP / SVIP 会员多少钱？**
A：以 MODstore `PlanTemplate` 为准：**¥9.9（VIP）– ¥4,999（SVIP8）**。详见 §3.2。

**Q5：大客户要求源代码审计，能给吗？**
A：Apache-2.0 社区版已公开源码；等保三级等合规场景需 Commercial EULA + **另行商务报价**的安全审计服务（本文不列固定价）。

**Q6：开源贡献者签了 CLA 后还能改协议吗？**
A：可以。CLA 赋予许可方单独、永久、不可撤销、可再许可的权利。详见 [`.github/CONTRIBUTING.md`](../../.github/CONTRIBUTING.md) 第 4 节。

**Q7：历史 commit 还是 AGPL-3.0，会影响新协议吗？**
A：不影响。协议变更向前生效；HEAD 指向的 `LICENSE` 适用 Apache-2.0。

**Q8：竞品用了我的代码，能起诉吗？**
A：Apache-2.0 允许竞品使用，但**不得使用商标**；发起专利诉讼则专利授权自动失效。

---

## 9. 联系商务

- **销售咨询**：business@xcagi.com
- **法务咨询**：legal@xcagi.com
- **技术支持**：support@xcagi.com
- **Mod 作者入驻**：mod-store@xcagi.com
- **OEM / 战略合作**：bd@xcagi.com
- **公开文档**：https://docs.xiu-ci.com/

---

## 10. 已退役口径（禁止对外引用）

| 退役内容 | 原因 | 替代 SSOT |
|----------|------|-----------|
| 企业年费 ¥5万–20万+ | 2026-06 前法务草稿 | `saas_plans.json` 永久授权档 |
| Offline Bundle 固定 +¥50,000 | 未与运行时对齐 | EULA 附件 A / 商务订单 |
| EULA 参考价 ¥10k–30k / ¥50k–100k / ¥200k 年 | 旧套餐表 | `saas_plans.json` + `account_system_ssot.md` |
| Token 包 ¥999 / ¥2,999 / ¥9,999 月 | 旧 BUSINESS_MODEL 草稿 | MODstore `PlanTemplate` |

---

*最后更新：2026-07-07 · 定价已同步至 `saas_plans.json` 与 MODstore `PlanTemplate`；许可边界仍以 `LICENSE` / `COMMERCIAL_LICENSE.md` 为准。*
