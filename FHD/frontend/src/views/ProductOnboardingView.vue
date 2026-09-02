<template>
  <div class="product-flow">
    <div class="product-flow-card">
      <header class="product-flow-header">
        <div class="product-flow-header-main">
          <div class="brand">{{ fromTutorial ? '新手教程 · 宿主入门' : 'XCAGI 宿主' }}</div>
          <p v-if="currentStepMeta?.subtitle && currentStep !== 'welcome'" class="brand-lead">
            {{ currentStepMeta.subtitle }}
          </p>
        </div>
        <div class="edition-tag">发行版：{{ editionLabel }}</div>
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
          <div class="welcome-hero">
            <img class="welcome-logo" :src="welcomeLogoSrc" height="56" alt="XC" decoding="async" @error="onWelcomeLogoError" />
            <div>
              <h1>认识 XC</h1>
              <p class="welcome-tagline">专属于您的数字公司 · 默认干净，行业业务按需加载</p>
              <p class="lead">
                日常界面默认有<strong>智能对话</strong>（找小C办事）、<strong>信息</strong>（联系AI同事）、<strong>智能生态</strong>和<strong>员工工作台</strong>；行业业务菜单、定制
                AI 员工都按需加载。先把 XC 当成会长大的公司，用到哪再补哪。
              </p>
            </div>
          </div>
          <ul class="flow-list bullets">
            <li><strong>干净起步</strong>：侧栏默认只有对话、信息、生态、员工工作台，不堆满行业菜单</li>
            <li><strong>先定行业</strong>：选好方向后，再告诉您还要补哪些侧栏能力卡片</li>
            <li><strong>AI 员工</strong>：从市场或定制 Mod 安装后上岗，不在本步基础线里批量装</li>
          </ul>
          <p class="lead muted pricing-anchor">
            <strong>价格预期</strong>：99 元试用 30 天；满意后选购永久授权（1
            万元起），一次购买永久使用。试用到期账户冻结，购买后即可继续使用。
          </p>
          <p v-if="trialStatusText" class="lead muted trial-status" role="status">
            {{ trialStatusText }}
          </p>
          <div class="actions">
            <button type="button" class="btn primary" @click="goStep('industry')">下一步：行业定型</button>
          </div>
        </template>

        <template v-else-if="currentStep === 'industry'">
          <h1>先定行业</h1>
          <p v-if="openIndustryLeadNames.length" class="lead">
            当前开放
            <template v-for="(name, idx) in openIndustryLeadNames" :key="name">
              <strong>{{ name }}</strong
              ><template v-if="idx < openIndustryLeadNames.length - 1"> 与 </template>
            </template>
            {{ industryLeadKindText }}；选好后下一步会列出要补的基础线。
          </p>
          <p v-else class="lead">正在读取当前账号可选行业，读取完成后再继续下一步。</p>
          <p class="industry-open-hint">请选择您的行业方向</p>
          <div class="industry-pick industry-pick--open" role="listbox" aria-label="可选行业">
            <button
              v-for="preset in openIndustryOptions"
              :key="preset.id"
              type="button"
              class="industry-chip"
              :class="{ active: pickedIndustryId === preset.id }"
              role="option"
              :aria-selected="pickedIndustryId === preset.id"
              @click="pickIndustry(preset.id)"
            >
              <span class="industry-chip-name">{{ preset.name }}</span>
              <span class="industry-chip-product">{{ industryPackageLabel(preset.id) }}</span>
              <span class="industry-chip-scenario">{{ chipScenarioText(preset.scenario) }}</span>
            </button>
          </div>
          <p v-if="!openIndustryOptions.length" class="industry-loading-hint">正在加载行业权限…</p>
          <p v-if="previewIndustryOptions.length" class="industry-preview-hint">更多行业（即将开放，暂不可选）</p>
          <div v-if="previewIndustryOptions.length" class="industry-pick industry-pick--preview" aria-hidden="true">
            <div v-for="preset in previewIndustryOptions" :key="preset.id" class="industry-chip industry-chip--locked">
              <span class="industry-chip-name">{{ preset.name }}</span>
              <span class="industry-chip-product industry-chip-product--locked">即将开放</span>
              <span class="industry-chip-scenario">{{ chipScenarioText(preset.scenario) }}</span>
            </div>
          </div>
          <div class="actions">
            <button type="button" class="btn primary" :disabled="!canConfirmIndustry || loading" @click="confirmIndustryAndNext">
              下一步：看要补哪些侧栏基础线
            </button>
            <button type="button" class="btn ghost" @click="openModStore">打开扩展市场</button>
            <button type="button" class="btn link" @click="finishToChat">先跳过，直接用对话</button>
          </div>
        </template>

        <template v-else-if="currentStep === 'host-pack'">
          <h1>准备侧栏菜单</h1>
          <p class="lead">
            已选 <strong>{{ pickedIndustryName }}</strong
            >。点一下装齐推荐菜单，就可以进对话。 AI 员工以后需要再装，不挡这一步。
          </p>
          <p class="lead muted">行业 Mod 含在授权内，不单独收费；定制 AI 员工按需另行评估。</p>
          <div class="status-card" :class="{ ok: baselineOk && !loading, warn: !baselineOk && !loading }">
            <template v-if="loading"> <i class="fa fa-spinner fa-spin"></i> 正在检测… </template>
            <template v-else-if="baselineOk">
              <i class="fa fa-check-circle"></i>
              菜单已齐，可以进入智能对话。
            </template>
            <template v-else>
              <i class="fa fa-exclamation-circle"></i>
              还差 {{ missingSidebarBaselineCount || missingRequiredCount || 1 }} 项推荐菜单
            </template>
          </div>
          <div v-if="industrySidebarPreviewLabels.length" class="sidebar-preview" aria-label="进入后补齐的侧栏菜单">
            <p class="sidebar-preview-title">装好后侧栏会出现</p>
            <div class="sidebar-preview-list">
              <span v-for="label in industrySidebarPreviewLabels" :key="label" class="sidebar-preview-chip">
                {{ label }}
              </span>
            </div>
          </div>
          <div class="actions">
            <button v-if="!baselineOk" type="button" class="btn primary" :disabled="bootstrapBusy || loading" @click="runBootstrap">
              <i class="fa" :class="bootstrapBusy ? 'fa-spinner fa-spin' : 'fa-download'"></i>
              {{ bootstrapBusy ? '正在装齐…' : '一键装齐' }}
            </button>
            <button v-else type="button" class="btn primary" :disabled="finishing" @click="finishOnboardingComplete">
              <i class="fa" :class="finishing ? 'fa-spinner fa-spin' : 'fa-check'"></i>
              {{ finishing ? '正在进入智能对话…' : '完成并进入对话' }}
            </button>
            <button type="button" class="btn link" :disabled="finishing" @click="finishToChat">先进入对话</button>
          </div>
          <p v-if="finishing" class="finish-progress" role="status" aria-live="polite">菜单已经准备好，正在打开智能对话…</p>
          <details v-if="hostPackDetailGroups.length" class="host-pack-details">
            <summary>查看明细（可选）</summary>
            <p v-if="baselinePlan?.summary" class="lead muted">{{ baselinePlan.summary }}</p>
            <p v-if="showNoAccountCustomHint" class="account-custom-empty-hint muted">
              当前账号未绑定定制能力；AI 员工可稍后在扩展市场安装。
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
              <button type="button" class="btn ghost" :disabled="loading" @click="refreshStatus">重新检测</button>
              <button v-if="!baselineOk" type="button" class="btn ghost" :disabled="bootstrapBusy || loading" @click="runBootstrap">
                再次一键装齐
              </button>
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
        <button v-else type="button" class="btn text" @click="skipEntireFlow">跳过引导（高级用户）</button>
        <span class="doc-hint">{{ footerHint }}</span>
      </footer>
    </div>
  </div>
</template>

<script setup>
// 入口 façade：状态/行为/导航拆分至 ./product-onboarding/，此处仅装配，行为与拆分前一致
import { onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProductFlow } from '@/composables/useProductFlow'
import { useIndustryStore } from '@/stores/industry'
import { useTutorialCatalog } from '@/composables/useTutorialCatalog'
import { fetchProductSku } from '@/utils/productSku'
import { authApi } from '@/api/auth'
import { clearDeliverableStatusCache, fetchOnboardingIndustryCatalog } from '@/utils/platformShellApi'
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults'
import { parseFlowStepQuery, saveProductFlowLastStep, setRuntimeOnboardingOpenIndustryIds } from '@/constants/productFlow'
import { useProductOnboardingState } from './product-onboarding/useProductOnboardingState'
import { useProductOnboardingNav } from './product-onboarding/useProductOnboardingNav'
import { useProductOnboardingActions } from './product-onboarding/useProductOnboardingActions'

const route = useRoute()
const router = useRouter()
const flow = useProductFlow()
const industryStore = useIndustryStore()
const { buildContext: tutorialBuildContext } = useTutorialCatalog()

const state = useProductOnboardingState(route)
const nav = useProductOnboardingNav(state, { router, flow })
const actions = useProductOnboardingActions(state, { router, flow, industryStore, nav, tutorialBuildContext })

// 顶层解耦保留全部同名绑定：模板渲染与测试 setupState（pickedIndustryId）访问面与拆分前一致
const {
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
  currentIndex,
  currentStepMeta,
  editionLabel,
  fromTutorial,
  returnPath,
  footerHint,
} = state

const { goStep, returnFromTutorial, openModStore, finishToChat, skipEntireFlow } = nav
const { refreshStatus, runBootstrap, pickIndustry, confirmIndustryAndNext, finishOnboardingComplete } = actions

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

onMounted(async () => {
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

<style scoped src="./product-onboarding/product-onboarding.css"></style>
