import {
  createRouter,
  createWebHistory,
  START_LOCATION,
  type RouteRecordRaw,
} from 'vue-router'
import { useLanGate } from '@/composables/useLanGate'
import { isPlatformShellModeEnabled, isIndustryDeliveryRouteName, SHELL_CORE_ROUTE_NAMES } from '@/constants/platformShellMode'
import { shouldRouteToProductOnboarding } from '@/composables/useProductFlow'
import { readHostPackAcknowledged } from '@/constants/productFlow'
import { resolveHostPackOnboardingStep, shouldRouteToHostPackOnboarding } from '@/utils/hostPackOnboardingGate'
import { resolveHostBusinessPageRedirect } from '@/utils/hostBusinessPageRedirect'
import { customerServiceHostPathFromModPath } from '@/utils/customerServicePagePaths'
import { resolvePlannerChatHomePath, resolvePlannerPagePath } from '@/utils/plannerPagePaths'
import { readActiveExtensionModId } from '@/utils/erpDomainPaths'
import { isProtectedClientModId } from '@/constants/protectedMods'
import { fetchProductSku, isEnterpriseEdition } from '@/utils/productSku'
import {
  consumeDesktopSessionBootstrapHint,
  hasRecentEnterpriseSessionHint,
  validateEnterpriseSessionCached,
} from '@/utils/authSessionCache'
import { useModsStore } from '@/stores/mods'
import { DESKTOP_ADMIN_FORBIDDEN_MESSAGE, isAdminConsoleSpa, resolveAdminConsoleHomeUrl } from '@/utils/adminConsoleUrl'
import { isDesktopShell } from '@/utils/desktopShell'
import { ADMIN_HOST_ROUTE_RECORDS } from '@admin-console-inject/adminHostRoutes'
import { ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES, ADMIN_OPERATOR_HOME_ROUTE } from '@/constants/adminOperatorNav'
import { buildRoleMenuProfile, canShowCoreMenuKey } from '@/utils/roleMenuProfile'
import { isClientErpSidebarContext } from '@/constants/genericModPack'
import { resolveInitialRoutes } from './initialRouteSelection'
import { CORE_ROUTES } from './routes/core'
import { BUSINESS_ROUTES } from './routes/business'
import { SHELL_ROUTES } from './routes/shell'
import { refreshDesktopSessionInBackground } from '@/utils/desktopSessionRestore'
import { activeTutorialRunAllowsRoute } from '@/stores/tutorialV2'
const DEFAULT_DUTY_ROSTER_GRAPH_VIEW = 'department'
function normalizeDutyRosterGraphView(raw: unknown): string {
  const token = String(Array.isArray(raw) ? raw[0] : raw || '')
    .trim()
    .toLowerCase()
  if (token === 'department' || token === 'dept' || token === '六部门') return 'department'
  if (token === 'hub' || token === 'center' || token === '中心' || token === '中心图') return 'hub'
  if (token === 'legacy-area' || token === 'area' || token === '物理' || token === '物理分区') return 'legacy-area'
  if (token === 'client' || token === 'workshop' || token === '车间' || token === '客户端车间') return 'client'
  return DEFAULT_DUTY_ROSTER_GRAPH_VIEW
}

// 路由定义按域拆分至 ./routes/（core/business/shell），拼接顺序与拆分前注册顺序完全一致
const allRoutes: RouteRecordRaw[] = [
  ...CORE_ROUTES,
  ...BUSINESS_ROUTES,
  ...SHELL_ROUTES,
]

if (import.meta.env.VITE_XCMAX_ADMIN_CONSOLE === '1') {
  allRoutes.push(...ADMIN_HOST_ROUTE_RECORDS)
}

const routes = resolveInitialRoutes(allRoutes)

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})
router.beforeEach(async (to, _from, next) => {
  let provisionalDesktopEntry = false
  if (to.name === 'duty-roster-graph') {
    const nextView = normalizeDutyRosterGraphView(to.query.view)
    const currentView = String(Array.isArray(to.query.view) ? to.query.view[0] : to.query.view || '')
      .trim()
      .toLowerCase()
    const normalizedView = String(nextView)
    if (currentView !== normalizedView) {
      next({
        name: 'duty-roster-graph',
        query: { ...to.query, view: normalizedView },
        hash: to.hash,
        replace: true,
      })
      return
    }
  }

  if (isAdminConsoleSpa() && to.path.startsWith('/mod/xcagi-planner-bridge/')) {
    const hostPath = to.path.slice('/mod/xcagi-planner-bridge'.length) || '/'
    next({ path: hostPath, query: to.query, hash: to.hash, replace: true })
    return
  }

  if (isAdminConsoleSpa() && to.name && ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES.has(String(to.name))) {
    next({ name: ADMIN_OPERATOR_HOME_ROUTE, replace: true })
    return
  }

  // 独立管理端对所有非公开页面先做管理员会话校验。失败时必须闭锁到登录页，
  // 不能继续渲染企业端对话页；登录后回到 `/` 时直接进入运维总览。
  if (isAdminConsoleSpa() && !to.meta?.publicAccess) {
    try {
      const { useAccountProfileStore } = await import('@/stores/accountProfile')
      const profile = useAccountProfileStore()
      if (!profile.loaded) await profile.refreshFromServer()
      if (!profile.isAdminAccount) {
        next({
          name: 'login',
          query: {
            redirect: to.path === '/' ? '/xcmax-admin' : to.fullPath,
            error: '需要管理员账号登录后访问',
          },
          replace: true,
        })
        return
      }
      if (to.name === 'chat' && to.path === '/' && (_from === START_LOCATION || _from.name === 'login')) {
        next({ name: ADMIN_OPERATOR_HOME_ROUTE, replace: true })
        return
      }
    } catch {
      next({
        name: 'login',
        query: {
          redirect: to.path === '/' ? '/xcmax-admin' : to.fullPath,
          error: '管理员会话校验失败，请重新登录',
        },
        replace: true,
      })
      return
    }
  }

  if (!isAdminConsoleSpa() && (to.name === 'workflow-visualization' || to.name === 'mod-workflow-visualization')) {
    try {
      const { useAccountProfileStore } = await import('@/stores/accountProfile')
      const profileStore = useAccountProfileStore()
      if (!profileStore.loaded) await profileStore.refreshFromServer()
      const modsStore = useModsStore()
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
      )
      if (!canShowCoreMenuKey(menuProfile, 'workflow-visualization')) {
        next({ name: 'workflow-employee-space', replace: true })
        return
      }
    } catch {
      next({ name: 'workflow-employee-space', replace: true })
      return
    }
  }

  if (to.matched.length === 0 && to.path.startsWith('/mod/')) {
    const csHost = customerServiceHostPathFromModPath(to.path)
    if (csHost) {
      next({ path: csHost, query: to.query, hash: to.hash, replace: true })
      return
    }
    if (to.path.startsWith('/mod/xcagi-planner-bridge/') && isProtectedClientModId(readActiveExtensionModId())) {
      next({ path: '/', query: to.query, hash: to.hash, replace: true })
      return
    }
    next({ path: '/', replace: true })
    return
  }

  if (to.path.startsWith('/mod/xcagi-planner-bridge/') && isProtectedClientModId(readActiveExtensionModId())) {
    next({ path: '/', query: to.query, hash: to.hash, replace: true })
    return
  }

  // 局域网授权守卫仅作用于主机管理员控制台（避免影响其他业务页面）
  // 独立 admin-console SPA 已由账号会话鉴权，不再弹出局域网密钥框
  const requiresLanGate = !isAdminConsoleSpa() && to.matched.some((r) => Boolean(r.meta?.hostAdmin))
  if (requiresLanGate && !to.meta.publicAccess) {
    try {
      const lan = useLanGate()
      const status = await lan.refresh()
      if (status?.enabled && !status.authorized) {
        lan.openLanGateModal(to.fullPath)
        next(false)
        return
      }
    } catch {
      /* 状态接口异常时不阻断；后端 401 会兜底拦截 */
    }
  }

  try {
    const modsStore = useModsStore()
    if (modsStore.clientModsUiOff && to.matched.some((r) => Boolean(r.meta?.mod))) {
      next(resolvePlannerChatHomePath())
      return
    }
  } catch {
    /* Pinia 未就绪时忽略 */
  }

  if (to.path === '/' || to.name === 'chat') {
    const modChat = resolvePlannerPagePath('/')
    const modChatPath = modChat.split('?')[0] || modChat
    if (modChat !== '/' && to.path !== modChatPath) {
      if (router.resolve(modChatPath).matched.length === 0) {
        next()
        return
      }
      next({ path: modChat, query: to.query, hash: to.hash })
      return
    }
  }

  const activeTutorialRoute = activeTutorialRunAllowsRoute(String(to.name || ''))
  if (
    isPlatformShellModeEnabled() &&
    !activeTutorialRoute &&
    to.name &&
    !SHELL_CORE_ROUTE_NAMES.has(String(to.name)) &&
    !isIndustryDeliveryRouteName(
      String(to.name),
      useModsStore()
        .mods.map((m) => String(m.id || '').trim())
        .filter(Boolean),
      readHostPackAcknowledged(),
    ) &&
    !to.meta?.mod
  ) {
    const modPage = resolveHostBusinessPageRedirect(String(to.name))
    if (modPage) {
      next(modPage)
      return
    }
    next(resolvePlannerChatHomePath())
    return
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

  // SSOT：桌面壳禁止 admin（须早于 requiresAdminAccount / 管理端客服侧，避免企业构建内 /admin/entitlements 可达）
  if (!to.meta?.publicAccess && isDesktopShell() && !isAdminConsoleSpa()) {
    try {
      const { useAccountProfileStore } = await import('@/stores/accountProfile')
      const profile = useAccountProfileStore()
      const useSessionHint = !profile.loaded && (hasRecentEnterpriseSessionHint() || (await consumeDesktopSessionBootstrapHint()))
      if (useSessionHint) {
        provisionalDesktopEntry = true
        refreshDesktopSessionInBackground(router, profile, to.fullPath !== '/login' ? to.fullPath : '/')
      } else if (!profile.loaded) {
        await profile.refreshFromServer()
      }
      if (!provisionalDesktopEntry && profile.isAdminAccount && to.name !== 'login') {
        try {
          const { authApi } = await import('@/api/auth')
          await authApi.logout().catch(() => undefined)
        } catch {
          /* ignore */
        }
        next({
          name: 'login',
          query: {
            redirect: '/',
            error: DESKTOP_ADMIN_FORBIDDEN_MESSAGE,
          },
        })
        return
      }
    } catch {
      /* ignore — 后续企业会话校验会兜底 */
    }
  }

  if (to.meta?.requiresAdminAccount && !isAdminConsoleSpa()) {
    try {
      const { useAccountProfileStore } = await import('@/stores/accountProfile')
      const profile = useAccountProfileStore()
      if (!profile.loaded) {
        await profile.refreshFromServer()
      }
      if (!profile.isAdminAccount) {
        next({ name: 'chat' })
        return
      }
    } catch {
      next({ name: 'chat' })
      return
    }
  }

  if (!to.meta?.publicAccess) {
    try {
      const sku = await fetchProductSku()
      if (isEnterpriseEdition(sku)) {
        const useSessionHint = isDesktopShell() && provisionalDesktopEntry
        if (useSessionHint) {
          provisionalDesktopEntry = true
        }
        const valid = useSessionHint ? true : await validateEnterpriseSessionCached()
        if (!valid) {
          next({
            name: 'login',
            query: { redirect: to.fullPath !== '/login' ? to.fullPath : '/' },
          })
          return
        }
        try {
          const { useAccountProfileStore } = await import('@/stores/accountProfile')
          const profile = useAccountProfileStore()
          if (provisionalDesktopEntry && !profile.loaded) {
            refreshDesktopSessionInBackground(router, profile, to.fullPath !== '/login' ? to.fullPath : '/')
          } else if (!profile.loaded) {
            await profile.refreshFromServer()
          }
          if (!provisionalDesktopEntry && !isAdminConsoleSpa() && profile.isAdminAccount && to.name !== 'login') {
            // 非桌面：网页企业壳把 admin 会话导向独立管理端；桌面已在上方拒入
            if (isDesktopShell()) {
              try {
                const { authApi } = await import('@/api/auth')
                await authApi.logout().catch(() => undefined)
              } catch {
                /* ignore */
              }
              next({
                name: 'login',
                query: {
                  redirect: '/',
                  error: DESKTOP_ADMIN_FORBIDDEN_MESSAGE,
                },
              })
              return
            }
            const adminHome = resolveAdminConsoleHomeUrl()
            if (!adminHome) {
              next({
                name: 'login',
                query: {
                  redirect: '/',
                  error: DESKTOP_ADMIN_FORBIDDEN_MESSAGE,
                },
              })
              return
            }
            window.location.href = adminHome
            next(false)
            return
          }
        } catch {
          /* ignore */
        }
      }
    } catch {
      const sku = await fetchProductSku().catch(() => 'generic')
      if (!isEnterpriseEdition(sku)) {
        next()
        return
      }
      next({
        name: 'login',
        query: { redirect: to.fullPath !== '/login' ? to.fullPath : '/' },
      })
      return
    }
  }

  // Do not turn an existing desktop user into a first-run user while the
  // background validation and tenant preference hydration are still running.
  if (provisionalDesktopEntry) {
    next()
    return
  }

  if (shouldRouteToProductOnboarding(to.name) && !to.meta?.publicAccess && !isAdminConsoleSpa()) {
    const sku = await fetchProductSku().catch(() => 'generic')
    if (!isEnterpriseEdition(sku)) {
      const { resolveProductFlowEntryStep } = await import('@/constants/productFlow')
      const step = resolveProductFlowEntryStep(to.query?.step)
      next({ name: 'product-onboarding', query: { step, redirect: to.fullPath } })
      return
    }
  }

  if (shouldRouteToHostPackOnboarding(to.name) && !to.meta?.publicAccess && !isAdminConsoleSpa()) {
    try {
      // The login success navigation refreshes this gate once.  Reusing its
      // short session cache keeps a subsequent desktop deep-link/reload from
      // blocking the usable screen on the same three bootstrap requests.
      const onboardingStep = await resolveHostPackOnboardingStep(false)
      if (onboardingStep) {
        next({
          name: 'product-onboarding',
          query: {
            step: onboardingStep,
            redirect: to.fullPath !== '/onboarding' ? to.fullPath : '/',
          },
        })
        return
      }
    } catch {
      /* API 异常时不阻断主流程 */
    }
  }

  next()
})

router.afterEach((to) => {
  const title = to.meta?.title
  document.title = title ? `${title} - XCAGI` : 'XCAGI'
})

export default router
