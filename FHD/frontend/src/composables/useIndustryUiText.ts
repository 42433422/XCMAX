import { computed } from 'vue'
import { useIndustryStore } from '@/stores/industry'
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults'
import { resolveCoreNavLabel } from '@/utils/coreNavLabel'
import { getIndustryPreset } from '@/constants/industryPresets'
import { asRecord } from '@/utils/typeGuards'

type StarterPackItem = {
  label: string
  hint: string
  text: string
}

function str(value: unknown, fallback = ''): string {
  const s = String(value ?? '').trim()
  return s || fallback
}

function stripEntitySuffix(label: string): string {
  return str(label)
    .replace(/(名称|姓名|编号|代码|编码|名)$/u, '')
    .trim()
}

function normalizeStarterPack(rows: unknown): StarterPackItem[] {
  if (!Array.isArray(rows)) return []
  return rows
    .map((row) => {
      if (!row || typeof row !== 'object') return null
      const r = row as Record<string, unknown>
      const label = str(r.label)
      const hint = str(r.hint)
      const text = str(r.text)
      if (!label || !text) return null
      return { label, hint, text }
    })
    .filter((item): item is StarterPackItem => Boolean(item))
}

/**
 * 行业 UI 文案 composable：只从 industryStore（SSOT）读取行业信息。
 * Phase 1 SSOT 收敛后，行业由后端 User.industry_id 决定，前端不再从 active mod 推断。
 */
export function useIndustryUiText() {
  const industryStore = useIndustryStore()

  const industryId = computed(() => str(industryStore.currentIndustryId, DEFAULT_INDUSTRY_ID))
  const industryConfig = computed(() => asRecord(industryStore.currentConfig))
  const uiLabels = computed<Record<string, unknown>>(() => {
    const labels = industryConfig.value.ui_labels
    return labels && typeof labels === 'object' ? asRecord(labels) : {}
  })

  const productFields = computed<Record<string, unknown>>(() => {
    return asRecord(industryConfig.value.product_fields)
  })
  const quantityFields = computed<Record<string, unknown>>(() => {
    return asRecord(industryConfig.value.quantity_fields)
  })
  const orderTypes = computed<Record<string, unknown>>(() => {
    return asRecord(industryConfig.value.order_types)
  })
  const units = computed<Record<string, unknown>>(() => {
    return asRecord(industryConfig.value.units)
  })

  const entityName = computed(() =>
    str(uiLabels.value.entity, stripEntitySuffix(str(productFields.value.name, '业务对象')) || '业务对象'),
  )
  const entityPluralName = computed(() => str(uiLabels.value.entity_plural, entityName.value))
  const modelLabel = computed(() => str(uiLabels.value.model_label, str(productFields.value.model, '编号')))
  const nameLabel = computed(() => str(uiLabels.value.name_label, str(productFields.value.name, `${entityName.value}名称`)))
  const categoryLabel = computed(() => str(uiLabels.value.category_label, str(productFields.value.category, '分类')))
  const priceLabel = computed(() => str(uiLabels.value.price_label, str(productFields.value.price, '单价')))
  const unitLabel = computed(() => str(uiLabels.value.unit_label, str(productFields.value.unit, '单位')))
  const primaryUnit = computed(() => str(uiLabels.value.primary_unit, str(units.value.primary, '次')))
  const primaryQuantityLabel = computed(() =>
    str(uiLabels.value.primary_quantity_label, str(quantityFields.value.primary_label, primaryUnit.value)),
  )
  const shipmentOrderName = computed(() => str(uiLabels.value.shipment_order, str(orderTypes.value.shipment, '业务单')))
  const recordsName = computed(() =>
    str(
      uiLabels.value.records,
      resolveCoreNavLabel('shipment-records', industryId.value, []) || `${shipmentOrderName.value}记录`,
    ),
  )
  const queryTitle = computed(() => str(uiLabels.value.query_title, `${entityName.value}查询`))
  const queryDescription = computed(() =>
    str(uiLabels.value.query_description, `查询与快速修改${entityPluralName.value}资料`),
  )
  const queryPlaceholder = computed(() =>
    str(
      uiLabels.value.query_placeholder,
      `输入${modelLabel.value}或${nameLabel.value}查询${entityName.value}`,
    ),
  )
  const entityListName = computed(() =>
    str(
      uiLabels.value.entity_list,
      resolveCoreNavLabel('products', industryId.value, []) || `${entityName.value}管理`,
    ),
  )
  const assistantSubtitle = computed(() => {
    const indId = industryId.value
    const indName = str(industryConfig.value.name)
    if (indName) return `${indName}（${indId}系统）`
    return `${indId}系统`
  })

  const emptyBeforeSearch = computed(() =>
    str(uiLabels.value.empty_before_search, `请先输入${modelLabel.value}或${nameLabel.value}，再点右侧「查询」。`),
  )
  const keywordChanged = computed(() => str(uiLabels.value.keyword_changed, '关键词已变更，请再点「查询」刷新结果。'))
  const queryFailedPrefix = computed(() => str(uiLabels.value.query_failed_prefix, `${entityName.value}接口请求失败`))
  const searchFailedMessage = computed(
    () => `${queryFailedPrefix.value}。请确认后端已启动、Vite 代理或 VITE_API_BASE_URL 指向正确。`,
  )

  const starterPackPresets = computed<StarterPackItem[]>(() => {
    const fromConfig = normalizeStarterPack(industryConfig.value.ui_starter_pack)
    if (fromConfig.length) return fromConfig
    const preset = getIndustryPreset(industryId.value)
    const fromIndustry = preset.quickButtons
      .filter((b) => b.label !== '测试预览')
      .slice(0, 5)
      .map((b) => ({ label: b.label, hint: b.text, text: b.text }))
    if (fromIndustry.length) return fromIndustry
    return []
  })

  return {
    industryConfig,
    industryId,
    entityName,
    entityPluralName,
    modelLabel,
    nameLabel,
    categoryLabel,
    priceLabel,
    unitLabel,
    primaryUnit,
    primaryQuantityLabel,
    shipmentOrderName,
    recordsName,
    queryTitle,
    queryDescription,
    queryPlaceholder,
    entityListName,
    assistantSubtitle,
    emptyBeforeSearch,
    keywordChanged,
    searchFailedMessage,
    starterPackPresets,
  }
}
