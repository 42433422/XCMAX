# 1.0-A 首样板验收清单：通用（Generic）

> **状态**：当前战役首样板（2026-07-29 起）  
> **产品版本**：`1.0.0.0`（见 [`VERSION.md`](../../VERSION.md)）  
> **行业 id**：`通用`  
> **L2 种子 mod**：`xcagi-planner-bridge`（见 [`config/industry_baseline.json`](../../config/industry_baseline.json)）  
> **定位**：干净宿主起步——智能对话 + 智能生态底座；行业垂直能力按需再补，**不**把涂料/考勤等当作首样板承诺。

关联：[`DELIVERABLE_PRODUCT.md`](../DELIVERABLE_PRODUCT.md) · [`guides/PRODUCT_USER_FLOW.md`](../guides/PRODUCT_USER_FLOW.md) · [`CUSTOMER_SUPPORT.md`](CUSTOMER_SUPPORT.md)  
战役全量任务（含商店/消膨胀/工单）：[`../../../specs/checklist-1.0-campaign-full.md`](../../../specs/checklist-1.0-campaign-full.md)

---

## 0. 承诺边界（签字前必读）

| 本清单承诺 | 本清单明确不承诺 |
|------------|------------------|
| 企业桌面 enterprise 安装、启动、引导 | Android / iOS 签约级交付 |
| L1 通用 bridge 装齐后 `deliverable: true` | 完整 RBAC / IdP / SIEM |
| 行业选「通用」后对话与宿主可用 | 涂料/考勤等垂直行业深度流程 |
| 日志、备份、升级核对口径 | 客来来全渠道商用、yuangon「客户侧 55 员工」 |

后续行业样板（涂料、考勤等）另开验收清单，不得挤占本首样板口径。

---

## 1. 环境与版本

| # | 检查项 | 通过标准 | 实际 | 签字 |
|---|--------|----------|------|------|
| 1.1 | 安装包 / 构建标识 | 产品版本 `1.0.0.0`，SKU `enterprise` | | |
| 1.2 | 关于页 / 属性 | 与供应商发行说明一致 | | |
| 1.3 | 数据目录 | 已记录 userData 路径（见 CUSTOMER_SUPPORT） | | |

---

## 2. 引导与宿主就绪

按 [`PRODUCT_USER_FLOW.md`](../guides/PRODUCT_USER_FLOW.md)：`welcome` → `industry=通用` → `host-pack`。

| # | 检查项 | 命令 / 界面 | 通过标准 | 实际 | 签字 |
|---|--------|-------------|----------|------|------|
| 2.1 | 首次引导可选「通用」 | `/onboarding` · `GET /api/platform-shell/onboarding-industries` | 「通用」在开放列表且可选 | | |
| 2.2 | 一键装齐通用包 | `POST /api/mod-store/bootstrap-edition-pack?edition=generic` 或引导按钮 | `success: true` | | |
| 2.3 | 可交付 API | `GET /api/platform-shell/deliverable-status` | 见下表字段 | | |
| 2.4 | 行业种子（可选） | `POST /api/mod-store/install-industry-seed`（industry=`通用`） | 成功或已跳过且说明原因 | | |

### 2.3 字段表（`deliverable-status`）

| 字段 | 期望 |
|------|------|
| `success` | `true` |
| `data.deliverable` | `true` |
| `data.generic_pack_installed` | `true`（或 `missing_mod_ids` 为空） |
| `data.blockers` | `[]` 或空 |
| `product_sku` / edition | 与 enterprise / 约定 edition 一致 |

L1 必须齐（`GENERIC_HOST_MOD_IDS`）：

- `xcagi-planner-bridge`
- `xcagi-neuro-bus-bridge`
- `xcagi-erp-domain-bridge`
- `xcagi-core-workflow-employees`
- `xcagi-approval-bridge`
- `xcagi-lan-license-bridge`
- `xcagi-model-payment-bridge`
- `xcagi-office-employee-pack-bridge`
- `xcagi-customer-service-bridge`

> 通用行业自身 `host_mod_ids` 为空；首样板以 **L1 宿主包 + 对话** 为完成线。`optional_host_mod_ids`（`xcagi-planner-excel-tools`、`xcagi-erp-domain-bridge`）为加分项，不挡首样板签字。

---

## 3. 三个日常业务动作（首样板固定）

| # | 动作 | 路径 | 通过标准 | 实际 | 签字 |
|---|------|------|----------|------|------|
| 3.1 | 智能对话一轮 | `/` 或 Planner 对话入口 | 发出一句、收到回复、无 5xx | | |
| 3.2 | 宿主能力可见 | `GET /api/platform-shell/capabilities` 或侧栏壳菜单 | `success: true`；侧栏可见对话/壳入口 | | |
| 3.3 | 智能生态门面 | NeuroBus bridge 已装（侧栏或 `deliverable-status` 无缺失） | `xcagi-neuro-bus-bridge` 在已装列表；健康探针 `/api/health` = 200 | | |

**加分（非必须）：** 从扩展市场或引导安装 `xcagi-planner-excel-tools` 或打开 ERP 门面一页。

证据：每动作截图 + `deliverable-status` JSON + `capabilities` JSON，目录建议：

`FHD/docs/evidence/e2e/closure-generic-1.0-A-YYYYMMDD/`

---

## 4. 运维抽检

| # | 检查项 | 通过标准 | 实际 | 签字 |
|---|--------|----------|------|------|
| 4.1 | 日志可定位 | 能指出当日日志文件路径 | | |
| 4.2 | 备份 | 退出后复制 userData 或 `backups/` 下 db | | |
| 4.3 | 重装验证 | 备份还原或重装后再次 `deliverable: true` | | |

---

## 5. 供应商侧自动化（非客户勾选，发版前必跑）

在仓根 / `FHD/`：

```powershell
powershell -ExecutionPolicy Bypass -File FHD/scripts/dev/deliverable_smoke.ps1
```

或：

```bash
cd FHD
python -m pytest tests/test_deliverable_status.py tests/test_edition_policy.py -q --tb=short
python3 scripts/dev/verify_version_anchors.py
```

| # | 检查项 | 结果 |
|---|--------|------|
| 5.1 | deliverable pytest | |
| 5.2 | version anchors | |
| 5.3 | （可选）安装包冷启 deliverable | |

---

## 6. 签字

| 角色 | 姓名 | 日期 | 结论（PASS / FAIL） |
|------|------|------|---------------------|
| 客户实施 | | | |
| 供应商交付 | | | |

失败时：只修本清单缺口，不扩展行业样板范围。下一行业样板须新建 `ACCEPTANCE_<行业>_1.0-A.md`，不得改写本文件承诺。
