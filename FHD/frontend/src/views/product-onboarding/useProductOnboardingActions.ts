import { nextTick } from 'vue'
import type { Router } from 'vue-router'
import { installHostFoundation, installMod, installIndustrySeed, installCustomerDeliverySeed } from '@/api/modStore'
import { autoOnboardWorkflowEmployeesFromMods } from '@/utils/workflowEmployeeOnboard'
import { deliverySeedModIds } from '@/utils/deliverySeedPackages'
import { patchWorkspacePrefs, queueWorkspacePrefsSync } from '@/utils/workspacePrefsApi'
import { useModsStore } from '@/stores/mods'
import { readBuildEdition } from '@/constants/genericModPack'
import { readProductFlowCompleted, setRuntimeOnboardingOpenIndustryIds } from '@/constants/productFlow'
import { appAlert } from '@/utils/appDialog'
import { productErrorMessage } from '@/utils/productErrorMessage'
import { clearDeliverableStatusCache, fetchIndustryBaseline, fetchOnboardingIndustryCatalog } from '@/utils/platformShellApi'
import { invalidateHostPackCompletionCache } from '@/utils/hostPackOnboardingGate'
import type { WorkspacePrefs } from '@/utils/workspacePrefsApi'
import { promptAdvancedTutorialAfterInstall } from '@/tutorial/promptAdvancedTutorial'
import type { TutorialBuildContext } from '@/tutorial/types'
import type { useProductFlow } from '@/composables/useProductFlow'
import type { useIndustryStore } from '@/stores/industry'
import type { ProductOnboardingState } from './useProductOnboardingState'
import type { useProductOnboardingNav } from './useProductOnboardingNav'

type ProductFlow = ReturnType<typeof useProductFlow>
type IndustryStore = ReturnType<typeof useIndustryStore>
type ProductOnboardingNav = ReturnType<typeof useProductOnboardingNav>

// ProductOnboardingView 的加载与操作逻辑（与拆分前逐字一致）
export function useProductOnboardingActions(
  state: ProductOnboardingState,
  options: {
    router: Router
    flow: ProductFlow
    industryStore: IndustryStore
    nav: ProductOnboardingNav
    tutorialBuildContext: { value: TutorialBuildContext }
  },
) {
  const {
    onboardingCatalog,
    pickedIndustryId,
    loading,
    bootstrapBusy,
    finishing,
    baselinePlan,
    baselineOk,
    normalizePickedIndustryId,
    isIndustrySelectable,
    industryPackageModId,
  } = state
  const { router, flow, industryStore, nav, tutorialBuildContext } = options

  async function refreshBaseline(force = false) {
    baselinePlan.value = await fetchIndustryBaseline(pickedIndustryId.value, force)
  }

  async function refreshStatus() {
    loading.value = true
    try {
      clearDeliverableStatusCache()
      await Promise.all([flow.refreshDeliverable(true), refreshBaseline(true)])
    } finally {
      loading.value = false
    }
  }

  async function runBootstrap() {
    bootstrapBusy.value = true
    try {
      const e = readBuildEdition()
      const edition = e === 'minimal' ? 'minimal' : 'generic'
      const res = await installHostFoundation(edition)
      clearDeliverableStatusCache()
      await flow.refreshDeliverable(true)
      await refreshBaseline(true)

      const industryMissing = [...(baselinePlan.value?.missing_industry_mod_ids || [])]
      const customMissing = [...(baselinePlan.value?.missing_account_custom_mod_ids || [])]
      const installErrors: string[] = []
      if (industryMissing.length) {
        try {
          const ir = await installIndustrySeed(pickedIndustryId.value)
          if (!ir.success) {
            installErrors.push(`行业包：${ir.message || '安装失败'}`)
          }
        } catch (err) {
          installErrors.push(`行业包：${err instanceof Error ? err.message : '安装失败'}`)
        }
      }
      for (const modId of customMissing) {
        try {
          const ir = await installMod(modId)
          if (!ir.success) {
            installErrors.push(`${modId}：${ir.message || '安装失败'}`)
          }
        } catch (err) {
          installErrors.push(`${modId}：${err instanceof Error ? err.message : '安装失败'}`)
        }
      }
      const customSeedIds = deliverySeedModIds(baselinePlan.value)
      for (const modId of customSeedIds) {
        try {
          const ir = await installCustomerDeliverySeed(modId, pickedIndustryId.value)
          if (!ir.success) {
            installErrors.push(`${modId} 交付数据：${ir.message || '安装失败'}`)
          }
        } catch (err) {
          installErrors.push(`${modId} 交付数据：${err instanceof Error ? err.message : '安装失败'}`)
        }
      }
      await refreshBaseline(true)

      if (customMissing.length) {
        try {
          const modsStore = useModsStore()
          await modsStore.refresh()
          await autoOnboardWorkflowEmployeesFromMods(modsStore.modsForUi)
        } catch (err) {
          console.warn('[ProductOnboarding] custom employee onboard failed:', err)
        }
      }

      if (baselineOk.value) {
        invalidateHostPackCompletionCache()
        flow.markHostPackAcknowledged()
        if (!readProductFlowCompleted()) {
          flow.markProductFlowCompleted()
        }
        const promptResult = await promptAdvancedTutorialAfterInstall({
          router,
          buildContext: tutorialBuildContext.value,
          message: '本行业推荐侧栏基础线已装齐，可以开始使用了。\n\n是否现在观看进阶教程，快速熟悉菜单与智能对话？',
          returnContext: { routeName: 'chat' },
        })
        if (promptResult === 'already_completed') {
          await appAlert('本行业推荐侧栏基础线已装齐，可以开始使用了。')
        }
        return
      }

      const requiredMissing = baselinePlan.value?.missing_required_mod_ids || []
      const detailParts: string[] = []
      if (!res.success) {
        detailParts.push(res.message || '宿主基础线装包未完成')
      }
      if (requiredMissing.length) {
        detailParts.push(`仍缺必需项：${requiredMissing.join('、')}`)
      }
      if (installErrors.length) {
        detailParts.push(installErrors.join('；'))
      }
      await appAlert(detailParts.join('\n') || '部分项目未装齐，可稍后在扩展市场继续安装。')
    } catch (err) {
      await appAlert(productErrorMessage(err, '装包失败'))
    } finally {
      bootstrapBusy.value = false
    }
  }

  function pickIndustry(id: string) {
    if (!isIndustrySelectable(id)) return
    pickedIndustryId.value = normalizePickedIndustryId(id)
  }

  async function confirmIndustryAndNext() {
    pickedIndustryId.value = normalizePickedIndustryId(pickedIndustryId.value)
    if (!industryStore.isLoaded) {
      try {
        await industryStore.initialize()
      } catch {
        /* 离线仍允许继续 */
      }
    }
    loading.value = true
    try {
      await patchWorkspacePrefs({
        selected_industry_id: pickedIndustryId.value,
        industry_mod_id: industryPackageModId(pickedIndustryId.value) || undefined,
      })
      clearDeliverableStatusCache()
      try {
        onboardingCatalog.value = await fetchOnboardingIndustryCatalog()
        if (onboardingCatalog.value?.open_industry_ids?.length) {
          setRuntimeOnboardingOpenIndustryIds(onboardingCatalog.value.open_industry_ids)
        }
      } catch {
        /* 绑定已完成，目录刷新失败不阻断下一步 */
      }
    } catch (err) {
      await appAlert(productErrorMessage(err, '行业绑定失败，请稍后重试'))
      return
    } finally {
      loading.value = false
    }
    nav.goStep('host-pack')
  }

  async function finishOnboardingComplete() {
    if (finishing.value) return
    finishing.value = true
    // onboarding_completed_at 为服务端兼容的额外字段，暂不在 WorkspacePrefs 类型内（断言豁免，运行时 payload 不变）
    queueWorkspacePrefsSync({
      product_flow_completed: true,
      onboarding_completed_at: new Date().toISOString(),
    } as WorkspacePrefs)
    flow.markProductFlowCompleted()
    flow.markHostPackAcknowledged()
    await nextTick()
    nav.finishHostPackFlow()
  }

  return {
    refreshBaseline,
    refreshStatus,
    runBootstrap,
    pickIndustry,
    confirmIndustryAndNext,
    finishOnboardingComplete,
  }
}
