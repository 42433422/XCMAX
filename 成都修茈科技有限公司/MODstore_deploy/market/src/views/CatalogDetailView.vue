<template>
  <div class="catalog-detail">
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="err" class="flash flash-err">{{ err }}</div>
    <template v-else-if="item">
      <header class="detail-hero">
        <div class="detail-hero__main">
          <div class="detail-hero__avatar" aria-hidden="true">{{ productAvatarLetter }}</div>
          <div class="detail-hero__body">
            <div class="detail-hero__title-row">
              <h1 class="detail-hero__title">{{ item.name }}</h1>
              <span
                v-if="qualityVisible && qualityOverallGrade"
                class="detail-hero__grade"
                :class="'detail-hero__grade--' + qualityOverallGrade.toLowerCase()"
                :title="qualityOverallScore + ' 分'"
              >
                {{ qualityOverallGrade }}级 · {{ qualityOverallScore }}
              </span>
            </div>
            <p class="detail-hero__meta">
              <code class="detail-hero__pkg">{{ item.pkg_id }}</code>
              <span class="detail-hero__dot">·</span>
              v{{ item.version }}
              <span class="detail-hero__dot">·</span>
              {{ item.industry || '通用' }}
              <span class="detail-hero__dot">·</span>
              {{ getArtifactLabel(item.artifact) }}
            </p>
            <div class="detail-hero__tags">
              <span class="info-chip">{{ item.license_scope_label || licenseScopeLabel(item.license_scope) }}</span>
              <span class="info-chip">来源：{{ originTypeLabel(item.origin_type) }}</span>
              <span class="info-chip">风险：{{ ipRiskLabel(item.ip_risk_level) }}</span>
              <span
                class="info-chip"
                :class="{ warn: item.compliance_status && item.compliance_status !== 'approved' }"
              >
                {{ complianceStatusLabel(item.compliance_status) }}
              </span>
            </div>
          </div>
        </div>
        <div class="detail-hero__cta">
          <div class="detail-hero__price" :class="{ free: item.price <= 0 }">
            {{ item.price <= 0 ? '免费' : '¥' + item.price.toFixed(2) }}
          </div>
          <div class="detail-hero__buttons">
            <template v-if="item.purchased">
              <button type="button" class="btn btn-success" @click="doDownload">下载</button>
              <span class="owned-badge">已拥有</span>
            </template>
            <template v-else>
              <button type="button" class="btn btn-primary-solid btn-cta-buy" @click="doBuy" :disabled="buying">
                {{ buying ? '购买中...' : '购买' }}
              </button>
            </template>
            <button
              v-if="authStore.isAdmin"
              type="button"
              class="btn btn-danger"
              :disabled="delisting"
              @click="delistItem"
            >
              {{ delisting ? '下架中...' : '下架' }}
            </button>
          </div>
        </div>
      </header>

      <CatalogCreatorProfile
        v-if="item"
        :author="item.author ?? null"
        :stats="item.creator_stats ?? null"
        :install-count="item.install_count"
        :industry="item.industry"
        :favorited="!!item.favorited"
        :following="authorFollowing"
        :fav-busy="favBusy"
        :is-self="isAuthorSelf"
        @follow="toggleAuthorFollow"
        @favorite="toggleFavorite"
        @complaint="openComplaintPanel"
      />

      <div v-if="complaintPanelOpen" class="detail-section complaint-panel">
        <div class="complaint-panel__head">
          <h2 class="section-title">投诉与申诉</h2>
          <button type="button" class="btn btn-secondary complaint-panel__close" @click="complaintPanelOpen = false">
            收起
          </button>
        </div>
        <p class="section-desc">
          涉及抄袭、联动/IP 风险、授权争议、无法下载或权益异常时，可先提交记录，再进入 AI 客服补充证据材料。
        </p>
        <div class="complaint-form">
          <select v-model="complaintType" class="input">
            <option value="plagiarism">疑似抄袭</option>
            <option value="ip_risk">联动/IP 风险</option>
            <option value="license">授权或商业使用争议</option>
            <option value="delivery">购买/下载/权益异常</option>
            <option value="appeal">作者申诉</option>
            <option value="other">其他问题</option>
          </select>
          <textarea
            v-model="complaintReason"
            class="input textarea"
            rows="3"
            maxlength="4000"
            placeholder="请说明问题、证据链接或希望处理的结果"
          />
          <div class="complaint-actions">
            <button type="button" class="btn btn-primary-solid" :disabled="complaintSubmitting" @click="submitComplaint">
              {{ complaintSubmitting ? '提交中...' : '提交投诉/申诉' }}
            </button>
            <router-link :to="customerServiceLink('complaint')" class="btn btn-secondary">进入 AI 客服补充材料</router-link>
          </div>
        </div>
      </div>

      <!-- 员工包：规格 + 六维（懒加载） -->
      <div v-if="item.artifact === 'employee_pack'" class="detail-main-grid">
        <section class="detail-spec-col detail-panel">
          <h2 class="section-title">规格与能力</h2>
          <div v-if="qualityPipelineLabel" class="spec-runtime">
            <span class="spec-label">Runtime</span>
            <code>{{ qualityPipelineLabel }}</code>
          </div>
          <div v-if="itemCapabilities.length" class="spec-block">
            <h3 class="spec-subtitle">核心能力</h3>
            <ul class="capability-list">
              <li v-for="cap in itemCapabilities" :key="cap.label">
                <span class="cap-label">{{ cap.label }}</span>
                <span v-if="cap.description" class="cap-desc">{{ cap.description }}</span>
              </li>
            </ul>
          </div>
          <div class="spec-cards">
            <div class="spec-mini-card">
              <span class="spec-mini-label">行业适配</span>
              <span>{{ item.industry || '通用' }}</span>
            </div>
            <div class="spec-mini-card">
              <span class="spec-mini-label">安全等级</span>
              <span>{{ securityLevelLabel(item.security_level) }}</span>
            </div>
            <div class="spec-mini-card">
              <span class="spec-mini-label">版本</span>
              <span>v{{ item.version }}</span>
            </div>
          </div>
        </section>

        <section class="detail-quality-col detail-panel">
          <div class="quality-section-head">
            <h2 class="section-title">质量评估</h2>
            <p v-if="qualityVisible && qualityOverallScore" class="quality-section-score">
              综合 <strong>{{ qualityOverallScore }}</strong> 分
              <span v-if="qualityPipelineLabel" class="quality-section-pipe">{{ qualityPipelineLabel }}</span>
            </p>
          </div>
          <div v-if="!qualityVisible" class="quality-placeholder">
            <p>规则引擎快速评估不消耗 LLM；「LLM 深度评估」由六维质检员工（hex-quality-assessor）打分。</p>
            <div class="quality-placeholder-actions">
              <button type="button" class="btn btn-primary-solid" :disabled="qualityLoading" @click="loadQuality({ refresh: false })">
                {{ qualityLoading ? '检测中...' : '查看六维评估' }}
              </button>
              <button type="button" class="btn btn-secondary" :disabled="qualityLoading" @click="loadQuality({ llm: true })">
                {{ qualityLoading ? '评估中...' : 'LLM 深度评估' }}
              </button>
            </div>
          </div>
          <template v-else>
            <div v-if="qualityValidateErrors.length" class="flash flash-err quality-errors">
              <p v-for="(e, i) in qualityValidateErrors.slice(0, 5)" :key="i">{{ e }}</p>
            </div>
            <EmployeeSixDimPanel
              :report="qualityReport"
              :loading="qualityLoading"
              :error="qualityError"
              compact
              title=""
              :show-grade-scale="false"
            />
            <div class="quality-actions">
              <p v-if="qualityScoringLabel" class="quality-meta quality-meta--source">{{ qualityScoringLabel }}</p>
              <p v-if="qualityLlmSummary" class="quality-meta quality-llm-summary">{{ qualityLlmSummary }}</p>
              <p v-if="qualityAuditedAt" class="quality-meta">
                检测时间：{{ qualityAuditedAt }}
                <span v-if="qualityFromCache">（缓存）</span>
              </p>
              <div class="quality-action-buttons">
                <button
                  type="button"
                  class="btn btn-secondary"
                  :disabled="qualityLoading"
                  @click="loadQuality({ llm: true })"
                >
                  LLM 深度评估
                </button>
                <button
                  v-if="authStore.isAdmin"
                  type="button"
                  class="btn btn-secondary"
                  :disabled="qualityLoading"
                  @click="loadQuality({ refresh: true })"
                >
                  重新检测
                </button>
              </div>
            </div>
          </template>
        </section>
      </div>

      <div v-if="item" class="detail-section reviews-section">
        <h2 class="section-title">评价</h2>
        <p v-if="reviewsData.total > 0" class="reviews-summary">
          平均 {{ reviewsData.average_rating }} 分 · 共 {{ reviewsData.total }} 条
        </p>
        <div v-if="reviewsLoading" class="loading">加载评价...</div>
        <div v-else-if="reviewsErr" class="flash flash-err">{{ reviewsErr }}</div>
        <ul v-else class="review-list">
          <li v-for="r in reviewsData.reviews" :key="r.id" class="review-item">
            <div class="review-head">
              <strong>{{ r.user_name }}</strong>
              <span class="review-stars">{{ '★'.repeat(r.rating) }}{{ '☆'.repeat(5 - r.rating) }}</span>
              <span class="review-date">{{ r.created_at }}</span>
            </div>
            <p v-if="r.content" class="review-body">{{ r.content }}</p>
          </li>
        </ul>
        <div
          v-if="hasToken && item.purchased && !item.user_has_review"
          class="review-form"
        >
          <h3 class="review-form-title">写评价</h3>
          <label class="label">评分（1–5）</label>
          <select v-model.number="reviewRating" class="input">
            <option v-for="n in 5" :key="n" :value="n">{{ n }} 分</option>
          </select>
          <label class="label">内容（可选）</label>
          <textarea v-model="reviewContent" class="input textarea" rows="3" maxlength="4000" placeholder="使用体验、建议等" />
          <button type="button" class="btn btn-primary-solid" :disabled="reviewSubmitting" @click="submitReview">
            {{ reviewSubmitting ? '提交中...' : '提交评价' }}
          </button>
        </div>
        <p v-else-if="hasToken && item.purchased && item.user_has_review" class="review-note">您已评价过该商品。</p>
        <p v-else-if="hasToken && !item.purchased" class="review-note">购买后可发表评价。</p>
      </div>

      <!-- 员工状态 -->
      <div v-if="item.artifact === 'employee_pack' && item.purchased" class="detail-section">
        <h2 class="section-title">员工状态</h2>
        <div v-if="employeeStatus.loading" class="loading">加载中...</div>
        <div v-else-if="employeeStatus.error" class="flash flash-err">{{ employeeStatus.error }}</div>
        <div v-else-if="employeeStatus.data" class="status-grid">
          <div class="status-item">
            <span class="status-label">状态</span>
            <span class="status-value">{{ employeeStatus.data.status }}</span>
          </div>
          <div class="status-item">
            <span class="status-label">总执行次数</span>
            <span class="status-value">{{ employeeTotalExecutions(employeeStatus.data) }}</span>
          </div>
          <div class="status-item">
            <span class="status-label">成功率</span>
            <span class="status-value">{{ employeeSuccessRate(employeeStatus.data).toFixed(1) }}%</span>
          </div>
        </div>
      </div>

      <!-- 工作流配置 -->
      <div v-if="item.artifact === 'employee_pack' && item.purchased" class="detail-section">
        <h2 class="section-title">工作流配置</h2>
        <p class="section-desc">将此员工添加到工作流中，配置任务参数</p>
        <div class="workflow-config">
          <button class="btn btn-primary" @click="navigateToWorkflow">添加到工作流</button>
        </div>
      </div>

      <details v-if="item.artifact === 'employee_pack'" class="detail-fold">
        <summary class="detail-fold-summary">描述与使用示例</summary>
        <p v-if="item.description" class="desc desc--fold">{{ item.description }}</p>
        <div v-if="itemExamples.length">
          <div v-for="ex in itemExamples" :key="ex.title" class="example-card">
            <h3>{{ ex.title }}</h3>
            <p v-if="ex.description" class="example-desc">{{ ex.description }}</p>
            <pre class="example-code">{{ JSON.stringify(ex.input, null, 2) }}</pre>
          </div>
        </div>
        <div v-else class="example-card">
          <h3>调用示例</h3>
          <pre class="example-code">{
  "action": "execute",
  "employee_id": "{{ item.pkg_id || 'employee' }}"
}</pre>
        </div>
      </details>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'
import CatalogCreatorProfile from '../components/catalog/CatalogCreatorProfile.vue'
import EmployeeSixDimPanel from '../components/workbench/EmployeeSixDimPanel.vue'
import type { CatalogQualityResponse, SixDimensionReport } from '../types/sixDimension'
import type { CatalogAuthor, CatalogCreatorStats } from '../components/catalog/CatalogCreatorProfile.vue'

const route = useRoute()
const router = useRouter()
const catalogParamId = computed(() => {
  const p = route.params.id
  const v = Array.isArray(p) ? p[0] : p
  return v == null ? '' : String(v)
})
const authStore = useAuthStore()

const itemCapabilities = computed(() => item.value?.capabilities || [])
const itemExamples = computed(() => item.value?.examples || [])

function securityLevelLabel(level: string | undefined) {
  const map: Record<string, string> = {
    personal: '个人级',
    team: '团队级',
    enterprise: '企业级',
  }
  return map[level || ''] || level || '个人级'
}

interface CatalogItemDetail {
  id: number | string
  pkg_id?: string
  name?: string
  version?: string
  industry?: string
  artifact?: string
  material_category?: string
  description?: string
  license_scope_label?: string
  license_scope?: string
  origin_type?: string
  ip_risk_level?: string
  compliance_status?: string
  security_level?: string
  price: number
  favorited?: boolean
  purchased?: boolean
  user_has_review?: boolean
  status?: string
  execution_stats?: { total_runs?: number; success_rate?: number } | null
  capabilities?: { label: string; description: string }[]
  examples?: { title: string; description: string; input: Record<string, unknown> }[]
  author_id?: number
  author?: CatalogAuthor | null
  creator_stats?: CatalogCreatorStats | null
  install_count?: number
}

interface ReviewRow {
  id: number | string
  user_name?: string
  rating: number
  created_at?: string
  content?: string
}

interface ReviewsPayload {
  reviews: ReviewRow[]
  average_rating: number
  total: number
}

interface EmployeeStatusPayload {
  status?: string
  execution_stats?: {
    total_executions?: number
    total_runs?: number
    success_rate?: number
  } | null
}

const item = ref<CatalogItemDetail | null>(null)
const loading = ref(true)
const err = ref('')
const buying = ref(false)
const delisting = ref(false)
const hasToken = ref(false)
const favBusy = ref(false)
const reviewsLoading = ref(false)
const reviewsErr = ref('')
const reviewsData = ref<ReviewsPayload>({ reviews: [], average_rating: 0, total: 0 })
const reviewRating = ref(5)
const reviewContent = ref('')
const reviewSubmitting = ref(false)
const complaintType = ref('plagiarism')
const complaintReason = ref('')
const complaintSubmitting = ref(false)
const complaintPanelOpen = ref(false)

const AUTHOR_FOLLOW_KEY = 'catalog_author_follows'

function readAuthorFollowSet(): Set<number> {
  try {
    const raw = localStorage.getItem(AUTHOR_FOLLOW_KEY)
    const arr = raw ? (JSON.parse(raw) as unknown) : []
    if (!Array.isArray(arr)) return new Set()
    return new Set(arr.map((x) => Number(x)).filter((n) => Number.isFinite(n) && n > 0))
  } catch {
    return new Set()
  }
}

function writeAuthorFollowSet(set: Set<number>) {
  localStorage.setItem(AUTHOR_FOLLOW_KEY, JSON.stringify([...set]))
}

const authorFollowing = ref(false)

const isAuthorSelf = computed(() => {
  const aid = item.value?.author?.id ?? item.value?.author_id
  const uid = authStore.user?.id
  return Boolean(aid && uid && Number(aid) === Number(uid))
})

function syncAuthorFollowing() {
  const aid = item.value?.author?.id ?? item.value?.author_id
  if (!aid) {
    authorFollowing.value = false
    return
  }
  authorFollowing.value = readAuthorFollowSet().has(Number(aid))
}

function toggleAuthorFollow() {
  const aid = item.value?.author?.id ?? item.value?.author_id
  if (!aid) return
  if (!localStorage.getItem('modstore_token')) {
    router.push({ name: 'login', query: { redirect: `/catalog/${catalogParamId.value}` } })
    return
  }
  const set = readAuthorFollowSet()
  const id = Number(aid)
  if (set.has(id)) set.delete(id)
  else set.add(id)
  writeAuthorFollowSet(set)
  authorFollowing.value = set.has(id)
}

function openComplaintPanel() {
  complaintPanelOpen.value = true
}

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

const productAvatarLetter = computed(() => {
  const name = String(item.value?.name || item.value?.pkg_id || '员').trim()
  return name.charAt(0).toUpperCase() || '员'
})

const qualityOverallScore = computed(() => {
  const n = Number(qualityReport.value?.overall_score ?? 0)
  return n > 0 ? n.toFixed(1) : ''
})

const qualityOverallGrade = computed(() =>
  String(qualityReport.value?.overall_grade || '').trim().toUpperCase(),
)

// 员工状态
const employeeStatus = ref({
  loading: false,
  error: '',
  data: null as EmployeeStatusPayload | null,
})

// 工件类型标签
const artifactLabels = {
  mod: 'MOD 插件',
  employee_pack: 'AI 员工包',
  bundle: '资源包',
  surface: '界面扩展',
  workflow_template: '工作流模板',
}

const materialCategoryLabels = {
  ai_employee: 'AI 员工',
  agent_prompt: 'Agent 提示词',
  skill: 'Skill',
  tts_voice: 'TTS 声音模型',
  mod_asset: 'MOD 包素材',
  page_style: '页面风格',
  personal_design: '个性化设计',
  workflow_template: '工作流模板',
  other: '其他素材',
}

const licenseScopeLabels = {
  personal: '个人使用',
  commercial: '商业授权',
  free_personal: '免费个人用',
  enterprise: '企业级',
}

const originTypeLabels = {
  original: '原创',
  derivative: '二创/改编',
  collaboration: '联动授权',
  fan_linkage: '粉丝联动',
  suspected_plagiarism: '疑似抄袭',
}

const complianceStatusLabels = {
  approved: '已审核',
  active: '已上架',
  under_review: '投诉处理中',
  restricted: '已降权',
  delisted: '已下架',
}

function getArtifactLabel(artifact: string | undefined) {
  return (artifact && (artifactLabels as Record<string, string>)[artifact]) || artifact || '其他'
}

function materialCategoryLabel(cat: string | undefined) {
  return (cat && (materialCategoryLabels as Record<string, string>)[cat]) || cat || '其他素材'
}

function licenseScopeLabel(scope: string | undefined) {
  return (scope && (licenseScopeLabels as Record<string, string>)[scope]) || scope || '个人使用'
}

function originTypeLabel(origin: string | undefined) {
  return (origin && (originTypeLabels as Record<string, string>)[origin]) || origin || '原创'
}

function ipRiskLabel(risk: string | undefined) {
  if (risk === 'high') return '高'
  if (risk === 'medium') return '中'
  return '低'
}

function complianceStatusLabel(status: string | undefined) {
  return (status && (complianceStatusLabels as Record<string, string>)[status]) || status || '已审核'
}

function employeeTotalExecutions(status: EmployeeStatusPayload | null): number {
  const stats = status?.execution_stats
  return Number(stats?.total_executions ?? stats?.total_runs ?? 0) || 0
}

function employeeSuccessRate(status: EmployeeStatusPayload | null): number {
  return Number(status?.execution_stats?.success_rate ?? 0) || 0
}

onMounted(async () => {
  hasToken.value = !!localStorage.getItem('modstore_token')
  try {
    item.value = (await api.catalogDetail(catalogParamId.value)) as CatalogItemDetail
    syncAuthorFollowing()
    await loadReviews()
    // 如果是员工包且已购买，加载员工状态
    if (item.value.artifact === 'employee_pack' && item.value.purchased) {
      await loadEmployeeStatus()
    }
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    loading.value = false
  }
})

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

async function toggleFavorite() {
  if (!item.value) return
  if (!localStorage.getItem('modstore_token')) {
    await router.push({ name: 'login', query: { redirect: `/catalog/${catalogParamId.value}` } })
    return
  }
  favBusy.value = true
  try {
    const r = await api.catalogToggleFavorite(catalogParamId.value)
    item.value.favorited = !!r.favorited
    if (item.value.creator_stats) {
      const delta = item.value.favorited ? 1 : -1
      const cur = Number(item.value.creator_stats.favorite_count ?? 0)
      item.value.creator_stats.favorite_count = Math.max(0, cur + delta)
    }
  } catch (e) {
    alert((e as Error)?.message || String(e))
  } finally {
    favBusy.value = false
  }
}

async function submitReview() {
  if (!item.value || item.value.user_has_review) return
  reviewSubmitting.value = true
  try {
    await api.catalogSubmitReview(catalogParamId.value, reviewRating.value, reviewContent.value.trim())
    item.value.user_has_review = true
    reviewContent.value = ''
    await loadReviews()
  } catch (e) {
    alert((e as Error)?.message || String(e))
  } finally {
    reviewSubmitting.value = false
  }
}

function customerServiceLink(scene = 'complaint') {
  const it = item.value
  return {
    name: 'customer-service',
    query: {
      scene,
      catalog_id: String(it?.id || catalogParamId.value || ''),
      pkg_id: it?.pkg_id || '',
      item_name: it?.name || '',
      material_category: it?.material_category || '',
      complaint_type: complaintType.value || '',
    },
  }
}

async function submitComplaint() {
  if (!item.value) return
  if (!localStorage.getItem('modstore_token')) {
    await router.push({ name: 'login', query: { redirect: `/catalog/${catalogParamId.value}` } })
    return
  }
  const reason = complaintReason.value.trim()
  if (reason.length < 4) {
    alert('请至少填写 4 个字的问题说明')
    return
  }
  complaintSubmitting.value = true
  try {
    await api.catalogSubmitComplaint(catalogParamId.value, complaintType.value, reason, {
      pkg_id: item.value.pkg_id,
      item_name: item.value.name,
      material_category: item.value.material_category,
    })
    complaintReason.value = ''
    item.value = (await api.catalogDetail(catalogParamId.value)) as CatalogItemDetail
    alert('已提交，建议继续进入 AI 客服补充证据材料。')
  } catch (e) {
    alert((e as Error)?.message || String(e))
  } finally {
    complaintSubmitting.value = false
  }
}

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

async function doBuy() {
  if (!localStorage.getItem('modstore_token')) {
    await router.push({
      name: 'login',
      query: { redirect: `/catalog/${catalogParamId.value}` },
    })
    return
  }
  const it = item.value
  if (!it) return

  if (it.price <= 0) {
    buying.value = true
    try {
      const res = await api.buyItem(catalogParamId.value)
      alert(res.message)
      item.value = (await api.catalogDetail(catalogParamId.value)) as CatalogItemDetail
      if (item.value.artifact === 'employee_pack' && item.value.purchased) {
        await loadEmployeeStatus()
      }
    } catch (e) {
      alert((e as Error)?.message || String(e))
    } finally {
      buying.value = false
    }
    return
  }

  buying.value = true
  try {
    const res = await api.paymentCheckout({
      item_id: Number(it.id),
      subject: it.name,
    })
    if (!res.ok) {
      alert(res.message || '下单失败')
      return
    }
    if (res.type === 'page' || res.type === 'wap') {
      window.location.href = res.redirect_url || ''
    } else if (res.type === 'precreate' || res.type === 'wechat_native') {
      await router.push({ name: 'checkout', params: { orderId: res.order_id } })
    } else {
      alert('未知的支付类型')
    }
  } catch (e) {
    alert((e as Error)?.message || String(e))
  } finally {
    buying.value = false
  }
}

async function doDownload() {
  try {
    await api.downloadItem(catalogParamId.value)
  } catch (e) {
    alert((e as Error)?.message || String(e))
  }
}

async function delistItem() {
  const it = item.value
  if (!it || delisting.value) return
  const ok = window.confirm(`确定下架「${it.name}」吗？下架后市场将不再展示该商品。`)
  if (!ok) return
  delisting.value = true
  try {
    await api.adminDeleteCatalog(it.id)
    await router.push({ name: 'ai-store' })
  } catch (e) {
    alert((e as Error)?.message || String(e))
  } finally {
    delisting.value = false
  }
}

function navigateToWorkflow() {
  router.push('/workflow')
}
</script>

<style scoped>
.catalog-detail {
  width: 100%;
  max-width: var(--layout-max);
  margin: 0 auto;
  padding: var(--page-pad-y) var(--layout-pad-x);
  box-sizing: border-box;
}

.detail-main-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 20px;
  margin-bottom: 1.5rem;
}

@media (max-width: 860px) {
  .detail-main-grid {
    grid-template-columns: 1fr;
  }
}

.detail-panel {
  padding: 16px 18px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 0.5px solid rgba(255, 255, 255, 0.1);
}

.spec-runtime {
  margin-bottom: 12px;
  font-size: 13px;
}

.spec-runtime code {
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.06);
  color: #c4b5fd;
}

.spec-label,
.spec-mini-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
}

.spec-subtitle {
  font-size: 13px;
  margin: 0 0 8px;
  color: rgba(255, 255, 255, 0.7);
}

.spec-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.spec-mini-card {
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 0.5px solid rgba(255, 255, 255, 0.08);
  font-size: 13px;
}

.spec-mini-card .spec-mini-label {
  display: block;
  margin-bottom: 4px;
}

.quality-placeholder {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 8px 0;
}

.quality-placeholder p {
  margin: 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
  line-height: 1.5;
}

.quality-placeholder-actions,
.quality-action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quality-meta--source {
  width: 100%;
  color: rgba(192, 132, 252, 0.85);
}

.quality-llm-summary {
  width: 100%;
  color: rgba(255, 255, 255, 0.55);
  line-height: 1.45;
}

.quality-errors {
  margin-bottom: 12px;
  font-size: 12px;
}

.quality-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}

.quality-meta {
  margin: 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.4);
}

.detail-fold {
  margin-bottom: 1.25rem;
  padding: 12px 16px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 0.5px solid rgba(255, 255, 255, 0.08);
}

.detail-fold-summary {
  cursor: pointer;
  font-weight: 600;
  font-size: 15px;
  color: rgba(255, 255, 255, 0.88);
  list-style: none;
}

.detail-fold-summary::-webkit-details-marker {
  display: none;
}

.detail-fold .section-desc,
.detail-fold .complaint-form,
.detail-fold .desc--fold {
  margin-top: 12px;
}

.detail-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 1rem;
  padding: 18px 20px;
  border-radius: 14px;
  background: linear-gradient(120deg, rgba(59, 130, 246, 0.08) 0%, rgba(124, 58, 237, 0.06) 55%, rgba(255, 255, 255, 0.02) 100%);
  border: 0.5px solid rgba(255, 255, 255, 0.1);
}

.detail-hero__main {
  display: flex;
  gap: 16px;
  flex: 1;
  min-width: 0;
}

.detail-hero__avatar {
  flex-shrink: 0;
  width: 56px;
  height: 56px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  font-weight: 800;
  color: #bfdbfe;
  background: linear-gradient(145deg, rgba(59, 130, 246, 0.5), rgba(37, 99, 235, 0.25));
  border: 1px solid rgba(147, 197, 253, 0.35);
}

.detail-hero__body {
  flex: 1;
  min-width: 0;
}

.detail-hero__title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.detail-hero__title {
  margin: 0;
  font-size: 1.45rem;
  font-weight: 700;
  color: #fff;
  line-height: 1.25;
}

.detail-hero__grade {
  font-size: 0.75rem;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(45, 212, 191, 0.15);
  color: #5eead4;
  border: 0.5px solid rgba(45, 212, 191, 0.35);
}

.detail-hero__grade--s,
.detail-hero__grade--a {
  background: rgba(74, 222, 128, 0.15);
  color: #86efac;
  border-color: rgba(74, 222, 128, 0.35);
}

.detail-hero__grade--c,
.detail-hero__grade--d,
.detail-hero__grade--f,
.detail-hero__grade--g {
  background: rgba(248, 113, 113, 0.12);
  color: #fca5a5;
  border-color: rgba(248, 113, 113, 0.3);
}

.detail-hero__meta {
  margin: 6px 0 0;
  font-size: 0.82rem;
  color: rgba(255, 255, 255, 0.45);
  line-height: 1.45;
}

.detail-hero__pkg {
  font-family: ui-monospace, monospace;
  font-size: 0.8rem;
  color: rgba(196, 181, 253, 0.9);
  background: rgba(255, 255, 255, 0.05);
  padding: 2px 6px;
  border-radius: 4px;
}

.detail-hero__dot {
  margin: 0 4px;
  opacity: 0.5;
}

.detail-hero__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.detail-hero__cta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

.detail-hero__price {
  font-size: 1.35rem;
  font-weight: 800;
  color: #ff6b6b;
}

.detail-hero__price.free {
  color: #4ade80;
}

.detail-hero__buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.btn-cta-buy {
  min-width: 96px;
}

.quality-section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}

.quality-section-head .section-title {
  margin: 0;
}

.quality-section-score {
  margin: 0;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.55);
}

.quality-section-score strong {
  color: #c4b5fd;
  font-size: 1rem;
}

.quality-section-pipe {
  margin-left: 6px;
  font-size: 0.78rem;
  opacity: 0.75;
}

@media (max-width: 720px) {
  .detail-hero {
    flex-direction: column;
  }
  .detail-hero__cta {
    align-items: stretch;
    width: 100%;
  }
  .detail-hero__buttons {
    justify-content: stretch;
  }
  .detail-hero__buttons .btn {
    flex: 1;
  }
}

.desc {
  font-size: 14px;
  color: rgba(255,255,255,0.5);
  max-width: 600px;
  line-height: 1.5;
}

.compliance-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.info-chip {
  font-size: 12px;
  color: rgba(255,255,255,0.72);
  background: rgba(255,255,255,0.07);
  border: 0.5px solid rgba(255,255,255,0.12);
  border-radius: 999px;
  padding: 4px 10px;
}

.info-chip.warn {
  color: #fde68a;
  border-color: rgba(251,191,36,0.35);
  background: rgba(251,191,36,0.12);
}

.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  flex-shrink: 0;
}

.price-tag {
  font-size: 20px;
  font-weight: 700;
  color: #ff6b6b;
}

.price-tag.free {
  color: #4ade80;
}

.owned-badge {
  font-size: 14px;
  color: #4ade80;
  background: rgba(74,222,128,0.1);
  padding: 6px 14px;
  border-radius: 12px;
}

.complaint-panel {
  border-color: rgba(251, 191, 36, 0.22);
  background: rgba(251, 191, 36, 0.04);
  animation: complaint-slide-in 0.25s ease;
}

.complaint-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.complaint-panel__head .section-title {
  margin: 0;
}

.complaint-panel__close {
  flex-shrink: 0;
}

@keyframes complaint-slide-in {
  from {
    opacity: 0;
    transform: translateY(-6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.complaint-form {
  display: grid;
  gap: 10px;
  max-width: 720px;
}

.complaint-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.loading {
  text-align: center;
  padding: 40px;
  color: rgba(255,255,255,0.4);
}

.flash {
  padding: 10px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 14px;
}

.flash-err {
  background: rgba(255,80,80,0.1);
  color: #ff8a8a;
}

.btn {
  padding: 0.5rem 1rem;
  border: 0.5px solid rgba(255,255,255,0.15);
  border-radius: 6px;
  background: transparent;
  color: rgba(255,255,255,0.7);
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn:hover {
  background: rgba(255,255,255,0.06);
  color: #ffffff;
}

.btn-primary {
  background: #60a5fa;
  color: #0a0a0a;
  border: none;
}

.btn-primary:hover {
  background: #3b82f6;
  color: #0a0a0a;
}

.btn-primary-solid {
  background: #ffffff;
  color: #0a0a0a;
  border: none;
}

.btn-primary-solid:hover {
  opacity: 0.9;
  color: #0a0a0a;
}

.btn-success {
  background: rgba(74,222,128,0.1);
  color: #4ade80;
  border-color: rgba(74,222,128,0.3);
}

.btn-success:hover {
  background: rgba(74,222,128,0.2);
  color: #4ade80;
}

.btn-danger {
  color: #fca5a5;
  border-color: rgba(248, 113, 113, 0.35);
  background: rgba(127, 29, 29, 0.18);
}

.btn-danger:hover {
  color: #fecaca;
  background: rgba(127, 29, 29, 0.28);
}

.btn-fav {
  border-color: rgba(250, 204, 21, 0.35);
  color: rgba(250, 204, 21, 0.9);
}

.btn-fav--on {
  background: rgba(250, 204, 21, 0.12);
  border-color: rgba(250, 204, 21, 0.5);
}

.reviews-section .reviews-summary {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.45);
  margin: 0 0 12px;
}

.review-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.review-item {
  padding: 12px 0;
  border-bottom: 0.5px solid rgba(255, 255, 255, 0.08);
}

.review-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.85);
}

.review-stars {
  color: #fbbf24;
  letter-spacing: 1px;
}

.review-date {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.35);
}

.review-body {
  margin: 8px 0 0;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.55);
  line-height: 1.5;
}

.review-form {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 0.5px solid rgba(255, 255, 255, 0.1);
}

.review-form-title {
  font-size: 15px;
  margin: 0 0 10px;
  color: #fff;
}

.review-form .label {
  display: block;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
  margin: 8px 0 4px;
}

.review-form .input {
  width: 100%;
  max-width: 420px;
  box-sizing: border-box;
  padding: 8px 10px;
  border-radius: 6px;
  border: 0.5px solid rgba(255, 255, 255, 0.12);
  background: #111;
  color: #fff;
  font-size: 14px;
}

.review-form .textarea {
  resize: vertical;
  min-height: 72px;
}

.review-form .btn-primary-solid {
  margin-top: 12px;
}

.review-note {
  margin-top: 12px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.4);
}

.detail-section {
  margin-bottom: 2rem;
  padding-bottom: 1.5rem;
  border-bottom: 0.5px solid rgba(255,255,255,0.1);
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  color: #ffffff;
  margin-bottom: 1rem;
}

.section-desc {
  font-size: 14px;
  color: rgba(255,255,255,0.5);
  margin-bottom: 1rem;
}

.capabilities-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 15.625rem), 1fr));
  gap: 1rem;
}

.capability-card {
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 1.25rem;
}

.capability-card h3 {
  font-size: 14px;
  font-weight: 600;
  color: #ffffff;
  margin-bottom: 0.75rem;
}

.capability-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.capability-list li {
  font-size: 13px;
  color: rgba(255,255,255,0.5);
  margin-bottom: 0.5rem;
  position: relative;
  padding-left: 1.25rem;
}

.capability-list li::before {
  content: '•';
  position: absolute;
  left: 0;
  color: #60a5fa;
}

.cap-label {
  color: rgba(255,255,255,0.85);
  font-weight: 500;
}

.cap-desc {
  display: block;
  font-size: 12px;
  color: rgba(255,255,255,0.4);
  margin-top: 2px;
  padding-left: 0;
}

.capability-card--full {
  grid-column: 1 / -1;
}

.example-desc {
  font-size: 13px;
  color: rgba(255,255,255,0.45);
  margin: 0 0 0.75rem;
  line-height: 1.5;
}

.capability-card p {
  font-size: 13px;
  color: rgba(255,255,255,0.5);
  margin: 0;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 12.5rem), 1fr));
  gap: 1rem;
}

.status-item {
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.status-label {
  font-size: 12px;
  color: rgba(255,255,255,0.3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.status-value {
  font-size: 18px;
  font-weight: 600;
  color: #ffffff;
}

.workflow-config {
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.config-hint {
  font-size: 13px;
  color: rgba(255,255,255,0.4);
  margin: 0;
}

.example-card {
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 1.25rem;
  margin-bottom: 1rem;
}

.example-card h3 {
  font-size: 14px;
  font-weight: 600;
  color: #ffffff;
  margin-bottom: 0.75rem;
}

.example-code {
  background: rgba(0,0,0,0.3);
  border-radius: 8px;
  padding: 1rem;
  font-size: 13px;
  color: rgba(255,255,255,0.8);
  overflow-x: auto;
  margin: 0;
}

@media (max-width: 768px) {
  .detail-hero__main {
    flex-direction: column;
    align-items: flex-start;
  }
  
  .capabilities-grid,
  .status-grid {
    grid-template-columns: 1fr;
  }
}

html[data-workbench-theme='light'] .catalog-detail {
  background: #f5f5f7;
}

html[data-workbench-theme='light'] .detail-hero {
  background: linear-gradient(120deg, rgba(59, 130, 246, 0.06) 0%, #fff 100%);
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .detail-hero__title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .detail-hero__meta {
  color: #86868b;
}

html[data-workbench-theme='light'] .meta {
  color: #86868b;
}

html[data-workbench-theme='light'] .desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .info-chip {
  color: #1d1d1f;
  background: rgba(0,0,0,0.04);
  border-color: rgba(0,0,0,0.08);
}

html[data-workbench-theme='light'] .info-chip.warn {
  color: #92400e;
  border-color: rgba(180,130,20,0.25);
  background: rgba(251,191,36,0.1);
}

html[data-workbench-theme='light'] .price-tag {
  color: #e53e3e;
}

html[data-workbench-theme='light'] .price-tag.free {
  color: #16a34a;
}

html[data-workbench-theme='light'] .owned-badge {
  color: #16a34a;
  background: rgba(22,163,74,0.08);
}

html[data-workbench-theme='light'] .complaint-section {
  border-color: rgba(180,130,20,0.18);
  background: rgba(251,191,36,0.06);
}

html[data-workbench-theme='light'] .loading {
  color: #86868b;
}

html[data-workbench-theme='light'] .flash-err {
  background: rgba(220,50,50,0.06);
  color: #c53030;
}

html[data-workbench-theme='light'] .btn {
  border-color: rgba(0,0,0,0.1);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .btn:hover {
  background: rgba(0,0,0,0.04);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .btn-primary {
  background: #0071e3;
  color: #ffffff;
}

html[data-workbench-theme='light'] .btn-primary:hover {
  background: #005bb5;
  color: #ffffff;
}

html[data-workbench-theme='light'] .btn-primary-solid {
  background: #1d1d1f;
  color: #ffffff;
}

html[data-workbench-theme='light'] .btn-primary-solid:hover {
  opacity: 0.85;
  color: #ffffff;
}

html[data-workbench-theme='light'] .btn-success {
  background: rgba(22,163,74,0.08);
  color: #16a34a;
  border-color: rgba(22,163,74,0.2);
}

html[data-workbench-theme='light'] .btn-success:hover {
  background: rgba(22,163,74,0.14);
  color: #16a34a;
}

html[data-workbench-theme='light'] .btn-danger {
  color: #c53030;
  border-color: rgba(200,50,50,0.2);
  background: rgba(220,50,50,0.06);
}

html[data-workbench-theme='light'] .btn-danger:hover {
  color: #9b2c2c;
  background: rgba(220,50,50,0.1);
}

html[data-workbench-theme='light'] .btn-fav {
  border-color: rgba(180,130,20,0.25);
  color: #a16207;
}

html[data-workbench-theme='light'] .btn-fav--on {
  background: rgba(251,191,36,0.12);
  border-color: rgba(180,130,20,0.35);
}

html[data-workbench-theme='light'] .reviews-section .reviews-summary {
  color: #86868b;
}

html[data-workbench-theme='light'] .review-item {
  border-bottom-color: rgba(0,0,0,0.06);
}

html[data-workbench-theme='light'] .review-head {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .review-stars {
  color: #d97706;
}

html[data-workbench-theme='light'] .review-date {
  color: #86868b;
}

html[data-workbench-theme='light'] .review-body {
  color: #86868b;
}

html[data-workbench-theme='light'] .review-form {
  border-top-color: rgba(0,0,0,0.08);
}

html[data-workbench-theme='light'] .review-form-title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .review-form .label {
  color: #86868b;
}

html[data-workbench-theme='light'] .review-form .input {
  border-color: rgba(0,0,0,0.1);
  background: #ffffff;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .review-note {
  color: #86868b;
}

html[data-workbench-theme='light'] .detail-section {
  border-bottom-color: rgba(0,0,0,0.08);
}

html[data-workbench-theme='light'] .section-title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .section-desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .capability-card {
  background: #ffffff;
  border-color: rgba(0,0,0,0.06);
}

html[data-workbench-theme='light'] .capability-card h3 {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .capability-list li {
  color: #86868b;
}

html[data-workbench-theme='light'] .capability-list li::before {
  color: #0071e3;
}

html[data-workbench-theme='light'] .cap-label {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .cap-desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .example-desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .capability-card p {
  color: #86868b;
}

html[data-workbench-theme='light'] .status-item {
  background: #ffffff;
  border-color: rgba(0,0,0,0.06);
}

html[data-workbench-theme='light'] .status-label {
  color: #86868b;
}

html[data-workbench-theme='light'] .status-value {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .workflow-config {
  background: #ffffff;
  border-color: rgba(0,0,0,0.06);
}

html[data-workbench-theme='light'] .config-hint {
  color: #86868b;
}

html[data-workbench-theme='light'] .example-card {
  background: #ffffff;
  border-color: rgba(0,0,0,0.06);
}

html[data-workbench-theme='light'] .example-card h3 {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .example-code {
  background: rgba(0,0,0,0.04);
  color: #1d1d1f;
}
</style>
