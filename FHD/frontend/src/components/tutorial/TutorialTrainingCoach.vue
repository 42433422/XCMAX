<template>
  <Teleport to="body">
    <div v-if="run" class="tutorial-coach-shell" :class="{ 'is-paused': run.status === 'paused' }">
      <div class="tutorial-space-banner" role="status">
        <strong>{{ run.status === 'paused' ? '练习已保存' : '教学空间' }}</strong>
        <span v-if="run.status === 'paused'">正式数据不会受影响，随时可以继续</span>
        <span v-else-if="run.status === 'completed'">这门课已经完成，可以回来查看学习成果</span>
        <span v-else>这里的练习不会改动你公司的正式数据</span>
        <span>已完成 {{ run.completed_steps }} / {{ run.total_steps }} 步</span>
      </div>
      <aside
        class="tutorial-coach"
        :class="[
          `is-${coachSide}`,
          { 'is-collapsed': collapsed, 'is-guide-mode': operationStarted },
        ]"
        aria-label="实训教练"
      >
        <header>
          <div>
            <span class="tutorial-coach__eyebrow">新手教练</span>
            <strong>{{ courseTitle }}</strong>
          </div>
          <div class="tutorial-coach__window-actions">
            <button
              v-if="!operationStarted"
              type="button"
              class="tutorial-coach__collapse"
              @click="toggleSide"
            >
              {{ coachSide === 'right' ? '移到左侧' : '移到右侧' }}
            </button>
            <button type="button" class="tutorial-coach__collapse" @click="collapsed = !collapsed">
              {{ collapsed ? '展开教练' : '收起' }}
            </button>
          </div>
        </header>

        <template v-if="!collapsed && step && run.status !== 'paused' && run.status !== 'completed'">
          <div class="tutorial-coach__step">
            第 {{ currentIndex + 1 }} / {{ run.total_steps }} 步 · {{ step.title }}
          </div>

          <section class="tutorial-coach__focus" aria-live="polite">
            <span>{{ operationStarted ? `照着做 · ${guideIndex + 1} / ${guideActions.length}` : '现在只做这一件事' }}</span>
            <strong>{{ operationStarted ? currentAction.instruction : step.goal }}</strong>
            <p v-if="!operationStarted">{{ step.instruction }}</p>
            <p class="tutorial-coach__location">
              <span>位置</span>{{ step.location_label || '当前业务页面' }}
            </p>
            <div v-if="operationStarted && currentAction.expected_input" class="tutorial-coach__input">
              <span>请准确输入</span>
              <code>{{ currentAction.expected_input }}</code>
              <button type="button" @click="copyExpectedInput">{{ copyHint || '复制' }}</button>
            </div>
          </section>

          <section class="tutorial-coach__cue">
            <span>完成后你会看到</span>
            <p>{{ step.completion_cue || step.success_criteria }}</p>
          </section>

          <p v-if="store.verificationHint" class="tutorial-coach__result" :data-status="step.status">
            {{ store.verificationHint }}
          </p>
          <div v-if="step.status === 'failed'" class="tutorial-coach__diagnosis">
            <strong>还差一点</strong>
            <p>{{ step.hint }}</p>
            <ul><li v-for="item in evidenceItems" :key="item">{{ item }}</li></ul>
          </div>

          <div class="tutorial-coach__actions">
            <button
              v-if="!operationStarted"
              type="button"
              class="btn btn-primary btn-sm"
              @click="goOperate"
            >
              打开操作页面
            </button>
            <template v-else>
              <button
                v-if="guideIndex > 0"
                type="button"
                class="btn btn-secondary btn-sm"
                @click="previousGuide"
              >
                上一条
              </button>
              <button type="button" class="btn btn-secondary btn-sm" @click="locateCurrentTarget">
                指给我看
              </button>
              <button
                v-if="guideIndex < guideActions.length - 1"
                type="button"
                class="btn btn-primary btn-sm"
                @click="nextGuide"
              >
                我做完了，下一条
              </button>
              <button
                v-else
                type="button"
                class="btn btn-primary btn-sm"
                :disabled="store.verifying"
                @click="verify"
              >
                {{ store.verifying ? '正在检查…' : '我做完了，检查一下' }}
              </button>
            </template>
            <button type="button" class="btn btn-secondary btn-sm" @click="leave">
              保存并退出
            </button>
          </div>

          <a
            v-if="step.id === 'import-preview'"
            class="tutorial-coach__asset"
            :href="tutorialAssetUrl"
            download
          >下载内置教学 Excel</a>

          <details class="tutorial-coach__more">
            <summary>想知道为什么？</summary>
            <p>{{ step.why }}</p>
            <p v-if="step.principle">以后遇到类似情况：{{ step.principle }}</p>
          </details>
          <details class="tutorial-coach__more">
            <summary>系统会检查什么？</summary>
            <p>{{ step.success_criteria }}</p>
            <ul v-if="step.evidence" class="tutorial-coach__evidence-list">
              <li v-for="item in evidenceItems" :key="item">{{ item }}</li>
            </ul>
          </details>
        </template>

        <div v-else-if="!collapsed && run.status === 'completed'" class="tutorial-coach__complete">
          <strong>做得好，这门课已经完成。</strong>
          <span>你可以打开任一步查看学习成果，也可以返回课程目录继续下一门。</span>
          <ul class="tutorial-coach__review-list">
            <li v-for="item in run.steps" :key="item.id">
              <button type="button" @click="reviewStep(item)">{{ item.title }}</button>
              <span>{{ resultCodeLabel(item.evidence?.result_code) }}</span>
            </li>
          </ul>
          <button type="button" class="btn btn-secondary btn-sm" @click="leave">返回课程目录</button>
        </div>
        <div v-else-if="!collapsed && run.status === 'paused'" class="tutorial-coach__paused">
          <span>上次做到的位置已经保存。</span>
          <button type="button" class="btn btn-primary btn-sm" @click="resume">继续当前步骤</button>
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { useTutorialV2Store } from '@/stores/tutorialV2'
import { buildFullApiUrl } from '@/api/core'
import type { TutorialGuideActionDTO, TutorialStepDTO } from '@/api/tutorialV2'

const store = useTutorialV2Store()
const { currentRun: run, currentStep: step } = storeToRefs(store)
const router = useRouter()
const route = useRoute()
const collapsed = ref(false)
const coachSide = ref<'left' | 'right'>('right')
const operationStarted = ref(false)
const guideIndex = ref(0)
const copyHint = ref('')
const tutorialAssetUrl = buildFullApiUrl('/api/tutorial/v2/assets/business-import.xlsx')
let highlighted: Element | null = null
let targetObserver: MutationObserver | null = null
let copyHintTimer: number | null = null

const courseTitle = computed(() => store.courses.find((course) => course.id === run.value?.course_id)?.title || '进阶实训')
const currentIndex = computed(() => run.value?.steps.findIndex((item) => item.id === step.value?.id) ?? 0)
const guideActions = computed<TutorialGuideActionDTO[]>(() => {
  if (step.value?.guide_actions?.length) return step.value.guide_actions
  const fallback = step.value?.action_checklist || []
  return fallback.length
    ? fallback.map((instruction) => ({ instruction, target_selector: '', expected_input: '' }))
    : [{
        instruction: step.value?.instruction || '按照页面提示完成操作。',
        target_selector: step.value?.target_selector || '',
        expected_input: '',
      }]
})
const currentAction = computed(() => guideActions.value[Math.min(guideIndex.value, guideActions.value.length - 1)])

const countLabels: Record<string, string> = {
  completed_task_count: '已完成任务', execution_count: '执行记录', queue_execution_count: '后台执行',
  observed_execution_count: '对话执行', run_count: '运行次数', result_viewed: '结果已查看',
  distinct_readonly_task_count: '不同查询任务', customer_query_count: '客户查询',
  product_query_count: '产品查询', viewed_result_count: '已查看结果', customer_count: '客户数量',
  product_count: '产品数量', price: '价格', inventory: '当前库存', pending_approval_count: '待审批申请',
  approval_detail_opened: '审批详情已打开', sales_order_count: '销售订单',
  sales_order_item_count: '订单明细', allocation_count: '收款对应记录', journal_entry_count: '记账凭证',
  invoice_voucher_count: '开票凭证', payment_voucher_count: '收款凭证',
  balanced_journal_entry_count: '平衡凭证', order_total: '订单金额', allocated_amount: '对应收款金额',
  invoice_status: '发票状态', payment_state: '收款状态', preview_run_count: '预览任务',
  preview_row_count: '预览行', completed_run_count: '完成导入', successful_row_count: '成功行',
  referenced_row_count: '已写入行', error_row_count: '错误行', sales_task_count: '销售任务',
  approved_request_count: '已批准申请',
}
const entityLabels: Record<string, string> = {
  agent_task: '任务', customer: '客户', product: '产品', approval_request: '审批申请',
  sales_order: '销售订单', sales_order_item: '订单明细', receivable_allocation: '收款对应记录',
  journal_entry: '记账凭证', etl_run: '导入任务',
}
const valueLabels: Record<string, string> = {
  invoiced: '已开票', paid: '已收款', pending: '待处理', approved: '已通过',
}
const evidenceItems = computed(() => {
  const evidence = step.value?.evidence
  if (!evidence) return ['还没有检查']
  const counts = Object.entries(evidence.counts).map(([key, value]) => {
    const display = valueLabels[String(value)] || (value === 1 && key.endsWith('_opened') ? '是' : value)
    return `${countLabels[key] || '检查项'}：${display}`
  })
  const refs = evidence.entity_refs.map((item) => `${entityLabels[item.type] || '业务记录'} #${item.id}`)
  return [...counts, ...refs].length ? [...counts, ...refs] : [resultCodeLabel(evidence.result_code)]
})

function resultCodeLabel(code?: string) {
  if (!code || code === 'verification_passed') return '已检查通过'
  return '还没有达到要求'
}

function clearHighlight() {
  highlighted?.classList.remove('xcagi-tutorial-target-highlight')
  highlighted = null
  targetObserver?.disconnect()
  targetObserver = null
}

function activeSelector() {
  return currentAction.value?.target_selector || step.value?.target_selector || ''
}

function selectAndHighlightTarget() {
  clearHighlight()
  const selector = activeSelector()
  try {
    highlighted = selector ? document.querySelector(selector) : null
  } catch {
    highlighted = null
  }
  if (!highlighted) return false
  highlighted.classList.add('xcagi-tutorial-target-highlight')
  highlighted.scrollIntoView?.({ block: 'center', inline: 'nearest', behavior: 'smooth' })
  return true
}

function watchForTarget() {
  clearHighlight()
  if (selectAndHighlightTarget()) return
  targetObserver = new MutationObserver(() => {
    if (selectAndHighlightTarget()) targetObserver?.disconnect()
  })
  targetObserver.observe(document.body, { childList: true, subtree: true })
}

function toggleSide() {
  coachSide.value = coachSide.value === 'right' ? 'left' : 'right'
}

function navigationTarget(item: TutorialStepDTO) {
  if (item.route_name !== 'approval-workspace') return { name: item.route_name }
  const approvalRef = item.evidence?.entity_refs.find((ref) => ref.type === 'approval_request')
    || run.value?.steps.flatMap((runStep) => runStep.evidence?.entity_refs || [])
      .find((ref) => ref.type === 'approval_request')
    || store.courses.flatMap((course) => course.run?.steps || [])
      .flatMap((runStep) => runStep.evidence?.entity_refs || [])
      .find((ref) => ref.type === 'approval_request')
  return approvalRef
    ? { name: item.route_name, query: { request_id: String(approvalRef.id) } }
    : { name: item.route_name }
}

async function goOperate() {
  if (!step.value || !run.value) return
  if (run.value.status === 'paused') await store.enterRun(run.value.id)
  await router.push(navigationTarget(step.value)).catch(() => undefined)
  store.markTargetVisited()
  operationStarted.value = true
  collapsed.value = false
  guideIndex.value = 0
  await nextTick()
  window.setTimeout(watchForTarget, 80)
}

async function locateCurrentTarget() {
  await nextTick()
  watchForTarget()
}

async function moveGuide(offset: number) {
  guideIndex.value = Math.max(0, Math.min(guideActions.value.length - 1, guideIndex.value + offset))
  copyHint.value = ''
  await nextTick()
  window.setTimeout(watchForTarget, 40)
}

async function previousGuide() {
  await moveGuide(-1)
}

async function nextGuide() {
  await moveGuide(1)
}

async function copyExpectedInput() {
  const value = currentAction.value?.expected_input || ''
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    copyHint.value = '已复制'
  } catch {
    copyHint.value = '请手动复制'
  }
  if (copyHintTimer !== null) window.clearTimeout(copyHintTimer)
  copyHintTimer = window.setTimeout(() => { copyHint.value = '' }, 1800)
}

async function verify() {
  const selector = activeSelector()
  let targetVisible = false
  try { targetVisible = Boolean(selector && document.querySelector(selector)) } catch { targetVisible = false }
  const result = await store.verifyCurrent(String(route.name || ''), targetVisible)
  if (result?.evidence.status === 'passed') clearHighlight()
}

async function leave() {
  clearHighlight()
  operationStarted.value = false
  await store.leaveCurrent()
  if (!store.currentRun) {
    await router.push({ name: 'chat' }).catch(() => undefined)
  }
}

async function resume() {
  if (!run.value) return
  await store.enterRun(run.value.id)
  await goOperate()
}

async function reviewStep(item: TutorialStepDTO) {
  await router.push(navigationTarget(item)).catch(() => undefined)
}

function resetGuide() {
  clearHighlight()
  operationStarted.value = false
  guideIndex.value = 0
  copyHint.value = ''
}

onMounted(() => {
  void store.loadCourses().catch(() => undefined)
  void store.restoreCurrent()
})
watch(() => step.value?.id, resetGuide)
onBeforeUnmount(() => {
  clearHighlight()
  if (copyHintTimer !== null) window.clearTimeout(copyHintTimer)
})
</script>

<style>
.tutorial-coach-shell { position: fixed; inset: 0; pointer-events: none; z-index: 10100; }
.tutorial-space-banner { pointer-events: auto; position: fixed; top: 0; left: 50%; transform: translateX(-50%); display: flex; gap: 12px; align-items: center; padding: 7px 16px; border: 1px solid #e6b64f; border-top: 0; border-radius: 0 0 12px 12px; background: #fff4d6; color: #6e4100; box-shadow: 0 4px 18px rgba(76, 49, 5, .16); z-index: 2; }
.tutorial-coach { pointer-events: auto; position: fixed; bottom: 20px; width: min(390px, calc(100vw - 32px)); max-height: calc(100vh - 92px); overflow: auto; border: 1px solid #cbd9e4; border-radius: 16px; padding: 14px; background: rgba(255, 255, 255, .98); box-shadow: 0 18px 50px rgba(25, 47, 66, .24); }
.tutorial-coach.is-right { right: 20px; }
.tutorial-coach.is-left { left: 20px; }
.tutorial-coach.is-guide-mode { top: 52px; bottom: auto; left: 50%; right: auto; transform: translateX(-50%); width: min(560px, calc(100vw - 32px)); max-height: min(520px, calc(100vh - 70px)); }
.tutorial-coach.is-collapsed { top: 52px; bottom: auto; max-height: none; }
.tutorial-coach header { display: flex; justify-content: space-between; gap: 12px; }
.tutorial-coach header > div { display: grid; }
.tutorial-coach__eyebrow { color: #2678ad; font-size: 12px; font-weight: 700; }
.tutorial-coach__collapse { border: 0; background: transparent; color: #4e6f86; cursor: pointer; }
.tutorial-coach__window-actions { display: flex; align-items: flex-start; gap: 4px; }
.tutorial-coach__step { margin-top: 10px; padding: 7px 9px; border-radius: 8px; background: #edf6fc; color: #205f87; font-weight: 700; }
.tutorial-coach__focus { display: grid; gap: 8px; margin-top: 10px; padding: 12px; border: 2px solid #52a6da; border-radius: 12px; background: #f5fbff; }
.tutorial-coach__focus > span, .tutorial-coach__cue > span, .tutorial-coach__input > span { color: #2678ad; font-size: 12px; font-weight: 800; }
.tutorial-coach__focus > strong { color: #173d55; font-size: 16px; line-height: 1.45; }
.tutorial-coach__focus p, .tutorial-coach__cue p { margin: 0; color: #4f6270; line-height: 1.5; }
.tutorial-coach__location { display: flex; gap: 8px; align-items: center; padding-top: 6px; border-top: 1px solid #d9eaf4; }
.tutorial-coach__location span { padding: 2px 6px; border-radius: 999px; background: #dbeefa; color: #205f87; font-size: 11px; font-weight: 700; }
.tutorial-coach__input { display: grid; grid-template-columns: 1fr auto; gap: 6px 8px; align-items: center; padding: 9px; border-radius: 9px; background: #fff; border: 1px solid #cbd9e4; }
.tutorial-coach__input > span { grid-column: 1 / -1; }
.tutorial-coach__input code { overflow-wrap: anywhere; color: #153f58; font-family: inherit; font-size: 14px; font-weight: 700; }
.tutorial-coach__input button { border: 1px solid #9fc7df; border-radius: 7px; padding: 4px 8px; background: #edf7fd; color: #205f87; cursor: pointer; }
.tutorial-coach__cue { margin: 9px 0; padding: 9px 11px; border-left: 4px solid #36a56f; border-radius: 8px; background: #f0faf5; }
.tutorial-coach__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.tutorial-coach__result { padding: 8px 9px; border-radius: 8px; background: #fff7dd; color: #755b16; }
.tutorial-coach__result[data-status='passed'] { background: #e9f8f0; color: #146541; }
.tutorial-coach__diagnosis { display: grid; gap: 5px; padding: 10px; margin: 8px 0; border-radius: 9px; background: #fff4ed; color: #7c3d1c; }
.tutorial-coach__diagnosis p, .tutorial-coach__diagnosis ul { margin: 0; }
.tutorial-coach__diagnosis ul, .tutorial-coach__evidence-list { padding-left: 18px; }
.tutorial-coach__asset { display: inline-block; margin-top: 10px; color: #1877ad; font-weight: 700; }
.tutorial-coach__more { margin-top: 9px; border-top: 1px solid #e3eaf0; padding-top: 8px; color: #5a6c7a; }
.tutorial-coach__more summary { cursor: pointer; color: #38566c; font-weight: 700; }
.tutorial-coach__more p { margin: 7px 0 0; line-height: 1.5; }
.tutorial-coach__paused, .tutorial-coach__complete { margin-top: 12px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.tutorial-coach__complete { align-items: stretch; flex-direction: column; }
.tutorial-coach__review-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; }
.tutorial-coach__review-list li { display: flex; justify-content: space-between; gap: 8px; color: #5f7180; font-size: 12px; }
.tutorial-coach__review-list button { border: 0; padding: 0; background: transparent; color: #1877ad; cursor: pointer; text-align: left; }
.xcagi-tutorial-target-highlight { position: relative !important; outline: 4px solid #f4b942 !important; outline-offset: 4px !important; box-shadow: 0 0 0 10px rgba(244, 185, 66, .22) !important; z-index: 4600 !important; }
@media (max-width: 720px) {
  .tutorial-space-banner { width: calc(100vw - 24px); justify-content: center; flex-wrap: wrap; gap: 5px 10px; font-size: 12px; }
  .tutorial-coach.is-right, .tutorial-coach.is-left, .tutorial-coach.is-guide-mode { left: 12px; right: 12px; bottom: 12px; top: auto; transform: none; width: calc(100vw - 24px); max-height: 58vh; }
}
</style>
