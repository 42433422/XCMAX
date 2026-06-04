import type { RouteRecordRaw } from 'vue-router'

export const approvalRoutes: RouteRecordRaw[] = [
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
        meta: { title: '审批工作台' }
      },
      {
        path: 'flow-management',
        name: 'approval-flow-management',
        component: () => import('../../views/ApprovalFlowManagementView.vue'),
        meta: { title: '审批流程管理' }
      },
      {
        path: 'rules',
        name: 'approval-rules',
        component: () => import('../../views/ApprovalRulesView.vue'),
        meta: { title: '审批规则配置' }
      }
    ]
  }
]
