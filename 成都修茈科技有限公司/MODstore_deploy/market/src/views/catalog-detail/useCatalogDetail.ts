// 拆分自 CatalogDetailView.vue：详情数据加载（详情/评价/质量评估/员工状态），逻辑逐字迁移，行为不变。
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../../api'
import type { CatalogQualityResponse, SixDimensionReport } from '../../types/sixDimension'
import type { CatalogItemDetail, EmployeeStatusPayload, ReviewsPayload } from './catalogDetailTypes'

export function useCatalogDetail() {
  const route = useRoute()
  const catalogParamId = computed(() => {
    const p = route.params.id
    const v = Array.isArray(p) ? p[0] : p
    return v == null ? '' : String(v)
  })

  const item = ref<CatalogItemDetail | null>(null)
  const loading = ref(true)
  const err = ref('')
  const hasToken = ref(false)

  const itemCapabilities = computed(() => item.value?.capabilities || [])
  const itemExamples = computed(() => item.value?.examples || [])

  const productAvatarLetter = computed(() => {
    const name = String(item.value?.name || item.value?.pkg_id || '员').trim()
    return name.charAt(0).toUpperCase() || '员'
  })

  // 评价
  const reviewsLoading = ref(false)
  const reviewsErr = ref('')
  const reviewsData = ref<ReviewsPayload>({ reviews: [], average_rating: 0, total: 0 })

  async function loadReviews() {
    if (!catalogParamId.value) return
    reviewsLoading.value = true
    reviewsErr.value = ''
    try {
      reviewsData.value = (await api.catalogReviews(catalogParamId.value)) as ReviewsPayload
    } catch (e) {
      reviewsErr.value = (e as Error)?.message || '加载评价失败'
    } finally {
      reviewsLoading.value = false
    }
  }

  // 质量评估
  const qualityLoading = ref(false)
  const qualityError = ref('')
  const qualityVisible = ref(false)
  const qualityReport = ref<SixDimensionReport | null>(null)
  const qualityValidateErrors = ref<string[]>([])
  const qualityPipelineLabel = ref('')
  const qualityAuditedAt = ref('')
  const qualityFromCache = ref(false)
  const qualityLlmSummary = ref('')

  const qualityScoringLabel = computed(() => {
    const src = qualityReport.value?.scoring_source
    if (src === 'llm') return '评分来源：六维质检员工 LLM 评估'
    if (src === 'deterministic') return '评分来源：规则引擎（快速）'
    return ''
  })

  const qualityOverallScore = computed(() => {
    const n = Number(qualityReport.value?.overall_score ?? 0)
    return n > 0 ? n.toFixed(1) : ''
  })

  const qualityOverallGrade = computed(() =>
    String(qualityReport.value?.overall_grade || '')
      .trim()
      .toUpperCase(),
  )

  async function loadQuality(opts: boolean | { refresh?: boolean; llm?: boolean } = false) {
    if (!catalogParamId.value) return
    const options = typeof opts === 'boolean' ? { refresh: opts } : opts
    qualityLoading.value = true
    qualityError.value = ''
    try {
      const res = (await api.catalogQuality(catalogParamId.value, options)) as CatalogQualityResponse
      qualityVisible.value = true
      qualityReport.value = (res.six_dimension as SixDimensionReport) || null
      qualityValidateErrors.value = Array.isArray(res.validate_errors) ? res.validate_errors : []
      qualityPipelineLabel.value = String(res.pipeline_label || '')
      qualityAuditedAt.value = String(res.audited_at || '')
      qualityFromCache.value = Boolean(res.from_cache) && !options.llm
      qualityLlmSummary.value = String(qualityReport.value?.llm_summary || '')
    } catch (e) {
      qualityError.value = (e as Error)?.message || '加载质量评估失败'
      qualityVisible.value = true
    } finally {
      qualityLoading.value = false
    }
  }

  // 员工状态
  const employeeStatus = ref({
    loading: false,
    error: '',
    data: null as EmployeeStatusPayload | null,
  })

  async function loadEmployeeStatus() {
    if (!item.value) return

    employeeStatus.value.loading = true
    employeeStatus.value.error = ''

    try {
      const status = await api.getEmployeeStatus(item.value.pkg_id || '')
      employeeStatus.value.data = status
    } catch (e) {
      employeeStatus.value.error = (e as Error)?.message || String(e)
    } finally {
      employeeStatus.value.loading = false
    }
  }

  return {
    catalogParamId,
    item,
    loading,
    err,
    hasToken,
    itemCapabilities,
    itemExamples,
    productAvatarLetter,
    reviewsLoading,
    reviewsErr,
    reviewsData,
    loadReviews,
    qualityLoading,
    qualityError,
    qualityVisible,
    qualityReport,
    qualityValidateErrors,
    qualityPipelineLabel,
    qualityAuditedAt,
    qualityFromCache,
    qualityLlmSummary,
    qualityScoringLabel,
    qualityOverallScore,
    qualityOverallGrade,
    loadQuality,
    employeeStatus,
    loadEmployeeStatus,
  }
}
