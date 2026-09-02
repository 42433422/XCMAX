import { computed } from 'vue'
import type { ComputedRef } from 'vue'
import type { RouteLocationNormalizedLoaded, RouteLocationRaw, Router } from 'vue-router'
import { installHostFoundation, reloadEmployeePacks } from '@/api/modStore'
import { readBuildEdition } from '@/constants/genericModPack'
import { markProductFlowCompleted, markHostPackAcknowledged } from '@/constants/productFlow'
import { fetchDeliverableStatus } from '@/utils/platformShellApi'
import { appAlert } from '@/utils/appDialog'
import { promptAdvancedTutorialAfterInstall, resolveRouteNameFromPath } from '@/tutorial/promptAdvancedTutorial'
import type { TutorialBuildContext } from '@/tutorial/types'
import type { ModStoreState, StoreModRow } from './useModStoreState'
import type { ModStoreCatalog } from './useModStoreCatalog'
import type { ModStoreActions } from './useModStoreActions'

export interface ModStoreOnboardingDeps {
  route: RouteLocationNormalizedLoaded
  router: Router
  tutorialBuildContext: { value: TutorialBuildContext }
  catalog: Pick<ModStoreCatalog, 'filterByCollectionTab' | 'loadMods' | 'mainListTitle'>
  actions: Pick<ModStoreActions, 'installModSilent' | 'refreshHostMods'>
}

export interface ModStoreOnboarding {
  onboardingBanner: ComputedRef<boolean>
  refreshDeliverable: () => Promise<void>
  finishOnboardingFromStore: (dest?: RouteLocationRaw) => void
  goBackFromStore: () => void
  runOneClickInstallAndOnboard: () => Promise<void>
  oneClickPendingCount: ComputedRef<number>
  oneClickCtaLabel: ComputedRef<string>
}

/** 引导/一键安装域（由 ModStore.vue 机械切出，行为不变）：交付物检查、完成引导、一键装齐并入驻 */
export function useModStoreOnboarding(
  state: ModStoreState,
  { route, router, tutorialBuildContext, catalog, actions }: ModStoreOnboardingDeps,
): ModStoreOnboarding {
  const { allMods, currentTab, deliverableOk, missingModIds, bootstrapBusy, oneClickProgress } = state

  const onboardingBanner = computed(() => route.query.onboarding === '1' || deliverableOk.value === false)

  const onboardingRedirect = (): string => {
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect.trim() : ''
    return redirect.startsWith('/') ? redirect : '/'
  }

  const onboardDestinationForTab = (tab: string): string => {
    const redirect = onboardingRedirect()
    if (redirect !== '/') return redirect
    if (tab === 'office' || tab === 'office_aux') return '/workflow-employee-space'
    if (tab === 'workflow') return '/employee-workspace'
    return '/'
  }

  const finishOnboardingFromStore = (dest?: RouteLocationRaw): void => {
    markProductFlowCompleted()
    markHostPackAcknowledged()
    void router.replace(dest || onboardDestinationForTab(currentTab.value))
  }

  const goBackFromStore = (): void => {
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect.trim() : ''
    if (redirect.startsWith('/')) {
      void router.push(redirect)
      return
    }
    if (typeof window !== 'undefined' && window.history.length > 1) {
      router.back()
      return
    }
    void router.push({ name: 'ai-ecosystem' })
  }

  const refreshDeliverable = async (): Promise<void> => {
    try {
      const st = await fetchDeliverableStatus(true)
      deliverableOk.value = st.deliverable !== false
      missingModIds.value = st.missing_mod_ids || []
    } catch {
      deliverableOk.value = true
    }
  }

  const ensureHostFoundationIfNeeded = async (): Promise<void> => {
    if (deliverableOk.value) return
    oneClickProgress.value = '正在安装宿主基础员工包…'
    const edition = readBuildEdition()
    const res = await installHostFoundation(edition === 'minimal' ? 'minimal' : 'generic')
    await refreshDeliverable()
    actions.refreshHostMods()
    if (!res.success || !deliverableOk.value) {
      throw new Error(res.message || '宿主基础员工包未装齐，请检查本机 mods 种子目录。')
    }
  }

  const completePackOnboard = async (tab: string): Promise<void> => {
    markProductFlowCompleted()
    markHostPackAcknowledged()
    const label = catalog.mainListTitle.value || '员工包'
    const dest = onboardDestinationForTab(tab)
    const promptResult = await promptAdvancedTutorialAfterInstall({
      router,
      buildContext: tutorialBuildContext.value,
      message: `${label}已装齐，正在入驻。\n\n是否现在观看进阶教程，快速熟悉菜单与智能对话？`,
      returnContext: { routeName: resolveRouteNameFromPath(router, dest) },
    })
    if (promptResult === 'started') return
    if (promptResult === 'already_completed') {
      await appAlert(`${label}已装齐，正在入驻…`)
    }
    await router.replace(dest)
  }

  const oneClickPendingCount = computed(() => {
    const tab = currentTab.value
    if (tab === 'all' || tab === 'installed') return 0
    if (tab === 'host_foundation') {
      return deliverableOk.value ? 0 : 1
    }
    return catalog.filterByCollectionTab([...allMods.value]).filter((m) => !m.is_installed).length
  })

  const oneClickCtaLabel = computed(() => {
    if (currentTab.value === 'all') return '一键安装并入驻'
    const pending = oneClickPendingCount.value
    if (pending === 0) return '完成入驻'
    return `一键安装并入驻 (${pending})`
  })

  const runOneClickInstallAndOnboard = async (): Promise<void> => {
    const tab = currentTab.value

    if (tab === 'all') {
      await appAlert('请先在左侧选择具体员工包分类（如办公员工包），再一键安装并入驻。')
      return
    }

    if (oneClickPendingCount.value === 0) {
      finishOnboardingFromStore()
      return
    }

    bootstrapBusy.value = true
    const errors: string[] = []
    try {
      await ensureHostFoundationIfNeeded()

      if (tab === 'host_foundation') {
        await completePackOnboard(tab)
        return
      }

      const targets = catalog.filterByCollectionTab([...allMods.value]).filter((m) => !m.is_installed)
      if (!targets.length) {
        await completePackOnboard(tab)
        return
      }

      const label = catalog.mainListTitle.value || '员工包'
      for (let i = 0; i < targets.length; i += 1) {
        const mod: StoreModRow = targets[i]
        oneClickProgress.value = `正在安装 ${label} ${i + 1}/${targets.length}：${mod.name}`
        mod.installationInProgress = true
        try {
          const res = await actions.installModSilent(mod)
          if (res.success) {
            mod.is_installed = true
          } else {
            errors.push(`${mod.name}：${res.message || '安装失败'}`)
          }
        } catch (e) {
          errors.push(`${mod.name}：${e instanceof Error ? e.message : '安装失败'}`)
        } finally {
          mod.installationInProgress = false
        }
      }

      await catalog.loadMods(false)
      actions.refreshHostMods()
      await refreshDeliverable()

      if (tab === 'office' || tab === 'office_aux') {
        try {
          await reloadEmployeePacks()
        } catch (e) {
          console.warn('[ModStore] reloadEmployeePacks:', e)
        }
      }

      const remaining = catalog.filterByCollectionTab([...allMods.value]).filter((m) => !m.is_installed)
      if (!remaining.length && !errors.length) {
        await completePackOnboard(tab)
      } else if (!errors.length && remaining.length) {
        await appAlert(`${label} 仍有 ${remaining.length} 项未安装，请点「刷新目录」后重试或单独安装。`)
      } else {
        const detail = errors.slice(0, 6).join('\n')
        await appAlert(
          `部分员工安装失败${remaining.length ? `，仍有 ${remaining.length} 项未装` : ''}：\n${detail}${errors.length > 6 ? '\n…' : ''}`,
        )
      }
    } catch (e) {
      await appAlert(e instanceof Error ? e.message : '装包失败')
    } finally {
      bootstrapBusy.value = false
      oneClickProgress.value = ''
    }
  }

  return {
    onboardingBanner,
    refreshDeliverable,
    finishOnboardingFromStore,
    goBackFromStore,
    runOneClickInstallAndOnboard,
    oneClickPendingCount,
    oneClickCtaLabel,
  }
}
