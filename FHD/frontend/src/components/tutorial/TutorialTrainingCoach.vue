<template>
  <Teleport to="body">
    <div v-if="run" class="tutorial-coach-shell" :class="{ 'is-paused': run.status === 'paused' }">
      <div class="tutorial-space-banner" role="status">
        <strong>{{ run.status === 'paused' ? '教学已保存' : '教学空间' }}</strong>
        <span v-if="run.status === 'paused'">当前未进入教学空间，请先返回当前步骤</span>
        <span v-else-if="run.status === 'completed'">复习模式只读；重置后才能重新操作</span>
        <span v-else>所有业务写入与正式企业数据隔离</span>
        <span>第 {{ run.generation }} 代 · {{ run.progress }}%</span>
      </div>
      <aside
        class="tutorial-coach"
        :class="[`is-${coachSide}`, { 'is-collapsed': collapsed }]"
        aria-label="实训教练"
      >
        <header>
          <div>
            <span class="tutorial-coach__eyebrow">实训教练</span>
            <strong>{{ courseTitle }}</strong>
          </div>
          <div class="tutorial-coach__window-actions">
            <button type="button" class="tutorial-coach__collapse" @click="toggleSide">
              {{ coachSide === 'right' ? '移到左侧' : '移到右侧' }}
            </button>
            <button type="button" class="tutorial-coach__collapse" @click="collapsed = !collapsed">
              {{ collapsed ? '展开' : '收起' }}
            </button>
          </div>
        </header>
        <template v-if="!collapsed && step && run.status !== 'paused' && run.status !== 'completed'">
          <div class="tutorial-coach__step">
            第 {{ currentIndex + 1 }} / {{ run.total_steps }} 步 · {{ step.title }}
          </div>
          <dl>
            <div><dt>目标</dt><dd>{{ step.goal }}</dd></div>
            <div><dt>你要做什么</dt><dd>{{ step.instruction }}</dd></div>
            <div v-if="step.action_checklist?.length">
              <dt>操作清单</dt>
              <dd>
                <ol class="tutorial-coach__checklist">
                  <li v-for="action in step.action_checklist" :key="action">{{ action }}</li>
                </ol>
              </dd>
            </div>
            <div><dt>成功标准</dt><dd>{{ step.success_criteria }}</dd></div>
            <div><dt>为什么</dt><dd>{{ step.why }}</dd></div>
            <div v-if="step.principle"><dt>可迁移方法</dt><dd>{{ step.principle }}</dd></div>
            <div><dt>提示</dt><dd>{{ step.hint }}</dd></div>
            <div v-if="step.evidence">
              <dt>结果证据</dt>
              <dd>
                <ul class="tutorial-coach__evidence-list">
                  <li v-for="item in evidenceItems" :key="item">{{ item }}</li>
                </ul>
              </dd>
            </div>
          </dl>
          <p v-if="store.verificationHint" class="tutorial-coach__result" :data-status="step.status">
            {{ store.verificationHint }}
          </p>
          <div v-if="step.status === 'failed'" class="tutorial-coach__diagnosis">
            <strong>系统检测</strong>
            <ul><li v-for="item in evidenceItems" :key="item">{{ item }}</li></ul>
            <strong>期望标准</strong>
            <p>{{ step.success_criteria }}</p>
            <strong>下一步</strong>
            <p>{{ step.hint }}</p>
          </div>
          <div class="tutorial-coach__actions">
            <button type="button" class="btn btn-primary btn-sm" @click="goOperate">去操作</button>
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="store.verifying"
              @click="verify"
            >
              {{ store.verifying ? '验证中…' : '验证结果' }}
            </button>
            <button type="button" class="btn btn-secondary btn-sm" @click="leave">
              保存退出
            </button>
          </div>
          <a
            v-if="step.id === 'import-preview'"
            class="tutorial-coach__asset"
            :href="tutorialAssetUrl"
            download
          >下载内置教学 Excel</a>
        </template>
        <div v-else-if="!collapsed && run.status === 'completed'" class="tutorial-coach__complete">
          <span>课程已完成。复习模式只读，可逐步返回业务页面查看证据。</span>
          <ul class="tutorial-coach__review-list">
            <li v-for="item in run.steps" :key="item.id">
              <button type="button" @click="reviewStep(item)">{{ item.title }}</button>
              <span>{{ resultCodeLabel(item.evidence?.result_code) }}</span>
            </li>
          </ul>
          <button type="button" class="btn btn-secondary btn-sm" @click="leave">退出教学</button>
        </div>
        <div v-else-if="!collapsed && run.status === 'paused'" class="tutorial-coach__paused">
          进度已保存。
          <button type="button" class="btn btn-primary btn-sm" @click="resume">返回当前步骤</button>
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
import type { TutorialStepDTO } from '@/api/tutorialV2'

const store = useTutorialV2Store()
const { currentRun: run, currentStep: step } = storeToRefs(store)
const router = useRouter()
const route = useRoute()
const collapsed = ref(false)
const coachSide = ref<'left' | 'right'>('right')
const tutorialAssetUrl = buildFullApiUrl('/api/tutorial/v2/assets/business-import.xlsx')
let highlighted: Element | null = null
let targetObserver: MutationObserver | null = null

const courseTitle = computed(() => store.courses.find((course) => course.id === run.value?.course_id)?.title || '进阶实训')
const currentIndex = computed(() => run.value?.steps.findIndex((item) => item.id === step.value?.id) ?? 0)
const countLabels: Record<string, string> = {
  completed_task_count: '已完成任务', execution_count: '执行证据', queue_execution_count: '后台执行',
  observed_execution_count: '对话执行', run_count: '运行次数', result_viewed: '结果已查看',
  distinct_readonly_task_count: '不同只读任务', customer_query_count: '客户查询',
  product_query_count: '产品查询', viewed_result_count: '已查看结果', customer_count: '客户数量',
  product_count: '产品数量', price: '价格', inventory: '当前库存', pending_approval_count: '待审批申请',
  approval_detail_opened: '审批详情已打开', sales_order_count: '销售订单',
  sales_order_item_count: '订单明细', allocation_count: '收款核销', journal_entry_count: '记账凭证',
  invoice_voucher_count: '开票凭证', payment_voucher_count: '收款凭证',
  balanced_journal_entry_count: '平衡凭证', order_total: '订单金额', allocated_amount: '核销金额',
  invoice_status: '发票状态', payment_state: '收款状态', preview_run_count: '预览任务',
  preview_row_count: '预览行', completed_run_count: '完成导入', successful_row_count: '成功行',
  referenced_row_count: '已关联实体行', error_row_count: '错误行', sales_task_count: '销售任务',
  approved_request_count: '已批准申请',
}
const entityLabels: Record<string, string> = {
  agent_task: '任务', customer: '客户', product: '产品', approval_request: '审批申请',
  sales_order: '销售订单', sales_order_item: '订单明细', receivable_allocation: '收款核销',
  journal_entry: '记账凭证', etl_run: '导入任务',
}
const valueLabels: Record<string, string> = {
  invoiced: '已开票', paid: '已收款', pending: '待处理', approved: '已通过',
}
const evidenceItems = computed(() => {
  const evidence = step.value?.evidence
  if (!evidence) return ['尚未验证']
  const counts = Object.entries(evidence.counts).map(([key, value]) => {
    const display = valueLabels[String(value)] || (value === 1 && key.endsWith('_opened') ? '是' : value)
    return `${countLabels[key] || '检测项'}：${display}`
  })
  const refs = evidence.entity_refs.map((item) => `${entityLabels[item.type] || '业务记录'} #${item.id}`)
  return [...counts, ...refs].length ? [...counts, ...refs] : [resultCodeLabel(evidence.result_code)]
})

function resultCodeLabel(code?: string) {
  if (!code || code === 'verification_passed') return '已验证通过'
  return '尚未达到成功标准'
}

function clearHighlight() {
  highlighted?.classList.remove('xcagi-tutorial-target-highlight')
  highlighted = null
  targetObserver?.disconnect()
  targetObserver = null
}

function selectAndHighlightTarget() {
  try {
    highlighted = document.querySelector(step.value?.target_selector || '')
  } catch {
    highlighted = null
  }
  if (!highlighted) return false
  highlighted.classList.add('xcagi-tutorial-target-highlight')
  const box = highlighted.getBoundingClientRect()
  const coachReserve = 420
  const spansBothCoachSides = box.left < coachReserve && box.right > window.innerWidth - coachReserve
  const tooWideToAvoid = box.width > window.innerWidth - coachReserve
  if (spansBothCoachSides || tooWideToAvoid) {
    // 聊天输入区等横跨页面的目标无法靠左右换位避让。进入操作态时自动收起教练，
    // 保留教学横幅和“展开”入口，避免挡住发送/确认按钮。
    collapsed.value = true
  } else if (box.left > window.innerWidth / 2) {
    coachSide.value = 'left'
  }
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
  await nextTick()
  window.setTimeout(watchForTarget, 80)
}

async function verify() {
  const selector = step.value?.target_selector || ''
  let targetVisible = false
  try { targetVisible = Boolean(selector && document.querySelector(selector)) } catch { targetVisible = false }
  const result = await store.verifyCurrent(String(route.name || ''), targetVisible)
  if (result?.evidence.status === 'passed') clearHighlight()
}

async function leave() {
  clearHighlight()
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

onMounted(() => {
  void store.loadCourses().catch(() => undefined)
  void store.restoreCurrent()
})
watch(() => step.value?.id, clearHighlight)
onBeforeUnmount(clearHighlight)
</script>

<style>
.tutorial-coach-shell { position: fixed; inset: 0; pointer-events: none; z-index: 10100; }
.tutorial-space-banner { pointer-events: auto; position: fixed; top: 0; left: 50%; transform: translateX(-50%); display: flex; gap: 12px; align-items: center; padding: 7px 16px; border: 1px solid #e6b64f; border-top: 0; border-radius: 0 0 12px 12px; background: #fff4d6; color: #6e4100; box-shadow: 0 4px 18px rgba(76, 49, 5, .16); }
.tutorial-coach { pointer-events: auto; position: fixed; bottom: 20px; width: min(370px, calc(100vw - 32px)); max-height: calc(100vh - 92px); overflow: auto; border: 1px solid #cbd9e4; border-radius: 16px; padding: 14px; background: rgba(255, 255, 255, .98); box-shadow: 0 18px 50px rgba(25, 47, 66, .24); }
.tutorial-coach.is-right { right: 20px; }
.tutorial-coach.is-left { left: 20px; }
.tutorial-coach.is-collapsed { top: 52px; bottom: auto; }
.tutorial-coach header { display: flex; justify-content: space-between; gap: 12px; }
.tutorial-coach header > div { display: grid; }
.tutorial-coach__eyebrow { color: #2678ad; font-size: 12px; font-weight: 700; }
.tutorial-coach__collapse { border: 0; background: transparent; color: #4e6f86; cursor: pointer; }
.tutorial-coach__window-actions { display: flex; align-items: flex-start; gap: 4px; }
.tutorial-coach__step { margin-top: 10px; padding: 7px 9px; border-radius: 8px; background: #edf6fc; color: #205f87; font-weight: 700; }
.tutorial-coach dl { margin: 10px 0; display: grid; gap: 8px; }
.tutorial-coach dl > div { display: grid; grid-template-columns: 78px 1fr; gap: 8px; }
.tutorial-coach dt { color: #38566c; font-weight: 700; }
.tutorial-coach dd { margin: 0; color: #4f6270; line-height: 1.45; }
.tutorial-coach__checklist, .tutorial-coach__evidence-list { margin: 0; padding-left: 18px; display: grid; gap: 3px; }
.tutorial-coach__diagnosis { display: grid; gap: 4px; padding: 9px; margin: 8px 0; border-radius: 9px; background: #fff4ed; color: #7c3d1c; }
.tutorial-coach__diagnosis ul { margin: 0; padding-left: 18px; }
.tutorial-coach__diagnosis p { margin: 0 0 4px; }
.tutorial-coach__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.tutorial-coach__result { padding: 8px 9px; border-radius: 8px; background: #f7f4e8; color: #755b16; }
.tutorial-coach__result[data-status='passed'] { background: #e9f8f0; color: #146541; }
.tutorial-coach__asset { display: inline-block; margin-top: 10px; color: #1877ad; font-weight: 600; }
.tutorial-coach__paused, .tutorial-coach__complete { margin-top: 12px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.tutorial-coach__complete { align-items: stretch; flex-direction: column; }
.tutorial-coach__review-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; }
.tutorial-coach__review-list li { display: flex; justify-content: space-between; gap: 8px; color: #5f7180; font-size: 12px; }
.tutorial-coach__review-list button { border: 0; padding: 0; background: transparent; color: #1877ad; cursor: pointer; text-align: left; }
.xcagi-tutorial-target-highlight { position: relative !important; outline: 4px solid #f4b942 !important; outline-offset: 4px !important; box-shadow: 0 0 0 10px rgba(244, 185, 66, .22) !important; z-index: 4600 !important; }
@media (max-width: 720px) {
  .tutorial-space-banner { width: calc(100vw - 24px); justify-content: center; flex-wrap: wrap; gap: 5px 10px; font-size: 12px; }
  .tutorial-coach.is-right, .tutorial-coach.is-left { left: 12px; right: 12px; bottom: 76px; width: calc(100vw - 24px); }
}
</style>
