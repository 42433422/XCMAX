# Mods 前端 UI 原语审计清单

> P2-1「mods 前端组件体系分散」Stage 3 产出。
> 背景：`mods/*/frontend/views/**` 下每个 mod 自带一套 vue 组件，重复内联 `<style>` 与 UI 原语。
> 宿主前端 `frontend/src/components/` 已有共享原语（DataTable / Modal / ConfirmDialog /
> InputDialog / AppDialogHost / PaneResizeHandle 等），mods 视图可通过 `@/...` 别名导入复用
> （如 `import { APPROVAL_BRIDGE_MOD_ID } from '@/constants/approvalMod'`）。
> 本清单用于量化重复内联样式体量并引导逐步迁移。
>
> 统计口径：`scripts/dev/guard_mods_inline_ui.py --report`（块内非空、非纯注释行数）。

## 1. 内联样式体量排行（35 个视图，非空 `<style>` 行数）

| 视图（相对 mods/） | style 块数 | style 行数 |
| --- | ---: | ---: |
| xcagi-erp-domain-bridge/.../TraditionalModeView.vue | 1 | 895 |
| xcagi-model-payment-bridge/.../ModelPaymentView.vue | 1 | 717 |
| xcagi-planner-bridge/.../BrainView.vue | 1 | 643 |
| xcagi-erp-domain-bridge/.../BatchAnalyzeView.vue | 1 | 599 |
| xcagi-approval-bridge/.../ApprovalWorkspaceView.vue | 1 | 523 |
| xcagi-erp-domain-bridge/.../TemplatePreviewView.vue | 1 | 384 |
| xcagi-erp-domain-bridge/.../LabelEditorView.vue | 1 | 374 |
| xcagi-approval-bridge/.../ApprovalFlowManagementView.vue | 1 | 308 |
| xcagi-core-workflow-employees/.../WorkflowVisualizationView.vue | 1 | 277 |
| xcagi-approval-bridge/.../ApprovalRulesView.vue | 1 | 256 |
| taiyangniao-pro/.../HomeView.vue | 1 | 221 |
| xcagi-erp-domain-bridge/.../CreateOrderView.vue | 1 | 208 |
| xcagi-model-payment-bridge/.../KittenFinanceView.vue | 1 | 174 |
| xcagi-erp-domain-bridge/.../DataSourcesView.vue | 1 | 170 |
| xcagi-planner-bridge/.../AIEcosystemView.vue | 1 | 139 |
| xcagi-erp-domain-bridge/.../CustomersView.vue | 1 | 110 |
| xcagi-planner-bridge/.../ChatDebugView.vue | 1 | 81 |
| xcagi-erp-domain-bridge/.../ShipmentRecordsView.vue | 1 | 63 |
| xcagi-customer-service-bridge/.../InternalCustomerServiceView.vue | 1 | 56 |
| xcagi-customer-service-bridge/.../EnterpriseCustomerServiceView.vue | 1 | 52 |
| xcagi-workflow-visualization-bridge/.../WorkflowVisualizationView.vue | 1 | 50 |
| xcagi-office-employee-pack-bridge/.../ToolsView.vue | 1 | 46 |
| xcagi-approval-bridge/.../ApprovalHubView.vue | 1 | 42 |
| xcagi-erp-domain-bridge/.../PurchaseView.vue | 1 | 37 |
| xcagi-erp-domain-bridge/.../InventoryView.vue | 1 | 16 |
| xcagi-erp-domain-bridge/.../MaterialsView.vue | 1 | 11 |
| xcagi-planner-bridge/.../ChatView.vue | 1 | 10 |
| sz-qsm-pro/.../HomeView.vue | 1 | 9 |
| xcagi-erp-domain-bridge/.../ProductsView.vue | 1 | 8 |
| xcagi-lan-license-bridge/.../LanGateView.vue | 1 | 8 |
| xcagi-office-employee-pack-bridge/.../OtherToolsView.vue | 1 | 4 |
| xcagi-erp-domain-bridge/.../BusinessDockingView.vue | 0 | 0 |
| xcagi-erp-domain-bridge/.../OrdersView.vue | 0 | 0 |
| xcagi-erp-domain-bridge/.../PrintView.vue | 0 | 0 |
| xcagi-erp-domain-bridge/.../PrinterListView.vue | 0 | 0 |

> 阈值提醒（`--check`，>300 行）：TraditionalModeView / ModelPaymentView / BrainView /
> BatchAnalyzeView / ApprovalWorkspaceView / TemplatePreviewView / LabelEditorView /
> ApprovalFlowManagementView 共 8 个视图超标。

## 2. 原语类型 → 受影响视图 → 宿主原语 → 建议动作

| 原语类型 | 受影响视图列表 | 宿主共享原语 | 建议动作 |
| --- | --- | --- | --- |
| 数据表（table + 分页） | BatchAnalyzeView / TraditionalModeView / TemplatePreviewView / MaterialsView / PurchaseView / InventoryView / ShipmentRecordsView / ApprovalFlowManagementView | `@/components/DataTable.vue`（columns/data/分页插槽/空态/加载态） | 复用 |
| 对话框 / 弹窗（modal overlay + content） | ApprovalWorkspaceView ✓ / ApprovalRulesView ✓ / ApprovalFlowManagementView / BatchAnalyzeView / TraditionalModeView / CustomersView / TemplatePreviewView / PurchaseView / CreateOrderView / ShipmentRecordsView / MaterialsView | `@/components/Modal.vue`（v-model + title + footer slot）；`ConfirmDialog.vue` / `InputDialog.vue` 用于确认/输入 | 复用（试点两视图已迁移）；其余待迁移 |
| 确认 / 输入对话框 | ApprovalWorkspaceView（appConfirm/appPrompt）/ ApprovalRulesView（appAlert）/ ApprovalFlowManagementView | `@/components/AppDialogHost.vue` + `@/utils/appDialog`（appAlert/appConfirm/appPrompt） | 复用（已接入，确认保留） |
| 按钮样式（btn-approve / btn-reject / btn-edit / btn-delete / btn-link / btn-ghost） | TraditionalModeView / BatchAnalyzeView / ApprovalWorkspaceView / ApprovalFlowManagementView / ApprovalRulesView / CustomersView / PurchaseView / InventoryView | 宿主无独立按钮原语；`DataTable` 样式穿透 `:deep(.btn)` | 保留（宿主暂未收敛按钮体系，登记「待补原语」） |
| 徽标 / 状态标签（status-tag / badge / rule-trigger） | ApprovalWorkspaceView / ApprovalRulesView / ApprovalFlowManagementView / BatchAnalyzeView / TraditionalModeView / InternalCustomerServiceView / EnterpriseCustomerServiceView | 宿主未见统一状态标签组件 | 保留（待补原语） |
| 空态 / 加载态（empty-state / empty-hint / loading-hint / loading-state） | ApprovalWorkspaceView / ApprovalFlowManagementView / BatchAnalyzeView / TraditionalModeView / ShipmentRecordsView / PrinterListView / DataSourcesView / KittenFinanceView / InternalCustomerServiceView / EnterpriseCustomerServiceView | `DataTable.vue` 内建 empty/loading 行；宿主其余页面无独立组件 | 部分复用（表格场景）；卡片/列表场景保留（待补原语） |
| 指标条 / 统计卡（stat-card / progress / metric） | ApprovalWorkspaceView（统计卡）/ InternalCustomerServiceView（cs-metrics）/ BrainView / ModelPaymentView | 宿主未见通用统计卡/进度条组件 | 保留（待补原语） |
| 表单栅格（form-group / form-grid / add-form） | TraditionalModeView / ApprovalRulesView / ProductsView / CustomersView / PurchaseView / CreateOrderView / InventoryView / MaterialsView | 宿主未见统一表单栅格组件 | 保留（待补原语） |
| 时间轴（timeline） | ApprovalWorkspaceView（审批记录）/ ApprovalFlowManagementView | 宿主未见 timeline 组件 | 保留（业务专属，待补原语） |
| 客户卡片 / 工作台面板 | InternalCustomerServiceView / EnterpriseCustomerServiceView | 已拆分至 `../components/Customer*Panel.vue` 子组件 | 保留（已组件化，无内联重复） |

> ✓ = 本 Stage 3 已迁移完成。

## 3. 试点迁移记录（xcagi-approval-bridge）

| 视图 | 复用宿主原语 | 删除内联样式 |
| --- | --- | --- |
| ApprovalWorkspaceView.vue | `@/components/Modal.vue`（详情弹窗，max-width 800px，footer 通过/拒绝/关闭） | 删除 `.modal-overlay` / `.modal-content` / `.modal-header` / `.btn-close` / `.modal-body` / `.modal-footer` 结构样式 |
| ApprovalRulesView.vue | `@/components/Modal.vue`（编辑规则弹窗，max-width 420px，footer 取消/保存） | 删除 `.edit-modal` / `.modal-content` / `.modal-content h3` / `.modal-actions` 结构样式 |

迁移原则：最小改动、不改变 props/emits/对外行为；仅替换可无损复用的窄 popup 结构，按钮/状态/时间轴等宿主无现成原语处一律保留内联实现并登记「待补原语」。

客服试点（xcagi-customer-service-bridge）视图已在此前「客服视图拆分」（git log `66e08f68a` 等）中拆为 `../components/Customer*Panel.vue` 子组件，内联样式体量小（≤56 行），本阶段无需迁移。

## 4. 后续建议（后续 Task 处理）

1. 将 `guard_mods_inline_ui.py --check` 接入 CI review 提示（当前仅提醒、不失败）。
2. 优先迁移内联样式 >300 行的 8 个视图：TraditionalModeView / ModelPaymentView / BrainView / BatchAnalyzeView / TemplatePreviewView / LabelEditorView / ApprovalFlowManagementView 的表单/弹窗到 `Modal.vue`、表格到 `DataTable.vue`。
3. 宿主侧补齐「按钮体系 / 状态标签 / 统计卡 / 表单栅格」原语后，再收敛对应内联实现。