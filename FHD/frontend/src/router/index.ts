import { createRouter, createWebHistory, START_LOCATION, type NavigationGuardNext, type RouteLocationNormalized, type RouteRecordRaw } from 'vue-router';
import { useLanGate } from '@/composables/useLanGate';
import {
  isPlatformShellModeEnabled,
  isShellEditionBuild,
  isIndustryDeliveryRouteName,
  INDUSTRY_DELIVERY_ROUTE_NAMES,
  SHELL_CORE_ROUTE_NAMES,
} from '@/constants/platformShellMode';
import { shouldRouteToProductOnboarding } from '@/composables/useProductFlow';
import { readHostPackAcknowledged } from '@/constants/productFlow';
import {
  resolveHostPackOnboardingStep,
  shouldRouteToHostPackOnboarding,
} from '@/utils/hostPackOnboardingGate';
import { resolveHostBusinessPageRedirect } from '@/utils/hostBusinessPageRedirect';
import { customerServiceHostPathFromModPath } from '@/utils/customerServicePagePaths';
import { readErpDomainModFacadeEnabled } from '@/constants/erpDomainMod';
import { readCoreWorkflowModPagesEnabled } from '@/constants/coreWorkflowMod';
import { resolveWorkflowPageRedirectForRouteName } from '@/utils/workflowPagePaths';
import { resolvePlannerChatHomePath, resolvePlannerPagePath } from '@/utils/plannerPagePaths';
import { readActiveExtensionModId } from '@/utils/erpDomainPaths';
import { isProtectedClientModId } from '@/constants/protectedMods';
import { fetchProductSku, isEnterpriseEdition } from '@/utils/productSku';
import { validateEnterpriseSessionCached } from '@/utils/authSessionCache';
import { useModsStore } from '@/stores/mods';
import {
  isAdminConsoleSpa,
  resolveAdminConsoleHomeUrl,
} from '@/utils/adminConsoleUrl';
import { ADMIN_HOST_ROUTE_RECORDS } from '@admin-console-inject/adminHostRoutes';
import {
  ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES,
  ADMIN_OPERATOR_HOME_ROUTE,
} from '@/constants/adminOperatorNav';
import { buildRoleMenuProfile, canShowCoreMenuKey } from '@/utils/roleMenuProfile';
import { isClientErpSidebarContext } from '@/constants/genericModPack';
const isSandbox = new URLSearchParams(window.location.search).has('sandbox');

const SANDBOX_ALLOWED = new Set([
  'login',
  'login-help',
  'login-register',
  'login-forgot-account',
  'login-forgot-password',
  'chat',
  'workflow-employee-space',
  'workflow-employee-stitch-full',
  'mod-landing',
  'chat-debug',
  'tools',
]);

const DEFAULT_DUTY_ROSTER_GRAPH_VIEW = 'department';

function normalizeDutyRosterGraphView(raw: unknown): string {
  const token = String(Array.isArray(raw) ? raw[0] : raw || '').trim().toLowerCase();
  if (token === 'department' || token === 'dept' || token === '六部门') return 'department';
  if (token === 'hub' || token === 'center' || token === '中心' || token === '中心图') return 'hub';
  if (token === 'legacy-area' || token === 'area' || token === '物理' || token === '物理分区') return 'legacy-area';
  if (token === 'client' || token === 'workshop' || token === '车间' || token === '客户端车间') return 'client';
  return DEFAULT_DUTY_ROSTER_GRAPH_VIEW;
}

const allRoutes: RouteRecordRaw[] = [
  {
    path: '/index.html',
    redirect: (to) => ({ path: '/', query: to.query, hash: to.hash }),
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { title: '登录', publicAccess: true, hideChrome: true }
  },
  {
    path: '/login/help',
    name: 'login-help',
    component: () => import('../views/LoginHelpView.vue'),
    meta: { title: '登录帮助', publicAccess: true, hideChrome: true }
  },
  {
    path: '/login/register',
    name: 'login-register',
    component: () => import('../views/RegisterView.vue'),
    meta: { title: '注册', publicAccess: true, hideChrome: true }
  },
  {
    path: '/login/forgot-account',
    name: 'login-forgot-account',
    component: () => import('../views/ForgotAccountView.vue'),
    meta: { title: '忘记账号', publicAccess: true, hideChrome: true }
  },
  {
    path: '/login/forgot-password',
    name: 'login-forgot-password',
    component: () => import('../views/ForgotPasswordView.vue'),
    meta: { title: '忘记密码', publicAccess: true, hideChrome: true }
  },
  {
    path: '/',
    name: 'chat',
    component: () => import('../views/ChatView.vue'),
    meta: { title: '智能对话' }
  },
  {
    path: '/lan-gate',
    name: 'lan-gate',
    component: () => import('../views/LanGateView.vue'),
    meta: { title: '局域网授权', publicAccess: true, hideChrome: true }
  },
];

/** minimal 构建：Vite 静态剔除下列宿主 ERP/审批等业务路由（勿改为动态 import 独立 chunk） */
if (import.meta.env.VITE_XCAGI_EDITION !== 'minimal') {
  allRoutes.push(
    {
      path: '/ai-ecosystem',
      name: 'ai-ecosystem',
      component: () => import('../views/AIEcosystemView.vue'),
      meta: { title: '智能生态' },
    },
    {
      path: '/brain',
      name: 'brain',
      component: () => import('../views/BrainView.vue'),
      meta: { title: '智脑集成' },
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
      component: () => import('../views/KittenFinanceView.vue'),
      meta: { title: '财务分析' },
    },
    {
      path: '/products',
      name: 'products',
      component: () => import('../views/ProductsView.vue'),
      meta: { title: '业务对象' },
    },
    {
      path: '/materials',
      name: 'materials',
      component: () => import('../views/MaterialsView.vue'),
      meta: { title: '资源库' },
    },
    {
      path: '/materials-list',
      redirect: { name: 'materials' },
    },
    {
      path: '/orders',
      name: 'orders',
      component: () => import('../views/OrdersView.vue'),
      meta: { title: '业务单据' },
    },
    {
      path: '/traditional-mode',
      name: 'traditional-mode',
      component: () => import('../views/TraditionalModeView.vue'),
      meta: { title: '表格模式' },
    },
    {
      path: '/business-docking',
      redirect: { name: 'template-preview' },
    },
    {
      path: '/orders/create',
      name: 'orders-create',
      component: () => import('../views/CreateOrderView.vue'),
      meta: { title: '新建业务单据' },
    },
    {
      path: '/shipment-records',
      name: 'shipment-records',
      component: () => import('../views/ShipmentRecordsView.vue'),
      meta: { title: '业务记录' },
    },
    {
      path: '/customers',
      name: 'customers',
      component: () => import('../views/CustomersView.vue'),
      meta: { title: '组织管理' },
    },
    {
      path: '/data-sources',
      name: 'data-sources',
      component: () => import('../views/DataSourcesView.vue'),
      meta: { title: '数据来源' },
    },
    {
      path: '/wechat-contacts',
      name: 'wechat-contacts',
      redirect: { name: 'data-sources', query: { source: 'wechat_local_db' } },
      meta: { title: '企业微信联系人' },
    },
    {
      path: '/print',
      name: 'print',
      component: () => import('../views/PrintView.vue'),
      meta: { title: '模板与打印' },
    },
    {
      path: '/printer-list',
      name: 'printer-list',
      component: () => import('../views/PrinterListView.vue'),
      meta: { title: '打印机列表' },
    },
    {
      path: '/template-preview',
      name: 'template-preview',
      component: () => import('../views/TemplatePreviewView.vue'),
      meta: { title: '模板预览' },
    },
    {
      path: '/label-editor',
      name: 'label-editor',
      component: () => import('../views/LabelEditorView.vue'),
      meta: { title: '标签编辑器' },
    },
    {
      path: '/console',
      name: 'console',
      component: () => import('../views/TemplatePreviewView.vue'),
      meta: { title: '模板预览' },
      beforeEnter: (to: RouteLocationNormalized, _from: RouteLocationNormalized, next: NavigationGuardNext) => {
        const view = to.query.view;
        if (view === 'excel' || view === 'template-preview') {
          next();
        } else if (view) {
          next();
        } else {
          next();
        }
      },
    },
    {
      path: '/purchase',
      name: 'purchase',
      component: () => import('../views/PurchaseView.vue'),
      meta: { title: '耗材申领' },
    },
    {
      path: '/batch-analyze',
      name: 'batch-analyze',
      component: () => import('../views/BatchAnalyzeView.vue'),
      meta: { title: '批量分析' },
    },
    {
      path: '/enterprise-customer-service',
      name: 'enterprise-customer-service',
      component: () => import('../views/EnterpriseCustomerServiceView.vue'),
      meta: { title: '外部客服', customerServiceSide: 'enterprise' },
    },
    {
      path: '/internal-customer-service',
      name: 'internal-customer-service',
      component: () => import('../views/InternalCustomerServiceView.vue'),
      meta: { title: '内部客服', customerServiceSide: 'admin', requiresAdminAccount: true },
    },
    {
      path: '/approval-hub',
      name: 'approval-hub',
      component: () => import('../views/ApprovalHubView.vue'),
      meta: { title: '审批中心' },
      redirect: { name: 'approval-workspace' },
      children: [
        {
          path: 'workspace',
          name: 'approval-workspace',
          component: () => import('../views/ApprovalWorkspaceView.vue'),
          meta: { title: '审批工作台' },
        },
        {
          path: 'flow-management',
          name: 'approval-flow-management',
          component: () => import('../views/ApprovalFlowManagementView.vue'),
          meta: { title: '审批流程管理' },
        },
        {
          path: 'rules',
          name: 'approval-rules',
          component: () => import('../views/ApprovalRulesView.vue'),
          meta: { title: '审批规则配置' },
        },
      ],
    },
    {
      path: '/inventory',
      name: 'inventory',
      component: () => import('../views/InventoryView.vue'),
      meta: { title: '库存管理' },
    },
  );
}

allRoutes.push(
  {
    path: '/onboarding',
    name: 'product-onboarding',
    component: () => import('../views/ProductOnboardingView.vue'),
    meta: { title: '首次设置', hideChrome: true, publicAccess: true },
  },
  {
    path: '/discover',
    name: 'discover',
    component: () => import('../views/DiscoverView.vue'),
    meta: { title: '发现' },
  },
  {
    path: '/mod-store',
    name: 'mod-store',
    component: () => import('../views/ModStore.vue'),
    meta: { title: '能力库' }
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('../views/SettingsView.vue'),
    meta: { title: '设置' }
  },
  {
    path: '/im',
    name: 'im',
    component: () => import('../views/ImMessengerView.vue'),
    meta: { title: '信息' }
  },
  {
    path: '/ai-groups',
    name: 'ai-groups',
    component: () => import('../views/AiGroupChatView.vue'),
    meta: { title: 'AI群聊' }
  },
  {
    path: '/admin/entitlements',
    name: 'admin-entitlements',
    component: () => import('../views/AdminEntitlementsView.vue'),
    meta: { title: '用户管理', requiresAdminAccount: true },
  },
  {
    path: '/desktop-runtime',
    name: 'desktop-runtime',
    component: () => import('../views/DesktopRuntimeView.vue'),
    meta: { title: '桌面运行时' }
  },
  {
    path: '/chat-debug',
    name: 'chat-debug',
    component: () => import('../views/ChatDebugView.vue'),
    meta: { title: '对话调试' }
  },
  {
    path: '/tools',
    name: 'tools',
    component: () => import('../views/ToolsView.vue'),
    meta: { title: '工具' }
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
          component: () => import('../views/WorkflowVisualizationView.vue'),
          meta: { title: '流程可视化' },
        } as RouteRecordRaw,
      ]
    : []),
  {
    path: '/workflow-employee-space',
    name: 'workflow-employee-space',
    component: () => import('../views/EmployeeWorkspaceView.vue'),
    meta: { title: '员工空间' }
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
          component: () => import('../views/YuangongStitchFullView.vue'),
          meta: { title: '企业员工工作流全景' },
        } as RouteRecordRaw,
      ]),
  {
    path: '/employee-workspace',
    redirect: { name: 'workflow-employee-space' }
  },
  {
    path: '/yuangong-stitch',
    redirect: { name: 'workflow-employee-stitch-full' }
  },
  {
    path: '/mod/:modId',
    name: 'mod-landing',
    component: () => import('../views/ModLandingView.vue'),
    meta: { title: 'Mod 详情', mod: true }
  },
);

if (import.meta.env.VITE_XCMAX_ADMIN_CONSOLE === '1') {
  allRoutes.push(...ADMIN_HOST_ROUTE_RECORDS);
}

function filterSandboxRoutes(routes: RouteRecordRaw[]): RouteRecordRaw[] {
  return routes.filter((r) => {
    if (!r.name) return false;
    if (SANDBOX_ALLOWED.has(r.name as string)) return true;
    if (r.path === '/employee-workspace' || r.path === '/yuangong-stitch') return true;
    return false;
  });
}

function filterPlatformShellRoutes(routes: RouteRecordRaw[]): RouteRecordRaw[] {
  return routes.filter((r) => {
    if (!r.name) return false;
    if (SHELL_CORE_ROUTE_NAMES.has(r.name as string)) return true;
    if (INDUSTRY_DELIVERY_ROUTE_NAMES.has(r.name as string)) return true;
    if (r.meta?.mod === true) return true;
    if (r.meta?.hostAdmin === true) return true;
    if (r.path === '/employee-workspace' || r.path === '/yuangong-stitch') return true;
    if (r.path?.startsWith('/mod/')) return true;
    return false;
  });
}

function resolveInitialRoutes(): RouteRecordRaw[] {
  if (isAdminConsoleSpa()) return allRoutes;
  if (isSandbox) return filterSandboxRoutes(allRoutes);
  if (isPlatformShellModeEnabled()) return filterPlatformShellRoutes(allRoutes);
  return allRoutes;
}

const routes = resolveInitialRoutes();

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
});

router.beforeEach(async (to, _from, next) => {
  if (to.name === 'duty-roster-graph') {
    const nextView = normalizeDutyRosterGraphView(to.query.view);
    const currentView = String(Array.isArray(to.query.view) ? to.query.view[0] : to.query.view || '').trim().toLowerCase();
    const normalizedView = String(nextView);
    if (currentView !== normalizedView) {
      next({
        name: 'duty-roster-graph',
        query: { ...to.query, view: normalizedView },
        hash: to.hash,
        replace: true,
      });
      return;
    }
  }

  if (
    isAdminConsoleSpa() &&
    to.path.startsWith('/mod/xcagi-planner-bridge/')
  ) {
    const hostPath = to.path.slice('/mod/xcagi-planner-bridge'.length) || '/'
    next({ path: hostPath, query: to.query, hash: to.hash, replace: true })
    return
  }

  if (
    isAdminConsoleSpa() &&
    to.name &&
    ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES.has(String(to.name))
  ) {
    next({ name: ADMIN_OPERATOR_HOME_ROUTE, replace: true });
    return;
  }

  if (
    !isAdminConsoleSpa() &&
    (to.name === 'workflow-visualization' || to.name === 'mod-workflow-visualization')
  ) {
    try {
      const { useAccountProfileStore } = await import('@/stores/accountProfile');
      const profileStore = useAccountProfileStore();
      if (!profileStore.loaded) await profileStore.refreshFromServer();
      const modsStore = useModsStore();
      const menuProfile = buildRoleMenuProfile(
        {
          accountKind: profileStore.accountKind,
          marketIsAdmin: profileStore.marketIsAdmin,
          marketIsEnterprise: profileStore.marketIsEnterprise,
          isAdminAccount: profileStore.isAdminAccount,
        },
        isClientErpSidebarContext(
          (modsStore.mods || []).map((m) => String(m.id || '').trim()),
          modsStore.activeModId,
        ),
      );
      if (!canShowCoreMenuKey(menuProfile, 'workflow-visualization')) {
        next({ name: 'workflow-employee-space', replace: true });
        return;
      }
    } catch {
      next({ name: 'workflow-employee-space', replace: true });
      return;
    }
  }

  // 管理端冷启动落在 `/` 时默认进运维总览；侧栏点「智能对话」时 _from 非 START_LOCATION，须放行
  if (
    isAdminConsoleSpa() &&
    to.name === 'chat' &&
    to.path === '/' &&
    _from === START_LOCATION
  ) {
    try {
      const { useAccountProfileStore } = await import('@/stores/accountProfile');
      const profile = useAccountProfileStore();
      if (!profile.loaded) await profile.refreshFromServer();
      if (profile.isAdminAccount) {
        next({ name: ADMIN_OPERATOR_HOME_ROUTE, replace: true });
        return;
      }
    } catch {
      /* ignore */
    }
  }

  if (to.matched.length === 0 && to.path.startsWith('/mod/')) {
    const csHost = customerServiceHostPathFromModPath(to.path);
    if (csHost) {
      next({ path: csHost, query: to.query, hash: to.hash, replace: true });
      return;
    }
    if (
      to.path.startsWith('/mod/xcagi-planner-bridge/') &&
      isProtectedClientModId(readActiveExtensionModId())
    ) {
      next({ path: '/', query: to.query, hash: to.hash, replace: true });
      return;
    }
    next({ path: '/', replace: true });
    return;
  }

  if (
    to.path.startsWith('/mod/xcagi-planner-bridge/') &&
    isProtectedClientModId(readActiveExtensionModId())
  ) {
    next({ path: '/', query: to.query, hash: to.hash, replace: true });
    return;
  }

  // 局域网授权守卫仅作用于主机管理员控制台（避免影响其他业务页面）
  // 独立 admin-console SPA 已由账号会话鉴权，不再弹出局域网密钥框
  const requiresLanGate =
    !isAdminConsoleSpa() && to.matched.some((r) => Boolean(r.meta?.hostAdmin));
  if (requiresLanGate && !to.meta.publicAccess) {
    try {
      const lan = useLanGate();
      const status = await lan.refresh();
      if (status?.enabled && !status.authorized) {
        lan.openLanGateModal(to.fullPath);
        next(false);
        return;
      }
    } catch {
      /* 状态接口异常时不阻断；后端 401 会兜底拦截 */
    }
  }

  try {
    const modsStore = useModsStore();
    if (modsStore.clientModsUiOff && to.matched.some((r) => Boolean(r.meta?.mod))) {
      next(resolvePlannerChatHomePath());
      return;
    }
  } catch {
    /* Pinia 未就绪时忽略 */
  }

  if (to.path === '/' || to.name === 'chat') {
    const modChat = resolvePlannerPagePath('/');
    const modChatPath = modChat.split('?')[0] || modChat;
    if (modChat !== '/' && to.path !== modChatPath) {
      if (router.resolve(modChatPath).matched.length === 0) {
        next();
        return;
      }
      next({ path: modChat, query: to.query, hash: to.hash });
      return;
    }
  }

  if (
    isPlatformShellModeEnabled() &&
    to.name &&
    !SHELL_CORE_ROUTE_NAMES.has(String(to.name)) &&
    !isIndustryDeliveryRouteName(
      String(to.name),
      useModsStore().mods.map((m) => String(m.id || '').trim()).filter(Boolean),
      readHostPackAcknowledged(),
    ) &&
    !to.meta?.mod
  ) {
    const modPage = resolveHostBusinessPageRedirect(String(to.name));
    if (modPage) {
      next(modPage);
      return;
    }
    next(resolvePlannerChatHomePath());
    return;
  }

  // 干净通用版：禁用 Mod 页 redirect，宿主 /products 等走 frontend/src/views/*
  // if (
  //   readErpDomainModFacadeEnabled() &&
  //   to.name &&
  //   !to.meta?.mod &&
  //   !to.meta?.publicAccess
  // ) {
  //   const modPage = resolveHostBusinessPageRedirect(String(to.name));
  //   if (modPage && to.path !== modPage.split('?')[0]) {
  //     next({ path: modPage, query: to.query, hash: to.hash });
  //     return;
  //   }
  // }

  // if (
  //   readCoreWorkflowModPagesEnabled() &&
  //   to.name &&
  //   !to.meta?.mod &&
  //   !to.meta?.publicAccess
  // ) {
  //   const wfPage = resolveWorkflowPageRedirectForRouteName(String(to.name));
  //   if (wfPage && to.path !== wfPage.split('?')[0]) {
  //     next({ path: wfPage, query: to.query, hash: to.hash });
  //     return;
  //   }
  // }

  const customerServiceSide = to.meta?.customerServiceSide as string | undefined;
  if (customerServiceSide === 'enterprise' || customerServiceSide === 'admin') {
    try {
      const { useAccountProfileStore } = await import('@/stores/accountProfile');
      const profile = useAccountProfileStore();
      if (!profile.loaded) {
        await profile.refreshFromServer();
      }
      if (customerServiceSide === 'admin' && !profile.isAdminAccount) {
        next({ name: 'im' });
        return;
      }
      if (customerServiceSide === 'enterprise' && profile.isAdminAccount) {
        next({ name: 'internal-customer-service' });
        return;
      }
    } catch {
      next({ name: 'chat' });
      return;
    }
  }

  if (to.meta?.requiresAdminAccount && !isAdminConsoleSpa()) {
    try {
      const { useAccountProfileStore } = await import('@/stores/accountProfile');
      const profile = useAccountProfileStore();
      if (!profile.loaded) {
        await profile.refreshFromServer();
      }
      if (!profile.isAdminAccount) {
        next({ name: 'chat' });
        return;
      }
    } catch {
      next({ name: 'chat' });
      return;
    }
  }

  if (!to.meta?.publicAccess) {
    try {
      const sku = await fetchProductSku();
      if (isEnterpriseEdition(sku)) {
        const valid = await validateEnterpriseSessionCached();
        if (!valid) {
          next({
            name: 'login',
            query: { redirect: to.fullPath !== '/login' ? to.fullPath : '/' },
          });
          return;
        }
        try {
          const { useAccountProfileStore } = await import('@/stores/accountProfile');
          const profile = useAccountProfileStore();
          if (!profile.loaded) {
            await profile.refreshFromServer();
          }
          if (!isAdminConsoleSpa() && profile.isAdminAccount && to.name !== 'login') {
            window.location.href = resolveAdminConsoleHomeUrl();
            next(false);
            return;
          }
        } catch {
          /* ignore */
        }
      }
    } catch {
      const sku = await fetchProductSku().catch(() => 'generic');
      if (!isEnterpriseEdition(sku)) {
        next();
        return;
      }
      next({
        name: 'login',
        query: { redirect: to.fullPath !== '/login' ? to.fullPath : '/' },
      });
      return;
    }
  }

  if (
    shouldRouteToProductOnboarding(to.name) &&
    !to.meta?.publicAccess &&
    !isAdminConsoleSpa()
  ) {
    // 首次引导始终从「认识宿主」开始；宿主包未齐时在步骤 2 由用户点「下一步」进入
    next({ name: 'product-onboarding', query: { step: 'welcome', redirect: to.fullPath } });
    return;
  }

  if (
    shouldRouteToHostPackOnboarding(to.name) &&
    !to.meta?.publicAccess &&
    !isAdminConsoleSpa()
  ) {
    try {
      const onboardingStep = await resolveHostPackOnboardingStep(true);
      if (onboardingStep) {
        next({
          name: 'product-onboarding',
          query: {
            step: onboardingStep,
            redirect: to.fullPath !== '/onboarding' ? to.fullPath : '/',
          },
        });
        return;
      }
    } catch {
      /* API 异常时不阻断主流程 */
    }
  }

  next();
});

router.afterEach((to) => {
  const title = to.meta?.title
  document.title = title ? `${title} - XCAGI` : 'XCAGI'
});

export default router;
