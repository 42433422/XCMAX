import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { installAuthGuards } from './guards'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'home', redirect: { name: 'workbench-home' }, meta: { auth: true } },
  {
    path: '/about',
    name: 'about',
    component: () => import('../views/public/HomeView.vue'),
    meta: {
      layout: 'public',
      pageTitle: 'XC AGI 市场 | 智能员工与 AI 工作台',
      pageDescription:
        '修茈科技 AI 市场：组合 Mod 与 AI 员工，处理单据、流程与报表；支持注册试用与进入工作台。',
    },
  },
  {
    path: '/ai-store',
    name: 'ai-store',
    component: () => import('../views/AiStoreView.vue'),
    meta: {
      pageTitle: 'AI 市场',
      pageDescription: '浏览与选购 AI 员工、模板与能力包。',
    },
  },
  { path: '/login', name: 'login', component: () => import('../views/public/LoginView.vue'), meta: { layout: 'public' } },
  { path: '/login-email', name: 'login-email', component: () => import('../views/public/LoginByEmailView.vue'), meta: { layout: 'public' } },
  { path: '/forgot-password', name: 'forgot-password', component: () => import('../views/public/ForgotPasswordView.vue'), meta: { layout: 'public' } },
  { path: '/register', name: 'register', component: () => import('../views/public/RegisterView.vue'), meta: { layout: 'public' } },
  { path: '/legacy-login', redirect: { name: 'login' } },
  { path: '/legacy-login-email', redirect: { name: 'login-email' } },
  { path: '/legacy-forgot-password', redirect: { name: 'forgot-password' } },
  { path: '/legacy-register', redirect: { name: 'register' } },
  { path: '/catalog/:id', name: 'catalog-detail', component: () => import('../views/CatalogDetailView.vue') },
  { path: '/templates', name: 'templates', component: () => import('../views/templates/TemplatesView.vue') },
  {
    path: '/templates/:id',
    name: 'template-detail',
    component: () => import('../views/templates/TemplateDetailView.vue'),
  },
  {
    path: '/wallet',
    component: () => import('../views/WalletLayoutView.vue'),
    meta: { auth: true },
    children: [
      { path: '', name: 'wallet', component: () => import('../views/WalletView.vue') },
      { path: 'purchased', name: 'wallet-purchased', component: () => import('../views/MyStoreView.vue') },
    ],
  },
  { path: '/wallet/keys', redirect: { name: 'account', hash: '#api-keys' } },
  { path: '/my-store', redirect: { name: 'wallet-purchased' } },
  { path: '/notifications', name: 'notifications', component: () => import('../views/NotificationCenter.vue'), meta: { auth: true } },
  { path: '/analytics', name: 'analytics', component: () => import('../views/AnalyticsView.vue'), meta: { auth: true } },
  { path: '/customer-service', name: 'customer-service', component: () => import('../views/CustomerServiceView.vue'), meta: { auth: true } },
  { path: '/refunds', name: 'refunds', component: () => import('../views/RefundApplyView.vue'), meta: { auth: true } },
  { path: '/recharge', name: 'recharge', component: () => import('../views/WalletRechargeView.vue'), meta: { auth: true } },
  {
    path: '/plans',
    name: 'plans',
    component: () => import('../views/public/PaymentPlansView.vue'),
    meta: {
      layout: 'public',
      pageTitle: '会员方案',
      pageDescription: '查看与购买 XC AGI 会员套餐。',
    },
  },
  {
    path: '/download',
    name: 'download',
    component: () => import('../views/SoftwareDownloadView.vue'),
    meta: {
      layout: 'public',
      pageTitle: '下载 XCAGI 客户端',
      pageDescription:
        '下载 XCAGI 个人版与企业版客户端：Windows、macOS 与 Android APK（官网分发，应用商店审核中）。',
    },
  },
  { path: '/workflow', name: 'workflow', component: () => import('../views/WorkflowView.vue'), meta: { auth: true } },
  {
    path: '/workflow/v2/:id',
    name: 'workflow-v2-editor',
    redirect: (to: any) => ({
      name: 'workbench-shell',
      params: { target: 'workflow', id: to.params.id },
    }),
    meta: { auth: true },
  },
  // ===== 脚本即工作流（替代节点图）— 旧路径重定向到 /workbench 下 =====
  {
    path: '/script-workflows',
    redirect: { name: 'workbench-script-workflows' },
  },
  {
    path: '/script-workflows/new',
    redirect: { name: 'workbench-script-workflow-new' },
  },
  {
    path: '/script-workflows/:id',
    redirect: (to: any) => ({ name: 'workbench-script-workflow-detail', params: { id: to.params.id } }),
  },
  {
    path: '/script-workflows/:id/edit',
    redirect: (to: any) => ({ name: 'workbench-script-workflow-edit', params: { id: to.params.id } }),
  },
  {
    path: '/workbench',
    component: () => import('../views/WorkbenchView.vue'),
    meta: { auth: true },
    children: [
      // Default /workbench → 原主界面（三档对话）
      { path: '', redirect: { name: 'workbench-home' } },
      // /workbench/home → 原主界面（三档对话）
      {
        path: 'home',
        name: 'workbench-home',
        component: () => import('../views/WorkbenchHomeView.vue'),
      },
      // /workbench/unified → 原统一工作台；员工制作子页再进入新 Shell
      {
        path: 'unified',
        name: 'workbench-unified',
        component: () => import('../views/UnifiedWorkbenchView.vue'),
      },
      // Legacy sub-paths → 原统一工作台不同 focus
      {
        path: 'repository',
        name: 'workbench-repository',
        redirect: (to: any) => ({ name: 'workbench-unified', query: { ...to.query, focus: 'repository' } }),
      },
      {
        path: 'workflow',
        name: 'workbench-workflow',
        redirect: (to: any) => ({ name: 'workbench-unified', query: { ...to.query, focus: 'skill' } }),
      },
      {
        path: 'employee',
        name: 'workbench-employee',
        redirect: (to: any) => ({
          name: 'workbench-unified',
          query: { ...to.query, focus: 'employee' },
        }),
      },
      {
        path: 'integrations',
        name: 'workbench-integrations',
        redirect: (to: any) => ({ name: 'workbench-unified', query: { ...to.query, focus: 'integrations' } }),
      },
      // Mod authoring still uses its own view for now
      { path: 'mod/:modId', name: 'mod-authoring', component: () => import('../views/ModAuthoringView.vue') },
      {
        path: 'employees',
        name: 'workbench-employees',
        component: () => import('../views/MyEmployeesView.vue'),
      },
      {
        path: 'my-employees',
        name: 'workbench-my-employees',
        redirect: { name: 'workbench-employees' },
      },
      {
        path: 'materials',
        name: 'workbench-materials',
        component: () => import('../views/MyMaterialsView.vue'),
      },
      {
        path: 'download',
        name: 'workbench-download',
        component: () => import('../views/SoftwareDownloadView.vue'),
      },
      {
        path: 'change-requests',
        name: 'workbench-change-requests',
        component: () => import('../views/WorkbenchChangeRequestsView.vue'),
        meta: { pageTitle: '变更工单' },
      },
      {
        path: 'my-materials',
        name: 'workbench-my-materials',
        redirect: { name: 'workbench-materials' },
      },
      {
        path: 'script-workflows',
        name: 'workbench-script-workflows',
        component: () => import('../views/ScriptWorkflowListView.vue'),
      },
      {
        path: 'script-workflows/new',
        name: 'workbench-script-workflow-new',
        component: () => import('../views/ScriptWorkflowComposerView.vue'),
      },
      {
        path: 'script-workflows/:id',
        name: 'workbench-script-workflow-detail',
        component: () => import('../views/ScriptWorkflowDetailView.vue'),
      },
      {
        path: 'script-workflows/:id/edit',
        name: 'workbench-script-workflow-edit',
        component: () => import('../views/ScriptWorkflowComposerView.vue'),
      },
    ],
  },
  // ===== AI-Native WorkbenchShell (三栏 shell) =====
  {
    path: '/workbench/shell/:target?/:id?',
    name: 'workbench-shell',
    component: () => import('../views/workbench/WorkbenchShell.vue'),
    meta: { auth: true },
  },
  { path: '/repository', redirect: '/workbench/repository' },
  {
    path: '/repository/mod/:modId',
    redirect: (to: any) => ({ name: 'mod-authoring', params: { modId: to.params.modId } }),
  },
  { path: '/admin', redirect: '/admin/database', meta: { auth: true, admin: true } },
  { path: '/admin/database', name: 'admin-database', component: () => import('../views/AdminDatabaseView.vue'), meta: { auth: true, admin: true } },
  {
    path: '/admin/duty-employees',
    name: 'admin-duty-employees',
    component: () => import('../views/AdminDutyEmployeesView.vue'),
    meta: { auth: true, admin: true },
  },
  {
    path: '/admin/ops-audit',
    name: 'admin-ops-audit',
    component: () => import('../views/AdminOpsAuditView.vue'),
    meta: { auth: true, admin: true },
  },
  {
    path: '/admin/employee-autonomy',
    name: 'admin-employee-autonomy',
    component: () => import('../views/AdminEmployeeAutonomyView.vue'),
    meta: { auth: true, admin: true },
  },
  {
    path: '/admin/change-requests',
    name: 'admin-change-requests',
    component: () => import('../views/AdminEmployeeChangeRequestsView.vue'),
    meta: { auth: true, admin: true },
  },
  {
    path: '/admin/yuangon-onboard',
    name: 'admin-yuangon-onboard',
    component: () => import('../views/AdminYuangonOnboardView.vue'),
    meta: { auth: true, admin: true },
  },
  {
    path: '/admin/orchestrate-jobs',
    name: 'admin-orchestrate-jobs',
    component: () => import('../views/AdminOrchestrateJobsView.vue'),
    meta: { auth: true, admin: true },
  },
  { path: '/admin/customer-service', name: 'admin-customer-service', component: () => import('../views/AdminCustomerServiceView.vue'), meta: { auth: true, admin: true } },
  { path: '/admin/butler-skills', name: 'admin-butler-skills', component: () => import('../components/floating-agent/AdminAgentSkillMarket.vue'), meta: { auth: true, admin: true } },
  {
    path: '/admin/ai-accounts',
    name: 'admin-ai-accounts',
    component: () => import('../views/AdminAiAccountsView.vue'),
    meta: { auth: true, admin: true },
  },
  {
    path: '/admin/ops-terminal',
    name: 'admin-ops-terminal',
    component: () => import('../views/AdminOpsTerminalView.vue'),
    meta: { auth: true, admin: true },
  },
  { path: '/checkout/:orderId', name: 'checkout', component: () => import('../views/PaymentCheckoutView.vue'), meta: { auth: true } },
  { path: '/order/:orderId', name: 'order-detail', component: () => import('../views/OrderDetailView.vue'), meta: { auth: true } },
  { path: '/orders', name: 'orders', component: () => import('../views/OrderListView.vue'), meta: { auth: true } },
  { path: '/account', name: 'account', component: () => import('../views/AccountSettingsView.vue'), meta: { auth: true } },
  { path: '/knowledge', name: 'knowledge', component: () => import('../views/KnowledgeManagerView.vue'), meta: { auth: true } },
  {
    path: '/ai-test',
    name: 'ai-test',
    component: () => import('../views/AiTestLayout.vue'),
    meta: { auth: true },
    children: [
      { path: '', redirect: { name: 'ai-test-sandbox' } },
      {
        path: 'sandbox',
        name: 'ai-test-sandbox',
        component: () => import('../views/SandboxView.vue'),
        meta: { auth: true },
      },
      {
        path: 'exam',
        name: 'ai-test-exam',
        component: () => import('../views/EmployeeExamView.vue'),
        meta: { auth: true },
      },
    ],
  },
  { path: '/sandbox', name: 'sandbox', redirect: { name: 'ai-test-sandbox' } },
  {
    path: '/dev',
    name: 'developer-portal',
    component: () => import('../views/developer/DeveloperPortalView.vue'),
    meta: { auth: true },
  },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('../views/NotFoundView.vue') },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash, behavior: 'smooth' }
    return { top: 0 }
  },
})

installAuthGuards(router)

router.afterEach((to) => {
  const meta = to.meta || {}
  const rawTitle = (meta.pageTitle as string) || (meta.title as string) || ''
  if (rawTitle) {
    document.title = rawTitle.includes('XC AGI') || rawTitle.includes('修茈')
      ? rawTitle
      : `${rawTitle} | XC AGI`
  }
  const desc = meta.pageDescription as string | undefined
  if (desc) {
    let el = document.querySelector('meta[name="description"]')
    if (!el) {
      el = document.createElement('meta')
      el.setAttribute('name', 'description')
      document.head.appendChild(el)
    }
    el.setAttribute('content', desc)
  }
})

/** 部署后 index 与 assets 哈希不一致时，懒加载 chunk 404 会导致 router.push 静默失败。 */
function isChunkLoadError(err: unknown): boolean {
  const msg = String((err as Error)?.message || err || '')
  return (
    msg.includes('Failed to fetch dynamically imported module') ||
    msg.includes('Importing a module script failed') ||
    msg.includes('Loading chunk') ||
    msg.includes('Loading CSS chunk')
  )
}

function appLocationHref(to: { fullPath?: string; path?: string; name?: string | symbol | null }): string {
  try {
    return router.resolve({
      path: to.fullPath || to.path || '/',
      name: to.name as string | undefined,
    }).href
  } catch {
    const base = import.meta.env.BASE_URL || '/'
    const p = to.fullPath || to.path || '/'
    const normalized = p.startsWith('/') ? p : `/${p}`
    return `${base.replace(/\/$/, '')}${normalized}`
  }
}

router.onError((err, to) => {
  if (!isChunkLoadError(err)) return
  const href = appLocationHref(to)
  const key = `vite-chunk-reload:${href}`
  try {
    if (!sessionStorage.getItem(key)) {
      sessionStorage.setItem(key, '1')
      window.location.assign(href)
      return
    }
    sessionStorage.removeItem(key)
  } catch {
    window.location.assign(href)
  }
})

export default router
