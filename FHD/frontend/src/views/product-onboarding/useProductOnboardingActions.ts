import { nextTick, ref, watch } from 'vue'
import type { Router } from 'vue-router'
import { installHostFoundation, installMod, installIndustrySeed, installCustomerDeliverySeed } from '@/api/modStore'
import { autoOnboardWorkflowEmployeesFromMods } from '@/utils/workflowEmployeeOnboard'
import { deliverySeedModIds } from '@/utils/deliverySeedPackages'
import { patchWorkspacePrefs, queueWorkspacePrefsSync } from '@/utils/workspacePrefsApi'
import { useModsStore } from '@/stores/mods'
import { readBuildEdition } from '@/constants/genericModPack'
import { cancelPendingFirstAiTask, queueFirstAiTaskPrompt, setRuntimeOnboardingOpenIndustryIds } from '@/constants/productFlow'
import { appAlert } from '@/utils/appDialog'
import { productErrorMessage } from '@/utils/productErrorMessage'
import { invalidateEnterpriseSessionCache, validateEnterpriseSessionCached } from '@/utils/authSessionCache'
import {
  clearDeliverableStatusCache,
  fetchIndustryBaseline,
  fetchOnboardingIndustryCatalog,
  seedOnboardingDemo,
} from '@/utils/platformShellApi'
import { invalidateHostPackCompletionCache } from '@/utils/hostPackOnboardingGate'
import type { WorkspacePrefs } from '@/utils/workspacePrefsApi'
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
    seedBusy,
    demoSeedResult,
    baselinePlan,
    baselineOk,
    normalizePickedIndustryId,
    isIndustrySelectable,
    industryPackageModId,
  } = state
  const { flow, industryStore, nav } = options
  const loginRequired = ref(false)

  function handleMissingAccount(error: unknown): boolean {
    const status = error && typeof error === 'object' && 'status' in error ? Number(error.status) : 0
    if (status !== 401 && !(error instanceof Error && /\b401\b/.test(error.message))) return false
    invalidateEnterpriseSessionCache()
    loginRequired.value = true
    return true
  }

  async function requireAccount(): Promise<boolean> {
    try {
      // Public onboarding can precede the first login. A local profile/hint
      // cannot authorize binding an industry or installing account features.
      loginRequired.value = !(await validateEnterpriseSessionCached(true))
      return !loginRequired.value
    } catch (error) {
      if (handleMissingAccount(error)) return false
      throw error
    }
  }

  watch(
    state.isAttendanceOnboarding,
    (attendance) => {
      demoSeedResult.value = null
      if (attendance) cancelPendingFirstAiTask()
    },
    { immediate: true },
  )

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
      if (!(await requireAccount())) return
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
        return true
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
      if (!handleMissingAccount(err)) await appAlert(productErrorMessage(err, '装包失败'))
    } finally {
      bootstrapBusy.value = false
    }
  }

  async function ensureDemoData(): Promise<boolean> {
    if (state.isAttendanceOnboarding.value) return false
    if (demoSeedResult.value) return true
    if (seedBusy.value) return false
    seedBusy.value = true
    try {
      if (!(await requireAccount())) return false
      const result = await seedOnboardingDemo(pickedIndustryId.value)
      if (result.seeded === false || result.seed_status === 'workspace_review_required') return false
      demoSeedResult.value = result
      queueWorkspacePrefsSync({ onboarding_seed_done: true } as WorkspacePrefs)
      return true
    } catch (err) {
      if (handleMissingAccount(err)) return false
      console.warn('[ProductOnboarding] demo seed preload failed:', err)
      return false
    } finally {
      seedBusy.value = false
    }
  }

  async function prepareDemoData() {
    if (state.isAttendanceOnboarding.value) {
      nav.goStep('first-ai-task')
      return
    }
    if (await ensureDemoData()) {
      nav.goStep('first-ai-task')
      return
    }
    if (!loginRequired.value) await appAlert('演示数据准备失败，请重试')
  }

  function pickIndustry(id: string) {
    if (!isIndustrySelectable(id)) return
    pickedIndustryId.value = normalizePickedIndustryId(id)
  }

  async function persistIndustryChoice() {
    pickedIndustryId.value = normalizePickedIndustryId(pickedIndustryId.value)
    const industryId = pickedIndustryId.value
    if (!industryStore.isLoaded) {
      try {
        await industryStore.initialize()
      } catch {
        /* 离线仍允许继续 */
      }
    }
    await state.saveCompanyName()
    const saved = await patchWorkspacePrefs({
      selected_industry_id: industryId,
      industry_mod_id: industryPackageModId(industryId) || '',
    })
    if (saved.success !== true) throw new Error('行业未保存，请重试')
    await industryStore.loadFromServer()
    if (industryStore.error || industryStore.currentIndustryId !== industryId || pickedIndustryId.value !== industryId) {
      throw new Error('行业已保存，但工作空间尚未刷新，请重试')
    }
    clearDeliverableStatusCache()
    try {
      onboardingCatalog.value = await fetchOnboardingIndustryCatalog()
      if (onboardingCatalog.value?.open_industry_ids?.length) {
        setRuntimeOnboardingOpenIndustryIds(onboardingCatalog.value.open_industry_ids)
      }
    } catch {
      /* 绑定已完成，目录刷新失败不阻断下一步 */
    }
  }

  async function confirmIndustryAndNext() {
    if (loading.value || finishing.value) return
    loading.value = true
    try {
      if (!(await requireAccount())) return
      await persistIndustryChoice()
    } catch (err) {
      if (!handleMissingAccount(err)) await appAlert(productErrorMessage(err, '行业绑定失败，请稍后重试'))
      return
    } finally {
      loading.value = false
    }
    nav.goStep('host-pack')
  }

  async function createWorkspace() {
    if (bootstrapBusy.value || loading.value || finishing.value) return
    finishing.value = true
    try {
      if (!(await requireAccount())) return
      // Deep links and login redirects can reach configuration without the
      // industry-step action. Bind the displayed selection before accepting
      // readiness; an earlier ready plan may belong to the previous industry.
      await persistIndustryChoice()
      await refreshBaseline(true)
      if (!baselineOk.value && !(await runBootstrap())) return
      // This confirms configuration only; no demo run is queued or completed.
      const saved = await patchWorkspacePrefs({ host_pack_acknowledged: true, product_flow_completed: true })
      if (saved.success !== true) throw new Error('工作空间配置未保存，请重试')
      nav.finishHostPackFlow()
    } catch (error) {
      if (!handleMissingAccount(error)) await appAlert(productErrorMessage(error, '工作空间暂时未准备好，请重试'))
    } finally {
      finishing.value = false
    }
  }

  async function finishOnboardingComplete() {
    if (state.isAttendanceOnboarding.value) {
      await nav.openAttendanceWorkspace()
      return
    }
    if (finishing.value) return
    finishing.value = true
    // A reload on the first-task step loses the in-memory names. Re-read the
    // idempotent seed result before constructing the exact business prompt.
    if (!(await ensureDemoData())) {
      finishing.value = false
      if (!loginRequired.value) await appAlert('演示数据尚未准备完成，请重试后再做第一单')
      return
    }
    queueFirstAiTaskPrompt(state.firstOrderPrompt.value)
    flow.markHostPackAcknowledged()
    await nextTick()
    nav.launchFirstAiTask()
  }

  return {
    loginRequired,
    createWorkspace,
    refreshBaseline,
    refreshStatus,
    runBootstrap,
    prepareDemoData,
    pickIndustry,
    confirmIndustryAndNext,
    finishOnboardingComplete,
  }
}
