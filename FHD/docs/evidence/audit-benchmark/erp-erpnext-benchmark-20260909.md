# R22 外部标杆实测：ERP 域开源锚点（ERPNext）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分；正式评分需全部必选证据齐备后另行出具。

## 审计记录字段（required_audit_record_fields）

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| source_sha | 405f0a13ffc98838c1cfd4b67b90e94e885fe74a（XCMAX 分支 feat/audit-roadmap-r01-r22） |
| main_sha | 405f0a13ffc98838c1cfd4b67b90e94e885fe74a |
| reference_versions_editions_regions | ERPNext v15 镜像（frappe/erpnext:v15，容器内 frappe 15.120.0 / erpnext 15.121.1），本地 Docker（db=mariadb、redis），站点 r22.localhost，单公司 R22 Bench Co（CNY） |
| dataset_hash | 任务脚本 sha256=177f19fa45fe3248dd0b6cdf96edfd27e3f28ab0aaa45899d7919e0f1591a314（/tmp/r22-erpnext/run_tasks.py） |
| task_protocol | T1 建单→出库→开票→收款；T2 金额精度；T3 冲销/退货；T4 重复提交；T5 超库存部分失败；T6 总账读回一致性 |
| predeclared_metrics_and_tolerances | 库存增量=3（精确）；金额一致（order=invoice=payment，容差 0）；核销后应收净额=0（容差 0.01） |
| model_and_budget | 不适用（确定性业务任务，无 LLM） |
| environment | 本机 Docker（macOS），ERPNext 容器 + bench console 外独立 python runner（frappe.init/connect） |
| evidence_ids | 本文档 + 原始 RESULT 行（sha256=e8ab04de6b7d4ade13b6896716c7ef654e80d6e5252fae916067563aab12f7ee） |
| observed_results | 见下表，6/6 PASS |
| unknowns | 商业锚点（SAP S/4HANA / Oracle Fusion / Dynamics 365）未实测 → 90 分锚点仍为 not_run；多租户/跨币种/审批职责分离（erp-C2/C3）未在本任务集覆盖 |
| axis_levels | 本记录仅覆盖 contracts/correctness/verification 轴的 ERP 域基线证据，不出具轴分 |
| domain_status | erp 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实软件环境完整任务+故障拒绝） |
| score | 不授予（单锚点单域记录，正式分需全必选证据） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-09（Asia/Shanghai） |

## 逐任务结果（ERPNext v15 实测）

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| T1 建单→出库→开票→收款 | erp-B1 | PASS | 库存 10→7（出库 3）；order=invoice=payment=20200.00；发票状态 Paid、未核销 0 |
| T2 金额精度 | erp-B2 | PASS | 输入 19999.995 按 currency_precision 舍入落库为 20000.00（明确业务约束，非静默丢精度） |
| T3 冲销/退货 | erp-B2 | PASS | `make_return_doc` 生成退货单 MAT-DN-2026-00007，库存回补 +3，可追溯到原出库单 |
| T4 重复提交 | erp-B3 | PASS | 对已提交单重复 submit 为空操作：docstatus 保持 1，Stock Ledger/GL Entry 行数零新增（幂等防重） |
| T5 超库存部分失败 | erp-B3 | PASS | 99999 出库被 NegativeStockError 整体拒绝，台账行数前后不变（无部分副作用） |
| T6 账表一致性 | erp-B3 | PASS | 本次发票+收款总账读回 4 行，Debtors 净额=0.00（核销闭环） |

## 环境修复记录（如实留痕，非产品缺陷）

ERPNext 容器为最小化手工初始化（非 setup wizard），实测前需补齐：
Company 科目/成本中心树（`create_default_cost_center`）、Fiscal Year、Price List（CNY）、
Mode of Payment（Cash 绑定账户）、Round Off/Write Off 科目、Item Default 收支科目、
站点默认币种（INR→CNY）、`allow_multiple_items`、Contact `is_billing_contact` 自定义字段
（`erpnext.setup.install.create_address_and_contact_custom_fields`）、`bench migrate` 补 schema。
Payment Entry 引用行必须显式 `allocated_amount`，否则 validate 阶段被裁空（API 形态与 UI 不同）。

## 结论与边界

- ERP 域**开源 60 分锚点（ERPNext）三项必选基线 B1/B2/B3 在同任务集上全部实测通过**，证据级别 E3。
- 该结果证明 XCMAX 在 R10 端到端验收中所验证的四账一致/防重/冲销语义与行业开源基线等价可复现；
  不据此宣称 XCMAX 达到或超过任何商业产品（90 分锚点未实测，政策禁止）。
- 其余 17 域开源锚点实测与全部商业锚点实测仍未完成，R22 整体保持进行中。
