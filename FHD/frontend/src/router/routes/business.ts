import type { NavigationGuardNext, RouteLocationNormalized, RouteRecordRaw } from 'vue-router'
import { AI_DELIVERY_ROUTES } from '../privateModDeliveryRoutes'

/** 宿主 ERP / 审批等业务路由（minimal 构建下为空数组） */
const routes: RouteRecordRaw[] = []

/** minimal 构建：Vite 静态剔除下列宿主 ERP/审批等业务路由（勿改为动态 import 独立 chunk） */
if (import.meta.env.VITE_XCAGI_EDITION !== 'minimal') {
  routes.push(
    {
      path: '/ai-ecosystem',
      name: 'ai-ecosystem',
      component: () => import('../../views/AIEcosystemView.vue'),
      meta: { title: '智能生态' },
    },
    ...AI_DELIVERY_ROUTES,
    {
      path: '/project-factory',
      name: 'project-factory',
      component: () => import('../../views/ProjectFactoryView.vue'),
      meta: { title: '项目工厂' },
    },
    {
      path: '/model-payment',
      name: 'model-payment',
      redirect: { name: 'settings', query: { section: 'model-payment' } },
      meta: { title: '模型服务' },
    },
    {
      path: '/kitten-finance',
      name: 'kitten-finance',
      component: () => import('../../views/KittenFinanceView.vue'),
      meta: { title: '财务分析' },
    },
    {
      path: '/products',
      name: 'products',
      component: () => import('../../views/ProductsView.vue'),
      meta: { title: '业务对象' },
    },
    {
      path: '/materials',
      name: 'materials',
      component: () => import('../../views/MaterialsView.vue'),
      meta: { title: '资源库' },
    },
    {
      path: '/materials-list',
      redirect: { name: 'materials' },
    },
    {
      path: '/orders',
      name: 'orders',
      component: () => import('../../views/OrdersView.vue'),
      meta: { title: '业务单据' },
    },
    {
      path: '/traditional-mode',
      name: 'traditional-mode',
      component: () => import('../../views/TraditionalModeView.vue'),
      meta: { title: '表格模式' },
    },
    {
      path: '/business-docking',
      name: 'business-docking',
      component: () => import('../../views/EtlCenterView.vue'),
      meta: { title: '数据对接中心' },
    },
    {
      path: '/orders/create',
      name: 'orders-create',
      component: () => import('../../views/CreateOrderView.vue'),
      meta: { title: '新建业务单据' },
    },
    {
      path: '/shipment-records',
      name: 'shipment-records',
      component: () => import('../../views/ShipmentRecordsView.vue'),
      meta: { title: '业务记录' },
    },
    {
      path: '/customers',
      name: 'customers',
      component: () => import('../../views/CustomersView.vue'),
      meta: { title: '组织管理' },
    },
    {
      path: '/data-sources',
      name: 'data-sources',
      component: () => import('../../views/DataSourcesView.vue'),
      meta: { title: '数据来源' },
    },
    {
      path: '/print',
      name: 'print',
      component: () => import('../../views/PrintView.vue'),
      meta: { title: '模板与打印' },
    },
    {
      path: '/printer-list',
      name: 'printer-list',
      component: () => import('../../views/PrinterListView.vue'),
      meta: { title: '打印机列表' },
    },
    {
      path: '/template-preview',
      name: 'template-preview',
      component: () => import('../../views/TemplatePreviewView.vue'),
      meta: { title: '模板预览' },
    },
    {
      path: '/label-editor',
      name: 'label-editor',
      component: () => import('../../views/LabelEditorView.vue'),
      meta: { title: '标签编辑器' },
    },
    {
      path: '/console',
      name: 'console',
      component: () => import('../../views/TemplatePreviewView.vue'),
      meta: { title: '模板预览' },
      beforeEnter: (to: RouteLocationNormalized, _from: RouteLocationNormalized, next: NavigationGuardNext) => {
        const view = to.query.view
        if (view === 'excel' || view === 'template-preview') {
          next()
        } else if (view) {
          next()
        } else {
          next()
        }
      },
    },
    {
      path: '/purchase',
      name: 'purchase',
      component: () => import('../../views/PurchaseView.vue'),
      meta: { title: '耗材申领' },
    },
    {
      path: '/batch-analyze',
      name: 'batch-analyze',
      component: () => import('../../views/BatchAnalyzeView.vue'),
      meta: { title: '批量分析' },
    },
    {
      path: '/enterprise-customer-service',
      name: 'enterprise-customer-service',
      redirect: { name: 'im' },
      meta: { title: '信息' },
    },
    {
      path: '/internal-customer-service',
      name: 'internal-customer-service',
      redirect: { name: 'im' },
      meta: { title: '信息' },
    },
    {
      path: '/approval-hub',
      name: 'approval-hub',
      component: () => import('../../views/ApprovalHubView.vue'),
      meta: { title: '审批中心' },
      redirect: { name: 'approval-workspace' },
      children: [
        {
          path: 'workspace',
          name: 'approval-workspace',
          component: () => import('../../views/ApprovalWorkspaceView.vue'),
          meta: { title: '审批工作台' },
        },
        {
          path: 'flow-management',
          name: 'approval-flow-management',
          component: () => import('../../views/ApprovalFlowManagementView.vue'),
          meta: { title: '审批流程管理' },
        },
        {
          path: 'rules',
          name: 'approval-rules',
          component: () => import('../../views/ApprovalRulesView.vue'),
          meta: { title: '审批规则配置' },
        },
      ],
    },
    {
      path: '/inventory',
      name: 'inventory',
      component: () => import('../../views/InventoryView.vue'),
      meta: { title: '库存管理' },
    },
  )
}

export const BUSINESS_ROUTES: RouteRecordRaw[] = routes
