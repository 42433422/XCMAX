# R22 外部标杆实测：FHD 前端与用户任务域开源锚点（ERPNext Desk）同任务集实测记录

> 标准版本：`external-anchors-v1`（`FHD/config/audit_benchmark_ssot.json`）。
> 本文是**单域单锚点的实测审计记录**，不是 18 域正式评分。

## 审计记录字段

| 字段 | 值 |
|---|---|
| standard_version | 1.0.0 |
| scoring_version | external-anchors-v1 |
| reference_versions_editions_regions | ERPNext v15 镜像（frappe/erpnext:v15，容器内 frappe 15.120.0 / erpnext 15.121.1，GPL-3.0），站点 r22.localhost。**版本边界**：基准目录固定参考为 frappe/erpnext@e0d6d797（分支代码快照），本次实测为 v15 稳定发行版，差异已在本记录登记（政策允许，不声称等同该 SHA） |
| dataset_hash | 任务脚本与导出样例随本文档存档（同目录 business-frontend-erpnext-desk-tasks / export-sample） |
| task_protocol | B1 登录后核心业务任务+输入校验+空状态；B2 加载/失败/健康/结果状态来自真实服务；B3 筛选、编辑、导出语义一致。经 Desk 前端实际调用的 REST 层（/api/method/*，与 UI 同一代码路径）执行 |
| predeclared_metrics_and_tolerances | B1 真实建单成功且服务端拒绝非法物料/数量 0、不存在筛选返回空列表非报错；B2 ping=200、坏 DocType 返回服务端异常、列表计数与 DB 行数精确一致、未登录核心 API 真实 401；B3 编辑后重读精确一致、name 精确筛选唯一命中、导出 CSV 含编辑标记 |
| environment | 本机 macOS Docker（r22-erpnext-backend-1:18081，Host 头路由站点），curl 直连 Desk REST 层 |
| observed_results | B1/B2/B3 全部 PASS（见下表） |
| unknowns | 商业锚点（SAP Fiori / Microsoft Dynamics 365 Business Central / Oracle NetSuite ERP）未实测；本记录走 Desk 前端实际调用的同一 REST 代码路径，未做浏览器像素级 UI 断言（列表视图渲染、看板拖拽等纯前端语义不在本任务范围）；scope_note 要求按完整任务比较而非页面数，本记录只覆盖必选治理语义 |
| domain_status | business-frontend 域开源 60 分锚点：B1/B2/B3 实测通过（E3：真实软件环境完整任务） |
| score | 不授予（单锚点记录） |
| auditor | agent-mac-trae |
| observed_at | 2026-09-09（Asia/Shanghai） |

## 逐任务结果

| 任务 | 对应锚点 | 结果 | 关键证据 |
|---|---|---|---|
| B1 核心任务+校验+空状态 | business-frontend-B1 | PASS | 登录后建销售订单成功（`SAL-ORD-2026-00008`）；非法物料/数量 0 均被服务端 ValidationError 真实拒绝（非仅前端提示）；不存在单据筛选返回 `"message":[]` 空状态而非报错 |
| B2 状态来自真实服务 | business-frontend-B2 | PASS | `ping`=200；坏 DocType 查询返回服务端异常；Desk 列表计数=8 与 DB `frappe.db.count`=8 精确一致（结果状态非伪造）；删 cookie 后核心 API 真实 401 |
| B3 筛选/编辑/导出一致 | business-frontend-B3 | PASS | 编辑 `po_no=R22-PO-SAL-ORD-2026-00008` 后重读精确一致；name 精确筛选唯一命中；Data Export CSV 含同一编辑标记（导出与 DB 一致，样例已存档） |

## 环境修复记录（如实留痕）

- Frappe 按 `Host` 头路由站点，直连端口必须带 `Host: r22.localhost`。
- `frappe.client.get/set_value` 参数名为 `doctype/name/fieldname/value`（非 v1 reference_* 命名）；`_notes` 是 Comment 表非文档字段，编辑断言改用真实字段 `po_no`。
- Sales Order 服务端强制 `delivery_date`，缺失即 ValidationError（这本身是 B1 输入校验的证据）。
- 导出 CSV 不含 name 列（Data Export 语义），一致性断言改用编辑标记列。

## 与 XCMAX 侧对照

XCMAX 同域验收见 R10（ERP 建单→出库→收款→冲销端到端 2/2 绿）与 R21（商城付款/授权/交付/退款 121 项全绿）。
本记录证明 ERPNext Desk 开源基线在同等必选语义（真实服务端校验、状态来自真实服务、筛选/编辑/导出一致）
上行为一致，XCMAX 前端业务契约不低于该开源锚点；不据此宣称达到商业产品水平（90 分锚点未实测）。
