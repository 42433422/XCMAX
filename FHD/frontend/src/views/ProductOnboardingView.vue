<template>
  <div class="product-flow">
    <div class="product-flow-card">
      <header class="product-flow-header">
        <div class="product-flow-header-main">
          <div class="brand">{{ fromTutorial ? '新手教程 · 创建工作空间' : 'XCAGI · 创建您的数字公司' }}</div>
          <p v-if="currentStepMeta?.subtitle && currentStep !== 'welcome'" class="brand-lead">
            {{ isAttendanceOnboarding && ['host-pack', 'seed-demo', 'first-ai-task'].includes(currentStep) ? '在考勤工作区核对部门和人员，再开始考勤查询' : currentStepMeta.subtitle }}
          </p>
        </div>
      </header>

      <nav v-if="['welcome', 'industry', 'host-pack'].includes(currentStep)" class="step-rail" aria-label="设置流程">
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
        <div v-if="loginRequired" class="status-card warn" role="status">
          <p>请先登录，登录后继续准备业务功能。已选行业和当前步骤会保留。</p>
          <button type="button" class="btn primary" @click="loginToContinue">登录并继续设置</button>
        </div>
        <OnboardingCompanyStep v-if="currentStep === 'welcome'" v-model="companyName" @continue="goStep('industry')" />
        <OnboardingIndustryStep v-else-if="currentStep === 'industry'" v-model:query="industryQuery" :company-name="companyName" :category="industryCategory" :categories="industryCategories" :options="visibleIndustryOptions" :hidden-count="filteredIndustryOptions.length - visibleIndustryOptions.length" :selected="pickedIndustryId" :selected-name="pickedIndustryName" :has-special-plan="Boolean(industryPackageModId(pickedIndustryId))" :busy="loading || companySaving" :login-required="loginRequired" @category="industryCategory = $event; industryExpanded = false" @select="pickIndustry" @custom="pickIndustry($event.trim()); industryQuery = ''" @expand="industryExpanded = true" @continue="confirmIndustryAndNext" @back="goStep('welcome')" />
        <OnboardingConfigurationStep v-else-if="currentStep === 'host-pack'" :company-name="companyName" :industry-name="pickedIndustryName" :labels="industrySidebarPreviewLabels" :deferred="isAttendanceOnboarding ? [] : industryNavigationProfile.deferredCapabilities" :has-special-plan="Boolean(industryPackageModId(pickedIndustryId))" :ready="baselineOk" :loading="loading" :busy="bootstrapBusy || finishing || companySaving" :missing-count="missingSidebarBaselineCount || missingRequiredCount" :attendance="isAttendanceOnboarding" :login-required="loginRequired" :groups="hostPackDetailGroups" @create="createWorkspace" @back="goStep('industry')" @refresh="refreshStatus" @example="goStep(isAttendanceOnboarding ? 'first-ai-task' : 'seed-demo')" />

        <template v-else-if="isAttendanceOnboarding && ['seed-demo', 'first-ai-task'].includes(currentStep)">
          <h1>先到考勤工作区确认名单</h1>
          <p class="lead">请先确认部门和人员名单，再开始考勤查询。这里不会自动添加演示人员或修改您的现有名单。</p>
          <ul class="flow-list bullets">
            <li><strong>已有名单</strong>：在人员管理中查询一位员工，核对姓名、工号和所属部门。</li>
            <li><strong>尚无名单</strong>：先在部门管理中录入部门，再录入人员；完成后重新查询核对。</li>
            <li><strong>考勤表转换</strong>：属于按账号开通的定制功能；未开通时仍可准备部门和人员名单。</li>
          </ul>
          <div class="status-card warn" role="status">名单尚待您在考勤工作区确认。打开工作区不会将人员查询记为完成。</div>
          <div class="actions">
            <button type="button" class="btn primary" @click="openAttendanceWorkspace">打开考勤工作区</button>
            <button type="button" class="btn ghost" @click="goStep('host-pack')">重新检测考勤功能</button>
          </div>
        </template>

        <template v-else-if="currentStep === 'seed-demo'">
          <h1>先给您一套可以动手的数据</h1>
          <p class="lead">系统会为 <strong>{{ pickedIndustryName }}</strong> 创建一个演示客户和一个演示商品；重复点击不会重复创建，也不会覆盖您的真实数据。</p>
          <div class="status-card ok">
            <i class="fa fa-database"></i>
            演示数据带有明确名称，体验结束后可以自行删除。
          </div>
          <div class="actions">
            <button type="button" class="btn primary" :disabled="seedBusy" @click="prepareDemoData">
              <i class="fa" :class="seedBusy ? 'fa-spinner fa-spin' : 'fa-magic'"></i>
              {{ seedBusy ? '正在准备…' : '一键准备演示数据' }}
            </button>
          </div>
        </template>

        <template v-else-if="currentStep === 'first-ai-task'">
          <h1>跟着 AI 员工完成第一单</h1>
          <p class="lead">AI 会依次查询演示客户和商品，展示执行计划，等待您确认后创建演示出货单。完成后请核对业务记录中的客户、商品和数量。</p>
          <pre class="first-task-prompt">{{ firstOrderPrompt }}</pre>
          <div class="actions">
            <button type="button" class="btn primary" :disabled="finishing" @click="finishOnboardingComplete">
              <i class="fa" :class="finishing ? 'fa-spinner fa-spin' : 'fa-play'"></i>
              {{ finishing ? '正在打开智能对话…' : '跟 AI 员工做第一单' }}
            </button>
          </div>
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
        <button v-else type="button" class="btn text" @click="skipEntireFlow">先进入，稍后再设置</button>
        <span class="doc-hint">{{ footerHint }}</span>
      </footer>
    </div>
  </div>
</template>

<script setup>
// 入口 façade：状态/行为/导航拆分至 ./product-onboarding/，此处仅装配，行为与拆分前一致
import { onMounted, watch } from 'vue'
import OnboardingCompanyStep from './product-onboarding/OnboardingCompanyStep.vue'
import OnboardingIndustryStep from './product-onboarding/OnboardingIndustryStep.vue'
import OnboardingConfigurationStep from './product-onboarding/OnboardingConfigurationStep.vue'
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
  companyName, companySaving, industryQuery, industryCategory, industryExpanded, industryCategories, filteredIndustryOptions, visibleIndustryOptions, industryNavigationProfile,
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
  isAttendanceOnboarding,
  currentIndex,
  currentStepMeta,
  editionLabel,
  fromTutorial,
  returnPath,
  footerHint,
} = state

const { goStep, loginToContinue, returnFromTutorial, openModStore, openAttendanceWorkspace, finishToChat, skipEntireFlow } = nav
const { loginRequired, createWorkspace, refreshStatus, runBootstrap, prepareDemoData, pickIndustry, confirmIndustryAndNext, finishOnboardingComplete } = actions

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
  pickedIndustryId.value = normalizePickedIndustryId(route.query.industry || onboardingCatalog.value?.selected_industry_id || cur)
  const expectedQuery = { ...route.query, step: currentStep.value }
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

<style src="./product-onboarding/product-onboarding.css"></style>
