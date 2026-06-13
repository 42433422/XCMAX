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
            <img
              class="welcome-logo"
              :src="welcomeLogoSrc"
              height="56"
              alt="XC"
              decoding="async"
              @error="onWelcomeLogoError"
            />
            <div>
              <h1>认识 XC</h1>
              <p class="welcome-tagline">专属于您的数字公司 · 默认干净，对话与生态先行</p>
              <p class="lead">
                日常界面只保留<strong>智能对话</strong>和<strong>智能生态</strong>；其它菜单、行业 Mod、AI 员工都按需加载。先把 XC 当成会长大的公司，用到哪再补哪。
              </p>
            </div>
          </div>
          <ul class="flow-list bullets">
            <li><strong>干净起步</strong>：侧栏默认只有智能对话、智能生态，不堆满菜单</li>
            <li><strong>先定行业</strong>：选好方向后，再告诉您还要补哪些基础 Mod</li>
            <li><strong>AI 员工</strong>：住在 Mod 里，按需唤醒，开口交代即可</li>
          </ul>
          <div class="actions">
            <button type="button" class="btn primary" @click="goStep('industry')">下一步：行业定型</button>
          </div>
        </template>

        <template v-else-if="currentStep === 'industry'">
          <h1>先定行业</h1>
          <p class="lead">
            当前开放
            <template v-for="(name, idx) in openIndustryLeadNames" :key="name">
              <strong>{{ name }}</strong><template v-if="idx < openIndustryLeadNames.length - 1"> 与 </template>
            </template>
            两套行业方向；选好后下一步会列出要补的基础线。
          </p>
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
          <p v-if="previewIndustryOptions.length" class="industry-preview-hint">更多行业（即将开放，暂不可选）</p>
          <div v-if="previewIndustryOptions.length" class="industry-pick industry-pick--preview" aria-hidden="true">
            <div
              v-for="preset in previewIndustryOptions"
              :key="preset.id"
              class="industry-chip industry-chip--locked"
            >
              <span class="industry-chip-name">{{ preset.name }}</span>
              <span class="industry-chip-product industry-chip-product--locked">即将开放</span>
              <span class="industry-chip-scenario">{{ chipScenarioText(preset.scenario) }}</span>
            </div>
          </div>
          <div class="actions">
            <button type="button" class="btn primary" @click="confirmIndustryAndNext">
              下一步：看要补哪些基础线
            </button>
            <button type="button" class="btn ghost" @click="openModStore">打开扩展市场</button>
            <button type="button" class="btn link" @click="finishToChat">先跳过，直接用对话</button>
          </div>
        </template>

        <template v-else-if="currentStep === 'host-pack'">
          <h1>补基础线（按需）</h1>
          <p v-if="baselinePlan?.summary" class="lead">{{ baselinePlan.summary }}</p>
          <p v-else class="lead">
            您选了<strong>{{ pickedIndustryName }}</strong>。下面按行业列出建议补装项，可一键装齐，也可以先进入对话。
          </p>
          <div
            class="status-card"
            :class="{ ok: baselineOk && !loading, warn: !baselineOk && !loading }"
          >
            <template v-if="loading">
              <i class="fa fa-spinner fa-spin"></i> 正在检测…
            </template>
            <template v-else-if="baselineOk">
              <i class="fa fa-check-circle"></i> 本行业推荐基础线已齐，可以开始使用了。
            </template>
            <template v-else>
              <i class="fa fa-exclamation-circle"></i>
              还缺 {{ missingRequiredCount }} 项必需基础线
              <span v-if="missingAccountCustomCount > 0">
                （另 {{ missingAccountCustomCount }} 项账号定制 Mod 待安装）
              </span>
              <span v-else-if="missingIndustryPackageCount > 0">
                （另 {{ missingIndustryPackageCount }} 项行业包可选安装）
              </span>
            </template>
          </div>
          <p
            v-if="showNoAccountCustomHint"
            class="account-custom-empty-hint muted"
          >
            当前账号未绑定定制 Mod，可联系管理员或在扩展市场购买。
          </p>
          <div v-if="baselineGroups.length" class="baseline-groups">
            <section v-for="group in baselineGroups" :key="group.id" class="baseline-group">
              <h3>{{ group.title }}</h3>
              <p class="baseline-group-hint">{{ group.hint }}</p>
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
                  <span v-if="!item.installed && item.show_mod_id !== false" class="mono">{{ item.mod_id }}</span>
                </li>
              </ul>
            </section>
          </div>
          <div class="actions">
            <button type="button" class="btn primary" :disabled="bootstrapBusy" @click="runBootstrap">
              <i class="fa" :class="bootstrapBusy ? 'fa-spinner fa-spin' : 'fa-download'"></i>
              一键装齐本行业推荐项
            </button>
            <button type="button" class="btn ghost" :disabled="loading" @click="refreshStatus">重新检测</button>
            <button v-if="baselineOk" type="button" class="btn primary" @click="finishToChat">
              进入智能对话
            </button>
            <button type="button" class="btn link" @click="finishToChat">先进入对话，稍后再补</button>
          </div>
        </template>

        <template v-else>
          <h1>可以开始使用</h1>
          <p class="lead">可从智能对话或扩展市场开始。</p>
          <div class="actions">
            <button type="button" class="btn primary" @click="finishToChat">进入智能对话</button>
          </div>
        </template>
      </section>

      <footer class="product-flow-footer">
        <button v-if="fromTutorial" type="button" class="btn text" @click="returnFromTutorial">
          返回上一页
        </button>
        <button v-else type="button" class="btn text" @click="skipEntireFlow">跳过引导（高级用户）</button>
        <span class="doc-hint">{{ footerHint }}</span>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { installHostFoundation, installMod, installOfficeEmployeePack, installIndustrySeed } from '@/api/modStore'
import { readBuildEdition } from '@/constants/genericModPack'
import { fetchProductSku, isEnterpriseEdition } from '@/utils/productSku'
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults'
import { getIndustryPreset, listIndustryPresets } from '@/constants/industryPresets'
import {
  PRODUCT_FLOW_STEPS,
  defaultOnboardingIndustryId,
  isOnboardingIndustryOpen,
  isTutorialReplayQuery,
  parseFlowStepQuery,
  readOnboardingReturnPath,
  readProductFlowCompleted,
  setRuntimeOnboardingOpenIndustryIds,
} from '@/constants/productFlow'
import { useProductFlow } from '@/composables/useProductFlow'
import { useIndustryStore } from '@/stores/industry'
import {
  clearDeliverableStatusCache,
  fetchIndustryBaseline,
  fetchOnboardingIndustryCatalog,
} from '@/utils/platformShellApi'
import { appAlert } from '@/utils/appDialog'
import {
  promptAdvancedTutorialAfterInstall,
  resolveRouteNameFromPath,
} from '@/tutorial/promptAdvancedTutorial'
import { useTutorialCatalog } from '@/composables/useTutorialCatalog'
import {
  invalidateHostPackCompletionCache,
  markHostPackSkippedThisSession,
} from '@/utils/hostPackOnboardingGate'

const route = useRoute()
const router = useRouter()
const flow = useProductFlow()
const industryStore = useIndustryStore()
const { buildContext: tutorialBuildContext } = useTutorialCatalog()

const industryOptions = listIndustryPresets()
const onboardingCatalog = ref(null)

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
  return industryOptions
    .filter((p) => isOnboardingIndustryOpen(p.id))
    .map((p) => ({ id: p.id, name: p.name, scenario: p.scenario, productName: '' }))
})

const previewIndustryOptions = computed(() => {
  const previewPkgs = onboardingCatalog.value?.preview_packages
  if (Array.isArray(previewPkgs) && previewPkgs.length) {
    return previewPkgs.map(catalogChipRow)
  }
  return industryOptions
    .filter((p) => !isOnboardingIndustryOpen(p.id))
    .map((p) => ({ id: p.id, name: p.name, scenario: p.scenario, productName: '' }))
})

const openIndustryLeadNames = computed(() => {
  const ids = onboardingCatalog.value?.open_industry_ids
  if (Array.isArray(ids) && ids.length) return ids
  return openIndustryOptions.value.map((p) => p.id)
})
const pickedIndustryId = ref(resolveDefaultPickedIndustryId())

function industryPackageLabel(industryId) {
  const id = String(industryId || '').trim()
  const row = onboardingCatalog.value?.open_packages?.find((p) => p.industry_id === id)
  if (row?.product_name) return row.product_name
  const chip = openIndustryOptions.value.find((p) => p.id === id)
  if (chip?.productName) return chip.productName
  const preset = getIndustryPreset(id)
  return preset?.name ? `${preset.name}行业包` : ''
}

/** 行业 chip 第三行：去掉句末句号，避免行高不齐 */
function chipScenarioText(text) {
  return String(text || '').replace(/[。．]$/, '')
}

function isIndustrySelectable(id) {
  const key = String(id || '').trim()
  if (!key) return false
  const openIds = onboardingCatalog.value?.open_industry_ids
  if (Array.isArray(openIds)) {
    return openIds.includes(key)
  }
  return isOnboardingIndustryOpen(key)
}

function resolveDefaultPickedIndustryId() {
  const selected = String(onboardingCatalog.value?.selected_industry_id || '').trim()
  if (selected && isIndustrySelectable(selected)) return selected
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
const baselinePlan = ref(null)

function startupAsset(fileName) {
  const base = String(import.meta.env.BASE_URL || '/')
  return `${base}startup/${fileName}`.replace(/([^:]\/)\/+/g, '$1')
}

/** 与侧栏 / 开屏同源：带 XC 字标；PNG 透明底 */
const welcomeLogoCandidates = [
  startupAsset('xc-logo-text.png'),
  startupAsset('xc-logo-text.jpg'),
  startupAsset('xc-logo-base.jpg'),
]
const welcomeLogoSrc = ref(welcomeLogoCandidates[0])
let welcomeLogoFallbackIndex = 0

function onWelcomeLogoError() {
  welcomeLogoFallbackIndex += 1
  if (welcomeLogoFallbackIndex < welcomeLogoCandidates.length) {
    welcomeLogoSrc.value = welcomeLogoCandidates[welcomeLogoFallbackIndex]
  }
}

const productSku = ref('generic')
const baselineOk = computed(() => baselinePlan.value?.baseline_ready === true)
const baselineGroups = computed(() => baselinePlan.value?.groups || [])
const missingRequiredCount = computed(
  () => baselinePlan.value?.missing_required_mod_ids?.length || 0,
)
const missingAccountCustomCount = computed(
  () => baselinePlan.value?.missing_account_custom_mod_ids?.length || 0,
)
const missingIndustryPackageCount = computed(() => {
  const ids = new Set(baselinePlan.value?.industry_mod_ids || [])
  return (baselinePlan.value?.missing_industry_mod_ids || []).filter((id) => ids.has(id)).length
})
const hasAccountCustomEntitlement = computed(
  () => (baselinePlan.value?.account_custom_mod_ids?.length || 0) > 0,
)
const showNoAccountCustomHint = computed(
  () =>
    isEnterpriseEdition(productSku.value) &&
    currentStep.value === 'host-pack' &&
    !loading.value &&
    !hasAccountCustomEntitlement.value,
)
const pickedIndustryName = computed(() => getIndustryPreset(pickedIndustryId.value).name)

const currentIndex = computed(() => {
  const row = steps.find((s) => s.id === currentStep.value)
  return row?.index ?? 1
})

const currentStepMeta = computed(() => steps.find((s) => s.id === currentStep.value) || null)

const editionLabel = computed(() => {
  const e = readBuildEdition()
  if (e === 'minimal') return '空壳 minimal'
  if (e === 'generic') return '通用 generic'
  return '完整 full'
})

const fromTutorial = computed(() => isTutorialReplayQuery(route.query.from))
const returnPath = computed(() => readOnboardingReturnPath(route.query.redirect))
const footerHint = computed(() =>
  fromTutorial.value
    ? '来自新手教程 · 可随时返回继续日常使用'
    : '完整流程见 docs/guides/PRODUCT_USER_FLOW.md',
)

watch(
  () => route.query.step,
  (q) => {
    currentStep.value = parseFlowStepQuery(q)
  },
)

watch(currentStep, (step) => {
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

    const officeResult = await installOfficeEmployeePack({
      onProgress: (msg) => {
        console.info('[ProductOnboarding]', msg)
      },
    })
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
        installErrors.push(
          `行业包：${err instanceof Error ? err.message : '安装失败'}`,
        )
      }
    }
    for (const modId of customMissing) {
      try {
        const ir = await installMod(modId)
        if (!ir.success) {
          installErrors.push(`${modId}：${ir.message || '安装失败'}`)
        }
      } catch (err) {
        installErrors.push(
          `${modId}：${err instanceof Error ? err.message : '安装失败'}`,
        )
      }
    }
    await refreshBaseline(true)

    if (baselineOk.value) {
      invalidateHostPackCompletionCache()
      flow.markHostPackAcknowledged()
      if (!readProductFlowCompleted()) {
        flow.markProductFlowCompleted()
      }
      const promptResult = await promptAdvancedTutorialAfterInstall({
        router,
        buildContext: tutorialBuildContext.value,
        message:
          '本行业推荐基础线已装齐，可以开始使用了。\n\n是否现在观看进阶教程，快速熟悉菜单与智能对话？',
        returnContext: { routeName: 'chat' },
      })
      if (promptResult === 'already_completed') {
        await appAlert('本行业推荐基础线已装齐，可以开始使用了。')
      }
      return
    }

    const requiredMissing = baselinePlan.value?.missing_required_mod_ids || []
    const detailParts = []
    if (!res.success) {
      detailParts.push(res.message || '宿主基础线装包未完成')
    }
    if (requiredMissing.length) {
      detailParts.push(`仍缺必需项：${requiredMissing.join('、')}`)
    }
    if (installErrors.length) {
      detailParts.push(installErrors.join('；'))
    }
    if (!officeResult.success && officeResult.errors.length) {
      detailParts.push(`办公员工包：${officeResult.errors.slice(0, 3).join('；')}`)
    }
    await appAlert(detailParts.join('\n') || '部分项目未装齐，可稍后在扩展市场继续安装。')
  } catch (err) {
    await appAlert(err instanceof Error ? err.message : '装包失败')
  } finally {
    bootstrapBusy.value = false
  }
}

function pickIndustry(id) {
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
  const id = pickedIndustryId.value
  if (industryStore.isLoaded && id !== industryStore.currentIndustryId) {
    await industryStore.switchIndustry(id)
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

function openModStore() {
  if (!fromTutorial.value || !readProductFlowCompleted()) {
    flow.markProductFlowCompleted()
  }
  void router.push({
    name: 'mod-store',
    query: fromTutorial.value ? {} : { onboarding: '1' },
  })
}

function finishHostPackFlow() {
  invalidateHostPackCompletionCache()
  if (baselineOk.value) {
    if (!readProductFlowCompleted()) {
      flow.markProductFlowCompleted()
      flow.markHostPackAcknowledged()
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
  try {
    productSku.value = await fetchProductSku()
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
  pickedIndustryId.value = normalizePickedIndustryId(
    onboardingCatalog.value?.selected_industry_id || cur,
  )
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
  transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
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
</style>
