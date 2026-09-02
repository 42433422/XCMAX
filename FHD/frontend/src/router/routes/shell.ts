import type { RouteRecordRaw } from 'vue-router'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'

/** 设置 / 工具 / 员工空间 / Mod 落地等壳层路由 */
export const SHELL_ROUTES: RouteRecordRaw[] = [
  {
    path: '/onboarding',
    name: 'product-onboarding',
    component: () => import('../../views/ProductOnboardingView.vue'),
    meta: { title: '首次设置', hideChrome: true, publicAccess: true },
  },
  {
    path: '/discover',
    name: 'discover',
    component: () => import('../../views/DiscoverView.vue'),
    meta: { title: '发现' },
  },
  {
    path: '/mod-store',
    name: 'mod-store',
    component: () => import('../../views/ModStore.vue'),
    meta: { title: '能力库' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('../../views/SettingsView.vue'),
    meta: { title: '设置' },
  },
  {
    path: '/im',
    name: 'im',
    component: () => import('../../views/ImMessengerView.vue'),
    meta: { title: '信息' },
  },
  {
    path: isAdminConsoleSpa() ? '/entitlements' : '/admin/entitlements',
    name: 'admin-entitlements',
    component: () => import('../../views/AdminEntitlementsView.vue'),
    meta: { title: '用户管理', requiresAdminAccount: true },
  },
  {
    path: '/desktop-runtime',
    name: 'desktop-runtime',
    component: () => import('../../views/DesktopRuntimeView.vue'),
    meta: { title: '桌面运行时' },
  },
  {
    path: '/chat-debug',
    name: 'chat-debug',
    component: () => import('../../views/ChatDebugView.vue'),
    meta: { title: '对话调试' },
  },
  {
    path: '/tools',
    name: 'tools',
    component: () => import('../../views/ToolsView.vue'),
    meta: { title: '工具' },
  },
  {
    path: '/other-tools',
    name: 'other-tools',
    redirect: { name: 'workflow-employee-space' },
  },
  ...(import.meta.env.VITE_XCAGI_EDITION !== 'minimal'
    ? [
        {
          path: '/workflow-visualization',
          name: 'workflow-visualization',
          component: () => import('../../views/WorkflowVisualizationView.vue'),
          meta: { title: '流程可视化' },
        } as RouteRecordRaw,
      ]
    : []),
  {
    path: '/workflow-employee-space',
    name: 'workflow-employee-space',
    component: () => import('../../views/EmployeeWorkspaceView.vue'),
    meta: { title: '员工空间' },
  },
  ...(isAdminConsoleSpa()
    ? [
        {
          path: '/workflow-employee-space/stitch-full',
          name: 'workflow-employee-stitch-full',
          redirect: { name: 'duty-roster-graph' },
          meta: { title: '管理端六部门可视化' },
        } as RouteRecordRaw,
      ]
    : [
        {
          path: '/workflow-employee-space/stitch-full',
          name: 'workflow-employee-stitch-full',
          component: () => import('../../views/YuangongStitchFullView.vue'),
          meta: { title: '企业员工工作流全景' },
        } as RouteRecordRaw,
      ]),
  {
    path: '/employee-workspace',
    redirect: { name: 'workflow-employee-space' },
  },
  {
    path: '/yuangong-stitch',
    redirect: { name: 'workflow-employee-stitch-full' },
  },
  {
    path: '/mod/:modId',
    name: 'mod-landing',
    component: () => import('../../views/ModLandingView.vue'),
    meta: { title: 'Mod 详情', mod: true },
  },
]
