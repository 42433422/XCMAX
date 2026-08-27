import type { RouteRecordRaw } from 'vue-router'
import XCmaxAdminView from './views/XCmaxAdminView.vue'
import AutomationPolicyView from './views/AutomationPolicyView.vue'
import DutyTimeArchitectureView from './views/DutyTimeArchitectureView.vue'
import DutyRosterGraphView from './views/DutyRosterGraphView.vue'
import ServerFunctionsView from './views/ServerFunctionsView.vue'
import ApprovalHubView from './views/ApprovalHubView.vue'
import EmployeeAutonomyView from './views/EmployeeAutonomyView.vue'
import FounderAutonomyView from './views/FounderAutonomyView.vue'
import DeliveryCenterView from './views/DeliveryCenterView.vue'

/** 管理端运维宿主页（同步 import，避免懒加载期间仍渲染对话页） */
export const ADMIN_HOST_ROUTE_RECORDS: RouteRecordRaw[] = [
  {
    path: '/xcmax-admin',
    name: 'xcmax-admin',
    component: XCmaxAdminView,
    meta: { title: '服务器后台总览', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/delivery-center',
    name: 'delivery-center',
    component: DeliveryCenterView,
    meta: { title: '客户交付中心', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/founder-autonomy',
    name: 'founder-autonomy',
    component: FounderAutonomyView,
    meta: { title: '创始人自治驾驶舱', requiresAdminAccount: true, hostAdmin: true },
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
  // 菜单 key 仍为 approval-hub；path 避开企业端 ERP /approval-hub 冲突
  {
    path: '/autonomy-approval-hub',
    name: 'autonomy-approval-hub',
    component: ApprovalHubView,
    meta: { title: '自治审批中心', requiresAdminAccount: true, hostAdmin: true },
  },
  {
    path: '/employee-autonomy',
    name: 'employee-autonomy',
    component: EmployeeAutonomyView,
    meta: { title: '员工自治', requiresAdminAccount: true, hostAdmin: true },
  },
]
