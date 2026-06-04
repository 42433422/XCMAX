import type { RouteRecordRaw } from 'vue-router'

export const toolsRoutes: RouteRecordRaw[] = [
  {
    path: '/tools',
    name: 'tools',
    component: () => import('../../views/ToolsView.vue'),
    meta: { title: '工具' }
  },
  {
    path: '/other-tools/employee-load-remove',
    name: 'workflow-employee-load-remove',
    component: () => import('../../views/WorkflowEmployeeLoadRemoveView.vue'),
    meta: { title: '加载和去除员工' }
  },
  {
    path: '/other-tools',
    name: 'other-tools',
    component: () => import('../../views/OtherToolsView.vue'),
    meta: { title: '其他工具' }
  },
  {
    path: '/chat-debug',
    name: 'chat-debug',
    component: () => import('../../views/ChatDebugView.vue'),
    meta: { title: '对话调试' }
  },
  {
    path: '/batch-analyze',
    name: 'batch-analyze',
    component: () => import('../../views/BatchAnalyzeView.vue'),
    meta: { title: '批量分析' }
  },
  {
    path: '/traditional-mode',
    name: 'traditional-mode',
    component: () => import('../../views/TraditionalModeView.vue'),
    meta: { title: '表格模式' }
  }
]
