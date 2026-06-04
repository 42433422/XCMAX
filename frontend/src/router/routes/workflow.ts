import type { RouteRecordRaw } from 'vue-router'

export const workflowRoutes: RouteRecordRaw[] = [
  {
    path: '/workflow-visualization',
    name: 'workflow-visualization',
    component: () => import('../../views/WorkflowVisualizationView.vue'),
    meta: { title: '流程可视化' }
  },
  {
    path: '/workflow-employee-space',
    name: 'workflow-employee-space',
    component: () => import('../../views/EmployeeWorkspaceView.vue'),
    meta: { title: '员工空间' }
  },
  {
    path: '/workflow-employee-space/stitch-full',
    name: 'workflow-employee-stitch-full',
    component: () => import('../../views/YuangongStitchFullView.vue'),
    meta: { title: '员工工作流全景' }
  },
  {
    path: '/employee-workspace',
    redirect: { name: 'workflow-employee-space' }
  },
  {
    path: '/yuangong-stitch',
    redirect: { name: 'workflow-employee-stitch-full' }
  }
]
