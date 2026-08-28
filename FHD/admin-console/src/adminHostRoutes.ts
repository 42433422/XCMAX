import type { RouteRecordRaw } from 'vue-router'

/** 管理端运维宿主页。路由守卫先完成重定向，页面组件按需加载以缩小首屏入口包。 */
export const ADMIN_HOST_ROUTE_RECORDS: RouteRecordRaw[] = [
  {
    path: '/xcmax-admin',
    name: 'xcmax-admin',
    component: () => import('./views/XCmaxAdminView.vue'),
    meta: { title: '服务器后台总览', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/delivery-center',
    name: 'delivery-center',
    component: () => import('./views/DeliveryCenterView.vue'),
    meta: { title: '客户交付中心', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/founder-autonomy',
    name: 'founder-autonomy',
    component: () => import('./views/FounderAutonomyView.vue'),
    meta: { title: '创始人自治驾驶舱', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/automation-policy',
    name: 'automation-policy',
    component: () => import('./views/AutomationPolicyView.vue'),
    meta: { title: '自动化方针', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/duty-time-architecture',
    name: 'duty-time-architecture',
    component: () => import('./views/DutyTimeArchitectureView.vue'),
    meta: { title: '同时完成时间架构', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/duty-roster-graph',
    name: 'duty-roster-graph',
    component: () => import('./views/DutyRosterGraphView.vue'),
    meta: { title: '员工可视化', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/server-functions',
    name: 'server-functions',
    component: () => import('./views/ServerFunctionsView.vue'),
    meta: { title: '服务器功能模块', requiresAdminAccount: true, hostAdmin: true },
  },
  // 菜单 key 仍为 approval-hub；path 避开企业端 ERP /approval-hub 冲突
  {
    path: '/autonomy-approval-hub',
    name: 'autonomy-approval-hub',
    component: () => import('./views/ApprovalHubView.vue'),
    meta: { title: '自治审批中心', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/employee-autonomy',
    name: 'employee-autonomy',
    component: () => import('./views/EmployeeAutonomyView.vue'),
    meta: { title: '员工自治', requiresAdminAccount: true, hostAdmin: true },
  },
]
