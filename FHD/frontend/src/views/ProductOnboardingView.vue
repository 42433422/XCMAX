<template>
  <div class="product-flow">
    <div class="organic-glow organic-glow--moss" aria-hidden="true"></div>
    <div class="organic-glow organic-glow--sky" aria-hidden="true"></div>
    <div class="organic-grid" aria-hidden="true"></div>
    <div class="product-flow-card">
      <header class="product-flow-header">
        <div class="brand-lockup">
          <span class="brand-seed" aria-hidden="true"><span></span></span>
          <div class="product-flow-header-main">
            <div class="brand">{{ fromTutorial ? '重新认识您的数字公司' : '创建数字公司' }}</div>
            <p class="brand-lead">{{ currentStepMeta?.subtitle || '让 XC 从这里开始理解您的公司' }}</p>
          </div>
        </div>
        <div class="edition-tag"><span></span>{{ editionLabel }} · AI 引导</div>
      </header>

      <nav class="step-rail" aria-label="设置流程">
        <div
          v-for="step in steps"
          :key="step.id"
          class="step-rail-item"
          :class="{ active: step.id === currentStep, done: step.index < currentIndex }"
        >
          <span class="step-num">{{ step.index }}</span>
          <span class="step-label">{{ step.title }}</span>
        </div>
      </nav>

      <section class="step-panel">
        <template v-if="currentStep === 'welcome'">
          <div class="step-layout step-layout--company">
            <div class="step-copy">
              <span class="step-eyebrow">01 · COMPANY IDENTITY</span>
              <div class="welcome-hero">
                <img class="welcome-logo" :src="welcomeLogoSrc" height="56" alt="XC" decoding="async" @error="onWelcomeLogoError" />
                <div>
                  <h1>您的公司叫什么？</h1>
                  <p class="welcome-tagline">每一家数字公司，都从一个真实的名字开始。</p>
                </div>
              </div>
              <p class="lead company-lead">XC 会用这个名称生成工作空间、欢迎语和行业配置，以后可以随时修改。</p>
              <label class="company-field">
                <span>公司或团队名称</span>
                <div class="company-input-shell" :class="{ active: companyName.trim() }">
                  <input
                    v-model="companyName"
                    class="company-name-input"
                    type="text"
                    maxlength="80"
                    autocomplete="organization"
                    placeholder="例如：成都修茈科技有限公司"
                    @keydown.enter.prevent="confirmCompanyAndNext"
                  />
                  <i class="fa fa-arrow-right" aria-hidden="true"></i>
                </div>
              </label>
              <p v-if="trialStatusText" class="trial-status" role="status">{{ trialStatusText }}</p>
              <div class="actions">
                <button type="button" class="btn primary" :disabled="!canContinueCompany || companySaving" @click="confirmCompanyAndNext">
                  <span>{{ companySaving ? '正在认识您的公司…' : '让 XC 认识我的公司' }}</span>
                  <i class="fa" :class="companySaving ? 'fa-circle-o-notch fa-spin' : 'fa-long-arrow-right'" aria-hidden="true"></i>
                </button>
              </div>
            </div>
            <div class="identity-garden" aria-label="数字公司身份预览">
              <span class="garden-orbit garden-orbit--one"></span>
              <span class="garden-orbit garden-orbit--two"></span>
              <span class="garden-node garden-node--chat"><i class="fa fa-commenting-o"></i>智能对话</span>
              <span class="garden-node garden-node--data"><i class="fa fa-database"></i>企业数据</span>
              <span class="garden-node garden-node--people"><i class="fa fa-users"></i>AI 员工</span>
              <div class="company-seed" :class="{ awake: companyName.trim() }">
                <span class="company-seed-pulse"></span>
                <strong>{{ companyInitial }}</strong>
                <small>{{ companyDisplayName }}</small>
              </div>
              <p>名称正在成为工作空间的第一条记忆</p>
            </div>
          </div>
        </template>

        <template v-else-if="currentStep === 'industry'">
          <div class="industry-stage">
            <div class="industry-heading">
              <div>
                <span class="step-eyebrow">02 · INDUSTRY SIGNAL</span>
                <h1>{{ companyDisplayName }}属于什么行业？</h1>
                <p class="lead">选择最接近的方向。XC 会理解行业，而不是用行业限制您的公司。</p>
              </div>
              <div class="company-memory"><span>{{ companyInitial }}</span><strong>{{ companyDisplayName }}</strong><small>已记住</small></div>
            </div>
            <label class="industry-search">
              <i class="fa fa-search" aria-hidden="true"></i>
              <input v-model="industryQuery" type="search" placeholder="搜索行业，例如：制造、软件、建筑、医疗…" />
              <span v-if="industryQuery" role="button" tabindex="0" @click="industryQuery = ''" @keydown.enter="industryQuery = ''">清除</span>
            </label>
            <nav v-if="!industryQuery.trim()" class="industry-category-rail" aria-label="行业分类">
              <button
                v-for="category in industryCategoryFilters"
                :key="category.id"
                type="button"
                :class="{ active: selectedIndustryCategory === category.id }"
                @click="selectedIndustryCategory = category.id"
              >
                <i class="fa" :class="category.icon" aria-hidden="true"></i>
                <span>{{ category.label }}</span>
                <small>{{ industryCategoryCount(category.id) }}</small>
              </button>
            </nav>
            <p class="industry-open-hint">
              <span>{{ industryVisibleSummary }}</span>
              <small>覆盖 {{ industryExperienceOptions.length }} 个行业方向</small>
            </p>
            <div class="industry-pick industry-pick--open" role="listbox" aria-label="可选行业">
              <button
                v-for="preset in displayedIndustryOptions"
                :key="preset.id"
                type="button"
                class="industry-chip"
                :class="{ active: pickedIndustryId === preset.id }"
                role="option"
                :aria-selected="pickedIndustryId === preset.id"
                @click="pickIndustry(preset.id)"
              >
                <span class="industry-chip-icon"><i class="fa" :class="industryIcon(preset.id)" aria-hidden="true"></i></span>
                <span class="industry-chip-copy">
                  <span class="industry-chip-name">{{ preset.name }}</span>
                  <span class="industry-chip-scenario">{{ chipScenarioText(preset.scenario) }}</span>
                </span>
                <span class="industry-chip-state">{{ industryAvailabilityLabel(preset.id) }}</span>
              </button>
            </div>
            <button v-if="industryRemainingCount > 0" type="button" class="industry-more-button" @click="industryExpanded = true">
              查看另外 {{ industryRemainingCount }} 个行业
              <i class="fa fa-angle-down" aria-hidden="true"></i>
            </button>
            <div v-if="!filteredIndustryOptions.length" class="industry-loading-hint">
              <span>没有完全匹配的选项，XC 仍然可以理解您填写的行业。</span>
            </div>
            <button
              v-if="showCustomIndustryAction"
              type="button"
              class="custom-industry-option custom-industry-option--standalone"
              @click="useCustomIndustry"
            >
              <i class="fa fa-plus-circle" aria-hidden="true"></i>
              没有合适的？将“{{ industryQuery.trim() }}”作为我的行业
            </button>
            <div v-if="pickedIndustryId" class="ai-understanding-card">
              <span class="ai-understanding-icon"><i class="fa fa-leaf"></i></span>
              <div>
                <small>XC 已理解</small>
                <strong>{{ pickedIndustryName }}</strong>
                <p>{{ industryUnderstandingText }}</p>
              </div>
            </div>
            <div class="actions">
              <button type="button" class="btn primary" :disabled="!canConfirmIndustry || loading" @click="confirmIndustryAndNext">
                <span>{{ loading ? '正在理解行业…' : '生成我的配置方案' }}</span>
                <i class="fa" :class="loading ? 'fa-circle-o-notch fa-spin' : 'fa-magic'" aria-hidden="true"></i>
              </button>
              <button type="button" class="btn link" @click="goStep('welcome')">返回修改公司名称</button>
            </div>
          </div>
        </template>

        <template v-else-if="currentStep === 'host-pack'">
          <div class="configuration-stage">
            <div class="configuration-heading">
              <span class="step-eyebrow">03 · AI WORKSPACE</span>
              <h1>为{{ companyDisplayName }}生成专属工作空间</h1>
              <p class="lead">XC 根据“{{ pickedIndustryName }}”方向准备了一套轻量起步方案。基础能力现在启用，更多能力以后随公司一起生长。</p>
            </div>
            <div class="configuration-grid">
              <div class="capability-map" aria-label="AI 工作空间能力图">
                <span class="map-ring map-ring--outer"></span>
                <span class="map-ring map-ring--inner"></span>
                <div class="map-core"><span>{{ companyInitial }}</span><strong>{{ companyDisplayName }}</strong><small>{{ pickedIndustryName }}工作空间</small></div>
                <span v-for="(capability, index) in capabilityOrbit" :key="capability.label" class="map-node" :class="`map-node--${index + 1}`">
                  <i class="fa" :class="capability.icon"></i>{{ capability.label }}
                </span>
              </div>
              <div class="configuration-panel">
                <div class="ai-config-title">
                  <span class="ai-config-signal"><span></span></span>
                  <div><small>XC AI CONFIGURATION</small><strong>建议从这些能力开始</strong></div>
                </div>
                <div class="capability-section">
                  <div class="capability-section-title"><span>基础能力</span><small>默认开启</small></div>
                  <div class="capability-list">
                    <span v-for="item in baseCapabilities" :key="item.label"><i class="fa" :class="item.icon"></i>{{ item.label }}<b>已选择</b></span>
                  </div>
                </div>
                <div class="capability-section capability-section--industry">
                  <div class="capability-section-title"><span>可用行业侧栏</span><small>真实页面</small></div>
                  <div class="sidebar-preview-list">
                    <span v-for="label in industrySidebarPreviewLabels.slice(0, 7)" :key="label" class="sidebar-preview-chip">{{ label }}</span>
                  </div>
                  <p class="capability-integrity-note">
                    <i class="fa fa-check-circle" aria-hidden="true"></i>
                    以上入口均有可用页面
                    <template v-if="industryDeferredCapabilities.length">
                      <span>暂不显示：{{ industryDeferredCapabilities.slice(0, 3).join('、') }}（尚无对应业务页）</span>
                    </template>
                  </p>
                </div>
                <div class="status-card" :class="{ ok: baselineOk && !loading, warn: !baselineOk && !loading }">
                  <template v-if="loading"><i class="fa fa-circle-o-notch fa-spin"></i><span>AI 正在核对可用能力…</span></template>
                  <template v-else-if="baselineOk"><i class="fa fa-check"></i><span>基础能力已就绪，可以进入工作空间。</span></template>
                  <template v-else><i class="fa fa-magic"></i><span>方案已生成，创建时会自动准备 {{ missingSidebarBaselineCount || missingRequiredCount || 1 }} 项能力。</span></template>
                </div>
              </div>
            </div>
            <div class="actions configuration-actions">
              <button type="button" class="btn primary" :disabled="bootstrapBusy || loading || finishing" @click="createWorkspace">
                <span>{{ workspacePrimaryLabel }}</span>
                <i class="fa" :class="workspacePrimaryIcon" aria-hidden="true"></i>
              </button>
              <button type="button" class="btn link" :disabled="finishing" @click="finishToChat">先进入，以后再完善</button>
              <button type="button" class="btn link" :disabled="bootstrapBusy || finishing" @click="goStep('industry')">返回修改行业</button>
            </div>
            <p v-if="bootstrapBusy || finishing" class="finish-progress" role="status" aria-live="polite">{{ buildProgressText }}</p>
          </div>
          <details v-if="hostPackDetailGroups.length" class="host-pack-details">
            <summary>查看配置详情</summary>
            <p v-if="baselinePlan?.summary" class="lead muted">{{ baselinePlan.summary }}</p>
            <p v-if="showNoAccountCustomHint" class="account-custom-empty-hint muted">
              当前先使用通用能力；专属 AI 员工可以稍后继续添加。
            </p>
            <p v-else-if="missingAccountCustomCount > 0 || missingIndustryPackageCount > 0" class="muted host-pack-details-note">
              <template v-if="missingAccountCustomCount > 0"> 另有 {{ missingAccountCustomCount }} 项定制/员工可稍后安装 </template>
              <template v-if="missingAccountCustomCount > 0 && missingIndustryPackageCount > 0">；</template>
              <template v-if="missingIndustryPackageCount > 0"> 另有 {{ missingIndustryPackageCount }} 项行业包可选 </template>
            </p>
            <div class="baseline-groups">
              <section v-for="group in hostPackDetailGroups" :key="group.id" class="baseline-group">
                <h3>{{ group.title }}</h3>
                <ul class="baseline-list">
                  <li
                    v-for="item in group.items"
                    :key="item.mod_id"
                    :class="{
                      ok: item.installed,
                      warn: !item.installed && item.required,
                      optional: !item.required && !item.installed,
                    }"
                  >
                    <i
                      class="fa"
                      :class="item.installed ? 'fa-check-circle' : item.required ? 'fa-exclamation-circle' : 'fa-circle-o'"
                      aria-hidden="true"
                    ></i>
                    <span>{{ item.label }}</span>
                  </li>
                </ul>
              </section>
            </div>
            <div class="actions host-pack-details-actions">
              <button type="button" class="btn ghost" :disabled="loading" @click="refreshStatus">重新核对</button>
            </div>
          </details>
        </template>

        <template v-else-if="currentStep === 'done'">
          <h1>可以开始使用</h1>
          <p class="lead">可从智能对话或扩展市场开始。</p>
          <div class="actions">
            <button type="button" class="btn primary" @click="finishToChat">进入智能对话</button>
          </div>
        </template>
      </section>

      <footer class="product-flow-footer">
        <button v-if="fromTutorial" type="button" class="btn text" @click="returnFromTutorial">返回上一页</button>
        <button v-else type="button" class="btn text" @click="skipEntireFlow">稍后设置</button>
        <span class="doc-hint">{{ footerHint }}</span>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { installHostFoundation, installMod, installIndustrySeed, installCustomerDeliverySeed } from '@/api/modStore'
import { autoOnboardWorkflowEmployeesFromMods } from '@/utils/workflowEmployeeOnboard'
import { deliverySeedModIds } from '@/utils/deliverySeedPackages'
import { queueWorkspacePrefsSync } from '@/utils/workspacePrefsApi'
import { useModsStore } from '@/stores/mods'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { readBuildEdition } from '@/constants/genericModPack'
import { fetchProductSku, isEnterpriseEdition } from '@/utils/productSku'
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults'
import { getIndustryPreset, listIndustryPresets } from '@/constants/industryPresets'
import {
  listOnboardingIndustryOptions,
  ONBOARDING_INDUSTRY_CATEGORIES,
} from '@/constants/onboardingIndustryCatalog'
import { resolveIndustryNavigationProfile } from '@/constants/industryNavigationProfiles'
import {
  PRODUCT_FLOW_STEPS,
  defaultOnboardingIndustryId,
  isOnboardingIndustryOpen,
  isTutorialReplayQuery,
  parseFlowStepQuery,
  readOnboardingReturnPath,
  readProductFlowCompleted,
  saveProductFlowLastStep,
  setRuntimeOnboardingOpenIndustryIds,
} from '@/constants/productFlow'
import { useProductFlow } from '@/composables/useProductFlow'
import { useIndustryStore } from '@/stores/industry'
import { authApi } from '@/api/auth'
import { clearDeliverableStatusCache, fetchIndustryBaseline, fetchOnboardingIndustryCatalog } from '@/utils/platformShellApi'
import { invalidateHostPackCompletionCache, markHostPackSkippedThisSession } from '@/utils/hostPackOnboardingGate'
import { resolveCoreNavLabel } from '@/utils/coreNavLabel'
import { patchWorkspacePrefs } from '@/utils/workspacePrefsApi'
import { appAlert } from '@/utils/appDialog'
import { productErrorMessage } from '@/utils/productErrorMessage'
import { readTenantScopedStorageItem, writeTenantScopedStorageItem } from '@/utils/tenantStorageScope'
const route = useRoute()
const router = useRouter()
const flow = useProductFlow()
const industryStore = useIndustryStore()
const accountProfileStore = useAccountProfileStore()
const industryOptions = listIndustryPresets()
const onboardingIndustryOptions = listOnboardingIndustryOptions()
const LS_ONBOARDING_COMPANY_NAME = 'xcagi_onboarding_company_name'
const companyName = ref('')
const companySaving = ref(false)
const industryQuery = ref('')
const selectedIndustryCategory = ref('popular')
const industryExpanded = ref(false)
const customIndustryOption = ref(null)
const onboardingCatalog = ref(null)
const onboardingCatalogLoaded = ref(false)
function catalogChipRow(pkg) {
  const id = String(pkg?.industry_id || '').trim()
  return {
    id,
    name: String(pkg?.name || getIndustryPreset(id)?.name || id).trim(),
    scenario: String(pkg?.scenario || getIndustryPreset(id)?.scenario || '').trim(),
    productName: String(pkg?.product_name || '').trim(),
  }
}
const openIndustryOptions = computed(() => {
  const catalog = onboardingCatalog.value
  if (catalog) {
    return (catalog.open_packages || []).map(catalogChipRow)
  }
  if (isEnterpriseEdition(productSku.value)) return []
  return industryOptions
    .filter((p) => isOnboardingIndustryOpen(p.id))
    .map((p) => ({ id: p.id, name: p.name, scenario: p.scenario, productName: '' }))
})
const previewIndustryOptions = computed(() => {
  const previewPkgs = onboardingCatalog.value?.preview_packages
  if (Array.isArray(previewPkgs) && previewPkgs.length) {
    return previewPkgs.map(catalogChipRow)
  }
  if (isEnterpriseEdition(productSku.value) && !onboardingCatalogLoaded.value) return []
  return industryOptions
    .filter((p) => !isOnboardingIndustryOpen(p.id))
    .map((p) => ({ id: p.id, name: p.name, scenario: p.scenario, productName: '' }))
})
const industryExperienceOptions = computed(() => {
  const byId = new Map()
  for (const option of onboardingIndustryOptions) {
    byId.set(option.id, { ...option, productName: '' })
  }
  for (const preset of industryOptions) {
    if (preset.id !== '管理端') {
      const existing = byId.get(preset.id)
      byId.set(preset.id, {
        ...existing,
        id: preset.id,
        name: existing?.name || preset.name,
        scenario: existing?.scenario || preset.scenario,
        productName: '',
        categoryId: existing?.categoryId || 'business-services',
        aliases: existing?.aliases || [],
        popular: Boolean(existing?.popular || preset.id === '考勤'),
      })
    }
  }
  for (const preset of [...openIndustryOptions.value, ...previewIndustryOptions.value]) {
    if (preset.id && preset.id !== '管理端') {
      const existing = byId.get(preset.id)
      byId.set(preset.id, {
        ...existing,
        ...preset,
        categoryId: existing?.categoryId || 'business-services',
        aliases: existing?.aliases || [],
        popular: Boolean(existing?.popular || onboardingCatalog.value?.open_industry_ids?.includes(preset.id)),
      })
    }
  }
  if (customIndustryOption.value?.id) {
    byId.set(customIndustryOption.value.id, customIndustryOption.value)
  }
  return [...byId.values()]
})
const filteredIndustryOptions = computed(() => {
  const query = String(industryQuery.value || '')
    .trim()
    .toLowerCase()
  if (!query) {
    if (selectedIndustryCategory.value === 'all') return industryExperienceOptions.value
    if (selectedIndustryCategory.value === 'popular') {
      return industryExperienceOptions.value.filter((preset) => preset.popular || preset.id === pickedIndustryId.value)
    }
    return industryExperienceOptions.value.filter((preset) => preset.categoryId === selectedIndustryCategory.value)
  }
  return industryExperienceOptions.value.filter((preset) =>
    [preset.id, preset.name, preset.scenario, preset.productName, ...(preset.aliases || [])].some((value) =>
      String(value || '')
        .toLowerCase()
        .includes(query),
    ),
  )
})
const INDUSTRY_VISIBLE_LIMIT = 10
const displayedIndustryOptions = computed(() => {
  const options = filteredIndustryOptions.value
  if (industryExpanded.value || industryQuery.value.trim()) return options
  const visible = options.slice(0, INDUSTRY_VISIBLE_LIMIT)
  const selected = options.find((preset) => preset.id === pickedIndustryId.value)
  if (selected && !visible.some((preset) => preset.id === selected.id)) {
    return [selected, ...visible].slice(0, INDUSTRY_VISIBLE_LIMIT)
  }
  return visible
})
const industryRemainingCount = computed(() => Math.max(0, filteredIndustryOptions.value.length - displayedIndustryOptions.value.length))
const industryCategoryFilters = [
  { id: 'popular', label: '常用', icon: 'fa-star-o' },
  ...ONBOARDING_INDUSTRY_CATEGORIES,
  { id: 'all', label: '全部', icon: 'fa-th-large' },
]
const industryVisibleSummary = computed(() => {
  const query = industryQuery.value.trim()
  if (query) return `找到 ${filteredIndustryOptions.value.length} 个相关方向`
  const category = industryCategoryFilters.find((item) => item.id === selectedIndustryCategory.value)
  return `${category?.label || '行业'} · 选择最接近的主要方向`
})
const showCustomIndustryAction = computed(() => {
  const query = industryQuery.value.trim().toLowerCase()
  if (!query) return false
  return !industryExperienceOptions.value.some((preset) =>
    [preset.id, preset.name, ...(preset.aliases || [])].some((value) => String(value || '').trim().toLowerCase() === query),
  )
})
function industryCategoryCount(categoryId) {
  if (categoryId === 'all') return industryExperienceOptions.value.length
  if (categoryId === 'popular') {
    return industryExperienceOptions.value.filter((preset) => preset.popular || preset.id === pickedIndustryId.value).length
  }
  return industryExperienceOptions.value.filter((preset) => preset.categoryId === categoryId).length
}
watch([selectedIndustryCategory, industryQuery], () => {
  industryExpanded.value = false
})
const pickedIndustryId = ref(resolveDefaultPickedIndustryId())
const canConfirmIndustry = computed(() => industryExperienceOptions.value.length > 0 && isIndustrySelectable(pickedIndustryId.value))
function industryPackageModId(industryId) {
  const id = String(industryId || '').trim()
  const row = onboardingCatalog.value?.open_packages?.find((p) => p.industry_id === id)
  return String(row?.mod_id || '').trim()
}

/** 行业 chip 第三行：去掉句末句号，避免行高不齐 */
function chipScenarioText(text) {
  return String(text || '').replace(/[。．]$/, '')
}

function isIndustrySelectable(id) {
  const key = String(id || '').trim()
  if (!key) return false
  return industryExperienceOptions.value.some((preset) => preset.id === key) || isOnboardingIndustryOpen(key)
}

function resolveDefaultPickedIndustryId() {
  const selected = String(onboardingCatalog.value?.selected_industry_id || '').trim()
  if (selected && (industryOptions.some((preset) => preset.id === selected) || isOnboardingIndustryOpen(selected))) return selected
  const openIds = onboardingCatalog.value?.open_industry_ids
  if (Array.isArray(openIds) && openIds.length) return openIds[0]
  return defaultOnboardingIndustryId()
}

function normalizePickedIndustryId(raw) {
  const id = String(raw || '').trim()
  if (isIndustrySelectable(id)) return id
  return resolveDefaultPickedIndustryId()
}

const steps = PRODUCT_FLOW_STEPS.filter((s) => s.id !== 'done')
const currentStep = ref(parseFlowStepQuery(route.query.step))
const loading = ref(false)
const bootstrapBusy = ref(false)
const finishing = ref(false)
const baselinePlan = ref(null)

const canContinueCompany = computed(() => companyName.value.trim().length >= 1)
const companyDisplayName = computed(() => companyName.value.trim() || '您的公司')
const companyInitial = computed(() => {
  const text = companyDisplayName.value.replace(/[（(].*$/, '').trim()
  return text === '您的公司' ? 'XC' : text.slice(0, 2).toUpperCase()
})

const BASE_CAPABILITIES = [
  { label: '智能对话', icon: 'fa-commenting-o' },
  { label: '企业知识', icon: 'fa-book' },
  { label: '数据对接', icon: 'fa-exchange' },
  { label: '员工空间', icon: 'fa-users' },
]
const baseCapabilities = BASE_CAPABILITIES
const capabilityOrbit = computed(() => {
  const industry = industrySidebarPreviewLabels.value.slice(0, 2).map((label, index) => ({
    label,
    icon: index === 0 ? 'fa-cubes' : 'fa-file-text-o',
  }))
  return [...BASE_CAPABILITIES.slice(0, 2), ...industry].slice(0, 4)
})

const INDUSTRY_ICONS = {
  通用: 'fa-compass',
  涂料: 'fa-tint',
  考勤: 'fa-calendar-check-o',
  批发: 'fa-truck',
  电商: 'fa-shopping-bag',
  餐饮: 'fa-cutlery',
  物流: 'fa-map-signs',
}

const INDUSTRY_CATEGORY_ICONS = Object.fromEntries(ONBOARDING_INDUSTRY_CATEGORIES.map((category) => [category.id, category.icon]))

function industryIcon(id) {
  const key = String(id || '').trim()
  const categoryId = industryExperienceOptions.value.find((preset) => preset.id === key)?.categoryId
  return INDUSTRY_ICONS[key] || INDUSTRY_CATEGORY_ICONS[categoryId] || 'fa-compass'
}

function industryAvailabilityLabel(id) {
  const key = String(id || '').trim()
  const openIds = onboardingCatalog.value?.open_industry_ids
  if (!Array.isArray(openIds) || openIds.includes(key)) return '专属方案'
  return '通用能力可用'
}

const industryUnderstandingText = computed(() => {
  const labels = industrySidebarPreviewLabels.value.slice(0, 3)
  return labels.length ? `建议优先准备${labels.join('、')}，进入后仍可自由调整。` : '先从通用能力开始，进入后再按实际业务继续生长。'
})

const workspacePrimaryLabel = computed(() => {
  if (finishing.value) return '正在进入工作空间…'
  if (bootstrapBusy.value) return `正在创建${companyDisplayName.value}…`
  if (baselineOk.value) return `进入${companyDisplayName.value}`
  return `创建${companyDisplayName.value}工作空间`
})
const workspacePrimaryIcon = computed(() => {
  if (bootstrapBusy.value || finishing.value) return 'fa-circle-o-notch fa-spin'
  return baselineOk.value ? 'fa-long-arrow-right' : 'fa-magic'
})
const buildProgressText = computed(() =>
  finishing.value ? '工作空间已经准备好，正在打开智能对话…' : 'XC 正在连接基础能力、行业工作区与 AI 员工…',
)

function startupAsset(fileName) {
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

function initialProductSku() {
  return (
    String(import.meta.env.VITE_XCAGI_PRODUCT_SKU || 'generic')
      .trim()
      .toLowerCase() || 'generic'
  )
}

const productSku = ref(initialProductSku())
const subscription = ref(null)
const trialStatusText = computed(() => {
  const sub = subscription.value
  if (!sub || sub.reason !== 'trial') return ''
  const days = sub.trial_days_remaining ?? '—'
  return `当前为试用账户 · 剩余 ${days} 天${sub.trial_expires_at ? ` · 有效期至 ${sub.trial_expires_at}` : ''}`
})
const baselineOk = computed(() => baselinePlan.value?.baseline_ready === true)
const industryNavigationProfile = computed(() => resolveIndustryNavigationProfile(String(pickedIndustryId.value || '').trim()))
const industrySidebarPreviewLabels = computed(() => {
  const id = String(pickedIndustryId.value || '').trim()
  const labels = industryNavigationProfile.value.previewMenuKeys.map((key) => resolveCoreNavLabel(key, id, null)).filter(Boolean)
  return [...new Set(labels)]
})
const industryDeferredCapabilities = computed(() => industryNavigationProfile.value.deferredCapabilities)
const baselineGroups = computed(() => baselinePlan.value?.groups || [])
const SIDEBAR_BASELINE_GROUP_IDS = new Set(['core', 'host'])
const sidebarBaselineGroups = computed(() => baselineGroups.value.filter((g) => SIDEBAR_BASELINE_GROUP_IDS.has(String(g?.id || ''))))
const supplementBaselineGroups = computed(() => baselineGroups.value.filter((g) => !SIDEBAR_BASELINE_GROUP_IDS.has(String(g?.id || ''))))
/** 明细折叠区：优先侧栏+补充分组，否则回退全部 groups */
const hostPackDetailGroups = computed(() => {
  if (sidebarBaselineGroups.value.length) {
    return [...sidebarBaselineGroups.value, ...supplementBaselineGroups.value]
  }
  return baselineGroups.value
})
const missingSidebarBaselineCount = computed(() => {
  const ids = new Set()
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
const pickedIndustryName = computed(
  () => industryExperienceOptions.value.find((preset) => preset.id === pickedIndustryId.value)?.name || getIndustryPreset(pickedIndustryId.value).name,
)

const currentIndex = computed(() => {
  const row = steps.find((s) => s.id === currentStep.value)
  return row?.index ?? 1
})

const currentStepMeta = computed(() => steps.find((s) => s.id === currentStep.value) || null)

const editionLabel = computed(() => {
  const sku = String(productSku.value || '')
    .trim()
    .toLowerCase()
  if (sku === 'enterprise') return '企业版'
  if (sku === 'personal') return '个人版'
  const e = readBuildEdition()
  if (e === 'minimal') return '轻量版'
  if (e === 'generic') return '通用版'
  return '完整体验'
})

const fromTutorial = computed(() => isTutorialReplayQuery(route.query.from))
const returnPath = computed(() => readOnboardingReturnPath(route.query.redirect))
const footerHint = computed(() =>
  fromTutorial.value ? '这次调整不会影响已有业务数据' : '信息仅用于生成工作空间，可随时在设置中修改',
)

function readRememberedCompanyName() {
  const accountName = String(accountProfileStore.tenantName || accountProfileStore.companyBrand || '').trim()
  if (accountName) return accountName
  try {
    return String(readTenantScopedStorageItem(LS_ONBOARDING_COMPANY_NAME) || '').trim()
  } catch {
    return ''
  }
}

function rememberCompanyName(value) {
  try {
    writeTenantScopedStorageItem(LS_ONBOARDING_COMPANY_NAME, value)
  } catch {
    /* private mode / quota */
  }
}

async function confirmCompanyAndNext() {
  const name = companyName.value.trim().replace(/\s+/g, ' ')
  if (!name || companySaving.value) return
  companyName.value = name
  companySaving.value = true
  rememberCompanyName(name)
  try {
    if (accountProfileStore.loaded && accountProfileStore.accountKind === 'enterprise' && accountProfileStore.companyBrand !== name) {
      const response = await authApi.updateCompanyBrand(name)
      if (response?.success !== false) {
        accountProfileStore.companyBrand = name
        accountProfileStore.tenantName = name
      }
    }
  } catch {
    /* 离线或账号只读时保留本机名称，不阻断体验 */
  } finally {
    companySaving.value = false
  }
  goStep('industry')
}

watch(
  () => route.query.step,
  (q) => {
    currentStep.value = parseFlowStepQuery(q)
  },
)

watch(currentStep, (step) => {
  saveProductFlowLastStep(step)
  if (step === 'host-pack') {
    void refreshStatus()
  }
})

watch(pickedIndustryId, () => {
  if (currentStep.value === 'host-pack') {
    clearDeliverableStatusCache()
    void refreshStatus()
  }
})

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
    const installErrors = []
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
      return true
    }

    const requiredMissing = baselinePlan.value?.missing_required_mod_ids || []
    const detailParts = []
    if (!res.success) {
      detailParts.push(res.message || '基础能力暂时没有准备完整')
    }
    if (requiredMissing.length) {
      detailParts.push(`仍缺必需项：${requiredMissing.join('、')}`)
    }
    if (installErrors.length) {
      detailParts.push(installErrors.join('；'))
    }
    await appAlert(detailParts.join('\n') || '部分项目未装齐，可稍后在扩展市场继续安装。')
    return false
  } catch (err) {
    await appAlert(productErrorMessage(err, '工作空间暂时没有准备完整，可以先进入后稍后重试'))
    return false
  } finally {
    bootstrapBusy.value = false
  }
}

async function createWorkspace() {
  if (bootstrapBusy.value || loading.value || finishing.value) return
  if (!baselineOk.value) {
    const ready = await runBootstrap()
    if (!ready) return
  }
  await finishOnboardingComplete()
}

function pickIndustry(id) {
  if (!isIndustrySelectable(id)) return
  pickedIndustryId.value = normalizePickedIndustryId(id)
}

function useCustomIndustry() {
  const name = industryQuery.value.trim().replace(/\s+/g, ' ')
  if (!name) return
  customIndustryOption.value = {
    id: name,
    name,
    scenario: '由您定义的行业方向',
    productName: '',
    categoryId: 'business-services',
    aliases: [],
    popular: true,
  }
  pickedIndustryId.value = name
  industryQuery.value = ''
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
  goStep('host-pack')
}

function goStep(id) {
  const query = { step: id }
  if (fromTutorial.value) {
    query.from = 'tutorial'
    query.redirect = returnPath.value
  }
  void router.replace({ name: 'product-onboarding', query })
}

function returnFromTutorial() {
  void router.replace(returnPath.value)
}

function finishHostPackFlow() {
  invalidateHostPackCompletionCache()
  if (baselineOk.value) {
    flow.markHostPackAcknowledged()
    if (!readProductFlowCompleted()) {
      flow.markProductFlowCompleted()
    }
    if (fromTutorial.value) {
      returnFromTutorial()
      return
    }
    flow.completeFlowAndGoChat(router)
    return
  }
  markHostPackSkippedThisSession()
  if (fromTutorial.value) {
    returnFromTutorial()
    return
  }
  void router.replace({ path: '/' })
}

function finishToChat() {
  finishHostPackFlow()
}

async function finishOnboardingComplete() {
  if (finishing.value) return
  finishing.value = true
  queueWorkspacePrefsSync({
    product_flow_completed: true,
    onboarding_completed_at: new Date().toISOString(),
  })
  flow.markProductFlowCompleted()
  flow.markHostPackAcknowledged()
  await nextTick()
  finishHostPackFlow()
}

function skipEntireFlow() {
  if (fromTutorial.value) {
    returnFromTutorial()
    return
  }
  if (baselineOk.value) {
    flow.markProductFlowCompleted()
    flow.markHostPackAcknowledged()
  } else {
    markHostPackSkippedThisSession()
  }
  finishToChat()
}

onMounted(async () => {
  companyName.value = readRememberedCompanyName()
  try {
    productSku.value = await fetchProductSku()
  } catch {
    /* ignore */
  }
  try {
    const subRes = await authApi.getSubscriptionStatus().catch(() => null)
    if (subRes?.data) subscription.value = subRes.data
  } catch {
    /* ignore */
  }
  try {
    onboardingCatalog.value = await fetchOnboardingIndustryCatalog()
    if (onboardingCatalog.value?.open_industry_ids?.length) {
      setRuntimeOnboardingOpenIndustryIds(onboardingCatalog.value.open_industry_ids)
    }
  } catch {
    /* 离线兜底：仅展示 preset 名称 */
  } finally {
    onboardingCatalogLoaded.value = true
  }
  currentStep.value = flow.resolveEntryStep(route.query.step)
  if (!industryStore.isLoaded) {
    try {
      await industryStore.initialize()
    } catch {
      /* ignore */
    }
  }
  const cur = String(industryStore.currentIndustryId || DEFAULT_INDUSTRY_ID).trim()
  pickedIndustryId.value = normalizePickedIndustryId(onboardingCatalog.value?.selected_industry_id || cur)
  const expectedQuery = { step: currentStep.value }
  if (fromTutorial.value) {
    expectedQuery.from = 'tutorial'
    expectedQuery.redirect = returnPath.value
  }
  const parsed = parseFlowStepQuery(route.query.step)
  if (currentStep.value !== parsed || (fromTutorial.value && route.query.from !== 'tutorial')) {
    void router.replace({ name: 'product-onboarding', query: expectedQuery })
  }
  void refreshStatus()
})
</script>

<style scoped>
.product-flow {
  box-sizing: border-box;
  width: 100%;
  min-height: 100dvh;
  padding: clamp(16px, 3vh, 32px) 16px;
  background:
    radial-gradient(circle at 50% 0%, rgba(37, 99, 235, 0.1), transparent 46%),
    linear-gradient(180deg, #eef2f7 0%, #f8fafc 55%, #f1f5f9 100%);
  color: #0f172a;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  overflow-y: auto;
}

.product-flow-card {
  width: min(100%, 720px);
  margin: 0 auto;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  box-shadow:
    0 20px 48px rgba(15, 23, 42, 0.08),
    0 2px 8px rgba(15, 23, 42, 0.04);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  max-height: calc(100dvh - clamp(32px, 6vh, 64px));
}

.product-flow-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 24px 24px 16px;
  border-bottom: 1px solid #f1f5f9;
}

.product-flow-header-main {
  min-width: 0;
}

.brand {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.01em;
  line-height: 1.3;
}

.brand-lead {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.5;
  color: #64748b;
}

.edition-tag {
  flex-shrink: 0;
  font-size: 12px;
  color: #64748b;
  padding: 4px 10px;
  border-radius: 999px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.step-rail {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 0 16px 16px;
  border-bottom: 1px solid #f1f5f9;
}

.step-rail-item {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 8px;
  border-radius: 10px;
  background: #f1f5f9;
  font-size: 13px;
  color: #64748b;
  text-align: center;
}

.step-rail-item.active {
  background: #2563eb;
  color: #fff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.24);
}

.step-rail-item.done {
  background: #ecfdf5;
  color: #047857;
}

.step-num {
  font-weight: 700;
}

.step-label {
  white-space: nowrap;
}

.step-panel {
  padding: 24px;
  min-height: 0;
  flex: 1 1 auto;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.step-panel h1 {
  margin: 0 0 10px;
  font-size: 22px;
  line-height: 1.3;
}

.step-panel .actions {
  margin-top: auto;
  padding-top: 20px;
}

.welcome-hero {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.welcome-logo {
  flex-shrink: 0;
  height: 56px;
  width: auto;
  max-width: 180px;
  object-fit: contain;
  display: block;
  user-select: none;
  -webkit-user-drag: none;
}

.lead {
  margin: 8px 0 0;
  line-height: 1.65;
  color: #475569;
  font-size: 15px;
}

.baseline-scope-note {
  margin-bottom: 4px;
  color: #334155;
}

.lead.muted {
  font-size: 14px;
  color: #64748b;
}

.pricing-anchor {
  margin-top: 12px;
  padding: 10px 14px;
  border-left: 3px solid #1d4ed8;
  background: #eff6ff;
  border-radius: 0 8px 8px 0;
}

.trial-status {
  margin-top: 8px;
  color: #059669;
}

.welcome-tagline {
  margin: 6px 0 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.45;
  color: #1d4ed8;
}

.flow-list strong {
  color: #0f172a;
}

.flow-list {
  margin: 0 0 20px 20px;
  padding: 0;
  line-height: 1.7;
  color: #334155;
}

.flow-list.bullets {
  list-style: disc;
}

.industry-pick {
  display: grid;
  gap: 10px;
  margin: 16px 0 4px;
}

.industry-pick--open {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.industry-pick--preview {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 0;
  pointer-events: none;
}

.industry-open-hint {
  margin: 12px 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.industry-preview-hint {
  margin: 16px 0 8px;
  font-size: 12px;
  color: #94a3b8;
}

.industry-loading-hint {
  margin: 12px 0 4px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  color: #64748b;
  font-size: 13px;
}

.industry-chip-product {
  font-size: 12px;
  font-weight: 600;
  color: #2563eb;
  line-height: 1.35;
}

.industry-chip-product--locked {
  color: #94a3b8;
  font-weight: 600;
}

.industry-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.15s ease,
    background 0.15s ease,
    box-shadow 0.15s ease;
  min-height: 96px;
}

.industry-chip--locked {
  cursor: not-allowed;
  opacity: 0.72;
  background: #f8fafc;
  border-style: dashed;
  padding: 10px;
  min-height: 88px;
  pointer-events: none;
}

.industry-chip--locked:hover {
  border-color: #e2e8f0;
  background: #f8fafc;
}

.industry-chip:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}

.industry-chip.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15);
}

.industry-chip-name {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}

.industry-chip-scenario {
  font-size: 12px;
  line-height: 1.4;
  color: #64748b;
}

.status-card {
  padding: 14px 16px;
  border-radius: 10px;
  margin-bottom: 20px;
  font-size: 14px;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
}

.status-card.ok {
  background: #f0fdf4;
  border-color: #86efac;
  color: #166534;
}

.status-card.warn {
  background: #fffbeb;
  border-color: #fcd34d;
  color: #92400e;
}

.baseline-groups {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 16px;
}

.baseline-groups--supplement {
  padding-top: 4px;
  border-top: 1px dashed #cbd5e1;
}

.baseline-section-title {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.sidebar-shell-note {
  margin: 10px 0 12px;
  font-size: 13px;
  line-height: 1.55;
  color: #64748b;
}

.host-pack-details {
  margin-top: 18px;
  padding-top: 12px;
  border-top: 1px dashed #e2e8f0;
  color: #64748b;
  font-size: 13px;
}

.host-pack-details summary {
  cursor: pointer;
  font-weight: 600;
  color: #475569;
  user-select: none;
}

.host-pack-details[open] summary {
  margin-bottom: 10px;
}

.host-pack-details-note {
  margin: 0 0 10px;
  font-size: 12px;
}

.host-pack-details-actions {
  margin-top: 8px;
}

.sidebar-preview {
  margin: 0 0 14px;
  padding: 10px 0 2px;
}

.sidebar-preview-title {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.sidebar-preview-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.sidebar-preview-chip {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 5px 10px;
  border-radius: 999px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 600;
}

.baseline-group h3 {
  margin: 0 0 4px;
  font-size: 15px;
  color: #0f172a;
}

.baseline-group-hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: #64748b;
}

.account-custom-empty-hint {
  margin: 0 0 12px;
  font-size: 13px;
  color: #64748b;
}

.baseline-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.baseline-list li {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.baseline-list li.ok {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #166534;
}

.baseline-list li.warn {
  background: #fffbeb;
  border-color: #fde68a;
  color: #92400e;
}

.baseline-list li.optional {
  color: #475569;
}

.baseline-list .mono {
  margin-left: auto;
  font-size: 11px;
  opacity: 0.85;
}

.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.btn {
  border: none;
  border-radius: 8px;
  padding: 10px 18px;
  font-size: 14px;
  cursor: pointer;
  font-weight: 600;
}

.btn.primary {
  background: #2563eb;
  color: #fff;
}

.btn.primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn.ghost {
  background: #f1f5f9;
  color: #334155;
  border: 1px solid #cbd5e1;
}

.btn.link {
  background: transparent;
  color: #2563eb;
}

.btn.text {
  background: transparent;
  color: #64748b;
  font-weight: 500;
  padding: 6px 0;
}

.product-flow-footer {
  padding: 16px 24px 20px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  flex-shrink: 0;
}

.doc-hint {
  color: #64748b;
  font-size: 12px;
  text-align: right;
}

@media (max-width: 560px) {
  .step-rail {
    grid-template-columns: 1fr;
  }

  .step-label {
    white-space: normal;
  }

  .industry-pick--open {
    grid-template-columns: 1fr;
  }

  .industry-pick--preview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .product-flow-header {
    flex-direction: column;
  }

  .welcome-hero {
    flex-direction: column;
    align-items: center;
    text-align: center;
  }

  .product-flow-footer {
    flex-direction: column;
    align-items: flex-start;
  }
}

/* 2026 AI onboarding · 人工自然主义：温润材质、自然生长与精密数字结构并置。 */
.product-flow {
  --ink: #18352f;
  --ink-soft: #4c665f;
  --moss: #587d6d;
  --moss-deep: #315a4d;
  --leaf: #8fb29d;
  --clay: #c98562;
  --sand: #f2eee5;
  --paper: rgba(255, 253, 248, 0.92);
  --line: rgba(54, 92, 80, 0.15);
  position: relative;
  isolation: isolate;
  align-items: center;
  padding: clamp(14px, 2.4vh, 24px) clamp(18px, 3.2vw, 44px);
  overflow: hidden auto;
  background:
    radial-gradient(circle at 18% 12%, rgba(160, 192, 170, 0.34), transparent 30%),
    radial-gradient(circle at 86% 82%, rgba(212, 168, 137, 0.24), transparent 32%),
    linear-gradient(145deg, #e9eee7 0%, #f5f1e9 50%, #e8eeeb 100%);
  color: var(--ink);
  font-family: Inter, "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
}

.organic-grid {
  position: absolute;
  z-index: -3;
  inset: 0;
  opacity: 0.45;
  background-image:
    linear-gradient(rgba(48, 86, 73, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(48, 86, 73, 0.045) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: radial-gradient(circle at center, #000, transparent 78%);
}

.organic-glow {
  position: absolute;
  z-index: -2;
  width: min(42vw, 620px);
  aspect-ratio: 1;
  border-radius: 48% 52% 61% 39% / 44% 40% 60% 56%;
  filter: blur(2px);
  opacity: 0.55;
  animation: organic-breathe 10s ease-in-out infinite alternate;
}

.organic-glow--moss {
  top: -24%;
  left: -12%;
  background: radial-gradient(circle at 58% 60%, rgba(100, 143, 121, 0.38), rgba(120, 164, 140, 0.02) 68%);
}

.organic-glow--sky {
  right: -13%;
  bottom: -35%;
  animation-delay: -4s;
  background: radial-gradient(circle at 42% 40%, rgba(107, 145, 183, 0.25), rgba(182, 140, 109, 0.05) 67%);
}

.product-flow-card {
  position: relative;
  width: min(100%, 1160px);
  max-height: calc(100dvh - clamp(28px, 4.8vh, 48px));
  border: 1px solid rgba(255, 255, 255, 0.82);
  border-radius: 30px;
  background: var(--paper);
  box-shadow:
    0 32px 90px rgba(36, 63, 54, 0.15),
    0 3px 14px rgba(48, 74, 66, 0.07),
    inset 0 1px 0 rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(28px) saturate(1.08);
}

.product-flow-card::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  border-radius: inherit;
  opacity: 0.24;
  background-image: radial-gradient(rgba(30, 70, 58, 0.2) 0.55px, transparent 0.7px);
  background-size: 7px 7px;
  mask-image: linear-gradient(115deg, #000, transparent 36%, transparent 74%, #000);
}

.product-flow-header {
  position: relative;
  z-index: 1;
  align-items: center;
  padding: 24px 34px 16px;
  border-bottom: 0;
}

.brand-lockup,
.company-memory,
.ai-config-title {
  display: flex;
  align-items: center;
}

.brand-lockup {
  gap: 12px;
}

.brand-seed {
  position: relative;
  width: 38px;
  height: 38px;
  border-radius: 50% 50% 47% 53% / 58% 44% 56% 42%;
  background: linear-gradient(145deg, #335e50, #83a58f);
  box-shadow: 0 8px 22px rgba(49, 90, 77, 0.24);
  transform: rotate(-14deg);
}

.brand-seed::before,
.brand-seed::after {
  content: "";
  position: absolute;
  background: rgba(255, 255, 255, 0.76);
}

.brand-seed::before {
  width: 2px;
  height: 20px;
  left: 18px;
  top: 9px;
  transform: rotate(18deg);
}

.brand-seed::after {
  width: 10px;
  height: 2px;
  left: 17px;
  top: 16px;
  transform: rotate(-18deg);
}

.brand {
  color: var(--ink);
  font-size: 16px;
  font-weight: 720;
  letter-spacing: 0.02em;
}

.brand-lead {
  margin-top: 3px;
  color: #71847e;
  font-size: 11px;
}

.edition-tag {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 11px;
  border-color: rgba(74, 112, 99, 0.16);
  background: rgba(237, 243, 237, 0.72);
  color: #597068;
  font-size: 11px;
  letter-spacing: 0.04em;
}

.edition-tag > span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #77a28b;
  box-shadow: 0 0 0 4px rgba(119, 162, 139, 0.13);
}

.step-rail {
  position: relative;
  z-index: 1;
  grid-template-columns: repeat(3, minmax(90px, 150px));
  justify-content: center;
  gap: 42px;
  padding: 4px 34px 16px;
  border-bottom: 1px solid rgba(53, 91, 78, 0.09);
}

.step-rail::before {
  content: "";
  position: absolute;
  left: 50%;
  top: 17px;
  width: min(410px, 46%);
  height: 1px;
  transform: translateX(-50%);
  background: linear-gradient(90deg, transparent, rgba(75, 111, 98, 0.23) 14%, rgba(75, 111, 98, 0.23) 86%, transparent);
}

.step-rail-item {
  position: relative;
  z-index: 1;
  justify-content: flex-start;
  padding: 7px 10px;
  border: 1px solid transparent;
  background: rgba(255, 253, 248, 0.88);
  color: #8a9994;
  font-size: 12px;
}

.step-rail-item.active {
  border-color: rgba(62, 103, 89, 0.18);
  background: #eff4ef;
  color: var(--moss-deep);
  box-shadow: 0 7px 18px rgba(49, 90, 77, 0.1);
}

.step-rail-item.done {
  background: rgba(235, 243, 235, 0.92);
  color: #64806f;
}

.step-num {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 50%;
  background: rgba(84, 120, 107, 0.1);
  font-size: 10px;
}

.step-rail-item.active .step-num {
  background: var(--moss-deep);
  color: white;
}

.step-panel {
  position: relative;
  z-index: 1;
  padding: clamp(24px, 3vw, 36px);
}

.step-panel h1 {
  margin: 8px 0 10px;
  color: var(--ink);
  font-size: clamp(27px, 3vw, 39px);
  font-weight: 680;
  letter-spacing: -0.035em;
}

.step-eyebrow {
  color: #758f84;
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.18em;
}

.lead {
  color: var(--ink-soft);
}

.step-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.06fr) minmax(340px, 0.94fr);
  align-items: center;
  gap: clamp(36px, 5vw, 72px);
  min-height: 430px;
}

.welcome-hero {
  align-items: center;
  margin: 5px 0 0;
}

.welcome-logo {
  display: none;
}

.welcome-tagline {
  margin-top: 8px;
  color: var(--moss);
  font-size: 15px;
  font-weight: 560;
}

.company-lead {
  max-width: 560px;
  margin-top: 19px;
  font-size: 14px;
}

.company-field {
  display: block;
  margin-top: 30px;
}

.company-field > span {
  display: block;
  margin-bottom: 9px;
  color: #60766e;
  font-size: 12px;
  font-weight: 650;
}

.company-input-shell {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 15px 5px 5px;
  border: 1px solid rgba(67, 105, 91, 0.19);
  border-radius: 15px;
  background: rgba(255, 255, 252, 0.82);
  box-shadow: inset 0 1px 2px rgba(57, 85, 75, 0.035);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.company-input-shell:focus-within,
.company-input-shell.active {
  border-color: rgba(49, 90, 77, 0.52);
  box-shadow: 0 0 0 4px rgba(85, 130, 111, 0.09), 0 10px 25px rgba(49, 90, 77, 0.06);
  transform: translateY(-1px);
}

.company-name-input {
  width: 100%;
  min-width: 0;
  padding: 14px 13px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--ink);
  font-size: 17px;
  font-weight: 580;
}

.company-name-input::placeholder {
  color: #a2ada8;
  font-weight: 430;
}

.company-input-shell > i {
  color: #8ba297;
}

.trial-status {
  margin: 10px 0 0;
  color: #73867f;
  font-size: 11px;
}

.identity-garden {
  position: relative;
  min-height: 390px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 45% 55% 38% 62% / 47% 39% 61% 53%;
  background:
    radial-gradient(circle at 47% 44%, rgba(255, 255, 250, 0.86), transparent 21%),
    radial-gradient(circle at 34% 28%, rgba(145, 180, 157, 0.5), transparent 34%),
    radial-gradient(circle at 72% 72%, rgba(213, 170, 140, 0.38), transparent 35%),
    linear-gradient(145deg, #dfe9df, #eee6da);
  box-shadow: inset 0 0 60px rgba(255, 255, 255, 0.46), 0 25px 60px rgba(66, 92, 82, 0.12);
}

.identity-garden::before {
  content: "";
  position: absolute;
  inset: 10%;
  border-radius: 50%;
  background-image: radial-gradient(rgba(52, 91, 77, 0.2) 0.6px, transparent 0.8px);
  background-size: 10px 10px;
  mask-image: radial-gradient(circle, #000, transparent 68%);
}

.identity-garden > p {
  position: absolute;
  right: 0;
  bottom: 18px;
  left: 0;
  margin: 0;
  color: rgba(50, 82, 71, 0.6);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-align: center;
}

.garden-orbit,
.map-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  border: 1px solid rgba(57, 95, 82, 0.16);
  border-radius: 50%;
  transform: translate(-50%, -50%);
}

.garden-orbit--one {
  width: 62%;
  aspect-ratio: 1;
}

.garden-orbit--two {
  width: 87%;
  aspect-ratio: 1;
  border-style: dashed;
}

.company-seed {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  width: 140px;
  height: 140px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  padding: 18px;
  border: 1px solid rgba(255, 255, 255, 0.78);
  border-radius: 50% 50% 44% 56% / 55% 44% 56% 45%;
  background: linear-gradient(145deg, rgba(42, 81, 68, 0.95), rgba(91, 128, 108, 0.9));
  box-shadow: 0 22px 45px rgba(43, 76, 65, 0.23), inset 0 1px 0 rgba(255, 255, 255, 0.25);
  color: white;
  text-align: center;
  transform: translate(-50%, -50%);
  transition: transform 0.4s ease, box-shadow 0.4s ease;
}

.company-seed.awake {
  box-shadow: 0 25px 55px rgba(43, 76, 65, 0.3), 0 0 0 12px rgba(255, 255, 255, 0.12);
  transform: translate(-50%, -50%) scale(1.04);
}

.company-seed strong {
  position: relative;
  z-index: 1;
  font-size: 28px;
  font-weight: 660;
  letter-spacing: -0.04em;
}

.company-seed small {
  position: relative;
  z-index: 1;
  width: 100%;
  margin-top: 7px;
  overflow: hidden;
  color: rgba(255, 255, 255, 0.74);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.company-seed-pulse {
  position: absolute;
  inset: -18px;
  border: 1px solid rgba(255, 255, 255, 0.26);
  border-radius: inherit;
  animation: seed-pulse 3.4s ease-out infinite;
}

.garden-node,
.map-node {
  position: absolute;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 11px;
  border: 1px solid rgba(255, 255, 255, 0.74);
  border-radius: 999px;
  background: rgba(255, 253, 247, 0.76);
  box-shadow: 0 9px 24px rgba(57, 85, 75, 0.1);
  backdrop-filter: blur(12px);
  color: #4c6a5e;
  font-size: 10px;
}

.garden-node--chat { top: 18%; left: 10%; }
.garden-node--data { top: 24%; right: 5%; }
.garden-node--people { bottom: 19%; left: 11%; }

.industry-stage,
.configuration-stage {
  min-height: 430px;
}

.industry-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 28px;
}

.industry-heading h1,
.configuration-heading h1 {
  font-size: clamp(25px, 2.8vw, 35px);
}

.company-memory {
  flex: 0 0 auto;
  gap: 9px;
  max-width: 260px;
  padding: 8px 11px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: rgba(242, 246, 241, 0.72);
}

.company-memory > span {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 10px 10px 8px 12px;
  background: var(--moss-deep);
  color: white;
  font-size: 10px;
}

.company-memory strong {
  min-width: 0;
  overflow: hidden;
  color: var(--ink);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.company-memory small {
  color: #84968f;
  font-size: 9px;
}

.industry-search {
  display: flex;
  align-items: center;
  gap: 11px;
  max-width: 640px;
  margin-top: 23px;
  padding: 0 15px;
  border: 1px solid rgba(67, 105, 91, 0.18);
  border-radius: 14px;
  background: rgba(255, 255, 252, 0.74);
}

.industry-stage .industry-search {
  margin-top: 14px;
}

.industry-search > i { color: #80958c; }
.industry-search > span { color: #7a8d86; cursor: pointer; font-size: 11px; }
.industry-search input {
  width: 100%;
  padding: 13px 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--ink);
  font-size: 13px;
}

.industry-category-rail {
  display: flex;
  gap: 7px;
  margin-top: 8px;
  padding: 2px 1px 5px;
  overflow-x: auto;
  scrollbar-width: none;
}

.industry-category-rail::-webkit-scrollbar {
  display: none;
}

.industry-category-rail button {
  display: inline-flex;
  min-width: max-content;
  align-items: center;
  gap: 6px;
  padding: 7px 9px;
  border: 1px solid rgba(0, 82, 217, 0.11);
  border-radius: 999px;
  background: rgba(250, 252, 255, 0.7);
  color: #657b9b;
  cursor: pointer;
  font: inherit;
  font-size: 9px;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    color 0.18s ease;
}

.industry-category-rail button:hover {
  border-color: rgba(0, 82, 217, 0.28);
  color: #1d4ed8;
}

.industry-category-rail button.active {
  border-color: rgba(0, 82, 217, 0.42);
  background: #e8f1ff;
  color: #0052d9;
  box-shadow: 0 5px 14px rgba(0, 82, 217, 0.08);
}

.industry-category-rail small {
  display: grid;
  min-width: 16px;
  height: 16px;
  place-items: center;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.08);
  color: #7891b8;
  font-size: 7px;
}

.industry-category-rail button.active small {
  background: rgba(37, 99, 235, 0.13);
  color: #1d4ed8;
}

.industry-open-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 9px 0;
  color: #71847d;
  font-size: 11px;
  letter-spacing: 0.03em;
}

.industry-open-hint small {
  color: #8ba0bd;
  font-size: 8px;
  letter-spacing: 0;
}

.industry-pick {
  margin: 0;
}

.industry-pick--open {
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 9px;
}

.industry-chip {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  min-height: 72px;
  padding: 10px;
  overflow: hidden;
  border-color: rgba(73, 107, 95, 0.12);
  border-radius: 15px;
  background: rgba(250, 250, 245, 0.72);
}

.industry-chip:hover {
  border-color: rgba(66, 108, 91, 0.34);
  background: rgba(242, 247, 241, 0.9);
  box-shadow: 0 10px 24px rgba(48, 82, 69, 0.08);
  transform: translateY(-2px);
}

.industry-more-button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-top: 8px;
  padding: 5px 9px;
  border: 0;
  background: transparent;
  color: #2563eb;
  cursor: pointer;
  font: inherit;
  font-size: 9px;
}

.industry-more-button:hover {
  color: #0052d9;
}

.industry-chip.active {
  border-color: rgba(49, 90, 77, 0.58);
  background: linear-gradient(145deg, rgba(231, 241, 233, 0.95), rgba(244, 240, 228, 0.88));
  box-shadow: 0 0 0 2px rgba(65, 110, 91, 0.09), 0 13px 28px rgba(49, 90, 77, 0.1);
}

.industry-chip-icon {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 12px 12px 9px 14px;
  background: #e8efe8;
  color: #5f816f;
}

.industry-chip.active .industry-chip-icon {
  background: var(--moss-deep);
  color: white;
}

.industry-chip-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.industry-chip-name {
  color: var(--ink);
  font-size: 13px;
  font-weight: 660;
}

.industry-chip-scenario {
  display: -webkit-box;
  overflow: hidden;
  color: #7a8c85;
  font-size: 10px;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.industry-chip-state {
  position: absolute;
  right: 10px;
  bottom: 8px;
  color: #91a099;
  font-size: 8px;
}

.industry-loading-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border-color: rgba(67, 105, 91, 0.22);
  border-radius: 14px;
  background: rgba(242, 246, 240, 0.74);
  color: #647a71;
  font-size: 11px;
}

.custom-industry-option {
  flex: 0 0 auto;
  padding: 8px 12px;
  border: 1px solid rgba(49, 90, 77, 0.22);
  border-radius: 10px;
  background: rgba(255, 253, 248, 0.9);
  color: var(--moss-deep);
  cursor: pointer;
  font: inherit;
  font-weight: 650;
}

.custom-industry-option:hover {
  border-color: rgba(49, 90, 77, 0.48);
  background: #eef4ed;
}

.custom-industry-option--standalone {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-top: 9px;
}

.ai-understanding-card {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
  padding: 10px 14px;
  border: 1px solid rgba(67, 105, 91, 0.13);
  border-radius: 15px;
  background: linear-gradient(90deg, rgba(233, 242, 234, 0.75), rgba(248, 244, 235, 0.6));
}

.ai-understanding-icon {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 50%;
  background: var(--moss-deep);
  color: #d9ebdf;
  box-shadow: 0 0 0 6px rgba(67, 105, 91, 0.07);
}

.ai-understanding-card div {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: baseline;
  gap: 2px 9px;
}

.ai-understanding-card small {
  color: #81938c;
  font-size: 9px;
  letter-spacing: 0.08em;
}

.ai-understanding-card strong {
  color: var(--ink);
  font-size: 12px;
}

.ai-understanding-card p {
  grid-column: 1 / -1;
  margin: 2px 0 0;
  color: #62776f;
  font-size: 10px;
}

.configuration-heading {
  text-align: center;
}

.configuration-heading .lead {
  max-width: 720px;
  margin: 0 auto;
  font-size: 13px;
}

.configuration-grid {
  display: grid;
  grid-template-columns: minmax(340px, 0.85fr) minmax(0, 1.15fr);
  align-items: stretch;
  gap: 20px;
  margin-top: 23px;
}

.capability-map {
  position: relative;
  min-height: 290px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.78);
  border-radius: 27px 38px 28px 42px;
  background:
    radial-gradient(circle at center, rgba(255, 255, 248, 0.86), transparent 25%),
    radial-gradient(circle at 24% 25%, rgba(132, 171, 146, 0.35), transparent 35%),
    radial-gradient(circle at 80% 80%, rgba(212, 165, 132, 0.28), transparent 36%),
    #e7ece4;
  box-shadow: inset 0 0 45px rgba(255, 255, 255, 0.45);
}

.map-ring--outer { width: 78%; aspect-ratio: 1; border-style: dashed; }
.map-ring--inner { width: 48%; aspect-ratio: 1; }

.map-core {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  width: 125px;
  height: 125px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  padding: 15px;
  border-radius: 50% 50% 45% 55% / 56% 44% 56% 44%;
  background: linear-gradient(145deg, #31594c, #668b75);
  box-shadow: 0 20px 44px rgba(45, 82, 69, 0.27), inset 0 1px rgba(255, 255, 255, 0.25);
  color: white;
  text-align: center;
  transform: translate(-50%, -50%);
}

.map-core > span { font-size: 22px; font-weight: 700; }
.map-core strong { width: 100%; margin-top: 5px; overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.map-core small { margin-top: 4px; color: rgba(255,255,255,.62); font-size: 8px; }
.map-node--1 { top: 12%; left: 7%; }
.map-node--2 { top: 12%; right: 6%; }
.map-node--3 { right: 7%; bottom: 13%; }
.map-node--4 { bottom: 13%; left: 7%; }

.configuration-panel {
  padding: 20px;
  border: 1px solid rgba(67, 105, 91, 0.13);
  border-radius: 25px;
  background: rgba(252, 251, 246, 0.7);
}

.ai-config-title {
  gap: 12px;
  margin-bottom: 16px;
}

.ai-config-signal {
  position: relative;
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 50%;
  background: #31594c;
  box-shadow: 0 8px 20px rgba(49, 89, 76, 0.18);
}

.ai-config-signal::before,
.ai-config-signal::after,
.ai-config-signal > span {
  content: "";
  position: absolute;
  border: 1px solid rgba(220, 238, 225, 0.78);
  border-radius: 50%;
}

.ai-config-signal::before { width: 7px; height: 7px; }
.ai-config-signal::after { width: 17px; height: 17px; opacity: .65; }
.ai-config-signal > span { width: 27px; height: 27px; opacity: .35; }

.ai-config-title div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.ai-config-title small { color: #80938b; font-size: 8px; letter-spacing: .14em; }
.ai-config-title strong { color: var(--ink); font-size: 13px; }

.capability-section + .capability-section {
  margin-top: 15px;
}

.capability-section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.capability-section-title span { color: #506a60; font-size: 10px; font-weight: 700; }
.capability-section-title small { color: #92a099; font-size: 8px; }

.capability-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}

.capability-list > span {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 7px;
  padding: 9px 10px;
  border: 1px solid rgba(73, 107, 95, 0.1);
  border-radius: 10px;
  background: rgba(239, 245, 239, 0.68);
  color: #48655a;
  font-size: 9px;
}

.capability-list b { color: #8fa098; font-size: 7px; font-weight: 500; }

.sidebar-preview-list {
  gap: 6px;
}

.sidebar-preview-chip {
  min-height: 25px;
  padding: 4px 8px;
  border-color: rgba(185, 142, 111, 0.18);
  background: rgba(246, 237, 226, 0.78);
  color: #81634f;
  font-size: 9px;
}

.status-card {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 15px 0 0;
  padding: 10px 12px;
  border-color: rgba(83, 119, 104, 0.14);
  border-radius: 11px;
  background: rgba(236, 243, 236, 0.68);
  color: #587167;
  font-size: 9px;
}

.status-card.ok,
.status-card.warn {
  border-color: rgba(83, 119, 104, 0.14);
  background: rgba(236, 243, 236, 0.68);
  color: #587167;
}

.step-panel .actions {
  margin-top: 0;
  padding-top: 24px;
}

.industry-stage .actions {
  padding-top: 14px;
}

.actions {
  gap: 12px;
}

.btn {
  border-radius: 12px;
  padding: 12px 17px;
  font-size: 12px;
  transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
}

.btn.primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 13px;
  min-width: 190px;
  background: linear-gradient(135deg, #294f43, #547d68);
  box-shadow: 0 12px 26px rgba(42, 78, 66, 0.2), inset 0 1px rgba(255,255,255,.17);
}

.btn.primary:not(:disabled):hover {
  box-shadow: 0 15px 32px rgba(42, 78, 66, 0.27);
  transform: translateY(-2px);
}

.btn.primary:disabled {
  background: #9daca6;
  box-shadow: none;
}

.btn.link {
  color: #637d73;
  font-size: 10px;
}

.btn.ghost {
  border-color: rgba(67, 105, 91, 0.16);
  background: #eef2ed;
  color: #526b62;
}

.configuration-actions {
  justify-content: center;
  padding-top: 20px !important;
}

.finish-progress {
  margin: 10px 0 0;
  color: #73877f;
  font-size: 10px;
  text-align: center;
}

.host-pack-details {
  margin-top: 15px;
  padding: 10px 18px 0;
  border-top-color: rgba(67, 105, 91, 0.12);
}

.product-flow-footer {
  position: relative;
  z-index: 1;
  padding: 12px 34px 17px;
  border-top-color: rgba(53, 91, 78, 0.08);
}

.btn.text,
.doc-hint {
  color: #84948e;
  font-size: 9px;
}

@keyframes seed-pulse {
  0% { opacity: 0; transform: scale(0.75); }
  28% { opacity: 0.55; }
  100% { opacity: 0; transform: scale(1.28); }
}

@keyframes organic-breathe {
  from { transform: rotate(-3deg) scale(0.96); }
  to { transform: rotate(4deg) scale(1.06); }
}

@media (max-width: 900px) {
  .product-flow {
    align-items: flex-start;
  }

  .product-flow-card {
    max-height: none;
  }

  .step-layout,
  .configuration-grid {
    grid-template-columns: 1fr;
  }

  .identity-garden {
    min-height: 320px;
  }

  .industry-pick--open {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .company-memory {
    display: none;
  }
}

@media (max-width: 620px) {
  .product-flow {
    padding: 0;
  }

  .product-flow-card {
    min-height: 100dvh;
    border: 0;
    border-radius: 0;
  }

  .product-flow-header {
    flex-direction: row;
    padding: 18px 18px 12px;
  }

  .edition-tag {
    display: none;
  }

  .step-rail {
    grid-template-columns: repeat(3, 1fr);
    gap: 5px;
    padding: 4px 15px 12px;
  }

  .step-rail::before {
    display: none;
  }

  .step-rail-item {
    justify-content: center;
  }

  .step-panel {
    padding: 28px 20px;
  }

  .step-layout {
    gap: 28px;
  }

  .identity-garden {
    min-height: 290px;
  }

  .industry-heading {
    display: block;
  }

  .industry-loading-hint {
    align-items: stretch;
    flex-direction: column;
  }

  .industry-pick--open,
  .capability-list {
    grid-template-columns: 1fr;
  }

  .industry-chip {
    min-height: 80px;
  }

  .capability-map {
    min-height: 290px;
  }

  .actions,
  .configuration-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .btn.primary {
    width: 100%;
  }

  .product-flow-footer {
    padding: 12px 20px 18px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .organic-glow,
  .company-seed-pulse {
    animation: none;
  }

  .company-seed,
  .industry-chip,
  .btn {
    transition: none;
  }
}

/* XCAGI brand correction: keep the organic material language, return every
   interactive and identity-bearing surface to the product's established blue. */
.product-flow {
  --ink: #102341;
  --ink-soft: #5d6f89;
  --moss: #2563eb;
  --moss-deep: #0052d9;
  --clay: #7aa7f8;
  --line: rgba(0, 82, 217, 0.13);
  --paper: rgba(248, 251, 255, 0.88);
  background:
    radial-gradient(circle at 18% 12%, rgba(96, 165, 250, 0.28), transparent 30%),
    radial-gradient(circle at 86% 82%, rgba(147, 197, 253, 0.24), transparent 32%),
    linear-gradient(145deg, #eaf2ff 0%, #f8f9f6 50%, #e8f0ff 100%);
}

.organic-grid {
  background-image:
    linear-gradient(rgba(0, 82, 217, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 82, 217, 0.045) 1px, transparent 1px);
}

.organic-glow--moss {
  background: radial-gradient(circle at 58% 60%, rgba(37, 99, 235, 0.32), rgba(96, 165, 250, 0.02) 68%);
}

.organic-glow--sky {
  background: radial-gradient(circle at 42% 40%, rgba(14, 165, 233, 0.23), rgba(147, 197, 253, 0.04) 67%);
}

.product-flow-card {
  box-shadow:
    0 32px 90px rgba(30, 64, 112, 0.15),
    0 3px 14px rgba(30, 64, 112, 0.07),
    inset 0 1px 0 rgba(255, 255, 255, 0.94);
}

.product-flow-card::before {
  background-image: radial-gradient(rgba(0, 82, 217, 0.17) 0.55px, transparent 0.7px);
}

.brand-seed {
  background: linear-gradient(145deg, #0052d9, #60a5fa);
  box-shadow: 0 8px 22px rgba(0, 82, 217, 0.24);
}

.brand-lead,
.step-eyebrow,
.company-field > span,
.trial-status,
.industry-open-hint,
.finish-progress {
  color: #6a7f9f;
}

.edition-tag {
  border-color: rgba(0, 82, 217, 0.14);
  background: rgba(238, 244, 255, 0.78);
  color: #506b96;
}

.edition-tag > span {
  background: #3b82f6;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.13);
}

.step-rail {
  border-bottom-color: rgba(0, 82, 217, 0.09);
}

.step-rail::before {
  background: linear-gradient(90deg, transparent, rgba(0, 82, 217, 0.22) 14%, rgba(0, 82, 217, 0.22) 86%, transparent);
}

.step-rail-item {
  background: rgba(251, 253, 255, 0.9);
  color: #8292aa;
}

.step-rail-item.active {
  border-color: rgba(0, 82, 217, 0.18);
  background: #edf4ff;
  box-shadow: 0 7px 18px rgba(0, 82, 217, 0.1);
}

.step-rail-item.done {
  background: rgba(235, 243, 255, 0.94);
  color: #5075ac;
}

.step-num {
  background: rgba(37, 99, 235, 0.1);
}

.welcome-tagline,
.btn.link {
  color: #2563eb;
}

.company-input-shell,
.industry-search {
  border-color: rgba(0, 82, 217, 0.18);
  background: rgba(252, 253, 255, 0.84);
}

.company-input-shell:focus-within,
.company-input-shell.active {
  border-color: rgba(0, 82, 217, 0.5);
  box-shadow:
    0 0 0 4px rgba(37, 99, 235, 0.09),
    0 10px 25px rgba(0, 82, 217, 0.06);
}

.company-input-shell > i,
.industry-search > i,
.industry-search > span {
  color: #7891b8;
}

.identity-garden {
  background:
    radial-gradient(circle at 47% 44%, rgba(255, 255, 255, 0.88), transparent 21%),
    radial-gradient(circle at 34% 28%, rgba(96, 165, 250, 0.47), transparent 34%),
    radial-gradient(circle at 72% 72%, rgba(186, 213, 255, 0.5), transparent 35%),
    linear-gradient(145deg, #dceaff, #eef4ff);
  box-shadow:
    inset 0 0 60px rgba(255, 255, 255, 0.48),
    0 25px 60px rgba(30, 64, 112, 0.13);
}

.identity-garden::before {
  background-image: radial-gradient(rgba(0, 82, 217, 0.18) 0.6px, transparent 0.8px);
}

.identity-garden > p {
  color: rgba(30, 74, 132, 0.62);
}

.garden-orbit,
.map-ring {
  border-color: rgba(0, 82, 217, 0.16);
}

.company-seed,
.map-core {
  background: linear-gradient(145deg, rgba(0, 61, 171, 0.97), rgba(37, 99, 235, 0.92));
  box-shadow:
    0 22px 45px rgba(0, 82, 217, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.25);
}

.company-seed.awake {
  box-shadow:
    0 25px 55px rgba(0, 82, 217, 0.3),
    0 0 0 12px rgba(255, 255, 255, 0.14);
}

.garden-node,
.map-node {
  background: rgba(250, 253, 255, 0.8);
  box-shadow: 0 9px 24px rgba(30, 64, 112, 0.1);
  color: #456895;
}

.company-memory {
  background: rgba(238, 244, 255, 0.78);
}

.company-memory small,
.industry-chip-state,
.capability-section-title small,
.capability-list b,
.btn.text,
.doc-hint {
  color: #8495ae;
}

.industry-chip {
  border-color: rgba(0, 82, 217, 0.12);
  background: rgba(250, 252, 255, 0.76);
}

.industry-chip:hover {
  border-color: rgba(0, 82, 217, 0.34);
  background: rgba(240, 246, 255, 0.92);
  box-shadow: 0 10px 24px rgba(0, 82, 217, 0.08);
}

.industry-chip.active {
  border-color: rgba(0, 82, 217, 0.56);
  background: linear-gradient(145deg, rgba(230, 240, 255, 0.96), rgba(244, 248, 255, 0.9));
  box-shadow:
    0 0 0 2px rgba(37, 99, 235, 0.09),
    0 13px 28px rgba(0, 82, 217, 0.1);
}

.industry-chip-icon {
  background: #e8f1ff;
  color: #4d79b8;
}

.industry-chip-scenario,
.ai-understanding-card p,
.capability-section-title span {
  color: #607797;
}

.industry-loading-hint {
  border-color: rgba(0, 82, 217, 0.2);
  background: rgba(239, 245, 255, 0.78);
  color: #58739c;
}

.custom-industry-option {
  border-color: rgba(0, 82, 217, 0.22);
  background: rgba(250, 253, 255, 0.92);
}

.custom-industry-option:hover {
  border-color: rgba(0, 82, 217, 0.48);
  background: #edf4ff;
}

.ai-understanding-card {
  border-color: rgba(0, 82, 217, 0.13);
  background: linear-gradient(90deg, rgba(232, 241, 255, 0.78), rgba(247, 250, 255, 0.66));
}

.ai-understanding-icon {
  color: #dceaff;
  box-shadow: 0 0 0 6px rgba(0, 82, 217, 0.07);
}

.ai-understanding-card small,
.ai-config-title small {
  color: #7e92b0;
}

.capability-map {
  background:
    radial-gradient(circle at center, rgba(255, 255, 255, 0.88), transparent 25%),
    radial-gradient(circle at 24% 25%, rgba(96, 165, 250, 0.34), transparent 35%),
    radial-gradient(circle at 80% 80%, rgba(186, 213, 255, 0.42), transparent 36%),
    #e7effc;
}

.configuration-panel {
  border-color: rgba(0, 82, 217, 0.13);
  background: rgba(250, 252, 255, 0.74);
}

.ai-config-signal {
  background: #0052d9;
  box-shadow: 0 8px 20px rgba(0, 82, 217, 0.2);
}

.ai-config-signal::before,
.ai-config-signal::after,
.ai-config-signal > span {
  border-color: rgba(219, 234, 254, 0.82);
}

.capability-list > span {
  border-color: rgba(0, 82, 217, 0.1);
  background: rgba(237, 244, 255, 0.72);
  color: #426797;
}

.sidebar-preview-chip {
  border-color: rgba(96, 165, 250, 0.2);
  background: rgba(231, 240, 255, 0.82);
  color: #3f6392;
}

.capability-integrity-note {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 6px;
  margin: 8px 0 0;
  color: #5f7697;
  font-size: 8px;
  line-height: 1.45;
}

.capability-integrity-note > i {
  color: #2563eb;
}

.capability-integrity-note > span {
  flex-basis: 100%;
  padding-left: 14px;
  color: #8594a9;
}

.status-card,
.status-card.ok,
.status-card.warn {
  border-color: rgba(0, 82, 217, 0.14);
  background: rgba(235, 243, 255, 0.72);
  color: #4f6d98;
}

.btn.primary {
  background: linear-gradient(135deg, #003cab, #2563eb);
  box-shadow:
    0 12px 26px rgba(0, 82, 217, 0.22),
    inset 0 1px rgba(255, 255, 255, 0.18);
}

.btn.primary:not(:disabled):hover {
  box-shadow: 0 15px 32px rgba(0, 82, 217, 0.3);
}

.btn.primary:disabled {
  background: #9aa9bf;
}

.btn.ghost {
  border-color: rgba(0, 82, 217, 0.16);
  background: #edf3fc;
  color: #4a678f;
}

.host-pack-details,
.product-flow-footer {
  border-color: rgba(0, 82, 217, 0.1);
}
</style>
