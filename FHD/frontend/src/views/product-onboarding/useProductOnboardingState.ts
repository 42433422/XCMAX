import { computed, ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import type {
  IndustryBaselineGroup,
  IndustryBaselinePlan,
  OnboardingIndustryCatalog,
  OnboardingIndustryPackage,
} from '@/constants/platformShell'
import type { OnboardingDemoSeedResult } from '@/utils/platformShellApi'
import { readBuildEdition } from '@/constants/genericModPack'
import { isEnterpriseEdition } from '@/utils/productSku'
import { getIndustryPreset, listIndustryPresets } from '@/constants/industryPresets'
import {
  PRODUCT_FLOW_STEPS,
  defaultOnboardingIndustryId,
  isOnboardingIndustryOpen,
  isTutorialReplayQuery,
  parseFlowStepQuery,
  readOnboardingReturnPath,
} from '@/constants/productFlow'
import type { ProductFlowStepId, ProductFlowStepMeta } from '@/constants/productFlow'
import { resolveCoreNavLabel } from '@/utils/coreNavLabel'

/** 行业 chip 行（目录行或 preset 兜底后的统一形状） */
export interface CatalogChipRow {
  id: string
  name: string
  scenario: string
  productName: string
}

/** 订阅/试用状态（authApi.getSubscriptionStatus 的 data 载荷子集） */
export interface OnboardingSubscriptionStatus {
  reason?: string
  trial_days_remaining?: number | string
  trial_expires_at?: string
}

/**
 * ProductOnboardingView 的全部响应式状态与纯展示逻辑（与拆分前逐项对应）。
 * 各行为 composable 共享同一组 ref，保证与拆分前同一实例。
 */
export function useProductOnboardingState(route: RouteLocationNormalizedLoaded) {
  const industryOptions = listIndustryPresets()
  const onboardingCatalog = ref<OnboardingIndustryCatalog | null>(null)
  const onboardingCatalogLoaded = ref(false)

  function catalogChipRow(pkg: OnboardingIndustryPackage | null | undefined): CatalogChipRow {
    const id = String(pkg?.industry_id || '').trim()
    return {
      id,
      name: String(pkg?.name || getIndustryPreset(id)?.name || id).trim(),
      scenario: String(pkg?.scenario || getIndustryPreset(id)?.scenario || '').trim(),
      productName: String(pkg?.product_name || '').trim(),
    }
  }

  const openIndustryOptions = computed<CatalogChipRow[]>(() => {
    const catalog = onboardingCatalog.value
    if (catalog) {
      return (catalog.open_packages || []).map(catalogChipRow)
    }
    if (isEnterpriseEdition(productSku.value)) return []
    return industryOptions
      .filter((p) => isOnboardingIndustryOpen(p.id))
      .map((p) => ({ id: p.id, name: p.name, scenario: p.scenario, productName: '' }))
  })

  const previewIndustryOptions = computed<CatalogChipRow[]>(() => {
    const previewPkgs = onboardingCatalog.value?.preview_packages
    if (Array.isArray(previewPkgs) && previewPkgs.length) {
      return previewPkgs.map(catalogChipRow)
    }
    if (isEnterpriseEdition(productSku.value) && !onboardingCatalogLoaded.value) return []
    return industryOptions
      .filter((p) => !isOnboardingIndustryOpen(p.id))
      .map((p) => ({ id: p.id, name: p.name, scenario: p.scenario, productName: '' }))
  })

  const openIndustryLeadNames = computed<string[]>(() => {
    const ids = onboardingCatalog.value?.open_industry_ids
    if (Array.isArray(ids) && ids.length) return ids
    return openIndustryOptions.value.map((p) => p.id)
  })

  const industryLeadKindText = computed(() => {
    const count = openIndustryLeadNames.value.length
    return count > 1 ? `${count} 套行业方向` : '行业方向'
  })

  function isIndustrySelectable(id: unknown): boolean {
    const key = String(id || '').trim()
    if (!key) return false
    const openIds = onboardingCatalog.value?.open_industry_ids
    if (Array.isArray(openIds)) {
      return openIds.includes(key)
    }
    return isOnboardingIndustryOpen(key)
  }

  function resolveDefaultPickedIndustryId(): string {
    const selected = String(onboardingCatalog.value?.selected_industry_id || '').trim()
    if (selected && isIndustrySelectable(selected)) return selected
    const openIds = onboardingCatalog.value?.open_industry_ids
    if (Array.isArray(openIds) && openIds.length) return openIds[0]
    return defaultOnboardingIndustryId()
  }

  function normalizePickedIndustryId(raw: unknown): string {
    const id = String(raw || '').trim()
    if (isIndustrySelectable(id)) return id
    return resolveDefaultPickedIndustryId()
  }

  const pickedIndustryId = ref<string>(resolveDefaultPickedIndustryId())
  const canConfirmIndustry = computed(() => openIndustryOptions.value.length > 0 && isIndustrySelectable(pickedIndustryId.value))

  function industryPackageLabel(industryId: unknown): string {
    const id = String(industryId || '').trim()
    const row = onboardingCatalog.value?.open_packages?.find((p) => p.industry_id === id)
    if (row?.product_name) return row.product_name
    const chip = openIndustryOptions.value.find((p) => p.id === id)
    if (chip?.productName) return chip.productName
    const preset = getIndustryPreset(id)
    return preset?.name ? `${preset.name}行业包` : ''
  }

  function industryPackageModId(industryId: string): string {
    const id = String(industryId || '').trim()
    const row = onboardingCatalog.value?.open_packages?.find((p) => p.industry_id === id)
    return String(row?.mod_id || '').trim()
  }

  /** 行业 chip 第三行：去掉句末句号，避免行高不齐 */
  function chipScenarioText(text: unknown): string {
    return String(text || '').replace(/[。．]$/, '')
  }

  const steps: ProductFlowStepMeta[] = PRODUCT_FLOW_STEPS.filter((s) => s.id !== 'done')
  const currentStep = ref<ProductFlowStepId>(parseFlowStepQuery(route.query.step))
  const loading = ref(false)
  const bootstrapBusy = ref(false)
  const finishing = ref(false)
  const seedBusy = ref(false)
  const demoSeedResult = ref<OnboardingDemoSeedResult | null>(null)
  const baselinePlan = ref<IndustryBaselinePlan | null>(null)

  function startupAsset(fileName: string): string {
    const base = String(import.meta.env.BASE_URL || '/')
    return `${base}startup/${fileName}`.replace(/([^:]\/)\/+/g, '$1')
  }

  /** 与侧栏 / 开屏同源：带 XC 字标；PNG 透明底 */
  const welcomeLogoCandidates = [startupAsset('xc-logo-text.png'), startupAsset('xc-logo-text.jpg'), startupAsset('xc-logo-base.jpg')]
  const welcomeLogoSrc = ref(welcomeLogoCandidates[0])
  let welcomeLogoFallbackIndex = 0

  function onWelcomeLogoError() {
    welcomeLogoFallbackIndex += 1
    if (welcomeLogoFallbackIndex < welcomeLogoCandidates.length) {
      welcomeLogoSrc.value = welcomeLogoCandidates[welcomeLogoFallbackIndex]
    }
  }

  function initialProductSku(): string {
    return (
      String(import.meta.env.VITE_XCAGI_PRODUCT_SKU || 'generic')
        .trim()
        .toLowerCase() || 'generic'
    )
  }

  const productSku = ref(initialProductSku())
  const subscription = ref<OnboardingSubscriptionStatus | null>(null)
  const trialStatusText = computed(() => {
    const sub = subscription.value
    if (!sub || sub.reason !== 'trial') return ''
    const days = sub.trial_days_remaining ?? '—'
    return `当前为试用账户：剩余 ${days} 天${sub.trial_expires_at ? `（至 ${sub.trial_expires_at}）` : ''}。满意后可选购永久授权（1 万元起）。`
  })
  const baselineOk = computed(() => baselinePlan.value?.baseline_ready === true)

  const SIDEBAR_PREVIEW_MENU_KEYS = [
    'products',
    'customers',
    'orders',
    'shipment-records',
    'materials',
    'data-sources',
    'print',
    'printer-list',
    'template-preview',
  ]
  const industrySidebarPreviewLabels = computed<string[]>(() => {
    const id = String(pickedIndustryId.value || '').trim()
    const labels = SIDEBAR_PREVIEW_MENU_KEYS.map((key) => resolveCoreNavLabel(key, id, null)).filter(Boolean)
    const capabilityIds = new Set((baselinePlan.value?.capability_mod_ids || []).map((value) => String(value || '').trim()))
    if (id === '考勤' || capabilityIds.has('attendance-industry')) {
      labels.unshift('考勤表转换')
    }
    return [...new Set(labels)]
  })
  const baselineGroups = computed<IndustryBaselineGroup[]>(() => baselinePlan.value?.groups || [])
  const SIDEBAR_BASELINE_GROUP_IDS = new Set(['core', 'host'])
  const sidebarBaselineGroups = computed(() => baselineGroups.value.filter((g) => SIDEBAR_BASELINE_GROUP_IDS.has(String(g?.id || ''))))
  const supplementBaselineGroups = computed(() => baselineGroups.value.filter((g) => !SIDEBAR_BASELINE_GROUP_IDS.has(String(g?.id || ''))))
  /** 明细折叠区：优先侧栏+补充分组，否则回退全部 groups */
  const hostPackDetailGroups = computed<IndustryBaselineGroup[]>(() => {
    if (sidebarBaselineGroups.value.length) {
      return [...sidebarBaselineGroups.value, ...supplementBaselineGroups.value]
    }
    return baselineGroups.value
  })
  const missingSidebarBaselineCount = computed(() => {
    const ids = new Set<string>()
    for (const g of sidebarBaselineGroups.value) {
      for (const it of g.items || []) {
        if (it?.required && !it?.installed && it?.mod_id) ids.add(String(it.mod_id))
      }
    }
    return ids.size
  })
  const missingRequiredCount = computed(() => baselinePlan.value?.missing_required_mod_ids?.length || 0)
  const missingAccountCustomCount = computed(() => baselinePlan.value?.missing_account_custom_mod_ids?.length || 0)
  const missingIndustryPackageCount = computed(() => {
    const ids = new Set(baselinePlan.value?.industry_mod_ids || [])
    return (baselinePlan.value?.missing_industry_mod_ids || []).filter((id) => ids.has(id)).length
  })
  const hasAccountCustomEntitlement = computed(() => (baselinePlan.value?.account_custom_mod_ids?.length || 0) > 0)
  const showNoAccountCustomHint = computed(
    () => isEnterpriseEdition(productSku.value) && currentStep.value === 'host-pack' && !loading.value && !hasAccountCustomEntitlement.value,
  )
  const pickedIndustryName = computed(() => getIndustryPreset(pickedIndustryId.value).name)
  const firstOrderPrompt = computed(() => {
    const customer = String(demoSeedResult.value?.customer?.name || '演示客户').trim()
    const product = String(demoSeedResult.value?.product?.name || '演示商品').trim()
    return [
      '这是我的新手第一单，请你作为 AI 业务员工按顺序执行：',
      `1. 查询客户「${customer}」；`,
      `2. 查询商品「${product}」并确认可用数量；`,
      '3. 根据查询结果创建一张数量为 1 的演示出货单。',
      '涉及写入时先展示计划并让我确认，完成后告诉我每一步调用的工具和业务结果。',
    ].join('\n')
  })

  const currentIndex = computed(() => {
    const row = steps.find((s) => s.id === currentStep.value)
    return row?.index ?? 1
  })

  const currentStepMeta = computed<ProductFlowStepMeta | null>(() => steps.find((s) => s.id === currentStep.value) || null)

  const editionLabel = computed(() => {
    const sku = String(productSku.value || '')
      .trim()
      .toLowerCase()
    if (sku === 'enterprise') return '企业版 enterprise'
    if (sku === 'personal') return '个人版 personal'
    const e = readBuildEdition()
    if (e === 'minimal') return '空壳 minimal'
    if (e === 'generic') return '通用 generic'
    return '完整 full'
  })

  const fromTutorial = computed(() => isTutorialReplayQuery(route.query.from))
  const returnPath = computed(() => readOnboardingReturnPath(route.query.redirect))
  const footerHint = computed(() =>
    fromTutorial.value ? '来自新手教程 · 可随时返回继续日常使用' : '完整流程见 docs/guides/PRODUCT_USER_FLOW.md',
  )

  return {
    industryOptions,
    onboardingCatalog,
    onboardingCatalogLoaded,
    openIndustryOptions,
    previewIndustryOptions,
    openIndustryLeadNames,
    industryLeadKindText,
    isIndustrySelectable,
    normalizePickedIndustryId,
    pickedIndustryId,
    canConfirmIndustry,
    industryPackageLabel,
    industryPackageModId,
    chipScenarioText,
    steps,
    currentStep,
    loading,
    bootstrapBusy,
    finishing,
    seedBusy,
    demoSeedResult,
    baselinePlan,
    welcomeLogoSrc,
    onWelcomeLogoError,
    productSku,
    subscription,
    trialStatusText,
    baselineOk,
    industrySidebarPreviewLabels,
    hostPackDetailGroups,
    missingSidebarBaselineCount,
    missingRequiredCount,
    missingAccountCustomCount,
    missingIndustryPackageCount,
    showNoAccountCustomHint,
    pickedIndustryName,
    firstOrderPrompt,
    currentIndex,
    currentStepMeta,
    editionLabel,
    fromTutorial,
    returnPath,
    footerHint,
  }
}

export type ProductOnboardingState = ReturnType<typeof useProductOnboardingState>
