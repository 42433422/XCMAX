import type { RouteRecordRaw } from 'vue-router'
import XCmaxAdminView from './views/XCmaxAdminView.vue'
import AutomationPolicyView from './views/AutomationPolicyView.vue'
import DutyTimeArchitectureView from './views/DutyTimeArchitectureView.vue'
import DutyRosterGraphView from './views/DutyRosterGraphView.vue'
import ServerFunctionsView from './views/ServerFunctionsView.vue'

/** 管理端运维五页（同步 import，避免懒加载期间仍渲染对话页） */
export const ADMIN_HOST_ROUTE_RECORDS: RouteRecordRaw[] = [
  {
    path: '/xcmax-admin',
    name: 'xcmax-admin',
    component: XCmaxAdminView,
    meta: { title: '服务器后台总览', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/automation-policy',
    name: 'automation-policy',
    component: AutomationPolicyView,
    meta: { title: '自动化方针', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/duty-time-architecture',
    name: 'duty-time-architecture',
    component: DutyTimeArchitectureView,
    meta: { title: '同时完成时间架构', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/duty-roster-graph',
    name: 'duty-roster-graph',
    component: DutyRosterGraphView,
    meta: { title: '员工可视化', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/server-functions',
    name: 'server-functions',
    component: ServerFunctionsView,
    meta: { title: '服务器功能模块', requiresAdminAccount: true, hostAdmin: true },
  },
]
